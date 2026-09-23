"""Puts sync frames on the terminal: drawn once, then the same rows rewritten
in place, so the list never scrolls the terminal. Piped output gets one plain
line per resolved row instead.
"""
import shutil
import sys
import threading

from ..primitives import strip_ansi
from .sync_screen import ACTIVE, OVERFLOW, CHROME_LINES

REFRESH_HZ = 10  # slower and the bars visibly step


def _terminal_size() -> tuple[int, int]:
    size = shutil.get_terminal_size(fallback=(80, 24))
    return size.columns, size.lines


class ScreenPainter:
    """Draws a SyncScreen, in place on a terminal or as lines to a pipe."""

    def __init__(self, screen, write=None, size=None, is_tty=None):
        self.screen = screen
        self._write = write or (lambda text: sys.stdout.write(text))
        self._size = size or _terminal_size
        if is_tty is None:
            is_tty = bool(sys.__stdout__ and sys.__stdout__.isatty())
        self.is_tty = is_tty
        self._drawn = 0          # rows currently held by the frame
        self._last_size = None
        self._logged: set[int] = set()
        self._lock = threading.Lock()

    # -- in place ---------------------------------------------------------

    def _frame_size(self) -> tuple[int, int]:
        width, height = self._size()
        # One row is left free so the shell prompt has somewhere to sit.
        height = max(8, height - 1)
        total = self.screen.total_files
        if not total and not self.screen.entries.count():
            # Compact while there is nothing to list: a screen of blank rows
            # looks hung. It grows once, not a row at a time, since every size
            # change costs a full redraw.
            return max(40, width), min(height, self.screen.compact_height())
        if total:
            # No taller than the run could ever need.
            height = max(8, min(height, total + CHROME_LINES))
        return max(40, width), height

    def paint(self) -> None:
        """Draw the current state. Safe to call from any thread."""
        with self._lock:
            if not self.is_tty:
                self._log_new_rows()
                return

            width, height = self._frame_size()
            if self._last_size not in (None, (width, height)):
                # A resized terminal leaves the old block's rows behind.
                self._write("\x1b[2J\x1b[H")
                self._drawn = 0
            self._last_size = (width, height)

            if self._drawn:
                self._write(f"\x1b[{self._drawn}A")
            for line in self.screen.frame(width, height):
                self._write(f"\r{line}\x1b[K\n")
            self._drawn = height

    def close(self) -> None:
        """Stop owning the block and leave the last frame where it is."""
        with self._lock:
            if self.is_tty and self._drawn:
                self._write("\n")
            self._drawn = 0

    # -- piped ------------------------------------------------------------

    def _log_new_rows(self) -> None:
        """One line per chart that has resolved since the last call."""
        # By identity, not key: notes reuse names ("Purge", a drive's name)
        # that an earlier row already logged under.
        for entry in self.screen.entries.ordered():
            if entry.state in (ACTIVE, OVERFLOW) or id(entry) in self._logged:
                continue
            self._logged.add(id(entry))
            context = f"[{entry.context}] " if entry.context else ""
            if entry.reason:
                self._write(f"  {entry.position}. {context}{entry.name}"
                            f" - {entry.reason}\n")
            else:
                self._write(f"  {entry.position}. {context}{entry.name}\n")


class PaintLoop:
    """Repaints on a timer for as long as the sync is running."""

    def __init__(self, painter: ScreenPainter, hz: int = REFRESH_HZ):
        self.painter = painter
        self._interval = 1.0 / hz
        self._stop = threading.Event()
        self._thread = None

    def start(self) -> "PaintLoop":
        self.painter.paint()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                self.painter.paint()
            except OSError:
                return  # terminal went away

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1.0)
        self.painter.paint()
        self.painter.close()

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()
        return False


def plain(line: str) -> str:
    """The line as it would look without colour, for logs and tests."""
    return strip_ansi(line)
