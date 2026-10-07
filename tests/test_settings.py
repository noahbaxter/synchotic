"""
Tests for user settings management.

Tests UserSettings class - drive toggles, subfolder toggles, persistence.
"""

import tempfile
from pathlib import Path

import pytest

from src.config.settings import UserSettings


class TestUserSettingsDefaults:
    """Tests for UserSettings default behavior."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_new_user_no_drives_enabled(self, temp_dir):
        """New users (no settings file) have no drives enabled by default."""
        settings = UserSettings.load(temp_dir / "settings.json")

        # No drives should be enabled for new users
        assert not settings.is_drive_enabled("1OTcP60EwXnT73FYy-yjbB2C7yU6mVMTf")
        assert not settings.is_drive_enabled("some_other_drive_id")

    def test_an_upgrade_keeps_the_drives_it_had(self, temp_dir):
        """1.5.4 had every unseen drive on without writing it down. The upgrade
        writes it down once the drives are known."""
        settings_path = temp_dir / "settings.json"
        settings_path.write_text(
            '{"download_mode": "rclone", "delete_videos": true, "use_default_drives": false}')

        settings = UserSettings.load(settings_path)
        settings.settle_drive_defaults(["any_drive_id", "another_drive"])

        assert settings.drive_toggles == {"any_drive_id": True, "another_drive": True}

    def test_an_upgrade_that_quits_in_setup_still_keeps_them(self, temp_dir, monkeypatch):
        """Loading a 1.5.4 file rewrites it straight away. The drives it had on
        used to be written down only once drives loaded, after setup, so a
        launch that quit or crashed in setup lost them for good. Charts on disk
        under a drive that reads as off are what purge deletes."""
        import json
        import sync

        settings_path = temp_dir / "settings.json"
        settings_path.write_text(json.dumps({
            "download_mode": "rclone", "delete_videos": True,
            "drive_toggles": {"picked_drive": True}}))
        drives = temp_dir / "drives.json"
        drives.write_text(json.dumps({"drives": [
            {"name": "Picked", "folder_id": "picked_drive"},
            {"name": "Untouched", "folder_id": "untouched_drive"}]}))
        monkeypatch.setattr(sync, "get_settings_path", lambda: settings_path)
        monkeypatch.setattr(sync, "get_drives_config_path", lambda: drives)
        monkeypatch.setattr(sync, "get_local_manifest_path", lambda: temp_dir / "local.json")
        monkeypatch.setattr(sync, "get_token_path", lambda: temp_dir / "token.json")
        monkeypatch.setattr(sync, "cleanup_tmp_dir", lambda: None)

        # main() loads (and so migrates and saves) settings before SyncApp
        # exists, and may save again. Then this launch quits in setup.
        UserSettings.load(settings_path).save()
        UserSettings.load(settings_path)

        sync.SyncApp()  # the next launch

        after = UserSettings.load(settings_path)
        assert after.is_drive_enabled("untouched_drive") is True
        assert after.is_drive_enabled("picked_drive") is True
        assert "drive_defaults_owed" not in settings_path.read_text()

    @pytest.mark.parametrize("stale", [
        '{"version": 1, "drive_defaults_owed": "false"}',
        '{"drive_toggles": {"a": false}, "drive_defaults_owed": true}',
    ])
    def test_a_stale_or_hand_edited_debt_turns_nothing_on(self, temp_dir, stale):
        """A "false" typed by hand, or one left in a file that is not a 1.5.4
        one, is not an upgrade that owes its drives."""
        settings_path = temp_dir / "settings.json"
        settings_path.write_text(stale)
        UserSettings.load(settings_path).save()

        settings = UserSettings.load(settings_path)
        assert settings.settle_drive_defaults(["b"]) is False
        assert "b" not in settings.drive_toggles

    def test_a_hand_written_file_turns_nothing_on(self, temp_dir):
        """No version and no retired keys is a person's file, not an old one."""
        settings_path = temp_dir / "settings.json"
        settings_path.write_text('{"library_path": "/mnt/ch", "drive_toggles": {"a": true}}')

        settings = UserSettings.load(settings_path)
        assert settings.settle_drive_defaults(["a", "b"]) is False
        assert settings.is_drive_enabled("b") is False

    def test_a_drive_nobody_has_decided_about_is_off(self, temp_dir):
        settings = UserSettings.load(temp_dir / "settings.json")
        assert settings.is_drive_enabled("any_drive_id") is False

    def test_explicit_toggle_respected(self, temp_dir):
        """Explicit drive toggles override defaults."""
        settings = UserSettings.load(temp_dir / "settings.json")

        # Explicitly disable a default drive
        settings.set_drive_enabled("1OTcP60EwXnT73FYy-yjbB2C7yU6mVMTf", False)
        assert not settings.is_drive_enabled("1OTcP60EwXnT73FYy-yjbB2C7yU6mVMTf")

        # Explicitly enable a non-default drive
        settings.set_drive_enabled("custom_drive", True)
        assert settings.is_drive_enabled("custom_drive")

    def test_toggle_drive_returns_new_state(self, temp_dir):
        """toggle_drive() returns the new enabled state."""
        settings_path = temp_dir / "settings.json"
        settings_path.write_text('{"version": 2}')
        settings = UserSettings.load(settings_path)

        # A drive nobody has decided about is off, so the first toggle enables
        new_state = settings.toggle_drive("test_drive")
        assert new_state is True
        assert settings.is_drive_enabled("test_drive")

        # Second toggle disables
        new_state = settings.toggle_drive("test_drive")
        assert new_state is False
        assert not settings.is_drive_enabled("test_drive")


class TestSubfolderToggles:
    """Tests for subfolder enable/disable."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_subfolders_default_enabled(self, temp_dir):
        """Subfolders default to enabled."""
        settings = UserSettings.load(temp_dir / "settings.json")
        assert settings.is_subfolder_enabled("any_drive", "any_setlist")

    def test_disabled_subfolders_returned(self, temp_dir):
        """get_disabled_subfolders returns only disabled ones."""
        settings = UserSettings.load(temp_dir / "settings.json")
        settings.set_subfolder_enabled("drive1", "setlist1", False)
        settings.set_subfolder_enabled("drive1", "setlist2", True)
        settings.set_subfolder_enabled("drive1", "setlist3", False)

        disabled = settings.get_disabled_subfolders("drive1")
        assert disabled == {"setlist1", "setlist3"}

    def test_disabled_subfolders_empty_for_new_drive(self, temp_dir):
        """get_disabled_subfolders returns empty set for drives with no toggles."""
        settings = UserSettings.load(temp_dir / "settings.json")
        disabled = settings.get_disabled_subfolders("unknown_drive")
        assert disabled == set()

    def test_toggle_subfolder_returns_new_state(self, temp_dir):
        """toggle_subfolder() returns the new enabled state."""
        settings = UserSettings.load(temp_dir / "settings.json")

        # First toggle disables (was enabled by default)
        new_state = settings.toggle_subfolder("drive1", "setlist1")
        assert new_state is False

        # Second toggle enables
        new_state = settings.toggle_subfolder("drive1", "setlist1")
        assert new_state is True

    def test_enable_all_subfolders(self, temp_dir):
        """enable_all() enables multiple subfolders at once."""
        settings = UserSettings.load(temp_dir / "settings.json")

        # Disable some first
        settings.set_subfolder_enabled("drive1", "setlist1", False)
        settings.set_subfolder_enabled("drive1", "setlist2", False)

        # Enable all
        settings.enable_all("drive1", ["setlist1", "setlist2", "setlist3"])

        assert settings.is_subfolder_enabled("drive1", "setlist1")
        assert settings.is_subfolder_enabled("drive1", "setlist2")
        assert settings.is_subfolder_enabled("drive1", "setlist3")

    def test_disable_all_subfolders(self, temp_dir):
        """disable_all() disables multiple subfolders at once."""
        settings = UserSettings.load(temp_dir / "settings.json")

        settings.disable_all("drive1", ["setlist1", "setlist2", "setlist3"])

        assert not settings.is_subfolder_enabled("drive1", "setlist1")
        assert not settings.is_subfolder_enabled("drive1", "setlist2")
        assert not settings.is_subfolder_enabled("drive1", "setlist3")


class TestSettingsPersistence:
    """Tests for settings file persistence."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_save_and_load(self, temp_dir):
        """Settings persist across save/load cycle."""
        settings_path = temp_dir / "settings.json"

        # Create and configure
        settings = UserSettings.load(settings_path)
        settings.set_drive_enabled("drive1", False)
        settings.set_subfolder_enabled("drive2", "setlist1", False)
        settings.download_ignore = []
        settings.save()

        # Load fresh
        settings2 = UserSettings.load(settings_path)
        assert not settings2.is_drive_enabled("drive1")
        assert not settings2.is_subfolder_enabled("drive2", "setlist1")
        assert settings2.download_ignore == []

    def test_download_ignore_defaults_to_the_video_types(self, temp_dir):
        """A new install skips videos and nothing else."""
        settings = UserSettings.load(temp_dir / "settings.json")
        assert settings.download_ignore == ["*.mp4", "*.avi", "*.webm", "*.mkv", "*.mov"]


    def test_corrupted_file_treated_as_new(self, temp_dir):
        """Corrupted JSON file treated as new user."""
        settings_path = temp_dir / "settings.json"
        settings_path.write_text("not valid json {{{")

        settings = UserSettings.load(settings_path)

        # Should behave like new user (no drives enabled)
        assert not settings.is_drive_enabled("1OTcP60EwXnT73FYy-yjbB2C7yU6mVMTf")
        assert not settings.is_drive_enabled("random_drive")


class TestSettingsRegressions:
    """Regression tests for real bugs."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_a_file_that_calls_itself_new_but_has_been_used(self, temp_dir):
        """use_default_drives said "new" over a file full of toggles, and the
        old loader corrected it on sight. The upgrade has to read the corrected
        answer, or an install in use for a year loses every drive it never
        explicitly turned on."""
        import json
        settings_path = temp_dir / "settings.json"
        settings_path.write_text(json.dumps({
            "use_default_drives": True,
            "drive_toggles": {"some_drive": False},
            "subfolder_toggles": {},
        }))

        settings = UserSettings.load(settings_path)
        settings.settle_drive_defaults(["some_drive", "untouched_drive"])

        assert settings.is_drive_enabled("untouched_drive") is True
        assert settings.is_drive_enabled("some_drive") is False, "their own choice stands"

    def test_a_fresh_install_turns_nothing_on_by_itself(self, temp_dir):
        settings = UserSettings.load(temp_dir / "nonexistent_settings.json")

        assert settings.is_drive_enabled("any_drive") is False
        assert settings.settle_drive_defaults(["any_drive"]) is False, "nothing to carry over"
        assert settings.is_drive_enabled("any_drive") is False

    def test_disabled_drive_stays_disabled_after_reload(self, temp_dir):
        """
        Regression test: disabled drives must stay disabled after app restart.

        Bug: Users reported Guitar Hero setlists auto-re-enabling on launch.
        """
        settings_path = temp_dir / "settings.json"

        # Simulate first session - user disables a drive
        settings1 = UserSettings.load(settings_path)
        settings1.set_drive_enabled("guitar_hero_drive_id", False)
        settings1.save()

        # Simulate app restart - fresh load
        settings2 = UserSettings.load(settings_path)

        # Drive should still be disabled
        assert not settings2.is_drive_enabled("guitar_hero_drive_id")


class TestAHandEditedFile:
    """settings.json is meant to be edited. Windows reads text in its legacy
    codepage unless told otherwise, and Notepad or PowerShell can write a BOM,
    which threw the whole file away as unreadable."""

    def test_a_bom_keeps_every_choice(self, tmp_path):
        path = tmp_path / "settings.json"
        path.write_bytes(b'\xef\xbb\xbf{"drive_toggles": {"d1": true}, "download_mode": "byoc"}')
        settings = UserSettings.load(path)
        assert settings.is_drive_enabled("d1")
        assert settings.download_mode == "byoc"
        assert not list(tmp_path.glob("*.broken-*")), "set aside as unreadable"

    def test_a_utf8_setlist_name_reads_back_as_written(self, tmp_path):
        path = tmp_path / "settings.json"
        path.write_bytes('{"subfolder_toggles": {"d1": {"Suc [ゲーミー] Charts": false}}}'.encode("utf-8"))
        settings = UserSettings.load(path)
        assert settings.get_disabled_subfolders("d1") == {"Suc [ゲーミー] Charts"}

    def test_one_saved_in_the_legacy_codepage_still_loads(self, tmp_path, monkeypatch):
        """Not UTF-8 at all, which 1.5.6 read fine on Windows: no crash at
        launch, and nothing set aside."""
        monkeypatch.setattr("locale.getpreferredencoding", lambda *a: "cp1252")
        path = tmp_path / "settings.json"
        path.write_bytes('{"subfolder_toggles": {"d1": {"Café Charts": false}}}'.encode("cp1252"))
        settings = UserSettings.load(path)
        assert settings.get_disabled_subfolders("d1") == {"Café Charts"}
        assert not list(tmp_path.glob("*.broken-*")), "set aside as unreadable"

    def test_it_saves_as_utf8(self, tmp_path):
        path = tmp_path / "settings.json"
        settings = UserSettings.load(path)
        settings.set_subfolder_enabled("d1", "ЧёЗаУродыНаСцене", False)
        settings.save()
        assert UserSettings.load(path).get_disabled_subfolders("d1") == {"ЧёЗаУродыНаСцене"}
        path.read_bytes().decode("utf-8")


class TestGroupExpanded:
    """Tests for group expanded state."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_groups_default_expanded(self, temp_dir):
        """Groups default to expanded."""
        settings = UserSettings.load(temp_dir / "settings.json")
        assert settings.is_group_expanded("any_group")
        assert settings.is_group_expanded("another_group")

    def test_toggle_group_expanded(self, temp_dir):
        """toggle_group_expanded() toggles and returns new state."""
        settings = UserSettings.load(temp_dir / "settings.json")

        # First toggle collapses (was expanded by default)
        new_state = settings.toggle_group_expanded("test_group")
        assert new_state is False
        assert not settings.is_group_expanded("test_group")

        # Second toggle expands
        new_state = settings.toggle_group_expanded("test_group")
        assert new_state is True
        assert settings.is_group_expanded("test_group")

    def test_group_state_lasts_the_session_and_is_not_written_down(self, temp_dir):
        """Which groups are open is where the cursor was, not a decision, so it
        is no longer kept in settings.json."""
        settings_path = temp_dir / "settings.json"

        settings = UserSettings.load(settings_path)
        settings.toggle_group_expanded("collapsed_group")
        settings.save()

        assert not settings.is_group_expanded("collapsed_group"), "still holds for now"
        assert "group_expanded" not in settings_path.read_text()
        assert UserSettings.load(settings_path).is_group_expanded("collapsed_group")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
