"""Tests for custom folder → released drive migration and blocking."""

import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from src.config import DrivesConfig, CustomFolders, UserSettings
from src.config.drives import DriveConfig
from src.core.formatting import normalize_path_key
from src.sync.markers import save_marker
from src.sync.background_scanner import SetlistInfo


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def migration_env(temp_dir, monkeypatch):
    """Isolated environment for testing custom→released migration."""
    download_path = temp_dir / "Sync Charts"
    download_path.mkdir()
    markers_dir = temp_dir / ".dm-sync" / "markers"
    markers_dir.mkdir(parents=True)

    monkeypatch.setattr("src.sync.markers.get_markers_dir", lambda: markers_dir)

    # Patch get_download_path in sync.py where it's called
    monkeypatch.setattr("sync.get_download_path", lambda: download_path)

    return MigrationEnv(
        temp_dir=temp_dir,
        download_path=download_path,
        markers_dir=markers_dir,
    )


class MigrationEnv:
    def __init__(self, temp_dir: Path, download_path: Path, markers_dir: Path):
        self.temp_dir = temp_dir
        self.download_path = download_path
        self.markers_dir = markers_dir

    def make_drives_config(self, drives: list[DriveConfig]) -> DrivesConfig:
        path = self.temp_dir / "drives.json"
        config = DrivesConfig(path)
        config.drives = drives
        return config

    def make_custom_folders(self, folders: list[tuple[str, str]]) -> CustomFolders:
        """Create CustomFolders with given (folder_id, name) pairs."""
        path = self.temp_dir / "local_manifest.json"
        custom = CustomFolders(path)
        for folder_id, name in folders:
            custom.add_folder(folder_id, name)
        custom.save()
        return custom

    def make_download_folder(self, name: str, files: dict[str, int] | None = None):
        """Create a download folder with optional files."""
        folder = self.download_path / name
        folder.mkdir(parents=True, exist_ok=True)
        if files:
            for rel_path, size in files.items():
                full = folder / rel_path
                full.parent.mkdir(parents=True, exist_ok=True)
                full.write_bytes(b"\x00" * size)
        return folder

    def make_marker_file(self, drive_name: str, archive_rel: str, md5: str, extracted: dict[str, int]):
        """Create a marker file. archive_rel is like 'Setlist/pack.7z'."""
        archive_path = f"{drive_name}/{archive_rel}"
        return save_marker(archive_path, md5, extracted)


# ============================================================================
# Migration tests
# ============================================================================

class TestMigrateCustomToReleased:
    """Tests for _migrate_custom_to_released()."""

    def _make_app(self, env: MigrationEnv, drives: list[DriveConfig], custom_folders: list[tuple[str, str]]):
        """Build a minimal SyncApp-like object with just the fields migration needs."""
        from sync import SyncApp

        app = object.__new__(SyncApp)
        app.drives_config = env.make_drives_config(drives)
        app.custom_folders = env.make_custom_folders(custom_folders)
        return app

    def test_no_migration_when_no_overlap(self, migration_env):
        """Custom folders with unique IDs are left alone."""
        drives = [DriveConfig(name="Released Pack", folder_id="released_1")]
        app = self._make_app(migration_env, drives, [("custom_1", "My Custom")])

        app._migrate_custom_to_released()

        assert len(app.custom_folders.folders) == 1
        assert app.custom_folders.folders[0].name == "My Custom"

    def test_migration_removes_custom_entry(self, migration_env):
        """Custom folder matching a released drive gets removed."""
        drives = [DriveConfig(name="CSC Released Packs", folder_id="shared_id")]
        app = self._make_app(migration_env, drives, [("shared_id", "Released Packs - Chorus")])

        app._migrate_custom_to_released()

        assert len(app.custom_folders.folders) == 0
        assert not app.custom_folders.has_folder("shared_id")

    def test_migration_renames_download_folder(self, migration_env):
        """Download folder gets renamed from custom name to released name."""
        custom_name = "Released Packs - Chorus"
        released_name = "CSC Released Packs"

        migration_env.make_download_folder(custom_name, {
            "Setlist1/Chart/song.ini": 100,
        })

        drives = [DriveConfig(name=released_name, folder_id="shared_id")]
        app = self._make_app(migration_env, drives, [("shared_id", custom_name)])

        app._migrate_custom_to_released()

        assert not (migration_env.download_path / custom_name).exists()
        assert (migration_env.download_path / released_name).exists()
        assert (migration_env.download_path / released_name / "Setlist1" / "Chart" / "song.ini").exists()

    def test_migration_skips_rename_when_both_dirs_exist(self, migration_env):
        """If both old and new folders exist, skip rename (don't clobber)."""
        custom_name = "My Custom Name"
        released_name = "Official Name"

        migration_env.make_download_folder(custom_name, {"file1.txt": 10})
        migration_env.make_download_folder(released_name, {"file2.txt": 20})

        drives = [DriveConfig(name=released_name, folder_id="shared_id")]
        app = self._make_app(migration_env, drives, [("shared_id", custom_name)])

        app._migrate_custom_to_released()

        # Both should still exist — old wasn't clobbered
        assert (migration_env.download_path / custom_name).exists()
        assert (migration_env.download_path / released_name).exists()
        # But the custom entry IS removed (migration still proceeds)
        assert not app.custom_folders.has_folder("shared_id")

    def test_migration_skips_rename_when_old_dir_missing(self, migration_env):
        """No error when the custom download folder doesn't exist on disk."""
        drives = [DriveConfig(name="Released", folder_id="shared_id")]
        app = self._make_app(migration_env, drives, [("shared_id", "Custom")])

        # No download folder created — should not crash
        app._migrate_custom_to_released()

        assert not app.custom_folders.has_folder("shared_id")

    def test_migration_renames_marker_files(self, migration_env):
        """Marker files with old name prefix get renamed to new prefix."""
        custom_name = "Released Packs - Chorus"
        released_name = "CSC Released Packs"

        # Create markers under the custom name
        migration_env.make_marker_file(
            custom_name, "Setlist1/pack.7z", "abc12345",
            {"Setlist1/Chart1/song.ini": 100},
        )
        migration_env.make_marker_file(
            custom_name, "Setlist2/pack.7z", "def67890",
            {"Setlist2/Chart2/notes.mid": 200},
        )

        old_prefix = normalize_path_key(custom_name).replace("/", "_").replace("\\", "_") + "_"
        new_prefix = normalize_path_key(released_name).replace("/", "_").replace("\\", "_") + "_"

        # Verify old markers exist before migration
        old_markers = [f for f in migration_env.markers_dir.glob("*.json") if f.stem.lower().startswith(old_prefix)]
        assert len(old_markers) == 2

        drives = [DriveConfig(name=released_name, folder_id="shared_id")]
        app = self._make_app(migration_env, drives, [("shared_id", custom_name)])

        app._migrate_custom_to_released()

        # Old markers should be gone
        remaining_old = [f for f in migration_env.markers_dir.glob("*.json") if f.stem.lower().startswith(old_prefix)]
        assert len(remaining_old) == 0

        # New markers should exist
        new_markers = [f for f in migration_env.markers_dir.glob("*.json") if f.stem.lower().startswith(new_prefix)]
        assert len(new_markers) == 2

    def test_migration_preserves_unrelated_markers(self, migration_env):
        """Markers for other drives are not affected."""
        migration_env.make_marker_file(
            "Unrelated Drive", "Setlist/pack.7z", "zzz99999",
            {"Setlist/Chart/song.ini": 50},
        )

        drives = [DriveConfig(name="Released", folder_id="shared_id")]
        app = self._make_app(migration_env, drives, [("shared_id", "Custom")])

        app._migrate_custom_to_released()

        # Unrelated marker should still exist
        unrelated_prefix = normalize_path_key("Unrelated Drive").replace("/", "_").replace("\\", "_") + "_"
        unrelated = [f for f in migration_env.markers_dir.glob("*.json") if f.stem.lower().startswith(unrelated_prefix)]
        assert len(unrelated) == 1

    def test_migration_handles_multiple_customs(self, migration_env):
        """Multiple custom folders can be migrated in one pass."""
        drives = [
            DriveConfig(name="Pack A", folder_id="id_a"),
            DriveConfig(name="Pack B", folder_id="id_b"),
        ]
        customs = [("id_a", "My Pack A"), ("id_b", "My Pack B"), ("id_c", "Unrelated")]

        migration_env.make_download_folder("My Pack A")
        migration_env.make_download_folder("My Pack B")

        app = self._make_app(migration_env, drives, customs)

        app._migrate_custom_to_released()

        # Two migrated, one remains
        assert len(app.custom_folders.folders) == 1
        assert app.custom_folders.folders[0].folder_id == "id_c"
        assert (migration_env.download_path / "Pack A").exists()
        assert (migration_env.download_path / "Pack B").exists()

    def test_migration_saves_custom_folders_file(self, migration_env):
        """Custom folders file is persisted after migration."""
        drives = [DriveConfig(name="Released", folder_id="shared_id")]
        app = self._make_app(migration_env, drives, [("shared_id", "Custom")])

        app._migrate_custom_to_released()

        # Reload from disk — should reflect removal
        reloaded = CustomFolders.load(app.custom_folders.path)
        assert not reloaded.has_folder("shared_id")

    def test_same_name_duplicate_removed(self, migration_env):
        """Custom folder with same name as released drive is just removed (no renames)."""
        drives = [DriveConfig(name="Same Name", folder_id="shared_id")]
        app = self._make_app(migration_env, drives, [("shared_id", "Same Name")])

        migration_env.make_download_folder("Same Name", {"file.txt": 10})

        app._migrate_custom_to_released()

        assert not app.custom_folders.has_folder("shared_id")
        # Download folder untouched (no rename needed)
        assert (migration_env.download_path / "Same Name" / "file.txt").exists()


# ============================================================================
# Block adding released drives as custom
# ============================================================================

class TestBlockReleasedAsCustom:
    """Tests for blocking released drive IDs from being added as custom."""

    def _make_app(self, env: MigrationEnv, drives: list[DriveConfig]):
        """Build a minimal SyncApp with drives config."""
        from sync import SyncApp

        app = object.__new__(SyncApp)
        app.drives_config = env.make_drives_config(drives)
        app.custom_folders = env.make_custom_folders([])
        app.user_settings = UserSettings.load(env.temp_dir / "settings.json")
        app.folders = []
        app._background_scanner = None
        return app

    def test_released_id_blocked(self, migration_env):
        """Adding a folder ID that matches a released drive is rejected."""
        drives = [DriveConfig(name="Official Pack", folder_id="released_id")]
        app = self._make_app(migration_env, drives)

        app.auth = type("Auth", (), {"is_signed_in": True, "get_token": lambda _: "tok"})()

        with patch("sync.show_add_custom_folder", return_value=("released_id", "My Folder")), \
             patch("sync.DriveClient"), \
             patch("sync.DriveClientConfig"), \
             patch("sync.wait_with_skip"):
            result = app.handle_add_custom_folder()

        assert result is False
        assert not app.custom_folders.has_folder("released_id")

    def test_non_released_id_allowed(self, migration_env):
        """Adding a folder ID that doesn't match any released drive is allowed."""
        drives = [DriveConfig(name="Official Pack", folder_id="released_id")]
        app = self._make_app(migration_env, drives)

        app.auth = type("Auth", (), {"is_signed_in": True, "get_token": lambda _: "tok"})()

        mock_client = MagicMock()
        mock_client.get_file_metadata.return_value = {"parents": ["unrelated_parent"]}

        with patch("sync.show_add_custom_folder", return_value=("new_custom_id", "My Folder")), \
             patch("sync.DriveClient", return_value=mock_client), \
             patch("sync.DriveClientConfig"):
            result = app.handle_add_custom_folder()

        assert result is True
        assert app.custom_folders.has_folder("new_custom_id")


# ============================================================================
# Block adding released drive subfolders as custom
# ============================================================================

class TestBlockReleasedSubfolderAsCustom:
    """Tests for blocking subfolders of released drives from being added as custom."""

    def _make_app(self, env: MigrationEnv, drives: list[DriveConfig]):
        from sync import SyncApp

        app = object.__new__(SyncApp)
        app.drives_config = env.make_drives_config(drives)
        app.custom_folders = env.make_custom_folders([])
        app.user_settings = UserSettings.load(env.temp_dir / "settings.json")
        app.folders = []
        app._background_scanner = None
        return app

    def test_subfolder_of_released_drive_blocked(self, migration_env):
        """Adding a subfolder of a released drive is rejected."""
        drives = [DriveConfig(name="Popular Charters", folder_id="drive_abc")]
        app = self._make_app(migration_env, drives)
        app.auth = type("Auth", (), {"is_signed_in": True, "get_token": lambda _: "tok"})()

        mock_client = MagicMock()
        mock_client.get_file_metadata.return_value = {"parents": ["drive_abc"]}

        with patch("sync.show_add_custom_folder", return_value=("subfolder_xyz", "Miscellany")), \
             patch("sync.DriveClient", return_value=mock_client), \
             patch("sync.DriveClientConfig"), \
             patch("sync.wait_with_skip"):
            result = app.handle_add_custom_folder()

        assert result is False
        assert not app.custom_folders.has_folder("subfolder_xyz")

    def test_unrelated_folder_allowed(self, migration_env):
        """Folder whose parent is not a released drive is allowed."""
        drives = [DriveConfig(name="Popular Charters", folder_id="drive_abc")]
        app = self._make_app(migration_env, drives)
        app.auth = type("Auth", (), {"is_signed_in": True, "get_token": lambda _: "tok"})()

        mock_client = MagicMock()
        mock_client.get_file_metadata.return_value = {"parents": ["some_other_parent"]}

        with patch("sync.show_add_custom_folder", return_value=("unrelated_id", "My Folder")), \
             patch("sync.DriveClient", return_value=mock_client), \
             patch("sync.DriveClientConfig"):
            result = app.handle_add_custom_folder()

        assert result is True
        assert app.custom_folders.has_folder("unrelated_id")

    def test_parent_check_handles_api_error(self, migration_env):
        """If get_file_metadata returns None, allow the add (graceful degradation)."""
        drives = [DriveConfig(name="Popular Charters", folder_id="drive_abc")]
        app = self._make_app(migration_env, drives)
        app.auth = type("Auth", (), {"is_signed_in": True, "get_token": lambda _: "tok"})()

        mock_client = MagicMock()
        mock_client.get_file_metadata.return_value = None

        with patch("sync.show_add_custom_folder", return_value=("mystery_id", "Unknown Folder")), \
             patch("sync.DriveClient", return_value=mock_client), \
             patch("sync.DriveClientConfig"):
            result = app.handle_add_custom_folder()

        assert result is True
        assert app.custom_folders.has_folder("mystery_id")


# ============================================================================
# Migrate subfolder customs after discovery
# ============================================================================

class TestMigrateSubfolderCustoms:
    """Tests for _migrate_subfolder_customs()."""

    def _make_app(self, env: MigrationEnv, drives: list[DriveConfig], custom_folders: list[tuple[str, str]]):
        from sync import SyncApp

        app = object.__new__(SyncApp)
        app.drives_config = env.make_drives_config(drives)
        app.custom_folders = env.make_custom_folders(custom_folders)
        app.folders = []
        return app

    def _make_scanner_with_setlists(self, setlists: dict[str, SetlistInfo]):
        scanner = MagicMock()
        scanner.all_setlists = setlists
        return scanner

    def test_subfolder_custom_removed_after_discovery(self, migration_env):
        """Custom folder whose ID matches a discovered setlist gets removed."""
        drives = [DriveConfig(name="Popular Charters", folder_id="drive_abc")]
        app = self._make_app(migration_env, drives, [("setlist_xyz", "Miscellany")])

        setlist = SetlistInfo(
            setlist_id="setlist_xyz", name="Miscellany",
            drive_id="drive_abc", drive_name="Popular Charters", drive={},
        )
        app._background_scanner = self._make_scanner_with_setlists({"setlist_xyz": setlist})

        app._migrate_subfolder_customs()

        assert not app.custom_folders.has_folder("setlist_xyz")

    def test_subfolder_download_folder_moved(self, migration_env):
        """Download folder moves from top-level into drive subfolder."""
        migration_env.make_download_folder("Miscellany", {"Chart1/song.ini": 100})

        drives = [DriveConfig(name="Popular Charters", folder_id="drive_abc")]
        app = self._make_app(migration_env, drives, [("setlist_xyz", "Miscellany")])

        setlist = SetlistInfo(
            setlist_id="setlist_xyz", name="Miscellany",
            drive_id="drive_abc", drive_name="Popular Charters", drive={},
        )
        app._background_scanner = self._make_scanner_with_setlists({"setlist_xyz": setlist})

        app._migrate_subfolder_customs()

        assert not (migration_env.download_path / "Miscellany").exists()
        assert (migration_env.download_path / "Popular Charters" / "Miscellany").exists()
        assert (migration_env.download_path / "Popular Charters" / "Miscellany" / "Chart1" / "song.ini").exists()

    def test_subfolder_markers_renamed(self, migration_env):
        """Markers prefixed with custom name get drive/setlist prefix."""
        migration_env.make_marker_file(
            "Miscellany", "Chart1/pack.7z", "abc12345",
            {"Chart1/Song/song.ini": 100},
        )

        old_prefix = normalize_path_key("Miscellany").replace("/", "_").replace("\\", "_") + "_"
        new_prefix = (
            normalize_path_key("Popular Charters").replace("/", "_").replace("\\", "_") + "_"
            + normalize_path_key("Miscellany").replace("/", "_").replace("\\", "_") + "_"
        )

        drives = [DriveConfig(name="Popular Charters", folder_id="drive_abc")]
        app = self._make_app(migration_env, drives, [("setlist_xyz", "Miscellany")])

        setlist = SetlistInfo(
            setlist_id="setlist_xyz", name="Miscellany",
            drive_id="drive_abc", drive_name="Popular Charters", drive={},
        )
        app._background_scanner = self._make_scanner_with_setlists({"setlist_xyz": setlist})

        app._migrate_subfolder_customs()

        remaining_old = [f for f in migration_env.markers_dir.glob("*.json") if f.stem.lower().startswith(old_prefix)]
        assert len(remaining_old) == 0

        new_markers = [f for f in migration_env.markers_dir.glob("*.json") if f.stem.lower().startswith(new_prefix)]
        assert len(new_markers) == 1

    def test_non_subfolder_customs_preserved(self, migration_env):
        """Custom folders that aren't subfolders of released drives are untouched."""
        drives = [DriveConfig(name="Popular Charters", folder_id="drive_abc")]
        app = self._make_app(migration_env, drives, [
            ("setlist_xyz", "Miscellany"),
            ("unrelated_id", "My Custom Pack"),
        ])

        setlist = SetlistInfo(
            setlist_id="setlist_xyz", name="Miscellany",
            drive_id="drive_abc", drive_name="Popular Charters", drive={},
        )
        # Only setlist_xyz is in discovered setlists, not unrelated_id
        app._background_scanner = self._make_scanner_with_setlists({"setlist_xyz": setlist})

        app._migrate_subfolder_customs()

        assert not app.custom_folders.has_folder("setlist_xyz")
        assert app.custom_folders.has_folder("unrelated_id")
        assert len(app.custom_folders.folders) == 1

    def test_migration_when_target_dir_exists(self, migration_env):
        """Drive folder already exists — subfolder should still be moved into it."""
        # Drive dir already has other setlists
        migration_env.make_download_folder("Popular Charters/OtherSetlist", {"file.txt": 50})
        migration_env.make_download_folder("Miscellany", {"Chart1/song.ini": 100})

        drives = [DriveConfig(name="Popular Charters", folder_id="drive_abc")]
        app = self._make_app(migration_env, drives, [("setlist_xyz", "Miscellany")])

        setlist = SetlistInfo(
            setlist_id="setlist_xyz", name="Miscellany",
            drive_id="drive_abc", drive_name="Popular Charters", drive={},
        )
        app._background_scanner = self._make_scanner_with_setlists({"setlist_xyz": setlist})

        app._migrate_subfolder_customs()

        # Old folder gone, new in place
        assert not (migration_env.download_path / "Miscellany").exists()
        assert (migration_env.download_path / "Popular Charters" / "Miscellany" / "Chart1" / "song.ini").exists()
        # Existing content preserved
        assert (migration_env.download_path / "Popular Charters" / "OtherSetlist" / "file.txt").exists()
