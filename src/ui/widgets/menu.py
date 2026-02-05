"""
Interactive menu widget.

Provides terminal menus with arrow key navigation, scrolling, and hotkeys.
"""

import os
import sys
import time
import signal
import shutil
from dataclasses import dataclass, field
from typing import Any

from ..primitives import (
    getch,
    getch_with_timeout,
    cbreak_noecho,
    Colors,
    cycle_theme,
    THEME_SWITCHER_ENABLED,
    KEY_UP,
    KEY_DOWN,
    KEY_LEFT,
    KEY_RIGHT,
    KEY_PAGE_UP,
    KEY_PAGE_DOWN,
    KEY_ENTER,
    KEY_ESC,
    KEY_SPACE,
    KEY_TAB,
)
from ..components import (
    box_row,
    strip_ansi,
    print_header,
    invalidate_header_cache,
    BOX_TL,
    BOX_TR,
    BOX_BL,
    BOX_BR,
    BOX_H,
    BOX_V,
    BOX_TL_DIV,
    BOX_TR_DIV,
)


# Global flag for resize detection
_resize_flag = False


def _handle_resize(signum, frame):
    """Signal handler for terminal resize (SIGWINCH)."""
    global _resize_flag
    _resize_flag = True
    invalidate_header_cache()


# Install signal handler (Unix only)
if hasattr(signal, 'SIGWINCH'):
    signal.signal(signal.SIGWINCH, _handle_resize)


def check_resize() -> bool:
    """Check and clear the resize flag. Returns True if resize occurred."""
    global _resize_flag
    if _resize_flag:
        _resize_flag = False
        return True
    return False


@dataclass
class MenuItem:
    """A selectable menu item."""
    label: str
    hotkey: str | None = None
    value: Any = None
    description: str | None = None
    disabled: bool = False
    show_toggle: bool | None = None
    pinned: bool = False

    def __post_init__(self):
        if self.value is None:
            self.value = self.label


@dataclass
class MenuDivider:
    """A visual divider between menu items."""
    pinned: bool = False


@dataclass
class MenuGroupHeader:
    """A collapsible group header in the menu."""
    label: str
    group_name: str
    expanded: bool = False
    value: Any = None
    drive_count: int = 0
    enabled_count: int = 0

    def __post_init__(self):
        if self.value is None:
            self.value = ("group", self.group_name)


@dataclass
class MenuAction(MenuItem):
    """A menu action item (alias for MenuItem)."""
    pass


@dataclass
class MenuResult:
    """Result from menu selection."""
    item: MenuItem | MenuAction
    action: str  # "enter" or "space"

    @property
    def value(self):
        return self.item.value


@dataclass
class Menu:
    """Interactive terminal menu with arrow key navigation."""

    title: str = ""
    subtitle: str = ""
    footer: str = ""
    space_hint: str = ""
    esc_label: str = "Back"
    items: list = field(default_factory=list)
    column_header: str = ""  # Right-aligned header row rendered after title divider
    status_line: str = ""  # Rendered below menu box (for scan progress, etc.)
    _selected: int = 0
    _selected_before_hotkey: int = 0
    _scroll_offset: int = 0
    update_callback: callable = None  # Called periodically; return True to re-render
    refresh_interval_ms: int = 200  # How often to check for updates
    _last_callback_time: float = 0.0

    def add_item(self, item):
        self.items.append(item)

    def update_item_description(self, value: Any, new_description: str) -> bool:
        """Update the description of an item by its value. Returns True if found."""
        for item in self.items:
            if isinstance(item, (MenuItem, MenuAction)) and item.value == value:
                item.description = new_description
                return True
        return False

    def update_item_label(self, value: Any, new_label: str) -> bool:
        """Update the label of an item by its value. Returns True if found."""
        for item in self.items:
            if isinstance(item, (MenuItem, MenuAction)) and item.value == value:
                item.label = new_label
                return True
        return False

    def _split_items(self) -> tuple[list[tuple[int, Any]], list[tuple[int, Any]]]:
        """Split items into scrollable and pinned lists, preserving original indices."""
        scrollable = []
        pinned = []
        for i, item in enumerate(self.items):
            is_pinned = getattr(item, 'pinned', False)
            if is_pinned:
                pinned.append((i, item))
            else:
                scrollable.append((i, item))
        return scrollable, pinned

    def _base_visible_capacity(self) -> int:
        """Calculate base capacity for scrollable items (without scroll indicators)."""
        term_height = shutil.get_terminal_size().lines
        fixed_lines = 8 + 4 + 1 + 1  # Header + box + hint + buffer
        if self.subtitle:
            fixed_lines += 1
        if self.column_header:
            fixed_lines += 1
        if self.footer:
            fixed_lines += 2
        _, pinned = self._split_items()
        fixed_lines += len(pinned)
        available = term_height - fixed_lines
        return max(5, available)

    def _visible_items_for_scroll(self, total_scrollable: int, scroll_offset: int) -> int:
        """Calculate visible items based on which scroll indicators will appear."""
        base = self._base_visible_capacity()

        if total_scrollable <= base:
            return base

        has_above = scroll_offset > 0
        has_below = scroll_offset + (base - 1) < total_scrollable

        if has_above and has_below:
            return base - 2
        else:
            return base - 1

    def _adjust_scroll(self):
        """Adjust scroll offset to keep selected item visible within scrollable items."""
        scrollable, _ = self._split_items()
        if not scrollable:
            self._scroll_offset = 0
            return

        total = len(scrollable)
        max_visible = self._visible_items_for_scroll(total, self._scroll_offset)

        selected_scroll_pos = None
        for pos, (orig_idx, _) in enumerate(scrollable):
            if orig_idx == self._selected:
                selected_scroll_pos = pos
                break

        if selected_scroll_pos is None:
            return

        if selected_scroll_pos < self._scroll_offset:
            self._scroll_offset = selected_scroll_pos
        elif selected_scroll_pos >= self._scroll_offset + max_visible:
            self._scroll_offset = selected_scroll_pos - max_visible + 1

        max_visible = self._visible_items_for_scroll(total, self._scroll_offset)
        max_scroll = max(0, total - max_visible)
        self._scroll_offset = max(0, min(self._scroll_offset, max_scroll))

    def _drain_arrow_keys(self) -> int:
        """Read all buffered arrow keys and return net UP/DOWN delta.

        Positive = DOWN, negative = UP. Non-arrow input is discarded.
        """
        if os.name == 'nt':
            return 0

        import fcntl
        fd = sys.stdin.fileno()
        flags = fcntl.fcntl(fd, fcntl.F_GETFL)
        fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
        try:
            raw = sys.stdin.read(1024)
        except (IOError, BlockingIOError):
            raw = ''
        finally:
            fcntl.fcntl(fd, fcntl.F_SETFL, flags)

        if not raw:
            return 0

        delta = 0
        i = 0
        while i < len(raw):
            if raw[i] == '\x1b' and i + 2 < len(raw) and raw[i + 1] == '[':
                code = raw[i + 2]
                if code == 'A':
                    delta -= 1
                    i += 3
                elif code == 'B':
                    delta += 1
                    i += 3
                else:
                    # Other escape sequence (e.g. [5~ for page up) — skip
                    i += 3
                    # Consume trailing ~ for sequences like [5~
                    if i < len(raw) and raw[i] == '~':
                        i += 1
            else:
                i += 1
        return delta

    def _selectable(self) -> list[int]:
        return [i for i, item in enumerate(self.items) if isinstance(item, (MenuItem, MenuAction, MenuGroupHeader))]

    def _move_selection(self, selectable: list[int], delta: int):
        """Move selection by delta steps (positive=down, negative=up), wrapping."""
        if not selectable or delta == 0:
            return
        pos = selectable.index(self._selected)
        pos = (pos + delta) % len(selectable)
        self._selected = selectable[pos]

    def _width(self) -> int:
        """Return menu width based on terminal size."""
        return shutil.get_terminal_size().columns - 2

    def _render_item(self, orig_idx: int, item: Any, w: int, c: str):
        """Render a single menu item."""
        if isinstance(item, MenuDivider):
            print(box_row(BOX_TL_DIV, BOX_H, BOX_TR_DIV, w, c))
        elif isinstance(item, MenuGroupHeader):
            selected = (orig_idx == self._selected)
            indicator = "▼" if item.expanded else "▶"
            label_upper = item.label.upper()
            count_str = ""
            if not item.expanded and item.drive_count > 0:
                count_str = f" {Colors.MUTED}({item.enabled_count}/{item.drive_count} drives){Colors.RESET}"
            if selected:
                content = f"{Colors.PINK}▸{Colors.RESET} {Colors.MUTED}{indicator}{Colors.RESET} {Colors.HOTKEY}[{label_upper}]{Colors.RESET}{count_str}"
            else:
                content = f"  {Colors.MUTED}{indicator}{Colors.RESET} {Colors.HOTKEY}[{label_upper}]{Colors.RESET}{count_str}"
            visible = len(strip_ansi(content))
            pad = w - 4 - visible
            print(f"{c}{BOX_V}{Colors.RESET} {content}{' ' * pad} {c}{BOX_V}{Colors.RESET}")
        elif isinstance(item, (MenuItem, MenuAction)):
            selected = (orig_idx == self._selected)
            is_disabled = getattr(item, 'disabled', False)
            show_toggle = getattr(item, 'show_toggle', None)

            if show_toggle is not None:
                toggle_prefix = f"{Colors.HOTKEY}[ON]{Colors.RESET}  " if show_toggle else f"{Colors.DIM}[OFF]{Colors.RESET} "
                toggle_len = 6
            else:
                toggle_prefix = ""
                toggle_len = 0

            label_text = item.label
            label_visible_len = len(strip_ansi(label_text))

            # Build left side (selector + toggle + hotkey + label)
            # Items with hotkeys: [key] shifted so key middle aligns with ▼
            if item.hotkey:
                key_offset = (len(item.hotkey) - 1) // 2
                unsel_w = max(0, 1 - key_offset)
                sel_pfx = f"{Colors.PINK}▸{Colors.RESET}"
                unsel_pfx = " " * unsel_w
                pfx_width = 1 if selected else unsel_w
                hotkey_pad = " " * max(0, 5 - pfx_width - len(item.hotkey) - 2)
            else:
                sel_pfx = f"{Colors.PINK}▸{Colors.RESET} "
                unsel_pfx = "  "
                pfx_width = 2
                hotkey_pad = ""

            if is_disabled:
                if selected:
                    hotkey = f"{Colors.DIM_HOVER}[{item.hotkey}]{Colors.RESET}{hotkey_pad}" if item.hotkey else ""
                    left = f"{sel_pfx}{toggle_prefix}{hotkey}{Colors.DIM_HOVER}{label_text}{Colors.RESET}"
                else:
                    hotkey = f"{Colors.DIM}[{item.hotkey}]{Colors.RESET}{hotkey_pad}" if item.hotkey else ""
                    left = f"{unsel_pfx}{toggle_prefix}{hotkey}{Colors.DIM}{label_text}{Colors.RESET}"
            else:
                hotkey = f"{Colors.HOTKEY}[{item.hotkey}]{Colors.RESET}{hotkey_pad}" if item.hotkey else ""
                if selected:
                    left = f"{sel_pfx}{toggle_prefix}{hotkey}{Colors.BOLD}{label_text}{Colors.RESET}"
                else:
                    left = f"{unsel_pfx}{toggle_prefix}{hotkey}{label_text}"

            hotkey_len = (len(item.hotkey) + 2 + len(hotkey_pad)) if item.hotkey else 0
            left_visible = pfx_width + toggle_len + hotkey_len + label_visible_len

            # Build right side (description, right-aligned)
            right = ""
            right_visible = 0
            if item.description:
                desc_visible = len(strip_ansi(item.description))
                available = w - 4 - left_visible
                if desc_visible > 0 and desc_visible + 2 <= available:
                    if is_disabled:
                        right = f"{Colors.MUTED_DIM}{item.description}{Colors.RESET}"
                    else:
                        right = f"{Colors.MUTED}{item.description}{Colors.RESET}"
                    right_visible = desc_visible

            if right_visible > 0:
                gap = w - 4 - left_visible - right_visible
                content = f"{left}{' ' * gap}{right}"
            else:
                pad = max(0, w - 4 - left_visible)
                content = f"{left}{' ' * pad}"

            print(f"{c}{BOX_V}{Colors.RESET} {content} {c}{BOX_V}{Colors.RESET}")

    def _render(self):
        """Render the full menu using buffered output to prevent flicker."""
        import sys
        from io import StringIO

        # Capture all print output to a buffer
        buf = StringIO()
        old_stdout = sys.stdout
        sys.stdout = buf
        try:
            print_header()

            w = self._width()
            c = Colors.INDIGO

            scrollable, pinned = self._split_items()
            self._adjust_scroll()
            total = len(scrollable)
            max_visible = self._visible_items_for_scroll(total, self._scroll_offset)
            visible_start = self._scroll_offset
            visible_end = min(total, visible_start + max_visible)
            has_more_above = visible_start > 0
            has_more_below = visible_end < total

            # Box top
            print(box_row(BOX_TL, BOX_H, BOX_TR, w, c))

            # Title
            if self.title:
                pad = w - 4 - len(self.title)
                left = pad // 2
                print(f"{c}{BOX_V}{Colors.RESET} {' ' * left}{Colors.BOLD}{self.title}{Colors.RESET}{' ' * (pad - left)} {c}{BOX_V}{Colors.RESET}")
                if self.subtitle:
                    sub_pad = w - 4 - len(strip_ansi(self.subtitle))
                    sub_left = sub_pad // 2
                    print(f"{c}{BOX_V}{Colors.RESET} {' ' * sub_left}{Colors.MUTED}{self.subtitle}{Colors.RESET}{' ' * (sub_pad - sub_left)} {c}{BOX_V}{Colors.RESET}")
                print(box_row(BOX_TL_DIV, BOX_H, BOX_TR_DIV, w, c))

            # Column header (right-aligned, after title divider)
            if self.column_header:
                hdr_visible = len(strip_ansi(self.column_header))
                hdr_pad = w - 4 - hdr_visible
                print(f"{c}{BOX_V}{Colors.RESET} {' ' * hdr_pad}{self.column_header} {c}{BOX_V}{Colors.RESET}")

            # Scroll indicator (more above)
            if has_more_above:
                indicator = f"{Colors.MUTED}  ▲ {visible_start} more above{Colors.RESET}"
                vis_len = len(strip_ansi(indicator))
                pad = w - 4 - vis_len
                print(f"{c}{BOX_V}{Colors.RESET} {indicator}{' ' * pad} {c}{BOX_V}{Colors.RESET}")

            # Render visible scrollable items
            for scroll_idx in range(visible_start, visible_end):
                orig_idx, item = scrollable[scroll_idx]
                self._render_item(orig_idx, item, w, c)

            # Scroll indicator (more below)
            if has_more_below:
                remaining = len(scrollable) - visible_end
                indicator = f"{Colors.MUTED}  ▼ {remaining} more below{Colors.RESET}"
                vis_len = len(strip_ansi(indicator))
                pad = w - 4 - vis_len
                print(f"{c}{BOX_V}{Colors.RESET} {indicator}{' ' * pad} {c}{BOX_V}{Colors.RESET}")

            # Render pinned items
            for orig_idx, item in pinned:
                self._render_item(orig_idx, item, w, c)

            # Footer
            if self.footer:
                print(box_row(BOX_TL_DIV, BOX_H, BOX_TR_DIV, w, c))
                footer_len = len(strip_ansi(self.footer))
                pad = w - 4 - footer_len
                left = pad // 2
                print(f"{c}{BOX_V}{Colors.RESET} {' ' * left}{self.footer}{' ' * (pad - left)} {c}{BOX_V}{Colors.RESET}")

            # Box bottom
            print(box_row(BOX_BL, BOX_H, BOX_BR, w, c))

            # Hint
            hint = f"  {Colors.MUTED}↑/↓ Navigate  {Colors.HOTKEY}Enter{Colors.MUTED} Select"
            if self.space_hint:
                hint += f"  {Colors.HOTKEY}Space{Colors.MUTED} {self.space_hint}"
            if THEME_SWITCHER_ENABLED:
                hint += f"  {Colors.HOTKEY}C{Colors.MUTED} Theme"
            hint += f"  {Colors.HOTKEY}Esc{Colors.MUTED} {self.esc_label}{Colors.RESET}"
            print(hint)

            # Status line (scan progress, etc.)
            if self.status_line:
                status = self.status_line
                term_width = shutil.get_terminal_size().columns
                max_len = term_width - 4
                if len(status) > max_len:
                    status = status[:max_len - 3] + "..."
                print(f"  {Colors.MUTED}{status}{Colors.RESET}")
        finally:
            sys.stdout = old_stdout

        # Write cursor-home + content + clear-rest + clear-scrollback as one atomic write
        # \033[K on each line clears trailing old content that the new line doesn't cover
        out = sys.__stdout__ if sys.__stdout__ else sys.stdout
        content = buf.getvalue().replace('\n', '\033[K\n')
        out.write(f"\033[H{content}\033[J\033[3J")
        out.flush()

    def update_status_line_in_place(self, new_status: str):
        """Update just the status line without full re-render.

        Uses ANSI codes to move cursor to last line and overwrite.
        Only works in TTY mode.
        """
        import sys
        if not sys.__stdout__ or not sys.__stdout__.isatty():
            self.status_line = new_status
            return

        old_had_status = bool(self.status_line)
        self.status_line = new_status

        # If status line state changed (had vs didn't have), need full re-render
        if old_had_status != bool(new_status):
            return  # Caller should trigger full re-render

        if not new_status:
            return

        try:
            # Truncate to terminal width to prevent wrapping
            term_width = shutil.get_terminal_size().columns
            max_len = term_width - 4  # Account for "  " prefix and safety margin
            if len(new_status) > max_len:
                new_status = new_status[:max_len - 3] + "..."

            # Move cursor up one line, clear it, print new status
            sys.stdout.write("\033[A\033[2K")  # Up + clear
            sys.stdout.write(f"  {Colors.MUTED}{new_status}{Colors.RESET}\n")
            sys.stdout.flush()
        except OSError:
            pass  # Terminal closed

    def run(self, initial_index: int = 0) -> MenuResult | None:
        """Run menu, returns MenuResult or None if cancelled."""
        selectable = self._selectable()
        if not selectable:
            return None

        if initial_index in selectable:
            self._selected = initial_index
        else:
            self._selected = selectable[0]

        self._scroll_offset = 0
        self._adjust_scroll()

        hotkeys = {item.hotkey.upper(): i for i, item in enumerate(self.items)
                   if isinstance(item, (MenuItem, MenuAction)) and item.hotkey}

        # Use timeout-based input if we have an update callback
        use_timeout = self.update_callback is not None

        with cbreak_noecho():
            check_resize()
            self._last_callback_time = time.monotonic()
            self._render()

            while True:
                if check_resize():
                    self._render()
                    continue

                # Get input (with timeout if we have update callback)
                if use_timeout:
                    key = getch_with_timeout(self.refresh_interval_ms, return_special_keys=True)
                    if key is None:
                        # Timeout - check for updates
                        if self.update_callback:
                            self._last_callback_time = time.monotonic()
                            result = self.update_callback(self)
                            if result == "rebuild":
                                return MenuResult(self.items[self._selected], "rebuild")
                            elif result:
                                self._render()
                        continue
                else:
                    key = getch(return_special_keys=True)

                if check_resize():
                    self._render()
                    continue

                # Periodic callback during rapid input
                if use_timeout:
                    now = time.monotonic()
                    if now - self._last_callback_time >= self.refresh_interval_ms / 1000.0:
                        self._last_callback_time = now
                        if self.update_callback:
                            result = self.update_callback(self)
                            if result == "rebuild":
                                return MenuResult(self.items[self._selected], "rebuild")

                if key == KEY_ESC:
                    return None

                elif key == KEY_UP:
                    delta = -1 + self._drain_arrow_keys()
                    self._move_selection(selectable, delta)
                    self._render()

                elif key == KEY_DOWN:
                    delta = 1 + self._drain_arrow_keys()
                    self._move_selection(selectable, delta)
                    self._render()

                elif key == KEY_PAGE_UP:
                    pos = selectable.index(self._selected)
                    scrollable, _ = self._split_items()
                    page_size = max(1, self._base_visible_capacity() - 2)
                    new_pos = max(0, pos - page_size)
                    self._selected = selectable[new_pos]
                    self._render()

                elif key == KEY_PAGE_DOWN:
                    pos = selectable.index(self._selected)
                    scrollable, _ = self._split_items()
                    page_size = max(1, self._base_visible_capacity() - 2)
                    new_pos = min(len(selectable) - 1, pos + page_size)
                    self._selected = selectable[new_pos]
                    self._render()

                elif key == KEY_ENTER:
                    return MenuResult(self.items[self._selected], "enter")

                elif key == KEY_SPACE:
                    return MenuResult(self.items[self._selected], "space")

                elif key == KEY_TAB:
                    return MenuResult(self.items[self._selected], "tab")

                elif key == KEY_LEFT or key == KEY_RIGHT:
                    current_item = self.items[self._selected]
                    if isinstance(current_item, MenuGroupHeader):
                        return MenuResult(current_item, "enter")

                elif THEME_SWITCHER_ENABLED and isinstance(key, str) and len(key) == 1 and key.upper() == 'C':
                    cycle_theme()
                    invalidate_header_cache()
                    self._render()

                elif isinstance(key, str) and len(key) == 1:
                    upper = key.upper()
                    if upper in hotkeys:
                        self._selected_before_hotkey = self._selected
                        self._selected = hotkeys[upper]
                        return MenuResult(self.items[self._selected], "enter")
                    if key.isdigit() and key != '0':
                        idx = int(key)
                        if idx <= len(selectable):
                            self._selected = selectable[idx - 1]
                            return MenuResult(self.items[self._selected], "enter")
