"""Spawn and supervise a localhost-only `rclone rcd` daemon."""
import json, os, signal, socket, subprocess, time
from typing import Optional

from ..core.paths import get_rclone_config_path, get_rclone_pid_path


class RcloneDaemon:
    def __init__(self, binary: str):
        self.binary = binary
        self.port: Optional[int] = None
        self.proc: Optional[subprocess.Popen] = None

    @property
    def address(self) -> Optional[str]:
        return f"http://127.0.0.1:{self.port}" if self.port else None

    def _free_port(self) -> int:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        return port

    def _wait_until_up(self, timeout: float = 10.0) -> bool:
        import requests
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.proc and self.proc.poll() is not None:
                return False
            try:
                requests.post(f"{self.address}/rc/noop", timeout=1)
                return True
            except Exception:
                time.sleep(0.1)
        return False

    def start(self) -> None:
        self.reap_stale()
        self.port = self._free_port()
        args = [
            self.binary, "rcd",
            "--rc-addr", f"127.0.0.1:{self.port}",
            "--rc-no-auth",
            "--config", str(get_rclone_config_path()),
        ]
        self.proc = subprocess.Popen(
            args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        get_rclone_pid_path().write_text(json.dumps({"pid": self.proc.pid, "port": self.port}))
        if not self._wait_until_up():
            self.stop()
            raise RuntimeError("rclone rcd failed to start")

    def _pid_is_rclone(self, pid: int) -> bool:
        try:
            out = subprocess.run(["ps", "-p", str(pid), "-o", "comm="],
                                 capture_output=True, text=True, timeout=5).stdout
            return "rclone" in out.lower()
        except Exception:
            return False  # be conservative: don't kill unknown pids

    def reap_stale(self) -> None:
        pidfile = get_rclone_pid_path()
        if not pidfile.exists():
            return
        try:
            saved = json.loads(pidfile.read_text())
            pid = saved.get("pid")
            if pid and self._pid_is_rclone(pid):
                os.kill(pid, signal.SIGTERM)
        except Exception:
            pass
        finally:
            pidfile.unlink(missing_ok=True)

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except Exception:
                self.proc.kill()
        get_rclone_pid_path().unlink(missing_ok=True)
        self.proc = None
        self.port = None

    def __enter__(self):
        self.start(); return self
    def __exit__(self, *exc):
        self.stop()
