"""Manage Synchotic's isolated rclone remote + one-time OAuth consent."""
import json
import subprocess
from typing import Callable

from ..core import constants
from ..core.logging import debug_log
from ..core.paths import get_rclone_config_path


def _default_runner(args, **kw):
    # No stdin: the output is captured, so a question rclone asks is one
    # nobody sees. Without a terminal to read it fails at once instead of
    # waiting out the timeout. Consent needs none, it goes through the browser.
    return subprocess.run(args, capture_output=True, text=True,
                          stdin=subprocess.DEVNULL, **kw)


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
        """Redo consent for a remote that exists but no longer works: forget it,
        then create it again. `config create` over a live remote keeps the dead
        token, and `config reconnect` opens with "Already have a token -
        refresh?", which waited on the captured output for an answer nobody
        could see until it timed out.

        A probe that timed out reads as dead too, so the old remote comes back
        if consent does not finish: an offline user keeps a token that may
        still work."""
        try:
            before = self.config_path.read_bytes()
        except OSError:
            before = None
        try:
            self.delete_remote()
        except (RuntimeError, subprocess.TimeoutExpired) as err:
            debug_log(f"RCLONE_RECONNECT | could not forget the dead remote: {err}")
            return False
        done = False
        try:
            done = self.create_remote(timeout=timeout)
        finally:
            # Ctrl+C during consent too, or the old remote is lost with it.
            if not done and before is not None:
                self.config_path.write_bytes(before)
        return done and self.token_works()

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
        # Every question rclone would ask is answered here: its output is
        # captured, so a prompt would fail on an answer nobody can see. Newer
        # rclone asks whether to keep its shared client_id, default No (1.69.1
        # does not know the option and ignores it), and after consent any
        # account with shared drives is asked whether to use one.
        args = self._base() + [
            "config", "create", constants.RCLONE_REMOTE_NAME, "drive",
            "scope=drive.readonly", "config_is_local=true",
            "config_shared_client_id=true", "config_change_team_drive=false",
        ]
        try:
            r = self.runner(args, timeout=timeout)
            done = r.returncode == 0
        except subprocess.TimeoutExpired:
            # Headless box, no browser, nobody to click. 300s of silence was the
            # old behaviour; fail fast and let the caller report it instead.
            done = False
        if not done:
            # rclone writes the remote before consent, so an abandoned one
            # leaves a remote with no token, which every later launch reports
            # as Google not responding. Only reached with no working remote.
            try:
                self.delete_remote()
            except (RuntimeError, subprocess.TimeoutExpired):
                pass
        return done

    def is_authed(self) -> bool:
        return self.has_remote()
