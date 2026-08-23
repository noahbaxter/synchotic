"""The home screen's Downloads line.

It used to be a locked, non-selectable label hardcoded to "anonymous + rclone",
so it lied about the current mode and offered no way to change it.
"""
import pytest

from src.config.settings import (DOWNLOAD_MODE_ANONYMOUS, DOWNLOAD_MODE_BYOC,
                                 DOWNLOAD_MODE_RCLONE, UserSettings)
from src.ui.screens.home import show_main_menu


@pytest.fixture
def downloads_item(monkeypatch, tmp_path):
    """Build the home menu and hand back its Downloads row."""
    def build(mode, rclone_authed=True, byoc_configured=True):
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
        show_main_menu([], user_settings=settings)

        rows = [i for i in captured["items"]
                if "Downloads" in (getattr(i, "label", "") or "")]
        assert len(rows) == 1, f"expected one Downloads row, got {len(rows)}"
        return rows[0]
    return build


def test_row_is_selectable_and_routes_to_the_chooser(downloads_item):
    row = downloads_item(DOWNLOAD_MODE_RCLONE)
    assert row.disabled is False
    assert row.value == ("download_mode", None)


@pytest.mark.parametrize("mode,shown", [
    (DOWNLOAD_MODE_RCLONE, "rclone"),
    (DOWNLOAD_MODE_BYOC, "your own Google credentials"),
    (DOWNLOAD_MODE_ANONYMOUS, "no sign-in"),
])
def test_row_names_the_mode_actually_in_use(downloads_item, mode, shown):
    assert shown in downloads_item(mode).label


def test_unset_mode_reads_as_rclone(downloads_item):
    """Matches the runtime default of `download_mode or "rclone"`."""
    assert "rclone" in downloads_item("").label


def test_rclone_without_consent_says_so(downloads_item):
    """Otherwise it claims rclone while every large chart is still being skipped."""
    assert "not connected yet" in downloads_item(DOWNLOAD_MODE_RCLONE, rclone_authed=False).label
    assert "not connected yet" not in downloads_item(DOWNLOAD_MODE_RCLONE, rclone_authed=True).label


def test_byoc_without_credentials_says_so(downloads_item):
    """Silently falling back to the blocked shared client is the failure to surface."""
    row = downloads_item(DOWNLOAD_MODE_BYOC, byoc_configured=False)
    assert "not set up" in row.label
    assert "not set up" not in downloads_item(DOWNLOAD_MODE_BYOC, byoc_configured=True).label
