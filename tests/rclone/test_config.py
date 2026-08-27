from src.rclone.config import RcloneConfig
from src.core import paths, constants


class FakeRunner:
    def __init__(self):
        self.calls = []
        self.dump = "{}"

    def run(self, args, **kw):
        self.calls.append(args)

        class R:
            pass

        r = R()
        r.returncode = 0
        r.stdout = self.dump if "dump" in args else ""
        r.stderr = ""
        return r


def test_has_remote_false_when_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "get_app_dir", lambda: tmp_path)
    runner = FakeRunner()
    cfg = RcloneConfig(binary="/x/rclone", runner=runner.run)
    assert cfg.has_remote() is False


def test_has_remote_true_when_present(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "get_app_dir", lambda: tmp_path)
    runner = FakeRunner()
    runner.dump = '{"synchotic": {"type": "drive"}}'
    cfg = RcloneConfig(binary="/x/rclone", runner=runner.run)
    assert cfg.has_remote() is True


def test_create_remote_passes_scope_and_config(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "get_app_dir", lambda: tmp_path)
    runner = FakeRunner()
    cfg = RcloneConfig(binary="/x/rclone", runner=runner.run)
    cfg.create_remote()
    args = runner.calls[-1]
    assert "config" in args and "create" in args
    assert constants.RCLONE_REMOTE_NAME in args
    assert "scope=drive.readonly" in args
    assert "--config" in args and str(paths.get_rclone_config_path()) in args
