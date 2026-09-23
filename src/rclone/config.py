"""Manage Synchotic's isolated rclone remote + one-time OAuth consent."""
import json
import subprocess
from typing import Callable

from ..core import constants
from ..core.logging import debug_log
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

    def token_works(self, timeout: float = 20.0) -> bool:
        """True when the remote can actually reach Drive right now. A revoked,
        expired or half-written token leaves the config looking healthy.
        `about` is one API call, so it proves the token without listing."""
        try:
            r = self.runner(self._base() + ["about", f"{constants.RCLONE_REMOTE_NAME}:",
                                            "--json"], timeout=timeout)
        except subprocess.TimeoutExpired:
            debug_log("RCLONE_PROBE | timed out")
            return False
        except Exception as err:
            debug_log(f"RCLONE_PROBE | {type(err).__name__}: {err}")
            return False
        if r.returncode != 0:
            # Keep rclone's reason: a revoked token is reconnectable, a retired
            # client id is not.
            debug_log(f"RCLONE_PROBE | rc={r.returncode} | "
                      f"{(r.stderr or '').strip()[:300]}")
            return False
        return True

    def reconnect(self, timeout: float = 120.0) -> bool:
        """Redo consent for a remote that exists but no longer works. `config
        create` over a live remote does not refresh its token."""
        try:
            r = self.runner(
                self._base() + ["config", "reconnect",
                                f"{constants.RCLONE_REMOTE_NAME}:"],
                timeout=timeout)
        except subprocess.TimeoutExpired:
            return False
        return r.returncode == 0 and self.token_works()

    def delete_remote(self) -> None:
        """Forget the remote and its token, raising with rclone's reason when
        it cannot. Only touches our own config file, so any rclone remotes the
        user has elsewhere are safe."""
        r = self.runner(self._base() + ["config", "delete",
                                        constants.RCLONE_REMOTE_NAME], timeout=10)
        if r.returncode != 0:
            raise RuntimeError((r.stderr or "").strip() or f"rclone exited {r.returncode}")

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
