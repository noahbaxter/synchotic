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


def _make_folder(file_ids):
    files = [{"id": fid, "path": f"Set/{fid}.7z", "size": 1, "md5": ""} for fid in file_ids]
    return {"name": "Drive", "folder_id": "fid", "files": files}


def test_loose_file_recovered_without_extraction(monkeypatch, tmp_path):
    from src.sync.download_planner import DownloadTask
    blocked = DownloadTask(file_id="ID", local_path=tmp_path / "Set" / "loose.txt",
                           size=1, md5="", is_archive=False, rel_path="Drive/Set/loose.txt")

    # Primary downloader reports one blocked loose file, counted as 1 error.
    def fake_download_many(self, tasks, **kw):
        return (0, 0, 1, [], False, 0, [blocked])
    monkeypatch.setattr("src.sync.downloader.FileDownloader.download_many", fake_download_many)

    class FakeSession:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        downloader = type("D", (), {
            "download": lambda self, tasks, cancel_check=None, progress_cb=None: (["ID"], [])
        })()
    monkeypatch.setattr("src.rclone.is_authed", lambda: True)
    monkeypatch.setattr("src.rclone.RcloneSession", FakeSession)

    processed = {"called": False}
    monkeypatch.setattr(
        "src.sync.downloader.FileDownloader.process_archive",
        lambda self, task, rel=None: processed.update(called=True) or (True, "", {})
    )

    fs = FolderSync(client=None, auth_token=None)
    folder = _make_folder(["ID"])
    folder["files"][0]["path"] = "Set/loose.txt"
    result = fs.sync_folder(folder, tmp_path)
    downloaded, skipped, errors = result[0], result[1], result[2]
    assert downloaded == 1            # loose file counted as recovered
    assert errors == 0               # error subtracted away
    assert processed["called"] is False  # no extraction for loose files


def test_not_authed_leaves_blocked_as_errors(monkeypatch, tmp_path):
    from src.sync.download_planner import DownloadTask
    blocked = DownloadTask(file_id="ID", local_path=tmp_path / "Set" / "_download_a.7z",
                           size=1, md5="", is_archive=True, rel_path="Drive/Set/a.7z")

    def fake_download_many(self, tasks, **kw):
        return (0, 0, 1, [], False, 0, [blocked])
    monkeypatch.setattr("src.sync.downloader.FileDownloader.download_many", fake_download_many)

    def boom(*a, **kw):
        raise AssertionError("RcloneSession should not be constructed when not authed")
    monkeypatch.setattr("src.rclone.is_authed", lambda: False)
    monkeypatch.setattr("src.rclone.RcloneSession", boom)

    fs = FolderSync(client=None, auth_token=None)
    folder = _make_folder(["ID"])
    result = fs.sync_folder(folder, tmp_path)
    downloaded, errors = result[0], result[2]
    assert downloaded == 0    # nothing recovered
    assert errors == 1        # blocked file stays an error


def test_rclone_exception_keeps_files_failed(monkeypatch, tmp_path):
    from src.sync.download_planner import DownloadTask
    blocked = DownloadTask(file_id="ID", local_path=tmp_path / "Set" / "_download_a.7z",
                           size=1, md5="", is_archive=True, rel_path="Drive/Set/a.7z")

    def fake_download_many(self, tasks, **kw):
        return (0, 0, 1, [], False, 0, [blocked])
    monkeypatch.setattr("src.sync.downloader.FileDownloader.download_many", fake_download_many)

    class FakeSession:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        downloader = type("D", (), {
            "download": lambda self, tasks, cancel_check=None, progress_cb=None: (_ for _ in ()).throw(RuntimeError("rclone boom"))
        })()
    monkeypatch.setattr("src.rclone.is_authed", lambda: True)
    monkeypatch.setattr("src.rclone.RcloneSession", FakeSession)

    processed = {"called": False}
    monkeypatch.setattr(
        "src.sync.downloader.FileDownloader.process_archive",
        lambda self, task, rel=None: processed.update(called=True) or (True, "", {})
    )

    fs = FolderSync(client=None, auth_token=None)
    folder = _make_folder(["ID"])
    result = fs.sync_folder(folder, tmp_path)   # must not raise
    downloaded, errors = result[0], result[2]
    assert downloaded == 0           # nothing recovered after exception
    assert errors == 1              # error count unchanged
    assert processed["called"] is False


def test_errors_never_go_negative_when_partial_recovery(monkeypatch, tmp_path):
    from src.sync.download_planner import DownloadTask
    blocked_a = DownloadTask(file_id="A", local_path=tmp_path / "Set" / "_download_a.7z",
                             size=1, md5="", is_archive=True, rel_path="Drive/Set/A.7z")
    blocked_b = DownloadTask(file_id="B", local_path=tmp_path / "Set" / "_download_b.7z",
                             size=1, md5="", is_archive=True, rel_path="Drive/Set/B.7z")

    def fake_download_many(self, tasks, **kw):
        return (0, 0, 2, [], False, 0, [blocked_a, blocked_b])
    monkeypatch.setattr("src.sync.downloader.FileDownloader.download_many", fake_download_many)

    class FakeSession:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        downloader = type("D", (), {
            # rclone only recovers one of the two ids
            "download": lambda self, tasks, cancel_check=None, progress_cb=None: (["A"], ["B"])
        })()
    monkeypatch.setattr("src.rclone.is_authed", lambda: True)
    monkeypatch.setattr("src.rclone.RcloneSession", FakeSession)

    monkeypatch.setattr(
        "src.sync.downloader.FileDownloader.process_archive",
        lambda self, task, rel=None: (True, "", {})
    )

    fs = FolderSync(client=None, auth_token=None)
    folder = _make_folder(["A", "B"])
    result = fs.sync_folder(folder, tmp_path)
    downloaded, errors = result[0], result[2]
    assert downloaded == 1    # one archive recovered
    assert errors == 1        # 2 errors - 1 recovered
    assert errors >= 0        # never negative
