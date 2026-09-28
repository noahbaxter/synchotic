"""The app keeps the launcher current.

Launchers never updated, so Windows users ran 1.1 and 1.3 in consoles the app
was never built for. These pin finding the launcher that started the app,
picking the release to move to, and never swapping in one that will not start.
"""
import os
import sys
from pathlib import Path

import pytest

from src.core import launcher_update as lu

MARKED = f"Fixes Windows.\n{lu.OPT_IN}"


def _release(tag, body=MARKED, platform="linux", prerelease=False):
    return {
        "tag_name": tag, "body": body, "draft": False, "prerelease": prerelease,
        "assets": [{"name": lu.ASSETS[platform],
                    "browser_download_url": f"https://example.invalid/{tag}"}],
    }


class TestWhichLauncher:
    def test_a_new_launcher_says_so(self, tmp_path):
        env = {"SYNCHOTIC_LAUNCHER_VERSION": "1.4",
               "SYNCHOTIC_LAUNCHER_PATH": str(tmp_path / "Synchotic.app")}
        assert lu.running_launcher(env) == ((1, 4), tmp_path / "Synchotic.app")

    def test_a_source_run_has_none(self):
        assert lu.running_launcher({}, parent_exe=lambda: Path("/usr/bin/python3")) is None

    def test_a_new_launcher_that_gives_no_path_is_left_alone(self, monkeypatch):
        """A --dev, source or dev-channel run. Guessing from the parent would
        take python.exe for the launcher on Windows."""
        monkeypatch.setattr(sys, "platform", "win32")
        env = {"SYNCHOTIC_LAUNCHER_VERSION": "1.4", "SYNCHOTIC_START_TIME": "1"}
        python = Path("C:/Python311/python.exe")
        assert lu.running_launcher(env, parent_exe=lambda: python) is None

    def test_a_version_it_cannot_read_does_not_stop_the_app(self, tmp_path):
        env = {"SYNCHOTIC_LAUNCHER_VERSION": "1.4-beta",
               "SYNCHOTIC_LAUNCHER_PATH": str(tmp_path / "l.exe")}
        assert lu.running_launcher(env) == (lu.UNKNOWN, tmp_path / "l.exe")

    def test_an_old_windows_launcher_is_the_parent(self, monkeypatch):
        """1.1 and 1.3 both wait on the app as their child."""
        monkeypatch.setattr(sys, "platform", "win32")
        exe = Path("D:/Synchotic/synchotic-launcher.exe")
        found = lu.running_launcher({"SYNCHOTIC_START_TIME": "1"}, parent_exe=lambda: exe)
        assert found == (lu.UNKNOWN, exe)

    def test_the_app_is_never_mistaken_for_the_launcher(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")
        exe = Path("D:/Synchotic/.dm-sync/_app/synchotic-app.exe")
        assert lu.running_launcher({"SYNCHOTIC_START_TIME": "1"}, parent_exe=lambda: exe) is None

    def test_an_old_macos_launcher_is_the_bundle_wezterm_runs_in(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        exe = Path("/Applications/Synchotic.app/Contents/MacOS/wezterm-gui")
        found = lu.running_launcher({"SYNCHOTIC_START_TIME": "1"}, parent_exe=lambda: exe)
        assert found == (lu.UNKNOWN, Path("/Applications/Synchotic.app"))

    def test_an_old_linux_launcher_is_its_appimage(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        env = {"SYNCHOTIC_START_TIME": "1", "APPIMAGE": "/home/me/Synchotic.AppImage"}
        assert lu.running_launcher(env) == (lu.UNKNOWN, Path("/home/me/Synchotic.AppImage"))


class TestWhichRelease:
    def test_the_newest_opted_in_launcher_wins(self):
        releases = [_release("launcher-v1.4"), _release("launcher-v1.10"),
                    _release("launcher-v1.3")]
        assert lu.newest_launcher(releases, "linux")[1] == "launcher-v1.10"

    def test_a_release_without_the_opt_in_is_left_alone(self):
        """How a launcher gets tested by hand before anyone updates to it."""
        assert lu.newest_launcher([_release("launcher-v1.5", body="WIP")], "linux") is None

    def test_prereleases_and_app_releases_are_not_launchers(self):
        releases = [_release("launcher-v1.5", prerelease=True), _release("v1.5.6")]
        assert lu.newest_launcher(releases, "linux") is None

    def test_a_release_missing_this_platform_is_skipped(self):
        assert lu.newest_launcher([_release("launcher-v1.5", platform="win32")], "linux") is None


class TestWhichWindowCloses:
    """The app retitles whatever console it runs in, so a cmd window the user
    started the launcher from looked like one the launcher had opened."""

    def names(self, *names):
        return dict(pids=list(range(len(names))), name_of=lambda pid: names[pid])

    def test_a_double_clicked_console_holds_only_ours(self):
        exe = Path("D:/Synchotic/synchotic-launcher.exe")
        assert lu._others_on_console(exe, **self.names(
            "synchotic-launcher.exe", "synchotic-launcher.exe", "synchotic-app.exe")) == set()

    def test_a_shell_the_user_started_it_from_is_left_open(self):
        exe = Path("D:/Synchotic/synchotic-launcher.exe")
        assert lu._others_on_console(exe, **self.names(
            "cmd.exe", "synchotic-launcher.exe", "synchotic-app.exe")) == {"cmd.exe"}


class TestStartingTheNewLauncher:
    def test_a_launcher_that_will_not_start_does_not_stop_the_app(self, monkeypatch, tmp_path):
        """The swap has happened; this session carries on and the next launch
        starts the new launcher."""
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(lu, "running_launcher", lambda: ((1, 1), tmp_path / "l.exe"))
        monkeypatch.setattr(lu, "_console_window", lambda launcher=None: None)
        monkeypatch.setattr(lu, "update_launcher", lambda **kw: "updated")

        def refuse(*a, **k):
            raise PermissionError("held by antivirus")

        monkeypatch.setattr(lu, "reopen", refuse)
        assert lu.update_at_startup() is False


class TestReopening:
    def test_the_new_launcher_starts_clean(self):
        """PyInstaller's own variables make the next exe think it is a child,
        and the old launcher's describe the install being replaced."""
        env = lu.clean_environment({
            "PATH": "/bin", "SYNCHOTIC_ROOT": "D:/Synchotic", "SYNCHOTIC_START_TIME": "1",
            "_PYI_PARENT_PROCESS_LEVEL": "1", "_MEIPASS2": "x",
            "LD_LIBRARY_PATH": "/tmp/_MEIabc", "LD_LIBRARY_PATH_ORIG": "/usr/lib",
        })
        assert env == {"PATH": "/bin", "LD_LIBRARY_PATH": "/usr/lib"}

    def test_what_the_user_set_survives(self):
        """Dropping SYNCHOTIC_LIBRARY reopened the app on whatever library
        settings.json named, which purge then worked on."""
        user = {"SYNCHOTIC_LIBRARY": "/mnt/charts", "SYNCHOTIC_OAUTH_CLIENT_ID": "id",
                "SYNCHOTIC_THEME": "dark", "SYNCHOTIC_LAUNCHER_DIR": "/opt/s"}
        assert lu.clean_environment(dict(user, SYNCHOTIC_OS_DIRS="1")) == user

    @pytest.mark.parametrize("platform,first", [
        ("win32", "D:/Synchotic/synchotic-launcher.exe"),
        ("darwin", "open"),
        ("linux", "D:/Synchotic/synchotic-launcher.exe"),
    ])
    def test_it_is_started_as_if_double_clicked(self, monkeypatch, platform, first):
        started = []
        monkeypatch.setattr(sys, "platform", platform)
        monkeypatch.setattr(lu.subprocess, "Popen",
                            lambda args, **kw: started.append((args, kw)))
        lu.reopen(Path("D:/Synchotic/synchotic-launcher.exe"))
        args, kw = started[0]
        assert Path(args[0]) == Path(first) or args[0] == first
        if platform == "win32":
            assert kw["creationflags"] & 0x10, "a console of its own, so it moves into WezTerm"
        if platform == "linux":
            assert kw["stdin"] == lu.subprocess.DEVNULL, "no tty, so it opens WezTerm"

    def test_a_source_run_never_updates(self, monkeypatch):
        monkeypatch.setattr(sys, "frozen", False, raising=False)
        assert lu.update_at_startup() is False

    def test_nothing_is_shown_when_there_is_nothing_to_update(self, tmp_path):
        shown = []
        result = lu.update_launcher(
            fetch=lambda: [_release("launcher-v1.4")], download=None,
            launcher=((1, 4), tmp_path / "launcher"), platform="linux",
            work=lambda job: shown.append("spinner") or job())
        assert result == "current" and shown == []


def _script(path: Path, says: str) -> None:
    path.write_text(f"#!/bin/sh\necho {says}\n")
    path.chmod(0o755)


@pytest.mark.skipif(os.name == "nt", reason="runs a shell script as the launcher")
class TestReplacing:
    @pytest.fixture
    def install(self, tmp_path):
        target = tmp_path / "Synchotic-launcher-x86_64.AppImage"
        _script(target, "1.3")
        return target

    def _update(self, install, says, releases=None, current=lu.UNKNOWN):
        return lu.update_launcher(
            fetch=lambda: releases or [_release("launcher-v1.4")],
            download=lambda url, dest: _script(dest, says),
            launcher=(current, install), platform="linux")

    def test_a_newer_launcher_takes_its_place(self, install):
        assert self._update(install, "1.4") == "updated"
        assert "echo 1.4" in install.read_text()
        assert os.access(install, os.X_OK)

    def test_one_that_will_not_say_its_version_is_never_swapped_in(self, install):
        """A launcher that cannot start leaves nothing to run the app with."""
        assert self._update(install, "garbage") == "failed check"
        assert "echo 1.3" in install.read_text()
        assert sorted(p.name for p in install.parent.iterdir()) == [install.name]

    def test_the_same_version_is_left_alone(self, install):
        assert self._update(install, "1.4", current=(1, 4)) == "current"
        assert "echo 1.3" in install.read_text()

    @pytest.mark.skipif(sys.platform != "darwin", reason="needs ditto")
    def test_macos_swaps_the_whole_bundle(self, tmp_path):
        import subprocess

        def bundle(root: Path, says: str) -> Path:
            app = root / "Synchotic.app"
            (app / "Contents" / "MacOS").mkdir(parents=True)
            _script(app / "Contents" / "MacOS" / "Synchotic", says)
            return app

        installed = bundle(tmp_path / "Applications", "1.3")
        build = tmp_path / "build"

        def download(url, dest):
            subprocess.run(["ditto", "-c", "-k", "--keepParent",
                            str(bundle(build, "1.4")), str(dest)], check=True)

        result = lu.update_launcher(fetch=lambda: [_release("launcher-v1.4", platform="darwin")],
                                    download=download, launcher=(lu.UNKNOWN, installed),
                                    platform="darwin")
        assert result == "updated"
        assert "echo 1.4" in (installed / "Contents" / "MacOS" / "Synchotic").read_text()
        assert sorted(p.name for p in installed.parent.iterdir()) == [
            "Synchotic.app", "Synchotic.app.old"]

    def test_what_was_moved_aside_goes_on_the_next_run(self, install):
        self._update(install, "1.4")
        old = install.with_name(install.name + ".old")
        assert old.exists(), "the running launcher waits beside the new one"
        self._update(install, "1.4", current=(1, 4))
        assert not old.exists()
