"""
Full-screen interactive views.

Each screen is a class that manages its own render loop and user interaction.
"""

from .home import HomeScreen, MainMenuCache, compute_main_menu_cache, show_main_menu, update_menu_cache_on_toggle
from .drive_config import DriveConfigScreen, show_subfolder_settings
from .oauth import OAuthPromptScreen, show_oauth_prompt
from .add_folder import AddFolderScreen, show_add_custom_folder
from .download_mode import (change_download_mode, choose_download_mode,
                            connection_step_for)
from .account import account_status, show_account_screen

__all__ = [
    "account_status",
    "show_account_screen",
    "change_download_mode",
    "choose_download_mode",
    "connection_step_for",
    # Home screen
    "HomeScreen",
    "MainMenuCache",
    "compute_main_menu_cache",
    "show_main_menu",
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
