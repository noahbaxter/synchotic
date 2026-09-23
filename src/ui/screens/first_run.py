"""What a launch asks before it shows anything else.

A new install gets all three steps. A later launch gets only the required ones
that are missing or broken (see setup_needs), so setup also repairs.

Library first, because it is the only answer that can lose data. Download mode
second, drives last. Every screen says which step it is, and nothing moves on
by itself: a page that vanishes on a timer is a page nobody read.
"""
from ... import copy
from ..widgets.sync_display import deletion_warning

LIBRARY_STEP = copy.STEP_LIBRARY
MODE_STEP = copy.STEP_MODE
DRIVES_STEP = copy.STEP_DRIVES

# One paragraph, wrapped by whatever box it lands in; the risk is coloured.
LIBRARY_INTRO = copy.LIBRARY_INTRO.format(warning=deletion_warning())

MODE_INTRO = copy.MODE_INTRO


# What is actually missing, keyed by mode_blocked_step's tokens.
UNFINISHED = {
    "rclone": (copy.STATUS_RCLONE, copy.UNFINISHED_RCLONE_BODY),
    "byoc_setup": (copy.STATUS_BYOC, copy.UNFINISHED_BYOC_BODY),
    "signin": (copy.STATUS_SIGNED_OUT, copy.UNFINISHED_SIGNIN_BODY),
}


LIBRARY = "library"
MODE = "mode"


def setup_needs(*, library_set: bool, mode_chosen: bool,
                mode_blocked: str) -> list:
    """The setup steps this launch has to ask, in order. Empty when none.

    Local checks only: an unplugged library is still set, and an expired
    sign-in only shows up online, so neither forces setup.
    """
    needs = []
    if not library_set:
        needs.append(LIBRARY)
    if not mode_chosen or mode_blocked:
        needs.append(MODE)
    return needs


def _page(at: tuple, name: str, title: str, body: str,
          options=((copy.BTN_CONTINUE, True),), esc_label=copy.BTN_SKIP):
    """One step, drawn as the same boxed menu as every other step. `title`
    heads the body: these pages are statements with a button."""
    from .library import ask
    from ..primitives import Colors

    heading = f"{Colors.BOLD}{title}{Colors.RESET}"
    return ask("", f"{heading}\n\n{body}", list(options), setup_step=at,
               esc_label=esc_label, step_name=name)


def run_setup(needs: list, *, choose_library, choose_mode, library_is_set,
              mode_chosen, blocked_step, pick_starting_drives=None,
              first_run: bool = False) -> bool:
    """Ask the steps in `needs` until each one works. False means quit.

    A required step is finished or the app quits; no sign-in is always an
    option, so there is always a way through. `choose_library(intro, at)` and
    `choose_mode(intro, at)` show their screens (`choose_mode` returns None
    when escaped), and the state callables are re-read after each attempt
    rather than trusting a return value. A first run ends on the drives page.
    """
    steps = list(needs) + ([DRIVES_STEP] if first_run else [])
    title = copy.SETUP_TITLE if first_run else copy.SETUP_REPAIR_TITLE

    def at(step):
        return (steps.index(step) + 1, len(steps), title)

    if LIBRARY in needs:
        while True:
            choose_library(LIBRARY_INTRO, at(LIBRARY))
            if library_is_set():
                break
            if not _page(at(LIBRARY), LIBRARY_STEP, copy.LIBRARY_UNSET,
                         copy.NO_LIBRARY_BODY,
                         options=((copy.LIBRARY_BROWSE, True),
                                  (copy.BTN_QUIT, False)),
                         esc_label=copy.BTN_QUIT):
                return False

    if MODE in needs:
        # A mode that was chosen before and has since broken says what broke
        # first. A mode never chosen goes straight to the options.
        problem = blocked_step() if mode_chosen() else ""
        while True:
            if problem:
                title_, body = UNFINISHED.get(problem, UNFINISHED["signin"])
                if not _page(at(MODE), MODE_STEP, title_,
                             body,
                             options=((copy.UNFINISHED_RETRY, True),
                                      (copy.BTN_QUIT, False)),
                             esc_label=copy.BTN_QUIT):
                    return False
            if choose_mode(MODE_INTRO, at(MODE)) is None:
                return False
            problem = blocked_step()
            if not problem and mode_chosen():
                break

    if first_run:
        detected = pick_starting_drives() if pick_starting_drives else ""
        _page(at(DRIVES_STEP), DRIVES_STEP, copy.READY_TITLE,
              _ready_body(detected), options=((copy.READY_GO, True),))
    return True


def _ready_body(detected: str = "") -> str:
    """The last page. `detected` lists a previous library setup turned back
    on, or is "": this page is the only place that is ever mentioned."""
    from ..primitives import Colors

    parts = [copy.READY_LAYOUT.format(bold_open=Colors.BOLD,
                                      bold_close=Colors.RESET)]
    if detected:
        parts.append(copy.READY_DETECTED.format(setlists=detected))
    parts.append(copy.READY_SYNC)
    return "\n\n".join(parts)
