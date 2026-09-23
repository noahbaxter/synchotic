"""The scan-triggered menu recompute runs on a worker. on_tick only drains a
finished result, and a toggle made while one is in flight must not be painted
over by numbers computed before it."""
import threading
import time

from src.ui.screens.menu_cache_warm import MenuCacheWarmer


def _wait(predicate, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return False


class _Once:
    """scanner_changed that reports one change, then nothing."""

    def __init__(self):
        self.fired = False

    def __call__(self):
        if self.fired:
            return False
        self.fired = True
        return True


def test_a_scan_change_is_recomputed_and_drained_once():
    warmer = MenuCacheWarmer(_Once(), lambda: "fresh", poll_s=0.01)
    try:
        got = []
        assert _wait(lambda: got.append(warmer.drain()) or got[-1] == "fresh")
        assert warmer.drain() is None
    finally:
        warmer.stop()


def test_draining_never_waits_for_the_recompute():
    release = threading.Event()
    warmer = MenuCacheWarmer(_Once(), lambda: release.wait(5) and "fresh", poll_s=0.01)
    try:
        t = time.time()
        assert warmer.drain() is None
        assert time.time() - t < 0.5
    finally:
        release.set()
        warmer.stop()


def test_a_toggle_mid_recompute_throws_the_stale_result_away():
    started, release = threading.Event(), threading.Event()
    results = iter(["computed before the toggle", "computed after it"])

    def compute():
        started.set()
        release.wait(5)
        return next(results)

    warmer = MenuCacheWarmer(_Once(), compute, poll_s=0.01)
    try:
        assert _wait(started.is_set)
        warmer.invalidate()
        release.set()
        got = []
        assert _wait(lambda: got.append(warmer.drain()) or got[-1] is not None)
        assert got[-1] == "computed after it"
    finally:
        release.set()
        warmer.stop()


def test_a_toggle_discards_a_result_that_was_not_collected_yet():
    results = iter(["before", "after"])
    warmer = MenuCacheWarmer(_Once(), lambda: next(results), poll_s=0.01)
    try:
        assert _wait(lambda: warmer._ready is not None)
        warmer.invalidate()
        got = []
        assert _wait(lambda: got.append(warmer.drain()) or got[-1] is not None)
        assert got[-1] == "after"
    finally:
        warmer.stop()
