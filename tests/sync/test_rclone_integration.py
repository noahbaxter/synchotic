# tests/sync/test_rclone_integration.py
from pathlib import Path
from src.sync.folder_sync import FolderSync


def test_blocked_tasks_routed_through_rclone(monkeypatch, tmp_path):
    from src.sync.download_planner import DownloadTask
    blocked = DownloadTask(file_id="ID", local_path=tmp_path / "Set" / "_download_a.7z",
                           size=1, md5="", is_archive=True, rel_path="Drive/Set/a.7z")

    # Primary downloader reports one blocked task, nothing downloaded.
    def fake_download_many(self, tasks, **kw):
        return (0, 0, 0, [], False, 0, [blocked])
    monkeypatch.setattr("src.sync.downloader.FileDownloader.download_many", fake_download_many)

    calls = {}
    class FakeSession:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def ensure_authed(self): return True
        downloader = type("D", (), {
            "download": lambda self, tasks, cancel_check=None, progress_cb=None: (
                calls.update(ids=[t.file_id for t in tasks]) or (["ID"], [])
            )
        })()
    monkeypatch.setattr("src.rclone.is_authed", lambda: True)
    monkeypatch.setattr("src.rclone.RcloneSession", FakeSession)

    processed = {}
    monkeypatch.setattr(
        "src.sync.downloader.FileDownloader.process_archive",
        lambda self, task, rel=None: processed.update(rel=rel) or (True, "", {})
    )

    fs = FolderSync(client=None, auth_token=None)
    folder = {"name": "Drive", "folder_id": "fid",
              "files": [{"id": "ID", "path": "Set/a.7z", "size": 1, "md5": ""}]}
    fs.sync_folder(folder, tmp_path)
    assert calls["ids"] == ["ID"]            # rclone got the blocked task
    assert processed["rel"] == "Drive/Set/a.7z"  # existing extraction path reused
