"""The rclone and library checks run on a worker; the screen only reads the
last snapshot, so a stalled mount or a slow `rclone config dump` never blocks it."""
import threading
import time

from src.ui.screens.status_warm import StatusSnapshot, StatusWarmer


def _wait(predicate, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return False


def test_reading_the_snapshot_never_waits_for_a_check():
    release = threading.Event()

    def slow():
        release.wait(5)
        return StatusSnapshot(rclone_connected=True, library_blocked="")

    warmer = StatusWarmer(slow)
    try:
        t = time.time()
        assert warmer.snapshot == StatusSnapshot(False, "")
        assert time.time() - t < 0.5
    finally:
        release.set()
        warmer.stop()


def test_the_snapshot_follows_the_checks():
    state = {"blocked": "Library not connected"}
    warmer = StatusWarmer(lambda: StatusSnapshot(False, state["blocked"]),
                          interval_s=0.01)
    try:
        assert _wait(lambda: warmer.snapshot.library_blocked == "Library not connected")
        state["blocked"] = ""
        assert _wait(lambda: warmer.snapshot.library_blocked == "")
    finally:
        warmer.stop()


def test_a_failing_check_keeps_the_last_good_snapshot():
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] > 1:
            raise OSError("mount went away")
        return StatusSnapshot(True, "")

    warmer = StatusWarmer(flaky, interval_s=0.01)
    try:
        assert _wait(lambda: calls["n"] > 3)
        assert warmer.snapshot == StatusSnapshot(True, "")
    finally:
        warmer.stop()
