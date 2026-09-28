import pytest

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


class TestTheRemoteActuallyWorking:
    """A remote in the config file is not a working one. Its token can be
    revoked from a Google account page or simply expire, and nothing else in
    the app can tell the difference: it just fails every large chart, forever.
    """

    def _cfg(self, tmp_path, monkeypatch, returncode=0, raises=None):
        monkeypatch.setattr(paths, "get_app_dir", lambda: tmp_path)
        calls = []

        def runner(args, **kw):
            calls.append(args)
            if raises:
                raise raises
            class R:
                pass
            r = R()
            r.returncode = returncode
            r.stdout = '{"synchotic": {"type": "drive"}}' if "dump" in args else "{}"
            r.stderr = ""
            return r

        return RcloneConfig(binary="/x/rclone", runner=runner), calls

    def test_a_token_that_answers_is_working(self, tmp_path, monkeypatch):
        cfg, calls = self._cfg(tmp_path, monkeypatch, returncode=0)
        assert cfg.token_works() is True
        assert "about" in calls[-1]
        assert f"{constants.RCLONE_REMOTE_NAME}:" in calls[-1]

    def test_a_token_google_refuses_is_not_working(self, tmp_path, monkeypatch):
        cfg, _ = self._cfg(tmp_path, monkeypatch, returncode=1)
        assert cfg.token_works() is False

    def test_a_probe_that_hangs_is_not_working(self, tmp_path, monkeypatch):
        import subprocess
        cfg, _ = self._cfg(tmp_path, monkeypatch,
                           raises=subprocess.TimeoutExpired("rclone", 20))
        assert cfg.token_works() is False

    def test_reconnect_forgets_the_dead_remote_then_creates_it(self, tmp_path, monkeypatch):
        """`config create` over a live remote keeps the dead token, and
        `config reconnect` asks "Already have a token - refresh?" on output
        we capture, so it waited for an answer nobody could see."""
        cfg, calls = self._cfg(tmp_path, monkeypatch, returncode=0)
        assert cfg.reconnect() is True
        verbs = [args[args.index("config", 3) + 1] for args in calls if "config" in args[3:]]
        assert verbs == ["delete", "create"]
        assert not any("reconnect" in args for args in calls)

    def test_a_remote_that_cannot_be_forgotten_is_not_recreated(self, tmp_path, monkeypatch):
        cfg, calls = self._cfg(tmp_path, monkeypatch, returncode=1)
        assert cfg.reconnect() is False
        assert not any("create" in args for args in calls)

    def test_reconnect_is_only_true_once_the_token_answers(self, tmp_path, monkeypatch):
        """Consent can exit cleanly and still leave a remote that cannot
        reach Drive, which is how this state is reached in the first place."""
        cfg, _ = self._cfg(tmp_path, monkeypatch, returncode=1)
        assert cfg.reconnect() is False

    def test_a_clean_reconnect_that_still_cannot_reach_drive_is_false(self, tmp_path, monkeypatch):
        monkeypatch.setattr(paths, "get_app_dir", lambda: tmp_path)

        def runner(args, **kw):
            return type("R", (), {"returncode": 1 if "about" in args else 0,
                                  "stdout": "{}", "stderr": ""})()

        assert RcloneConfig(binary="/x/rclone", runner=runner).reconnect() is False


class TestSigningOut:
    def _cfg(self, tmp_path, monkeypatch, returncode=0, stderr=""):
        monkeypatch.setattr(paths, "get_app_dir", lambda: tmp_path)
        calls = []

        def runner(args, **kw):
            calls.append(args)
            return type("R", (), {"returncode": returncode, "stdout": "",
                                  "stderr": stderr})()

        return RcloneConfig(binary="/x/rclone", runner=runner), calls

    def test_it_deletes_our_remote_from_our_config(self, tmp_path, monkeypatch):
        """Only our remote, only in our file: the user's own rclone setup is
        not ours to sign out of."""
        cfg, calls = self._cfg(tmp_path, monkeypatch)
        cfg.delete_remote()
        args = calls[-1]
        assert args[args.index("config", 3):] == ["config", "delete",
                                                  constants.RCLONE_REMOTE_NAME]
        assert args[1:3] == ["--config", str(paths.get_rclone_config_path())]

    def test_a_failure_carries_rclones_reason(self, tmp_path, monkeypatch):
        import pytest
        cfg, _ = self._cfg(tmp_path, monkeypatch, returncode=1,
                           stderr="Failed to delete: permission denied\n")
        with pytest.raises(RuntimeError, match="permission denied"):
            cfg.delete_remote()


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


def test_create_remote_answers_every_question_itself(tmp_path, monkeypatch):
    """Newer rclone asks whether to keep its retiring shared client_id before
    consent, default No, and asks about shared drives after it, all on output
    we capture. Checked against rclone 1.75.1 --non-interactive: nothing left."""
    monkeypatch.setattr(paths, "get_app_dir", lambda: tmp_path)
    runner = FakeRunner()
    RcloneConfig(binary="/x/rclone", runner=runner.run).create_remote()
    assert "config_shared_client_id=true" in runner.calls[-1]
    assert "config_change_team_drive=false" in runner.calls[-1]


def test_an_abandoned_consent_leaves_no_remote_behind(tmp_path, monkeypatch):
    """rclone writes the remote before consent. One nobody clicked through
    has no token, and every later launch called that Google not responding."""
    import subprocess
    monkeypatch.setattr(paths, "get_app_dir", lambda: tmp_path)
    calls = []

    def runner(args, **kw):
        calls.append(args)
        if "create" in args:
            raise subprocess.TimeoutExpired("rclone", 120)
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    assert RcloneConfig(binary="/x/rclone", runner=runner).create_remote() is False
    assert "delete" in calls[-1]


def _old_remote_then(tmp_path, monkeypatch, on_create):
    """A config holding a token, and a runner that forgets it on delete and
    runs `on_create` for the consent."""
    monkeypatch.setattr(paths, "get_app_dir", lambda: tmp_path)
    cfg = RcloneConfig(binary="/x/rclone", runner=None)
    cfg.config_path.parent.mkdir(parents=True, exist_ok=True)
    cfg.config_path.write_text("[synchotic]\ntoken = maybe-still-good\n")

    def runner(args, **kw):
        if "delete" in args:
            cfg.config_path.write_text("")
        if "create" in args:
            on_create()
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    cfg.runner = runner
    return cfg


def test_a_reconnect_nobody_finishes_puts_the_old_remote_back(tmp_path, monkeypatch):
    """Dead also means a probe that timed out offline, whose token may still
    be good. Deleting it for a consent that never finished lost it."""
    import subprocess

    def times_out():
        raise subprocess.TimeoutExpired("rclone", 120)

    cfg = _old_remote_then(tmp_path, monkeypatch, times_out)
    assert cfg.reconnect() is False
    assert "maybe-still-good" in cfg.config_path.read_text()


def test_a_reconnect_interrupted_puts_the_old_remote_back(tmp_path, monkeypatch):
    def interrupted():
        raise KeyboardInterrupt

    cfg = _old_remote_then(tmp_path, monkeypatch, interrupted)
    with pytest.raises(KeyboardInterrupt):
        cfg.reconnect()
    assert "maybe-still-good" in cfg.config_path.read_text()


def test_rclone_never_gets_a_terminal_to_ask_on(monkeypatch):
    """A question on captured output has to fail at once, not wait it out."""
    import subprocess
    from src.rclone import config

    seen = {}
    monkeypatch.setattr(subprocess, "run", lambda args, **kw: seen.update(kw))
    config._default_runner(["rclone", "version"])
    assert seen["stdin"] is subprocess.DEVNULL
