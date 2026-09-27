"""The screen before a sync that has something wrong with it. A blocker is
shown with its fix and the sync does not start; a warning is the user's call.
"""
from ... import copy
from ...core.formatting import format_size
from ...sync.preflight import BLOCK
from ..primitives import Colors, clear_screen, wait_with_skip
from ..components.header import print_header


def _ask(title: str, message: str) -> bool:
    from ..widgets.confirm import ConfirmDialog
    return ConfirmDialog(title, message).run()


def _wrapped(text: str, indent: str) -> list[str]:
    """`text` wrapped (not truncated) to the terminal, each line indented."""
    import textwrap

    from ..primitives.terminal import get_terminal_width

    room = max(30, get_terminal_width() - len(indent) - 2)
    return [f"{indent}{line}" for line in textwrap.wrap(text, room)] or [indent]


def _print_concern(concern, blocking: bool) -> None:
    c = Colors
    mark = f"{c.ERROR}✗{c.RESET}" if blocking else f"{c.INFO}!{c.RESET}"
    print(f"  {mark} {concern.headline}")
    for line in (_wrapped(concern.detail, "    ") if concern.detail else []):
        print(f"{c.MUTED}{line}{c.RESET}")
    if concern.fix:
        # Set apart from the explanation: this is what to do.
        for i, line in enumerate(_wrapped(concern.fix, "      ")):
            arrow = f"    {c.PRIMARY}→ " if i == 0 else f"{c.PRIMARY}"
            print(f"{arrow}{line.lstrip() if i == 0 else line}{c.RESET}")
    print()


def confirm_sync(concerns, destination: str, free_bytes: int, ask=_ask,
                 pause=None) -> bool:
    """Show the concerns and ask. True when the sync should go ahead."""
    if not concerns:
        return True

    c = Colors
    if any(x.severity == BLOCK for x in concerns):
        # Nothing to ask: a sync in this state cannot work. Printed, since no
        # dialog follows to draw over it.
        clear_screen()
        print_header()
        print()
        print(f"  {c.BOLD}{copy.PRE_TITLE_BLOCKED}{c.RESET}")
        print()
        for concern in concerns:
            _print_concern(concern, blocking=concern.severity == BLOCK)
        print(f"  {c.MUTED}→ {destination}{c.RESET}")
        print(f"  {c.MUTED}  {copy.PRE_FREE.format(size=format_size(free_bytes))}{c.RESET}")
        print()
        (pause or wait_with_skip)(5)
        return False

    # The dialog repaints from the top of the screen, so everything printed
    # above is gone the moment it opens. The concerns go inside it.
    return ask(copy.PRE_ASK, _message(concerns, destination, free_bytes))


def _message(concerns, destination: str, free_bytes: int) -> str:
    """The concerns as the dialog's subtitle. Only the short runs are coloured:
    the menu never breaks a coloured run across lines, so a coloured sentence
    would run off the box instead of wrapping. Plain text shows muted there."""
    c = Colors
    lines = []
    for concern in concerns:
        lines.append(f"{c.INFO}!{c.RESET} {c.BOLD}{concern.headline}{c.RESET}")
        if concern.detail:
            lines.append(concern.detail)
        if concern.fix:
            lines.append(f"{c.PRIMARY}→{c.RESET} {concern.fix}")
        lines.append("")
    lines.append(f"→ {destination}")
    lines.append(copy.PRE_FREE.format(size=format_size(free_bytes)))
    return "\n".join(lines)
