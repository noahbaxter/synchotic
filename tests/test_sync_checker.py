"""
Tests for sync_checker.py - unified sync checking logic.

Verifies that the single source of truth for "is this synced?" works correctly
using marker files as the only verification method.
"""

import tempfile
from pathlib import Path

import pytest

from src.sync.sync_checker import (
    FileSpec,
    is_archive_file,
    is_archive_synced,
    is_file_synced,
)
from src.sync.markers import save_marker, get_markers_dir


class TestFileSpec:
    """Tests for FileSpec dataclass."""

    def test_default_is_archive_false(self):
        """FileSpec defaults to is_archive=False."""
        spec = FileSpec(rel_path="folder/song.ini", size=100, md5="abc")
        assert spec.is_archive is False

    def test_all_fields_set(self):
        """All fields can be set explicitly."""
        spec = FileSpec(rel_path="folder/pack.7z", size=5000, md5="xyz", is_archive=True)
        assert spec.rel_path == "folder/pack.7z"
        assert spec.size == 5000
        assert spec.md5 == "xyz"
        assert spec.is_archive is True


class TestIsArchiveFile:
    """Tests for is_archive_file() helper."""

    def test_zip_detected(self):
        assert is_archive_file("chart.zip") is True
        assert is_archive_file("chart.ZIP") is True

    def test_7z_detected(self):
        assert is_archive_file("chart.7z") is True
        assert is_archive_file("chart.7Z") is True

    def test_rar_detected(self):
        assert is_archive_file("chart.rar") is True
        assert is_archive_file("chart.RAR") is True

    def test_non_archive_not_detected(self):
        assert is_archive_file("song.ini") is False
        assert is_archive_file("notes.mid") is False
        assert is_archive_file("song.ogg") is False


class TestIsArchiveSynced:
    """Tests for is_archive_synced() - core archive sync checking."""

    @pytest.fixture
    def temp_dir(self, monkeypatch):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Monkeypatch markers directory to use temp dir
            markers_dir = Path(tmpdir) / ".dm-sync" / "markers"
            markers_dir.mkdir(parents=True)
            monkeypatch.setattr("src.sync.markers.get_markers_dir", lambda: markers_dir)
            yield Path(tmpdir)

    def test_synced_when_marker_valid_and_files_exist(self, temp_dir, monkeypatch):
        """Archive synced when marker has matching MD5 and files exist."""
        # Create extracted files on disk
        chart_folder = temp_dir / "TestDrive" / "Setlist"
        chart_folder.mkdir(parents=True)
        (chart_folder / "song.ini").write_text("[song]")
        (chart_folder / "notes.mid").write_bytes(b"midi")

        # Create marker file
        save_marker(
            archive_path="TestDrive/Setlist/pack.7z",
            md5="abc123",
            extracted_files={
                "Setlist/song.ini": 6,
                "Setlist/notes.mid": 4,
            },
        )

        is_synced, size = is_archive_synced(
            folder_name="TestDrive",
            checksum_path="Setlist",
            archive_name="pack.7z",
            manifest_md5="abc123",
            local_base=temp_dir / "TestDrive",
        )

        assert is_synced is True
        assert size == 10  # 6 + 4

    def test_not_synced_when_marker_valid_but_files_missing(self, temp_dir, monkeypatch):
        """Archive NOT synced when marker exists but files missing."""
        # NO files on disk - just create the folder
        chart_folder = temp_dir / "TestDrive" / "Setlist"
        chart_folder.mkdir(parents=True)

        # Create marker file (but files don't exist)
        save_marker(
            archive_path="TestDrive/Setlist/pack.7z",
            md5="abc123",
            extracted_files={
                "Setlist/song.ini": 6,
                "Setlist/notes.mid": 4,
            },
        )

        is_synced, size = is_archive_synced(
            folder_name="TestDrive",
            checksum_path="Setlist",
            archive_name="pack.7z",
            manifest_md5="abc123",
            local_base=temp_dir / "TestDrive",
        )

        assert is_synced is False

    def test_not_synced_when_no_marker_and_no_state(self, temp_dir, monkeypatch):
        """Archive NOT synced when no marker and no state entry."""
        # Create files on disk (but no marker)
        chart_folder = temp_dir / "TestDrive" / "Setlist"
        chart_folder.mkdir(parents=True)
        (chart_folder / "song.ini").write_text("[song]")
        (chart_folder / "notes.mid").write_bytes(b"midi")

        is_synced, _ = is_archive_synced(
            folder_name="TestDrive",
            checksum_path="Setlist",
            archive_name="pack.7z",
            manifest_md5="abc123",
            local_base=temp_dir / "TestDrive",
        )

        # No marker and no state = NOT synced (no disk heuristics)
        assert is_synced is False

    def test_marker_synced_regardless_of_state(self, temp_dir, monkeypatch):
        """Archive synced when marker has matching MD5."""
        # Create extracted files on disk
        chart_folder = temp_dir / "TestDrive" / "Setlist"
        chart_folder.mkdir(parents=True)
        (chart_folder / "song.ini").write_text("[song]")

        # Create marker with correct info
        save_marker(
            archive_path="TestDrive/Setlist/pack.7z",
            md5="new_md5",
            extracted_files={"Setlist/song.ini": 6},
        )

        is_synced, _ = is_archive_synced(
            folder_name="TestDrive",
            checksum_path="Setlist",
            archive_name="pack.7z",
            manifest_md5="new_md5",
            local_base=temp_dir / "TestDrive",
        )

        assert is_synced is True


class TestIsFileSynced:
    """Tests for is_file_synced() - regular file sync checking."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_synced_when_file_exists_with_correct_size(self, temp_dir):
        """File synced when it exists with manifest size."""
        local_file = temp_dir / "folder" / "notes.mid"
        local_file.parent.mkdir()
        local_file.write_bytes(b"midi data")  # 9 bytes

        result = is_file_synced(
            rel_path="folder/notes.mid",
            manifest_size=9,
            local_path=local_file,
        )

        assert result is True

    def test_not_synced_when_wrong_size(self, temp_dir):
        """File NOT synced when disk size doesn't match expected."""
        local_file = temp_dir / "folder" / "notes.mid"
        local_file.parent.mkdir()
        local_file.write_bytes(b"old")  # 3 bytes

        result = is_file_synced(
            rel_path="folder/notes.mid",
            manifest_size=100,
            local_path=local_file,
        )

        assert result is False

    def test_not_synced_when_file_missing(self, temp_dir):
        """File NOT synced when file doesn't exist."""
        local_file = temp_dir / "folder" / "notes.mid"

        result = is_file_synced(
            rel_path="folder/notes.mid",
            manifest_size=6,
            local_path=local_file,
        )

        assert result is False

    def test_ini_tolerates_size_growth(self, temp_dir):
        """song.ini synced when larger than manifest (Clone Hero appends leaderboard data)."""
        local_file = temp_dir / "folder" / "song.ini"
        local_file.parent.mkdir()
        local_file.write_text("[song]\nscores=999")  # larger than original

        result = is_file_synced(
            rel_path="folder/song.ini",
            manifest_size=6,  # original was smaller
            local_path=local_file,
        )

        assert result is True

    def test_ini_not_synced_when_smaller(self, temp_dir):
        """song.ini NOT synced if smaller than manifest (corrupted/truncated)."""
        local_file = temp_dir / "folder" / "song.ini"
        local_file.parent.mkdir()
        local_file.write_text("x")  # 1 byte, smaller than expected

        result = is_file_synced(
            rel_path="folder/song.ini",
            manifest_size=100,
            local_path=local_file,
        )

        assert result is False

    def test_non_ini_not_tolerant_of_size_growth(self, temp_dir):
        """Non-.ini files must match size exactly."""
        local_file = temp_dir / "folder" / "notes.mid"
        local_file.parent.mkdir()
        local_file.write_bytes(b"midi data plus extra")  # larger than expected

        result = is_file_synced(
            rel_path="folder/notes.mid",
            manifest_size=9,
            local_path=local_file,
        )

        assert result is False


class TestMultipleArchivesSameSetlist:
    """
    Test that multiple archives in the same setlist are tracked independently.
    """

    @pytest.fixture
    def temp_dir(self, monkeypatch):
        with tempfile.TemporaryDirectory() as tmpdir:
            markers_dir = Path(tmpdir) / ".dm-sync" / "markers"
            markers_dir.mkdir(parents=True)
            monkeypatch.setattr("src.sync.markers.get_markers_dir", lambda: markers_dir)
            yield Path(tmpdir)

    def test_each_archive_has_own_marker(self, temp_dir):
        """Each archive is tracked independently with its own marker."""
        # Create chart files for archive A
        chart_a = temp_dir / "TestDrive" / "Setlist" / "ChartA"
        chart_a.mkdir(parents=True)
        (chart_a / "song.ini").write_text("[song]")

        # Create marker for archive A only
        save_marker(
            archive_path="TestDrive/Setlist/ChartA.7z",
            md5="aaa",
            extracted_files={"Setlist/ChartA/song.ini": 6},
        )

        # Archive A should be synced
        is_synced_a, _ = is_archive_synced(
            folder_name="TestDrive",
            checksum_path="Setlist",
            archive_name="ChartA.7z",
            manifest_md5="aaa",
            local_base=temp_dir / "TestDrive",
        )

        # Archive B should NOT be synced (no marker)
        is_synced_b, _ = is_archive_synced(
            folder_name="TestDrive",
            checksum_path="Setlist",
            archive_name="ChartB.7z",
            manifest_md5="bbb",
            local_base=temp_dir / "TestDrive",
        )

        assert is_synced_a is True
        assert is_synced_b is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
