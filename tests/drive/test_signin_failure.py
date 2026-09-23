"""A failed Google sign-in says why, once."""
import pytest

from src import copy
from src.drive import auth as drive_auth


@pytest.fixture
def refusing_flow(monkeypatch):
    """Google's consent flow failing the way a blocked client does."""
    class Flow:
        @classmethod
        def from_client_config(cls, *a, **k):
            raise RuntimeError("access_denied: This app is blocked")

    monkeypatch.setattr(drive_auth, "OAUTH_AVAILABLE", True)
    monkeypatch.setattr(drive_auth, "InstalledAppFlow", Flow)
    monkeypatch.setattr(drive_auth, "load_client_config", lambda: {})


def test_the_reason_is_kept_and_nothing_is_printed(refusing_flow, tmp_path, capsys):
    """The caller prints the failure. Two messages for one failure read as two."""
    mgr = drive_auth.UserOAuthManager(token_path=tmp_path / "token.json")
    assert mgr.sign_in() is False
    assert mgr.last_error == "access_denied: This app is blocked"
    assert capsys.readouterr().out == ""


def test_the_settings_row_prints_the_reason(refusing_flow, tmp_path, monkeypatch, capsys):
    from types import SimpleNamespace
    from sync import SyncApp

    app = object.__new__(SyncApp)
    app.user_settings = SimpleNamespace(download_mode="byoc")
    app.auth = drive_auth.AuthManager(token_path=tmp_path / "token.json")
    monkeypatch.setattr("src.app.auth.wait_with_skip", lambda *a, **k: None)

    app.handle_signin()

    assert f"{copy.FAILURE}: access_denied: This app is blocked" in capsys.readouterr().out
