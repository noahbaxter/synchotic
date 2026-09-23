"""The bordered sync frame: exactly the lines asked for, each the full width."""
import re

from src.ui.primitives import strip_ansi
from src.ui.widgets.sync_screen import (CHROME_LINES, HEADER_ROWS, SPINNER,
                                        SyncScreen)


def _body(lines):
    """The list rows only. The tally above the divider carries the same ✓ as a
    finished row, so anything picking rows by glyph has to start below it."""
    plain = [strip_ansi(line) for line in lines]
    divider = next(i for i, line in enumerate(plain) if line.startswith("├"))
    return plain[divider + 1:-1]


def _screen():
    screen = SyncScreen(title="Drummer's Monthly (2/6)")
    screen.set_totals(files=664, total_bytes=31_600_000_000)
    return screen


class TestFrameShape:
    def test_an_overlong_line_is_cut_to_the_box(self):
        """A line that overruns wraps and shunts the whole frame."""
        from src.ui.widgets.sync_screen import _line
        assert len(strip_ansi(_line("x" * 200, 40))) == 40

    def test_frame_is_exactly_the_box_it_was_asked_for(self):
        screen = _screen()
        screen.entries.start("a", "Gojira - Flying Whales", total_bytes=90_000_000)

        for width, height in ((60, 14), (78, 20), (120, 30)):
            lines = screen.frame(width=width, height=height)
            assert len(lines) == height
            assert {len(strip_ansi(line)) for line in lines} == {width}

    def test_a_whole_run_never_renders_a_frame_the_wrong_size(self, charts, seed):
        """Every frame of a real-shaped run, not three rows picked by hand."""
        screen = SyncScreen(title="Drummer's Monthly (2/6)")
        screen.set_totals(files=len(charts), total_bytes=sum(c.size for c in charts))

        live = []
        for chart in charts:
            screen.entries.start(chart.key, chart.name, chart.context, chart.size)
            live.append(chart)
            if len(live) > 24:
                done = live.pop(0)
                screen.entries.finish(done.key)
                screen.downloaded_bytes += done.size
            for width, height in ((60, 12), (78, 20), (140, 40)):
                lines = screen.frame(width=width, height=height)
                assert len(lines) == height, f"seed={seed}"
                assert {len(strip_ansi(line)) for line in lines} == {width}, f"seed={seed}"

    def test_a_narrow_terminal_still_gets_square_borders(self, charts):
        """80 columns is an assumption, not a fact. Half a library, 40 columns."""
        screen = SyncScreen(title="Anti Hero 2 - The Complete Collection (12/12)")
        screen.set_totals(files=len(charts), total_bytes=sum(c.size for c in charts))
        for chart in charts[:60]:
            screen.entries.start(chart.key, chart.name, chart.context, chart.size)
            screen.entries.finish(chart.key)
        for chart in charts[60:63]:
            screen.entries.start(chart.key, chart.name, chart.context, chart.size)
            screen.entries.fail(chart.key, "needs sign-in")
        screen.downloaded_bytes = sum(c.size for c in charts[:60])

        lines = screen.frame(width=40, height=14)
        assert {len(strip_ansi(line)) for line in lines} == {40}

    def test_nothing_is_pressed_against_the_border(self, charts, seed):
        """Text touching the frame reads as if it has been cut off."""
        screen = SyncScreen(title="Drummer's Monthly (2/6)")
        screen.set_totals(files=664, total_bytes=31_600_000_000)
        screen.downloaded_bytes = 14_200_000_000
        for chart in charts[:8]:
            screen.entries.start(chart.key, chart.name, chart.context, chart.size)
            screen.entries.finish(chart.key)
        for chart in charts[8:12]:
            screen.entries.start(chart.key, chart.name, chart.context, chart.size)
            screen.entries.progress(chart.key, chart.size // 3)

        content = [strip_ansi(line) for line in screen.frame(width=78, height=20)
                   if strip_ansi(line).startswith("│")]
        assert content, "no content lines in the frame"
        for plain in content:
            assert plain[1] == " ", f"{plain!r} (seed={seed})"
            assert plain[-2] == " ", f"{plain!r} (seed={seed})"

    def test_the_number_column_fits_the_size_of_the_run(self, charts):
        """A 12,000 chart library numbers past 9999.

        A five digit number in a four wide column does not fail loudly: it
        pushes that one row's columns along and the list stops lining up.
        """
        screen = SyncScreen(title="Everything")
        screen.set_totals(files=12_137, total_bytes=1)
        for chart in charts[:2]:
            screen.entries.start(chart.key, chart.name, chart.context, chart.size)
            screen.entries.finish(chart.key)
        early, late = screen.entries.ordered()[:2]
        early.position, late.position = 1, 12_137

        rows = [line for line in _body(screen.frame(width=100, height=12))
                if "✓" in line]
        assert len(rows) == 2
        assert len({row.index("✓") for row in rows}) == 1

    def test_the_count_appears_with_the_first_chart(self, charts):
        """"✓ 0 charts" is a scoreboard for a race that has not started."""
        screen = SyncScreen(title="Drummer's Monthly")
        screen.set_totals(files=664, total_bytes=31_600_000_000)

        assert "0 charts" not in strip_ansi("\n".join(screen.frame(width=78, height=14)))

        chart = charts[0]
        screen.entries.start(chart.key, chart.name, chart.context, chart.size)
        screen.entries.finish(chart.key)
        assert "✓ 1 chart" in strip_ansi("\n".join(screen.frame(width=78, height=14)))

    def test_short_list_pads_rather_than_shrinking_the_frame(self):
        """A frame that grows as rows arrive judders and leaves debris behind."""
        screen = _screen()
        lines = screen.frame(width=78, height=20)

        assert len(lines) == 20


class TestTheNetworkBox:
    """What the transfer is doing, kept apart from what the run is doing."""

    def _screen_with_traffic(self):
        screen = _screen()
        screen.clock = lambda: 50.0
        screen.speed = 140_000
        screen.last_transfer_at = 50.0
        screen.downloaded_bytes = 8_500_000
        return screen

    def test_the_rate_goes_idle_when_nothing_is_arriving(self):
        """A run that has moved on to checking setlists is not crawling along
        at a few KB/s. It is not downloading anything."""
        screen = self._screen_with_traffic()
        now = [50.0]
        screen.clock = lambda: now[0]

        assert "136.7 KB/s" in strip_ansi("\n".join(screen.frame(width=86, height=16)))

        now[0] += 10
        text = strip_ansi("\n".join(screen.frame(width=86, height=16)))
        assert "-- KB/s" in text
        assert "136.7" not in text, "the last rate outlived the transfer"

    def test_the_byte_total_stays_when_the_rate_goes_idle(self):
        screen = self._screen_with_traffic()
        screen.clock = lambda: 500.0

        text = strip_ansi("\n".join(screen.frame(width=86, height=16)))
        assert "8.1 MB /" in text

    def test_the_rate_and_the_total_sit_in_a_box(self):
        screen = self._screen_with_traffic()
        lines = "\n".join(strip_ansi(ln) for ln in screen.frame(width=86, height=16))

        assert "network" in lines
        assert "KB/s" in lines
        assert re.search(r"\d[\d.]* [KMGT]?B / \d[\d.]* [KMGT]?B", lines), lines

    def test_no_time_remaining_anywhere(self):
        """A guess derived from the other two, and the figure people watch
        instead of the work."""
        lines = "\n".join(strip_ansi(ln) for ln in
                          self._screen_with_traffic().frame(width=86, height=16))

        assert "left" not in lines.split("ESC cancel")[0]

    def test_every_edge_of_the_box_lines_up(self):
        """A box whose rows differ by a column zigzags down the panel."""
        screen = self._screen_with_traffic()
        box = [strip_ansi(ln) for ln in screen._network_box()]

        assert len(box) == 4, f"expected a four-row box, got {len(box)}"
        assert len({len(ln) for ln in box}) == 1, f"rows differ in width: {box}"

        lines = [strip_ansi(ln) for ln in screen.frame(width=86, height=16)]
        start = HEADER_ROWS.index("progress")
        offsets = {lines[start + i].index(row) for i, row in enumerate(box)}
        assert len(offsets) == 1, "the box does not sit in one column"

    def test_a_run_with_no_traffic_gets_no_box(self):
        """Purge moves no bytes; an empty network box is furniture."""
        screen = SyncScreen(title="Purge")

        lines = "\n".join(strip_ansi(ln) for ln in screen.frame(width=86, height=16))

        assert "network" not in lines

    def test_a_narrow_panel_keeps_the_counts_over_the_figures(self):
        screen = self._screen_with_traffic()
        screen.entries.finish("a", name="Chart.7z")

        lines = "\n".join(strip_ansi(ln) for ln in screen.frame(width=56, height=16))

        assert "network" not in lines, "no room for a box at this width"
        assert "✓ 1 chart" in lines, "the counts were clipped for the figures"


class TestTheTally:
    """What this run brought in and what went wrong, in the list's own glyphs."""

    def _header(self, screen):
        lines = [strip_ansi(ln) for ln in screen.frame(width=86, height=16)]
        divider = next(i for i, ln in enumerate(lines) if ln.startswith("├"))
        return "\n".join(lines[:divider])

    def test_charts_and_errors_are_counted_with_their_glyphs(self):
        screen = _screen()
        screen.entries.finish("a", name="A.7z")
        screen.entries.finish("b", name="B.7z")
        screen.entries.fail("c", "timed out", name="C.7z")

        header = self._header(screen)
        assert "✓ 2 charts" in header
        assert "! 1 error" in header and "1 errors" not in header

    def test_setlists_are_left_to_the_bar(self):
        screen = _screen()
        screen.run_total, screen.run_done, screen.run_unit = 80, 68, "setlists"
        screen.entries.finish("a", name="A.7z")

        header = self._header(screen)
        assert "up to date" not in header
        assert header.count("setlists") == 1, "setlists counted twice"


class TestTheAdviceSaysWhoHasToAct:
    """A count of errors leaves the one question that matters unanswered: is
    this mine to fix, or will it sort itself out."""

    def test_nothing_failed_nothing_said(self):
        from src.ui.widgets.sync_display import advise
        assert advise([]) == ("", "", "")

    def test_something_that_passes_says_so(self):
        from src.ui.widgets.sync_display import TRANSIENT, advise
        tone, reason, advice = advise(["rate limited", "rate limited"])
        assert (tone, reason) == (TRANSIENT, "rate limited")
        assert "retries" in advice

    def test_something_you_must_fix_wins_even_when_rarer(self):
        """Nine timeouts and one full disk: the disk is the news."""
        from src.ui.widgets.sync_display import FIX, advise
        tone, reason, _ = advise(["timed out"] * 9 + ["disk full"])
        assert (tone, reason) == (FIX, "disk full")

    def test_the_unexplained_ranks_above_the_passing(self):
        from src.ui.widgets.sync_display import REPORT, advise
        tone, reason, _ = advise(["timed out", "timed out", "unpack failed"])
        assert (tone, reason) == (REPORT, "unpack failed")

    def test_a_reason_nobody_wrote_advice_for_still_gets_some(self):
        from src.ui.widgets.sync_display import REPORT, advise
        tone, reason, advice = advise(["HTTP 418"])
        assert (tone, reason) == (REPORT, "HTTP 418")
        assert advice

    def test_the_panel_carries_it(self):
        screen = _screen()
        screen.entries.fail("c", "disk full", name="C.7z")

        text = strip_ansi("\n".join(screen.frame(width=120, height=16)))
        assert "disk full: Free up space" in text

    def test_a_clean_run_has_no_advice_row_text(self):
        screen = _screen()
        screen.entries.finish("a", name="A.7z")

        text = strip_ansi("\n".join(screen.frame(width=120, height=16)))
        assert ":" not in text.split("├")[0], "advice shown with nothing to advise"


class TestTheChromeCountIsHonest:
    """Every sizing decision is made from CHROME_LINES.

    If the layout grows a row and the count does not follow, the list is handed
    one row more than exists and the bottom of it falls off the frame.
    """

    def test_it_matches_the_rows_actually_drawn(self):
        lines = [strip_ansi(ln) for ln in _screen().frame(width=78, height=30)]
        divider = next(i for i, ln in enumerate(lines) if ln.startswith("├"))

        assert divider + 2 == CHROME_LINES, "header rows and CHROME_LINES disagree"

    def test_the_list_gets_every_row_the_chrome_left(self):
        screen = _screen()
        for i in range(40):
            screen.entries.finish(f"c{i}", name=f"Chart {i}.7z")
        rows = [ln for ln in _body(screen.frame(width=78, height=30)) if " ✓ " in ln]

        assert len(rows) == 30 - CHROME_LINES


class TestTheDividerShowsItIsAlive:
    """Checking one big setlist can run for minutes without producing a row.

    The caption is the only thing on screen saying that work is still going on,
    so it has to move: a still one is what a hung app looks like, which is the
    call we want people to stop having to make by guessing.
    """

    def _divider(self, screen):
        """Found by its border, not by a row number: the header's shape is
        not what any of these tests are about."""
        lines = [strip_ansi(ln) for ln in screen.frame(width=78, height=14)]
        return next(ln for ln in lines if ln.startswith("├"))

    def _screen_at(self, status, now=0.0):
        screen = _screen()
        clock = [now]
        screen.clock = lambda: clock[0]
        screen.status_getter = lambda: status
        return screen, clock

    def test_the_caption_animates_as_time_passes(self):
        screen, clock = self._screen_at("checking Rock Band (17/80)")

        seen = []
        for tick in range(4):
            clock[0] = tick * 0.125
            seen.append(self._divider(screen))

        glyphs = [line.split()[1] for line in seen]
        assert len(set(glyphs)) == 4, f"caption never moved: {glyphs}"
        for line in seen:
            assert "checking Rock Band (17/80)" in line

    def test_it_animates_on_the_clock_not_on_repaints(self):
        """A paint loop that died must not keep pretending to make progress."""
        screen, _clock = self._screen_at("checking Rock Band (17/80)")

        assert self._divider(screen) == self._divider(screen)

    def test_nothing_happening_gets_no_spinner(self):
        screen, _clock = self._screen_at("")

        assert self._divider(screen).strip("├┤─ ") == ""

    def test_a_held_view_is_a_state_not_an_activity(self):
        screen, _clock = self._screen_at("checking Rock Band (17/80)")
        for i in range(30):
            screen.entries.finish(f"chart{i}", name=f"Chart {i}.7z")
        self._divider(screen)  # a render, so the list knows its own height
        screen.scroll(-1)
        assert not screen.following, "the view did not actually hold"

        assert "held" in self._divider(screen)
        assert not any(glyph in self._divider(screen) for glyph in SPINNER)

    def test_the_spinner_does_not_break_the_frame_width(self):
        """The glyph is multi-byte; padding is measured in columns."""
        screen, clock = self._screen_at("checking Rock Band (17/80)")

        for tick in range(10):
            clock[0] = tick * 0.125
            for width in (60, 78, 120):
                lines = screen.frame(width=width, height=14)
                assert {len(strip_ansi(line)) for line in lines} == {width}
