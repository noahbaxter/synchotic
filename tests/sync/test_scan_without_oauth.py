"""A scan with no Google sign-in must go out on the API key.

That is the whole basis for rclone and anonymous mode. docs/downloads.md:
"Scanning is unaffected: it is API-key based and has no cap. Only authenticated
downloads are gated." manifest_gen.py has always relied on it, walking every
drive in drives.json with DriveClient(config) and no token.

These drive the real BackgroundScanner rather than a stub, so they check the
credential that actually reaches Google, not just that a scanner was built.
"""

import pytest
import requests

from src.sync.background_scanner import BackgroundScanner

FOLDER_MIME = "application/vnd.google-apps.folder"


class _NoSignIn:
    """AuthManager for a user who never signed in, which is every rclone user."""
    is_signed_in = False

    def get_token(self):
        return None


class _Settings:
    def is_drive_enabled(self, folder_id):
        return True

    def is_subfolder_enabled(self, *a):
        return True

    def sync_subfolder_names(self, *a):
        return False

    def save(self):
        pass


@pytest.fixture
def google(monkeypatch):
    """Record every outgoing request and answer with one setlist."""
    calls = []

    class Response:
        status_code = 200
        headers = {"Content-Type": "application/json"}

        def json(self):
            return {"files": [{"id": "setlist1", "name": "Setlist One",
                               "mimeType": FOLDER_MIME}]}

        def raise_for_status(self):
            pass

    def fake_request(method, url, **kwargs):
        calls.append({
            "params": kwargs.get("params") or {},
            "headers": kwargs.get("headers") or {},
        })
        return Response()

    monkeypatch.setattr(requests, "request", fake_request)
    return calls


def _discover(api_key, google):
    folder = {"folder_id": "drive1", "name": "Drive One", "files": None}
    scanner = BackgroundScanner([folder], _NoSignIn(), api_key=api_key,
                                user_settings=_Settings())
    scanner.discover()
    return scanner, folder


def test_a_signed_out_scan_sends_the_api_key(google):
    _discover("baked-ci-key", google)

    assert google, "discovery made no request at all"
    assert google[0]["params"].get("key") == "baked-ci-key"


def test_a_signed_out_scan_sends_no_authorization_header(google):
    _discover("baked-ci-key", google)

    assert "Authorization" not in google[0]["headers"]


def test_a_signed_out_scan_actually_discovers_setlists(google):
    """The point of the key: without a token, discovery still finds the drive."""
    scanner, _ = _discover("baked-ci-key", google)

    assert scanner.get_enabled_setlist_count() == 1
