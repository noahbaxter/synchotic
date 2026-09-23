"""Measuring setlists on a worker thread, so the screen showing them never
blocks on a disk walk (seconds per setlist on a network library). The worker
only measures; results come back through a queue and whoever drains it writes
the cache, so the cache stays on one thread.
"""
import queue
import threading


class BackgroundWarmer:
    """Measures setlists on a worker thread; results arrive through `drain`."""

    def __init__(self, compute):
        """`compute(folder, name)` returns the stats for one setlist."""
        self._compute = compute
        self._requests: queue.Queue = queue.Queue()
        self._results: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        self._thread = None
        self._outstanding = 0
        self._lock = threading.Lock()

    def request(self, folder, folder_id: str, names) -> None:
        """Ask for these setlists, oldest request first. Starts the worker."""
        names = list(names)
        if not names:
            return
        with self._lock:
            self._outstanding += len(names)
        for name in names:
            self._requests.put((folder, folder_id, name))
        self._start()

    def _start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="stats-warmer")
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                folder, folder_id, name = self._requests.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                stats = self._compute(folder, name)
            except Exception:
                stats = None  # a setlist we cannot measure is not a crash
            self._results.put((folder_id, name, stats))
            with self._lock:
                self._outstanding -= 1

    def drain(self) -> list:
        """Every result ready right now, as (folder_id, name, stats)."""
        out = []
        while True:
            try:
                out.append(self._results.get_nowait())
            except queue.Empty:
                return out

    @property
    def busy(self) -> bool:
        """True while anything is queued, being measured, or waiting to drain."""
        with self._lock:
            return self._outstanding > 0 or not self._results.empty()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1.0)
