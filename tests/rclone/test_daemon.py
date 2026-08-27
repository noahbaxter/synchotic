# tests/rclone/test_daemon.py
import json
from src.rclone.daemon import RcloneDaemon
from src.core import paths

class FakeProc:
    def __init__(self): self.pid = 4242; self._alive = True; self.terminated = False
    def poll(self): return None if self._alive else 0
    def terminate(self): self.terminated = True; self._alive = False
    def kill(self): self._alive = False
    def wait(self, timeout=None): return 0

def test_start_writes_pidfile_and_binds_localhost(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "get_app_dir", lambda: tmp_path)
    monkeypatch.setattr(RcloneDaemon, "_free_port", lambda self: 5599)
    spawned = {}
    def fake_popen(args, **kw):
        spawned["args"] = args
        return FakeProc()
    monkeypatch.setattr("subprocess.Popen", fake_popen)
    monkeypatch.setattr(RcloneDaemon, "_wait_until_up", lambda self, timeout=10: True)
    d = RcloneDaemon(binary="/x/rclone")
    d.start()
    assert d.address == "http://127.0.0.1:5599"
    assert "rcd" in spawned["args"]
    assert "--rc-addr" in spawned["args"] and "127.0.0.1:5599" in spawned["args"]
    assert "--rc-no-auth" in spawned["args"]
    saved = json.loads(paths.get_rclone_pid_path().read_text())
    assert saved["pid"] == 4242 and saved["port"] == 5599
    d.stop()

def test_reap_stale_kills_previous_pid(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "get_app_dir", lambda: tmp_path)
    paths.get_rclone_pid_path().write_text(json.dumps({"pid": 9988, "port": 5599}))
    killed = {}
    monkeypatch.setattr("os.kill", lambda pid, sig: killed.setdefault("pid", pid))
    monkeypatch.setattr(RcloneDaemon, "_pid_is_rclone", lambda self, pid: True)
    RcloneDaemon(binary="/x/rclone").reap_stale()
    assert killed["pid"] == 9988
    assert not paths.get_rclone_pid_path().exists()
