"""Two Drive files at one path.

A folder can hold an older and a newer upload under one name (Drummer's
Monthly `Covet - nero [highfine]/notes.chart`: 82,541 and 82,712 bytes). Only
one fits on disk, so the other always read as "size differs", downloaded again
on every sync, and the drive never showed synced. The scanner keeps the newest
upload, so the planner, status and purge all see the same one file.
"""

import pytest

from src.core import paths
from src.drive.scanner import ScanResult, newest_per_path
from src.sync import cache as cache_mod
from src.sync.background_scanner import BackgroundScanner
from src.sync.download_planner import plan_downloads

FOLDER = "application/vnd.google-apps.folder"
CHART = "Pack/Covet - Nero/notes.chart"


def _file(path, size, modified, fid=None):
    return {"id": fid or f"{path}:{size}", "path": path, "name": path.rsplit("/", 1)[-1],
            "size": size, "md5": f"md5-{size}", "modified": modified}


class TestNewestPerPath:
    def test_the_newer_upload_wins_whichever_is_listed_first(self):
        old = _file(CHART, 82712, "2025-08-16T02:26:06.000Z")
        new = _file(CHART, 82541, "2025-08-17T18:57:22.000Z")
        assert newest_per_path([old, new]) == [new]
        assert newest_per_path([new, old]) == [new]

    def test_paths_that_differ_only_in_case_are_one_path(self):
        old = _file("Pack/Song.7z", 10, "2024-01-01T00:00:00.000Z")
        new = _file("Pack/song.7z", 11, "2025-01-01T00:00:00.000Z")
        assert newest_per_path([old, new]) == [new]

    def test_identical_copies_leave_one(self):
        a = _file(CHART, 5, "2025-01-01T00:00:00.000Z", fid="a")
        b = _file(CHART, 5, "2025-01-01T00:00:00.000Z", fid="b")
        assert newest_per_path([a, b]) == [a]

    def test_a_file_with_no_date_loses_to_one_with(self):
        undated = _file(CHART, 5, "")
        dated = _file(CHART, 6, "2025-01-01T00:00:00.000Z")
        assert newest_per_path([dated, undated]) == [dated]

    def test_everything_else_is_untouched_and_in_order(self):
        files = [_file(f"Pack/{n}/song.ini", 1, "2025-01-01T00:00:00.000Z") for n in "cab"]
        assert newest_per_path(files) == files


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNCHOTIC_ROOT", str(tmp_path))
    monkeypatch.setattr(cache_mod, "_persistent_stats_cache", None)
    monkeypatch.setattr(cache_mod, "_scan_cache", None)
    monkeypatch.delenv("SYNCHOTIC_LIBRARY", raising=False)
    paths.set_library_path(tmp_path / "library")
    yield
    paths.set_library_path(None)


class _Client:
    api_calls = 0

    def list_folder(self, folder_id):
        return [{"id": "pack", "name": "Pack", "mimeType": FOLDER}]


class _FolderScanner:
    def scan(self, setlist_id, base_path=""):
        return ScanResult(files=[_file(f"{base_path}/Covet - Nero/notes.chart", 82712,
                                       "2025-08-16T02:26:06.000Z"),
                                 _file(f"{base_path}/Covet - Nero/notes.chart", 82541,
                                       "2025-08-17T18:57:22.000Z")],
                          folder_count=1, shortcut_count=0, api_calls=1)


def test_a_synced_drive_has_nothing_left_to_download(tmp_path):
    drive = {"folder_id": "d1", "name": "Drive", "files": None}
    scanner = BackgroundScanner([drive], None, "key")
    scanner._client = _Client()
    scanner._discover_folder_setlists(drive)
    while (setlist := scanner._get_next_setlist_to_scan()) is not None:
        scanner._scan_setlist(setlist, _FolderScanner())

    assert [f["size"] for f in drive["files"]] == [82541]
    assert drive["total_size"] == 82541

    local = tmp_path / "library"
    chart = local / "Drive" / "Pack" / "Covet - Nero" / "notes.chart"
    chart.parent.mkdir(parents=True)
    chart.write_bytes(b"x" * 82541)  # the newest upload, which is what a sync leaves

    tasks, skipped, _ = plan_downloads(drive["files"], local / "Drive", folder_name="Drive")
    assert tasks == []
