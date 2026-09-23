"""Rows render from their state without moving the name column."""
from src.ui.primitives import strip_ansi
from src.ui.widgets.sync_screen import Entry, format_row


class TestActiveRow:
    def test_bar_fills_in_proportion_to_bytes(self):
        entry = Entry(key="f1", name="Gojira - Flying Whales",
                      context="DM 2024-06", total_bytes=100, downloaded=40)
        row = strip_ansi(format_row(entry, width=78))
        assert row.count("█") == 4
        assert row.count("░") == 6
        assert "40%" in row


def _rows(width=78):
    """The same chart in each of the three states."""
    active = Entry(key="f1", name="Gojira - Flying Whales",
                   context="DM 2024-06", total_bytes=100, downloaded=40)
    done = Entry(key="f2", name="Gojira - Flying Whales", context="A Longer Setlist")
    done.finish()
    failed = Entry(key="f3", name="Gojira - Flying Whales", context="RB")
    failed.fail("needs sign-in")
    return [active, done, failed]


class TestAlignment:
    def test_name_starts_at_the_same_column_in_every_state(self):
        """A list whose names jog left and right as rows resolve is unreadable."""
        columns = {strip_ansi(format_row(e, width=78)).index("Gojira") for e in _rows()}
        assert len(columns) == 1

    def test_state_reads_down_the_left_edge(self):
        """Bar, tick and reason share one column, ahead of the setlist."""
        for entry in _rows():
            plain = strip_ansi(format_row(entry, width=78))
            assert plain.index("Gojira") > plain.rstrip().index(plain.strip()[0])
        active, done, failed = _rows()
        assert strip_ansi(format_row(active, 78)).index("█") < \
            strip_ansi(format_row(active, 78)).index("DM 2024-06")
        assert strip_ansi(format_row(failed, 78)).index("needs sign-in") < \
            strip_ansi(format_row(failed, 78)).index("RB")

    def test_a_resolved_row_is_numbered_on_the_far_left(self):
        """Where it came in, ahead of everything else on the row."""
        done = Entry(key="f2", name="Gojira - Flying Whales", context="Setlist")
        done.finish()
        done.position = 309

        plain = strip_ansi(format_row(done, width=78, number_width=4))
        assert plain.startswith("   309 ")
        assert "664" not in plain

    def test_a_live_row_leaves_the_number_column_empty(self):
        """It has not come in yet, so there is no place in the order to show."""
        active = Entry(key="f1", name="Gojira - Flying Whales", context="Setlist",
                       total_bytes=100, downloaded=40)
        plain = strip_ansi(format_row(active, width=78, number_width=4))

        assert plain[:7] == " " * 7
        assert plain.index("█") == strip_ansi(
            format_row(_rows()[1], width=78, number_width=4)).index("✓")

    def test_row_is_exactly_the_width_asked_for(self):
        """The row sits between two borders, so an overrun wraps and tears the frame."""
        long = Entry(key="f1", name="A Very Long Song Title That Runs Past The Column" * 2,
                     context="An Overlong Setlist Name", total_bytes=100, downloaded=40)
        short = Entry(key="f2", name="Rush - YYZ", context="")
        short.finish()

        for width in (60, 78, 120):
            for entry in (long, short):
                assert len(strip_ansi(format_row(entry, width=width))) == width

    def test_a_narrow_row_spends_its_columns_on_the_song(self):
        """At 50 columns the setlist was taking 16 and leaving the name 8."""
        entry = Entry(key="f1", name="Gojira - Flying Whales",
                      context="Community Track Packs", total_bytes=100, downloaded=40)
        row = strip_ansi(format_row(entry, width=49))

        assert "Gojira - Flying Whales" in row
        assert "Community" not in row
