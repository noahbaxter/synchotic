"""
Tests for markers.py - marker file management for archive sync tracking.

Verifies marker creation, loading, verification, and migration from sync_state.
"""

import tempfile
from pathlib import Path

import pytest

from src.sync.markers import (
    get_marker_path,
    load_marker,
    save_marker,
    verify_marker,
    delete_marker,
    find_markers_for_archive,
    is_migration_done,
    mark_migration_done,
    migrate_sync_state_to_markers,
    get_markers_dir,
)
from src.sync.state import SyncState


class TestMarkerPaths:
    """Tests for marker path generation."""

    @pytest.fixture
    def temp_dir(self, monkeypatch):
        with tempfile.TemporaryDirectory() as tmpdir:
            markers_dir = Path(tmpdir) / ".dm-sync" / "markers"
            markers_dir.mkdir(parents=True)
            monkeypatch.setattr("src.sync.markers.get_markers_dir", lambda: markers_dir)
            yield Path(tmpdir)

    def test_marker_path_includes_archive_path_and_md5(self, temp_dir):
        """Marker path includes sanitized archive path and MD5 prefix."""
        path = get_marker_path("TestDrive/Setlist/pack.7z", "abc123def456")
        assert "TestDrive_Setlist_pack.7z" in str(path)
        assert "abc123de" in str(path)  # First 8 chars of MD5

    def test_marker_path_sanitizes_slashes(self, temp_dir):
        """Slashes in archive path are converted to underscores."""
        path = get_marker_path("Drive/Sub/Folder/archive.rar", "xyz789")
        # No slashes in filename part
        assert "/" not in path.name


class TestMarkerSaveLoad:
    """Tests for saving and loading markers."""

    @pytest.fixture
    def temp_dir(self, monkeypatch):
        with tempfile.TemporaryDirectory() as tmpdir:
            markers_dir = Path(tmpdir) / ".dm-sync" / "markers"
            markers_dir.mkdir(parents=True)
            monkeypatch.setattr("src.sync.markers.get_markers_dir", lambda: markers_dir)
            yield Path(tmpdir)

    def test_save_creates_marker_file(self, temp_dir):
        """save_marker creates a JSON file."""
        marker_path = save_marker(
            archive_path="TestDrive/Setlist/pack.7z",
            md5="abc123",
            extracted_files={"song.ini": 100, "notes.mid": 200},
        )
        assert marker_path.exists()
        assert marker_path.suffix == ".json"

    def test_load_returns_saved_data(self, temp_dir):
        """load_marker returns data that was saved."""
        save_marker(
            archive_path="TestDrive/Setlist/pack.7z",
            md5="abc123",
            extracted_files={"song.ini": 100},
        )

        marker = load_marker("TestDrive/Setlist/pack.7z", "abc123")
        assert marker is not None
        assert marker["archive_path"] == "TestDrive/Setlist/pack.7z"
        assert marker["md5"] == "abc123"
        assert marker["files"] == {"song.ini": 100}
        assert "extracted_at" in marker

    def test_load_returns_none_for_missing(self, temp_dir):
        """load_marker returns None for non-existent marker."""
        marker = load_marker("DoesNotExist/archive.7z", "xyz")
        assert marker is None

    def test_load_returns_none_for_wrong_md5(self, temp_dir):
        """load_marker returns None when MD5 doesn't match."""
        save_marker(
            archive_path="TestDrive/pack.7z",
            md5="correct_md5",
            extracted_files={"file.txt": 10},
        )

        marker = load_marker("TestDrive/pack.7z", "wrong_md5")
        assert marker is None


class TestMarkerVerification:
    """Tests for verify_marker()."""

    @pytest.fixture
    def temp_dir(self, monkeypatch):
        with tempfile.TemporaryDirectory() as tmpdir:
            markers_dir = Path(tmpdir) / ".dm-sync" / "markers"
            markers_dir.mkdir(parents=True)
            monkeypatch.setattr("src.sync.markers.get_markers_dir", lambda: markers_dir)
            yield Path(tmpdir)

    def test_verify_passes_when_files_exist_with_correct_size(self, temp_dir):
        """Verification passes when all files exist with correct sizes."""
        # Create files on disk
        (temp_dir / "song.ini").write_text("[song]")  # 6 bytes
        (temp_dir / "notes.mid").write_bytes(b"midi")  # 4 bytes

        marker = {
            "files": {
                "song.ini": 6,
                "notes.mid": 4,
            }
        }

        assert verify_marker(marker, temp_dir) is True

    def test_verify_fails_when_file_missing(self, temp_dir):
        """Verification fails when a file is missing."""
        # Only create one file
        (temp_dir / "song.ini").write_text("[song]")

        marker = {
            "files": {
                "song.ini": 6,
                "notes.mid": 4,  # This file doesn't exist
            }
        }

        assert verify_marker(marker, temp_dir) is False

    def test_verify_fails_when_size_wrong(self, temp_dir):
        """Verification fails when file size doesn't match."""
        (temp_dir / "song.ini").write_text("different content")  # Different size

        marker = {
            "files": {
                "song.ini": 6,  # Expected 6, but file has different size
            }
        }

        assert verify_marker(marker, temp_dir) is False

    def test_verify_fails_when_no_files(self, temp_dir):
        """Verification fails for empty files dict."""
        marker = {"files": {}}
        assert verify_marker(marker, temp_dir) is False


class TestMarkerDeletion:
    """Tests for delete_marker()."""

    @pytest.fixture
    def temp_dir(self, monkeypatch):
        with tempfile.TemporaryDirectory() as tmpdir:
            markers_dir = Path(tmpdir) / ".dm-sync" / "markers"
            markers_dir.mkdir(parents=True)
            monkeypatch.setattr("src.sync.markers.get_markers_dir", lambda: markers_dir)
            yield Path(tmpdir)

    def test_delete_removes_marker(self, temp_dir):
        """delete_marker removes the marker file."""
        save_marker("TestDrive/pack.7z", "abc123", {"file.txt": 10})
        assert load_marker("TestDrive/pack.7z", "abc123") is not None

        result = delete_marker("TestDrive/pack.7z", "abc123")
        assert result is True
        assert load_marker("TestDrive/pack.7z", "abc123") is None

    def test_delete_returns_false_for_missing(self, temp_dir):
        """delete_marker returns False for non-existent marker."""
        result = delete_marker("DoesNotExist/pack.7z", "xyz")
        assert result is False


class TestFindMarkers:
    """Tests for find_markers_for_archive()."""

    @pytest.fixture
    def temp_dir(self, monkeypatch):
        with tempfile.TemporaryDirectory() as tmpdir:
            markers_dir = Path(tmpdir) / ".dm-sync" / "markers"
            markers_dir.mkdir(parents=True)
            monkeypatch.setattr("src.sync.markers.get_markers_dir", lambda: markers_dir)
            yield Path(tmpdir)

    def test_finds_markers_for_archive(self, temp_dir):
        """find_markers_for_archive finds all markers for an archive path."""
        # Create markers with different MD5s (simulates archive updates)
        save_marker("TestDrive/pack.7z", "version1", {"file.txt": 10})
        save_marker("TestDrive/pack.7z", "version2", {"file.txt": 20})

        markers = find_markers_for_archive("TestDrive/pack.7z")
        assert len(markers) == 2

    def test_does_not_find_other_archives(self, temp_dir):
        """find_markers_for_archive doesn't return markers for other archives."""
        save_marker("TestDrive/pack.7z", "abc", {"file.txt": 10})
        save_marker("TestDrive/other.7z", "xyz", {"file.txt": 10})

        markers = find_markers_for_archive("TestDrive/pack.7z")
        assert len(markers) == 1


class TestMigration:
    """Tests for sync_state → marker migration."""

    @pytest.fixture
    def temp_dir(self, monkeypatch):
        with tempfile.TemporaryDirectory() as tmpdir:
            markers_dir = Path(tmpdir) / ".dm-sync" / "markers"
            markers_dir.mkdir(parents=True)
            monkeypatch.setattr("src.sync.markers.get_markers_dir", lambda: markers_dir)
            yield Path(tmpdir)

    def test_migration_creates_markers_when_files_exist(self, temp_dir):
        """Migration creates markers for archives with verified files."""
        # Create files on disk
        # sync_state stores files under archive's parent path (TestDrive/Setlist)
        # So file "song.ini" becomes "TestDrive/Setlist/song.ini"
        chart_folder = temp_dir / "TestDrive" / "Setlist"
        chart_folder.mkdir(parents=True)
        (chart_folder / "song.ini").write_text("[song]")

        # Set up sync_state with archive
        # Files are relative to where they're extracted (archive's parent)
        sync_state = SyncState(temp_dir)
        sync_state.load()
        sync_state.add_archive(
            path="TestDrive/Setlist/pack.7z",
            md5="abc123",
            archive_size=1000,
            files={"song.ini": 6}  # Just the filename, gets parent path prepended
        )

        # Manifest has same MD5
        manifest_md5s = {"TestDrive/Setlist/pack.7z": "abc123"}

        migrated, skipped = migrate_sync_state_to_markers(sync_state, temp_dir, manifest_md5s)

        assert migrated == 1
        assert skipped == 0

        # Verify marker was created
        marker = load_marker("TestDrive/Setlist/pack.7z", "abc123")
        assert marker is not None

    def test_migration_skips_when_files_missing(self, temp_dir):
        """Migration skips archives where files don't exist on disk."""
        # NO files on disk
        (temp_dir / "TestDrive" / "Setlist").mkdir(parents=True)

        sync_state = SyncState(temp_dir)
        sync_state.load()
        sync_state.add_archive(
            path="TestDrive/Setlist/pack.7z",
            md5="abc123",
            archive_size=1000,
            files={"song.ini": 6}  # File doesn't exist on disk
        )

        manifest_md5s = {"TestDrive/Setlist/pack.7z": "abc123"}

        migrated, skipped = migrate_sync_state_to_markers(sync_state, temp_dir, manifest_md5s)

        assert migrated == 0
        assert skipped == 1

        # No marker created
        marker = load_marker("TestDrive/Setlist/pack.7z", "abc123")
        assert marker is None

    def test_migration_skips_when_md5_outdated(self, temp_dir):
        """Migration skips archives where manifest has newer MD5."""
        # Create files on disk
        chart_folder = temp_dir / "TestDrive" / "Setlist"
        chart_folder.mkdir(parents=True)
        (chart_folder / "song.ini").write_text("[song]")

        sync_state = SyncState(temp_dir)
        sync_state.load()
        sync_state.add_archive(
            path="TestDrive/Setlist/pack.7z",
            md5="old_md5",  # Old version
            archive_size=1000,
            files={"song.ini": 6}
        )

        # Manifest has NEW md5
        manifest_md5s = {"TestDrive/Setlist/pack.7z": "new_md5"}

        migrated, skipped = migrate_sync_state_to_markers(sync_state, temp_dir, manifest_md5s)

        assert migrated == 0
        assert skipped == 1

    def test_migration_only_runs_once(self, temp_dir):
        """Migration marks itself complete and doesn't run again."""
        sync_state = SyncState(temp_dir)
        sync_state.load()

        # First migration
        migrate_sync_state_to_markers(sync_state, temp_dir, {})
        assert is_migration_done() is True

        # Add an archive to sync_state after migration
        sync_state.add_archive(
            path="TestDrive/new.7z",
            md5="xyz",
            archive_size=100,
            files={"file.txt": 10}
        )

        # Second migration should do nothing
        migrated, skipped = migrate_sync_state_to_markers(sync_state, temp_dir, {"TestDrive/new.7z": "xyz"})
        assert migrated == 0
        assert skipped == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
