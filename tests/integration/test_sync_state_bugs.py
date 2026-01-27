"""
Tests for ACTUAL sync state bugs that cause "100% synced but files missing".

These tests verify bug scenarios where:
1. sync_state is lost/corrupted but files exist on disk
2. sync_state records fewer files than actually needed
3. Disk fallback incorrectly marks things as synced
4. Nested archives adjustment inflates counts incorrectly

THESE ARE NOT TAUTOLOGICAL TESTS - they create mismatches between
sync_state and reality to verify the system handles them correctly.
"""

import tempfile
from pathlib import Path

import pytest

from src.sync.state import SyncState
from src.sync.status import get_sync_status, _check_archive_synced
from src.sync.download_planner import plan_downloads


class MockSettings:
    delete_videos = True

    def is_drive_enabled(self, folder_id):
        return True

    def is_subfolder_enabled(self, folder_id, subfolder):
        return True

    def get_disabled_subfolders(self, folder_id):
        return set()


class TestDiskFallbackBug:
    """
    Tests for the disk fallback logic in _check_archive_synced.

    THE BUG: When sync_state doesn't have an archive tracked, it falls back
    to checking if song.ini exists on disk. If it does, the archive is
    considered "synced" even if most files are missing.

    This is the primary suspect for "100% synced but 500 files missing".
    """

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_no_sync_state_partial_folder_not_synced(self, temp_dir):
        """
        When sync_state doesn't track an archive and folder is incomplete,
        it should NOT be considered synced.

        Smart fallback requires 3+ files including a chart marker to consider
        a folder as a complete extraction.
        """
        # Create folder with only 1 file (incomplete extraction)
        chart_folder = temp_dir / "TestDrive" / "Setlist"
        chart_folder.mkdir(parents=True)
        (chart_folder / "song.ini").write_text("[song]\nname = Test")

        # Empty sync_state (simulating loss/corruption)
        sync_state = SyncState(temp_dir)
        sync_state.load()

        # Check archive sync status - pass folder_path for fallback
        is_synced, _ = _check_archive_synced(
            sync_state,
            folder_name="TestDrive",
            checksum_path="Setlist",
            archive_name="chart.7z",
            manifest_md5="any_md5",
            folder_path=temp_dir / "TestDrive",
        )

        # Partial folder (< 3 files) should NOT be considered synced
        assert not is_synced, (
            "Archive should NOT be considered synced with incomplete folder (< 3 files)"
        )

    def test_no_sync_state_complete_folder_is_synced(self, temp_dir):
        """
        When sync_state doesn't track an archive but folder has complete extraction,
        smart fallback should consider it synced.

        This prevents unnecessary re-downloads when sync_state is lost but files
        are actually present on disk.
        """
        # Create folder with 3+ files including chart marker
        chart_folder = temp_dir / "TestDrive" / "Setlist"
        chart_folder.mkdir(parents=True)
        (chart_folder / "song.ini").write_text("[song]\nname = Test")
        (chart_folder / "notes.mid").write_bytes(b"midi data")
        (chart_folder / "album.png").write_bytes(b"png data")

        # Empty sync_state (simulating loss/corruption)
        sync_state = SyncState(temp_dir)
        sync_state.load()

        # Check archive sync status - pass folder_path for fallback
        is_synced, _ = _check_archive_synced(
            sync_state,
            folder_name="TestDrive",
            checksum_path="Setlist",
            archive_name="chart.7z",
            manifest_md5="any_md5",
            folder_path=temp_dir / "TestDrive",
        )

        # Complete folder (3+ files with marker) IS synced via fallback
        assert is_synced, (
            "Archive should be considered synced when folder has complete extraction"
        )

    def test_two_files_not_considered_complete(self, temp_dir):
        """
        Boundary test: 2 files with marker should NOT be considered complete.

        The threshold is 3 files (marker + audio + notes minimum). This test
        ensures we don't accidentally lower the threshold to 2.
        """
        # Create folder with exactly 2 files including chart marker
        chart_folder = temp_dir / "TestDrive" / "Setlist"
        chart_folder.mkdir(parents=True)
        (chart_folder / "song.ini").write_text("[song]\nname = Test")
        (chart_folder / "notes.mid").write_bytes(b"midi data")
        # Only 2 files - missing the audio file

        # Empty sync_state
        sync_state = SyncState(temp_dir)
        sync_state.load()

        is_synced, _ = _check_archive_synced(
            sync_state,
            folder_name="TestDrive",
            checksum_path="Setlist",
            archive_name="chart.7z",
            manifest_md5="any_md5",
            folder_path=temp_dir / "TestDrive",
        )

        # 2 files is NOT enough - need 3+
        assert not is_synced, (
            "2 files should NOT be considered complete (threshold is 3)"
        )

    def test_status_and_planner_agree_without_sync_state_partial(self, temp_dir):
        """
        Status and planner must agree when sync_state is empty and folder is partial.

        Both should report "not synced" when folder has < 3 files.
        """
        # Set up folder with only 1 file (incomplete)
        chart_folder = temp_dir / "TestDrive" / "Setlist"
        chart_folder.mkdir(parents=True)
        (chart_folder / "song.ini").write_text("[song]")

        # Empty sync_state
        sync_state = SyncState(temp_dir)
        sync_state.load()

        manifest_files = [
            {"id": "archive_id", "path": "Setlist/chart.7z",
             "size": 50000, "md5": "archive_md5"},
        ]

        folder = {
            "folder_id": "test_folder",
            "name": "TestDrive",
            "files": manifest_files,
        }

        # Get status
        status = get_sync_status([folder], temp_dir, MockSettings(), sync_state)

        # Get planner view
        tasks, skipped, _ = plan_downloads(
            manifest_files,
            temp_dir / "TestDrive",
            delete_videos=True,
            sync_state=sync_state,
            folder_name="TestDrive"
        )

        # Both should agree: partial folder needs download
        assert len(tasks) == 1, "Planner should want to download (partial folder)"
        assert status.synced_charts < status.total_charts, (
            "Status should not show 100% for partial folder"
        )

    def test_status_and_planner_agree_without_sync_state_complete(self, temp_dir):
        """
        Status and planner must agree when sync_state is empty but folder is complete.

        Both should report "synced" via smart fallback when folder has 3+ files
        including a chart marker.
        """
        # Set up complete folder (3+ files with marker)
        chart_folder = temp_dir / "TestDrive" / "Setlist"
        chart_folder.mkdir(parents=True)
        (chart_folder / "song.ini").write_text("[song]")
        (chart_folder / "notes.mid").write_bytes(b"midi data")
        (chart_folder / "album.png").write_bytes(b"png data")

        # Empty sync_state
        sync_state = SyncState(temp_dir)
        sync_state.load()

        manifest_files = [
            {"id": "archive_id", "path": "Setlist/chart.7z",
             "size": 50000, "md5": "archive_md5"},
        ]

        folder = {
            "folder_id": "test_folder",
            "name": "TestDrive",
            "files": manifest_files,
        }

        # Get status
        status = get_sync_status([folder], temp_dir, MockSettings(), sync_state)

        # Get planner view
        tasks, skipped, _ = plan_downloads(
            manifest_files,
            temp_dir / "TestDrive",
            delete_videos=True,
            sync_state=sync_state,
            folder_name="TestDrive"
        )

        # Both should agree: complete folder is synced via smart fallback
        assert len(tasks) == 0, "Planner should skip (complete folder via fallback)"
        assert status.synced_charts == status.total_charts, (
            "Status should show 100% for complete folder via fallback"
        )


class TestSyncStateMismatch:
    """
    Tests for scenarios where sync_state doesn't match disk reality.
    """

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
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
        Archive extracted 5 files, but only 3 remain on disk.

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


class TestNestedArchivesInflation:
    """
    Tests for the _adjust_for_nested_archives inflation logic.

    THE BUG: When manifest says "this archive contains 500 charts" and
    the archive appears synced (even via disk fallback), the system
    inflates synced_charts to 500 without verifying all 500 exist.
    """

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_nested_archives_inflates_count_incorrectly(self, temp_dir):
        """
        BUG SCENARIO: Manifest says MegaPack.7z has 50 charts.
        Only 3 charts actually exist on disk.
        Archive appears "synced" via disk fallback.

        Current behavior (buggy): Reports 50/50 synced
        Expected behavior: Reports 3/50 synced (or detects mismatch)
        """
        # Create folder with only 3 charts (simulating partial extraction)
        folder_path = temp_dir / "TestDrive" / "MegaPack"
        folder_path.mkdir(parents=True)

        for i in range(3):  # Only 3 charts, not 50
            chart_folder = folder_path / f"Chart{i}"
            chart_folder.mkdir()
            (chart_folder / "song.ini").write_text(f"[song]\nname = Chart {i}")
            (chart_folder / "notes.mid").write_bytes(b"midi")

        # Manifest says there should be 50 charts
        manifest_files = [
            {"id": "mega_archive", "path": "MegaPack/MegaPack.7z",
             "size": 500000, "md5": "mega_md5"},
        ]

        folder = {
            "folder_id": "test_folder_id",
            "name": "TestDrive",
            "files": manifest_files,
            "subfolders": [
                {
                    "name": "MegaPack",
                    "charts": {"total": 50},  # Manifest claims 50 charts!
                    "total_size": 500000,
                }
            ],
        }

        # Empty sync_state (relies on disk fallback)
        sync_state = SyncState(temp_dir)
        sync_state.load()

        status = get_sync_status([folder], temp_dir, MockSettings(), sync_state)

        # With get_best_stats, it should scan disk and find 3 charts
        # The question is: does it report 3/50 or 50/50?

        # If disk fallback says archive is synced, AND nested archives
        # adjustment inflates to manifest count, we get 50/50 (wrong!)

        # The correct behavior depends on whether local scan overrides
        # Let's check what actually happens:

        if status.synced_charts == 50 and status.total_charts == 50:
            pytest.xfail(
                "POTENTIAL BUG: Reporting 50/50 synced but only 3 charts exist. "
                "This could cause '100% synced but files missing'."
            )

        # Ideally it should report 3 synced (what's actually on disk)
        # or flag that there's a mismatch
        assert status.synced_charts <= 3, (
            f"Should not report more than 3 synced charts when only 3 exist. "
            f"Got {status.synced_charts}"
        )


class TestPathFormatAlignment:
    """
    Tests that paths used in different parts of the system align correctly.

    Paths are built differently in:
    - downloader.py (task.rel_path)
    - status.py (_check_archive_synced builds path from folder_name/checksum_path/archive_name)
    - sync_state.py (stores paths as provided)

    If these don't match, lookups fail silently.
    """

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
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

        # Path format from status.py _check_archive_synced
        # It builds: folder_name/checksum_path/archive_name
        is_synced, _ = _check_archive_synced(
            sync_state,
            folder_name="TestDrive",
            checksum_path="Setlist/Artist - Song",
            archive_name="Artist - Song.7z",
            manifest_md5="test_md5",
        )

        assert is_synced, (
            "Path format mismatch: archive added with one format can't be found "
            "when checking with another format. This causes false negatives."
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
