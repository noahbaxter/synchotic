"""How charts arrive, as a line of text.

This used to own an Account & Downloads screen. It does not any more: download
type, Google sign-in, library location and the data folder are rows in the home
screen's settings pane, which is where someone goes looking for them. What is
left is the summary string, and the mode names the pane labels itself with.
"""

from ...config.settings import (DOWNLOAD_MODE_ANONYMOUS, DOWNLOAD_MODE_BYOC,
                                DOWNLOAD_MODE_RCLONE)

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
