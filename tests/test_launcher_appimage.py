"""The Linux launcher ships as an AppImage, which breaks two assumptions.

An AppImage runs from a squashfs mount that is unmounted the moment the
process exits, so sys.executable answers neither "where did the user put this"
nor "what should a menu entry point at". AppRun passes the first in through
the environment; $APPIMAGE, set by the runtime, is the second.
"""

import sys
from pathlib import Path

import pytest

import launcher


@pytest.fixture
def in_appimage(monkeypatch, tmp_path):
    """A launcher running from a mount, with the real file elsewhere."""
    mount = tmp_path / ".mount_abc123"
    (mount / "usr" / "bin").mkdir(parents=True)
    exe = mount / "usr" / "bin" / "synchotic-launcher"
    exe.touch()

    kept = tmp_path / "Charts"
    kept.mkdir()
    appimage = kept / "Synchotic-launcher-x86_64.AppImage"
    appimage.touch()

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    monkeypatch.setenv("APPIMAGE", str(appimage))
    monkeypatch.delenv("SYNCHOTIC_LAUNCHER_DIR", raising=False)
    return appimage, kept, exe


class TestWhereTheLauncherWrites:
    """Nothing lands beside the AppImage or inside its mount."""

    def test_it_uses_the_xdg_data_dir(self, in_appimage, monkeypatch, tmp_path):
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.delenv("XDG_DATA_HOME", raising=False)
        monkeypatch.setattr(launcher.Path, "home", staticmethod(lambda: home))
        monkeypatch.setattr(launcher.sys, "platform", "linux")
        assert launcher.get_launcher_dir() == home / ".local" / "share" / "synchotic"

    def test_xdg_data_home_is_honoured(self, in_appimage, monkeypatch, tmp_path):
        xdg = tmp_path / "xdg"
        monkeypatch.setenv("XDG_DATA_HOME", str(xdg))
        monkeypatch.setattr(launcher.sys, "platform", "linux")
        assert launcher.get_launcher_dir() == xdg / "synchotic"

    def test_it_is_not_beside_the_appimage(self, in_appimage, monkeypatch):
        """The folder the user keeps it in is not ours to write into."""
        _, kept, _ = in_appimage
        monkeypatch.setattr(launcher.sys, "platform", "linux")
        assert launcher.get_launcher_dir() != kept

    def test_it_is_not_in_the_mount(self, in_appimage, monkeypatch):
        _, _, exe = in_appimage
        monkeypatch.setattr(launcher.sys, "platform", "linux")
        assert launcher.get_launcher_dir() != exe.parent

    def test_an_appimage_counts_as_bundled(self, in_appimage):
        assert launcher.is_bundled() is True


class TestTheDesktopEntry:
    def test_it_points_at_the_appimage_not_the_mount(self, in_appimage):
        """An entry naming the mount is dead as soon as the app closes."""
        appimage, _, _ = in_appimage
        assert launcher.relaunchable_path() == appimage

    def test_it_falls_back_to_the_running_binary(self, tmp_path, monkeypatch):
        monkeypatch.delenv("APPIMAGE", raising=False)
        exe = tmp_path / "synchotic-launcher"
        exe.touch()
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "executable", str(exe))
        assert launcher.relaunchable_path() == exe


class TestTheCommandHandedToWezTerm:
    """A GUI launch re-execs into WezTerm, which then spawns the launcher again
    with --hosted. That spawn happens after the exec has handed our process to
    WezTerm, and inside an AppImage that releases the squashfs mount. Naming the
    mount left WezTerm with a program that no longer existed: the window opened
    and shut, with nothing on screen and nothing in any log. Running the same
    build from source worked, which is how it stayed hidden.
    """

    @pytest.fixture
    def spawned(self, in_appimage, monkeypatch, tmp_path):
        """The argv a GUI launch would hand WezTerm, without execing anything."""
        wez = tmp_path / "wezterm" / "squashfs-root" / "usr" / "bin"
        wez.mkdir(parents=True)
        gui = wez / "wezterm-gui"
        gui.touch()
        lua = tmp_path / "wezterm" / "wezterm.lua"
        lua.touch()

        monkeypatch.setattr(launcher.sys, "platform", "linux")
        monkeypatch.setattr(launcher, "_has_terminal", lambda: False)
        monkeypatch.setattr(launcher, "ensure_wezterm_linux", lambda: True)
        monkeypatch.setattr(launcher, "host_paths", lambda: (gui, lua))
        monkeypatch.setattr(launcher.sys, "argv", ["synchotic-launcher"])

        captured = {}

        def fake_execve(path, argv, env):
            captured["path"] = path
            captured["argv"] = argv

        monkeypatch.setattr(launcher.os, "execve", fake_execve)
        launcher.maybe_relaunch_in_host()
        return captured

    def test_it_names_the_file_the_user_keeps(self, spawned, in_appimage):
        appimage, _, exe = in_appimage
        assert str(appimage) in spawned["argv"]
        assert str(exe) not in spawned["argv"]

    def test_the_mount_is_never_the_program(self, spawned):
        """The whole failure in one assertion: nothing under a .mount_ path may
        be handed to something that outlives us."""
        assert not any(".mount_" in part for part in spawned["argv"])

    def test_hosted_is_still_the_recursion_guard(self, spawned):
        assert spawned["argv"][-1] == "--hosted"
        assert launcher.should_relaunch_in_host(
            spawned["argv"], has_terminal=False, wezterm_exists=True) is False


class TestTheMovedLauncherCheck:
    """That check reconciles a portable install's .dm-sync with a launcher the
    user dragged somewhere else. A bundle keeps nothing beside itself, and its
    own path is a squashfs mount with a fresh random name every run, so every
    launch compared a path it had never seen against one that no longer existed
    and called it a move. When a stale mount dir did still hold a .dm-sync, that
    landed the user on a move-or-delete prompt they had done nothing to earn.
    """

    def test_a_bundle_is_never_asked(self, in_appimage, monkeypatch, tmp_path):
        asked = []
        monkeypatch.setattr(launcher, "_prompt_directory_action",
                            lambda: asked.append(True) or "I")
        monkeypatch.setattr(launcher, "read_state", lambda: {
            "launcher_path_prod": "/tmp/.mount_gone/usr/bin/synchotic-launcher"})
        saved = []
        monkeypatch.setattr(launcher, "_save_launcher_state", saved.append)

        launcher.handle_directory_change()

        assert asked == []
        assert saved == [], "a mount path is not an identity worth recording"

    def test_a_portable_install_still_gets_the_check(self, monkeypatch, tmp_path):
        """The case the check exists for must keep working."""
        old = tmp_path / "old"
        (old / ".dm-sync").mkdir(parents=True)
        old_exe = old / "synchotic-launcher"
        old_exe.touch()
        new_exe = tmp_path / "new" / "synchotic-launcher"
        new_exe.parent.mkdir()
        new_exe.touch()

        monkeypatch.delenv("APPIMAGE", raising=False)
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "executable", str(new_exe))
        monkeypatch.setattr(launcher, "read_state",
                            lambda: {"launcher_path_prod": str(old_exe)})
        monkeypatch.setattr(launcher, "_save_launcher_state", lambda p: None)
        asked = []
        monkeypatch.setattr(launcher, "_prompt_directory_action",
                            lambda: asked.append(True) or "I")

        launcher.handle_directory_change()

        assert asked == [True]
