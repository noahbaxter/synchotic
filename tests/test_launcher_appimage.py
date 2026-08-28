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
        assert launcher.desktop_exec_path() == appimage

    def test_it_falls_back_to_the_running_binary(self, tmp_path, monkeypatch):
        monkeypatch.delenv("APPIMAGE", raising=False)
        exe = tmp_path / "synchotic-launcher"
        exe.touch()
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "executable", str(exe))
        assert launcher.desktop_exec_path() == exe
