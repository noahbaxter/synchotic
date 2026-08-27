"""One place for everything about who you are and how charts arrive.

Download mode, Google sign-in and the data folder were three separate rows on
the main menu. They are the same subject, they are touched rarely, and together
they pushed the row that matters (Sync) down the screen. They live here now, and
the main menu carries a single row whose tagline reports the combined state, so
"rclone - signed out" is visible without opening anything.
"""

from ...config.settings import (DOWNLOAD_MODE_ANONYMOUS, DOWNLOAD_MODE_BYOC,
                                DOWNLOAD_MODE_RCLONE)
from ..widgets.menu import Menu, MenuDivider, MenuItem

MODE_NAMES = {
    DOWNLOAD_MODE_RCLONE: "rclone",
    DOWNLOAD_MODE_BYOC: "BYOC",
    DOWNLOAD_MODE_ANONYMOUS: "no sign-in",
}


def account_status(user_settings=None, auth=None, rclone_connected=False) -> str:
    """The one-line state for the main menu tagline, e.g. "rclone - signed out".

    Says the mode first because that is what the user chose, then whether it is
    actually usable. A mode that cannot download is the thing worth surfacing on
    a screen the user is not currently looking at.
    """
    mode = (user_settings.download_mode if user_settings else "") or DOWNLOAD_MODE_RCLONE
    name = MODE_NAMES.get(mode, mode)

    if mode == DOWNLOAD_MODE_ANONYMOUS:
        return f"{name} - most charts skipped"

    if auth is not None and getattr(auth, "session_expired", False):
        return f"{name} - session expired"

    if mode == DOWNLOAD_MODE_BYOC:
        from ...drive.auth import has_custom_client_config
        if not has_custom_client_config():
            return f"{name} - not set up"
        if auth and auth.is_signed_in:
            return f"{name} - signed in"
        return f"{name} - signed out"

    # rclone carries its own consent, so its connection is the thing that gates
    # downloads. An account sign-in on top is a bonus, not a requirement.
    if not rclone_connected:
        return f"{name} - not connected"
    if auth and auth.is_signed_in:
        return f"{name} - connected, signed in"
    return f"{name} - connected"


def _sign_in_row(auth=None, byoc_configured=False):
    """The Google row, or None when there is no sign-in worth offering.

    Sign-in resolves its client from credentials.json and otherwise falls back to
    Synchotic's own, whose 100-user lifetime cap is full. Offering it to someone
    without their own credentials produces "This app is blocked", so the row is
    simply absent rather than present and broken.
    """
    if auth is not None and getattr(auth, "session_expired", False):
        return MenuItem("  Sign in again", hotkey="G", value="signin",
                        description="Sign in again to restore fast downloads")

    if auth is not None and auth.is_signed_in:
        email = auth.user_email
        label = f"  Sign out ({email})" if email else "  Sign out of Google"
        return MenuItem(label, hotkey="G", value="signout",
                        description="Remove saved Google credentials")

    if byoc_configured:
        return MenuItem("  Sign in to Google", hotkey="G", value="signin",
                        description="Uses the credentials you set up")
    return None


def show_account_screen(user_settings=None, auth=None, rclone_connected=False) -> str:
    """Account and downloads. Returns an action for the caller, or "" to go back."""
    mode = (user_settings.download_mode if user_settings else "") or DOWNLOAD_MODE_RCLONE

    menu = Menu(
        title="Account & Downloads",
        subtitle=f"Currently: {account_status(user_settings, auth, rclone_connected)}",
        esc_label="Back",
        detail_pane=True,
    )

    menu.add_item(MenuItem(
        f"  Download mode: {MODE_NAMES.get(mode, mode)}", hotkey="D", value="download_mode",
        description="How large blocked files are fetched. Decides how much of "
                    "the library you get.",
    ))
    from ...drive.auth import has_custom_client_config
    row = _sign_in_row(auth, has_custom_client_config())
    if row is not None:
        menu.add_item(row)
    menu.add_item(MenuDivider())
    from ...core.paths import get_library_path
    menu.add_item(MenuItem(f"  Chart library: {get_library_path()}", hotkey="L",
                           value="library",
                           description="Where charts are downloaded to"))
    menu.add_item(MenuItem("  Open data folder", hotkey="F", value="open_data_folder",
                           description="Settings, logs, credentials.json"))

    result = menu.run()
    return result.value if result else ""
