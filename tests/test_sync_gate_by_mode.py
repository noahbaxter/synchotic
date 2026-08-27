"""Sync is gated on whether the mode can reach Drive, not on OAuth.

handle_sync required auth.is_signed_in from the day it was written, when
embedded OAuth was the only way in. rclone and BYOC arrived later and never
touched it, so once embedded sign-in stopped being available, pressing sync
in rclone mode printed "Cannot scan custom folders: not signed in to Google"
and returned, with rclone connected and working.
"""

import pytest

from src.config.settings import (UserSettings, DOWNLOAD_MODE_ANONYMOUS,
                                 DOWNLOAD_MODE_BYOC, DOWNLOAD_MODE_RCLONE)


class _Auth:
    def __init__(self, signed_in=False):
        self.is_signed_in = signed_in


@pytest.fixture
def app(tmp_path, monkeypatch):
    from sync import SyncApp

    def build(mode, *, signed_in=False, rclone_authed=False, byoc_creds=False):
        a = object.__new__(SyncApp)
        a.user_settings = UserSettings(tmp_path / "settings.json")
        a.user_settings.download_mode = mode
        a.auth = _Auth(signed_in)
        monkeypatch.setattr("src.rclone.is_authed", lambda: rclone_authed)
        monkeypatch.setattr("src.drive.auth.has_custom_client_config", lambda: byoc_creds)
        return a
    return build


def test_connected_rclone_can_sync_without_signing_in(app):
    """The reported breakage: rclone connected, sync refused anyway."""
    assert app(DOWNLOAD_MODE_RCLONE, rclone_authed=True, signed_in=False)._drive_blocked() == ""


def test_anonymous_can_sync_without_signing_in(app):
    assert app(DOWNLOAD_MODE_ANONYMOUS, signed_in=False)._drive_blocked() == ""


def test_unconnected_rclone_is_blocked_and_says_so(app):
    assert app(DOWNLOAD_MODE_RCLONE, rclone_authed=False)._drive_blocked() == \
        "rclone is not connected yet"


def test_byoc_without_credentials_is_blocked(app):
    assert app(DOWNLOAD_MODE_BYOC, byoc_creds=False)._drive_blocked() == \
        "your own Google credentials are not set up yet"


def test_byoc_signed_out_is_blocked(app):
    assert app(DOWNLOAD_MODE_BYOC, byoc_creds=True, signed_in=False)._drive_blocked() == \
        "you are not signed in to Google"


def test_byoc_signed_in_can_sync(app):
    assert app(DOWNLOAD_MODE_BYOC, byoc_creds=True, signed_in=True)._drive_blocked() == ""


def test_the_block_message_names_syncing_not_custom_folders(capsys):
    """The old text described a feature the user was not using."""
    from src.ui.widgets import sync_display

    sync_display.sync_blocked("rclone is not connected yet")
    out = capsys.readouterr().out

    assert "Cannot sync: rclone is not connected yet" in out
    assert "custom folders" not in out


def test_the_menu_and_sync_cannot_disagree(app):
    """Both read the same rule, so a row you can click never fails the gate."""
    from src.ui.screens.home_panes import _mode_blocked_reason

    for mode, kw in [(DOWNLOAD_MODE_RCLONE, {"rclone_authed": True}),
                     (DOWNLOAD_MODE_RCLONE, {"rclone_authed": False}),
                     (DOWNLOAD_MODE_ANONYMOUS, {}),
                     (DOWNLOAD_MODE_BYOC, {"byoc_creds": False}),
                     (DOWNLOAD_MODE_BYOC, {"byoc_creds": True, "signed_in": True})]:
        a = app(mode, **kw)
        menu_blocked = bool(_mode_blocked_reason(a.user_settings, a.auth,
                                                 kw.get("rclone_authed", False)))
        assert menu_blocked == bool(a._drive_blocked()), (mode, kw)


class TestScanningStartsWithoutOAuth:
    """The gate that was missed.

    handle_sync stopped requiring OAuth, but _start_background_scan kept its own
    `if not self.auth.is_signed_in: return`. So in rclone mode sync got past the
    front door and then no scanner was ever built: no discovery, no stats, every
    drive left with files=None. The home screen reads that as nothing enabled and
    the footer reads it as nothing to fetch.
    """

    @pytest.fixture
    def scanning_app(self, app, monkeypatch, tmp_path):
        def build(mode, **kw):
            a = app(mode, **kw)
            a.folders = [{"folder_id": "drive1", "name": "Drive One", "files": None}]
            a.custom_folders = None
            a._background_scanner = None
            monkeypatch.setattr("sync.get_download_path", lambda: tmp_path)
            started = {}

            class _Scanner:
                def __init__(self, folders, *a_, **kw_):
                    started["folders"] = folders
                def discover(self, on_progress=None):
                    started["discovered"] = True
                def start(self):
                    started["started"] = True

            monkeypatch.setattr("sync.BackgroundScanner", _Scanner)
            monkeypatch.setattr(a, "_migrate_subfolder_customs", lambda: None)
            return a, started
        return build

    def test_connected_rclone_scans_without_signing_in(self, scanning_app):
        a, started = scanning_app(DOWNLOAD_MODE_RCLONE, rclone_authed=True, signed_in=False)

        a._start_background_scan()

        assert started.get("started"), "no scanner was ever started"
        assert a._background_scanner is not None

    def test_anonymous_scans_without_signing_in(self, scanning_app):
        a, started = scanning_app(DOWNLOAD_MODE_ANONYMOUS, signed_in=False)

        a._start_background_scan()

        assert started.get("started"), "no scanner was ever started"

    def test_unconnected_rclone_still_does_not_scan(self, scanning_app):
        """A mode that cannot reach Drive should still not start a scan."""
        a, started = scanning_app(DOWNLOAD_MODE_RCLONE, rclone_authed=False, signed_in=False)

        a._start_background_scan()

        assert not started.get("started")
