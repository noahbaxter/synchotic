"""
Integration tests for archive extraction and sync_state tracking.

THE CRITICAL FLOW:
    1. Download archive to _download_chart.7z
    2. process_archive() extracts it
    3. sync_state.add_archive() records the extracted files
    4. plan_downloads() should now skip this archive
    5. get_sync_status() should count it as synced

This tests that extraction ACTUALLY works and sync_state is ACTUALLY updated.
Uses real (synthetic) archive files, not mocks.
"""

import shutil
import tempfile
from pathlib import Path

import pytest

from src.sync.state import SyncState
from src.sync.status import get_sync_status
from src.sync.download_planner import plan_downloads, DownloadTask
from src.sync.downloader import FileDownloader
from src.sync.extractor import extract_archive, scan_extracted_files


FIXTURES_DIR = Path(__file__).parent / "fixtures" / "test_archives"


class MockSettings:
    delete_videos = True

    def is_drive_enabled(self, folder_id):
        return True

    def is_subfolder_enabled(self, folder_id, subfolder):
        return True

    def get_disabled_subfolders(self, folder_id):
        return set()


def get_file_md5(file_path: Path) -> str:
    """Get MD5 hash of a file (for test verification)."""
    import hashlib
    with open(file_path, "rb") as f:
        return hashlib.md5(f.read()).hexdigest()


class TestArchiveExtractionTracking:
    """
    Tests that extraction + sync_state tracking work together correctly.

    This is the critical path where "100% but missing" bugs occur.
    """

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def downloader(self):
        return FileDownloader(delete_videos=True)

    def test_flat_archive_extraction_and_tracking(self, temp_dir, downloader):
        """
        Flat archive extracts correctly and gets tracked in sync_state.

        Archive contents:
            song.ini
            notes.chart
            album.png
        """
        archive_src = FIXTURES_DIR / "test_flat.zip"
        if not archive_src.exists():
            pytest.skip("Test fixtures not generated. Run scripts/generate_test_fixtures.py")

        # Set up paths
        chart_folder = temp_dir / "TestDrive" / "Setlist"
        chart_folder.mkdir(parents=True)

        # Copy archive to simulate download (with _download_ prefix)
        archive_path = chart_folder / "_download_test_flat.zip"
        shutil.copy(archive_src, archive_path)
        archive_md5 = get_file_md5(archive_src)
        archive_size = archive_src.stat().st_size

        # Create sync_state
        sync_state = SyncState(temp_dir)
        sync_state.load()

        # Create download task
        task = DownloadTask(
            file_id="test_file_id",
            local_path=archive_path,
            size=archive_size,
            md5=archive_md5,
            is_archive=True,
            rel_path="TestDrive/Setlist/test_flat.zip"
        )

        # Process the archive (this is what downloader does after download)
        success, error, extracted_files = downloader.process_archive(
            task, sync_state, archive_rel_path=task.rel_path
        )

        # Verify extraction succeeded
        assert success, f"Extraction failed: {error}"
        assert len(extracted_files) > 0, "No files extracted"

        # Verify files exist on disk
        assert (chart_folder / "song.ini").exists(), "song.ini not extracted"
        assert (chart_folder / "notes.chart").exists(), "notes.chart not extracted"
        assert (chart_folder / "album.png").exists(), "album.png not extracted"

        # Verify sync_state was updated
        assert sync_state.is_archive_synced(task.rel_path, archive_md5), (
            "Archive not marked as synced in sync_state"
        )

        # Verify tracked files
        all_tracked = sync_state.get_all_files()
        assert "TestDrive/Setlist/song.ini" in all_tracked
        assert "TestDrive/Setlist/notes.chart" in all_tracked
        assert "TestDrive/Setlist/album.png" in all_tracked

        # THE CRITICAL CHECK: plan_downloads should now skip this archive
        manifest_files = [
            {"id": "test_file_id", "path": "Setlist/test_flat.zip", "size": archive_size, "md5": archive_md5}
        ]
        tasks, skipped, _ = plan_downloads(
            manifest_files,
            temp_dir / "TestDrive",
            delete_videos=True,
            sync_state=sync_state,
            folder_name="TestDrive"
        )

        assert len(tasks) == 0, f"plan_downloads should skip synced archive, got {len(tasks)} tasks"
        assert skipped == 1, "Archive should be counted as skipped"

    def test_nested_archive_extraction_and_tracking(self, temp_dir, downloader):
        """
        Nested archive extracts with subdirectory structure.

        Archive contents:
            Chart Data/
                song.ini
                notes.mid
                song.ogg
                album.png
        """
        archive_src = FIXTURES_DIR / "test_nested.zip"
        if not archive_src.exists():
            pytest.skip("Test fixtures not generated. Run scripts/generate_test_fixtures.py")

        chart_folder = temp_dir / "TestDrive" / "Setlist"
        chart_folder.mkdir(parents=True)

        archive_path = chart_folder / "_download_test_nested.zip"
        shutil.copy(archive_src, archive_path)
        archive_md5 = get_file_md5(archive_src)
        archive_size = archive_src.stat().st_size

        sync_state = SyncState(temp_dir)
        sync_state.load()

        task = DownloadTask(
            file_id="test_file_id",
            local_path=archive_path,
            size=archive_size,
            md5=archive_md5,
            is_archive=True,
            rel_path="TestDrive/Setlist/test_nested.zip"
        )

        success, error, extracted_files = downloader.process_archive(
            task, sync_state, archive_rel_path=task.rel_path
        )

        assert success, f"Extraction failed: {error}"

        # Nested archive should create subdirectory
        # The files should be under "Chart Data" subfolder
        assert (chart_folder / "Chart Data" / "song.ini").exists() or (chart_folder / "song.ini").exists(), (
            "song.ini not found in expected location"
        )

        # Verify sync_state tracking
        assert sync_state.is_archive_synced(task.rel_path, archive_md5)

        # Plan should skip it
        manifest_files = [
            {"id": "test_file_id", "path": "Setlist/test_nested.zip", "size": archive_size, "md5": archive_md5}
        ]
        tasks, skipped, _ = plan_downloads(
            manifest_files,
            temp_dir / "TestDrive",
            delete_videos=True,
            sync_state=sync_state,
            folder_name="TestDrive"
        )

        assert len(tasks) == 0, "Nested archive should be skipped after extraction"

    def test_archive_preserves_internal_folder_structure(self, temp_dir, downloader):
        """
        Archive with internal folder preserves structure during extraction.

        Archive: test_flatten_match.zip
        Contents:
            test_flatten_match/
                song.ini
                notes.chart
                song.ogg

        Expected extraction (no flattening):
            test_flatten_match/song.ini
            test_flatten_match/notes.chart
            test_flatten_match/song.ogg
        """
        archive_src = FIXTURES_DIR / "test_flatten_match.zip"
        if not archive_src.exists():
            pytest.skip("Test fixtures not generated. Run scripts/generate_test_fixtures.py")

        chart_folder = temp_dir / "TestDrive" / "Setlist"
        chart_folder.mkdir(parents=True)

        archive_path = chart_folder / "_download_test_flatten_match.zip"
        shutil.copy(archive_src, archive_path)
        archive_md5 = get_file_md5(archive_src)
        archive_size = archive_src.stat().st_size

        sync_state = SyncState(temp_dir)
        sync_state.load()

        task = DownloadTask(
            file_id="test_file_id",
            local_path=archive_path,
            size=archive_size,
            md5=archive_md5,
            is_archive=True,
            rel_path="TestDrive/Setlist/test_flatten_match.zip"
        )

        success, error, extracted_files = downloader.process_archive(
            task, sync_state, archive_rel_path=task.rel_path
        )

        assert success, f"Extraction failed: {error}"

        # Internal folder structure preserved (no flattening)
        assert (chart_folder / "test_flatten_match" / "song.ini").exists(), (
            "song.ini should be in test_flatten_match/ subfolder"
        )

        # Tracked files should reflect nested paths
        all_tracked = sync_state.get_all_files()
        song_ini_path = "TestDrive/Setlist/test_flatten_match/song.ini"
        assert song_ini_path in all_tracked, (
            f"Nested path {song_ini_path} not in tracked files: {all_tracked}"
        )

    def test_video_deleted_during_extraction(self, temp_dir, downloader):
        """
        Video files should be deleted during extraction when delete_videos=True.

        Archive contents:
            song.ini
            notes.chart
            video.mp4
            album.png
        """
        archive_src = FIXTURES_DIR / "test_with_video.zip"
        if not archive_src.exists():
            pytest.skip("Test fixtures not generated. Run scripts/generate_test_fixtures.py")

        chart_folder = temp_dir / "TestDrive" / "Setlist"
        chart_folder.mkdir(parents=True)

        archive_path = chart_folder / "_download_test_with_video.zip"
        shutil.copy(archive_src, archive_path)
        archive_md5 = get_file_md5(archive_src)
        archive_size = archive_src.stat().st_size

        sync_state = SyncState(temp_dir)
        sync_state.load()

        task = DownloadTask(
            file_id="test_file_id",
            local_path=archive_path,
            size=archive_size,
            md5=archive_md5,
            is_archive=True,
            rel_path="TestDrive/Setlist/test_with_video.zip"
        )

        success, error, extracted_files = downloader.process_archive(
            task, sync_state, archive_rel_path=task.rel_path
        )

        assert success, f"Extraction failed: {error}"

        # Video should be deleted
        assert not (chart_folder / "video.mp4").exists(), "Video file should be deleted"

        # Other files should exist
        assert (chart_folder / "song.ini").exists()
        assert (chart_folder / "album.png").exists()

        # Video should NOT be tracked in sync_state
        all_tracked = sync_state.get_all_files()
        assert "TestDrive/Setlist/video.mp4" not in all_tracked


class TestExtractionEdgeCases:
    """Tests for extraction edge cases that have caused bugs."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def downloader(self):
        return FileDownloader(delete_videos=True)

    def test_unicode_filenames(self, temp_dir, downloader):
        """Unicode characters in filenames should work correctly."""
        archive_src = FIXTURES_DIR / "test_unicode.zip"
        if not archive_src.exists():
            pytest.skip("Test fixtures not generated. Run scripts/generate_test_fixtures.py")

        chart_folder = temp_dir / "TestDrive" / "Setlist"
        chart_folder.mkdir(parents=True)

        archive_path = chart_folder / "_download_test_unicode.zip"
        shutil.copy(archive_src, archive_path)
        archive_md5 = get_file_md5(archive_src)
        archive_size = archive_src.stat().st_size

        sync_state = SyncState(temp_dir)
        sync_state.load()

        task = DownloadTask(
            file_id="test_file_id",
            local_path=archive_path,
            size=archive_size,
            md5=archive_md5,
            is_archive=True,
            rel_path="TestDrive/Setlist/test_unicode.zip"
        )

        success, error, extracted_files = downloader.process_archive(
            task, sync_state, archive_rel_path=task.rel_path
        )

        assert success, f"Unicode extraction failed: {error}"

        # Verify tracking works
        assert sync_state.is_archive_synced(task.rel_path, archive_md5)

    def test_deeply_nested_paths(self, temp_dir, downloader):
        """Deeply nested paths should extract and track correctly."""
        archive_src = FIXTURES_DIR / "test_deeply_nested.zip"
        if not archive_src.exists():
            pytest.skip("Test fixtures not generated. Run scripts/generate_test_fixtures.py")

        chart_folder = temp_dir / "TestDrive" / "Setlist"
        chart_folder.mkdir(parents=True)

        archive_path = chart_folder / "_download_test_deeply_nested.zip"
        shutil.copy(archive_src, archive_path)
        archive_md5 = get_file_md5(archive_src)
        archive_size = archive_src.stat().st_size

        sync_state = SyncState(temp_dir)
        sync_state.load()

        task = DownloadTask(
            file_id="test_file_id",
            local_path=archive_path,
            size=archive_size,
            md5=archive_md5,
            is_archive=True,
            rel_path="TestDrive/Setlist/test_deeply_nested.zip"
        )

        success, error, extracted_files = downloader.process_archive(
            task, sync_state, archive_rel_path=task.rel_path
        )

        assert success, f"Deep nested extraction failed: {error}"
        assert len(extracted_files) > 0

        # Verify all tracked paths use forward slashes (cross-platform consistency)
        all_tracked = sync_state.get_all_files()
        for path in all_tracked:
            assert "\\" not in path, f"Backslash in tracked path: {path}"


class TestExtractionFailureHandling:
    """Tests for handling extraction failures gracefully."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def downloader(self):
        return FileDownloader(delete_videos=True)

    def test_corrupted_archive_fails_gracefully(self, temp_dir, downloader):
        """Corrupted archives should fail without crashing or corrupting sync_state."""
        chart_folder = temp_dir / "TestDrive" / "Setlist"
        chart_folder.mkdir(parents=True)

        # Create a "corrupted" archive (just random bytes)
        archive_path = chart_folder / "_download_corrupted.zip"
        archive_path.write_bytes(b"this is not a valid zip file")

        sync_state = SyncState(temp_dir)
        sync_state.load()

        task = DownloadTask(
            file_id="test_file_id",
            local_path=archive_path,
            size=100,
            md5="fake_md5",
            is_archive=True,
            rel_path="TestDrive/Setlist/corrupted.zip"
        )

        success, error, extracted_files = downloader.process_archive(
            task, sync_state, archive_rel_path=task.rel_path
        )

        # Should fail gracefully
        assert not success, "Corrupted archive should fail extraction"
        assert len(error) > 0, "Should have error message"

        # sync_state should NOT be corrupted
        assert not sync_state.is_archive_synced(task.rel_path, "fake_md5")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
