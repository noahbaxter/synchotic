"""Locked drives (the Guitar Hero and Rock Band rips) are scanned once and never again.

They are the biggest scans and the least likely to change. The drives are
picked out by folder id in constants.LOCKED_DRIVES, so if drives.json ever
points those names at other ids, this fails instead of the never-rescan
quietly landing on nothing. Their file list is still there from the cache,
which purge and sync status read; only the Drive listing is skipped.
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.core import paths
from src.core.constants import LOCKED_DRIVES
from src.drive.scanner import ScanResult
from src.sync import cache as cache_mod
from src.sync.background_scanner import BackgroundScanner

FOLDER = "application/vnd.google-apps.folder"
COMMUNITY = "csc_folder"
LOCKED = next(iter(LOCKED_DRIVES))


def test_the_locked_drives_are_the_games_in_drives_json():
    shipped = json.loads((Path(__file__).parents[2] / "drives.json").read_text())["drives"]
    by_id = {d["folder_id"]: d for d in shipped}
    for folder_id, name in LOCKED_DRIVES.items():
        assert by_id[folder_id]["name"] == name
        assert by_id[folder_id]["group"] == "Games"
    games = {d["folder_id"] for d in shipped if d["group"] == "Games"}
    assert games == set(LOCKED_DRIVES)


class _Client:
    api_calls = 0

    def list_folder(self, folder_id):
        return [{"id": f"{folder_id}_pack", "name": "Pack", "mimeType": FOLDER}]


class _FolderScanner:
    scans = 0

    def scan(self, setlist_id, base_path=""):
        _FolderScanner.scans += 1
        return ScanResult(files=[], folder_count=1, shortcut_count=0, api_calls=1)


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNCHOTIC_ROOT", str(tmp_path))
    monkeypatch.setattr(cache_mod, "_persistent_stats_cache", None)
    monkeypatch.setattr(cache_mod, "_scan_cache", None)
    monkeypatch.delenv("SYNCHOTIC_LIBRARY", raising=False)
    paths.set_library_path(tmp_path / "library")
    _FolderScanner.scans = 0
    yield
    paths.set_library_path(None)


def _age_cache(days):
    """Pretend every cached scan was made `days` ago."""
    then = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    for f in (cache_mod.get_scan_cache()._dir).glob("*.json"):
        data = json.loads(f.read_text())
        data["scanned_at"] = then
        f.write_text(json.dumps(data))


def _scan_all(drive_id):
    drive = {"folder_id": drive_id, "name": "Some Drive", "files": None}
    scanner = BackgroundScanner([drive], None, "key")
    scanner._client = _Client()
    scanner._discover_folder_setlists(drive)
    while (setlist := scanner._get_next_setlist_to_scan()) is not None:
        scanner._scan_setlist(setlist, _FolderScanner())


@pytest.mark.parametrize("drive_id, rescanned", [(LOCKED, False), (COMMUNITY, True)])
def test_two_days_on(drive_id, rescanned):
    _scan_all(drive_id)
    assert _FolderScanner.scans == 1
    _age_cache(days=2)
    _scan_all(drive_id)
    assert (_FolderScanner.scans == 2) is rescanned


def test_a_locked_drive_is_not_rescanned_however_old_the_cache():
    _scan_all(LOCKED)
    _age_cache(days=1000)
    _scan_all(LOCKED)
    assert _FolderScanner.scans == 1


def test_a_manual_rescan_still_lists_a_locked_drive():
    _scan_all(LOCKED)
    cache_mod.get_scan_cache().invalidate_all()
    _scan_all(LOCKED)
    assert _FolderScanner.scans == 2
