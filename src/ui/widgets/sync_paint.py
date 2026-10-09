"""Puts sync frames on the terminal: drawn once, then the same rows rewritten
in place, so the list never scrolls the terminal. Piped output gets one plain
line per resolved row instead.
"""
import shutil
import sys
import threading

from chotic_ui.primitives.terminal import truncate_ansi

from ..primitives import strip_ansi
from .sync_screen import ACTIVE, OVERFLOW, CHROME_LINES

REFRESH_HZ = 10  # slower and the bars visibly step
MIN_FRAME = CHROME_LINES + 1  # the header, one list row and the bottom border


def _write_stdout(text: str) -> None:
    # Flushed: a write with no newline in it (the clear for a too-short
    # window) would otherwise sit in the line buffer.
    sys.stdout.write(text)
    sys.stdout.flush()


def _terminal_size() -> tuple[int, int]:
    size = shutil.get_terminal_size(fallback=(80, 24))
    return size.columns, size.lines


class ScreenPainter:
    """Draws a SyncScreen, in place on a terminal or as lines to a pipe."""

    def __init__(self, screen, write=None, size=None, is_tty=None,
                 banner_text=None, banner_rows=None):
        """`banner_text()` and `banner_rows()` are the app banner sitting above
        the frame, as every other screen has it. The frame fits under it, and a
        redraw from scratch puts it back rather than wiping it."""
        self.screen = screen
        self._write = write or _write_stdout
        self._size = size or _terminal_size
        self._banner_text = banner_text or (lambda: "")
        self._banner_rows = banner_rows or (lambda: 0)
        if is_tty is None:
            is_tty = bool(sys.__stdout__ and sys.__stdout__.isatty())
        self.is_tty = is_tty
        self._drawn = 0          # rows currently held by the frame
        self._last_size = None
        self._logged: set[int] = set()
        self._lock = threading.Lock()

    # -- in place ---------------------------------------------------------

    def _frame_size(self) -> tuple[int, int, bool] | None:
        """(width, height, banner shown), or None when the terminal is too
        short for any frame. A frame taller than the terminal scrolls on every
        paint, so it is never drawn."""
        width, rows = self._size()
        # One row is left free so the shell prompt has somewhere to sit, and the
        # banner keeps its rows above.
        height = rows - 1 - self._banner_rows()
        banner = True
        if height < MIN_FRAME:
            banner, height = False, rows - 1  # the frame matters more
        if height < MIN_FRAME:
            return None
        total = self.screen.total_files
        if not total and not self.screen.entries.count():
            # Compact while there is nothing to list: a screen of blank rows
            # looks hung. It grows once, not a row at a time, since every size
            # change costs a full redraw.
            return max(40, width), min(height, self.screen.compact_height()), banner
        if total:
            # No taller than the run could ever need.
            height = max(MIN_FRAME, min(height, total + CHROME_LINES))
        return max(40, width), height, banner

    def paint(self) -> None:
        """Draw the current state. Safe to call from any thread."""
        with self._lock:
            if not self.is_tty:
                self._log_new_rows()
                return

            layout = self._frame_size()
            if layout is None:
                # Too short for any frame: leave the screen blank until it grows.
                cols, rows = self._size()
                if self._last_size != ("small", cols, rows):
                    self._write("\x1b[2J\x1b[H")
                self._last_size = ("small", cols, rows)
                self._drawn = 0
                return
            width, height, banner = layout
            first_without_banner = self._last_size is None and not banner
            if first_without_banner or self._last_size not in (None, (width, height, banner)):
                # A resized terminal leaves the old block's rows behind. Every
                # run resizes once too, when the compact frame opens out, so
                # clearing without the banner lost it for the whole sync.
                self._write("\x1b[2J\x1b[H" + (self._banner_text() if banner else ""))
                self._drawn = 0
            self._last_size = (width, height, banner)

            if self._drawn:
                self._write(f"\x1b[{self._drawn}A")
            # The frame is never narrower than 40; clipped, so a line that
            # wrapped cannot push the frame down a row on every paint.
            cols = self._size()[0]
            for line in self.screen.frame(width, height):
                self._write(f"\r{truncate_ansi(line, cols)}\x1b[K\n")
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
