"""
Tests for markers.py - marker file management for archive sync tracking.

Verifies marker creation, loading, verification, and migration from sync_state.
"""

import tempfile
from pathlib import Path

import pytest

from src.core.formatting import normalize_path_key
from src.sync.markers import (
    get_marker_path,
    load_marker,
    save_marker,
    verify_marker,
    delete_marker,
    is_migration_done,
    mark_migration_done,
    migrate_sync_state_to_markers,
    rebuild_markers_from_disk,
    get_markers_dir,
    get_all_marker_files,
)
from src.sync.download_planner import plan_downloads
from src.sync.purge_planner import find_extra_files
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
        assert "testdrive_setlist_pack.7z" in str(path)
        assert "abc123de" in str(path)  # First 8 chars of MD5

    def test_marker_path_sanitizes_slashes(self, temp_dir):
        """Slashes in archive path are converted to underscores."""
        path = get_marker_path("Drive/Sub/Folder/archive.rar", "xyz789")
        # No slashes in filename part
        assert "/" not in path.name

    def test_marker_path_truncates_long_names(self, temp_dir):
        """Very long archive paths are truncated to fit filesystem limits."""
        # Create a path that would exceed 255 char filename limit
        long_path = "Misc/Joshwantsmaccas/" + "A" * 200 + "/" + "B" * 200 + ".rar"
        path = get_marker_path(long_path, "abc123def456")

        # Filename should be under 255 chars
        assert len(path.name) < 255

        # Should still end with .json and have MD5 prefix
        assert path.suffix == ".json"
        assert "abc123de" in path.name

    def test_long_paths_still_unique(self, temp_dir):
        """Different long paths produce different marker filenames."""
        base = "A" * 200
        path1 = f"Drive/{base}/archive1.rar"
        path2 = f"Drive/{base}/archive2.rar"

        marker1 = get_marker_path(path1, "same_md5")
        marker2 = get_marker_path(path2, "same_md5")

        # Should produce different filenames (via path hash)
        assert marker1.name != marker2.name

    def test_long_path_marker_saves_and_loads(self, temp_dir):
        """Long-path markers can be saved to disk and loaded back."""
        long_path = "Misc/Joshwantsmaccas/" + "A" * 200 + "/" + "B" * 200 + ".rar"
        marker_path = save_marker(long_path, "abc123def456", {"song.ini": 100})
        assert marker_path.exists()

        marker = load_marker(long_path, "abc123def456")
        assert marker is not None
        assert marker["files"] == {"song.ini": 100}

    def test_windows_path_length_respected(self, temp_dir, monkeypatch):
        """On Windows, full marker path (dir + filename) fits within MAX_PATH=260."""
        monkeypatch.setattr("src.sync.markers.os.name", "nt")
        monkeypatch.setattr("src.sync.markers._warn_long_paths_once", lambda: None)

        # Simulate a deep Windows markers dir (e.g., D:\Songs\.dm-sync\markers)
        # The temp_dir markers dir is already set via fixture
        long_archive = "Misc/Joshwantsmaccas/" + "X" * 300 + ".rar"
        path = get_marker_path(long_archive, "abc123def456")

        # Full path including .tmp suffix for atomic writes must fit in 260
        tmp_path = path.with_suffix(".json.tmp")
        assert len(str(tmp_path)) <= 260, f"Full .tmp path is {len(str(tmp_path))} chars, must be <= 260"


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
        (temp_dir / "notes.mid").write_bytes(b"different content")  # Different size

        marker = {
            "files": {
                "notes.mid": 6,  # Expected 6, but file has different size
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


class TestRebuildMarkersFromDisk:
    """Tests for rebuild_markers_from_disk — the pre-purge safety net."""

    @pytest.fixture
    def temp_dir(self, monkeypatch):
        with tempfile.TemporaryDirectory() as tmpdir:
            markers_dir = Path(tmpdir) / ".dm-sync" / "markers"
            markers_dir.mkdir(parents=True)
            monkeypatch.setattr("src.sync.markers.get_markers_dir", lambda: markers_dir)
            yield Path(tmpdir)

    def test_creates_marker_for_extracted_archive(self, temp_dir):
        """Rebuild creates a marker when archive extraction folder exists on disk."""
        drive_path = temp_dir / "TestDrive"
        chart_folder = drive_path / "Setlist" / "SomeChart"
        chart_folder.mkdir(parents=True)
        (chart_folder / "song.ini").write_text("[song]")
        (chart_folder / "notes.mid").write_bytes(b"midi")

        folders = [{
            "name": "TestDrive",
            "files": [
                {"path": "Setlist/pack.7z", "md5": "abc123", "size": 5000},
            ],
        }]

        created, skipped = rebuild_markers_from_disk(folders, temp_dir)
        assert created == 1
        assert skipped == 0

        marker = load_marker("TestDrive/Setlist/pack.7z", "abc123")
        assert marker is not None
        assert "Setlist/SomeChart/song.ini" in marker["files"]
        assert "Setlist/SomeChart/notes.mid" in marker["files"]

    def test_skips_archive_with_existing_marker(self, temp_dir):
        """Rebuild skips archives that already have markers (incremental)."""
        drive_path = temp_dir / "TestDrive"
        chart_folder = drive_path / "Setlist" / "SomeChart"
        chart_folder.mkdir(parents=True)
        (chart_folder / "song.ini").write_text("[song]")

        # Pre-create marker
        save_marker("TestDrive/Setlist/pack.7z", "abc123", {"Setlist/SomeChart/song.ini": 6})

        folders = [{
            "name": "TestDrive",
            "files": [
                {"path": "Setlist/pack.7z", "md5": "abc123", "size": 5000},
            ],
        }]

        created, skipped = rebuild_markers_from_disk(folders, temp_dir)
        assert created == 0
        assert skipped == 1

    def test_skips_when_extraction_folder_missing(self, temp_dir):
        """Rebuild skips archives whose extraction folder doesn't exist."""
        # Drive folder exists but extraction subfolder does not
        (temp_dir / "TestDrive").mkdir()

        folders = [{
            "name": "TestDrive",
            "files": [
                {"path": "Setlist/pack.7z", "md5": "abc123", "size": 5000},
            ],
        }]

        created, skipped = rebuild_markers_from_disk(folders, temp_dir)
        assert created == 0
        assert skipped == 1

    def test_handles_empty_files_list(self, temp_dir):
        """Rebuild handles folders with no files gracefully."""
        folders = [{"name": "TestDrive", "files": None}]

        created, skipped = rebuild_markers_from_disk(folders, temp_dir)
        assert created == 0
        assert skipped == 0

    def test_rebuilt_markers_prevent_purge(self, temp_dir):
        """
        End-to-end: extracted files on disk with no marker → rebuild → purge
        should NOT flag them for deletion.

        This is the core scenario that caused mass deletion of archive charts.
        """
        from src.sync.cache import clear_cache
        clear_cache()

        drive_path = temp_dir / "TestDrive"
        chart_folder = drive_path / "Setlist" / "SomeChart"
        chart_folder.mkdir(parents=True)
        (chart_folder / "song.ini").write_text("[song]")
        (chart_folder / "notes.mid").write_bytes(b"midi")

        folders = [{
            "name": "TestDrive",
            "folder_id": "123",
            "files": [
                {"path": "Setlist/pack.7z", "md5": "abc123", "size": 5000},
            ],
        }]

        # Before rebuild: files ARE flagged as extra (no marker, not in manifest as loose files)
        marker_files_before = {normalize_path_key(p) for p in get_all_marker_files()}
        manifest_paths = {normalize_path_key("TestDrive/Setlist/pack.7z")}
        extras_before = find_extra_files("TestDrive", drive_path, marker_files_before, manifest_paths)
        assert len(extras_before) == 2, "Without markers, extracted files should be flagged as extra"

        # Rebuild markers
        clear_cache()
        created, _ = rebuild_markers_from_disk(folders, temp_dir)
        assert created == 1

        # After rebuild: files are NOT flagged as extra
        marker_files_after = {normalize_path_key(p) for p in get_all_marker_files()}
        extras_after = find_extra_files("TestDrive", drive_path, marker_files_after, manifest_paths)
        assert len(extras_after) == 0, "After rebuild, extracted files should be protected by markers"

    def test_rebuilt_markers_prevent_redownload(self, temp_dir):
        """
        End-to-end: extracted archive on disk with no marker → rebuild → plan_downloads
        should skip it (not re-download).

        Without markers, is_archive_synced returns False and the archive gets queued
        for download even though its contents are already on disk.
        """
        drive_path = temp_dir / "TestDrive"
        chart_folder = drive_path / "Setlist" / "SomeChart"
        chart_folder.mkdir(parents=True)
        (chart_folder / "song.ini").write_text("[song]")
        (chart_folder / "notes.mid").write_bytes(b"midi")

        manifest_files = [
            {"id": "1", "path": "Setlist/pack.7z", "md5": "abc123", "size": 5000},
        ]
        folders = [{"name": "TestDrive", "files": manifest_files}]

        # Before rebuild: archive would be downloaded (no marker = not synced)
        tasks_before, skipped_before, _ = plan_downloads(
            manifest_files, drive_path, folder_name="TestDrive"
        )
        assert len(tasks_before) == 1, "Without marker, archive should be queued for download"

        # Rebuild markers
        created, _ = rebuild_markers_from_disk(folders, temp_dir)
        assert created == 1

        # After rebuild: archive is skipped (marker exists, files verified)
        tasks_after, skipped_after, _ = plan_downloads(
            manifest_files, drive_path, folder_name="TestDrive"
        )
        assert len(tasks_after) == 0, "After rebuild, archive should be skipped (already synced)"
        assert skipped_after == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
