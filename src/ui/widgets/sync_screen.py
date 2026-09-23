"""The sync screen: one list of charts whose rows change state in place
(downloading, done, failed), under a header saying how far the run is.

Rendering is pure. The driver updates entries and counters; sync_paint puts
frames on the terminal.
"""
import time
from dataclasses import dataclass

from chotic_ui.primitives.terminal import truncate_ansi

from ...core.formatting import format_size, format_speed
from ..components.box import BOX_BL, BOX_BR, BOX_H, BOX_TL, BOX_TR, BOX_TL_DIV, BOX_TR_DIV, BOX_V
from ..primitives import Colors, strip_ansi, truncate_text

BAR_W = 10
CTX_W = 16
STATUS_W = 16
NUM_W = 4  # completion numbers up to 9999; the screen widens it if it must

# Below this the setlist column is dropped and the bar shrinks.
NARROW_WIDTH = 64

ACTIVE = "active"
DONE = "done"
FAILED = "failed"
OVERFLOW = "overflow"  # the "and N more" row, not a chart

# The divider's spinner is the sign of life while one setlist takes minutes to
# check with no row to show for it.
SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
SPINNER_FPS = 8


def _append_right(content: str, right: str, width: int, shrink: bool = False) -> str:
    """Put `right` against the far edge of an already-indented line. On a
    collision `shrink` truncates `content`; otherwise `right` is dropped."""
    if not right:
        return content
    room = width - len(strip_ansi(right)) - RIGHT_MARGIN - 1
    if room < 1:
        return content
    if len(strip_ansi(content)) > room:
        if not shrink:
            return content
        content = truncate_ansi(content, room)
    gap = width - len(strip_ansi(content)) - len(strip_ansi(right)) - RIGHT_MARGIN
    return f"{content}{' ' * gap}{right}"


def spinner_frame(now: float) -> str:
    """The glyph for this moment, from the clock rather than a repaint count,
    so a paint loop that stopped cannot keep animating."""
    return SPINNER[int(now * SPINNER_FPS) % len(SPINNER)]


# The box in the top right holding what the network is doing.
NETWORK_LABEL = "network"

# Room the header keeps left of the box. Below this the figures go inline.
MIN_ROOM_BESIDE_BOX = 38

# With nothing arriving for this long the rate shows as idle rather than the
# last value, which would make a run busy checking setlists look like a crawl.
TRANSFER_IDLE_SECONDS = 3.0
IDLE_SPEED = "-- KB/s"

# The body while the list is empty: a line of air, then the note saying why.
EMPTY_BODY = ("blank", "note")

# Blank rows below that, so the note sits in the panel rather than on its floor.
EMPTY_BODY_AIR = 2

# How many transfers get a row of their own before the rest are summarised.
MAX_ACTIVE_ROWS = 5

# Blank columns kept before the right border. Text touching it looks truncated.
RIGHT_MARGIN = 1

_GLYPH = {ACTIVE: "↓", DONE: "✓", FAILED: "!", OVERFLOW: " "}
# A setlist that needed no download, never mistaken for a downloaded chart.
_GLYPH_NOTED = "≈"
_GLYPH_COLOR = {ACTIVE: Colors.INFO, DONE: Colors.SUCCESS,
                FAILED: Colors.ERROR, OVERFLOW: Colors.MUTED_DIM}


@dataclass
class Entry:
    """One item in the list: a chart being downloaded, done, or failed."""
    key: str
    name: str
    context: str = ""
    total_bytes: int = 0
    downloaded: int = 0
    state: str = ACTIVE
    reason: str = ""
    # Where this chart came in, counting every resolution. 0 until it resolves.
    position: int = 0
    # A resolved row that is not a downloaded chart (a note).
    noted: bool = False
    # Every byte is in and the archive is unpacking; the outcome is still to come.
    extracting: bool = False

    @property
    def fraction(self) -> float:
        if not self.total_bytes:
            return 0.0
        return min(1.0, self.downloaded / self.total_bytes)

    def finish(self) -> None:
        """Resolve as downloaded."""
        self.state = DONE

    def fail(self, reason: str) -> None:
        """Resolve as failed, with the reason shown in the status column."""
        self.state = FAILED
        self.reason = reason


class EntryList:
    """The rows on screen: resolved ones in history, live ones floating below,
    so a slow transfer stays visible while faster ones come and go."""

    def __init__(self):
        self._history: list[Entry] = []
        self._active: dict[str, Entry] = {}
        self.ok = 0
        self.failed = 0
        # Notes: real rows, but kept out of the chart counts.
        self.synced = 0

    def start(self, key: str, name: str, context: str = "", total_bytes: int = 0) -> Entry:
        entry = Entry(key=key, name=name, context=context, total_bytes=total_bytes)
        self._active[key] = entry
        return entry

    def progress(self, key: str, downloaded: int) -> None:
        entry = self._active.get(key)
        if entry:
            entry.downloaded = downloaded

    def extracting(self, key: str) -> None:
        entry = self._active.get(key)
        if entry:
            entry.extracting = True

    def _resolved(self, entry: Entry) -> None:
        """Number it and move it into history. One sequence for every outcome,
        so the number says where a row came in."""
        entry.position = self.ok + self.failed + self.synced
        self._history.append(entry)

    def note(self, key: str, name: str = "", context: str = "") -> None:
        """A resolved row that is not a chart (a purge result, a marker
        rebuild). Claims a live row under the same key, if one is showing."""
        entry = self._claim(key, name, context)
        entry.state = DONE
        entry.noted = True
        self.synced += 1
        self._resolved(entry)

    def drop(self, key: str) -> None:
        """Forget a live row without recording an outcome for it."""
        self._active.pop(key, None)

    def _claim(self, key: str, name: str, context: str) -> Entry:
        """The live entry for `key`, renamed for the chart, or a new one: only
        files over the progress threshold ever get a live row."""
        entry = self._active.pop(key, None)
        if entry is None:
            return Entry(key=key, name=name, context=context)
        entry.name = name or entry.name
        entry.context = context or entry.context
        return entry

    def finish(self, key: str, name: str = "", context: str = "") -> None:
        entry = self._claim(key, name, context)
        self.ok += 1
        entry.finish()
        self._resolved(entry)

    def fail(self, key: str, reason: str, name: str = "", context: str = "") -> None:
        entry = self._claim(key, name, context)
        self.failed += 1
        entry.fail(reason)
        self._resolved(entry)

    def ordered(self) -> list[Entry]:
        """History in resolution order, then whatever is still running."""
        return self._history + list(self._active.values())

    def failures(self) -> list[Entry]:
        return [entry for entry in self._history if entry.state == FAILED]

    def window(self, height: int, end: int, only_failed: bool = False) -> list[Entry]:
        """The `height` rows ending at index `end`. Anchored to a row, not to
        the bottom, so a held view does not drift as the list grows."""
        rows = self.failures() if only_failed else self.ordered()
        end = max(min(height, len(rows)), min(end, len(rows)))
        return rows[max(0, end - height):end]

    def count(self, only_failed: bool = False) -> int:
        return len(self.failures()) if only_failed else len(self.ordered())

    def visible(self, height: int) -> list[Entry]:
        """The last `height` rows: recent history, then at most
        MAX_ACTIVE_ROWS transfers, so completions still have room."""
        if height <= 0:
            return []

        active = list(self._active.values())
        cap = min(MAX_ACTIVE_ROWS, max(1, height - 1))
        tail = active[:cap]
        hidden = len(active) - len(tail)
        if hidden > 0:
            tail = tail + [Entry(key="", name=f"… and {hidden} more downloading",
                                 state=OVERFLOW)]

        return self._history[-(height - len(tail)):] + tail if len(tail) < height else tail


def _bar(fraction: float, width: int = BAR_W) -> str:
    filled = round(fraction * width)
    return "█" * filled + "░" * (width - filled)


def _status(entry: Entry, bar_w: int, status_w: int) -> str:
    """The left-hand column: what is happening to this chart, in one glance."""
    if entry.state == ACTIVE and entry.extracting:
        return truncate_text("extracting…", status_w)
    if entry.state == ACTIVE:
        return f"{_bar(entry.fraction, bar_w)} {entry.fraction * 100:3.0f}%"
    if entry.state == FAILED:
        return truncate_text(f"{_GLYPH[FAILED]} {entry.reason}", status_w)
    if entry.state == DONE:
        return _GLYPH_NOTED if entry.noted else _GLYPH[DONE]
    return ""


def _columns(width: int) -> tuple[int, int, int]:
    """Context, bar and status widths. Narrow terminals drop the setlist
    column first, so the name keeps its room."""
    if width < NARROW_WIDTH:
        return 0, 6, 13
    return CTX_W, BAR_W, STATUS_W


def format_row(entry: Entry, width: int, number_width: int = NUM_W) -> str:
    """One entry as a row of exactly `width` visible columns: number, state,
    setlist, name. Fixed columns keep the name in place as the row resolves."""
    c = Colors
    if entry.state == OVERFLOW:
        return f"  {c.MUTED_DIM}{truncate_text(entry.name, width - 2):<{width - 2}}{c.RESET}"

    num_w = max(1, number_width)
    ctx_w, bar_w, status_w = _columns(width - num_w)
    name_w = max(8, width - 4 - num_w - status_w - (ctx_w + 1 if ctx_w else 0))

    number = f"{entry.position:>{num_w}}" if entry.position else " " * num_w
    number = f"{c.MUTED_DIM}{number}{c.RESET}"
    status = f"{_status(entry, bar_w, status_w):<{status_w}}"
    glyph_color = Colors.MUTED_DIM if entry.noted else _GLYPH_COLOR[entry.state]
    status = f"{glyph_color}{status}{c.RESET}"
    context = ""
    if ctx_w:
        context = f"{c.DIM}{truncate_text(entry.context, ctx_w):<{ctx_w}}{c.RESET} "
    name = f"{truncate_text(entry.name, name_w):<{name_w}}"
    if entry.state != ACTIVE:
        name = f"{c.MUTED if entry.state == FAILED else ''}{name}{c.RESET}"

    return f"  {number} {status} {context}{name}"


def handle_key(screen: "SyncScreen", key: str, on_cancel) -> bool:
    """Apply one decoded key to the screen. True if it meant anything. Cancel
    is a single press: a confirmation prompt mid-sync would be its own trap."""
    from ..primitives.keys import CANCEL, DOWN, END, HOME, PAGE_DOWN, PAGE_UP, UP

    page = max(1, screen.visible_height - 1)
    if key == CANCEL:
        on_cancel()
    elif key == UP:
        screen.scroll(-1)
    elif key == DOWN:
        screen.scroll(1)
    elif key == PAGE_UP:
        screen.scroll(-page)
    elif key == PAGE_DOWN:
        screen.scroll(page)
    elif key == HOME:
        screen.scroll(-10 ** 9)
    elif key == END:
        screen.follow()
    elif key == "e":
        screen.show_errors_only(not screen.errors_only)
    else:
        return False
    return True


# The header, top border down to the divider. The renderer and the line count
# both read this, so they cannot disagree about how much the chrome takes.
HEADER_ROWS = ("border", "blank", "progress", "blank",
               "counts", "advice", "blank", "divider")

# Everything a frame spends before the list: the header plus the bottom border.
CHROME_LINES = len(HEADER_ROWS) + 1


def _border(left: str, right: str, label: str, width: int, emphasize: bool = False) -> str:
    """A border with a label let into it, e.g. ╭─ Syncing ─────╮. `emphasize`
    prints the label at normal brightness against the dim frame."""
    c = Colors
    label = truncate_text(label, max(0, width - 8))
    plain_lead = f"{left}{BOX_H} {label} " if label else f"{left}{BOX_H}"
    fill = BOX_H * max(0, width - len(strip_ansi(plain_lead)) - 1)
    if label and emphasize:
        lead = f"{c.MUTED_DIM}{left}{BOX_H} {c.RESET}{label}{c.MUTED_DIM} "
    else:
        lead = f"{c.MUTED_DIM}{plain_lead}"
    return f"{lead}{c.MUTED_DIM}{fill}{right}{c.RESET}"


def content_width(width: int) -> int:
    """Columns a line may use: the box, less both borders and the right margin."""
    return max(1, width - 2 - RIGHT_MARGIN)


def _line(content: str, width: int) -> str:
    """One framed row, content fitted (not just padded) to the content width:
    a line that overruns wraps and shunts the whole frame."""
    c = Colors
    inner = content_width(width)
    visible = len(strip_ansi(content))
    if visible > inner:
        content = truncate_ansi(content, inner)
        visible = len(strip_ansi(content))
    content = content + " " * (max(0, inner - visible) + RIGHT_MARGIN)
    return f"{c.MUTED_DIM}{BOX_V}{c.RESET}{content}{c.MUTED_DIM}{BOX_V}{c.RESET}"


class SyncScreen:
    """The whole download screen as a list of lines, ready to paint."""

    def __init__(self, title: str = "", controls: str = ""):
        self.title = title
        # The stage word in the header: SYNC, DOWNLOAD, VERIFY, PURGE...
        self.phase = "SYNC"
        self.controls = controls or "ESC cancel"
        self.entries = EntryList()
        self.total_files = 0
        self.total_bytes = 0
        self.downloaded_bytes = 0
        self.speed = 0.0
        # When bytes last arrived, on self.clock.
        self.last_transfer_at: float | None = None
        # Units of the current phase (setlists checked, drives purged). When
        # set, the bar tracks these instead of chart bytes, so a run of mostly
        # already-synced checks still moves.
        self.run_total = 0
        self.run_done = 0
        self.run_unit = ""
        # Progress within the unit in flight, 0 to 1.
        self.run_partial = 0.0
        self.errors_only = False
        # Something else worth saying in the divider, e.g. a scan still running.
        self.status_getter = None
        # Swappable so a test can pin the spinner to a known frame.
        self.clock = time.monotonic
        self._anchor: int | None = None  # index of the last visible row when held
        self._height = 1

    def set_totals(self, files: int = 0, total_bytes: int = 0) -> None:
        self.total_files = files
        self.total_bytes = total_bytes

    @property
    def done_count(self) -> int:
        return self.entries.ok + self.entries.failed

    def _progress_line(self, width: int) -> str:
        """How far along this run is. The network box has the rest."""
        c = Colors
        if self.run_total:
            fraction = min(1.0, (self.run_done + self.run_partial) / self.run_total)
            counter = f"{self.run_done}/{self.run_total}"
            if self.run_unit:
                counter += f" {self.run_unit}"
            parts = [f"{fraction * 100:3.0f}%", _bar(fraction, 20), counter]
        else:
            fraction = self.done_count / self.total_files if self.total_files else 0.0
            parts = [f"{fraction * 100:3.0f}%", _bar(fraction, 20)]
        return f"  {c.BOLD}{'   '.join(parts)}{c.RESET}"

    def _network_rows(self) -> list[str]:
        """Rate, then how much has arrived. No time remaining: a guess people
        watch instead of the work."""
        if not self.total_bytes:
            return []
        return [self._speed_text(),
                f"{format_size(self.downloaded_bytes)} / {format_size(self.total_bytes)}"]

    def _speed_text(self) -> str:
        """The current rate, or idle when nothing is arriving."""
        live = (self.speed > 0 and self.last_transfer_at is not None
                and self.clock() - self.last_transfer_at < TRANSFER_IDLE_SECONDS)
        return format_speed(self.speed) if live else IDLE_SPEED

    def _network_box(self) -> list[str]:
        """The network figures in a box of their own, or nothing to show."""
        rows = self._network_rows()
        if not rows:
            return []
        inner = max(len(NETWORK_LABEL) + 2, max(len(row) for row in rows))
        c = Colors
        edge = c.MUTED_DIM
        # Every line the same width, or the right edge zigzags.
        top = (f"{edge}{BOX_TL}{BOX_H} {c.RESET}{c.MUTED}{NETWORK_LABEL}{c.RESET}"
               f"{edge} {BOX_H * (inner - len(NETWORK_LABEL) - 1)}{BOX_TR}{c.RESET}")
        body = [f"{edge}{BOX_V}{c.RESET} {row.ljust(inner)} {edge}{BOX_V}{c.RESET}"
                for row in rows]
        bottom = f"{edge}{BOX_BL}{BOX_H * (inner + 2)}{BOX_BR}{c.RESET}"
        return [top, *body, bottom]

    def _counts_line(self, width: int) -> str:
        """Charts brought in and charts that failed, with the rows' own glyphs.
        Empty until something has resolved."""
        c = Colors
        parts = []
        if self.entries.ok:
            n = self.entries.ok
            parts.append(f"{_GLYPH_COLOR[DONE]}{_GLYPH[DONE]}{c.RESET}"
                         f" {n} chart{'' if n == 1 else 's'}")
        if self.entries.failed:
            n = self.entries.failed
            parts.append(f"{c.ERROR}{_GLYPH[FAILED]} {n} error{'' if n == 1 else 's'}{c.RESET}")
        return "  " + "   ".join(parts)

    def _advice_line(self, width: int) -> str:
        """Whether anybody has to do anything about the errors."""
        from .sync_display import FIX, REPORT, advise

        tone, reason, advice = advise([e.reason for e in self.entries.failures()])
        if not tone:
            return ""
        c = Colors
        label = {FIX: c.ERROR, REPORT: c.ERROR}.get(tone, c.MUTED)
        text = f"  {label}{reason}{c.RESET}{c.MUTED}: {advice}{c.RESET}"
        return truncate_ansi(text, max(4, width))

    @property
    def visible_height(self) -> int:
        """Rows the list was last drawn with, which is what a page key moves."""
        return self._height

    @property
    def following(self) -> bool:
        """True while the view sits at the bottom and new rows push it along."""
        return self._anchor is None

    def scroll(self, delta: int) -> None:
        """Move the view by `delta` rows. Negative is back through the run."""
        total = self.entries.count(self.errors_only)
        anchor = total if self._anchor is None else self._anchor
        anchor = max(min(self._height, total), min(anchor + delta, total))
        self._anchor = None if anchor >= total else anchor

    def follow(self) -> None:
        """Return to the bottom and track new rows again."""
        self._anchor = None

    def show_errors_only(self, on: bool) -> None:
        self.errors_only = on
        self._anchor = None

    def rows(self, height: int) -> list[Entry]:
        """The entries to draw, honouring the filter and the held position."""
        self._height = height
        if self.errors_only:
            end = self.entries.count(True) if self._anchor is None else self._anchor
            return self.entries.window(height, end, only_failed=True)
        if self.following:
            return self.entries.visible(height)
        return self.entries.window(height, self._anchor)

    def _divider_label(self) -> str:
        if self.errors_only:
            return f"showing errors only · {self.entries.failed}"
        if not self.following:
            return "held · END to follow"
        if self.status_getter:
            try:
                status = self.status_getter()
            except Exception:
                return ""
            if not status:
                return ""
            return f"{spinner_frame(self.clock())} {status}"
        return ""

    def _controls(self) -> str:
        if self.errors_only:
            return f"{self.controls} · ↑↓ scroll · E all charts"
        return f"{self.controls} · ↑↓ scroll · E errors only"

    @property
    def number_width(self) -> int:
        """Digits the completion column has to hold for a run this size."""
        return max(NUM_W, len(str(max(self.total_files, self.done_count))))

    def body_height(self, height: int) -> int:
        """Rows left for the list once the chrome has taken its share."""
        return max(1, height - CHROME_LINES)

    def compact_height(self) -> int:
        """How tall to draw while the list is empty, derived from the layout."""
        return CHROME_LINES + len(EMPTY_BODY) + EMPTY_BODY_AIR

    def _empty_note(self, width: int) -> str:
        """Said in the body while the list is empty, so a mostly current library
        reads as an answer rather than a hung app."""
        c = Colors
        note = ("nothing to download yet" if self.phase == "DOWNLOAD"
                else "nothing to show yet")
        return f"  {c.MUTED}{truncate_text(note, max(4, width - 4))}{c.RESET}"

    def frame(self, width: int, height: int) -> list[str]:
        """Exactly `height` lines, each exactly `width` visible columns wide."""
        rows = self.body_height(height)
        cw = content_width(width)
        title = f"{self.phase} · {self.title}" if self.title else self.phase

        # The network box rides down the right of the header from the bar row;
        # too narrow for it and the figures go inline on the counts row.
        box = self._network_box()
        if box and cw - len(strip_ansi(box[0])) < MIN_ROOM_BESIDE_BOX:
            box = []
        beside = dict(enumerate(box, start=HEADER_ROWS.index("progress")))

        content = {
            "blank": lambda w: "",
            "progress": self._progress_line,
            "counts": self._counts_line,
            "advice": self._advice_line,
        }
        lines = []
        for i, row in enumerate(HEADER_ROWS):
            if row == "border":
                lines.append(_border(BOX_TL, BOX_TR, title, width))
            elif row == "divider":
                lines.append(_border(BOX_TL_DIV, BOX_TR_DIV,
                                     self._divider_label(), width, emphasize=True))
            else:
                # Built against the room left beside the box, not cut after.
                alongside = beside.get(i, "")
                room = cw - (len(strip_ansi(alongside)) + RIGHT_MARGIN + 1
                             if alongside else 0)
                text = content[row](room)
                if alongside:
                    text = _append_right(text, alongside, cw, shrink=True)
                elif row == "counts" and not box:
                    text = _append_right(text, " · ".join(self._network_rows()), cw)
                lines.append(_line(text, width))

        visible = self.rows(rows)
        body = [format_row(entry, cw, self.number_width) for entry in visible]
        body = body or ["" if row == "blank" else self._empty_note(cw)
                        for row in EMPTY_BODY]
        for line in body[:rows]:
            lines.append(_line(line, width))
        for _ in range(rows - len(body)):
            lines.append(_line("", width))

        lines.append(_border(BOX_BL, BOX_BR, self._controls(), width))
        return lines
