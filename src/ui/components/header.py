"""
Application header component.

ASCII art header with gradient coloring. chotic-ui draws it on every screen;
this configures it.
"""

from chotic_ui.components.header import (
    configure_header,
    header_height,
    invalidate_header_cache,
    print_header as _draw_header,
)

from ... import copy
from ..primitives import Colors


ASCII_HEADER = r"""
███████╗██╗   ██╗███╗   ██╗ ██████╗██╗  ██╗ ██████╗ ████████╗██╗ ██████╗
██╔════╝╚██╗ ██╔╝████╗  ██║██╔════╝██║  ██║██╔═══██╗╚══██╔══╝██║██╔════╝
███████╗ ╚████╔╝ ██╔██╗ ██║██║     ███████║██║   ██║   ██║   ██║██║
╚════██║  ╚██╔╝  ██║╚██╗██║██║     ██╔══██║██║   ██║   ██║   ██║██║
███████║   ██║   ██║ ╚████║╚██████╗██║  ██║╚██████╔╝   ██║   ██║╚██████╗
╚══════╝   ╚═╝   ╚═╝  ╚═══╝ ╚═════╝╚═╝  ╚═╝ ╚═════╝    ╚═╝   ╚═╝ ╚═════╝
""".strip('\n')

LIBRARY_LABEL = f"{copy.ROW_LIBRARY.lower()} → "

__all__ = ["ASCII_HEADER", "install_header", "print_header", "header_height",
           "invalidate_header_cache", "library_detail"]


def install_header() -> None:
    """Hand chotic-ui the banner, the version, and the library line."""
    from src import __version__
    configure_header(ASCII_HEADER, __version__, detail=library_detail)


def print_header() -> None:
    """Draw the banner, installing it first if nothing has yet."""
    if not header_height():
        install_header()
    _draw_header()


def library_detail(room: int) -> str:
    """Where the charts are going: "library → path", fitted into `room`, or
    LIBRARY_UNSET in the error colour. It is on every screen because a path
    that only appears in Settings is a path nobody checks."""
    from ...core import paths

    if room <= len(LIBRARY_LABEL):
        return ""
    if not paths.library_is_set():
        return f"{Colors.ERROR}{copy.LIBRARY_UNSET}{Colors.RESET}"

    library = _library_label()
    if not library:
        return ""
    path = _fit_path(library, room - len(LIBRARY_LABEL))
    return f"{Colors.MUTED}{LIBRARY_LABEL}{Colors.RESET}{path}"


def _fit_path(path: str, room: int) -> str:
    """Shorten from the front: the folder name at the end is the part anyone
    reads."""
    if len(path) <= room:
        return path
    parts = path.split("/")
    while len(parts) > 1:
        parts.pop(0)
        candidate = "…/" + "/".join(parts)
        if len(candidate) <= room:
            return candidate
    return "…" + path[-(room - 1):]


def _library_label() -> str:
    """The library path, with home shortened to ~. Empty if it cannot be read."""
    from pathlib import Path

    from ...core import paths

    try:
        library = Path(paths.get_library_path())
    except Exception:
        return ""
    try:
        return f"~/{library.relative_to(Path.home())}"
    except ValueError:
        return str(library)
