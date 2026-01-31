"""
Tests for caching and setlist filtering behavior.
"""

import tempfile
import time
from pathlib import Path

import pytest

from src.sync import count_purgeable_files, clear_cache
from src.sync.cache import scan_local_files
from src.sync.state import SyncState

class TestScanPerformance:
    """Tests that scanning operations are fast enough."""

    @pytest.fixture
    def large_folder(self):
        """Create a folder with many files to simulate real usage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            folder_path = base / "TestDrive"

            # Create 500 chart folders with 5 files each = 2500 files
            # This simulates a medium-sized sync folder
            for i in range(500):
                chart_folder = folder_path / f"Setlist{i // 50}" / f"Chart{i}"
                chart_folder.mkdir(parents=True, exist_ok=True)

                # Create typical chart files
                (chart_folder / "song.ini").write_text("[song]\nname=Test")
                (chart_folder / "notes.mid").write_bytes(b"x" * 100)
                (chart_folder / "song.ogg").write_bytes(b"x" * 1000)
                (chart_folder / "album.png").write_bytes(b"x" * 500)
                (chart_folder / "extra.txt").write_bytes(b"x" * 50)

            yield base, folder_path

    def testscan_local_files_is_cached(self, large_folder):
        """Second scan should be instant due to caching."""
        _, folder_path = large_folder
        clear_cache()

        # First scan - populates cache
        result1 = scan_local_files(folder_path)

        # Second scan - should hit cache
        start = time.time()
        result2 = scan_local_files(folder_path)
        second_time = time.time() - start

        assert result1 == result2
        assert second_time < 0.01, f"Cached scan took {second_time:.3f}s, should be <0.01s"

    def testscan_local_files_reasonable_time(self, large_folder):
        """Initial scan of 2500 files should complete in <2 seconds."""
        _, folder_path = large_folder
        clear_cache()

        start = time.time()
        result = scan_local_files(folder_path)
        elapsed = time.time() - start

        assert len(result) == 2500, f"Expected 2500 files, got {len(result)}"
        assert elapsed < 2.0, f"Scan took {elapsed:.1f}s, should be <2s"


class TestCacheInvalidation:
    """Tests that cache is properly invalidated."""

    @pytest.fixture
    def temp_folder(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            folder_path = base / "TestDrive"
            folder_path.mkdir()
            (folder_path / "file1.txt").write_text("content")
            yield folder_path

    def test_clear_cache_forces_rescan(self, temp_folder):
        """After clear_cache(), next scan should see new files."""
        clear_cache()

        # Initial scan
        result1 = scan_local_files(temp_folder)
        assert len(result1) == 1

        # Add a file
        (temp_folder / "file2.txt").write_text("more content")

        # Without clearing, cache returns stale data
        result2 = scan_local_files(temp_folder)
        assert len(result2) == 1, "Cache should return stale data"

        # After clearing, should see new file
        clear_cache()
        result3 = scan_local_files(temp_folder)
        assert len(result3) == 2, "After clear, should see new file"


class TestCountPurgeableUsesCache:
    """Tests that count_purgeable uses cached data."""

    @pytest.fixture
    def folder_with_manifest(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            folder_path = base / "TestDrive"
            folder_path.mkdir()

            # Create some files
            (folder_path / "expected.txt").write_text("expected")
            (folder_path / "extra.txt").write_text("extra")

            # Manifest only includes expected.txt
            folder = {
                "name": "TestDrive",
                "folder_id": "test123",
                "files": [{"path": "expected.txt", "size": 8, "md5": "abc"}]
            }

            yield base, folder

    def test_count_purgeable_reuses_cache(self, folder_with_manifest):
        """count_purgeable_files should reuse scan_local_files cache."""
        base, folder = folder_with_manifest
        folder_path = base / "TestDrive"
        clear_cache()

        # Pre-populate cache
        cached_files = scan_local_files(folder_path)
        assert len(cached_files) == 2, "Should have scanned 2 files"

        # Set up sync_state tracking expected.txt
        sync_state = SyncState(base)
        sync_state.load()
        sync_state.add_file("TestDrive/expected.txt", size=8)

        # count_purgeable should NOT rescan
        start = time.time()
        count, size, charts = count_purgeable_files([folder], base, None, sync_state)
        elapsed = time.time() - start

        # Verify correctness: should find the extra file with correct size
        assert count == 1, "Should find 1 extra file"
        assert size == 5, "Extra file 'extra' is 5 bytes"
        assert elapsed < 0.1, f"Should be instant from cache, took {elapsed:.3f}s"

    def test_count_purgeable_correct_without_cache(self, folder_with_manifest):
        """count_purgeable_files should produce correct results even without pre-populated cache."""
        base, folder = folder_with_manifest
        clear_cache()

        # Set up sync_state tracking expected.txt
        sync_state = SyncState(base)
        sync_state.load()
        sync_state.add_file("TestDrive/expected.txt", size=8)

        # Call without pre-populating cache
        count, size, charts = count_purgeable_files([folder], base, None, sync_state)

        # Should still find the extra file correctly
        assert count == 1, "Should find 1 extra file"
        assert size == 5, "Extra file 'extra' is 5 bytes"


class TestSetlistFiltering:
    """Tests that disabled folders/setlists are properly excluded."""

    def test_disabled_drive_returns_zero_charts(self, tmp_path):
        """Disabled drive should report 0 charts regardless of manifest size."""
        from src.sync.status import get_sync_status
        from src.config.settings import UserSettings

        manifest = {
            "folder_id": "test",
            "name": "TestDrive",
            "files": [{"path": f"Song{i}.zip", "size": 1000, "md5": f"md5_{i}"} for i in range(100)],
            "subfolders": [],
        }
        settings = UserSettings.load(tmp_path / "settings.json")
        settings.set_drive_enabled("test", False)

        clear_cache()
        status = get_sync_status([manifest], tmp_path, settings, None)
        assert status.total_charts == 0

    def test_disabled_setlists_excluded_from_count(self, tmp_path):
        """Only enabled setlists should be counted."""
        from src.sync.status import get_sync_status
        from src.config.settings import UserSettings

        manifest = {
            "folder_id": "test",
            "name": "TestDrive",
            "files": [
                {"path": "Setlist_A/song1.zip", "size": 1000, "md5": "a1"},
                {"path": "Setlist_A/song2.zip", "size": 1000, "md5": "a2"},
                {"path": "Setlist_B/song1.zip", "size": 1000, "md5": "b1"},
                {"path": "Setlist_B/song2.zip", "size": 1000, "md5": "b2"},
            ],
            "subfolders": [
                {"name": "Setlist_A", "charts": {"total": 2}},
                {"name": "Setlist_B", "charts": {"total": 2}},
            ],
        }
        settings = UserSettings.load(tmp_path / "settings.json")
        settings.set_drive_enabled("test", True)
        settings.set_subfolder_enabled("test", "Setlist_B", False)

        clear_cache()
        status = get_sync_status([manifest], tmp_path, settings, None)
        assert status.total_charts == 2  # Only Setlist_A


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
