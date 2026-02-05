"""
Application header component.

ASCII art header with gradient coloring.
"""

from ..primitives import Colors, rgb, get_gradient_color
from ..primitives.colors import get_theme_name, THEME_SWITCHER_ENABLED


ASCII_HEADER = r"""
███████╗██╗   ██╗███╗   ██╗ ██████╗██╗  ██╗ ██████╗ ████████╗██╗ ██████╗
██╔════╝╚██╗ ██╔╝████╗  ██║██╔════╝██║  ██║██╔═══██╗╚══██╔══╝██║██╔════╝
███████╗ ╚████╔╝ ██╔██╗ ██║██║     ███████║██║   ██║   ██║   ██║██║
╚════██║  ╚██╔╝  ██║╚██╗██║██║     ██╔══██║██║   ██║   ██║   ██║██║
███████║   ██║   ██║ ╚████║╚██████╗██║  ██║╚██████╔╝   ██║   ██║╚██████╗
╚══════╝   ╚═╝   ╚═╝  ╚═══╝ ╚═════╝╚═╝  ╚═╝ ╚═════╝    ╚═╝   ╚═╝ ╚═════╝
""".strip('\n')


_header_cache = None
_header_theme = None


def invalidate_header_cache():
    """Clear cached header (call on terminal resize or theme change)."""
    global _header_cache, _header_theme
    _header_cache = None
    _header_theme = None


def print_header():
    """Print the ASCII header with diagonal gradient and version."""
    global _header_cache, _header_theme

    current_theme = get_theme_name()
    if _header_cache is None or _header_theme != current_theme:
        from src import __version__

        _header_theme = current_theme

        lines = ASCII_HEADER.split('\n')
        total = len(lines)
        cached_lines = []

        for row, line in enumerate(lines):
            result = []
            for col, char in enumerate(line):
                if char != ' ':
                    pos = (row / total) * 0.4 + (col / len(line)) * 0.6
                    r, g, b = get_gradient_color(pos)
                    result.append(f"{rgb(r, g, b)}{char}")
                else:
                    result.append(char)
            cached_lines.append(''.join(result) + Colors.RESET)

        version_line = f" {Colors.DIM}v{__version__}{Colors.RESET}"
        if THEME_SWITCHER_ENABLED:
            version_line += f"  {Colors.MUTED}theme: {Colors.HOTKEY}{current_theme}{Colors.RESET}"
        cached_lines.append(version_line)
        cached_lines.append("")
        _header_cache = '\n'.join(cached_lines)

    print(_header_cache)
