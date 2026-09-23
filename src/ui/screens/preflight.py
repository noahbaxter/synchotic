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
    blockers = [x for x in concerns if x.severity == BLOCK]

    clear_screen()
    print_header()
    print()
    if blockers:
        print(f"  {c.BOLD}{copy.PRE_TITLE_BLOCKED}{c.RESET}")
        print()
    for concern in concerns:
        _print_concern(concern, blocking=concern.severity == BLOCK)
    print(f"  {c.MUTED}→ {destination}{c.RESET}")
    print(f"  {c.MUTED}  {copy.PRE_FREE.format(size=format_size(free_bytes))}{c.RESET}")
    print()

    if blockers:
        # Nothing to ask: a sync in this state cannot work.
        (pause or wait_with_skip)(5)
        return False

    return ask(copy.PRE_ASK, "")
