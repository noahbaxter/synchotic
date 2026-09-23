"""A drive whose listing throws must not pass for a drive with one setlist.

Both register one entry named after the drive. Told apart nowhere, a fresh
BYOC key that could not list yet gave a home screen with no setlists, no
error, and a sync checkmark.
"""
from pathlib import Path

from src.config.settings import UserSettings
from src.sync.background_scanner import BackgroundScanner
from src.ui.screens.home import _get_display_state

DRIVE = "drv1"
NAME = "Drummer's Monthly Drive"


class Dead:
    def list_folder(self, folder_id):
        raise RuntimeError("403 quota exceeded")


class Flat:
    """A real drive that simply has no setlist subfolders."""

    def list_folder(self, folder_id):
        return [{"id": "f1", "name": "song.chart", "mimeType": "audio/midi"}]


def _scanner(tmp_path, client):
    settings = UserSettings.load(tmp_path / "settings.json")
    settings.set_drive_enabled(DRIVE, True)
    scanner = BackgroundScanner([{"folder_id": DRIVE, "name": NAME}], None,
                                "key", user_settings=settings,
                                download_path=Path(tmp_path))
    scanner._client = client
    scanner._discover_all_setlists()
    return scanner


def test_a_failed_listing_is_recorded_rather_than_swallowed(tmp_path):
    scanner = _scanner(tmp_path, Dead())

    assert scanner.discovery_failed(DRIVE) is True
    assert scanner.has_scan_failures() is True
    assert "403" in scanner.get_failure_reason()


def test_a_flat_drive_is_not_reported_as_a_failure(tmp_path):
    """Charts kept at the top level are a real layout, not an error."""
    scanner = _scanner(tmp_path, Flat())

    assert scanner.discovery_failed(DRIVE) is False
    assert scanner.has_scan_failures() is False


def test_the_home_screen_does_not_show_it_as_scanned(tmp_path):
    scanner = _scanner(tmp_path, Dead())
    scanner._scanned_setlist_ids.add(DRIVE)  # the stand-in, scanned empty

    assert _get_display_state(DRIVE, has_files=True, has_cache=False,
                              scanner=scanner) == "none"
