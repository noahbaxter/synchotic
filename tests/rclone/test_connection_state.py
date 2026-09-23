"""MISSING, DEAD or OK, and what the app does with each. DEAD is a configured
remote whose access Google no longer honours."""
import pytest

from src import copy, rclone


class FakeConfig:
    def __init__(self, has_remote=True, works=True):
        self._has_remote = has_remote
        self._works = works
        self.reconnected = False

    def has_remote(self):
        return self._has_remote

    def is_authed(self):
        return self._has_remote

    def token_works(self, timeout=20.0):
        return self._works

    def reconnect(self, timeout=120.0):
        self.reconnected = True
        return self._works


@pytest.fixture
def wired(tmp_path, monkeypatch):
    """A config file that exists and a binary that resolves, so the state is
    decided by the remote rather than by the plumbing."""
    config_path = tmp_path / "rclone.conf"
    config_path.write_text("[synchotic]\ntype = drive\n")
    monkeypatch.setattr("src.core.paths.get_rclone_config_path", lambda: config_path)
    monkeypatch.setattr("src.rclone.RcloneBinary.resolve", lambda self: "/x/rclone")

    def use(config):
        monkeypatch.setattr("src.rclone.RcloneConfig", lambda binary: config)
        return config

    return use


def test_a_working_remote_is_ok(wired):
    wired(FakeConfig(works=True))
    assert rclone.connection_state() == rclone.OK


def test_a_remote_google_will_not_answer_is_dead(wired):
    wired(FakeConfig(works=False))
    assert rclone.connection_state() == rclone.DEAD


def test_no_remote_is_missing(wired):
    wired(FakeConfig(has_remote=False))
    assert rclone.connection_state() == rclone.MISSING


def test_no_config_file_is_missing_without_resolving_a_binary(tmp_path, monkeypatch):
    """Downloading 60MB of rclone to discover nobody has set it up is the
    behaviour this check exists to avoid."""
    monkeypatch.setattr("src.core.paths.get_rclone_config_path",
                        lambda: tmp_path / "nope.conf")

    def explode(self):
        raise AssertionError("resolved a binary for a missing config")

    monkeypatch.setattr("src.rclone.RcloneBinary.resolve", explode)
    assert rclone.connection_state() == rclone.MISSING


def test_an_rclone_we_cannot_run_is_missing_not_dead(tmp_path, monkeypatch):
    """DEAD sends someone to redo consent. Over a binary that would not run,
    that is advice which cannot work."""
    config_path = tmp_path / "rclone.conf"
    config_path.write_text("[synchotic]\n")
    monkeypatch.setattr("src.core.paths.get_rclone_config_path", lambda: config_path)

    def explode(self):
        raise RuntimeError("checksum mismatch")

    monkeypatch.setattr("src.rclone.RcloneBinary.resolve", explode)
    assert rclone.connection_state() == rclone.MISSING


def test_reconnect_reports_whether_it_took(wired):
    config = wired(FakeConfig(works=True))
    assert rclone.reconnect() is True
    assert config.reconnected is True


@pytest.fixture
def app(monkeypatch):
    """A SyncApp with only what the rclone handlers touch."""
    from sync import SyncApp

    a = object.__new__(SyncApp)
    a.user_settings = None
    a.sync = None
    a.auth = None
    monkeypatch.setattr("src.app.auth._pause", lambda *a_, **k: None)
    monkeypatch.setattr("src.app.auth.display.rclone_consent_explainer", lambda: None)
    monkeypatch.setattr("src.rclone.can_open_browser", lambda: True)
    return a


def test_picking_rclone_with_a_dead_remote_goes_to_reconnect(app, monkeypatch):
    """A configured remote that does not work is not connected."""
    calls = []
    monkeypatch.setattr("src.ui.screens.change_download_mode", lambda *a, **k: "rclone")
    monkeypatch.setattr("src.rclone.connection_state", lambda *a, **k: rclone.DEAD)
    monkeypatch.setattr("src.rclone.is_authed", lambda: True)  # configured, but dead
    monkeypatch.setattr(type(app), "_connect_rclone",
                        lambda self, state: calls.append(("connect", state)))
    app.handle_download_mode()
    # The probe's answer is handed over, not asked for again.
    assert calls == [("connect", rclone.DEAD)]


def test_a_dead_remote_is_reconnected_not_created_again(app, monkeypatch):
    """`config create` over a live remote leaves the dead token in place."""
    calls = []
    monkeypatch.setattr("src.rclone.reconnect", lambda *a, **k: calls.append("reconnect") or True)
    monkeypatch.setattr("src.rclone.RcloneSession",
                        lambda: calls.append("create") or FakeConfig())
    app._connect_rclone(rclone.DEAD)
    assert calls == ["reconnect"]


def test_is_authed_still_answers_the_cheap_question(wired):
    """The home screen reads this every frame, so it stays a config-file
    check: a dead remote is still a configured one."""
    wired(FakeConfig(works=False))
    assert rclone.is_authed() is True


class _Auth:
    def __init__(self):
        self.signed_out = False

    def sign_out(self):
        self.signed_out = True


class TestSettingsSignInFollowsTheMode:
    """One sign-in row, and it signs in to whichever Google access the mode
    downloads with."""

    @pytest.fixture
    def rclone_app(self, app, monkeypatch):
        from types import SimpleNamespace
        app.user_settings = SimpleNamespace(download_mode="rclone")
        app.auth = _Auth()
        monkeypatch.setattr("src.app.auth.wait_with_skip", lambda *a, **k: None)
        return app

    def test_sign_in_connects_rclone_with_its_real_state(self, rclone_app, monkeypatch):
        calls = []
        monkeypatch.setattr("src.rclone.connection_state", lambda *a, **k: rclone.DEAD)
        monkeypatch.setattr(type(rclone_app), "_connect_rclone",
                            lambda self, state: calls.append(state))
        rclone_app.handle_signin()
        assert calls == [rclone.DEAD]

    def test_sign_out_forgets_the_rclone_remote_not_our_token(self, rclone_app, monkeypatch):
        calls = []
        monkeypatch.setattr("src.rclone.sign_out", lambda: calls.append("rclone"))
        rclone_app.handle_signout()
        assert calls == ["rclone"]
        assert rclone_app.auth.signed_out is False

    def test_a_failed_sign_out_says_why(self, rclone_app, monkeypatch, capsys):
        def refuse():
            raise RuntimeError("config is read-only")
        monkeypatch.setattr("src.rclone.sign_out", refuse)
        rclone_app.handle_signout()
        out = capsys.readouterr().out
        assert f"{copy.FAILURE}: config is read-only" in out
