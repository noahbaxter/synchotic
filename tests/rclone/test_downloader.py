# tests/rclone/test_downloader.py
from pathlib import Path
from src.rclone.downloader import RcloneDownloader
from src.sync.download_planner import DownloadTask

class FakeRc:
    def __init__(self): self.jobs = {}; self._n = 0; self.stopped = []
    def copyid_async(self, fs, file_id, dest, group=None):
        self._n += 1
        # simulate the file landing where copyid would put it (real Drive name)
        Path(dest).mkdir(parents=True, exist_ok=True)
        (Path(dest) / "song.7z").write_bytes(b"data")
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

def test_delivered_file_renamed_to_expected_temp_name(tmp_path):
    from src.rclone.downloader import RcloneDownloader
    from src.sync.download_planner import DownloadTask
    class Rc:
        def copyid_async(self, fs, fid, dest, group=None):
            from pathlib import Path
            Path(dest).mkdir(parents=True, exist_ok=True)
            (Path(dest) / "song.7z").write_bytes(b"d")  # rclone uses real name
            return 1
        def job_status(self, j): return {"finished": True, "success": True}
        def stop_job(self, j): pass
    task = DownloadTask(file_id="ID", local_path=tmp_path / "_download_song.7z",
                        size=1, md5="", is_archive=True, rel_path="d/song.7z")
    RcloneDownloader(rc=Rc(), fs="synchotic:").download([task], cancel_check=lambda: False)
    assert task.local_path.exists()  # renamed _download_song.7z

def test_delivered_name_differs_from_expected_reconciled_by_snapshot(tmp_path):
    # rclone writes the file under its raw Drive name, which differs from the
    # sanitized _download_ name Synchotic expects. Snapshot-diff must still find it.
    # (Uses plainly-different legal names rather than OS-illegal sanitized chars like
    # '?' or ':' so the fake can write the file on every platform, Windows included.)
    from src.rclone.downloader import RcloneDownloader
    from src.sync.download_planner import DownloadTask
    class Rc:
        def copyid_async(self, fs, fid, dest, group=None):
            from pathlib import Path
            Path(dest).mkdir(parents=True, exist_ok=True)
            (Path(dest) / "raw_drive_name.7z").write_bytes(b"d")  # name != expected
            return 1
        def job_status(self, j): return {"finished": True, "success": True}
        def stop_job(self, j): pass
    # expected temp name differs from the delivered raw name (simulates sanitization);
    # the old name-guessing code would look for "sanitized.7z" and fail.
    task = DownloadTask(file_id="ID", local_path=tmp_path / "Set" / "_download_sanitized.7z",
                        size=1, md5="", is_archive=True, rel_path="Drive/Set/sanitized.7z")
    ok, failed = RcloneDownloader(rc=Rc(), fs="synchotic:").download([task], cancel_check=lambda: False)
    assert ok == ["ID"] and not failed
    assert task.local_path.exists()


class SlowRc:
    """A job that never finishes. `bytes_per_poll` decides whether it is a
    transfer that is merely slow or one Drive has stopped answering."""

    def __init__(self, bytes_per_poll=0):
        self.bytes_per_poll = bytes_per_poll
        self.sent = 0
        self.stopped = []
        self.polls = 0

    def copyid_async(self, fs, fid, dest, group=None):
        Path(dest).mkdir(parents=True, exist_ok=True)
        return 1

    def job_status(self, jobid):
        self.polls += 1
        return {"finished": False}

    def core_stats(self, group=None):
        self.sent += self.bytes_per_poll
        return {"bytes": self.sent}

    def stop_job(self, jobid):
        self.stopped.append(jobid)


def _task(tmp_path):
    return DownloadTask(file_id="ID", local_path=tmp_path / "Set" / "_download_a.7z",
                        size=10, md5="", is_archive=True, rel_path="Drive/Set/a.7z")


class TestAStuckJobIsGivenUpOn:
    """Drive answers a flagged file by sending nothing at all, forever."""

    def test_a_job_moving_no_bytes_is_stopped(self, tmp_path):
        rc = SlowRc(bytes_per_poll=0)
        dl = RcloneDownloader(rc=rc, fs="s:", poll_interval=0, stall_timeout=0.05)

        ok, failed = dl.download([_task(tmp_path)], cancel_check=lambda: False)

        assert failed == ["ID"] and not ok
        assert rc.stopped == [1]  # and the job was cancelled, not left running

    def test_a_slow_but_moving_job_is_left_alone(self, tmp_path):
        """Whatever the wall clock says: a 4GB pack on a bad line is not stuck."""
        import time
        rc = SlowRc(bytes_per_poll=1)
        dl = RcloneDownloader(rc=rc, fs="s:", poll_interval=0,
                              stall_timeout=0.05, max_wait=0.2)

        started = time.time()
        dl.download([_task(tmp_path)], cancel_check=lambda: False)

        # It ran to the max_wait ceiling, not the stall timeout four times shorter.
        assert time.time() - started >= 0.2

    def test_bytes_are_reported_as_they_move(self, tmp_path):
        rc = SlowRc(bytes_per_poll=5)
        dl = RcloneDownloader(rc=rc, fs="s:", poll_interval=0,
                              stall_timeout=0.05, max_wait=0.05)
        seen = []

        dl.download([_task(tmp_path)], cancel_check=lambda: False,
                    on_bytes=lambda task, sent: seen.append(sent))

        assert seen and seen == sorted(seen)

    def test_an_rclone_that_cannot_report_bytes_is_not_killed_as_stalled(self, tmp_path):
        """No core_stats means no stall check, not "no progress": otherwise
        every transfer on an older rclone dies at the stall timeout."""
        class NoStatsRc(SlowRc):
            core_stats = None

            def job_status(self, jobid):
                self.polls += 1
                return {"finished": self.polls > 3, "success": True}

        rc = NoStatsRc()
        dl = RcloneDownloader(rc=rc, fs="s:", poll_interval=0, stall_timeout=0)

        ok, failed = dl.download([_task(tmp_path)], cancel_check=lambda: False)

        assert rc.stopped == []
        assert failed == ["ID"]  # no file was delivered, but it was not cut short
