"""How charts arrive, as a line of text for the settings pane's Mode row."""

from ... import copy
from ...config.settings import (DOWNLOAD_MODE_ANONYMOUS, DOWNLOAD_MODE_BYOC,
                                DOWNLOAD_MODE_RCLONE)

MODE_NAMES = {
    DOWNLOAD_MODE_RCLONE: copy.MODE_NAME_RCLONE,
    DOWNLOAD_MODE_BYOC: copy.MODE_NAME_BYOC,
    DOWNLOAD_MODE_ANONYMOUS: copy.MODE_ANON_LABEL,
}


def account_status(user_settings=None, auth=None, rclone_connected=False,
                   rclone_dead=False) -> str:
    """The Mode row's value: the mode's name while it can download, otherwise
    the same line setup, preflight and a blocked sync use for why not."""
    from .download_mode import MODE_STATUS, mode_blocked_step

    mode = (user_settings.download_mode if user_settings else "") or DOWNLOAD_MODE_RCLONE
    if rclone_dead and mode == DOWNLOAD_MODE_RCLONE:
        return copy.STATUS_SIGNIN_EXPIRED
    if auth is not None and getattr(auth, "session_expired", False) \
            and mode == DOWNLOAD_MODE_BYOC:
        return copy.STATUS_SIGNIN_EXPIRED
    step = mode_blocked_step(user_settings, auth, rclone_connected)
    return MODE_STATUS.get(step) or MODE_NAMES.get(mode, mode)
