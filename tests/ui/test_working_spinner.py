"""The spinner shown while something reads a disk."""
import io

import pytest

from src.ui.primitives import working


class _Tty(io.StringIO):
    def isatty(self):
        return True


class _Pipe(io.StringIO):
    def isatty(self):
        return False


class TestItStaysOutOfTheWay:
    def test_it_returns_what_the_work_returned(self):
        assert working("reading", lambda: "answer", out=_Tty()) == "answer"

    def test_quick_work_draws_nothing(self):
        """Below the threshold a spinner is a flicker, not information."""
        out = _Tty()
        working("reading", lambda: 1, out=out)
        assert out.getvalue() == ""

    def test_a_pipe_is_never_animated(self, monkeypatch):
        """Redirected output gets the answer, not a thousand spinner frames."""
        import time
        monkeypatch.setattr("src.ui.primitives.spinner.QUIET", 0)
        out = _Pipe()

        def slow():
            time.sleep(0.05)
            return 2

        assert working("reading", slow, out=out) == 2
        assert out.getvalue() == ""


class TestSlowWork:
    def _slow(self, monkeypatch):
        monkeypatch.setattr("src.ui.primitives.spinner.QUIET", 0)
        monkeypatch.setattr("src.ui.primitives.spinner.TICK", 0.01)

    def test_it_draws_the_label_while_it_waits(self, monkeypatch):
        import time
        self._slow(monkeypatch)
        out = _Tty()

        working("reading /songs", lambda: time.sleep(0.05), out=out)

        assert "reading /songs" in out.getvalue()

    def test_it_wipes_the_line_afterwards(self, monkeypatch):
        import time
        self._slow(monkeypatch)
        out = _Tty()

        working("reading", lambda: time.sleep(0.05), out=out)

        # Ends on a carriage return over blanks, so the next screen starts
        # on a clean line rather than under half a spinner.
        assert out.getvalue().endswith("\r")


class TestFailures:
    def test_an_error_reaches_the_caller(self, monkeypatch):
        """Swallowed on the worker thread, it would look like the work
        returned None and the caller would carry on with nothing."""
        monkeypatch.setattr("src.ui.primitives.spinner.QUIET", 0)

        def boom():
            raise RuntimeError("disk went away")

        with pytest.raises(RuntimeError, match="disk went away"):
            working("reading", boom, out=_Tty())
