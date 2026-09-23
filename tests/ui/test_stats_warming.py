"""Measuring setlists without freezing the screen: the render thread never
measures anything, it only collects what the worker has finished."""
import threading
import time

from src.ui.screens.stats_warm import BackgroundWarmer


def _wait(predicate, timeout=5.0):
    """Wait on a condition rather than a sleep, so slow machines do not flake."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return False


def _collect(warmer, count, timeout=5.0):
    """Drain until `count` results have arrived, the way on_tick does.

    Waiting for `busy` to go false would hang: it stays true until the results
    are collected, which is what keeps the screen repainting.
    """
    got = []
    deadline = time.time() + timeout
    while len(got) < count and time.time() < deadline:
        got.extend(warmer.drain())
        time.sleep(0.005)
    return got


class TestTheRenderThreadNeverWaits:
    def test_requesting_work_returns_immediately(self):
        """The call that used to take minutes happens on every repaint."""
        started = threading.Event()
        release = threading.Event()

        def slow(folder, name):
            started.set()
            release.wait(5)
            return f"stats:{name}"

        warmer = BackgroundWarmer(slow)
        try:
            t = time.time()
            warmer.request({"name": "Drive"}, "d1", [f"s{i}" for i in range(30)])
            elapsed = time.time() - t

            assert elapsed < 0.5, f"request blocked for {elapsed:.2f}s"
            assert _wait(started.is_set), "worker never picked the job up"
        finally:
            release.set()
            warmer.stop()

    def test_draining_before_anything_is_ready_returns_nothing(self):
        release = threading.Event()
        warmer = BackgroundWarmer(lambda folder, name: release.wait(5))
        try:
            warmer.request({}, "d1", ["a"])
            assert warmer.drain() == []
        finally:
            release.set()
            warmer.stop()


class TestResults:
    def test_measurements_come_back_through_drain(self):
        warmer = BackgroundWarmer(lambda folder, name: f"stats:{name}")
        try:
            warmer.request({}, "d1", ["a", "b", "c"])

            got = _collect(warmer, 3)
            assert sorted(got) == [("d1", "a", "stats:a"),
                                   ("d1", "b", "stats:b"),
                                   ("d1", "c", "stats:c")]
        finally:
            warmer.stop()

    def test_a_second_drain_does_not_repeat_them(self):
        warmer = BackgroundWarmer(lambda folder, name: name)
        try:
            warmer.request({}, "d1", ["a"])
            _collect(warmer, 1)

            assert warmer.drain() == []
        finally:
            warmer.stop()

    def test_busy_is_true_until_the_last_result_is_collected(self):
        """The screen repaints while this is true, so it must cover the gap
        between the worker finishing and the render collecting."""
        warmer = BackgroundWarmer(lambda folder, name: name)
        try:
            warmer.request({}, "d1", ["a"])
            assert _wait(lambda: warmer._results.qsize() == 1)
            assert warmer.busy

            warmer.drain()
            assert not warmer.busy
        finally:
            warmer.stop()


class TestFailures:
    def test_a_setlist_that_cannot_be_measured_does_not_kill_the_worker(self):
        """An unreadable folder is a row without numbers, not a dead screen."""
        def compute(folder, name):
            if name == "bad":
                raise OSError("unreadable")
            return f"stats:{name}"

        warmer = BackgroundWarmer(compute)
        try:
            warmer.request({}, "d1", ["bad", "good"])

            assert sorted(_collect(warmer, 2)) == [("d1", "bad", None),
                                              ("d1", "good", "stats:good")]
        finally:
            warmer.stop()

    def test_stopping_twice_is_harmless(self):
        warmer = BackgroundWarmer(lambda folder, name: name)
        warmer.stop()
        warmer.stop()
