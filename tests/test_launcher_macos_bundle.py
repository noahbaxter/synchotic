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
    """The payload, logs and chart library all land in get_launcher_dir(), and
    the app is handed it as SYNCHOTIC_ROOT."""

    def test_it_is_the_folder_holding_the_app_not_the_bundle(self, bundle, frozen):
        frozen(bundle / "Contents" / "MacOS" / "Synchotic")
        assert launcher.get_launcher_dir() == bundle.parent

    def test_an_unwritable_location_falls_back_home(self, bundle, frozen, monkeypatch, tmp_path):
        """Dragging the app to /Applications would otherwise die at the first
        extract, with the whole portable layout pointed somewhere read-only."""
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setattr(launcher.Path, "home", staticmethod(lambda: home))
        frozen(bundle / "Contents" / "MacOS" / "Synchotic")
        bundle.parent.chmod(0o555)
        try:
            assert launcher.get_launcher_dir() == home / "Synchotic"
        finally:
            bundle.parent.chmod(0o755)

    def test_a_loose_binary_still_uses_its_own_folder(self, tmp_path, frozen):
        """Unchanged for Windows and Linux, which ship exactly that."""
        exe = tmp_path / "synchotic-launcher-linux"
        exe.touch()
        frozen(exe)
        assert launcher.get_launcher_dir() == tmp_path
