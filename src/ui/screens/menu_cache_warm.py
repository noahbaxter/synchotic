"""Recomputing the main menu cache on a worker thread.

A background scan finishing triggers a full recompute, which measures any
setlist not yet measured: up to 25s mid-scan. Run inside on_tick that blocked
the key loop long enough for buffered arrow keys to merge into escape
sequences nobody recognised. The worker recomputes; on_tick only copies a
finished result onto the live cache.
"""
import threading


class MenuCacheWarmer:
    """Recomputes the main menu cache on a worker thread whenever the
    scanner reports a change; on_tick only ever drains a finished result."""

    def __init__(self, scanner_changed, compute, poll_s: float = 0.25):
        """`scanner_changed()` returns True once per real change (consumes
        it, same contract as BackgroundScanner.check_updates). `compute()`
        returns the freshly computed cache."""
        self._scanner_changed = scanner_changed
        self._compute = compute
        self._poll_s = poll_s
        self._lock = threading.Lock()
        self._ready = None
        self._generation = 0
        self._retry = False
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="menu-cache-warmer")
        self._thread.start()

    def invalidate(self) -> None:
        """Settings changed on the screen's own thread (a toggle). A result
        computed from the old settings would overwrite the toggle's fresh
        numbers, so drop it and recompute once more."""
        with self._lock:
            self._generation += 1
            if self._ready is not None:
                self._ready = None
                self._retry = True

    def _run(self) -> None:
        while not self._stop.is_set():
            with self._lock:
                retry, self._retry = self._retry, False
                generation = self._generation
            try:
                changed = self._scanner_changed() or retry
            except Exception:
                changed = retry
            if changed:
                try:
                    result = self._compute()
                except Exception:
                    result = None  # a recompute that cannot run is not a crash
                with self._lock:
                    if generation != self._generation:
                        self._retry = True  # started before a toggle: stale
                    elif result is not None:
                        self._ready = result
            if self._stop.wait(self._poll_s):
                return

    def drain(self):
        """The freshly computed cache if one landed since the last drain,
        else None."""
        with self._lock:
            result, self._ready = self._ready, None
            return result

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=1.0)
