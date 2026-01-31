"""
Tests for SyncState integration with sync status and purge detection.

Verifies that:
- Archives tracked in sync_state are recognized as synced
- get_sync_status uses sync_state for archive detection
- Purge planner uses sync_state to avoid flagging synced files
"""

import tempfile
from pathlib import Path

import pytest

from src.sync.state import SyncState
from src.sync.status import get_sync_status
from src.sync.purge_planner import find_extra_files


class TestSyncStateArchiveTracking:
    """Tests for SyncState archive tracking."""

    @pytest.fixture
    def temp_sync_root(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_archive_synced_detection(self, temp_sync_root):
        """SyncState correctly identifies synced archives by MD5."""
        sync_state = SyncState(temp_sync_root)
        sync_state.load()

        # Add an archive
        sync_state.add_archive(
            path="TestDrive/Setlist/pack.7z",
            md5="abc123",
            archive_size=1000000,
            files={"song.ini": 100, "notes.mid": 500}
        )

        # Check synced with correct MD5
        assert sync_state.is_archive_synced("TestDrive/Setlist/pack.7z", "abc123")

        # Check not synced with wrong MD5
        assert not sync_state.is_archive_synced("TestDrive/Setlist/pack.7z", "wrong_md5")

        # Check not synced for non-existent archive
        assert not sync_state.is_archive_synced("NonExistent/archive.7z", "abc123")

    def test_archive_files_tracked(self, temp_sync_root):
        """SyncState tracks extracted files under archive."""
        sync_state = SyncState(temp_sync_root)
        sync_state.load()

        sync_state.add_archive(
            path="TestDrive/Setlist/Chart.7z",
            md5="def456",
            archive_size=5000,
            files={
                "song.ini": 100,
                "notes.mid": 500,
                "song.ogg": 4000
            }
        )

        # Get all tracked files
        all_files = sync_state.get_all_files()

        # Files should be at parent path (not under archive name)
        assert "TestDrive/Setlist/song.ini" in all_files
        assert "TestDrive/Setlist/notes.mid" in all_files
        assert "TestDrive/Setlist/song.ogg" in all_files

        # Verify NOT under archive name (the old broken behavior)
        assert "TestDrive/Setlist/Chart.7z/song.ini" not in all_files

    def test_sync_state_persistence(self, temp_sync_root):
        """SyncState saves and loads correctly."""
        # Create and save
        sync_state = SyncState(temp_sync_root)
        sync_state.load()
        sync_state.add_archive(
            path="TestDrive/Chart.7z",
            md5="persist123",
            archive_size=1000,
            files={"song.ini": 50}
        )
        sync_state.save()

        # Load fresh instance
        sync_state2 = SyncState(temp_sync_root)
        sync_state2.load()

        assert sync_state2.is_archive_synced("TestDrive/Chart.7z", "persist123")
        assert "TestDrive/song.ini" in sync_state2.get_all_files()

    def test_remove_archive(self, temp_sync_root):
        """Removing an archive removes it and its tracked files."""
        sync_state = SyncState(temp_sync_root)
        sync_state.load()

        # Add archive
        sync_state.add_archive(
            path="TestDrive/Setlist/Chart.7z",
            md5="remove_me",
            archive_size=1000,
            files={"song.ini": 50, "notes.mid": 100}
        )

        # Verify it's tracked
        assert sync_state.is_archive_synced("TestDrive/Setlist/Chart.7z", "remove_me")
        assert "TestDrive/Setlist/song.ini" in sync_state.get_all_files()

        # Remove it
        sync_state.remove_archive("TestDrive/Setlist/Chart.7z")

        # Verify it's gone
        assert not sync_state.is_archive_synced("TestDrive/Setlist/Chart.7z", "remove_me")
        assert "TestDrive/Setlist/song.ini" not in sync_state.get_all_files()
        assert "TestDrive/Setlist/notes.mid" not in sync_state.get_all_files()

    def test_all_paths_use_forward_slashes(self, temp_sync_root):
        """
        Critical cross-platform test: ALL paths in sync_state must use forward slashes.

        On Windows, Path operations naturally produce backslashes. If any code path
        stores paths with backslashes, lookups will fail because the rest of the
        codebase uses forward slashes consistently.

        This test verifies the paths returned by get_all_files(), which is what
        gets compared against local file scans during sync/purge operations.
        """
        sync_state = SyncState(temp_sync_root)
        sync_state.load()

        # Add archive with nested extracted files
        sync_state.add_archive(
            path="TestDrive/Deep/Nested/Path/Chart.7z",
            md5="test123",
            archive_size=1000,
            files={
                "subfolder/song.ini": 100,
                "subfolder/notes.mid": 500,
                "album.png": 200
            }
        )

        # Add standalone file with deep path
        sync_state.add_file("TestDrive/Another/Path/file.txt", size=50)

        # Verify all tracked paths use forward slashes
        all_files = sync_state.get_all_files()

        # Should have 4 files total
        assert len(all_files) == 4

        for path in all_files:
            assert "\\" not in path, f"Backslash found in tracked path: {path}"
            # Deep paths must contain forward slashes
            assert "/" in path, f"Deep path missing forward slashes: {path}"


class TestGetSyncStatusWithSyncState:
    """Tests for get_sync_status using sync_state."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_archive_recognized_as_synced(self, temp_dir):
        """get_sync_status recognizes archives tracked in sync_state."""
        folder_path = temp_dir / "TestDrive" / "Setlist"
        folder_path.mkdir(parents=True)

        (folder_path / "song.ini").write_text("[song]")
        (folder_path / "notes.mid").write_bytes(b"midi")

        sync_state = SyncState(temp_dir)
        sync_state.load()
        sync_state.add_archive(
            path="TestDrive/Setlist/pack.7z",
            md5="test_md5_hash",
            archive_size=5000,
            files={"song.ini": 6, "notes.mid": 4}
        )

        folder = {
            "folder_id": "test123",
            "name": "TestDrive",
            "files": [
                {
                    "path": "Setlist/pack.7z",
                    "md5": "test_md5_hash",
                    "size": 5000
                }
            ]
        }

        status = get_sync_status([folder], temp_dir, None, sync_state)

        assert status.synced_charts == 1
        assert status.total_charts == 1

    def test_archive_not_synced_without_sync_state_partial(self, temp_dir):
        """Archive NOT tracked in sync_state shows as not synced with incomplete folder.

        Smart fallback only considers a folder synced if it has 3+ files including
        a chart marker. A single file is NOT enough.
        """
        folder_path = temp_dir / "TestDrive" / "Setlist"
        folder_path.mkdir(parents=True)

        # Only 1 file on disk - smart fallback requires 3+
        (folder_path / "song.ini").write_text("[song]")

        folder = {
            "folder_id": "test123",
            "name": "TestDrive",
            "files": [
                {
                    "path": "Setlist/pack.7z",
                    "md5": "test_md5_hash",
                    "size": 5000
                }
            ]
        }

        # No sync_state - with only 1 file, smart fallback should NOT mark as synced
        status = get_sync_status([folder], temp_dir, None, None)

        # Partial folder (< 3 files) is NOT synced
        assert status.synced_charts == 0
        assert status.total_charts == 1

    def test_archive_not_synced_without_marker_even_with_files(self, temp_dir):
        """Archive NOT synced without marker/sync_state even if files exist on disk.

        The new marker-based architecture removes disk heuristics entirely.
        Without a marker or sync_state entry, we can't know what MD5 those
        files came from, so they're NOT considered synced.
        """
        folder_path = temp_dir / "TestDrive" / "Setlist"
        folder_path.mkdir(parents=True)

        # Files exist on disk (simulating manual copy or state loss)
        (folder_path / "song.ini").write_text("[song]")
        (folder_path / "notes.mid").write_bytes(b"midi data")
        (folder_path / "album.png").write_bytes(b"png data")

        folder = {
            "folder_id": "test123",
            "name": "TestDrive",
            "files": [
                {
                    "path": "Setlist/pack.7z",
                    "md5": "test_md5_hash",
                    "size": 5000
                }
            ]
        }

        # No sync_state, no marker - files on disk are NOT enough
        status = get_sync_status([folder], temp_dir, None, None)

        # Without marker/state, archive is NOT synced (no disk heuristics)
        assert status.synced_charts == 0
        assert status.total_charts == 1

    def test_archive_not_synced_without_files(self, temp_dir):
        """Archive without files on disk shows as not synced."""
        folder_path = temp_dir / "TestDrive" / "Setlist"
        folder_path.mkdir(parents=True)

        # No chart markers on disk - folder is empty

        folder = {
            "folder_id": "test123",
            "name": "TestDrive",
            "files": [
                {
                    "path": "Setlist/pack.7z",
                    "md5": "test_md5_hash",
                    "size": 5000
                }
            ]
        }

        status = get_sync_status([folder], temp_dir, None, None)

        # Should show as not synced - no files on disk
        assert status.synced_charts == 0
        assert status.total_charts == 1

    def test_archive_update_not_skipped_by_disk_fallback(self, temp_dir):
        """When archive has new MD5 (update available), disk fallback should NOT skip it.

        This ensures updates are downloaded even if old files exist on disk.
        """
        folder_path = temp_dir / "TestDrive" / "Setlist"
        folder_path.mkdir(parents=True)

        # Old chart files exist on disk
        (folder_path / "song.ini").write_text("[song]\nversion=old")

        # sync_state has OLD version
        sync_state = SyncState(temp_dir)
        sync_state.load()
        sync_state.add_archive(
            path="TestDrive/Setlist/pack.7z",
            md5="old_md5_hash",  # OLD MD5
            archive_size=5000,
            files={"song.ini": 100}
        )
        sync_state.save()

        # Manifest has NEW version
        folder = {
            "folder_id": "test123",
            "name": "TestDrive",
            "files": [
                {
                    "path": "Setlist/pack.7z",
                    "md5": "new_md5_hash",  # NEW MD5 - update available!
                    "size": 6000
                }
            ]
        }

        status = get_sync_status([folder], temp_dir, None, sync_state)

        # Should show as NOT synced - update available, don't skip via disk fallback
        assert status.synced_charts == 0
        assert status.total_charts == 1


class TestPurgePlannerWithSyncState:
    """Tests for purge planner using sync_state."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_synced_files_not_purgeable(self, temp_dir):
        """Files tracked in sync_state are not flagged as purgeable."""
        folder_path = temp_dir / "TestDrive" / "Setlist"
        folder_path.mkdir(parents=True)

        # Create files on disk
        (folder_path / "song.ini").write_text("[song]")
        (folder_path / "notes.mid").write_bytes(b"midi")

        # Create sync_state tracking these files
        sync_state = SyncState(temp_dir)
        sync_state.load()
        sync_state.add_archive(
            path="TestDrive/Setlist/Chart.7z",
            md5="xyz789",
            archive_size=1000,
            files={"song.ini": 6, "notes.mid": 4}
        )

        # Use find_extra_files
        extras = find_extra_files(
            folder_name="TestDrive",
            folder_path=temp_dir / "TestDrive",
            sync_state=sync_state,
            manifest_paths=set()
        )

        # No files should be flagged as extra
        assert len(extras) == 0

    def test_untracked_files_are_purgeable(self, temp_dir):
        """Files NOT in sync_state are flagged as purgeable."""
        folder_path = temp_dir / "TestDrive" / "Setlist"
        folder_path.mkdir(parents=True)

        # Create files on disk
        (folder_path / "song.ini").write_text("[song]")
        (folder_path / "extra_file.txt").write_text("extra")

        # Create sync_state tracking only song.ini
        sync_state = SyncState(temp_dir)
        sync_state.load()
        sync_state.add_archive(
            path="TestDrive/Setlist/Chart.7z",
            md5="xyz789",
            archive_size=1000,
            files={"song.ini": 6}
        )

        extras = find_extra_files(
            folder_name="TestDrive",
            folder_path=temp_dir / "TestDrive",
            sync_state=sync_state,
            manifest_paths=set()
        )

        # Only extra_file.txt should be flagged
        extra_names = [f.name for f, _ in extras]
        assert "extra_file.txt" in extra_names
        assert "song.ini" not in extra_names


class TestStatusMatchesDownloadPlanner:
    """
    Integration test: status and download_planner must agree.

    The bug was status showing +466.6 MB while download said "all synced".
    This happened because status counted missing videos but download skipped them.
    """

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_status_and_download_agree_on_missing_videos(self, temp_dir):
        """
        When delete_videos=True and only video files are missing,
        both status and download_planner should agree: nothing to download.
        """
        from src.sync.download_planner import plan_downloads

        folder_path = temp_dir / "TestDrive" / "Setlist" / "ChartFolder"
        folder_path.mkdir(parents=True)

        # Create non-video files on disk (video is missing)
        (folder_path / "song.ini").write_text("[song]")
        (folder_path / "notes.mid").write_bytes(b"midi")

        manifest_files = [
            {"id": "1", "path": "Setlist/ChartFolder/song.ini", "size": 6, "md5": "a"},
            {"id": "2", "path": "Setlist/ChartFolder/notes.mid", "size": 4, "md5": "b"},
            {"id": "3", "path": "Setlist/ChartFolder/video.webm", "size": 1000000, "md5": "c"},
        ]

        folder = {
            "folder_id": "test123",
            "name": "TestDrive",
            "files": manifest_files,
        }

        class MockSettings:
            delete_videos = True
            def is_drive_enabled(self, folder_id):
                return True
            def get_disabled_subfolders(self, folder_id):
                return set()

        # What does status say?
        status = get_sync_status([folder], temp_dir, MockSettings(), None)

        # What does download_planner say?
        tasks, skipped, _ = plan_downloads(
            manifest_files,
            temp_dir / "TestDrive",
            delete_videos=True,
            sync_state=None,
            folder_name="TestDrive",
        )

        # They must agree: nothing to download
        assert status.missing_charts == 0, "Status says charts missing"
        assert len(tasks) == 0, "Download planner has tasks"
        assert status.synced_charts == status.total_charts

    def test_status_and_download_agree_when_sync_state_matches_manifest(self, temp_dir):
        """
        When sync_state matches manifest AND disk files match, files are synced.

        Correctness requires verifying disk state matches sync_state. If a file
        was modified after download, it needs to be re-downloaded.
        """
        from src.sync.download_planner import plan_downloads

        folder_path = temp_dir / "TestDrive" / "Setlist" / "ChartFolder"
        folder_path.mkdir(parents=True)

        # Create files on disk with CORRECT sizes matching manifest
        (folder_path / "song.ini").write_text("[song]")  # 6 bytes
        (folder_path / "notes.mid").write_bytes(b"midi")  # 4 bytes

        manifest_files = [
            {"id": "1", "path": "Setlist/ChartFolder/song.ini", "size": 6, "md5": "a"},
            {"id": "2", "path": "Setlist/ChartFolder/notes.mid", "size": 4, "md5": "b"},
        ]

        folder = {
            "folder_id": "test123",
            "name": "TestDrive",
            "files": manifest_files,
        }

        # sync_state says both files are synced with manifest sizes
        sync_state = SyncState(temp_dir)
        sync_state.load()
        sync_state.add_file("TestDrive/Setlist/ChartFolder/song.ini", size=6)
        sync_state.add_file("TestDrive/Setlist/ChartFolder/notes.mid", size=4)

        class MockSettings:
            delete_videos = True
            def is_drive_enabled(self, folder_id):
                return True
            def get_disabled_subfolders(self, folder_id):
                return set()

        # What does download_planner say?
        tasks, skipped, _ = plan_downloads(
            manifest_files,
            temp_dir / "TestDrive",
            delete_videos=True,
            sync_state=sync_state,
            folder_name="TestDrive",
        )

        # sync_state matches manifest AND disk matches - skip both
        assert len(tasks) == 0, "sync_state matches manifest and disk, should skip"
        assert skipped == 2

    def test_status_and_download_agree_when_file_not_in_sync_state(self, temp_dir):
        """
        When a file is NOT in sync_state, both should fall back to disk check.
        """
        from src.sync.download_planner import plan_downloads

        folder_path = temp_dir / "TestDrive" / "Setlist" / "ChartFolder"
        folder_path.mkdir(parents=True)

        # Create files on disk - song.ini correct size, notes.mid wrong size
        (folder_path / "song.ini").write_text("[song]")  # 6 bytes, matches manifest
        (folder_path / "notes.mid").write_bytes(b"wrong")  # 5 bytes, manifest says 4

        manifest_files = [
            {"id": "1", "path": "Setlist/ChartFolder/song.ini", "size": 6, "md5": "a"},
            {"id": "2", "path": "Setlist/ChartFolder/notes.mid", "size": 4, "md5": "b"},
        ]

        folder = {
            "folder_id": "test123",
            "name": "TestDrive",
            "files": manifest_files,
        }

        # Empty sync_state - neither file is tracked
        sync_state = SyncState(temp_dir)
        sync_state.load()

        class MockSettings:
            delete_videos = True
            def is_drive_enabled(self, folder_id):
                return True
            def get_disabled_subfolders(self, folder_id):
                return set()

        status = get_sync_status([folder], temp_dir, MockSettings(), sync_state)
        tasks, skipped, _ = plan_downloads(
            manifest_files,
            temp_dir / "TestDrive",
            delete_videos=True,
            sync_state=sync_state,
            folder_name="TestDrive",
        )

        # Both should fall back to disk: song.ini OK, notes.mid needs download
        assert len(tasks) == 1, "download_planner should want to download notes.mid"
        assert status.missing_charts == 1, "status should show 1 chart missing"

    def test_nested_archive_adjustment_respects_delete_videos(self, temp_dir):
        """
        REGRESSION TEST: _adjust_for_nested_archives must respect delete_videos.

        The bug: When a folder has subfolders metadata (triggering nested archive
        adjustment), _adjust_for_nested_archives would recount synced charts but
        NOT filter out video files. Charts with missing videos were counted as
        NOT synced in the adjustment, causing +1 discrepancy.

        This test creates a chart with a video file where:
        - Non-video files are synced
        - Video file is missing (delete_videos=True)
        - Folder has subfolders metadata to trigger adjustment

        Expected: Chart should be counted as synced (video excluded).
        """
        folder_path = temp_dir / "TestDrive" / "Setlist" / "ChartFolder"
        folder_path.mkdir(parents=True)

        # Create non-video files on disk, video is missing
        (folder_path / "song.ini").write_text("[song]")
        (folder_path / "notes.mid").write_bytes(b"midi")

        manifest_files = [
            {"id": "1", "path": "Setlist/ChartFolder/song.ini", "size": 6, "md5": "a"},
            {"id": "2", "path": "Setlist/ChartFolder/notes.mid", "size": 4, "md5": "b"},
            {"id": "3", "path": "Setlist/ChartFolder/video.webm", "size": 1000000, "md5": "c"},
        ]

        # Folder with subfolders metadata - this triggers _adjust_for_nested_archives
        # The subfolders.charts.total must be > number of chart folders to trigger adjustment
        folder = {
            "folder_id": "test123",
            "name": "TestDrive",
            "files": manifest_files,
            "subfolders": [
                {
                    "name": "Setlist",
                    "charts": {"total": 5},  # More than 1 chart folder -> triggers adjustment
                    "total_size": 1000000,
                }
            ],
        }

        # Sync state tracks the non-video files as synced
        sync_state = SyncState(temp_dir)
        sync_state.load()
        sync_state.add_file("TestDrive/Setlist/ChartFolder/song.ini", size=6)
        sync_state.add_file("TestDrive/Setlist/ChartFolder/notes.mid", size=4)

        class MockSettings:
            delete_videos = True
            def is_drive_enabled(self, folder_id):
                return True
            def is_subfolder_enabled(self, folder_id, subfolder):
                return True
            def get_disabled_subfolders(self, folder_id):
                return set()

        status = get_sync_status([folder], temp_dir, MockSettings(), sync_state)

        # CRITICAL: The chart should be synced because:
        # 1. Non-video files are in sync_state
        # 2. Video is excluded when delete_videos=True
        # 3. _adjust_for_nested_archives must also respect delete_videos
        assert status.synced_charts == status.total_charts, (
            f"Chart with missing video should be synced when delete_videos=True. "
            f"Got {status.synced_charts}/{status.total_charts}"
        )


class TestCleanupOrphanedEntries:
    """Tests for SyncState.cleanup_orphaned_entries."""

    @pytest.fixture
    def temp_sync_root(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_removes_missing_files(self, temp_sync_root):
        """Entries for files that don't exist are removed."""
        sync_state = SyncState(temp_sync_root)
        sync_state.load()

        # Track files but don't create them on disk
        sync_state.add_file("TestDrive/missing1.txt", size=100)
        sync_state.add_file("TestDrive/missing2.txt", size=200)

        assert len(sync_state.get_all_files()) == 2

        # Cleanup should remove both
        removed = sync_state.cleanup_orphaned_entries()

        assert removed == 2
        assert len(sync_state.get_all_files()) == 0

    def test_keeps_existing_files(self, temp_sync_root):
        """Entries for files that exist are kept."""
        # Create actual files
        folder = temp_sync_root / "TestDrive"
        folder.mkdir()
        (folder / "exists.txt").write_text("content")

        sync_state = SyncState(temp_sync_root)
        sync_state.load()
        sync_state.add_file("TestDrive/exists.txt", size=7)

        removed = sync_state.cleanup_orphaned_entries()

        assert removed == 0
        assert "TestDrive/exists.txt" in sync_state.get_all_files()

    def test_mixed_existing_and_missing(self, temp_sync_root):
        """Only missing files are removed, existing ones kept."""
        folder = temp_sync_root / "TestDrive"
        folder.mkdir()
        (folder / "exists.txt").write_text("hello")

        sync_state = SyncState(temp_sync_root)
        sync_state.load()
        sync_state.add_file("TestDrive/exists.txt", size=5)
        sync_state.add_file("TestDrive/missing.txt", size=100)

        removed = sync_state.cleanup_orphaned_entries()

        assert removed == 1
        all_files = sync_state.get_all_files()
        assert "TestDrive/exists.txt" in all_files
        assert "TestDrive/missing.txt" not in all_files

    def test_archive_children_not_individually_removable(self, temp_sync_root):
        """
        Archive children can't be individually removed - they're stored under archive path.

        NOTE: This is a known limitation. cleanup_orphaned_entries works for standalone
        files but can't remove individual files from archives. The workaround is to
        remove the whole archive via remove_archive() if needed.
        """
        folder = temp_sync_root / "TestDrive" / "Setlist"
        folder.mkdir(parents=True)
        (folder / "song.ini").write_text("[song]")

        sync_state = SyncState(temp_sync_root)
        sync_state.load()
        sync_state.add_archive(
            path="TestDrive/Setlist/Chart.7z",
            md5="abc123",
            archive_size=1000,
            files={"song.ini": 6, "notes.mid": 100}  # notes.mid doesn't exist
        )

        # check_files_exist correctly identifies missing file
        missing = sync_state.check_files_exist(verify_sizes=False)
        assert "TestDrive/Setlist/notes.mid" in missing

        # But cleanup can't remove it (tree path mismatch)
        # This is expected behavior - archive files are managed together
        removed = sync_state.cleanup_orphaned_entries()
        assert removed == 0  # Can't remove archive children individually


class TestCleanupStaleArchives:
    """Tests for SyncState.cleanup_stale_archives."""

    @pytest.fixture
    def temp_sync_root(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_removes_case_mismatch_entries(self, temp_sync_root):
        """
        Archives with case mismatches should be removed.

        e.g., sync_state has "Love, Lust, and Liars" but manifest has "Love, Lust, And Liars"
        """
        sync_state = SyncState(temp_sync_root)
        sync_state.load()

        # Add archive with lowercase "and"
        sync_state.add_archive(
            "TestDrive/I Prevail - Love, Lust, and Liars/archive.rar",
            md5="abc123",
            archive_size=1000,
            files={"song.ini": 100}
        )

        # Manifest has uppercase "And"
        manifest_archives = {
            "TestDrive/I Prevail - Love, Lust, And Liars/archive.rar": "abc123"
        }

        removed = sync_state.cleanup_stale_archives(manifest_archives)

        assert removed == 1
        assert len(sync_state._archives) == 0

    def test_removes_md5_mismatch_entries(self, temp_sync_root):
        """
        Archives with outdated MD5s should be removed.
        """
        sync_state = SyncState(temp_sync_root)
        sync_state.load()

        # Add archive with old MD5
        sync_state.add_archive(
            "TestDrive/Setlist/archive.rar",
            md5="old_md5_hash",
            archive_size=1000,
            files={"song.ini": 100}
        )

        # Manifest has new MD5 (file was updated on Drive)
        manifest_archives = {
            "TestDrive/Setlist/archive.rar": "new_md5_hash"
        }

        removed = sync_state.cleanup_stale_archives(manifest_archives)

        assert removed == 1
        assert len(sync_state._archives) == 0

    def test_keeps_matching_entries(self, temp_sync_root):
        """
        Archives that match manifest exactly should be kept.
        """
        sync_state = SyncState(temp_sync_root)
        sync_state.load()

        sync_state.add_archive(
            "TestDrive/Setlist/archive.rar",
            md5="correct_md5",
            archive_size=1000,
            files={"song.ini": 100}
        )

        manifest_archives = {
            "TestDrive/Setlist/archive.rar": "correct_md5"
        }

        removed = sync_state.cleanup_stale_archives(manifest_archives)

        assert removed == 0
        assert len(sync_state._archives) == 1

    def test_keeps_entries_not_in_manifest(self, temp_sync_root):
        """
        Archives not in manifest should be kept (might be custom folders).
        """
        sync_state = SyncState(temp_sync_root)
        sync_state.load()

        sync_state.add_archive(
            "CustomFolder/archive.rar",
            md5="custom_md5",
            archive_size=1000,
            files={"song.ini": 100}
        )

        # Manifest doesn't have this archive at all
        manifest_archives = {
            "OtherDrive/other.rar": "other_md5"
        }

        removed = sync_state.cleanup_stale_archives(manifest_archives)

        assert removed == 0
        assert len(sync_state._archives) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
