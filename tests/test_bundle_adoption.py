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

from pathlib import Path

import pytest

from src.config import jsonc
from src.core import paths


def _library():
    """The library without the Windows MAX_PATH prefix."""
    return Path(paths.plain_path(paths.get_library_path()))


@pytest.fixture(autouse=True)
def os_dirs(monkeypatch, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(paths.Path, "home", staticmethod(lambda: home))
    monkeypatch.setenv(paths.OS_DIRS_ENV, "1")
    monkeypatch.delenv(paths.LEGACY_ROOT_ENV, raising=False)
    monkeypatch.delenv("SYNCHOTIC_ROOT", raising=False)
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
        saved = jsonc.loads(paths.get_settings_path().read_text())
        assert saved["library_path"] == "/Volumes/nas/Charts"

    def test_the_drive_toggles_survive(self, previous):
        paths.adopt_legacy_install()
        saved = jsonc.loads(paths.get_settings_path().read_text())
        assert sum(1 for v in saved["drive_toggles"].values() if v) == 5

    def test_it_does_not_run_twice(self, previous):
        paths.adopt_legacy_install()
        paths.get_settings_path().write_text(json.dumps({"download_mode": "rclone"}))
        assert paths.adopt_legacy_install() == []
        assert jsonc.loads(paths.get_settings_path().read_text())["download_mode"] == "rclone"


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
        saved = jsonc.loads(paths.get_settings_path().read_text())
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

        saved = jsonc.loads(dest.read_text())
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

        saved = jsonc.loads(dest.read_text())
        assert saved["download_mode"] == "rclone"
        assert saved["library_path"] == "/Volumes/picked/Charts"


class TestTheAdoptedLibraryTakesEffectImmediately:
    """Startup resolves the library before it can read a setting, so on the one
    launch that adopts a previous install there is no setting to read yet.
    Leaving it at that pointed the whole session at the default library: markers
    copied into one folder, charts downloaded into it, and the real library
    untouched until the next launch.
    """

    @pytest.fixture
    def previous(self, os_dirs, tmp_path):
        library = tmp_path / "Volumes" / "nas" / "Charts"
        library.mkdir(parents=True)
        state = _install(os_dirs / "Synchotic", library=str(library), drives=5)
        (state / "markers").mkdir()
        (state / "markers" / "drive_setlist_pack_abcd1234.json").write_text('{"files": {}}')
        return library

    def test_the_session_uses_it(self, previous):
        paths.set_library_path(None)  # what startup found: no settings yet
        paths.adopt_legacy_install()
        assert _library() == previous

    def test_the_markers_land_in_it(self, previous):
        paths.set_library_path(None)
        paths.adopt_legacy_install()
        adopted = previous / paths.LIBRARY_STATE_DIR_NAME / "markers"
        assert list(adopted.glob("*.json")), "markers went somewhere else"

    def test_the_default_library_is_left_alone(self, previous, os_dirs):
        paths.set_library_path(None)
        paths.adopt_legacy_install()
        assert not (os_dirs / "Synchotic" / paths.DOWNLOAD_FOLDER_NAME).exists()

    def test_a_library_already_chosen_is_not_overridden(self, os_dirs, tmp_path):
        """The library screen adopts with the folder the user just picked."""
        legacy = _install(tmp_path / "old", library="/Volumes/nas/Charts", drives=1)
        picked = tmp_path / "picked"
        picked.mkdir()
        paths.set_library_path(picked)
        paths.migrate_to_os_dirs(legacy)
        assert _library() == picked


class TestAnImportKeepsEveryPreference:
    """The library screen writes a file of defaults before adopting. A default
    is not a preference, so it must not beat the install being adopted on keys
    whose default is not empty."""

    def test_a_non_default_preference_survives(self, os_dirs, tmp_path):
        legacy = tmp_path / "OldInstall" / paths.DATA_DIR_NAME
        legacy.mkdir(parents=True)
        (legacy / "settings.json").write_text(json.dumps({
            "delete_videos": False,
            "purge_ignore": ["*.txt"],
            "drive_toggles": {"driveA": True},
        }))
        # what the library screen has just written: defaults plus the pick
        from src.config.settings import UserSettings
        fresh = UserSettings.load(paths.get_settings_path())
        fresh.library_path = "/Volumes/picked/Charts"
        fresh.save()

        paths.migrate_to_os_dirs(legacy)

        saved = UserSettings.load(paths.get_settings_path())
        assert saved.download_ignore == []
        assert saved.purge_ignore == ["*.txt"]
        assert saved.drive_toggles == {"driveA": True}
        assert saved.library_path == "/Volumes/picked/Charts"


class TestAPlaceholderIsNotAnInstall:
    """Any launch that finds nothing to adopt writes a file of defaults. That
    file must not lock adoption out or silence the staleness warning."""

    @pytest.fixture
    def placeholder(self, os_dirs):
        """A real install elsewhere, and defaults sitting in the OS data dir."""
        live = _install(os_dirs / "Synchotic", library="/Volumes/nas/Charts",
                        drives=5, age=7 * 86400)
        from src.config.settings import UserSettings
        UserSettings.load(paths.get_settings_path()).save()
        return live

    def test_defaults_do_not_block_adoption(self, placeholder):
        assert paths.adopt_legacy_install() != []

    def test_the_sign_in_and_library_come_across(self, placeholder):
        paths.adopt_legacy_install()
        saved = jsonc.loads(paths.get_settings_path().read_text())
        assert saved["library_path"] == "/Volumes/nas/Charts"
        assert (paths.get_data_dir() / "token.json").exists()

    def test_a_real_preference_still_blocks_it(self, os_dirs):
        """One real choice here means this could be a live install."""
        _install(os_dirs / "Synchotic", library="/Volumes/nas/Charts", drives=5)
        from src.config.settings import UserSettings
        s = UserSettings.load(paths.get_settings_path())
        s.download_mode = "byoc"
        s.save()

        assert paths.adopt_legacy_install() == []
        assert jsonc.loads(paths.get_settings_path().read_text())["download_mode"] == "byoc"

    def test_a_library_pick_alone_is_still_told_about_the_real_install(self, os_dirs):
        """A newer file holding only a fresh library pick is not a rival install."""
        live = _install(os_dirs / "Synchotic", library="/Volumes/nas/Charts",
                        drives=5, age=7 * 86400)
        from src.config.settings import UserSettings
        fresh = UserSettings.load(paths.get_settings_path())
        fresh.library_path = "/Volumes/picked/Charts"
        fresh.save()

        assert str(live) in paths.stale_data_dir_warning()

    def test_an_empty_previous_install_is_not_worth_reporting(self, os_dirs):
        """Nothing to adopt from a folder whose settings are defaults too."""
        empty = os_dirs / "Synchotic" / paths.DATA_DIR_NAME
        empty.mkdir(parents=True)
        (empty / "settings.json").write_text(json.dumps({"drive_toggles": {}}))
        from src.config.settings import UserSettings
        s = UserSettings.load(paths.get_settings_path())
        s.download_mode = "byoc"
        s.save()
        # Newer than the file here, so only its lack of choices keeps it quiet.
        later = time.time() + 60
        os.utime(empty / "settings.json", (later, later))

        assert paths.stale_data_dir_warning() == ""


class TestAWindowsPortableInstall:
    """1.5.4 and earlier on Windows: the launcher's folder holds .dm-sync and,
    by default, Sync Charts. The upgrade moves the state into the OS dirs and
    leaves the library exactly where it was."""

    @pytest.fixture
    def old(self, tmp_path, monkeypatch):
        """The folder the exe sat in, synced on the default library. The app
        runs from its payload, as a shipped build does, not from a checkout
        that may hold a Sync Charts of its own."""
        monkeypatch.setattr(paths, "get_app_dir", lambda: tmp_path / "_app")
        folder = tmp_path / "Clone Hero"
        _install(folder, library="", drives=3)
        pack = folder / paths.DOWNLOAD_FOLDER_NAME / "Drive" / "Setlist" / "song.ini"
        pack.parent.mkdir(parents=True)
        pack.write_text("[song]")
        return folder

    def _startup(self):
        """What sync.py does before anything else reads a setting."""
        from src.config.settings import UserSettings
        from src.core.legacy_migration import default_library_to_adopt

        early = UserSettings.load(paths.get_settings_path())
        adopted = default_library_to_adopt()
        if adopted:
            early.library_path = str(adopted)
            early.save()
            paths.set_library_path(adopted)
        return paths.adopt_legacy_install()

    def test_the_default_library_beside_the_exe_is_kept(self, old, monkeypatch):
        """Found through the old folder: under the OS dirs, "beside the
        executable" is the payload, not where the charts are."""
        monkeypatch.setenv(paths.LEGACY_ROOT_ENV, str(old))
        self._startup()
        assert _library() == old / paths.DOWNLOAD_FOLDER_NAME
        assert (old / paths.DOWNLOAD_FOLDER_NAME / "Drive" / "Setlist" / "song.ini").exists()

    def test_the_sign_in_and_drives_come_across(self, old, monkeypatch):
        """The library pick startup just wrote is not a rival install. Treating
        it as one skipped adoption: signed out, no drives, every upgrade."""
        monkeypatch.setenv(paths.LEGACY_ROOT_ENV, str(old))
        assert self._startup() != []
        assert (paths.get_data_dir() / "token.json").exists()
        saved = jsonc.loads(paths.get_settings_path().read_text())
        assert len(saved["drive_toggles"]) == 3
        assert saved["library_path"] == str(old / paths.DOWNLOAD_FOLDER_NAME)

    def test_the_old_folder_is_left_as_it_was(self, old, monkeypatch):
        monkeypatch.setenv(paths.LEGACY_ROOT_ENV, str(old))
        self._startup()
        assert (old / paths.DATA_DIR_NAME / "token.json").exists()
