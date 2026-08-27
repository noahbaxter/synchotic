"""Contract: how Google authorizes a Drive request, enforced against our client.

The rule, learned the hard way from a BYOC user whose every scan 400'd:

  key + token  -> 400 when the two are from different Cloud projects
  key + token  -> 200 when they share one (every non-BYOC user)
  token only   -> 200
  key only     -> 200 (anonymous, public folders)
  neither      -> 403 "unregistered callers"

Release builds bake an API key into sync.py; local builds do not. That gap
meant BYOC was only ever tested in the one configuration that cannot fail,
so these tests pin the rule instead of the request-shaping helper. They drive
the public methods, so a future caller that hand-rolls its own query string
fails here too.

The rule itself is verified against live Google by scripts/verify_auth_contract.py.
"""

import pytest
import requests

from src.drive.client import DriveClient, DriveClientConfig

KEY_PROJECT = "key-from-project-A"
TOKEN_PROJECT = "token-from-project-B"


class GoogleRuleViolation(Exception):
    """Raised in place of a real 400, so a failure names the actual cause."""


def _authorize(has_key: bool, has_token: bool):
    """Apply Google's rule. Returns nothing; raises to mimic an error status."""
    if has_key and has_token:
        raise GoogleRuleViolation(
            "The API Key and the authentication credential are from different projects."
        )
    if not has_key and not has_token:
        err = requests.exceptions.HTTPError("403 unregistered caller")
        err.response = type("R", (), {"status_code": 403})()
        raise err


class FakeGoogle:
    """Stands in for the Drive endpoint, recording what it was sent."""

    def __init__(self):
        self.calls = []

    def get(self, params, headers):
        has_key = bool(params.get("key"))
        has_token = "Authorization" in (headers or {})
        self.calls.append({"key": has_key, "token": has_token})
        _authorize(has_key, has_token)
        return {"files": [{"id": "f1", "name": "chart.zip"}]}


@pytest.fixture
def google(monkeypatch):
    fake = FakeGoogle()

    class Response:
        headers = {"Content-Type": "application/json"}
        status_code = 200

        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

        def raise_for_status(self):
            pass

    def fake_request(method, url, **kwargs):
        return Response(fake.get(kwargs.get("params") or {}, kwargs.get("headers")))

    monkeypatch.setattr(requests, "request", fake_request)
    return fake


def _client(token=None):
    return DriveClient(DriveClientConfig(api_key=KEY_PROJECT), auth_token=token)


def test_byoc_user_can_list_a_folder(google):
    """The reported bug: signed in with own creds, every scan 400'd."""
    items = _client(token=TOKEN_PROJECT).list_folder("folder1")

    assert items == [{"id": "f1", "name": "chart.zip"}]
    assert google.calls == [{"key": False, "token": True}]


def test_anonymous_user_can_still_list_a_folder(google):
    """The key must survive for users who never sign in."""
    items = _client().list_folder("folder1")

    assert items == [{"id": "f1", "name": "chart.zip"}]
    assert google.calls == [{"key": True, "token": False}]


def test_paginated_scan_never_reintroduces_the_key(google):
    """Page 2+ rebuilds params; it must not re-add the key mid-scan."""
    client = _client(token=TOKEN_PROJECT)
    pages = [
        {"files": [{"id": "a"}], "nextPageToken": "p2"},
        {"files": [{"id": "b"}]},
    ]
    google.get = lambda params, headers: (
        google.calls.append({"key": bool(params.get("key")),
                             "token": "Authorization" in (headers or {})})
        or _authorize(bool(params.get("key")), "Authorization" in (headers or {}))
        or pages[len(google.calls) - 1]
    )

    items = client.list_folder("folder1")

    assert len(items) == 2
    assert len(google.calls) == 2
    assert all(c == {"key": False, "token": True} for c in google.calls)


def test_credential_less_request_reports_an_empty_folder(google):
    """A request with neither credential 403s, and list_folder swallows 403.

    So it surfaces as "no files", not as an error. Pinned because it is the
    shape a scan takes if the key is ever missing and nobody is signed in:
    silent zeroes feed the planner, not a failure the purge guard would see.
    """
    client = DriveClient(DriveClientConfig(api_key=""), auth_token=None)

    assert client.list_folder("folder1") == []
    # Retried to exhaustion first: _request_with_retry treats 403 as transient,
    # so each dead scan costs 3 round trips plus backoff before going quiet.
    assert google.calls == [{"key": False, "token": False}] * 3
