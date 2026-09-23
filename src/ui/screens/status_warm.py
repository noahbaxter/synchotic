"""Checking rclone and library status on a worker thread.

`rclone.is_authed()` shells out to `rclone config dump` (up to 10s) and
`library_blocked_reason()` stats a library that can be a network mount with no
timeout. The home screen rebuilds its rows every frame on the same loop that
reads keys, so either check there freezes the screen. The worker rechecks on an
interval and the screen reads the last snapshot.
"""
import threading
from dataclasses import dataclass


@dataclass(frozen=True)
class StatusSnapshot:
    rclone_connected: bool
    library_blocked: str


class StatusWarmer:
    """Recomputes a StatusSnapshot on a worker thread every `interval_s`."""

    def __init__(self, compute, interval_s: float = 3.0):
        """`compute()` returns a StatusSnapshot. The first check starts at once."""
        self._compute = compute
        self._interval_s = interval_s
        self._lock = threading.Lock()
        self._snapshot = StatusSnapshot(rclone_connected=False, library_blocked="")
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="status-warmer")
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                snapshot = self._compute()
            except Exception:
                snapshot = None  # a check that cannot run is not a crash
            if snapshot is not None:
                with self._lock:
                    self._snapshot = snapshot
            if self._stop.wait(self._interval_s):
                return

    @property
    def snapshot(self) -> StatusSnapshot:
        with self._lock:
            return self._snapshot

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=1.0)
