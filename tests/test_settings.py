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
