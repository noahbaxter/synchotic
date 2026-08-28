"""The macOS launcher only works from inside a .app.

host_paths() looks for wezterm-gui beside sys.executable and wezterm.lua in
../Resources. Those are bundle paths, and there is no ensure_wezterm_macos()
to download a host at runtime the way Windows and Linux have, so a launcher
shipped as a loose binary can never open its own window. The release shipped
one for months. These pin the layout the build script has to produce.
"""

import sys

import pytest

import launcher


@pytest.fixture
def bundle(tmp_path):
    """A .app laid out the way packaging/macos/build_launcher_app.sh builds it."""
    app = tmp_path / "install" / "Synchotic.app"
    macos = app / "Contents" / "MacOS"
    resources = app / "Contents" / "Resources"
    macos.mkdir(parents=True)
    resources.mkdir(parents=True)
    (macos / "Synchotic").touch()
    (macos / "wezterm-gui").touch()
    (resources / "wezterm.lua").touch()
    return app


@pytest.fixture
def frozen(monkeypatch):
    def run(executable):
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "executable", str(executable))
        monkeypatch.setattr(sys, "platform", "darwin")
    return run


class TestTheHostIsInsideTheBundle:
    def test_both_paths_resolve(self, bundle, frozen):
        frozen(bundle / "Contents" / "MacOS" / "Synchotic")
        wezterm, lua = launcher.host_paths()
        assert wezterm.exists(), f"no wezterm-gui at {wezterm}"
        assert lua.exists(), f"no wezterm.lua at {lua}"

    def test_a_loose_binary_finds_nothing(self, tmp_path, frozen):
        """The shape that shipped: nothing beside it, so no window, ever."""
        exe = tmp_path / "synchotic-launcher-macos"
        exe.touch()
        frozen(exe)
        wezterm, _ = launcher.host_paths()
        assert not wezterm.exists()
        assert not launcher.should_relaunch_in_host([], False, wezterm.exists())

    def test_a_bundle_relaunches_into_the_host(self, bundle, frozen):
        frozen(bundle / "Contents" / "MacOS" / "Synchotic")
        wezterm, _ = launcher.host_paths()
        assert launcher.should_relaunch_in_host([], False, wezterm.exists())


class TestWhereTheLauncherWrites:
    """A bundle writes nothing beside itself.

    /Applications is group-writable by admins, so "can I write here" says yes
    and a .app dropped there would put its payload, and every chart, in
    /Applications. Bundles use the OS data dir instead, and hand the app
    SYNCHOTIC_OS_DIRS so it splits its own settings, cache and logs the same way.
    """

    def test_a_bundle_uses_the_os_data_dir(self, bundle, frozen):
        frozen(bundle / "Contents" / "MacOS" / "Synchotic")
        assert launcher.get_launcher_dir() == launcher.os_data_dir()

    def test_it_is_not_beside_the_app(self, bundle, frozen):
        frozen(bundle / "Contents" / "MacOS" / "Synchotic")
        assert launcher.get_launcher_dir() != bundle.parent

    def test_the_os_data_dir_is_application_support(self, bundle, frozen, monkeypatch, tmp_path):
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setattr(launcher.Path, "home", staticmethod(lambda: home))
        frozen(bundle / "Contents" / "MacOS" / "Synchotic")
        assert launcher.get_launcher_dir() == home / "Library" / "Application Support" / "Synchotic"

    def test_a_bundle_is_recognised_as_one(self, bundle, frozen):
        frozen(bundle / "Contents" / "MacOS" / "Synchotic")
        assert launcher.is_bundled() is True

    def test_a_loose_binary_stays_portable(self, tmp_path, frozen):
        """Windows ships exactly that, and it keeps .dm-sync beside itself."""
        exe = tmp_path / "synchotic-launcher.exe"
        exe.touch()
        frozen(exe)
        assert launcher.is_bundled() is False
        assert launcher.get_launcher_dir() == tmp_path


class TestTheTwoHalvesAgree:
    """The launcher and the app resolve the same directories independently.

    launcher.py cannot import src.core.paths (it is a standalone one-file
    build), so the layout is written twice and can drift. It already did: OS
    dirs went in for the .app and nothing ever set SYNCHOTIC_OS_DIRS, so the
    bundles kept writing a portable .dm-sync into ~/Synchotic.
    """

    def test_the_data_dir_matches(self, monkeypatch, tmp_path):
        from src.core import paths

        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setattr(launcher.Path, "home", staticmethod(lambda: home))
        monkeypatch.setattr(paths.Path, "home", staticmethod(lambda: home))
        monkeypatch.setenv(paths.OS_DIRS_ENV, "1")
        assert launcher.os_data_dir() == paths.get_data_dir()

    def test_a_bundle_hands_the_app_os_dirs_not_a_root(self, bundle, frozen, monkeypatch):
        """SYNCHOTIC_ROOT would put the app back in portable mode and nest a
        .dm-sync inside Application Support."""
        monkeypatch.setenv("SYNCHOTIC_ROOT", "/somewhere/stale")
        frozen(bundle / "Contents" / "MacOS" / "Synchotic")
        env = launcher.app_environment()
        assert env["SYNCHOTIC_OS_DIRS"] == "1"
        assert "SYNCHOTIC_ROOT" not in env

    def test_a_loose_executable_still_gets_a_root(self, tmp_path, frozen, monkeypatch):
        monkeypatch.delenv("SYNCHOTIC_OS_DIRS", raising=False)
        exe = tmp_path / "synchotic-launcher.exe"
        exe.touch()
        frozen(exe)
        env = launcher.app_environment()
        assert env["SYNCHOTIC_ROOT"] == str(tmp_path)
        assert "SYNCHOTIC_OS_DIRS" not in env


class TestTheHiddenFolderIsPortableOnly:
    """.dm-sync exists to keep our files out of the user's chart folder. Inside
    the OS data dir there is nothing to hide from, and nesting it there just
    buries the payload a level deeper."""

    def test_a_bundle_has_no_dm_sync_level(self, bundle, frozen):
        frozen(bundle / "Contents" / "MacOS" / "Synchotic")
        assert ".dm-sync" not in str(launcher.get_app_dir())
        assert launcher.get_app_dir() == launcher.os_data_dir() / "_app"

    def test_a_loose_executable_keeps_it(self, tmp_path, frozen):
        exe = tmp_path / "synchotic-launcher.exe"
        exe.touch()
        frozen(exe)
        assert launcher.get_app_dir() == tmp_path / ".dm-sync" / "_app"
