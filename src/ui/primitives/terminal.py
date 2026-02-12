"""
Terminal utilities for DM Chart Sync.

Handles terminal size, clearing, and progress display.
"""

import os
import re

ANSI_PATTERN = re.compile(r'\x1b\[[0-9;]*m')


def strip_ansi(text: str) -> str:
    """Remove ANSI escape codes from text."""
    return ANSI_PATTERN.sub('', text)


def set_terminal_size(cols: int = 90, rows: int = 40):
    """
    Set terminal window size.

    Args:
        cols: Number of columns (width)
        rows: Number of rows (height)
    """
    try:
        if os.name == 'nt':
            # Windows: use mode command (may fail if not in a proper console)
            import subprocess
            subprocess.run(
                f'mode con: cols={cols} lines={rows}',
                shell=True,
                capture_output=True
            )
        else:
            # macOS/Linux: use ANSI escape sequence
            # \x1b[8;{rows};{cols}t sets window size
            print(f'\x1b[8;{rows};{cols}t', end='', flush=True)
    except Exception:
        pass  # Fail silently if terminal resize isn't supported


def clear_screen():
    """Clear the terminal screen using ANSI escape codes."""
    import sys
    # Use sys.__stdout__ to bypass any wrappers (like TeeOutput)
    # \033[H moves cursor home, \033[2J clears screen, \033[3J clears scrollback
    out = sys.__stdout__ if sys.__stdout__ else sys.stdout
    out.write("\033[H\033[2J\033[3J")
    out.flush()


def get_terminal_width() -> int:
    """Get terminal width, with fallback."""
    try:
        return os.get_terminal_size().columns
    except OSError:
        return 80


def truncate_text(text: str, max_len: int, suffix: str = "...") -> str:
    """Truncate text to max_len, adding suffix if truncated. Returns plain text (no ANSI)."""
    text = strip_ansi(text)  # Strip first - colors should be added after truncation, not before
    if len(text) <= max_len:
        return text
    if max_len <= len(suffix):
        return text[:max_len]
    return text[:max_len - len(suffix)] + suffix


def get_available_width(reserved: int = 0, min_width: int = 20) -> int:
    """Get available terminal width minus reserved chars."""
    return max(min_width, get_terminal_width() - reserved)


def print_progress(message: str, prefix: str = "  "):
    """
    Print a progress message that overwrites the previous line.

    Handles narrow terminals by truncating and using ANSI clear codes.
    """
    width = get_terminal_width()
    full_msg = f"{prefix}{message}"

    # Truncate if too long
    if len(strip_ansi(full_msg)) >= width:
        full_msg = truncate_text(full_msg, width - 1)

    # Clear line and print (\033[2K clears entire line)
    print(f"\033[2K\r{full_msg}", end="", flush=True)


def print_long_path_warning(count: int):
    """Print Windows long path warning with registry fix instructions."""
    print(f"  WARNING: {count} files skipped due to path length > 260 chars")
    print(f"  To fix: Enable long paths in Windows Registry:")
    print(f"    HKEY_LOCAL_MACHINE\\SYSTEM\\CurrentControlSet\\Control\\FileSystem")
    print(f"    Set LongPathsEnabled to 1")
    print(f"  IMPORTANT: You must restart your computer after changing this setting!")


SECTION_WIDTH = 50


def print_section_header(name: str, width: int = SECTION_WIDTH):
    """Print a styled section header using box-drawing characters."""
    from .colors import Colors
    c = Colors
    header = f"━━━ {name} "
    header += "━" * max(5, width - len(header))
    print(f"\n{c.BOLD}{header}{c.RESET}")


def make_separator(char: str = "━", width: int = SECTION_WIDTH) -> str:
    """Create a horizontal separator line string."""
    return char * width


def print_separator(char: str = "━", width: int = SECTION_WIDTH):
    """Print a horizontal separator line."""
    print(make_separator(char, width))
