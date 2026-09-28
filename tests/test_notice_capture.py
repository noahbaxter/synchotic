"""The notice capture sits outside the log tee, and the log must not notice.

sync.py wraps sys.stdout twice: TeeOutput copies to the log file, and chotic-ui's
notice capture keeps unread lines for the next screen. Everything printed has
to reach the log as before, and debug_log finds the tee by its log_only, which
now sits one wrapper down.
"""
import io
import sys

import pytest

from chotic_ui.primitives import notices
from src.core.logging import TeeOutput, debug_log


@pytest.fixture
def wrapped(tmp_path):
    """Wraps stdout as sync.py does. A context manager used inside the test:
    pytest puts its own sys.stdout back between fixture setup and the call."""
    import contextlib

    @contextlib.contextmanager
    def wrap():
        saved = sys.stdout
        terminal = io.StringIO()
        sys.stdout = terminal
        log = tmp_path / "session.log"
        tee = TeeOutput(log, version="test")
        sys.stdout = tee
        notices.mark_read()
        notices.install()
        try:
            yield terminal, log
        finally:
            sys.stdout = saved
            notices.mark_read()
            tee.close()
    return wrap


def test_printed_lines_still_reach_the_log_and_the_terminal(wrapped):
    with wrapped() as (terminal, log):
        print("Library not connected")
        assert "Library not connected" in terminal.getvalue()
        assert "Library not connected" in log.read_text()


def test_debug_log_still_finds_the_tee(wrapped):
    with wrapped() as (terminal, log):
        debug_log("[timing] drives: 3ms")
        assert "[timing] drives: 3ms" in log.read_text()
        assert "[timing]" not in terminal.getvalue()
        assert notices.take() == [], "a debug line is never a notice"


def test_what_was_printed_is_kept_for_the_next_screen(wrapped):
    with wrapped():
        print("Library not connected")
        assert notices.take() == ["Library not connected"]
