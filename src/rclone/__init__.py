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


MISSING = "missing"   # no remote configured
DEAD = "dead"         # a remote, but Drive will not answer for it
OK = "ok"


def is_authed() -> bool:
    """True when a remote is configured. Says nothing about whether it works.

    Kept cheap on purpose: the home screen reads it every frame through the
    status warmer. Use connection_state() where a wrong answer costs a sync.
    """
    try:
        from ..core.paths import get_rclone_config_path
        if not get_rclone_config_path().exists():
            return False  # no config yet; do not fetch a binary to learn that
        binary = RcloneBinary().resolve()
        return RcloneConfig(binary).is_authed()
    except Exception:
        return False


def connection_state(timeout: float = 20.0) -> str:
    """MISSING, DEAD or OK: what rclone can actually do for us right now. One
    API call, so not for a render loop. DEAD looks like OK everywhere else and
    fails every large chart."""
    try:
        from ..core.paths import get_rclone_config_path
        if not get_rclone_config_path().exists():
            return MISSING
        config = RcloneConfig(RcloneBinary().resolve())
        if not config.has_remote():
            return MISSING
        return OK if config.token_works(timeout=timeout) else DEAD
    except Exception:
        # An rclone we cannot resolve or run is not a dead token: saying DEAD
        # would send someone to redo consent over a missing binary.
        return MISSING


def reconnect(timeout: float = 120.0) -> bool:
    """Redo consent for an existing remote. True when it works afterwards."""
    try:
        return RcloneConfig(RcloneBinary().resolve()).reconnect(timeout=timeout)
    except Exception:
        return False


def sign_out() -> None:
    """Forget the remote, so the next sign-in runs consent from scratch.
    Raises with the reason when it cannot."""
    RcloneConfig(RcloneBinary().resolve()).delete_remote()


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
