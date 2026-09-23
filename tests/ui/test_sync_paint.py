"""Painting the frame in place, and one plain line per row when piped."""
import re

from src.ui.widgets.sync_paint import ScreenPainter
from src.ui.widgets.sync_screen import CHROME_LINES, SyncScreen

# strip_ansi in the primitives only drops colour (…m). Cursor moves and clears
# are the point here, so the helper has to drop every CSI sequence.
CSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


class Terminal:
    """Somewhere to write to, and a size that the test can change."""

    def __init__(self, width=78, height=20):
        self.written = []
        self.size = (width, height)

    def write(self, text):
        self.written.append(text)

    def out(self):
        return "".join(self.written)

    def lines(self):
        return [ln.lstrip("\r") for ln in CSI.sub("", self.out()).split("\n")]


def _screen(charts, done=3):
    screen = SyncScreen(title="Drummer's Monthly")
    screen.set_totals(files=len(charts), total_bytes=sum(c.size for c in charts))
    for chart in charts[:done]:
        screen.entries.start(chart.key, chart.name, chart.context, chart.size)
        screen.entries.finish(chart.key)
    return screen


class TestPaintingInPlace:
    def test_the_frame_fills_the_terminal_bar_one_row(self, charts):
        """The spare row is where the shell prompt lands when the sync ends."""
        term = Terminal(height=14)
        painter = ScreenPainter(_screen(charts), write=term.write,
                                size=lambda: term.size, is_tty=True)
        painter.paint()

        drawn = [ln for ln in term.lines() if ln.startswith(("╭", "│", "├", "╰"))]
        assert len(drawn) == 13
        assert drawn[0].startswith("╭") and drawn[-1].startswith("╰")

    def test_repainting_returns_to_the_top_instead_of_scrolling(self, charts):
        term = Terminal(height=14)
        painter = ScreenPainter(_screen(charts), write=term.write,
                                size=lambda: term.size, is_tty=True)
        painter.paint()
        term.written.clear()
        painter.paint()

        assert "\x1b[13A" in term.out(), "expected the cursor to go back up 13 rows"

    def test_a_resized_terminal_is_redrawn_from_scratch(self, charts):
        """Leftovers from the taller frame would otherwise sit under the new one."""
        term = Terminal(height=20)
        painter = ScreenPainter(_screen(charts), write=term.write,
                                size=lambda: term.size, is_tty=True)
        painter.paint()
        term.size = (78, 12)
        term.written.clear()
        painter.paint()

        assert "\x1b[2J" in term.out() or "\x1b[J" in term.out()
        assert len([ln for ln in term.lines() if ln.startswith("╭")]) == 1

    def test_a_small_run_does_not_reserve_a_full_screen_box(self, charts):
        """4 files on a 70-row terminal used to draw 69 rows, most of them
        blank padding below the last entry."""
        term = Terminal(height=70)
        small = charts[:4]
        painter = ScreenPainter(_screen(small, done=4), write=term.write,
                                size=lambda: term.size, is_tty=True)
        painter.paint()

        drawn = [ln for ln in term.lines() if ln.startswith(("╭", "│", "├", "╰"))]
        assert len(drawn) == CHROME_LINES + 4  # 4 entries, no blank padding

    def test_a_run_with_nothing_to_show_yet_stays_small(self):
        """Checking a library that is mostly current produces no charts for
        minutes. Sixty blank rows under a "checking..." caption is what a hung
        app looks like, which is the call we want nobody to have to make."""
        term = Terminal(height=64)
        screen = SyncScreen()
        screen.phase = "DOWNLOAD"
        screen.run_total, screen.run_done = 80, 11
        painter = ScreenPainter(screen, write=term.write,
                                size=lambda: term.size, is_tty=True)
        painter.paint()

        drawn = [ln for ln in term.lines() if ln.startswith(("╭", "│", "├", "╰"))]
        assert len(drawn) == screen.compact_height(), (
            f"drew {len(drawn)} rows for an empty run")
        assert len(drawn) < term.size[1] // 2, "still most of the screen"
        assert any("nothing to download yet" in ln for ln in drawn), (
            "an empty body has to say why it is empty")

    def test_it_opens_out_once_there_are_charts(self, charts):
        """The small box is for the wait, not for the download that follows."""
        term = Terminal(height=64)
        painter = ScreenPainter(_screen(charts), write=term.write,
                                size=lambda: term.size, is_tty=True)
        painter.paint()

        drawn = [ln for ln in term.lines() if ln.startswith(("╭", "│", "├", "╰"))]
        assert len(drawn) == 63

    def test_closing_leaves_the_finished_frame_on_screen(self, charts):
        """The summary is the last thing drawn, so it should survive the exit."""
        term = Terminal(height=14)
        painter = ScreenPainter(_screen(charts), write=term.write,
                                size=lambda: term.size, is_tty=True)
        painter.paint()
        term.written.clear()
        painter.close()

        assert "╭" not in term.out()
        assert term.out().endswith("\n")


class TestPipedOutput:
    def test_no_escape_codes_reach_a_pipe(self, charts):
        term = Terminal()
        painter = ScreenPainter(_screen(charts), write=term.write,
                                size=lambda: term.size, is_tty=False)
        painter.paint()

        assert "\x1b[" not in term.out()

    def test_each_finished_chart_gets_one_line(self, charts):
        screen = _screen(charts, done=0)
        term = Terminal()
        painter = ScreenPainter(screen, write=term.write,
                                size=lambda: term.size, is_tty=False)

        for chart in charts[:3]:
            screen.entries.start(chart.key, chart.name, chart.context, chart.size)
            screen.entries.finish(chart.key)
            painter.paint()
        painter.paint()  # nothing new; nothing more to say

        assert len([ln for ln in term.out().split("\n") if ln.strip()]) == 3

    def test_a_failure_says_why_in_the_log(self, charts):
        screen = _screen(charts, done=0)
        term = Terminal()
        painter = ScreenPainter(screen, write=term.write,
                                size=lambda: term.size, is_tty=False)

        chart = charts[0]
        screen.entries.start(chart.key, chart.name, chart.context, chart.size)
        screen.entries.fail(chart.key, "needs sign-in")
        painter.paint()

        assert "needs sign-in" in term.out()

    def test_two_notes_with_the_same_name_both_reach_the_log(self):
        """A drive's name can label a download row and later its purge result."""
        from src.ui.widgets.sync_screen import SyncScreen
        screen = SyncScreen()
        term = Terminal()
        painter = ScreenPainter(screen, write=term.write,
                                size=lambda: term.size, is_tty=False)

        screen.entries.note("Drive", name="Drive", context="already synced")
        painter.paint()
        screen.entries.note("Drive", name="Drive", context="3 purged")
        painter.paint()

        assert "already synced" in term.out() and "3 purged" in term.out()
