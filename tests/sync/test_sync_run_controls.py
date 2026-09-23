"""What the sync panel promises while a run is under way: ESC stops planning
and purging, a purge dialog gets the keyboard to itself, and a file Google
blocked is not reported as failed before rclone has had its turn."""
import pytest

from src.sync.cache import SyncCache


@pytest.fixture
def library(tmp_path, monkeypatch):
    markers = tmp_path / "state" / "markers"
    markers.mkdir(parents=True)
    monkeypatch.setattr("src.sync.markers.get_markers_dir", lambda: markers)
    monkeypatch.setattr("src.sync.cache._cache", SyncCache())
    monkeypatch.setattr("src.sync.ownership.is_library_adopted", lambda: True)
    lib = tmp_path / "library"
    (lib / "Drive").mkdir(parents=True)
    (lib / "Drive" / "stray.txt").write_text("not ours")
    return lib


def _folders():
    return [{"name": "Drive", "folder_id": "d1", "files": []}]


def test_planning_stops_when_cancelled(tmp_path):
    from src.sync.download_planner import plan_downloads
    files = [{"id": str(i), "path": f"Set/c{i}/song.ini", "size": 1, "md5": ""}
             for i in range(5)]
    tasks, _, _ = plan_downloads(files, tmp_path, cancel_check=lambda: True)
    assert tasks == []


def test_purge_stops_before_the_next_drive_when_cancelled(library):
    from src.sync.purge_flow import purge_all_folders
    from src.ui.widgets.progress import FolderProgress

    purge_all_folders(_folders(), library, progress=FolderProgress(0, 0),
                      cancel_check=lambda: True)
    assert (library / "Drive" / "stray.txt").exists()


def test_the_purge_dialog_gets_the_keyboard_to_itself(library, monkeypatch):
    from src.sync import purge_flow
    from src.ui.widgets.progress import FolderProgress

    events = []

    class Dialog:
        def __init__(self, text):
            pass

        def run(self):
            events.append("dialog")
            return False

    monkeypatch.setattr(purge_flow, "PURGE_CONFIRM_FILE_THRESHOLD", 0)
    monkeypatch.setattr("src.ui.widgets.confirm.ConfirmDialog", Dialog)

    purge_flow.purge_all_folders(
        _folders(), library, progress=FolderProgress(0, 0),
        pause_keys=lambda: events.append("pause"),
        resume_keys=lambda: events.append("resume"))

    assert events == ["pause", "dialog", "resume"]
    assert (library / "Drive" / "stray.txt").exists(), "declined means nothing deleted"


def test_a_blocked_file_is_not_a_failure_on_the_panel(monkeypatch, tmp_path):
    from src.sync.download_planner import DownloadTask
    from src.sync.downloader import DownloadResult, FileDownloader
    from src.ui.widgets.progress import FolderProgress

    async def blocked(self, session, task, sem, progress):
        return DownloadResult(success=False, file_path=task.local_path,
                              message="NEEDS AUTH: a.7z", needs_auth=True)

    monkeypatch.setattr(FileDownloader, "_download_file_async", blocked)
    task = DownloadTask(file_id="ID", local_path=tmp_path / "_download_a.7z",
                        size=1, md5="", is_archive=True, rel_path="d/a.7z")
    progress = FolderProgress(0, 0)
    FileDownloader(auth_token=None).download_many([task], progress=progress)
    assert progress.screen.entries.failures() == []
