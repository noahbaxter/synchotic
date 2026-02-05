"""
Tests for marker-based sync verification bugs.

Verifies scenarios where markers and disk state disagree:
- Marker exists but extracted files are missing/corrupted
- No marker exists even though files are on disk
- Marker + files match correctly (happy path)
"""

import tempfile
from pathlib import Path

import pytest

from src.sync.sync_checker import is_archive_synced
from src.sync.download_planner import plan_downloads
from src.sync.markers import save_marker


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

        is_synced, _ = is_archive_synced(
            folder_name="TestDrive",
            checksum_path="Setlist",
            archive_name="chart.7z",
            manifest_md5="any_md5",
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

        is_synced, size = is_archive_synced(
            folder_name="TestDrive",
            checksum_path="Setlist",
            archive_name="chart.7z",
            manifest_md5="test_md5",
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

        is_synced, _ = is_archive_synced(
            folder_name="TestDrive",
            checksum_path="Setlist",
            archive_name="chart.7z",
            manifest_md5="test_md5",
            local_base=temp_dir / "TestDrive",
        )

        assert not is_synced, "Missing files should cause NOT synced"

    def test_marker_all_files_missing_not_synced(self, temp_dir):
        """
        Marker exists but ALL files are missing → not synced.
        """
        chart_folder = temp_dir / "TestDrive" / "Setlist"
        chart_folder.mkdir(parents=True)
        # No files on disk

        save_marker(
            archive_path="TestDrive/Setlist/chart.7z",
            md5="test_md5",
            extracted_files={
                "Setlist/song.ini": 6,
                "Setlist/notes.mid": 4,
            },
        )

        is_synced, _ = is_archive_synced(
            folder_name="TestDrive",
            checksum_path="Setlist",
            archive_name="chart.7z",
            manifest_md5="test_md5",
            local_base=temp_dir / "TestDrive",
        )

        assert not is_synced


class TestMarkerDiskMismatch:
    """
    Tests for scenarios where markers say synced but disk disagrees.

    The real mismatch: marker exists (archive was extracted) but files
    were deleted or corrupted on disk. plan_downloads should detect this
    and trigger re-download.
    """

    @pytest.fixture
    def temp_dir(self, monkeypatch):
        with tempfile.TemporaryDirectory() as tmpdir:
            markers_dir = Path(tmpdir) / ".dm-sync" / "markers"
            markers_dir.mkdir(parents=True)
            monkeypatch.setattr("src.sync.markers.get_markers_dir", lambda: markers_dir)
            yield Path(tmpdir)

    def test_marker_synced_but_all_extracted_files_deleted(self, temp_dir):
        """
        Marker says archive was extracted, but all files were deleted from disk.
        plan_downloads should detect mismatch and trigger re-download.
        """
        folder_path = temp_dir / "TestDrive" / "Setlist"
        folder_path.mkdir(parents=True)

        # Save marker as if archive was previously extracted
        save_marker(
            archive_path="TestDrive/Setlist/chart.7z",
            md5="archive_md5",
            extracted_files={
                "Setlist/song.ini": 100,
                "Setlist/notes.mid": 200,
                "Setlist/album.png": 300,
            },
        )

        # All extracted files deleted — none exist on disk

        manifest_files = [
            {"id": "archive_id", "path": "Setlist/chart.7z",
             "size": 1000, "md5": "archive_md5"},
        ]

        tasks, skipped, _ = plan_downloads(
            manifest_files,
            temp_dir / "TestDrive",
            delete_videos=True,
            folder_name="TestDrive"
        )

        assert len(tasks) == 1, (
            "Marker exists but all files deleted — should re-download archive"
        )

    def test_marker_synced_but_some_extracted_files_deleted(self, temp_dir):
        """
        Marker says archive extracted 5 files, but only 2 remain on disk.
        plan_downloads should detect partial mismatch and trigger re-download.
        """
        folder_path = temp_dir / "TestDrive" / "Setlist"
        folder_path.mkdir(parents=True)

        # Create only some of the files
        (folder_path / "song.ini").write_text("x" * 100)
        (folder_path / "notes.mid").write_bytes(b"x" * 200)
        # Missing: album.png, guitar.ogg, drums.ogg

        save_marker(
            archive_path="TestDrive/Setlist/chart.7z",
            md5="archive_md5",
            extracted_files={
                "Setlist/song.ini": 100,
                "Setlist/notes.mid": 200,
                "Setlist/album.png": 300,
                "Setlist/guitar.ogg": 400,
                "Setlist/drums.ogg": 500,
            },
        )

        manifest_files = [
            {"id": "archive_id", "path": "Setlist/chart.7z",
             "size": 5000, "md5": "archive_md5"},
        ]

        tasks, skipped, _ = plan_downloads(
            manifest_files,
            temp_dir / "TestDrive",
            delete_videos=True,
            folder_name="TestDrive"
        )

        assert len(tasks) == 1, (
            "Marker exists but 3/5 files deleted — should re-download archive"
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
        Verify the path format used when saving a marker matches
        the format used when checking if it's synced.
        """
        # Create the directory and files on disk
        chart_folder = temp_dir / "TestDrive" / "Setlist" / "Artist - Song"
        chart_folder.mkdir(parents=True)
        song_file = chart_folder / "song.ini"
        song_file.write_text("[song]")
        actual_size = song_file.stat().st_size

        # Save marker with path format from downloader
        downloader_path = "TestDrive/Setlist/Artist - Song/Artist - Song.7z"
        save_marker(
            archive_path=downloader_path,
            md5="test_md5",
            extracted_files={
                "Setlist/Artist - Song/song.ini": actual_size,
            },
        )

        # Path format from sync_checker.is_archive_synced
        is_synced, _ = is_archive_synced(
            folder_name="TestDrive",
            checksum_path="Setlist/Artist - Song",
            archive_name="Artist - Song.7z",
            manifest_md5="test_md5",
            local_base=temp_dir / "TestDrive",
        )

        assert is_synced, (
            "Path format mismatch: marker saved with one format can't be found "
            "when checking with another format. This causes false negatives."
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
