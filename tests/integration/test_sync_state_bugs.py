"""
Tests for sync state bugs that cause "100% synced but files missing".

These tests verify bug scenarios where:
1. sync_state is lost/corrupted but markers exist
2. sync_state records fewer files than actually needed
3. Markers or sync_state claim synced but files are missing

The new marker-based architecture removes disk heuristics entirely.
Sync status is determined by: marker exists → verify files exist.
No "looks like a chart" guessing.
"""

import tempfile
from pathlib import Path

import pytest

from src.sync.state import SyncState
from src.sync.status import get_sync_status
from src.sync.sync_checker import is_archive_synced
from src.sync.download_planner import plan_downloads
from src.sync.markers import save_marker, get_markers_dir


class MockSettings:
    delete_videos = True

    def is_drive_enabled(self, folder_id):
        return True

    def is_subfolder_enabled(self, folder_id, subfolder):
        return True

    def get_disabled_subfolders(self, folder_id):
        return set()


class TestMarkerBasedSync:
    """
    Tests for the marker-based sync verification.

    The new architecture: markers are the source of truth for archives.
    No disk heuristics - if no marker, archive needs download.
    """

    @pytest.fixture
    def temp_dir(self, monkeypatch):
        with tempfile.TemporaryDirectory() as tmpdir:
            markers_dir = Path(tmpdir) / ".dm-sync" / "markers"
            markers_dir.mkdir(parents=True)
            monkeypatch.setattr("src.sync.markers.get_markers_dir", lambda: markers_dir)
            yield Path(tmpdir)

    def test_no_marker_not_synced_even_with_files(self, temp_dir):
        """
        Without a marker, archive is NOT synced even if files exist on disk.

        This is intentional - we can't know what MD5 those files came from
        without a marker to tell us.
        """
        # Create files on disk (simulating manual copy or state loss)
        chart_folder = temp_dir / "TestDrive" / "Setlist"
        chart_folder.mkdir(parents=True)
        (chart_folder / "song.ini").write_text("[song]\nname = Test")
        (chart_folder / "notes.mid").write_bytes(b"midi data")
        (chart_folder / "album.png").write_bytes(b"png data")

        # No marker, no sync_state
        sync_state = SyncState(temp_dir)
        sync_state.load()

        is_synced, _ = is_archive_synced(
            folder_name="TestDrive",
            checksum_path="Setlist",
            archive_name="chart.7z",
            manifest_md5="any_md5",
            sync_state=sync_state,
            local_base=temp_dir / "TestDrive",
        )

        # No marker = not synced (no guessing)
        assert not is_synced, (
            "Without marker, archive should NOT be synced even if files exist"
        )

    def test_marker_with_files_is_synced(self, temp_dir):
        """
        With a marker and matching files, archive IS synced.
        """
        # Create files on disk
        chart_folder = temp_dir / "TestDrive" / "Setlist"
        chart_folder.mkdir(parents=True)
        (chart_folder / "song.ini").write_text("[song]")  # 6 bytes
        (chart_folder / "notes.mid").write_bytes(b"midi")  # 4 bytes

        # Create marker
        save_marker(
            archive_path="TestDrive/Setlist/chart.7z",
            md5="test_md5",
            extracted_files={
                "Setlist/song.ini": 6,
                "Setlist/notes.mid": 4,
            },
        )

        sync_state = SyncState(temp_dir)
        sync_state.load()

        is_synced, size = is_archive_synced(
            folder_name="TestDrive",
            checksum_path="Setlist",
            archive_name="chart.7z",
            manifest_md5="test_md5",
            sync_state=sync_state,
            local_base=temp_dir / "TestDrive",
        )

        assert is_synced is True
        assert size == 10

    def test_marker_with_missing_files_not_synced(self, temp_dir):
        """
        With a marker but missing files, archive is NOT synced.
        """
        chart_folder = temp_dir / "TestDrive" / "Setlist"
        chart_folder.mkdir(parents=True)
        # Only one file, marker says two
        (chart_folder / "song.ini").write_text("[song]")

        save_marker(
            archive_path="TestDrive/Setlist/chart.7z",
            md5="test_md5",
            extracted_files={
                "Setlist/song.ini": 6,
                "Setlist/notes.mid": 4,  # Missing!
            },
        )

        sync_state = SyncState(temp_dir)
        sync_state.load()

        is_synced, _ = is_archive_synced(
            folder_name="TestDrive",
            checksum_path="Setlist",
            archive_name="chart.7z",
            manifest_md5="test_md5",
            sync_state=sync_state,
            local_base=temp_dir / "TestDrive",
        )

        assert not is_synced, "Missing files should cause NOT synced"


class TestSyncStateFallback:
    """
    Tests for sync_state fallback during migration period.

    sync_state is still checked when no marker exists, for backward compat.
    """

    @pytest.fixture
    def temp_dir(self, monkeypatch):
        with tempfile.TemporaryDirectory() as tmpdir:
            markers_dir = Path(tmpdir) / ".dm-sync" / "markers"
            markers_dir.mkdir(parents=True)
            monkeypatch.setattr("src.sync.markers.get_markers_dir", lambda: markers_dir)
            yield Path(tmpdir)

    def test_sync_state_fallback_when_files_exist(self, temp_dir):
        """
        sync_state is used as fallback when no marker but files exist.
        """
        chart_folder = temp_dir / "TestDrive" / "Setlist"
        chart_folder.mkdir(parents=True)
        (chart_folder / "song.ini").write_text("[song]")
        (chart_folder / "notes.mid").write_bytes(b"midi")

        sync_state = SyncState(temp_dir)
        sync_state.load()
        sync_state.add_archive(
            path="TestDrive/Setlist/chart.7z",
            md5="test_md5",
            archive_size=1000,
            files={"song.ini": 6, "notes.mid": 4}
        )

        is_synced, _ = is_archive_synced(
            folder_name="TestDrive",
            checksum_path="Setlist",
            archive_name="chart.7z",
            manifest_md5="test_md5",
            sync_state=sync_state,
            local_base=temp_dir / "TestDrive",
        )

        assert is_synced is True

    def test_sync_state_fallback_fails_when_files_missing(self, temp_dir):
        """
        sync_state fallback fails when tracked files are missing.
        """
        chart_folder = temp_dir / "TestDrive" / "Setlist"
        chart_folder.mkdir(parents=True)
        # No files on disk

        sync_state = SyncState(temp_dir)
        sync_state.load()
        sync_state.add_archive(
            path="TestDrive/Setlist/chart.7z",
            md5="test_md5",
            archive_size=1000,
            files={"song.ini": 6, "notes.mid": 4}  # These don't exist
        )

        is_synced, _ = is_archive_synced(
            folder_name="TestDrive",
            checksum_path="Setlist",
            archive_name="chart.7z",
            manifest_md5="test_md5",
            sync_state=sync_state,
            local_base=temp_dir / "TestDrive",
        )

        assert not is_synced


class TestSyncStateMismatch:
    """
    Tests for scenarios where sync_state doesn't match disk reality.
    """

    @pytest.fixture
    def temp_dir(self, monkeypatch):
        with tempfile.TemporaryDirectory() as tmpdir:
            markers_dir = Path(tmpdir) / ".dm-sync" / "markers"
            markers_dir.mkdir(parents=True)
            monkeypatch.setattr("src.sync.markers.get_markers_dir", lambda: markers_dir)
            yield Path(tmpdir)

    def test_sync_state_has_files_but_disk_doesnt(self, temp_dir):
        """
        sync_state says files exist but they've been deleted from disk.

        This should be detected and cause re-download.
        """
        folder_path = temp_dir / "TestDrive" / "Setlist"
        folder_path.mkdir(parents=True)

        # NO files on disk

        # But sync_state thinks files exist
        sync_state = SyncState(temp_dir)
        sync_state.load()
        sync_state.add_file("TestDrive/Setlist/song.ini", size=100)
        sync_state.add_file("TestDrive/Setlist/notes.mid", size=200)

        manifest_files = [
            {"id": "1", "path": "Setlist/song.ini", "size": 100, "md5": "a"},
            {"id": "2", "path": "Setlist/notes.mid", "size": 200, "md5": "b"},
        ]

        # Planner should detect files are missing
        tasks, skipped, _ = plan_downloads(
            manifest_files,
            temp_dir / "TestDrive",
            delete_videos=True,
            sync_state=sync_state,
            folder_name="TestDrive"
        )

        # Should want to download both missing files
        assert len(tasks) == 2, (
            f"Planner should detect missing files. Got {len(tasks)} tasks, expected 2"
        )

    def test_archive_in_sync_state_but_extracted_files_missing(self, temp_dir):
        """
        Archive is marked as synced in sync_state, but extracted files
        have been deleted from disk.

        This should trigger re-download of the archive.
        """
        folder_path = temp_dir / "TestDrive" / "Setlist"
        folder_path.mkdir(parents=True)

        # Create sync_state with archive that claims to have extracted files
        sync_state = SyncState(temp_dir)
        sync_state.load()
        sync_state.add_archive(
            path="TestDrive/Setlist/chart.7z",
            md5="archive_md5",
            archive_size=1000,
            files={
                "song.ini": 100,
                "notes.mid": 200,
                "album.png": 500,
            }
        )

        # But NO files exist on disk - they were deleted

        manifest_files = [
            {"id": "archive_id", "path": "Setlist/chart.7z",
             "size": 1000, "md5": "archive_md5"},
        ]

        # Planner should detect extracted files are missing
        tasks, skipped, _ = plan_downloads(
            manifest_files,
            temp_dir / "TestDrive",
            delete_videos=True,
            sync_state=sync_state,
            folder_name="TestDrive"
        )

        # Should want to re-download the archive
        assert len(tasks) == 1, (
            f"Planner should re-download archive with missing extracted files. "
            f"Got {len(tasks)} tasks"
        )

    def test_archive_sync_state_partial_files_missing(self, temp_dir):
        """
        Archive extracted 5 files, but only 2 remain on disk.

        Should trigger re-download.
        """
        folder_path = temp_dir / "TestDrive" / "Setlist"
        folder_path.mkdir(parents=True)

        # Create only some of the files
        (folder_path / "song.ini").write_text("x" * 100)
        (folder_path / "notes.mid").write_bytes(b"x" * 200)
        # Missing: album.png, guitar.ogg, drums.ogg

        sync_state = SyncState(temp_dir)
        sync_state.load()
        sync_state.add_archive(
            path="TestDrive/Setlist/chart.7z",
            md5="archive_md5",
            archive_size=5000,
            files={
                "song.ini": 100,
                "notes.mid": 200,
                "album.png": 500,
                "guitar.ogg": 2000,
                "drums.ogg": 2000,
            }
        )

        manifest_files = [
            {"id": "archive_id", "path": "Setlist/chart.7z",
             "size": 5000, "md5": "archive_md5"},
        ]

        tasks, skipped, _ = plan_downloads(
            manifest_files,
            temp_dir / "TestDrive",
            delete_videos=True,
            sync_state=sync_state,
            folder_name="TestDrive"
        )

        # Should want to re-download because some files are missing
        assert len(tasks) == 1, (
            f"Planner should re-download archive with partial files missing. "
            f"Got {len(tasks)} tasks, expected 1"
        )


class TestPathFormatAlignment:
    """
    Tests that paths used in different parts of the system align correctly.

    Paths are built differently in:
    - downloader.py (task.rel_path)
    - status.py (is_archive_synced builds path from folder_name/checksum_path/archive_name)
    - sync_state.py (stores paths as provided)

    If these don't match, lookups fail silently.
    """

    @pytest.fixture
    def temp_dir(self, monkeypatch):
        with tempfile.TemporaryDirectory() as tmpdir:
            markers_dir = Path(tmpdir) / ".dm-sync" / "markers"
            markers_dir.mkdir(parents=True)
            monkeypatch.setattr("src.sync.markers.get_markers_dir", lambda: markers_dir)
            yield Path(tmpdir)

    def test_archive_path_format_matches_between_systems(self, temp_dir):
        """
        Verify the path format used when adding an archive matches
        the format used when checking if it's synced.
        """
        sync_state = SyncState(temp_dir)
        sync_state.load()

        # Create the directory and files on disk
        chart_folder = temp_dir / "TestDrive" / "Setlist" / "Artist - Song"
        chart_folder.mkdir(parents=True)
        song_file = chart_folder / "song.ini"
        song_file.write_text("[song]")
        actual_size = song_file.stat().st_size

        # Path format from downloader (task.rel_path)
        downloader_path = "TestDrive/Setlist/Artist - Song/Artist - Song.7z"

        sync_state.add_archive(
            path=downloader_path,
            md5="test_md5",
            archive_size=1000,
            files={"song.ini": actual_size}  # Use actual size
        )

        # Path format from sync_checker.is_archive_synced
        # It builds: folder_name/checksum_path/archive_name
        is_synced, _ = is_archive_synced(
            folder_name="TestDrive",
            checksum_path="Setlist/Artist - Song",
            archive_name="Artist - Song.7z",
            manifest_md5="test_md5",
            sync_state=sync_state,
            local_base=temp_dir / "TestDrive",
        )

        assert is_synced, (
            "Path format mismatch: archive added with one format can't be found "
            "when checking with another format. This causes false negatives."
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
