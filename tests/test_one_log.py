"""The launcher and the app write one log between them.

They used to keep a folder each, and a user asked for logs sent the launcher's,
which say only that the app started. Each side works the path out on its own,
so this pins that they still agree.
"""

import time

import pytest

import launcher
from src.core import paths


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(paths.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(launcher.Path, "home", lambda: tmp_path)
    for var in ("XDG_DATA_HOME", "LOCALAPPDATA", "SYNCHOTIC_LAUNCHER_DIR", "SYNCHOTIC_ROOT"):
        monkeypatch.delenv(var, raising=False)
    return tmp_path


def _launcher_log(monkeypatch):
    opened = []
    monkeypatch.setattr(launcher, "open", lambda p, *a, **k: opened.append(p) or open(p, *a, **k),
                        raising=False)
    launcher.init_logging()
    launcher.close_logging()
    return opened[0]


def _app_log():
    return paths.get_log_dir() / f"{time.strftime('%Y-%m-%d')}.log"


@pytest.mark.parametrize("platform", ["linux", "darwin", "win32"])
def test_an_installed_launcher_writes_the_apps_log(home, monkeypatch, platform):
    monkeypatch.setattr("sys.platform", platform)
    monkeypatch.setattr(launcher, "is_installed", lambda: True)
    monkeypatch.setattr(launcher, "is_dev_mode", lambda: False)
    monkeypatch.setenv(paths.OS_DIRS_ENV, "1")
    assert _launcher_log(monkeypatch) == _app_log()


def test_a_portable_launcher_writes_the_apps_log(home, monkeypatch):
    monkeypatch.setattr(launcher, "is_installed", lambda: False)
    monkeypatch.setenv("SYNCHOTIC_LAUNCHER_DIR", str(home / "portable"))
    monkeypatch.setenv(paths.OS_DIRS_ENV, "0")
    monkeypatch.setenv("SYNCHOTIC_ROOT", str(home / "portable"))
    assert _launcher_log(monkeypatch) == _app_log()


def test_its_lines_say_they_are_the_launchers(home, monkeypatch):
    monkeypatch.setattr(launcher, "is_installed", lambda: True)
    monkeypatch.setenv(paths.OS_DIRS_ENV, "1")
    text = _launcher_log(monkeypatch).read_text()
    assert "launcher | === Launcher started" in text
