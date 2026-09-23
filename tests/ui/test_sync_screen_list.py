"""Ordering and windowing of the entry list: live rows float below history, so
a slow transfer stays in view while faster ones come and go."""
from src.ui.widgets.sync_screen import EntryList


def _names(entries):
    return [e.name for e in entries]


class TestCompletionNumbers:
    def test_failures_take_their_place_in_the_sequence(self):
        """The number is where a chart came in, not how well it went.

        Numbering successes only would make the column disagree with the list
        it sits next to: two rows apart on screen, three apart by number.
        """
        entries = EntryList()
        for key in ("a", "b", "c", "d"):
            entries.start(key, key.upper(), "Setlist", 1_000)
        entries.finish("a")
        entries.fail("b", "needs sign-in")
        entries.finish("c")

        assert [e.position for e in entries.ordered()[:3]] == [1, 2, 3]

    def test_an_unresolved_chart_has_no_number_yet(self):
        entries = EntryList()
        entries.start("a", "A", "Setlist", 1_000)
        assert entries.ordered()[0].position == 0


class TestChartsThatNeverGotALiveRow:
    """Only files over 512 KB get progress callbacks (downloader.py).

    Everything smaller lands between two paints and is never seen downloading,
    so resolving a key the list has never heard of has to work rather than be
    silently dropped.
    """

    def test_finishing_an_unknown_chart_still_records_it(self):
        entries = EntryList()
        entries.finish("never-started", name="Rush - YYZ", context="DM 2024-06")

        row = entries.ordered()[0]
        assert (row.name, row.context, row.position) == ("Rush - YYZ", "DM 2024-06", 1)
        assert entries.ok == 1

    def test_failing_an_unknown_chart_still_records_it(self):
        entries = EntryList()
        entries.fail("never-started", "needs sign-in", name="Rush - YYZ")

        assert entries.ordered()[0].reason == "needs sign-in"
        assert entries.failed == 1


class TestOrdering:
    def test_active_rows_sit_below_resolved_ones(self):
        entries = EntryList()
        entries.start("slow", "Gojira - Flying Whales", total_bytes=90_000_000)
        entries.start("quick", "Rush - YYZ", total_bytes=4_000_000)
        entries.finish("quick")

        assert _names(entries.ordered()) == ["Rush - YYZ", "Gojira - Flying Whales"]

    def test_a_long_download_stays_in_view_as_others_finish(self):
        """The regression the old pinned block existed to prevent."""
        entries = EntryList()
        entries.start("slow", "Gojira - Flying Whales", total_bytes=90_000_000)
        for i in range(30):
            entries.start(f"f{i}", f"Filler {i}", total_bytes=1_000)
            entries.finish(f"f{i}")

        assert "Gojira - Flying Whales" in _names(entries.visible(height=5))

    def test_completions_stay_visible_when_every_worker_is_busy(self, charts, seed):
        """24 workers would otherwise fill the whole viewport with live bars.

        Seeing nothing but in-flight rows is the same blindness as seeing none
        of them: the run looks stalled because nothing ever reaches history.
        """
        entries = EntryList()
        for chart in charts[:10]:
            entries.start(chart.key, chart.name, chart.context, chart.size)
            entries.finish(chart.key)
        for chart in charts[10:34]:
            entries.start(chart.key, chart.name, chart.context, chart.size)

        visible = entries.visible(height=10)
        resolved = [e for e in visible if e.state != "active"]
        assert resolved, f"no completions on screen (seed={seed})"

    def test_the_overflow_row_starts_at_the_left_edge(self):
        """It summarises the list, so it should not line up inside a column."""
        from src.ui.primitives import strip_ansi
        from src.ui.widgets.sync_screen import format_row

        entries = EntryList()
        for i in range(9):
            entries.start(f"f{i}", f"Chart {i}", "Setlist", 1_000_000)
        overflow = [e for e in entries.visible(height=8) if e.state == "overflow"]

        assert overflow, "expected an overflow row"
        assert strip_ansi(format_row(overflow[0], width=78)).startswith("  … and 4 more")

    def test_resolving_settles_an_entry_into_history(self):
        entries = EntryList()
        entries.start("slow", "Gojira - Flying Whales", total_bytes=90_000_000)
        entries.start("late", "Tool - Schism", total_bytes=1_000)
        entries.finish("slow")

        assert _names(entries.ordered()) == ["Gojira - Flying Whales", "Tool - Schism"]
