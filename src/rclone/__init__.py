"""Public facade for the rclone download tier."""
from typing import Optional

from .binary import RcloneBinary
from .config import RcloneConfig
from .daemon import RcloneDaemon
from .rc_client import RcClient
from .downloader import RcloneDownloader
from ..core import constants


def is_available() -> bool:
    """True if a usable rclone can be resolved (system or downloadable)."""
    try:
        RcloneBinary().resolve()
        return True
    except Exception:
        return False


def is_authed() -> bool:
    try:
        from ..core.paths import get_rclone_config_path
        if not get_rclone_config_path().exists():
            return False  # no config yet; do not fetch a binary to learn that
        binary = RcloneBinary().resolve()
        return RcloneConfig(binary).is_authed()
    except Exception:
        return False


def can_open_browser() -> bool:
    """False where consent could never be completed, so we can skip the attempt.

    Consent opens a browser. On a headless Linux box there is nobody to click it
    and the attempt just burns a binary download and then stalls until timeout.
    """
    import os
    import sys
    if sys.platform in ("darwin", "win32"):
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


class RcloneSession:
    """Context manager: resolves binary, ensures auth, runs a daemon, exposes a downloader."""
    def __init__(self):
        self.binary = RcloneBinary().resolve()
        self.config = RcloneConfig(self.binary)
        self.daemon: Optional[RcloneDaemon] = None
        self.downloader: Optional[RcloneDownloader] = None

    def ensure_authed(self, timeout: float = 120.0) -> bool:
        if self.config.is_authed():
            return True
        return self.config.create_remote(timeout=timeout)

    def __enter__(self):
        self.daemon = RcloneDaemon(self.binary)
        self.daemon.start()
        self.downloader = RcloneDownloader(
            RcClient(self.daemon.address), fs=f"{constants.RCLONE_REMOTE_NAME}:"
        )
        return self
    def __exit__(self, *exc):
        if self.daemon:
            self.daemon.stop()
