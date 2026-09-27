"""What the launcher hands the app so the app can keep the launcher current,
and the double-click check that decides whether Windows gets WezTerm.

Launcher 1.3 counted one process on the console as a double-click. A onefile
exe is two, the bootloader and the Python it starts, so every Windows launch
stayed in the default console. In Windows Terminal that console reported the
size `mode con` asked for, not the window's, and the home screen scrolled its
banner off on every repaint.
"""

import ctypes
import sys

import pytest

import launcher


@pytest.fixture
def console(monkeypatch):
    """A console with `n` processes attached."""
    def attach(n, frozen):
        class Kernel32:
            @staticmethod
            def GetConsoleProcessList(arr, size):
                return n

        class WinDLL:
            kernel32 = Kernel32

        monkeypatch.setattr(ctypes, "windll", WinDLL, raising=False)
        monkeypatch.setattr(sys, "frozen", frozen, raising=False)
    return attach


class TestDoubleClickOnWindows:
    def test_the_onefile_bootloader_counts_as_ours(self, console):
        console(2, frozen=True)
        assert launcher._double_clicked_windows()

    def test_a_shell_is_still_left_alone(self, console):
        console(3, frozen=True)
        assert not launcher._double_clicked_windows()

    def test_a_source_run_has_no_bootloader(self, console):
        console(2, frozen=False)
        assert not launcher._double_clicked_windows()


class TestInstallPath:
    def test_macos_replaces_the_whole_bundle(self, tmp_path, monkeypatch):
        exe = tmp_path / "Synchotic.app" / "Contents" / "MacOS" / "Synchotic"
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "executable", str(exe))
        monkeypatch.setattr(sys, "platform", "darwin")
        monkeypatch.delenv("APPIMAGE", raising=False)
        assert launcher.install_path() == tmp_path / "Synchotic.app"

    def test_windows_replaces_the_exe(self, tmp_path, monkeypatch):
        exe = tmp_path / "synchotic-launcher.exe"
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "executable", str(exe))
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.delenv("APPIMAGE", raising=False)
        assert launcher.install_path() == exe

    def test_linux_replaces_the_appimage_not_its_mount(self, tmp_path, monkeypatch):
        image = tmp_path / "Synchotic-launcher-x86_64.AppImage"
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "executable", "/tmp/.mount_abc/usr/bin/synchotic-launcher")
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setenv("APPIMAGE", str(image))
        assert launcher.install_path() == image


class TestFinishingAnUpdate:
    """The app could only move the running launcher aside. The new one, once
    its own window is up, deletes what was moved aside."""

    def _installed(self, monkeypatch, path, platform):
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "platform", platform)
        monkeypatch.delenv("APPIMAGE", raising=False)
        monkeypatch.setattr(launcher, "log", lambda *a: None)
        monkeypatch.setattr(sys, "executable", str(path))

    def test_the_old_exe_is_deleted(self, tmp_path, monkeypatch):
        exe = tmp_path / "synchotic-launcher.exe"
        exe.touch()
        (tmp_path / "synchotic-launcher.exe.old").touch()
        self._installed(monkeypatch, exe, "win32")
        launcher.finish_update()
        assert sorted(p.name for p in tmp_path.iterdir()) == ["synchotic-launcher.exe"]

    def test_the_old_bundle_is_deleted(self, tmp_path, monkeypatch):
        exe = tmp_path / "Synchotic.app" / "Contents" / "MacOS" / "Synchotic"
        exe.parent.mkdir(parents=True)
        (tmp_path / "Synchotic.app.old" / "Contents").mkdir(parents=True)
        self._installed(monkeypatch, exe, "darwin")
        launcher.finish_update()
        assert sorted(p.name for p in tmp_path.iterdir()) == ["Synchotic.app"]

    def test_nothing_to_finish_is_nothing_done(self, tmp_path, monkeypatch):
        exe = tmp_path / "synchotic-launcher.exe"
        exe.touch()
        self._installed(monkeypatch, exe, "win32")
        launcher.finish_update("")
        assert [p.name for p in tmp_path.iterdir()] == ["synchotic-launcher.exe"]


def test_version_prints_and_exits_before_anything_opens(monkeypatch, capsys):
    """The app runs a downloaded launcher this way before swapping it in, so it
    must not log, open WezTerm or start the app."""
    def must_not_run(*args, **kwargs):
        raise AssertionError("--version went past the version check")

    monkeypatch.setattr(launcher, "init_logging", must_not_run)
    monkeypatch.setattr(launcher, "maybe_relaunch_in_host", must_not_run)
    monkeypatch.setattr(sys, "argv", ["synchotic-launcher", "--version"])
    with pytest.raises(SystemExit) as exit_:
        launcher.main()
    assert exit_.value.code == 0
    assert capsys.readouterr().out.strip() == launcher.LAUNCHER_VERSION


class TestTheHostGraceCheck:
    """WezTerm closing within the grace period means it failed, except when the
    app replaced the launcher and started the new one, which takes about two
    seconds. Taking that for a failure ran the app a second time in the old
    console, where it tried to update over the launcher it had just started."""

    @pytest.fixture
    def installed(self, tmp_path, monkeypatch):
        exe = tmp_path / "synchotic-launcher.exe"
        exe.write_bytes(b"1.4")
        monkeypatch.setattr(launcher, "install_path", lambda: exe)
        monkeypatch.setattr(launcher, "log", lambda message: None)
        return exe

    def host(self, script):
        return [sys.executable, "-c", script]

    def test_a_quick_exit_is_a_failure(self, installed):
        assert launcher.host_survived_startup(self.host("pass"), None) is False

    def test_a_quick_exit_after_a_launcher_update_leaves_at_once(self, installed, monkeypatch):
        """Without finishing the update itself: this process is the .old file
        the new launcher is waiting to delete."""
        monkeypatch.setattr(launcher, "close_logging", lambda: None)
        swap = (f"import os; p = {str(installed)!r}; os.rename(p, p + '.old'); "
                "open(p, 'wb').write(b'1.5')")
        with pytest.raises(SystemExit) as exit_:
            launcher.host_survived_startup(self.host(swap), None)
        assert exit_.value.code == 0
