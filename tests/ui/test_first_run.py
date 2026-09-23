"""The setup steps a launch asks, and where their text ends up: an
explanation must be drawn by the screen that asks, since both screens repaint
and anything printed before them is wiped."""
import pytest

from src import copy
from src.ui.screens.first_run import (LIBRARY, LIBRARY_INTRO, MODE, MODE_INTRO,
                                      run_setup, setup_needs)


class TestWhenItRuns:
    """Every launch checks; only what is missing or broken is asked."""

    def test_a_new_install_needs_both(self):
        assert setup_needs(library_set=False, mode_chosen=False,
                           mode_blocked="") == [LIBRARY, MODE]

    def test_a_working_install_needs_nothing(self):
        assert setup_needs(library_set=True, mode_chosen=True,
                           mode_blocked="") == []

    def test_a_mode_never_chosen_is_asked(self):
        assert setup_needs(library_set=True, mode_chosen=False,
                           mode_blocked="") == [MODE]

    def test_a_mode_that_broke_since_last_time_is_asked_again(self):
        """A deleted credentials.json or rclone config is repaired on the next
        launch rather than discovered at the next sync."""
        assert setup_needs(library_set=True, mode_chosen=True,
                           mode_blocked="byoc_setup") == [MODE]


def _setup(monkeypatch, *, needs=(LIBRARY, MODE), library_after=True,
           blocked=("",), mode_chosen=True, first_run=True, answer=None,
           mode_answer="rclone"):
    """Run setup with every screen faked. `blocked` is what blocked_step
    returns on successive calls, its last value repeating. `answer` picks the
    reply to every boxed page: None for Esc, else an index into its options."""
    seen = {"pages": [], "waits": 0, "mode_asks": 0}
    blocked = list(blocked)
    # Picking a mode saves it, as handle_download_mode does.
    chosen = {"mode": mode_chosen}

    def fake_ask(title, body, options, setup_step=None, **kw):
        # Every step is the same boxed menu, and each one waits for an
        # answer: that is what stops setup sliding past on a timer.
        seen["waits"] += 1
        seen["pages"].append((setup_step, title, body, options))
        if answer is None and kw.get("esc_label") == copy.BTN_QUIT:
            return options[0][1]
        return None if answer == "esc" else options[answer or 0][1]

    monkeypatch.setattr("src.ui.screens.library.ask", fake_ask)

    def choose_library(intro, at):
        seen["library_intro"] = intro
        seen["library_step"] = at

    def choose_mode(intro, at):
        seen["mode_intro"] = intro
        seen["mode_step"] = at
        seen["mode_asks"] += 1
        if mode_answer:
            chosen["mode"] = True
        return mode_answer

    def blocked_step():
        return blocked.pop(0) if len(blocked) > 1 else blocked[0]

    finished = run_setup(list(needs), choose_library=choose_library,
                         choose_mode=choose_mode,
                         library_is_set=lambda: library_after,
                         mode_chosen=lambda: chosen["mode"],
                         blocked_step=blocked_step, first_run=first_run)
    return finished, seen


class TestTheStepsCarryTheirOwnText:
    """Each step hands its words to the screen that asks, so they arrive
    together instead of a page apart."""

    def _run(self, monkeypatch, library_after=True, blocked=""):
        return _setup(monkeypatch, library_after=library_after,
                      blocked=(blocked, ""))

    def test_the_library_step_hands_its_intro_to_the_picker(self, monkeypatch):
        _, seen = self._run(monkeypatch)
        assert seen["library_intro"] == LIBRARY_INTRO
        assert "DELETED" in LIBRARY_INTRO

    def test_the_picker_is_told_which_step_it_is(self, monkeypatch):
        """So it can print the setup banner itself, on the same screen as the
        prompt rather than a page earlier."""
        _, seen = self._run(monkeypatch)
        assert seen["library_step"] == (1, 3, copy.SETUP_TITLE)

    def test_nothing_advances_on_a_timer(self, monkeypatch):
        """The last page used to vanish after a few seconds, which is the same
        as not showing it."""
        _, seen = self._run(monkeypatch)
        assert seen["waits"] >= 1

    def test_a_mode_that_cannot_download_stops_to_say_so(self, monkeypatch):
        """Picking BYOC with no credentials used to print an explanation and
        then move on to the home screen by itself."""
        finished, seen = self._run(monkeypatch, blocked="byoc_setup")
        assert finished is True
        assert seen["waits"] >= 2  # the warning, then the drives page

    @pytest.mark.parametrize("step", ["rclone", "byoc_setup", "signin"])
    def test_the_warning_names_what_is_actually_missing(self, monkeypatch, step):
        """One shared "that is not finished" left someone who had just closed
        a browser window with nothing to act on."""
        from src.ui.screens.first_run import UNFINISHED

        _, seen = self._run(monkeypatch, blocked=step)
        warning = next(p for p in seen["pages"] if p[0][:2] == (2, 3))
        assert UNFINISHED[step][1] in warning[2]

    def test_an_imported_selection_is_said_out_loud(self):
        """Setup imports a previous library without asking, so the last page
        is the only place that ever mentions it happened."""
        from src.ui.screens.first_run import _ready_body

        body = _ready_body("· Rock Band: 2 setlists")

        assert copy.READY_DETECTED.format(setlists="· Rock Band: 2 setlists") in body

    def test_without_an_import_the_page_does_not_mention_one(self):
        from src.ui.screens.first_run import _ready_body

        body = _ready_body("")

        assert "detected" not in body
        assert body.endswith(copy.READY_SYNC)

    def test_the_mode_step_hands_its_intro_to_the_chooser(self, monkeypatch):
        _, seen = self._run(monkeypatch)
        assert seen["mode_intro"] == MODE_INTRO

    def test_it_finishes_when_a_library_was_picked(self, monkeypatch):
        finished, _ = self._run(monkeypatch)
        assert finished is True

class TestRequiredMeansRequired:
    """A library and a working mode are required. The only ways out of a
    required step are finishing it or quitting."""

    def test_no_library_asks_again_until_there_is_one(self, monkeypatch):
        picks = iter([False, False, True])
        seen = {"library_asks": 0}

        def ask(title, body, options, setup_step=None, **kw):
            return options[0][1]  # "Pick a folder"

        monkeypatch.setattr("src.ui.screens.library.ask", ask)

        def choose_library(intro, at):
            seen["library_asks"] += 1

        finished = run_setup([LIBRARY], choose_library=choose_library,
                             choose_mode=lambda intro, at: "rclone",
                             library_is_set=lambda: next(picks),
                             mode_chosen=lambda: True,
                             blocked_step=lambda: "")
        assert finished is True
        assert seen["library_asks"] == 3

    def test_quitting_with_no_library_quits(self, monkeypatch):
        finished, seen = _setup(monkeypatch, library_after=False, answer="esc")
        assert finished is False
        assert "mode_intro" not in seen

    def test_escaping_the_mode_chooser_quits(self, monkeypatch):
        finished, _ = _setup(monkeypatch, mode_answer=None)
        assert finished is False

    def test_an_unfinished_mode_cannot_be_walked_past(self, monkeypatch):
        """The old "Leave it for now" finished setup in a mode that could not
        sync anything. The answers now are retry or quit."""
        finished, seen = _setup(monkeypatch, blocked=("byoc_setup", "byoc_setup", ""))
        warning = next(p for p in seen["pages"] if p[1] == "")
        labels = [label for label, _ in warning[3]]
        assert labels == [copy.UNFINISHED_RETRY, copy.BTN_QUIT]
        assert seen["mode_asks"] == 2  # asked until it worked
        assert finished is True

    def test_quitting_an_unfinished_mode_quits(self, monkeypatch):
        finished, _ = _setup(monkeypatch, blocked=("rclone",), answer=1)
        assert finished is False


class TestRepairLaunch:
    """A later launch asks only what is missing, headed as setup rather than
    as a first run."""

    def test_only_the_broken_step_is_asked(self, monkeypatch):
        finished, seen = _setup(monkeypatch, needs=(MODE,), first_run=False,
                                blocked=("byoc_setup", ""))
        assert finished is True
        assert "library_step" not in seen
        assert seen["mode_step"] == (1, 1, copy.SETUP_REPAIR_TITLE)

    def test_it_says_what_broke_before_asking_again(self, monkeypatch):
        """Dropping someone on the chooser with no reason reads as the app
        forgetting their settings."""
        _, seen = _setup(monkeypatch, needs=(MODE,), first_run=False,
                         blocked=("byoc_setup", ""))
        first_page = seen["pages"][0]
        assert copy.STATUS_BYOC in first_page[2]

    def test_a_mode_never_chosen_goes_straight_to_the_options(self, monkeypatch):
        _, seen = _setup(monkeypatch, needs=(MODE,), first_run=False,
                         mode_chosen=False, blocked=("",))
        assert seen["pages"] == []
        assert seen["mode_asks"] == 1

    def test_no_drives_page_on_a_repair(self, monkeypatch):
        """The drive list is optional and already on the home screen."""
        _, seen = _setup(monkeypatch, needs=(MODE,), first_run=False)
        assert not any(copy.READY_TITLE in p[2] for p in seen["pages"])


class TestBackingOut:
    """Esc is a way out of every question here. Uncaught it ended the run on a
    traceback, which reads as a crash rather than as backing out."""

    def test_the_entry_point_catches_a_cancelled_prompt(self, monkeypatch):
        """wait_for_key and the typed prompts raise rather than return, so the
        outermost handler is what keeps Esc from printing a stack trace."""
        import sync as sync_entry
        from src.ui.primitives import CancelInput

        monkeypatch.setenv("SYNCHOTIC_OS_DIRS", "0")
        monkeypatch.setattr(sync_entry, "main",
                            lambda: (_ for _ in ()).throw(CancelInput()))
        monkeypatch.setattr("chotic_ui.primitives.host.leave_alt_screen",
                            lambda: None)

        with pytest.raises(SystemExit) as exit_info:
            sync_entry.cli()
        assert exit_info.value.code == 0


class TestStartup:
    """sync.py asks setup on every launch, and a quit there is a quit."""

    def _launch(self, monkeypatch, *, library_set, mode="rclone", blocked="",
                finishes=True):
        from types import SimpleNamespace

        import sync as sync_entry

        asked = []
        monkeypatch.setattr(sync_entry, "library_is_set", lambda: library_set)
        monkeypatch.setattr("sys.stdin.isatty", lambda: True, raising=False)

        def fake_run_setup(needs, **kw):
            asked.append((needs, kw["first_run"]))
            return finishes

        monkeypatch.setattr(sync_entry, "run_setup", fake_run_setup)
        app = SimpleNamespace(user_settings=SimpleNamespace(download_mode=mode),
                              _drive_blocked_step=lambda: blocked)
        return sync_entry.startup_setup(app), asked

    def test_a_working_install_is_asked_nothing(self, monkeypatch):
        assert self._launch(monkeypatch, library_set=True) == (True, [])

    def test_a_new_install_gets_the_whole_setup(self, monkeypatch):
        _, asked = self._launch(monkeypatch, library_set=False, mode="")
        assert asked == [([LIBRARY, MODE], True)]

    def test_a_broken_mode_is_repaired_without_a_first_run(self, monkeypatch):
        _, asked = self._launch(monkeypatch, library_set=True, blocked="rclone")
        assert asked == [([MODE], False)]

    def test_quitting_setup_quits_the_app(self, monkeypatch):
        finished, _ = self._launch(monkeypatch, library_set=False, finishes=False)
        assert finished is False


def test_the_chooser_shows_the_intro_it_is_handed(monkeypatch):
    """It repaints, so a caller's explanation has to travel as its subtitle."""
    from src.ui.screens.download_mode import choose_download_mode

    captured = {}

    def fake_run(self, initial_index=0):
        captured["subtitle"] = self.subtitle
        return None

    monkeypatch.setattr("chotic_ui.widgets.menu.Menu.run", fake_run)
    choose_download_mode(intro="step text")

    assert captured["subtitle"] == "step text"
