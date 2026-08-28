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
    monkeypatch.setenv("SYNCHOTIC_LAUNCHER_DIR", str(kept))
    return appimage, kept, exe


class TestWhereTheLauncherWrites:
    def test_it_follows_the_folder_apprun_passed_in(self, in_appimage):
        """The payload and chart library land beside the AppImage the user
        kept, not in a mount that disappears."""
        _, kept, _ = in_appimage
        assert launcher.get_launcher_dir() == kept

    def test_without_the_override_it_would_land_in_the_mount(self, in_appimage, monkeypatch):
        """Why the override exists at all."""
        _, _, exe = in_appimage
        monkeypatch.delenv("SYNCHOTIC_LAUNCHER_DIR")
        assert launcher.get_launcher_dir() == exe.parent

    def test_the_override_is_ignored_when_unset(self, tmp_path, monkeypatch):
        """Windows and macOS never set it, so nothing changes for them."""
        monkeypatch.delenv("SYNCHOTIC_LAUNCHER_DIR", raising=False)
        monkeypatch.delenv("APPIMAGE", raising=False)
        exe = tmp_path / "synchotic-launcher.exe"
        exe.touch()
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "executable", str(exe))
        assert launcher.get_launcher_dir() == tmp_path


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
