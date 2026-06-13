# tests/sync/test_blocked_surfacing.py
from src.sync.downloader import FileDownloader, DownloadResult


def test_download_result_has_needs_auth_flag():
    r = DownloadResult(success=False, file_path=None, message="x", needs_auth=True)
    assert r.needs_auth is True


def test_download_many_returns_blocked_tasks(monkeypatch, tmp_path):
    # No auth token, single virus-scan-blocked file -> should be reported as blocked task.
    from src.sync.download_planner import DownloadTask
    task = DownloadTask(file_id="ID", local_path=tmp_path / "_download_a.7z",
                        size=1, md5="", is_archive=True, rel_path="d/a.7z")
    dl = FileDownloader(auth_token=None)

    async def fake_dl(self, session, t, sem, prog):
        return DownloadResult(success=False, file_path=t.local_path,
                              message="SKIP (sign in to bypass virus scan)", needs_auth=True)

    monkeypatch.setattr(FileDownloader, "_download_file_async", fake_dl)
    result = dl.download_many([task], show_progress=False)
    blocked = result[6]   # 7th element: blocked tasks
    assert [t.file_id for t in blocked] == ["ID"]
