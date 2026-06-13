"""Drive rclone copyid jobs to deliver blocked files to their temp paths."""
import time
from typing import Callable, List, Optional, Tuple

from ..sync.download_planner import DownloadTask


class RcloneDownloader:
    def __init__(self, rc, fs: str, poll_interval: float = 0.5):
        self.rc = rc
        self.fs = fs
        self.poll_interval = poll_interval

    def download(
        self,
        tasks: List[DownloadTask],
        cancel_check: Optional[Callable[[], bool]] = None,
        progress_cb: Optional[Callable[[DownloadTask, bool], None]] = None,
    ) -> Tuple[List[str], List[str]]:
        """Copy each task's file_id into its temp dir. Returns (ok_ids, failed_ids)."""
        ok: List[str] = []
        failed: List[str] = []
        for task in tasks:
            if cancel_check and cancel_check():
                failed.append(task.file_id)
                continue
            dest_dir = str(task.local_path.parent) + "/"
            try:
                jobid = self.rc.copyid_async(self.fs, task.file_id, dest_dir)
                success = self._await_job(jobid, cancel_check)
            except Exception:
                success = False
            (ok if success else failed).append(task.file_id)
            if progress_cb:
                progress_cb(task, success)
        return ok, failed

    def _await_job(self, jobid: int, cancel_check) -> bool:
        while True:
            if cancel_check and cancel_check():
                self.rc.stop_job(jobid)
                return False
            st = self.rc.job_status(jobid)
            if st.get("finished"):
                return bool(st.get("success"))
            time.sleep(self.poll_interval)
