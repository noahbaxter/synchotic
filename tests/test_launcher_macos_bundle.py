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
        assert launcher.is_installed() is True


@pytest.fixture
def windows_exe(tmp_path, frozen, monkeypatch):
    """The Windows launcher: one loose exe, wherever the user dropped it."""
    exe = tmp_path / "Downloads" / "synchotic-launcher.exe"
    exe.parent.mkdir()
    exe.touch()
    frozen(exe)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.delenv("SYNCHOTIC_LAUNCHER_DIR", raising=False)
    return exe


class TestTheWindowsExe:
    """One exe, run from anywhere, with its files in the OS data dir like the
    .app and the AppImage. It used to keep a .dm-sync beside itself, which put
    a second layout into the world and a move-or-delete prompt in front of
    anyone who moved it."""

    def test_nothing_is_kept_beside_it(self, windows_exe, tmp_path):
        assert launcher.get_launcher_dir() == tmp_path / "local" / "Synchotic" / "Data"
        assert launcher.get_app_dir() == tmp_path / "local" / "Synchotic" / "Data" / "_app"

    def test_the_app_is_told_to_use_os_dirs(self, windows_exe, monkeypatch):
        monkeypatch.setenv("SYNCHOTIC_ROOT", "/somewhere/stale")
        env = launcher.app_environment()
        assert env["SYNCHOTIC_OS_DIRS"] == "1"
        assert "SYNCHOTIC_ROOT" not in env

    def test_its_folder_is_handed_over_to_adopt(self, windows_exe):
        """Where launcher 1.3 kept .dm-sync, so an upgrade keeps the sign-in."""
        env = launcher.app_environment()
        assert env["SYNCHOTIC_LEGACY_ROOT"] == str(windows_exe.parent)


class TestADevRun:
    """--dev reads a zip beside the binary and --clean deletes its folder, so it
    must never resolve to the OS data dir a real install lives in."""

    @pytest.fixture(autouse=True)
    def dev(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["synchotic-launcher", "--dev"])

    def test_it_stays_beside_the_binary(self, windows_exe):
        assert launcher.is_installed() is False
        assert launcher.get_app_dir() == windows_exe.parent / ".dm-sync" / "_app"

    def test_the_app_stays_out_of_the_os_dirs(self, windows_exe):
        """A frozen Windows app picks the OS dirs itself unless told not to."""
        env = launcher.app_environment()
        assert env["SYNCHOTIC_OS_DIRS"] == "0"
        assert env["SYNCHOTIC_ROOT"] == str(windows_exe.parent)


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


class TestTheHiddenFolderIsDevOnly:
    """Inside the OS data dir there is nothing to hide from, and nesting a
    .dm-sync there just buries the payload a level deeper."""

    def test_a_bundle_has_no_dm_sync_level(self, bundle, frozen):
        frozen(bundle / "Contents" / "MacOS" / "Synchotic")
        assert ".dm-sync" not in str(launcher.get_app_dir())
        assert launcher.get_app_dir() == launcher.os_data_dir() / "_app"
