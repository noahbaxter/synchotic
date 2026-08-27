"""
Interactive UI widgets.

Reusable interactive components with their own input handling and state.
"""

from .menu import (
    Menu,
    MenuItem,
    MenuDivider,
    MenuGroupHeader,
    MenuAction,
    MenuResult,
    check_resize,
)
from .confirm import ConfirmDialog
from .progress import FolderProgress
from . import sync_display as display
from chotic_ui import FilterList  # real-time filterable list (from the submodule)

__all__ = [
    # Menu
    "Menu",
    "MenuItem",
    "MenuDivider",
    "MenuGroupHeader",
    "MenuAction",
    "MenuResult",
    "check_resize",
    # Confirm
    "ConfirmDialog",
    # Filter list
    "FilterList",
    # Progress
    "FolderProgress",
    # Display
    "display",
]
