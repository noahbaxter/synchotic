"""Sync the same small drive over and over, changing download_ignore each time.

download_ignore decides what we fetch, never what we delete. This drives the
real pipeline (planner, downloader, extractor, markers, status, purge) with only
the bytes faked, so planners that disagree about an ignore rule show up as a
re-download, a wrong count, or a deletion.
"""
import asyncio
import hashlib
import io
import json
import zipfile
from pathlib import Path

import pytest

from src.config.settings import DEFAULT_DOWNLOAD_IGNORE, DEFAULT_PURGE_IGNORE, UserSettings
from src.sync.downloader import DownloadResult
from src.sync.folder_sync import FolderSync
from src.sync.purge_planner import plan_purge
from src.sync.status import get_setlist_sync_status

DRIVE = "TestDrive"
FID = "fid_TestDrive"
SETLIST = "Set"
CHART = f"{SETLIST}/Loose Chart"


def _zip_bytes(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in entries.items():
            z.writestr(name, data)
    return buf.getvalue()


@pytest.fixture
def drive(tmp_path, monkeypatch):
    """A tiny drive: one loose chart, one archive, both carrying a video."""
    library = tmp_path / "library"
    library.mkdir()
    monkeypatch.setenv("SYNCHOTIC_LIBRARY", str(library))
    markers = library / ".synchotic" / "markers"
    markers.mkdir(parents=True)
    monkeypatch.setattr("src.sync.markers.get_markers_dir", lambda: markers)
    from src.sync.cache import SyncCache
    monkeypatch.setattr("src.sync.cache._cache", SyncCache())

    archive = _zip_bytes({
        "Packed Chart/song.ini": b"[song]\nname=Packed\n",
        "Packed Chart/notes.mid": b"MThd" + b"\x00" * 60,
        "Packed Chart/background.webm": b"\x1aE\xdf\xa3" + b"\x00" * 200,
    })
    remote = {
        "id_ini": b"[song]\nname=Loose\n",
        "id_mid": b"MThd" + b"\x00" * 40,
        "id_mp4": b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 300,
        "id_txt": b"charted by somebody\n",
        "id_zip": archive,
    }
    files = [
        {"id": "id_ini", "path": f"{CHART}/song.ini"},
        {"id": "id_mid", "path": f"{CHART}/notes.mid"},
        {"id": "id_mp4", "path": f"{CHART}/video.mp4"},
        {"id": "id_txt", "path": f"{CHART}/readme.txt"},
        {"id": "id_zip", "path": f"{SETLIST}/pack.zip"},
    ]
    for f in files:
        data = remote[f["id"]]
        f["size"] = len(data)
        f["md5"] = hashlib.md5(data).hexdigest()
        f["modified"] = "2026-01-01T00:00:00"

    async def fake_fetch(self, session, task, semaphore, progress_tracker=None):
        data = remote[task.file_id]
        task.local_path.parent.mkdir(parents=True, exist_ok=True)
        task.local_path.write_bytes(data)
        return DownloadResult(success=True, file_path=task.local_path,
                              message="", bytes_downloaded=len(data))

    monkeypatch.setattr("src.sync.downloader.FileDownloader._download_file_async",
                        fake_fetch)

    return _Drive(library, {"name": DRIVE, "folder_id": FID, "files": files},
                  tmp_path / "settings.json")


class _Drive:
    def __init__(self, library, folder, settings_path):
        self.library = library
        self.folder = folder
        self.settings_path = settings_path

    def settings(self, download_ignore, purge_ignore=DEFAULT_PURGE_IGNORE):
        self.settings_path.write_text(json.dumps({
            "version": 1,
            "library_path": str(self.library),
            "download_ignore": list(download_ignore),
            "purge_ignore": list(purge_ignore),
            "drive_toggles": {FID: True},
        }))
        return UserSettings.load(self.settings_path)

    def sync(self, settings):
        sync = FolderSync(client=None, auth_token=None,
                          download_ignore=settings.download_ignore,
                          download_mode="byoc")
        downloaded, skipped, errors, _, cancelled, _ = sync.sync_folder(
            self.folder, self.library)
        assert errors == 0 and not cancelled
        return downloaded, skipped

    def on_disk(self):
        root = self.library / DRIVE
        return sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())

    def purge(self, settings):
        files, _ = plan_purge([self.folder], self.library, settings, None)
        return sorted(str(p.relative_to(self.library / DRIVE)) for p, _ in files)

    def status(self, settings):
        return get_setlist_sync_status(self.folder, SETLIST, self.library,
                                       download_ignore=settings.download_ignore)


VIDEOS = list(DEFAULT_DOWNLOAD_IGNORE)


class TestTogglingTheListBetweenSyncs:
    def test_a_video_you_asked_for_survives_turning_videos_back_off(self, drive):
        # 1. Videos ignored, as a new install has it.
        s = drive.settings(VIDEOS)
        downloaded, skipped = drive.sync(s)
        assert skipped == 1, "the loose mp4 is the only thing we decline to fetch"
        assert drive.on_disk() == [
            f"{CHART}/notes.mid",
            f"{CHART}/readme.txt",
            f"{CHART}/song.ini",
            "Set/Packed Chart/notes.mid",
            "Set/Packed Chart/song.ini",
        ], "no video reaches disk, in the open or out of an archive"
        assert drive.purge(s) == []
        assert drive.status(s).is_synced

        # 2. Nothing ignored: the loose video comes down.
        s = drive.settings([])
        drive.sync(s)
        assert f"{CHART}/video.mp4" in drive.on_disk()
        assert drive.purge(s) == []

        # 3. Videos ignored again. The file we already have is ours to keep.
        s = drive.settings(VIDEOS)
        downloaded, skipped = drive.sync(s)
        assert downloaded == 0, "nothing to fetch: the toggle is not a re-download"
        assert f"{CHART}/video.mp4" in drive.on_disk()
        assert drive.purge(s) == [], "purge must not touch a video it did not plant"
        assert drive.status(s).is_synced

    def test_the_second_sync_is_a_no_op_when_nothing_changed(self, drive):
        s = drive.settings(VIDEOS)
        drive.sync(s)
        before = drive.on_disk()
        downloaded, skipped = drive.sync(s)
        assert downloaded == 0
        assert skipped == 5, "4 already here plus the video we decline: nothing left"
        assert drive.on_disk() == before

    def test_an_archive_already_extracted_is_left_as_extracted(self, drive):
        """Turning videos on does not re-extract packs we already have.

        The marker says the pack is synced, so its stripped video stays gone
        until the pack itself changes. Pinned because it is surprising, not
        because it is desirable.
        """
        drive.sync(drive.settings(VIDEOS))
        s = drive.settings([])
        drive.sync(s)
        assert "Set/Packed Chart/background.webm" not in drive.on_disk()
        assert drive.purge(s) == []


class TestAnyPatternNotJustVideos:
    def test_a_custom_type_is_skipped_and_not_counted_missing(self, drive):
        s = drive.settings(["*.txt"])
        drive.sync(s)
        disk = drive.on_disk()
        assert f"{CHART}/readme.txt" not in disk
        assert f"{CHART}/video.mp4" in disk, "only what the list names is skipped"
        assert drive.status(s).is_synced, "a file we never fetch is not missing"
        assert drive.purge(s) == []


class TestPurgeIsGovernedByPurgeIgnoreAlone:
    def _hand_made(self, drive):
        p = drive.library / DRIVE / CHART / "my-own-render.webm"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"\x1aE\xdf\xa3" + b"\x00" * 100)
        return f"{CHART}/my-own-render.webm"

    def test_an_untracked_file_is_still_purged(self, drive):
        s = drive.settings(VIDEOS)
        drive.sync(s)
        mine = self._hand_made(drive)
        assert drive.purge(s) == [mine], "not in markers, not in the manifest: extra"

    def test_purge_ignore_is_what_spares_it(self, drive):
        s = drive.settings(VIDEOS, purge_ignore=list(DEFAULT_PURGE_IGNORE) + ["*.webm"])
        drive.sync(s)
        self._hand_made(drive)
        assert drive.purge(s) == []
        assert drive.sync(s)[0] == 0, "and sparing it does not make us fetch it again"
