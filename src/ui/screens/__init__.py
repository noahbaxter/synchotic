"""
Full-screen interactive views.

Each screen is a class that manages its own render loop and user interaction.
"""

from .home import MainMenuCache, compute_main_menu_cache, update_menu_cache_on_toggle
from .home_panes import show_main_menu_panes
from .drive_config import DriveConfigScreen, show_subfolder_settings
from .oauth import OAuthPromptScreen, show_oauth_prompt
from .add_folder import AddFolderScreen, show_add_custom_folder
from .download_mode import (change_download_mode, choose_download_mode,
                            connection_step_for)
from .account import account_status
from .library import show_library_screen

__all__ = [
    "account_status",
    "show_library_screen",
    "change_download_mode",
    "choose_download_mode",
    "connection_step_for",
    # Home screen
    "MainMenuCache",
    "compute_main_menu_cache",
    "show_main_menu_panes",
    "update_menu_cache_on_toggle",
    # Drive config
    "DriveConfigScreen",
    "show_subfolder_settings",
    # OAuth
    "OAuthPromptScreen",
    "show_oauth_prompt",
    # Add folder
    "AddFolderScreen",
    "show_add_custom_folder",
]
