"""settings.json: one field table, a commented file people edit, and old
files brought up to date."""

import json

import pytest

from src.config.settings import (
    DEFAULT_DOWNLOAD_IGNORE,
    SETTING_FIELDS,
    SETTINGS_VERSION,
    UserSettings,
    chosen_settings,
    default_settings,
)
from src.config import jsonc


@pytest.fixture
def path(tmp_path):
    return tmp_path / "settings.json"


def _written(path):
    return jsonc.loads(path.read_text())


class TestTheFileItWrites:
    def test_a_fresh_file_is_all_defaults_and_versioned(self, path):
        UserSettings.load(path).save()
        written = _written(path)
        assert written.pop("version") == SETTINGS_VERSION
        assert written == default_settings()

    def test_a_toggle_keeps_the_comments(self, path):
        s = UserSettings.load(path)
        s.save()
        s.toggle_drive("driveA")
        s.save()
        assert "// Sync chart folder location." in path.read_text()
        assert _written(path)["drive_toggles"] == {"driveA": True}

    def test_saving_what_was_loaded_changes_nothing(self, path):
        s = UserSettings.load(path)
        s.library_path = "/mnt/games/Charts"
        s.save()
        first = path.read_text()
        UserSettings.load(path).save()
        assert path.read_text() == first

    def test_every_field_survives_a_round_trip(self, path):
        s = UserSettings.load(path)
        s.library_path = "/mnt/games/Charts"
        s.download_mode = "byoc"
        s.download_ignore = ["*.mkv"]
        s.purge_ignore = ["*.webm"]
        s.drive_toggles = {"driveA": True}
        s.subfolder_toggles = {"driveA": {"Rock Band 3": False}}
        s.save()

        back = UserSettings.load(path)
        for f in SETTING_FIELDS:
            assert getattr(back, f.name) == getattr(s, f.name), f.name


class TestEditingItByHand:
    def test_comments_are_read(self, path):
        path.write_text('{\n // mine\n "library_path": "/mnt/games" // here\n}\n')
        assert UserSettings.load(path).library_path == "/mnt/games"

    def test_a_trailing_comma_is_read(self, path):
        path.write_text('{"library_path": "/mnt/games", "download_mode": "byoc",}')
        s = UserSettings.load(path)
        assert s.library_path == "/mnt/games"
        assert s.download_mode == "byoc"

    def test_a_double_slash_inside_a_value_is_not_a_comment(self, path):
        path.write_text('{"library_path": "//nas/charts"}')
        assert UserSettings.load(path).library_path == "//nas/charts"

    def test_a_hand_added_key_survives_a_save(self, path):
        path.write_text(json.dumps({"library_path": "/mnt/games", "future": ["x"]}))
        UserSettings.load(path).save()
        assert _written(path)["future"] == ["x"]


class TestAFileWeCannotRead:
    def test_it_is_kept_rather_than_overwritten(self, path):
        path.write_text('{"library_path": "/mnt/games" this is not json')
        s = UserSettings.load(path)
        s.save()

        kept = list(path.parent.glob("settings.broken-*.json"))
        assert kept, "the unreadable file was thrown away"
        assert "/mnt/games" in kept[0].read_text()

    def test_a_json_list_is_not_a_settings_file(self, path):
        path.write_text("[1, 2, 3]")
        assert UserSettings.load(path).drive_toggles == {}

    def test_a_junk_value_falls_back_to_its_default(self, path):
        path.write_text(json.dumps({"download_mode": "carrier-pigeon",
                                    "download_ignore": "not-a-list",
                                    "purge_ignore": "not-a-list",
                                    "drive_toggles": "not-a-map"}))
        s = UserSettings.load(path)
        assert s.download_mode == ""
        assert s.download_ignore == list(DEFAULT_DOWNLOAD_IGNORE)
        assert s.purge_ignore == ["._*", ".DS_Store", "Thumbs.db", "desktop.ini"]
        assert s.drive_toggles == {}


class TestComingFromAnOlderFile:
    def test_delete_videos_becomes_a_download_ignore_list(self, path):
        path.write_text(json.dumps({"delete_videos": True, "download_mode": "byoc"}))
        s = UserSettings.load(path)
        assert s.download_ignore == list(DEFAULT_DOWNLOAD_IGNORE)
        assert s.download_mode == "byoc"

    def test_keeping_videos_becomes_an_empty_list(self, path):
        path.write_text(json.dumps({"delete_videos": False}))
        assert UserSettings.load(path).download_ignore == []

    def test_retired_settings_are_dropped_and_the_file_versioned(self, path):
        path.write_text(json.dumps({"delete_videos": True,
                                    "group_expanded": {"DRUMS": False},
                                    "use_default_drives": False,
                                    "oauth_prompted": True,
                                    "delta_mode": "charts"}))
        UserSettings.load(path)
        written = _written(path)
        assert written["version"] == SETTINGS_VERSION
        for gone in ("delete_videos", "group_expanded", "use_default_drives",
                     "oauth_prompted", "delta_mode"):
            assert gone not in written


class TestWhatCountsAsAChoice:
    def test_defaults_are_not_choices(self):
        assert chosen_settings(default_settings()) == {}

    def test_a_changed_value_is(self):
        data = default_settings() | {"download_mode": "byoc"}
        assert chosen_settings(data) == {"download_mode": "byoc"}

    def test_nor_is_a_key_we_cannot_interpret(self):
        assert chosen_settings(default_settings() | {"something_new": 1}) == {}


class TestTheTemplateShipped:
    def test_it_holds_every_setting_at_its_default(self):
        """Fails when a field is added, removed or has its default changed
        without the template being updated to match."""
        from src.config.settings import template_text
        shown = jsonc.loads(template_text())
        assert shown.pop("version") == SETTINGS_VERSION
        assert shown == default_settings()

    def test_every_setting_is_explained(self):
        from src.config.settings import template_text
        lines = template_text().splitlines()
        for f in SETTING_FIELDS:
            at = next(i for i, ln in enumerate(lines)
                      if ln.strip().startswith(f'"{f.name}"'))
            above = [ln for ln in lines[:at] if ln.strip()]
            assert above and above[-1].strip().startswith("//"), \
                f"{f.name} has no comment above it"

    def test_a_missing_template_still_writes_a_usable_file(self, path, monkeypatch):
        from src.config import settings as mod
        monkeypatch.setattr(mod, "template_text", lambda: "")
        s = mod.UserSettings.load(path)
        s.library_path = "/mnt/games"
        s.save()
        assert _written(path)["library_path"] == "/mnt/games"
