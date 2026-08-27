"""Manage Synchotic's isolated rclone remote + one-time OAuth consent."""
import json
import subprocess
from typing import Callable

from ..core import constants
from ..core.paths import get_rclone_config_path


def _default_runner(args, **kw):
    return subprocess.run(args, capture_output=True, text=True, **kw)


class RcloneConfig:
    def __init__(self, binary: str, runner: Callable = _default_runner):
        self.binary = binary
        self.runner = runner
        self.config_path = get_rclone_config_path()

    def _base(self) -> list:
        return [self.binary, "--config", str(self.config_path)]

    def has_remote(self) -> bool:
        r = self.runner(self._base() + ["config", "dump"], timeout=10)
        if r.returncode != 0 or not r.stdout.strip():
            return False
        try:
            return constants.RCLONE_REMOTE_NAME in json.loads(r.stdout)
        except Exception:
            return False

    def create_remote(self, timeout: float = 120.0) -> bool:
        """Run interactive consent. rclone opens the browser; user clicks consent once.

        Returns True if the create command succeeded (returncode 0). Does not call
        has_remote() afterward so the last runner call is the create itself (keeps the
        command observable and avoids a redundant dump)."""
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        args = self._base() + [
            "config", "create", constants.RCLONE_REMOTE_NAME, "drive",
            "scope=drive.readonly", "config_is_local=true",
        ]
        try:
            r = self.runner(args, timeout=timeout)
        except subprocess.TimeoutExpired:
            # Headless box, no browser, nobody to click. 300s of silence was the
            # old behaviour; fail fast and let the caller report it instead.
            return False
        return r.returncode == 0

    def is_authed(self) -> bool:
        return self.has_remote()
