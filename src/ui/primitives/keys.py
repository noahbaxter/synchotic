"""Keys read during a sync. Unlike chotic-ui's EscMonitor, arrows and paging
are decoded (the screen scrolls and filters) while a lone ESC still cancels.
Decoding is separate from reading so it can be tested without a terminal.
"""
import os
import sys
import threading
from typing import Callable, Optional

CANCEL = "cancel"
UP = "up"
DOWN = "down"
PAGE_UP = "page_up"
PAGE_DOWN = "page_down"
HOME = "home"
END = "end"

_SEQUENCES = {
    "[A": UP,
    "[B": DOWN,
    "[5~": PAGE_UP,
    "[6~": PAGE_DOWN,
    "[H": HOME,
    "[1~": HOME,
    "[F": END,
    "[4~": END,
    "OH": HOME,
    "OF": END,
}


def decode(first: str, extra: str = "") -> Optional[str]:
    """Turn a keypress into a name, or None for anything we do not handle.

    `extra` is whatever followed an ESC. Empty means ESC was pressed alone,
    which is the one case that must not be confused with an arrow.
    """
    if first == "\x1b":
        if not extra:
            return CANCEL
        return _SEQUENCES.get(extra)
    if first.isalpha():
        return first.lower()
    return None


class KeyMonitor:
    """Calls `on_key` with a decoded key name until stopped."""

    def __init__(self, on_key: Callable[[str], None]):
        self.on_key = on_key
        self._stop = threading.Event()
        self._thread = None

    def start(self) -> "KeyMonitor":
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=0.5)

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()
        return False

    def _run(self) -> None:
        try:
            if os.name == "nt":
                self._run_windows()
            else:
                self._run_unix()
        except Exception:
            return  # no console to read from; the sync carries on regardless

    def _run_windows(self) -> None:
        import msvcrt
        import time

        while not self._stop.is_set():
            if not msvcrt.kbhit():
                time.sleep(0.05)
                continue
            char = msvcrt.getch()
            if char in (b"\x00", b"\xe0"):
                mapped = {b"H": UP, b"P": DOWN, b"I": PAGE_UP, b"Q": PAGE_DOWN,
                          b"G": HOME, b"O": END}.get(msvcrt.getch())
                if mapped:
                    self.on_key(mapped)
                continue
            if char == b"\x1b":
                self.on_key(CANCEL)
                continue
            try:
                key = decode(char.decode("utf-8", "ignore"))
            except Exception:
                key = None
            if key:
                self.on_key(key)

    def _run_unix(self) -> None:
        import select
        import termios

        from chotic_ui.primitives.keyboard_input import read_escape_sequence

        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            # ECHO off as well as ICANON, or keys print raw bytes under the frame.
            new_settings = termios.tcgetattr(fd)
            new_settings[3] = new_settings[3] & ~(termios.ECHO | termios.ICANON)
            termios.tcsetattr(fd, termios.TCSANOW, new_settings)
            while not self._stop.is_set():
                if not select.select([sys.stdin], [], [], 0.05)[0]:
                    continue
                char = sys.stdin.read(1)
                extra = read_escape_sequence(fd) if char == "\x1b" else ""
                key = decode(char, extra)
                if key:
                    self.on_key(key)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
