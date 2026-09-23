"""Drive rclone copyid jobs to deliver blocked files to their temp paths."""
import time
from typing import Callable, List, Optional, Tuple

from ..core.logging import debug_log
from ..sync.download_planner import DownloadTask


# No bytes for this long means stuck, not slow: rclone reports no error when
# Drive stops answering mid-copy, so the byte count is the only signal.
STALL_TIMEOUT = 120.0

# Ceiling per file, for a job that trickles just enough never to look stalled.
MAX_WAIT = 1800.0

# How often a job that is still waiting says so in the debug log.
LOG_INTERVAL = 15.0


class RcloneDownloader:
    def __init__(self, rc, fs: str, poll_interval: float = 0.5,
                 max_wait: float = MAX_WAIT, stall_timeout: float = STALL_TIMEOUT):
        self.rc = rc
        self.fs = fs
        self.poll_interval = poll_interval
        self.max_wait = max_wait
        self.stall_timeout = stall_timeout

    def download(
        self,
        tasks: List[DownloadTask],
        cancel_check: Optional[Callable[[], bool]] = None,
        progress_cb: Optional[Callable[[DownloadTask, bool], None]] = None,
        on_start: Optional[Callable[[DownloadTask], None]] = None,
        on_bytes: Optional[Callable[[DownloadTask, int], None]] = None,
    ) -> Tuple[List[str], List[str]]:
        """Copy each task's file_id into its temp dir. Returns (ok_ids, failed_ids)."""
        ok: List[str] = []
        failed: List[str] = []
        for task in tasks:
            if cancel_check and cancel_check():
                failed.append(task.file_id)
                continue
            parent = task.local_path.parent
            parent.mkdir(parents=True, exist_ok=True)
            before = set(parent.iterdir())
            dest_dir = str(parent) + "/"
            if on_start:
                on_start(task)
            group = f"synchotic/{task.file_id}"
            try:
                jobid = self.rc.copyid_async(self.fs, task.file_id, dest_dir,
                                             group=group)
                success = self._await_job(
                    jobid, cancel_check, group,
                    on_bytes=(lambda n, t=task: on_bytes(t, n)) if on_bytes else None)
            except Exception as err:
                debug_log(f"RCLONE_JOB_FAILED | {task.file_id} | {type(err).__name__}: {err}")
                success = False
            if success:
                success = self._reconcile(task.local_path, before)
            (ok if success else failed).append(task.file_id)
            if progress_cb:
                progress_cb(task, success)
        return ok, failed

    @staticmethod
    def _reconcile(expected, before_entries) -> bool:
        """Rename the single newly-delivered file (whatever Drive named it) to the
        expected _download_ temp path. Returns False (fail-safe, no mismark) if the
        delivered file cannot be unambiguously identified."""
        if expected.exists():
            return True
        new_entries = [p for p in expected.parent.iterdir()
                       if p not in before_entries and p.is_file()]
        if len(new_entries) == 1:
            new_entries[0].rename(expected)
            return True
        return False

    def _await_job(self, jobid: int, cancel_check, group: str = "",
                   on_bytes: Optional[Callable[[int], None]] = None) -> bool:
        """Wait for one copyid job, watching the bytes rather than the clock.
        Drive answers a flagged file by sending nothing, so a quiet job is given
        up on while a moving one is left alone, up to max_wait."""
        started = time.time()
        moved_at = started
        logged_at = started
        transferred = 0

        while True:
            if cancel_check and cancel_check():
                self.rc.stop_job(jobid)
                return False

            now = time.time()
            if now - started > self.max_wait:
                debug_log(f"RCLONE_TIMEOUT | job={jobid} | {transferred}B "
                          f"in {now - started:.0f}s")
                self.rc.stop_job(jobid)
                return False

            st = self.rc.job_status(jobid)
            if st.get("finished"):
                return bool(st.get("success"))

            current = self._transferred(group)
            if current is not None and current > transferred:
                transferred = current
                moved_at = now
                if on_bytes:
                    on_bytes(transferred)
            elif current is not None and now - moved_at > self.stall_timeout:
                debug_log(f"RCLONE_STALLED | job={jobid} | {transferred}B, "
                          f"nothing for {now - moved_at:.0f}s")
                self.rc.stop_job(jobid)
                return False

            if now - logged_at >= LOG_INTERVAL:
                logged_at = now
                debug_log(f"RCLONE_WAITING | job={jobid} | {transferred}B "
                          f"after {now - started:.0f}s")

            time.sleep(self.poll_interval)

    def _transferred(self, group: str) -> Optional[int]:
        """Bytes this job has moved, or None when rclone will not say.

        None disables the stall check rather than reading as no progress: an
        rclone too old for grouped stats would otherwise have every transfer
        killed at the stall timeout.
        """
        stats = getattr(self.rc, "core_stats", None)
        if not group or not stats:
            return None
        try:
            return int(stats(group).get("bytes", 0))
        except Exception:
            return None
