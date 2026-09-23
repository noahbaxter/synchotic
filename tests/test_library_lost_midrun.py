"""A library that goes away mid-run ends with a message, not a traceback."""
import io
import os
from contextlib import redirect_stdout

import pytest

import sync as sync_entry
from src.core.paths import LibraryUnavailable
from src.ui.widgets import display


def _run_cli(monkeypatch, raise_with):
    """Run the entry point with a main() that fails the way we care about."""
    def boom():
        raise raise_with

    # cli() does setdefault on this, which would leave every test after this
    # one resolving paths in the real user data dir. Setting it through
    # monkeypatch pins it for this test and puts it back afterwards.
    monkeypatch.setenv("SYNCHOTIC_OS_DIRS", os.environ.get("SYNCHOTIC_OS_DIRS", "0"))
    monkeypatch.setattr(sync_entry, "main", boom)
    monkeypatch.setattr("chotic_ui.primitives.host.leave_alt_screen", lambda: None)

    out = io.StringIO()
    with redirect_stdout(out):
        with pytest.raises(SystemExit) as exit_info:
            sync_entry.cli()
    return exit_info.value.code, out.getvalue()


def test_it_says_what_happened_instead_of_a_traceback(monkeypatch):
    code, printed = _run_cli(monkeypatch, LibraryUnavailable("gone"))

    assert code == 1
    assert "Library disconnected" in printed
    assert "Traceback" not in printed


def test_it_tells_the_user_what_to_do(monkeypatch):
    _, printed = _run_cli(monkeypatch, LibraryUnavailable("gone"))
    assert "Reconnect the drive" in printed


def test_it_does_not_claim_nothing_happened(monkeypatch):
    """The startup wording promises nothing has been downloaded or deleted.
    Mid-run that is a lie, and the two messages must not be swapped."""
    _, printed = _run_cli(monkeypatch, LibraryUnavailable("gone"))
    assert "Nothing has been scanned" not in printed


def test_cancelling_still_exits_cleanly(monkeypatch):
    """The handler sits next to the KeyboardInterrupt one, so pin that it
    did not swallow it."""
    code, printed = _run_cli(monkeypatch, KeyboardInterrupt())
    assert code == 0
    assert "Cancelled by user" in printed


def test_the_two_library_messages_stay_different():
    """Startup can promise nothing has happened yet. Mid-run cannot."""
    startup, lost = io.StringIO(), io.StringIO()
    with redirect_stdout(startup):
        display.library_unavailable("/Volumes/Charts")
    with redirect_stdout(lost):
        display.library_lost("/Volumes/Charts")

    assert "Nothing has been scanned" in startup.getvalue()
    assert "Nothing has been scanned" not in lost.getvalue()
