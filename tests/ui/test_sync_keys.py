"""Keys during a sync: sequences decoded, a lone ESC still cancel."""
from src.ui.primitives.keys import CANCEL, DOWN, END, HOME, PAGE_DOWN, PAGE_UP, UP, decode
from src.ui.widgets.sync_screen import SyncScreen, handle_key


class TestDecoding:
    def test_a_lone_escape_is_cancel(self):
        assert decode("\x1b", "") == CANCEL

    def test_arrows_are_not_mistaken_for_cancel(self):
        """The old monitor sidestepped this by ignoring every sequence."""
        assert decode("\x1b", "[A") == UP
        assert decode("\x1b", "[B") == DOWN
        assert decode("\x1b", "[A") != CANCEL

    def test_paging_and_ends(self):
        assert decode("\x1b", "[5~") == PAGE_UP
        assert decode("\x1b", "[6~") == PAGE_DOWN
        assert decode("\x1b", "[F") == END
        assert decode("\x1b", "[4~") == END
        assert decode("\x1b", "[H") == HOME

    def test_letters_come_back_folded(self):
        assert decode("E", "") == "e"
        assert decode("e", "") == "e"

    def test_an_unknown_sequence_is_nothing_at_all(self):
        assert decode("\x1b", "[27;5u") is None


class TestDrivingTheScreen:
    def _screen(self, charts):
        screen = SyncScreen(title="Drummer's Monthly")
        screen.set_totals(files=len(charts), total_bytes=1)
        for chart in charts[:40]:
            screen.entries.start(chart.key, chart.name, chart.context, chart.size)
            screen.entries.finish(chart.key)
        screen.rows(8)  # the screen learns its height from the frame it draws
        return screen

    def test_up_holds_the_view_and_end_releases_it(self, charts):
        screen = self._screen(charts)
        handle_key(screen, UP, on_cancel=lambda: None)
        assert not screen.following

        handle_key(screen, END, on_cancel=lambda: None)
        assert screen.following

    def test_paging_moves_by_a_screenful_less_one_row(self, charts):
        """The overlapping row is the reader's place; a clean jump loses it."""
        screen = self._screen(charts)
        handle_key(screen, PAGE_UP, on_cancel=lambda: None)
        assert [e.position for e in screen.rows(8)][-1] == 33

    def test_e_toggles_the_errors_view(self, charts):
        screen = self._screen(charts)
        handle_key(screen, "e", on_cancel=lambda: None)
        assert screen.errors_only

        handle_key(screen, "e", on_cancel=lambda: None)
        assert not screen.errors_only

    def test_escape_cancels_rather_than_scrolling(self, charts):
        screen = self._screen(charts)
        cancelled = []
        handle_key(screen, CANCEL, on_cancel=lambda: cancelled.append(True))

        assert cancelled == [True]
        assert screen.following

    def test_an_unhandled_key_changes_nothing(self, charts):
        screen = self._screen(charts)
        before = [e.position for e in screen.rows(8)]
        handle_key(screen, "z", on_cancel=lambda: None)

        assert [e.position for e in screen.rows(8)] == before
