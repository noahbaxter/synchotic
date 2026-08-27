"""The home screen's Account row.

Downloads, sign-in and the data folder used to be three separate rows here. They
are one subject, they are touched rarely, and together they pushed Sync down the
screen. They now live on the Account screen, and this row is the tagline that has
to report the combined state without being opened: a mode that cannot download
is exactly what the user needs to see from the main menu.
"""
import pytest

from src.config.settings import (DOWNLOAD_MODE_ANONYMOUS, DOWNLOAD_MODE_BYOC,
                                 DOWNLOAD_MODE_RCLONE, UserSettings)
from src.ui.screens.home import show_main_menu


class FakeAuth:
    def __init__(self, signed_in=False, expired=False, email=None):
        self.is_signed_in = signed_in
        self.session_expired = expired
        self.user_email = email


@pytest.fixture
def account_row(monkeypatch, tmp_path):
    """Build the home menu and hand back its Account row."""
    def build(mode, rclone_authed=True, byoc_configured=True, auth=None):
        captured = {}

        def fake_run(self, initial_index=0):
            captured["items"] = self.items

            class Result:
                value = ("quit", None)
            return Result()

        monkeypatch.setattr("src.ui.widgets.menu.Menu.run", fake_run, raising=False)
        monkeypatch.setattr("chotic_ui.widgets.menu.Menu.run", fake_run, raising=False)
        monkeypatch.setattr("src.rclone.is_authed", lambda: rclone_authed, raising=False)
        monkeypatch.setattr("src.drive.auth.has_custom_client_config",
                            lambda: byoc_configured, raising=False)

        settings = UserSettings(tmp_path / "settings.json")
        settings.download_mode = mode
        show_main_menu([], user_settings=settings, auth=auth)

        rows = [i for i in captured["items"]
                if "Account" in (getattr(i, "label", "") or "")]
        assert len(rows) == 1, f"expected one Account row, got {len(rows)}"
        return rows[0], captured["items"]
    return build


def test_row_is_selectable_and_opens_the_account_screen(account_row):
    row, _ = account_row(DOWNLOAD_MODE_RCLONE)
    assert row.disabled is False
    assert row.value == ("account", None)


def test_the_three_old_rows_are_gone(account_row):
    """One row, not four. That consolidation is the point of the screen."""
    _, items = account_row(DOWNLOAD_MODE_RCLONE)
    labels = [getattr(i, "label", "") or "" for i in items]
    assert not any("Downloads:" in l for l in labels), labels
    assert not any("Open data folder" in l for l in labels), labels
    assert not any("Sign in" in l or "Sign out" in l for l in labels), labels


@pytest.mark.parametrize("mode,shown", [
    (DOWNLOAD_MODE_RCLONE, "rclone"),
    (DOWNLOAD_MODE_BYOC, "BYOC"),
    (DOWNLOAD_MODE_ANONYMOUS, "no sign-in"),
])
def test_row_names_the_mode_actually_in_use(account_row, mode, shown):
    assert shown in account_row(mode)[0].label


def test_unset_mode_reads_as_rclone(account_row):
    """Matches the runtime default of `download_mode or "rclone"`."""
    assert "rclone" in account_row("")[0].label


def test_rclone_without_consent_says_so(account_row):
    """Otherwise it claims rclone while every large chart is still being skipped."""
    assert "not connected" in account_row(DOWNLOAD_MODE_RCLONE, rclone_authed=False)[0].label
    assert "not connected" not in account_row(DOWNLOAD_MODE_RCLONE, rclone_authed=True)[0].label


def test_byoc_without_credentials_says_so(account_row):
    """Silently falling back to the blocked shared client is the failure to surface."""
    assert "not set up" in account_row(DOWNLOAD_MODE_BYOC, byoc_configured=False)[0].label
    assert "not set up" not in account_row(DOWNLOAD_MODE_BYOC, byoc_configured=True)[0].label


def test_signed_out_is_visible_without_opening_anything(account_row):
    """The whole reason the tagline carries state rather than just the mode."""
    label = account_row(DOWNLOAD_MODE_BYOC, auth=FakeAuth(signed_in=False))[0].label
    assert "signed out" in label, label


def test_an_expired_session_is_called_out(account_row):
    label = account_row(DOWNLOAD_MODE_BYOC, auth=FakeAuth(signed_in=True, expired=True))[0].label
    assert "session expired" in label, label
