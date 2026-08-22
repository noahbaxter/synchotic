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
        binary = RcloneBinary().resolve()
        return RcloneConfig(binary).is_authed()
    except Exception:
        return False


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
