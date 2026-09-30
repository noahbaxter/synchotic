"""One Drive folder can be a setlist in two drives.

A custom drive can hold a shortcut to a released drive's setlist, and discovery
resolves the shortcut to the same folder id. Keyed by that id alone, the two
drives overwrote each other and whichever listed last got the setlist, so a
user with it on in their own drive and off in the released one had it
downloaded into the released drive, and the next launch could go the other way.
Each download was then a purge, on and on.
"""

import pytest

from src.config.settings import UserSettings
from src.core import paths
from src.drive.scanner import ScanResult
from src.sync import cache as cache_mod
from src.sync.background_scanner import BackgroundScanner

RELEASED, CUSTOM, FIG = "popular", "sucs", "fig_folder"
FOLDER = "application/vnd.google-apps.folder"
SHORTCUT = "application/vnd.google-apps.shortcut"


class _Client:
    api_calls = 0

    def list_folder(self, folder_id):
        if folder_id == RELEASED:
            return [{"id": FIG, "name": "FigNeutered", "mimeType": FOLDER}]
        return [{"id": "sc1", "name": "FigNeutered's Charts", "mimeType": SHORTCUT,
                 "shortcutDetails": {"targetId": FIG, "targetMimeType": FOLDER}}]


class _FolderScanner:
    def scan(self, setlist_id, base_path=""):
        return ScanResult(files=[{"id": "f1", "path": f"{base_path}/song.ini", "name": "song.ini",
                                  "size": 10, "md5": "abc"}],
                          folder_count=1, shortcut_count=0, api_calls=1)


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNCHOTIC_ROOT", str(tmp_path))
    monkeypatch.setattr(cache_mod, "_persistent_stats_cache", None)
    monkeypatch.setattr(cache_mod, "_scan_cache", None)  # a fresh one under tmp_path
    monkeypatch.delenv("SYNCHOTIC_LIBRARY", raising=False)
    paths.set_library_path(tmp_path / "library")
    yield
    paths.set_library_path(None)


def _scanned(tmp_path, order):
    """Discover the drives in `order`, the way the network happened to finish,
    then scan everything through the scan cache, as the app does: the first
    drive to scan the folder fills it and the second reads it back."""
    settings = UserSettings.load(tmp_path / "settings.json")
    settings.set_drive_enabled(RELEASED, True)
    settings.set_drive_enabled(CUSTOM, True)
    settings.set_subfolder_enabled(RELEASED, "FigNeutered", False)
    drives = {RELEASED: {"folder_id": RELEASED, "name": "Popular Charters", "files": None},
              CUSTOM: {"folder_id": CUSTOM, "name": "Suc's Sync Drive", "files": None}}
    scanner = BackgroundScanner(list(drives.values()), None, "key",
                                user_settings=settings)
    scanner._client = _Client()
    for drive_id in order:
        scanner._discover_folder_setlists(drives[drive_id])
    while (setlist := scanner._get_next_setlist_to_scan()) is not None:
        scanner._scan_setlist(setlist, _FolderScanner())
    return scanner, drives


@pytest.mark.parametrize("order", [[RELEASED, CUSTOM], [CUSTOM, RELEASED]])
def test_it_downloads_only_into_the_drive_that_has_it_on(tmp_path, order):
    scanner, _ = _scanned(tmp_path, order)
    ready = [(s.drive_name, s.name) for s in scanner.get_scanned_enabled_setlists()]
    assert ready == [("Suc's Sync Drive", "FigNeutered's Charts")]


@pytest.mark.parametrize("order", [[RELEASED, CUSTOM], [CUSTOM, RELEASED]])
def test_both_drives_get_its_files(tmp_path, order):
    """A drive missing the setlist from its file list reads its copy as extra."""
    _, drives = _scanned(tmp_path, order)
    assert [f["path"] for f in drives[RELEASED]["files"]] == ["FigNeutered/song.ini"]
    assert [f["path"] for f in drives[CUSTOM]["files"]] == ["FigNeutered's Charts/song.ini"]


@pytest.mark.parametrize("order", [[RELEASED, CUSTOM], [CUSTOM, RELEASED]])
def test_each_drive_counts_its_own(tmp_path, order):
    scanner, _ = _scanned(tmp_path, order)
    assert scanner.get_discovered_setlist_count(RELEASED) == (0, 1)
    assert scanner.get_discovered_setlist_count(CUSTOM) == (1, 1)
    assert scanner.is_scanned(RELEASED) and scanner.is_scanned(CUSTOM)
