"""First-run choice: how should virus-scan-blocked charts be downloaded?

Google refuses direct download of large archives, which is most of the library,
not an edge case: 637 of 1272 sampled files are blocked and every measured drive
contains them. Embedded OAuth is not offered because the 100-user cap is full and
verification was rejected, so it would simply fail for anyone new.
"""

from ..widgets.menu import Menu, MenuItem
from ...config.settings import (DOWNLOAD_MODE_ANONYMOUS, DOWNLOAD_MODE_BYOC,
                                DOWNLOAD_MODE_RCLONE)


def choose_download_mode(current: str = "") -> str | None:
    """Show the chooser. Returns the selected mode, or None if the user escaped."""
    menu = Menu(
        title="How should Synchotic download large charts?",
        subtitle="Google sometimes blocks anonymous direct downloads of popular "
                 "files, so sign in if you want to make sure you aren't missing "
                 "anything.",
        esc_label="Decide later",
        detail_pane=True,
    )

    menu.add_item(MenuItem(
        label="Use rclone  (recommended)",
        value=DOWNLOAD_MODE_RCLONE,
        description="rclone is a popular online storage sync tool and is the "
                    "easiest way to use Synchotic. Note that rclone shares its API "
                    "limits with all users and may be rate limited at popular times "
                    "of the day.",
    ))
    menu.add_item(MenuItem(
        label="Bring Your Own Creds  (advanced)",
        value=DOWNLOAD_MODE_BYOC,
        description="If you find rclone rate limits annoying, you can always set up "
                    "your own private Google project. This takes about ten minutes "
                    "to do but offers the best experience.",
    ))
    menu.add_item(MenuItem(
        label="No sign-in",
        value=DOWNLOAD_MODE_ANONYMOUS,
        description="No sign-in is required. Just be aware that many game rips will "
                    "not allow anonymous users to download them.",
    ))

    initial = 0
    for i, item in enumerate(menu.items):
        if item.value == current:
            initial = i
            break

    result = menu.run(initial_index=initial)
    return result.value if result else None


def change_download_mode(user_settings, sync=None) -> str | None:
    """Re-open the chooser later on, persist the pick, apply it to a live sync.

    Returns the chosen mode, or None if the user backed out.
    """
    chosen = choose_download_mode(current=user_settings.download_mode)
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
    return {
        "rclone": "rclone is not connected yet",
        "byoc_setup": "your own Google credentials are not set up yet",
        "signin": "you are not signed in to Google",
    }.get(mode_blocked_step(user_settings, auth, rclone_authed), "")
