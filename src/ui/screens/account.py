"""How charts arrive, as a line of text for the settings pane's Mode row."""

from ... import copy
from ...config.settings import (DOWNLOAD_MODE_ANONYMOUS, DOWNLOAD_MODE_BYOC,
                                DOWNLOAD_MODE_RCLONE)

MODE_NAMES = {
    DOWNLOAD_MODE_RCLONE: copy.MODE_NAME_RCLONE,
    DOWNLOAD_MODE_BYOC: copy.MODE_NAME_BYOC,
    DOWNLOAD_MODE_ANONYMOUS: copy.MODE_NAME_ANON,
}


def account_status(user_settings=None, auth=None, rclone_connected=False,
                   rclone_dead=False) -> str:
    """The one-line state for the Mode row, e.g. "rclone - signed out".

    Says the mode first because that is what the user chose, then whether it is
    actually usable. A mode that cannot download is the thing worth surfacing on
    a screen the user is not currently looking at.
    """
    mode = (user_settings.download_mode if user_settings else "") or DOWNLOAD_MODE_RCLONE
    return copy.MODE_STATE.format(
        mode=MODE_NAMES.get(mode, mode),
        state=_state(mode, auth, rclone_connected, rclone_dead))


def _state(mode, auth, rclone_connected, rclone_dead) -> str:
    if mode == DOWNLOAD_MODE_ANONYMOUS:
        return copy.STATE_ANON

    if auth is not None and getattr(auth, "session_expired", False):
        return copy.STATE_EXPIRED

    if mode == DOWNLOAD_MODE_BYOC:
        from ...drive.auth import has_custom_client_config
        if not has_custom_client_config():
            return copy.STATE_NOT_SET_UP
        if auth and auth.is_signed_in:
            return copy.STATE_SIGNED_IN
        return copy.STATE_SIGNED_OUT

    # rclone carries its own consent, so its connection is the thing that gates
    # downloads. An account sign-in on top is a bonus, not a requirement.
    if not rclone_connected:
        return copy.STATE_NOT_CONNECTED
    if rclone_dead:
        return copy.STATE_EXPIRED
    if auth and auth.is_signed_in:
        return copy.STATE_CONNECTED_SIGNED_IN
    return copy.STATE_CONNECTED
