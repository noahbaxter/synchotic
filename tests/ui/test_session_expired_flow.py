"""What a user sees when Google stops honouring their saved sign-in.

A refresh token dies for ordinary reasons: a revoked grant, a changed password,
or an OAuth client left in "Testing" publishing status, which expires them every
7 days. The old behaviour answered is_signed_in with a truthy value and no token
behind it, so the screen offered "Sign out" and never the sign-in that fixes it,
and the explanation only appeared after a wasted sync.

The sign-in control lives in the home screen's settings pane now.
"""
import json
from datetime import datetime, timedelta, timezone

import pytest

from src.config.settings import UserSettings
from src.ui.components import strip_ansi
from src.ui.screens.home_panes import show_main_menu_panes, SETTINGS


class FakeAuth:
    """Stands in for AuthManager: only the properties the pane reads."""
    def __init__(self, signed_in=False, expired=False, email=None):
        self.is_signed_in = signed_in
        self.session_expired = expired
        self.user_email = email


@pytest.fixture
def rows(monkeypatch, tmp_path):
    def build(auth, byoc=True, settings=None):
        captured = {}

        def fake_run(self):
            captured["rows"] = self._right_rows(SETTINGS, "")
            return None

        monkeypatch.setattr("chotic_ui.widgets.two_pane.TwoPane.run",
                            fake_run, raising=False)
        monkeypatch.setattr("src.drive.auth.has_custom_client_config",
                            lambda: byoc, raising=False)
        show_main_menu_panes(
            folders=[],
            user_settings=settings or UserSettings(tmp_path / "settings.json"),
            download_path=tmp_path / "charts",
            auth=auth,
        )
        return captured["rows"]
    return build


def _labels(rows):
    return [strip_ansi(r[0](False, False)).strip() for r in rows]


def _row_for(rows, text):
    return next(r for r in rows if text in strip_ansi(r[0](False, False)))


class TestTheSettingsPaneOffersTheFix:
    def test_expired_session_offers_sign_in_again(self, rows):
        labels = _labels(rows(FakeAuth(signed_in=False, expired=True)))
        assert any("Sign in again" in l for l in labels), labels

    def test_expired_session_never_offers_sign_out(self, rows):
        """The bug: the only Google row was "Sign out", which reads as the
        opposite of what a signed-out user needs to do."""
        labels = _labels(rows(FakeAuth(signed_in=True, expired=True)))
        assert not any("Sign out" in l for l in labels), labels

    def test_a_new_user_sees_a_greyed_sign_in_with_the_reason(self, rows):
        """The capped client answers "This app is blocked", so signing in cannot
        work. This used to hide the row entirely, which left people hunting for
        a control that was never there; it is shown unavailable instead."""
        from src.ui.primitives import Colors
        row = _row_for(rows(FakeAuth(), byoc=False), "Sign in")
        assert row[2] is False
        assert Colors.MUTED_DIM in row[0](False, False)
        assert "Needs your own credentials" in strip_ansi(row[0](False, False))

    def test_a_healthy_session_offers_sign_out_with_the_address(self, rows):
        labels = _labels(rows(FakeAuth(signed_in=True, expired=False, email="a@b.com")))
        assert any("Sign out" in l and "a@b.com" in l for l in labels), labels

    def test_a_signed_out_user_with_credentials_can_sign_in(self, rows):
        row = _row_for(rows(FakeAuth(signed_in=False, expired=False)), "Sign in to Google")
        assert row[2] is True
        assert row[1] == ("act", "signin")

    def test_the_expired_row_triggers_sign_in(self, rows):
        row = _row_for(rows(FakeAuth(expired=True)), "Sign in again")
        assert row[1] == ("act", "signin")

    def test_signing_in_is_pointless_in_anonymous_mode(self, rows, tmp_path):
        """Anonymous never authenticates, so the control is shown unavailable
        rather than inviting a sign-in that changes nothing."""
        from src.config.settings import DOWNLOAD_MODE_ANONYMOUS
        settings = UserSettings(tmp_path / "settings.json")
        settings.download_mode = DOWNLOAD_MODE_ANONYMOUS
        row = _row_for(rows(FakeAuth(), settings=settings), "Sign in")
        assert row[2] is False
        assert "anonymous" in strip_ansi(row[0](False, False)).lower()


class TestIsSignedInIsABool:
    def _token(self, tmp_path, refresh="1//0-secret-refresh-token"):
        p = tmp_path / "token.json"
        p.write_text(json.dumps({
            "token": "ya29.expired", "refresh_token": refresh,
            "token_uri": "https://oauth2.googleapis.com/token",
            "client_id": "cid", "client_secret": "sec",
            "scopes": ["https://www.googleapis.com/auth/drive.readonly"],
            "expiry": (datetime.now(timezone.utc) - timedelta(hours=2))
                      .replace(tzinfo=None).isoformat() + "Z",
        }))
        return p

    def test_never_returns_the_refresh_token(self, tmp_path):
        """It used to return the secret itself as its "yes"."""
        from src.drive.auth import UserOAuthManager
        mgr = UserOAuthManager(token_path=self._token(tmp_path))
        assert mgr.is_signed_in is True

    def test_absent_token_is_false(self, tmp_path):
        from src.drive.auth import UserOAuthManager
        mgr = UserOAuthManager(token_path=tmp_path / "nope.json")
        assert mgr.is_signed_in is False


class TestDeadTokensAreDiscarded:
    """Only Google refusing the grant should clear the token.

    A refresh also fails when the network is down. Deleting the token then would
    turn a flaky connection into a forced re-authorisation.
    """

    def _mgr(self, tmp_path):
        from src.drive.auth import UserOAuthManager
        p = tmp_path / "token.json"
        p.write_text(json.dumps({
            "token": "ya29.expired", "refresh_token": "1//0-dead",
            "token_uri": "https://oauth2.googleapis.com/token",
            "client_id": "cid", "client_secret": "sec",
            "scopes": ["https://www.googleapis.com/auth/drive.readonly"],
            "expiry": (datetime.now(timezone.utc) - timedelta(hours=2))
                      .replace(tzinfo=None).isoformat() + "Z",
        }))
        return UserOAuthManager(token_path=p), p

    def test_refused_grant_clears_the_token_and_flags_expiry(self, tmp_path, monkeypatch):
        from google.auth.exceptions import RefreshError
        from google.oauth2.credentials import Credentials
        mgr, path = self._mgr(tmp_path)

        def refuse(self, request):
            raise RefreshError("invalid_grant: Token has been expired or revoked.")
        monkeypatch.setattr(Credentials, "refresh", refuse)

        assert mgr.get_credentials() is None
        assert mgr.session_expired is True
        assert not path.exists(), "a grant Google refuses must not linger"
        assert mgr.is_signed_in is False

    def test_a_network_failure_keeps_the_token(self, tmp_path, monkeypatch):
        from google.oauth2.credentials import Credentials
        mgr, path = self._mgr(tmp_path)

        def offline(self, request):
            raise OSError("Network is unreachable")
        monkeypatch.setattr(Credentials, "refresh", offline)

        assert mgr.get_credentials() is None
        assert mgr.session_expired is False
        assert path.exists(), "offline is not a reason to sign the user out"
