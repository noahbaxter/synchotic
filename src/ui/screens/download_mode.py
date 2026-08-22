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
        subtitle="Google blocks direct download of large archives. Roughly half of "
                 "all charts are affected, so this choice decides how much of the "
                 "library you can actually get.",
        esc_label="Decide later",
    )

    menu.add_item(MenuItem(
        label="Use rclone  (recommended)",
        value=DOWNLOAD_MODE_RCLONE,
        description="One Google consent click, then everything downloads. Uses "
                    "rclone, an established open-source tool, so the consent screen "
                    "says \"rclone\" rather than Synchotic. Fetches a one-time "
                    "helper (~65 MB) the first time.",
    ))
    menu.add_item(MenuItem(
        label="Use your own Google credentials",
        value=DOWNLOAD_MODE_BYOC,
        description="Same result as rclone and just as fast, with the consent "
                    "screen showing your own project. Requires creating a Google "
                    "Cloud project first, see docs/byoc.md.",
    ))
    menu.add_item(MenuItem(
        label="No sign-in  (limited, most charts will not download)",
        value=DOWNLOAD_MODE_ANONYMOUS,
        description="Skips every blocked archive. You will be missing a large part "
                    "of every drive. Pick this only if you cannot open a browser, "
                    "for example on a headless machine.",
    ))

    initial = 0
    for i, item in enumerate(menu.items):
        if item.value == current:
            initial = i
            break

    result = menu.run(initial_index=initial)
    return result.value if result else None
