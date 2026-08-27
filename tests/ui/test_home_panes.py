"""The two-pane home screen.

The point of the layout is that a setlist toggle never leaves the screen, so
these check both halves: that the panes contain what they should, and that
toggling mutates settings in place instead of returning an action.
"""
import pytest

from src.config.settings import (UserSettings, DOWNLOAD_MODE_ANONYMOUS,
                                 DOWNLOAD_MODE_BYOC, DOWNLOAD_MODE_RCLONE)
from src.ui.screens.home_panes import show_main_menu_panes, SETTINGS


class _Auth:
    def __init__(self, signed_in=True):
        self.is_signed_in = signed_in
        self.session_expired = False


FOLDER = {
    "folder_id": "drive-1",
    "name": "BirdmanExe Drive",
    "files": [
        {"path": "Setlist A/song1/notes.chart", "size": 10, "id": "f1"},
        {"path": "Setlist B/song2/notes.chart", "size": 20, "id": "f2"},
    ],
}


@pytest.fixture
def build(monkeypatch, tmp_path):
    """Drive the screen without a terminal. `act` receives the live TwoPane so a
    test can poke its cursor and callbacks the way a keypress would."""
    def run(act=None, folders=(FOLDER,), auth=None, settings=None, scanner=None,
            mode=DOWNLOAD_MODE_ANONYMOUS, rclone_authed=False, byoc_creds=False):
        captured = {}
        settings = settings or UserSettings(tmp_path / "settings.json")
        # Drive-touching rows are gated on whether the mode can reach Drive, so
        # pin both inputs: is_authed() otherwise reads the real rclone config
        # and the rows would differ per machine. Anonymous is the default
        # because it always reaches Drive, leaving unrelated rows ungated.
        settings.download_mode = mode
        monkeypatch.setattr("src.rclone.is_authed", lambda: rclone_authed)
        monkeypatch.setattr("src.drive.auth.has_custom_client_config",
                            lambda: byoc_creds)

        def fake_run(self):
            captured["pane"] = self
            captured["left"] = self._left_rows()
            captured["right_for"] = lambda value: self._right_rows(value, "")
            return act(self) if act else None

        monkeypatch.setattr(
            "chotic_ui.widgets.two_pane.TwoPane.run", fake_run, raising=False)

        captured["returned"] = show_main_menu_panes(
            folders=list(folders),
            user_settings=settings,
            download_path=tmp_path / "charts",
            auth=auth,
            background_scanner=scanner,
        )
        captured["settings"] = settings
        return captured
    return run


def _labels(rows):
    from src.ui.components import strip_ansi
    return [strip_ansi(r[0](False, False)).strip() for r in rows]


def _values(rows):
    return [r[1] for r in rows]


class TestTheLeftPane:
    def test_it_lists_the_drives(self, build):
        assert "BirdmanExe Drive" in " ".join(_labels(build()["left"]))

    def test_settings_is_the_last_row(self, build):
        assert _values(build()["left"])[-1] == SETTINGS

    def test_a_drive_row_carries_its_folder_id(self, build):
        assert ("drive", "drive-1") in _values(build()["left"])


class TestTheRightPane:
    def test_a_drive_shows_its_setlists(self, build):
        out = build()
        labels = " ".join(_labels(out["right_for"](("drive", "drive-1"))))
        assert "Setlist A" in labels and "Setlist B" in labels

    def test_settings_shows_the_options_not_setlists(self, build):
        labels = " ".join(_labels(build()["right_for"](SETTINGS)))
        assert "Add folder" in labels
        assert "Location" in labels
        assert "Setlist A" not in labels

    def test_rescan_is_unselectable_when_the_mode_cannot_reach_drive(self, build):
        rows = build(auth=None, mode=DOWNLOAD_MODE_BYOC,
                     byoc_creds=False)["right_for"](SETTINGS)
        rescan = next(r for r in rows if r[1] == ("act", "rescan"))
        assert rescan[2] is False

    def test_rescan_is_selectable_when_the_mode_works(self, build):
        rows = build(auth=_Auth())["right_for"](SETTINGS)
        rescan = next(r for r in rows if r[1] == ("act", "rescan"))
        assert rescan[2] is True

    def test_rescan_survives_being_signed_out_in_anonymous_mode(self, build):
        """Anonymous has no token by design; the row must not be gated on one."""
        rows = build(auth=None, mode=DOWNLOAD_MODE_ANONYMOUS)["right_for"](SETTINGS)
        rescan = next(r for r in rows if r[1] == ("act", "rescan"))
        assert rescan[2] is True


class TestTogglingStaysOnTheScreen:
    def test_space_on_a_drive_toggles_it_without_returning(self, build):
        def act(pane):
            pane.focus = "left"
            pane._on_left_space(("drive", "drive-1"))
            return None

        out = build(act=act)
        assert out["settings"].is_drive_enabled("drive-1") is False
        assert out["returned"][0] == "quit"

    def test_toggling_a_setlist_returns_nothing(self, build):
        """A None return is what keeps TwoPane's loop running."""
        def act(pane):
            assert pane._on_right_enter(("setlist", "drive-1", "Setlist A")) is None
            return None

        build(act=act)

    def test_a_setlist_toggle_is_persisted(self, build):
        def act(pane):
            pane._on_right_enter(("setlist", "drive-1", "Setlist A"))
            return None

        settings = build(act=act)["settings"]
        assert settings.is_subfolder_enabled("drive-1", "Setlist A") is False


class TestWhatItHandsBack:
    def test_esc_quits(self, build):
        assert build()["returned"][0] == "quit"

    def test_a_settings_row_returns_its_action(self, build):
        out = build(act=lambda pane: pane._on_right_enter(("act", "download_mode")))
        assert out["returned"][0] == "download_mode"

    def test_s_syncs(self, build):
        def act(pane):
            return pane.keys["s"]() and "s"

        assert build(act=act)["returned"][0] == "sync"

    def test_the_cursor_position_comes_back(self, build):
        def act(pane):
            pane._left_cursor = 2
            return None

        assert build(act=act)["returned"][2] == 2


class TestTheColumnsLineUp:
    """Numbers used to drift left and right with the length of the name beside
    them, which made two rows impossible to compare at a glance."""

    def test_every_setlist_row_is_the_same_visible_width(self, build):
        from chotic_ui.primitives.terminal import visible_len
        rows = build()["right_for"](("drive", "drive-1"))
        widths = {visible_len(r[0](False, False))
                  for r in rows if r[1] and r[1][0] == "setlist"}
        assert len(widths) == 1, f"ragged rows: {widths}"

    def test_the_header_band_names_the_columns(self, build):
        from src.ui.components import strip_ansi
        out = build()
        out["right_for"](("drive", "drive-1"))
        header = strip_ansi(out["pane"].right_header)
        assert "CHARTS" in header and "SIZE" in header and "CHANGE" in header

    def test_drive_rows_are_the_same_visible_width(self, build):
        from chotic_ui.primitives.terminal import visible_len
        rows = build()["left"]
        widths = {visible_len(r[0](False, False))
                  for r in rows if r[1] and r[1][0] == "drive"}
        assert len(widths) == 1, f"ragged rows: {widths}"


class TestSettingsIsSetApart:
    def test_a_rule_sits_above_settings(self, build):
        rows = build()["left"]
        idx = next(i for i, r in enumerate(rows) if r[1] == SETTINGS)
        above = rows[idx - 1]
        assert above[2] is False, "the divider must not be selectable"
        assert "─" in above[0](False, False)


class TestThereIsNoThemeSwitcher:
    """Synchotic wears one palette. A hotkey that changes it is a preference
    nobody asked for, and it used to crash on press."""

    def test_t_is_not_bound(self, build):
        pane = build()["pane"]
        assert "t" not in pane.keys and "T" not in pane.keys

    def test_the_footer_does_not_advertise_one(self, build):
        from src.ui.components import strip_ansi
        pane = build()["pane"]
        assert "theme" not in strip_ansi(pane.footer()).lower()


class TestTheBoxLeavesRoomForTheLogo:
    def test_the_body_never_outgrows_the_window(self, build):
        """A long left pane used to force the box past the window height and
        push the banner off the top of the screen."""
        def act(pane):
            from chotic_ui.widgets.two_pane import CHROME_LINES
            lines = 34
            rows = pane._body_rows([0] * 60, [0] * 60, (100, lines))
            # Everything the frame draws has to fit, banner included.
            spent = rows + CHROME_LINES + (pane.footer_lines - 1)
            assert spent <= lines, f"{rows} rows overruns a {lines}-line window"
            return None

        build(act=act)

    def test_the_height_does_not_collapse_on_a_short_drive(self, build):
        def act(pane):
            tall = pane._body_rows([0] * 20, [0] * 20, (100, 40))
            short = pane._body_rows([0] * 20, [0] * 2, (100, 40))
            assert short == tall
            return None

        build(act=act)


class TestTheWholeFrameFits:
    """The banner was scrolling off the top: the frame drew more rows than the
    window had, so the terminal scrolled and the top of the logo went with it.
    That scroll is also what read as flicker and downward drift."""

    @staticmethod
    def _render(pane, cols, lines, monkeypatch):
        """Total rows drawn, banner included. print_header() goes through
        print() while the frame writes to sys.__stdout__, so both have to land
        in the same buffer or the count silently omits the banner."""
        import io, re, shutil, contextlib
        buf = io.StringIO()
        monkeypatch.setattr(shutil, "get_terminal_size",
                            lambda fallback=None: (cols, lines))
        monkeypatch.setattr("sys.__stdout__", buf)
        with contextlib.redirect_stdout(buf):
            pane.render_once()
        out = re.sub(r"\x1b\[[0-9;]*[HJK]", "", buf.getvalue())
        return out.count("\n") + 1

    @pytest.mark.parametrize("lines", [24, 30, 34, 40, 50])
    def test_it_never_draws_more_rows_than_the_window(self, build, monkeypatch, lines):
        from chotic_ui import configure_header
        from src.ui.components.header import ASCII_HEADER
        configure_header(ASCII_HEADER, "1.5.0")

        holder = {}
        build(act=lambda pane: holder.setdefault("pane", pane))
        pane = holder["pane"]
        # More content than any window can hold, so the clamp is what decides
        # the height rather than the fixture happening to be short.
        pane._left_rows = lambda: [(lambda f, c: "x", ("drive", "x"), True)] * 200
        drawn = self._render(pane, 100, lines, monkeypatch)
        assert drawn <= lines, f"{drawn} rows drawn into a {lines}-line window"

    def test_chrome_accounts_for_the_banner(self, build):
        from chotic_ui import configure_header
        from chotic_ui.components.header import header_height
        from chotic_ui.widgets.two_pane import BOX_LINES
        from src.ui.components.header import ASCII_HEADER
        configure_header(ASCII_HEADER, "1.5.0")

        holder = {}
        build(act=lambda pane: holder.setdefault("pane", pane))
        pane = holder["pane"]
        assert pane._chrome_lines() == header_height() + BOX_LINES + pane.footer_lines


class _Scanner:
    """A BackgroundScanner stand-in. The real one has a wide surface and these
    tests only care about whether a scan is running, so anything not named here
    answers falsely rather than raising."""

    def __init__(self, done):
        self._done = done

    def is_done(self):
        return self._done

    def is_scanning(self, folder_id):
        return not self._done

    def get_stats(self):
        class _S:
            current_folder = None
            folders_done = 0
            folders_total = 1
            api_calls = 0
            elapsed = 0.0
            current_folder_elapsed = 0.0
        return _S()

    def __getattr__(self, name):
        return lambda *a, **k: False


class TestUnavailableOptionsLookUnavailable:
    """An option the cursor skips has to say so, or it reads as a row that
    ignores you."""

    def _rescan(self, rows):
        return next(r for r in rows if r[1] == ("act", "rescan"))

    def test_rescan_is_grey_while_scanning(self, build, monkeypatch):
        from src.ui.primitives import Colors
        out = build(auth=_Auth(), scanner=_Scanner(done=False))
        row = self._rescan(out["right_for"](SETTINGS))
        assert row[2] is False
        assert Colors.MUTED_DIM in row[0](False, False)

    def test_rescan_is_grey_when_the_mode_cannot_reach_drive(self, build):
        from src.ui.primitives import Colors
        row = self._rescan(build(auth=None, mode=DOWNLOAD_MODE_BYOC,
                                 byoc_creds=False)["right_for"](SETTINGS))
        assert row[2] is False
        assert Colors.MUTED_DIM in row[0](False, False)

    def test_an_available_rescan_is_not_grey(self, build):
        from src.ui.primitives import Colors
        out = build(auth=_Auth(), scanner=_Scanner(done=True))
        row = self._rescan(out["right_for"](SETTINGS))
        assert row[2] is True
        assert Colors.MUTED_DIM not in row[0](False, False)


class TestDriveRowsNeedAWorkingMode:
    """Add folder, Rescan and Location all make Drive calls, so an unusable
    mode has to stop them at the menu rather than several screens in at
    "access denied"."""

    GATED = [("act", "add_custom"), ("act", "rescan"), ("act", "library")]

    def _rows(self, build, **kw):
        return {r[1]: r for r in build(**kw)["right_for"](SETTINGS) if r[1] in self.GATED}

    def test_byoc_without_credentials_blocks_all_three(self, build):
        rows = self._rows(build, auth=None, mode=DOWNLOAD_MODE_BYOC, byoc_creds=False)
        assert [rows[v][2] for v in self.GATED] == [False, False, False]

    def test_the_row_says_why_it_is_unavailable(self, build):
        """A greyed row with no reason reads as broken rather than unavailable."""
        from src.ui.components import strip_ansi
        rows = self._rows(build, auth=None, mode=DOWNLOAD_MODE_BYOC, byoc_creds=False)
        text = strip_ansi(rows[("act", "add_custom")][0](False, False))
        assert "Needs your Google credentials" in text

    def test_unconnected_rclone_says_to_connect_it(self, build):
        from src.ui.components import strip_ansi
        rows = self._rows(build, auth=None, mode=DOWNLOAD_MODE_RCLONE, rclone_authed=False)
        text = strip_ansi(rows[("act", "add_custom")][0](False, False))
        assert "Connect rclone first" in text

    def test_anonymous_mode_leaves_all_three_available(self, build):
        """The regression to avoid: gating these on sign-in would kill a mode
        that resolves public folders on the API key alone."""
        rows = self._rows(build, auth=None, mode=DOWNLOAD_MODE_ANONYMOUS)
        assert [rows[v][2] for v in self.GATED] == [True, True, True]

    def test_open_folder_is_never_gated(self, build):
        """It opens a local directory, so it works with no Drive access."""
        rows = build(auth=None, mode=DOWNLOAD_MODE_BYOC,
                     byoc_creds=False)["right_for"](SETTINGS)
        row = next(r for r in rows if r[1] == ("act", "open_data_folder"))
        assert row[2] is True


class TestTheChartsColumn:
    def test_it_shows_a_plain_count_not_a_ratio(self, build):
        from src.ui.components import strip_ansi
        rows = build()["right_for"](("drive", "drive-1"))
        text = " ".join(strip_ansi(r[0](False, False))
                        for r in rows if r[1] and r[1][0] == "setlist")
        assert "/" not in text, f"still a ratio: {text!r}"


class TestGroupHeadersStandOut:
    def test_a_header_carries_no_ratio(self, build):
        from src.ui.components import strip_ansi
        rows = build()["left"]
        headers = [strip_ansi(r[0](False, False)) for r in rows
                   if not r[2] and "─" not in r[0](False, False) and r[0](False, False)]
        assert all("/" not in h for h in headers), headers


class TestALiveScanDoesNotRepaintForNothing:
    """Repainting on every tick regardless of whether anything moved is what
    made a running scan look like it was flickering."""

    def test_an_idle_tick_asks_for_no_repaint(self, build):
        out = build(auth=_Auth(), scanner=_Scanner(done=False))
        pane = out["pane"]
        pane.update_callback(pane)                    # first tick primes it
        assert pane.update_callback(pane) is False    # nothing moved since

    def test_it_repaints_when_the_scan_reports_a_change(self, build):
        scanner = _Scanner(done=False)
        out = build(auth=_Auth(), scanner=scanner)
        pane = out["pane"]
        pane.update_callback(pane)
        scanner.check_updates = lambda: True
        assert pane.update_callback(pane) is True

    def test_it_repaints_when_the_footer_text_moves(self, build):
        scanner = _Scanner(done=False)
        out = build(auth=_Auth(), scanner=scanner)
        pane = out["pane"]
        pane.update_callback(pane)

        class _Moved:
            current_folder = "Rock Band"
            folders_done, folders_total, api_calls = 3, 10, 42
            elapsed = current_folder_elapsed = 99.0

        scanner.get_stats = lambda: _Moved()
        assert pane.update_callback(pane) is True


class TestDriveRowsUseTheSpaceTheyHave:
    def test_a_name_with_no_change_is_not_truncated_early(self, build):
        """Reserving a column for a value that is not there cost the name
        characters it could have used."""
        from src.ui.components import strip_ansi
        from src.ui.screens.home_panes import LEFT_WIDTH, LEFT_CHANGE_W
        # Long enough that reserving the change column would have cut it, short
        # enough to fit the row once that column is not reserved. No files means
        # nothing to sync, so there is no change to reserve for.
        name = "A Drive With A Fairly Long Name"
        assert LEFT_WIDTH - 2 - LEFT_CHANGE_W < len(name) + 2 <= LEFT_WIDTH - 2

        folder = {"folder_id": "d2", "name": name, "files": []}
        rows = build(folders=(folder,))["left"]
        row = next(r for r in rows if r[1] == ("drive", "d2"))
        text = strip_ansi(row[0](False, False))
        assert "…" not in text, text
        assert name in text

    def test_the_cyan_scan_ratio_is_gone(self, build):
        from src.ui.components import strip_ansi
        rows = build()["left"]
        for r in rows:
            if r[1] and r[1][0] == "drive":
                assert "/" not in strip_ansi(r[0](False, False))


class TestTheColumnHeaderSitsOverItsNumbers:
    def test_the_header_band_is_as_wide_as_the_rows(self, build):
        """It was built one column narrower to dodge a trailing space the frame
        appends, which left CHARTS sitting a column left of its numbers."""
        from chotic_ui.primitives.terminal import visible_len
        from src.ui.screens.home_panes import _right_text_width

        out = build()
        out["right_for"](("drive", "drive-1"))
        assert visible_len(out["pane"].right_header) == _right_text_width()

    def test_each_label_ends_where_its_column_ends(self, build):
        from src.ui.components import strip_ansi

        out = build()
        rows = out["right_for"](("drive", "drive-1"))
        header = strip_ansi(out["pane"].right_header)
        row = strip_ansi(next(r for r in rows
                              if r[1] and r[1][0] == "setlist")[0](False, False))

        # CHARTS is the first numeric column; its label and its value must share
        # a right edge.
        assert header.rstrip().endswith("CHANGE")
        charts_end = header.index("CHARTS") + len("CHARTS")
        value = row[:charts_end].rstrip()
        assert value and value[-1].isdigit(), f"{value!r} does not end at {charts_end}"


class TestTheCursorStartsOnSomethingSelectable:
    """Opening with the highlight on a section header offered a row that cannot
    be chosen, and the first drive underneath looked passed over."""

    def _left_with_groups(self, build, monkeypatch):
        out = build()
        pane = out["pane"]
        header = (lambda f, c: "  COMMUNITY", None, False)
        drive = (lambda f, c: "  CSC Released Packs", ("drive", "csc"), True)
        rows = [header, drive]
        pane._left_rows = lambda: rows
        return pane, rows

    def test_a_header_under_the_cursor_snaps_to_the_drive_below(self, build, monkeypatch):
        pane, rows = self._left_with_groups(build, monkeypatch)
        pane._left_cursor = 0
        pane._clamp_left(rows)
        assert pane._left_cursor == 1
        assert pane._active_left_value(rows) == ("drive", "csc")

    def test_a_selectable_row_is_left_where_it_is(self, build, monkeypatch):
        pane, rows = self._left_with_groups(build, monkeypatch)
        pane._left_cursor = 1
        pane._clamp_left(rows)
        assert pane._left_cursor == 1

    def test_a_trailing_header_falls_back_to_the_last_drive(self, build, monkeypatch):
        pane, _ = self._left_with_groups(build, monkeypatch)
        rows = [(lambda f, c: "  x", ("drive", "a"), True),
                (lambda f, c: "  GROUP", None, False)]
        pane._left_cursor = 1
        pane._clamp_left(rows)
        assert pane._left_cursor == 0

    def test_an_empty_pane_does_not_blow_up(self, build):
        out = build()
        out["pane"]._left_cursor = 5
        out["pane"]._clamp_left([])
        assert out["pane"]._left_cursor == 0

    def test_the_real_screen_opens_on_a_drive(self, build):
        """End to end: the first row of the real left pane is a group header
        when drives are grouped, so index 0 must not stay put."""
        out = build()
        pane = out["pane"]
        rows = out["left"]
        pane._left_cursor = 0
        pane._clamp_left(rows)
        assert rows[pane._left_cursor][2] is True


class TestTheFrameHoldsItsSize:
    """Coming back from the data folder, the library picker or Add folder used
    to leave a box smaller than the window it sits in, because the height was
    taken from whatever the panes happened to hold at that moment."""

    def test_the_body_fills_the_window(self, build):
        from chotic_ui.widgets.two_pane import MIN_BODY

        def act(pane):
            rows = pane._body_rows([0] * 3, [0] * 2, (100, 40))
            assert rows == 40 - pane._chrome_lines()
            assert rows > MIN_BODY
            return None

        build(act=act)

    def test_a_short_pane_is_the_same_height_as_a_tall_one(self, build):
        def act(pane):
            tall = pane._body_rows([0] * 40, [0] * 40, (100, 34))
            short = pane._body_rows([0] * 2, [0] * 1, (100, 34))
            assert short == tall
            return None

        build(act=act)


class TestReturningFromAnotherScreen:
    """Repainting in place stops the flicker, but the first frame after coming
    back has to wipe whatever the other screen left on the terminal."""

    @staticmethod
    def _paint(pane, monkeypatch):
        import io, shutil, contextlib
        buf = io.StringIO()
        monkeypatch.setattr(shutil, "get_terminal_size", lambda fallback=None: (100, 34))
        monkeypatch.setattr("sys.__stdout__", buf)
        with contextlib.redirect_stdout(buf):
            pane.render_once()
        return buf.getvalue()

    def test_the_first_frame_clears_the_screen(self, build, monkeypatch):
        holder = {}
        build(act=lambda pane: holder.setdefault("pane", pane))
        assert "\x1b[H\x1b[J" in self._paint(holder["pane"], monkeypatch)

    def test_later_frames_only_home_the_cursor(self, build, monkeypatch):
        holder = {}
        build(act=lambda pane: holder.setdefault("pane", pane))
        pane = holder["pane"]
        self._paint(pane, monkeypatch)
        second = self._paint(pane, monkeypatch)
        assert "\x1b[H" in second
        assert "\x1b[H\x1b[J" not in second


class TestItRemembersWhereYouWere:
    """sync.py rebuilds this screen from scratch every time it comes back, so
    Esc in Add folder or the library picker used to drop you on the left pane at
    the top -- nowhere near the row you were working on."""

    @pytest.fixture(autouse=True)
    def _clean(self):
        from src.ui.screens.home_panes import forget_pane_state
        forget_pane_state()
        yield
        forget_pane_state()

    def test_focus_on_the_right_pane_survives(self, build):
        def leave(pane):
            pane.focus = "right"
            pane._cursor = 3
            return ("library", None)

        build(act=leave)
        assert build()["pane"].focus == "right"

    def test_the_right_cursor_comes_back(self, build):
        def leave(pane):
            pane.focus = "right"
            pane._cursor = 2
            pane._scroll = 1
            return ("add_custom", None)

        build(act=leave)
        pane = build()["pane"]
        assert (pane._cursor, pane._scroll) == (2, 1)

    def test_a_different_left_row_does_not_restore_a_stale_cursor(self, build):
        """The remembered right position belongs to one left row. Restoring it
        under a different one would point at an unrelated setlist."""
        def leave(pane):
            pane.focus = "right"
            pane._cursor = 4
            return ("library", None)

        build(act=leave)
        other = {"folder_id": "elsewhere", "name": "Another Drive", "files": []}
        pane = build(folders=(other,))["pane"]
        assert pane.focus == "left"
        assert pane._cursor == 0

    def test_a_fresh_screen_starts_on_the_left(self, build):
        assert build()["pane"].focus == "left"


class TestThereIsNoFilter:
    """Type-to-filter took Space and every letter key away from rows whose main
    verb is toggling, to search lists short enough to read."""

    def test_the_pane_is_not_filterable(self, build):
        assert build()["pane"].right_filterable is False

    def test_the_footer_does_not_advertise_one(self, build):
        from src.ui.components import strip_ansi
        assert "filter" not in strip_ansi(build()["pane"].footer()).lower()
