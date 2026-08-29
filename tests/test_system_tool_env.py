"""Anything we shell out to has to run against the system's libraries.

PyInstaller points LD_LIBRARY_PATH at the folder it unpacked us into, and a
child inherits it. On Fedora that put our bundled libcrypto in front of
flatpak's, which xdg-open reaches through: it failed to load, exited quietly,
and the file manager never opened. The picker helpers were already given a
cleaned environment; open_folder was not.
"""

import subprocess
import sys

import pytest

from src.core import folder_picker
from src.core.files import open_folder, system_tool_env, system_tools_on_path


@pytest.fixture
def frozen(monkeypatch):
    """A PyInstaller build, with the bundle in front of the system libraries."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("LD_LIBRARY_PATH", "/tmp/_MEIabc/_internal")
    monkeypatch.setenv("LD_LIBRARY_PATH_ORIG", "/usr/lib64")


class TestTheEnvironmentHelpersGet:
    def test_the_pre_launch_value_is_put_back(self, frozen):
        env = system_tool_env()
        assert env["LD_LIBRARY_PATH"] == "/usr/lib64"
        assert "LD_LIBRARY_PATH_ORIG" not in env

    def test_it_is_dropped_when_there_was_nothing_before(self, monkeypatch):
        """No _ORIG means the user had no LD_LIBRARY_PATH, not that ours is fine."""
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setenv("LD_LIBRARY_PATH", "/tmp/_MEIabc/_internal")
        monkeypatch.delenv("LD_LIBRARY_PATH_ORIG", raising=False)
        assert "LD_LIBRARY_PATH" not in system_tool_env()

    def test_running_from_source_is_left_alone(self, monkeypatch):
        monkeypatch.setattr(sys, "frozen", False, raising=False)
        monkeypatch.setenv("LD_LIBRARY_PATH", "/opt/mine/lib")
        assert system_tool_env()["LD_LIBRARY_PATH"] == "/opt/mine/lib"


class TestWhatOpenFolderHandsTheFileManager:
    def test_it_does_not_pass_our_libraries_on(self, frozen, monkeypatch, tmp_path):
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
        spawned = {}
        monkeypatch.setattr(subprocess, "Popen",
                            lambda cmd, **kw: spawned.update(cmd=cmd, env=kw.get("env")))

        assert open_folder(tmp_path) is True
        assert spawned["cmd"][0] == "xdg-open"
        assert spawned["env"]["LD_LIBRARY_PATH"] == "/usr/lib64"

    def test_sign_in_is_clean_while_the_browser_opens(self, frozen):
        """webbrowser spawns xdg-open from inside run_local_server, so there is
        no env to pass it: the process itself has to be clean while it runs."""
        import os

        with system_tools_on_path():
            assert os.environ["LD_LIBRARY_PATH"] == "/usr/lib64"
        assert os.environ["LD_LIBRARY_PATH"] == "/tmp/_MEIabc/_internal"

    def test_the_picker_helpers_use_the_same_environment(self, frozen, monkeypatch):
        """One rule for every OS helper, not one per call site."""
        seen = {}

        class Result:
            returncode, stdout, stderr = 0, "/tmp/picked", ""

        monkeypatch.setattr(subprocess, "run",
                            lambda cmd, **kw: seen.update(env=kw.get("env")) or Result())
        folder_picker._run(["kdialog", "--getexistingdirectory", "/tmp"])

        assert seen["env"]["LD_LIBRARY_PATH"] == "/usr/lib64"
