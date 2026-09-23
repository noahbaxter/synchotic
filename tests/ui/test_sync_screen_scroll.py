"""Looking back through a run without stopping it: scrolling up holds the view,
the bottom follows again, and the errors view filters to failures."""
from src.ui.primitives import strip_ansi
from src.ui.widgets.sync_screen import SyncScreen


def _run(charts, done=40, failed=3):
    screen = SyncScreen(title="Drummer's Monthly")
    screen.set_totals(files=len(charts), total_bytes=sum(c.size for c in charts))
    for chart in charts[:done]:
        screen.entries.start(chart.key, chart.name, chart.context, chart.size)
        screen.entries.finish(chart.key)
    for chart in charts[done:done + failed]:
        screen.entries.start(chart.key, chart.name, chart.context, chart.size)
        screen.entries.fail(chart.key, "needs sign-in")
    return screen


def _numbers(screen, height=8):
    return [e.position for e in screen.rows(height)]


class TestScrolling:
    def test_the_view_follows_the_tail_until_it_is_scrolled(self, charts):
        screen = _run(charts)
        assert screen.following
        assert _numbers(screen)[-1] == 43

    def test_scrolling_up_holds_older_rows_in_place(self, charts):
        screen = _run(charts)
        screen.scroll(-5)

        assert not screen.following
        assert _numbers(screen)[-1] == 38

    def test_a_new_completion_does_not_yank_a_held_view(self, charts):
        """Reading something is not a reason to be dragged back to the bottom."""
        screen = _run(charts)
        screen.scroll(-5)
        held = _numbers(screen)

        chart = charts[80]
        screen.entries.start(chart.key, chart.name, chart.context, chart.size)
        screen.entries.finish(chart.key)

        assert _numbers(screen) == held

    def test_scrolling_back_to_the_bottom_follows_again(self, charts):
        screen = _run(charts)
        screen.scroll(-5)
        screen.scroll(5)

        assert screen.following

    def test_scrolling_past_the_top_stops_at_the_first_row(self, charts, seed):
        screen = _run(charts)
        screen.scroll(-9999)

        assert _numbers(screen)[0] == 1, f"seed={seed}"


class TestErrorsOnly:
    def test_the_errors_view_shows_only_what_failed(self, charts):
        screen = _run(charts)
        screen.show_errors_only(True)

        assert [e.state for e in screen.rows(8)] == ["failed"] * 3

    def test_the_frame_says_which_view_you_are_in(self, charts):
        """Three rows on screen out of six hundred needs an explanation."""
        screen = _run(charts)
        screen.show_errors_only(True)
        frame = strip_ansi("\n".join(screen.frame(width=78, height=14)))

        assert "showing errors only · 3" in frame

    def test_turning_it_off_brings_the_run_back(self, charts):
        screen = _run(charts)
        screen.show_errors_only(True)
        screen.show_errors_only(False)

        assert len(screen.rows(8)) == 8
