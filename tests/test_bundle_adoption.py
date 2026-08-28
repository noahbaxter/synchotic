"""Upgrading to a bundle must not read as a factory reset.

A real install, reproduced from the one this was found on: settings, sign-in
and rclone config in ~/Synchotic/.dm-sync, and a months-old leftover in the OS
data dir from a dev build. The upgrade found neither, booted the leftover, and
presented a signed-out app with no drives, no credentials and an empty default
library. The next sync from that state re-downloads the whole collection.
"""

import json
import os
import time

import pytest

from src.core import paths


@pytest.fixture(autouse=True)
def os_dirs(monkeypatch, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(paths.Path, "home", staticmethod(lambda: home))
    monkeypatch.setenv(paths.OS_DIRS_ENV, "1")
    monkeypatch.delenv(paths.LEGACY_ROOT_ENV, raising=False)
    monkeypatch.delenv("SYNCHOTIC_LIBRARY", raising=False)
    paths.set_library_path(None)
    yield home
    paths.set_library_path(None)


def _install(root, *, library, drives, mode="byoc", creds=True, age=0.0):
    """A previous install: its state dir, settings, token and credentials."""
    state = root / paths.DATA_DIR_NAME
    state.mkdir(parents=True, exist_ok=True)
    settings = state / "settings.json"
    settings.write_text(json.dumps({
        "library_path": library,
        "download_mode": mode,
        "drive_toggles": {f"drive{i}": True for i in range(drives)},
    }))
    (state / "token.json").write_text('{"token": "signed-in"}')
    if creds:
        (state / "credentials.json").write_text('{"installed": {}}')
    if age:
        old = time.time() - age
        for f in state.iterdir():
            os.utime(f, (old, old))
    return state


class TestFindingThePreviousInstall:
    def test_the_mac_shim_folder_is_searched(self, os_dirs):
        """~/Synchotic is where every .app kept its data before the OS dirs."""
        _install(os_dirs / "Synchotic", library="/Volumes/nas/Charts", drives=5)
        assert paths.legacy_install_candidates()

    def test_the_folder_beside_the_bundle_is_searched(self, os_dirs, monkeypatch, tmp_path):
        """A launcher that used to sit in the user's own folder."""
        beside = tmp_path / "Downloads" / "Synchotic"
        _install(beside, library="/Volumes/nas/Charts", drives=5)
        monkeypatch.setenv(paths.LEGACY_ROOT_ENV, str(beside))
        assert paths.legacy_install_candidates()

    def test_nothing_to_find_is_not_an_error(self):
        """A genuinely fresh install, which is most of them."""
        assert paths.legacy_install_candidates() == []
        assert paths.adopt_legacy_install() == []

    def test_the_liveliest_install_comes_first(self, os_dirs, monkeypatch, tmp_path):
        stale = tmp_path / "old-dev-build"
        _install(stale, library="/old", drives=1, age=180 * 86400)
        _install(os_dirs / "Synchotic", library="/Volumes/nas/Charts", drives=5)
        monkeypatch.setenv(paths.LEGACY_ROOT_ENV, str(stale))
        assert paths.legacy_install_candidates()[0].parent.name == "Synchotic"


class TestAdoptingItAtStartup:
    @pytest.fixture
    def previous(self, os_dirs):
        return _install(os_dirs / "Synchotic",
                        library="/Volumes/nas/Charts", drives=5)

    def test_the_sign_in_survives(self, previous):
        paths.adopt_legacy_install()
        assert (paths.get_data_dir() / "token.json").exists()

    def test_the_credentials_survive(self, previous):
        """Without these, BYOC mode is set but cannot work, and every scan
        fails with a credentials error the user did not cause."""
        paths.adopt_legacy_install()
        assert (paths.get_data_dir() / "credentials.json").exists()

    def test_the_library_location_survives(self, previous):
        """The expensive one. An empty library_path defaults somewhere new, and
        the next sync downloads the entire collection into it."""
        paths.adopt_legacy_install()
        saved = json.loads(paths.get_settings_path().read_text())
        assert saved["library_path"] == "/Volumes/nas/Charts"

    def test_the_drive_toggles_survive(self, previous):
        paths.adopt_legacy_install()
        saved = json.loads(paths.get_settings_path().read_text())
        assert sum(1 for v in saved["drive_toggles"].values() if v) == 5

    def test_it_does_not_run_twice(self, previous):
        paths.adopt_legacy_install()
        paths.get_settings_path().write_text(json.dumps({"download_mode": "rclone"}))
        assert paths.adopt_legacy_install() == []
        assert json.loads(paths.get_settings_path().read_text())["download_mode"] == "rclone"


class TestAStaleDataDirDoesNotWinSilently:
    """The dev-build leftover. Adopting over it could destroy a real install,
    so it is reported rather than resolved, and never ignored."""

    @pytest.fixture
    def conflict(self, os_dirs):
        live = _install(os_dirs / "Synchotic",
                        library="/Volumes/nas/Charts", drives=5)
        stale = paths.get_data_dir() / "settings.json"
        old = time.time() - 180 * 86400
        stale.write_text(json.dumps({"download_mode": "byoc",
                                     "drive_toggles": {"drive0": True}}))
        os.utime(stale, (old, old))
        return live

    def test_the_user_is_told_where_the_real_setup_is(self, conflict):
        assert str(conflict) in paths.stale_data_dir_warning()

    def test_nothing_is_overwritten_behind_their_back(self, conflict):
        paths.adopt_legacy_install()
        saved = json.loads(paths.get_settings_path().read_text())
        assert saved.get("library_path") in (None, "")

    def test_an_up_to_date_data_dir_raises_no_warning(self, os_dirs):
        _install(os_dirs / "Synchotic", library="/Volumes/nas/Charts",
                 drives=5, age=180 * 86400)
        paths.get_settings_path().write_text(json.dumps({"download_mode": "rclone"}))
        assert paths.stale_data_dir_warning() == ""


class TestMergingKeepsTheLivelierFile:
    """The merge exists so the library screen's freshly picked path survives.
    It must not also hand a stale file the sign-in and the drive toggles."""

    def test_a_stale_destination_keeps_only_the_picked_path(self, os_dirs, tmp_path):
        live = _install(tmp_path / "live", library="/old/library", drives=5)
        dest = paths.get_settings_path()
        dest.write_text(json.dumps({"library_path": "/Volumes/picked/Charts",
                                    "download_mode": "byoc",
                                    "drive_toggles": {"drive0": True}}))
        old = time.time() - 180 * 86400
        os.utime(dest, (old, old))

        paths.migrate_to_os_dirs(tmp_path / "live")

        saved = json.loads(dest.read_text())
        assert saved["library_path"] == "/Volumes/picked/Charts", "lost the picked folder"
        assert sum(1 for v in saved["drive_toggles"].values() if v) == 5, "stale toggles won"
        assert (live / "token.json").exists()

    def test_a_current_destination_still_wins(self, os_dirs, tmp_path):
        """The ordinary case: adopting an old install into a live one."""
        _install(tmp_path / "ancient", library="/old", drives=1, age=180 * 86400)
        dest = paths.get_settings_path()
        dest.write_text(json.dumps({"library_path": "/Volumes/picked/Charts",
                                    "download_mode": "rclone"}))

        paths.migrate_to_os_dirs(tmp_path / "ancient")

        saved = json.loads(dest.read_text())
        assert saved["download_mode"] == "rclone"
        assert saved["library_path"] == "/Volumes/picked/Charts"
