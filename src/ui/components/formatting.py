"""
Text formatting helpers for UI display.

Functions for formatting sync status, counts, sizes with colors.
"""

import math
from collections import defaultdict
from pathlib import Path

from src import copy
from src.core.formatting import count, format_size
from ..primitives import Colors, strip_ansi


def calc_percent(synced: int, total: int) -> int:
    """Calculate sync percentage, always rounding down."""
    if total == 0:
        return 100
    return math.floor(synced / total * 100)


def format_delta(
    add_size: int = 0,
    remove_size: int = 0,
    empty_text: str = "",
    is_estimate: bool = False,
) -> str:
    """
    Format add/remove sizes with combined brackets: [+2.3 GB / -317.3 MB]

    Bracket colors:
        Add only: white [...]
        Remove only: red [...]
        Both: white [ + white add + / + red remove + red ]
    """
    has_add = add_size > 0
    has_remove = remove_size > 0
    add_str = f"+{format_size(add_size)}" if has_add else ""
    remove_str = f"-{format_size(remove_size)}" if has_remove else ""

    i = Colors.ITALIC if is_estimate else ""
    if has_add and has_remove:
        return f"{Colors.RESET}{i}{Colors.BOLD}[{add_str} {Colors.MUTED}/{Colors.RESET} {i}{Colors.ERROR}{remove_str}]{Colors.RESET}"
    elif has_add:
        return f"{Colors.RESET}{i}{Colors.BOLD}[{add_str}]{Colors.RESET}"
    elif has_remove:
        return f"{Colors.ERROR}{i}[{remove_str}]{Colors.RESET}"
    else:
        return empty_text


def format_status_line(
    synced_charts: int,
    total_charts: int,
    enabled_setlists: int,
    total_setlists: int,
    total_size: int,
    disk_size: int = 0,
    empty_hint: str = "",
    **_kwargs,
) -> str:
    """Format status line: 100% | 562/562 charts, 10/15 setlists (4.0 GB)"""
    if total_charts == 0:
        if enabled_setlists == 0 and empty_hint:
            return empty_hint
        return ""

    pct = calc_percent(synced_charts, total_charts)

    parts = []
    if total_charts > 0:
        parts.append(copy.HOME_CHARTS.format(synced=synced_charts, total=total_charts))
    if total_setlists > 0:
        parts.append(copy.HOME_SETLISTS.format(enabled=enabled_setlists, total=total_setlists))

    info = ", ".join(parts)
    display_size = disk_size if disk_size > 0 else total_size
    if display_size > 0:
        info += f" ({format_size(display_size)})"

    return f"{pct}% | {info}"


def _format_columns(sync: str, count: str, size_str: str, pipe_color: str, value_color: str) -> str:
    """Build pipe-separated fixed-width column string.

    Format: "  {sync:>5}  |  {count:>6}  |  {size:>10}"
    Colors applied to values and pipes independently.
    When no colors given, returns plain text (menu applies its own color wrap).
    """
    if not pipe_color and not value_color:
        return f"  {sync:>5}  |  {count:>6}  |  {size_str:>10}"
    p = f"{pipe_color}|{Colors.RESET}"
    v = (lambda s: f"{value_color}{s}{Colors.RESET}") if value_color else (lambda s: s)
    return f"  {v(f'{sync:>5}')}  {p}  {v(f'{count:>6}')}  {p}  {v(f'{size_str:>10}')}"


def _compute_delta(
    disabled: bool,
    missing_size: int,
    purgeable_size: int,
    show_add: bool,
    is_estimate: bool = False,
) -> str:
    """Delta string for home/setlist items. Only what purge would remove when
    the drive is off, nothing is missing, or the add size is not reliable."""
    if disabled or not show_add or missing_size <= 0:
        return format_delta(remove_size=purgeable_size, is_estimate=is_estimate)
    return format_delta(add_size=missing_size, remove_size=purgeable_size,
                        is_estimate=is_estimate)


def format_home_item(
    enabled_setlists: int,
    total_setlists: int,
    total_size: int,
    synced_size: int,
    purgeable_size: int = 0,
    disabled: bool = False,
    is_estimate: bool = False,
    state: str = "current",
    scan_progress: tuple[int, int] | None = None,
    disk_size: int = 0,
) -> tuple[str, str]:
    """Format home screen item as (columns_str, delta_str).

    Returns pipe-separated columns with state-based coloring,
    and a separate delta string for the label.

    States:
        "current" - scanned, normal colors, with deltas. Green ✓ when 100%.
        "cached" - dimmed (STALE), no add deltas
        "scanning" - enabled count highlighted cyan, rest normal
    """
    show_add_delta = state in ("current", "scanning")
    missing_size = max(0, total_size - synced_size)

    # Build raw column values
    pct_prefix = "~" if is_estimate else ""

    if disabled:
        sync = ""
        is_synced = False
    else:
        is_synced = missing_size <= 0
        pct = 100 if is_synced else calc_percent(synced_size, total_size)
        sync = f"{pct_prefix}{pct}%"

    if total_setlists > 0 and not is_estimate:
        count = f"{enabled_setlists}/{total_setlists}"
    else:
        count = ""

    # Size column: disk size when available, download size with ↓ when not
    if disk_size > 0:
        size_str = format_size(disk_size)
    elif total_size > 0:
        size_str = f"↓ {format_size(total_size)}"
    else:
        size_str = ""

    # Checkmark for label prefix (confirmed 100% sync)
    show_checkmark = is_synced and state == "current" and total_setlists > 0 and not is_estimate

    # Determine colors and build columns
    if state == "scanning":
        # Italic columns without mid-string RESETs (italic persists through color switches)
        base = Colors.MUTED_DIM if disabled else Colors.MUTED
        hl = Colors.INFO_DIM if disabled else Colors.INFO
        pipe = f"\x1b[23m{base}|{Colors.ITALIC}"  # disable italic for pipe, re-enable after
        sync_val = f"{sync:>5}" if sync else "     "
        size_val = f"{size_str:>10}" if size_str else "          "

        if count and "/" in count:
            enabled_str, rest = count.split("/", 1)
            count_visible = len(enabled_str) + 1 + len(rest)
            pad = " " * max(0, 6 - count_visible)
            count_val = f"{pad}{hl}{enabled_str}{base}/{rest}"
        else:
            count_val = f"{count:>6}" if count else "      "

        columns = f"{Colors.ITALIC}{base}  {sync_val}  {pipe}  {count_val}  {pipe}  {size_val}{Colors.RESET}"
    elif state == "cached":
        columns = _format_columns(sync, count, size_str, Colors.STALE, Colors.STALE)
    else:
        # "current" - no color codes, menu applies MUTED/MUTED_DIM
        columns = _format_columns(sync, count, size_str, "", "")

    # Build delta string (estimated when scanning — partial data from cache)
    delta = _compute_delta(
        disabled=disabled,
        missing_size=missing_size,
        purgeable_size=purgeable_size,
        show_add=show_add_delta,
        is_estimate=(state == "scanning"),
    )

    return columns, delta, show_checkmark


def format_setlist_item(
    total_charts: int,
    synced_charts: int,
    total_size: int,
    synced_size: int,
    purgeable_size: int = 0,
    disabled: bool = False,
    unit: str = "charts",
    state: str = "current",
    disk_size: int = 0,
) -> tuple[str, str]:
    """Format setlist item as (columns_str, delta_str).

    Returns pipe-separated columns with state-based coloring,
    and a separate delta string for the label.
    """
    missing_size = max(0, total_size - synced_size)

    # Sync column: blank when disabled or 0 charts (don't show misleading 100%)
    if disabled:
        sync = ""
        is_synced = False
    elif total_charts == 0:
        sync = ""
        is_synced = False
    else:
        pct = calc_percent(synced_charts, total_charts)
        is_synced = synced_charts >= total_charts
        sync = f"{pct}%"

    count = str(total_charts) if total_charts > 0 else ""

    # Size column: disk size when available, download size with ↓ when not
    has_disk_data = disk_size > 0
    is_download = False

    if disabled and has_disk_data:
        size_str = ""  # purge delta on label tells the story
    elif has_disk_data:
        size_str = format_size(disk_size)
    elif total_size > 0:
        size_str = f"↓ {format_size(total_size)}"
        is_download = True
    else:
        size_str = ""

    # Checkmark for label prefix (confirmed 100% sync)
    show_checkmark = is_synced and state == "current"

    # Determine colors and build columns
    if state == "cached":
        columns = _format_columns(sync, count, size_str, Colors.STALE, Colors.STALE)
    elif is_download:
        # Download size indicator — dim the whole row
        columns = _format_columns(sync, count, size_str, Colors.STALE, Colors.STALE)
    else:
        # "current" or "scanning" - no color codes, menu applies MUTED/MUTED_DIM
        columns = _format_columns(sync, count, size_str, "", "")

    # Build delta string (show add delta for all states, estimated when not current)
    is_estimate = state in ("scanning", "cached")
    delta = _compute_delta(
        disabled=disabled,
        missing_size=missing_size,
        purgeable_size=purgeable_size,
        show_add=True,
        is_estimate=is_estimate,
    )

    return columns, delta, show_checkmark


def format_purge_tree(files: list[tuple[Path, int]], base_path: Path) -> list[str]:
    """
    Format files to purge as a tree showing file counts per folder.

    Args:
        files: List of (Path, size) tuples
        base_path: Base path for relative display

    Returns:
        List of formatted strings to print.
    """
    by_folder = defaultdict(lambda: {"count": 0, "size": 0})
    for f, size in files:
        rel_path = f.relative_to(base_path)
        parent = str(rel_path.parent)
        by_folder[parent]["count"] += 1
        by_folder[parent]["size"] += size

    sorted_folders = sorted(by_folder.items())

    lines = []
    for folder_path, stats in sorted_folders:
        lines.append(f"  {folder_path}/ ({count(stats['count'], 'file')}, "
                     f"{format_size(stats['size'])})")

    return lines
