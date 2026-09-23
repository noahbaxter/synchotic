"""First-run choice: how should virus-scan-blocked charts be downloaded?

Google refuses direct download of large archives, which is most of the library,
not an edge case: 637 of 1272 sampled files are blocked and every measured drive
contains them. Embedded OAuth is not offered because the 100-user cap is full and
verification was rejected, so it would simply fail for anyone new.
"""

from ... import copy
from ..widgets.menu import Menu, MenuItem
from ...config.settings import (DOWNLOAD_MODE_ANONYMOUS, DOWNLOAD_MODE_BYOC,
                                DOWNLOAD_MODE_RCLONE)


def choose_download_mode(current: str = "", intro: str = "",
                         setup_step=None, esc_label: str = copy.BTN_BACK) -> str | None:
    """Show the chooser. Returns the selected mode, or None if the user escaped.

    `intro` replaces the standing subtitle, for callers with something more
    specific to say. It is a parameter rather than something the caller prints
    first because this screen repaints. `setup_step` heads the box the same way
    every other first-run screen is headed.
    """
    from ..widgets import display

    question = copy.MODE_QUESTION
    body = intro or copy.MODE_INTRO
    # In setup the box is headed FIRST TIME SETUP / Download Mode, and the
    # three options are the question, so asking it again in words is a line
    # nobody needs to read.
    heading, subtitle = display.setup_frame("" if setup_step else question,
                                            body, setup_step, copy.STEP_MODE)

    menu = Menu(
        title=heading,
        subtitle=subtitle,
        esc_label=esc_label,
        detail_pane=True,
    )

    menu.add_item(MenuItem(label=copy.MODE_RCLONE_LABEL,
                           value=DOWNLOAD_MODE_RCLONE,
                           description=copy.MODE_RCLONE_DESC))
    menu.add_item(MenuItem(label=copy.MODE_BYOC_LABEL,
                           value=DOWNLOAD_MODE_BYOC,
                           description=copy.MODE_BYOC_DESC))
    menu.add_item(MenuItem(label=copy.MODE_ANON_LABEL,
                           value=DOWNLOAD_MODE_ANONYMOUS,
                           description=copy.MODE_ANON_DESC))

    # Whatever they are on now, else the best option they can actually take.
    # Somebody with credentials.json already in place has done the ten minutes
    # of work, so starting them on the easy-but-expiring option would be
    # recommending the worse of the two to the one person it does not cost
    # anything.
    preferred = current
    if not preferred:
        from ...drive.auth import has_custom_client_config
        preferred = (DOWNLOAD_MODE_BYOC if has_custom_client_config()
                     else DOWNLOAD_MODE_RCLONE)

    initial = 0
    for i, item in enumerate(menu.items):
        if item.value == preferred:
            initial = i
            break

    result = menu.run(initial_index=initial)
    return result.value if result else None


def change_download_mode(user_settings, sync=None, intro: str = "",
                         setup_step=None, **kw) -> str | None:
    """Re-open the chooser later on, persist the pick, apply it to a live sync.

    Returns the chosen mode, or None if the user backed out.
    """
    chosen = choose_download_mode(current=user_settings.download_mode,
                                  intro=intro, setup_step=setup_step, **kw)
    if not chosen:
        return None
    user_settings.download_mode = chosen
    user_settings.save()
    if sync is not None:
        sync.download_mode = chosen
    return chosen


def connection_step_for(mode: str, *, rclone_authed: bool, signed_in: bool,
                        byoc_configured: bool) -> str:
    """What still needs connecting after picking `mode`.

    Returns "rclone", "signin", "byoc_setup", or "" for nothing to do. Callers
    run the step immediately rather than at download time, so a setup that
    cannot work fails in front of the user instead of halfway through a sync.

    BYOC without credentials must never reach sign-in: it would fall back to the
    embedded client, which is the blocked one, while also disabling the rclone
    tier that would have rescued the download.
    """
    if mode == DOWNLOAD_MODE_RCLONE and not rclone_authed:
        return "rclone"
    if mode == DOWNLOAD_MODE_BYOC:
        if not byoc_configured:
            return "byoc_setup"
        if not signed_in:
            return "signin"
    return ""


def mode_blocked_step(user_settings, auth, rclone_authed: bool) -> str:
    """The connection step still owed under the current mode, "" when none.

    Callers word it for their own surface, so this returns the step token
    rather than prose: keying one module's wording off another module's exact
    sentence breaks silently the moment either is reworded.
    """
    from ...drive.auth import has_custom_client_config

    mode = (getattr(user_settings, "download_mode", "") if user_settings else "") \
        or DOWNLOAD_MODE_RCLONE
    return connection_step_for(
        mode,
        rclone_authed=rclone_authed,
        signed_in=bool(auth and getattr(auth, "is_signed_in", False)),
        byoc_configured=has_custom_client_config(),
    )


def mode_blocked_reason(user_settings, auth, rclone_authed: bool) -> str:
    """Why Drive is out of reach under the current mode, or "" when it is fine.

    The one rule for "can this install talk to Drive", shared by the menu and
    by sync itself. Sign-in is not that rule: rclone downloads through its own
    remote and anonymous has no token by design, yet both scan public folders
    on the API key alone. Gating either on OAuth blocks a setup that works,
    which is what stopped rclone users syncing at all.
    """
    return MODE_STATUS.get(mode_blocked_step(user_settings, auth, rclone_authed), "")


# Keyed by the step tokens mode_blocked_step returns. The same line is the
# setup page title, the preflight headline, the blocked-sync reason and the
# home screen hint.
MODE_STATUS = {
    "rclone": copy.STATUS_RCLONE,
    "byoc_setup": copy.STATUS_BYOC,
    "signin": copy.STATUS_SIGNED_OUT,
}
