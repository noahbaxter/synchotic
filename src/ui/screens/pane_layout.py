"""Column and row rendering for the two-pane home screen. Pure formatting, no
drive, settings or cache state."""

from chotic_ui.primitives.terminal import visible_len, truncate_ansi

from ..primitives import Colors
from ..components import strip_ansi


LEFT_WIDTH = 38

# Left-pane columns.
LEFT_CHANGE_W = 9


def cell(text: str, width: int, color: str = "") -> str:
    """Right-align `text` in a fixed column, measuring what is actually visible
    so ANSI codes do not shove the column out of true. Over-long values are cut
    to the column: letting one row run wide pushed the whole line past the pane,
    and the frame's own truncation then replaced the last cell with an ellipsis."""
    text = text or ""
    if visible_len(text) > width:
        text = truncate_ansi(text, width)
    pad = max(0, width - visible_len(text))
    body = f"{color}{text}{Colors.RESET}" if color and text else text
    return " " * pad + body


def columns(head: str, cells, width: int) -> str:
    """`head` flush left, `cells` as fixed right-aligned columns at the far edge."""
    tail = "".join(cell(t, w, c) for t, w, c in cells)
    tail_w = sum(w for _, w, _ in cells)
    room = width - tail_w - 1
    if visible_len(head) > room:
        head = truncate_ansi(head, max(1, room))
    gap = width - visible_len(head) - tail_w
    return f"{head}{' ' * max(1, gap)}{tail}"


def plain_delta(delta: str) -> str:
    """Deltas arrive wrapped for inline use ("[+22.9 MB]"); in a column of their
    own the brackets are just noise."""
    return strip_ansi(delta or "").strip().strip("[]").strip()


def row(text, value, selectable=True):
    """TwoPane wants (render(focused, cursor) -> str, value, selectable). Nothing
    here varies with focus; the widget owns the cursor marker."""
    return (lambda focused, cursor: text, value, selectable)


def header_row(label):
    """Flush against the left edge while the rows under it are indented, so the
    grouping reads at a glance without a count to decode."""
    return row(f"{Colors.BOLD}{Colors.PRIMARY}{label.upper()}{Colors.RESET}", None, False)


def spacer():
    return row("", None, False)


def rule(width: int):
    """A drawn divider, not a blank line: Settings is a different kind of thing
    from the drives above it and the gap alone did not say so."""
    return row(f"{Colors.BORDER}{'─' * max(1, width)}{Colors.RESET}", None, False)
