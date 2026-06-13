# tests/rclone/test_downloader.py
from pathlib import Path
from src.rclone.downloader import RcloneDownloader
from src.sync.download_planner import DownloadTask

class FakeRc:
    def __init__(self): self.jobs = {}; self._n = 0; self.stopped = []
    def copyid_async(self, fs, file_id, dest):
        self._n += 1
        # simulate the file landing where copyid would put it
        Path(dest).mkdir(parents=True, exist_ok=True)
        (Path(dest) / f"_download_{file_id}.7z").write_bytes(b"data")
        self.jobs[self._n] = {"finished": True, "success": True}
        return self._n
    def job_status(self, jobid): return self.jobs[jobid]
    def stop_job(self, jobid): self.stopped.append(jobid)

def test_downloads_each_task_to_temp_path(tmp_path):
    task = DownloadTask(
        file_id="ABC", local_path=tmp_path / "Set" / "_download_song.7z",
        size=4, md5="x", is_archive=True, rel_path="Drive/Set/song.7z",
    )
    dl = RcloneDownloader(rc=FakeRc(), fs="synchotic:")
    ok, failed = dl.download([task], cancel_check=lambda: False)
    assert task.file_id in ok and not failed

def test_cancel_stops_pending(tmp_path):
    task = DownloadTask(file_id="ABC", local_path=tmp_path / "_download_x.7z",
                        size=1, md5="", is_archive=True, rel_path="d/x.7z")
    rc = FakeRc()
    dl = RcloneDownloader(rc=rc, fs="synchotic:")
    ok, failed = dl.download([task], cancel_check=lambda: True)
    assert "ABC" in failed and not ok
