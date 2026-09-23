"""The pre-sync prompt: what is wrong, where charts go, what is left on disk.
Defaults to No, and does not appear when there is nothing to say."""
import io
from contextlib import redirect_stdout

from src import copy
from src.sync.preflight import GB, Concern
from src.ui.screens.preflight import confirm_sync


def _run(concerns, answer=True):
    asked = []

    def dialog(title, message):
        asked.append((title, message))
        return answer

    out = io.StringIO()
    with redirect_stdout(out):
        ok = confirm_sync(concerns, destination="/Users/noah/Clone Hero/Songs",
                          free_bytes=18 * GB, ask=dialog, pause=lambda *_: None)
    return ok, out.getvalue(), asked


SPACE = Concern("space", "Not enough space for this sync",
                "It needs 40.0 GB and there is 18.2 GB free.")
PURGE = Concern("purge", "This sync deletes 1,204 charts",
                "About 86.0 GB in drives Synchotic manages.")


def test_nothing_to_say_means_no_prompt_at_all():
    ok, printed, asked = _run([])
    assert ok is True
    assert printed == ""
    assert asked == []


def test_every_concern_is_shown_before_the_question():
    _, printed, _ = _run([SPACE, PURGE])
    for concern in (SPACE, PURGE):
        assert concern.headline in printed
        assert concern.detail in printed


def test_the_destination_and_what_is_left_are_on_screen():
    """Where the charts go is the question people ask after starting a sync."""
    _, printed, _ = _run([SPACE])
    assert "/Users/noah/Clone Hero/Songs" in printed
    assert "18.0 GB" in printed


class TestABlockerIsNotAQuestion:
    """A sync that cannot work has no "anyway": asking would offer a choice
    where there isn't one, and the answer people need is the fix."""

    BLOCKER = Concern("mode_rclone", "rclone is not connected",
                      "Large charts come through rclone in this mode.",
                      fix="Account → Connect rclone.", severity="block")

    def test_it_never_asks(self):
        ok, printed, asked = _run([self.BLOCKER])
        assert ok is False
        assert asked == []
        assert copy.PRE_TITLE_BLOCKED in printed

    def test_the_fix_is_on_screen(self):
        _, printed, _ = _run([self.BLOCKER])
        assert "Account → Connect rclone." in printed

    def test_a_warning_alongside_it_is_still_shown(self):
        _, printed, _ = _run([self.BLOCKER, SPACE])
        assert SPACE.headline in printed

    def test_warnings_alone_still_ask(self):
        ok, _, asked = _run([SPACE], answer=True)
        assert ok is True and len(asked) == 1


def test_a_fix_is_printed_for_warnings_too():
    warned = Concern("space", "Not enough space", "It needs 40.0 GB.",
                     fix="Free up space, or turn off drives you do not need.")
    _, printed, _ = _run([warned])
    assert "Free up space" in printed


def test_answering_no_stops_the_sync():
    ok, _, _ = _run([SPACE], answer=False)
    assert ok is False


def test_answering_yes_lets_it_run():
    ok, _, _ = _run([SPACE], answer=True)
    assert ok is True


class TestTheRealDialog:
    """The prompt above takes an injected asker, so pin the real one too."""

    def test_escape_means_no(self, monkeypatch):
        """Backing out of a destructive prompt must never mean yes."""
        from src.ui.widgets.confirm import ConfirmDialog

        monkeypatch.setattr("chotic_ui.widgets.confirm.Menu.run", lambda self, *a, **k: None)
        assert ConfirmDialog("Sync anyway?", "").run() is False

    def test_no_is_what_the_cursor_starts_on(self):
        """Enter on a prompt nobody read has to be the harmless answer."""
        from chotic_ui.widgets.confirm import ConfirmDialog as Vendored

        captured = {}

        class FakeMenu:
            def __init__(self, title="", subtitle=""):
                captured["items"] = []

            def add_item(self, item):
                captured["items"].append(item)

            def run(self):
                return None

        import chotic_ui.widgets.confirm as confirm_module
        original = confirm_module.Menu
        confirm_module.Menu = FakeMenu
        try:
            Vendored("Sync anyway?", "").run()
        finally:
            confirm_module.Menu = original

        assert captured["items"][0].value is False
