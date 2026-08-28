"""A scan in flight measures the library the user is looking at now.

Library Path is reachable while the background scan runs, and changing it
clears every stat measured against the old folder. The scanner held the path it
was built with, so each setlist that finished afterwards recomputed against the
old library and wrote those numbers straight back into the cache the change had
just emptied: an empty library reporting a full one, and no way back but a
forced re-scan.
"""

import pytest

from src.core import paths
from src.drive.scanner import ScanResult
from src.sync import cache as cache_mod
from src.sync.background_scanner import BackgroundScanner, SetlistInfo


class _Auth:
    def get_token(self):
        return "oauth-token"


class _Scanner:
    """A folder scan that returns one file and never touches the network."""

    def scan(self, setlist_id, base_path=""):
        return ScanResult(files=[{"id": "f1", "path": f"{base_path}/pack.7z",
                                  "name": "pack.7z", "size": 10, "md5": "abc"}],
                          folder_count=1, shortcut_count=0, api_calls=1)


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNCHOTIC_ROOT", str(tmp_path))
    monkeypatch.setattr(cache_mod, "_persistent_stats_cache", None)
    monkeypatch.delenv("SYNCHOTIC_LIBRARY", raising=False)
    paths.set_library_path(None)
    yield
    paths.set_library_path(None)


def test_stats_follow_a_library_changed_mid_scan(tmp_path, monkeypatch):
    old = tmp_path / "old"
    new = tmp_path / "new"
    old.mkdir()
    new.mkdir()
    paths.set_library_path(old)

    drive = {"folder_id": "drive1", "name": "MyDrive", "files": None}
    scanner = BackgroundScanner([drive], _Auth(), api_key="", download_path=old,
                                force_rescan=True)
    setlist = SetlistInfo(setlist_id="s1", name="Setlist", drive_id="drive1",
                          drive_name="MyDrive", drive=drive)

    measured = []

    def record(folder, setlist_name, base_path, user_settings=None):
        measured.append(base_path)
        return cache_mod.CachedSetlistStats(
            total_charts=1, total_size=10, synced_charts=0, synced_size=0,
            disk_files=0, disk_size=0)

    monkeypatch.setattr("src.sync.status.compute_setlist_stats", record)

    # the user picks a new library while this scan is still running
    paths.set_library_path(new)
    scanner._scan_setlist(setlist, _Scanner())

    assert measured == [new], "measured the library the user just left"
