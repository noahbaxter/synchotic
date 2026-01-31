"""
Tests for download planner logic.

Integration tests for plan_downloads() - what gets downloaded, skipped, or flagged.
Helper functions (is_archive_file) are tested implicitly through archive detection tests.
"""

import tempfile
from pathlib import Path

import pytest

from src.sync.download_planner import plan_downloads, DownloadTask
from src.sync.state import SyncState


class TestPlanDownloadsSkipping:
    """Tests for files that should be skipped."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_google_docs_skipped(self, temp_dir):
        """Files with no MD5 AND no extension are skipped (Google Docs/Sheets)."""
        files = [{"id": "1", "path": "My Document", "size": 0, "md5": ""}]
        tasks, skipped, long_paths = plan_downloads(files, temp_dir, delete_videos=True)
        assert len(tasks) == 0
        assert skipped == 1

    def test_file_with_md5_but_no_extension_included(self, temp_dir):
        """Files with MD5 but no extension are included (like _rb3con files)."""
        files = [{"id": "1", "path": "folder/_rb3con", "size": 100, "md5": "abc123"}]
        tasks, skipped, long_paths = plan_downloads(files, temp_dir, delete_videos=True)
        assert len(tasks) == 1

    def test_video_files_skipped_when_delete_videos_true(self, temp_dir):
        """Video files skipped when delete_videos=True."""
        files = [{"id": "1", "path": "folder/video.mp4", "size": 1000, "md5": "abc"}]
        tasks, skipped, long_paths = plan_downloads(files, temp_dir, delete_videos=True)
        assert len(tasks) == 0
        assert skipped == 1

    def test_video_files_included_when_delete_videos_false(self, temp_dir):
        """Video files included when delete_videos=False."""
        files = [{"id": "1", "path": "folder/video.mp4", "size": 1000, "md5": "abc"}]
        tasks, skipped, long_paths = plan_downloads(files, temp_dir, delete_videos=False)
        assert len(tasks) == 1

    def test_various_video_extensions_skipped(self, temp_dir):
        """All video extensions are skipped when delete_videos=True."""
        video_extensions = [".mp4", ".avi", ".webm", ".mov", ".mkv"]
        for ext in video_extensions:
            files = [{"id": "1", "path": f"folder/video{ext}", "size": 1000, "md5": "abc"}]
            tasks, skipped, _ = plan_downloads(files, temp_dir, delete_videos=True)
            assert len(tasks) == 0, f"{ext} should be skipped"
            assert skipped == 1


class TestPlanDownloadsArchives:
    """Tests for archive file handling."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_archive_detected_by_extension(self, temp_dir):
        """ZIP/7z/RAR files flagged as archives needing extraction."""
        for ext in [".zip", ".7z", ".rar", ".ZIP", ".7Z", ".RAR"]:
            files = [{"id": "1", "path": f"folder/chart{ext}", "size": 1000, "md5": "abc"}]
            tasks, _, _ = plan_downloads(files, temp_dir)
            assert len(tasks) == 1
            assert tasks[0].is_archive, f"{ext} should be detected as archive"

    def test_archive_download_path_is_temp_file(self, temp_dir):
        """Archives download to _download_ prefixed temp file."""
        files = [{"id": "1", "path": "Setlist/chart.7z", "size": 1000, "md5": "abc"}]
        tasks, _, _ = plan_downloads(files, temp_dir)
        assert "_download_chart.7z" in str(tasks[0].local_path)

    def test_synced_archive_skipped_via_sync_state(self, temp_dir):
        """Archives tracked in sync_state with matching MD5 are skipped."""
        # Create extracted files on disk at the path sync_state will check
        # sync_state looks for files at sync_root / tracked_path
        # so if archive is "TestDrive/folder/chart.7z", files are at "TestDrive/folder/song.ini"
        (temp_dir / "TestDrive" / "folder").mkdir(parents=True)
        (temp_dir / "TestDrive" / "folder" / "song.ini").write_text("[song]")

        sync_state = SyncState(temp_dir)
        sync_state.load()
        sync_state.add_archive(
            "TestDrive/folder/chart.7z",
            md5="abc123",
            archive_size=1000,
            files={"song.ini": 6}
        )

        # plan_downloads receives folder_path = temp_dir / "TestDrive"
        # and file path = "folder/chart.7z", so local_path = temp_dir/TestDrive/folder/chart.7z
        folder_path = temp_dir / "TestDrive"
        files = [{"id": "1", "path": "folder/chart.7z", "size": 1000, "md5": "abc123"}]
        tasks, skipped, _ = plan_downloads(
            files, folder_path, sync_state=sync_state, folder_name="TestDrive"
        )
        assert len(tasks) == 0
        assert skipped == 1

    def test_archive_redownloaded_when_md5_changed(self, temp_dir):
        """Archives with different MD5 than sync_state are re-downloaded."""
        sync_state = SyncState(temp_dir)
        sync_state.load()
        sync_state.add_archive(
            "TestDrive/folder/chart.7z",
            md5="old_md5",
            archive_size=1000,
            files={"song.ini": 6}
        )

        files = [{"id": "1", "path": "folder/chart.7z", "size": 1000, "md5": "new_md5"}]
        tasks, skipped, _ = plan_downloads(
            files, temp_dir, sync_state=sync_state, folder_name="TestDrive"
        )
        assert len(tasks) == 1  # MD5 changed, need to re-download

    def test_archive_redownloaded_when_extracted_files_missing(self, temp_dir):
        """Archives re-downloaded if extracted files no longer exist on disk."""
        # Don't create the extracted files on disk
        sync_state = SyncState(temp_dir)
        sync_state.load()
        sync_state.add_archive(
            "TestDrive/folder/chart.7z",
            md5="abc123",
            archive_size=1000,
            files={"song.ini": 6}  # This file doesn't exist on disk
        )

        files = [{"id": "1", "path": "folder/chart.7z", "size": 1000, "md5": "abc123"}]
        tasks, skipped, _ = plan_downloads(
            files, temp_dir, sync_state=sync_state, folder_name="TestDrive"
        )
        assert len(tasks) == 1  # Extracted files missing, need to re-download

    def test_archive_redownloaded_when_extracted_file_size_wrong(self, temp_dir):
        """
        Bug #9 regression test: archive extracted files exist but have wrong size.

        sync_state tracks extracted files with their sizes. If disk size differs
        (file corrupted, modified, or extraction was incomplete), should re-download.
        """
        # Create extracted file with WRONG size
        (temp_dir / "TestDrive" / "folder").mkdir(parents=True)
        (temp_dir / "TestDrive" / "folder" / "song.ini").write_text("short")  # 5 bytes

        sync_state = SyncState(temp_dir)
        sync_state.load()
        sync_state.add_archive(
            "TestDrive/folder/chart.7z",
            md5="abc123",
            archive_size=1000,
            files={"song.ini": 100}  # sync_state says 100 bytes, disk has 5
        )

        files = [{"id": "1", "path": "folder/chart.7z", "size": 1000, "md5": "abc123"}]
        tasks, skipped, _ = plan_downloads(
            files, temp_dir, sync_state=sync_state, folder_name="TestDrive"
        )

        # Should re-download because extracted file size is wrong
        assert len(tasks) == 1, "Should re-download when extracted file size differs"

    def test_missing_file_not_masked_by_disk_fallback(self, temp_dir):
        """
        Regression test: disk fallback must not override state-based missing file detection.

        Scenario: Archive extracted to folder with multiple charts. One chart folder
        is deleted. State correctly detects missing files, but disk fallback could
        find OTHER chart folders and incorrectly say "synced".

        The fix: disk fallback only runs when NO state entry exists. If state tracks
        the archive, trust the state's file list.
        """
        # Create chart folder structure - simulating extracted archive with 2 charts
        chart1 = temp_dir / "TestDrive" / "setlist" / "Chart1"
        chart2 = temp_dir / "TestDrive" / "setlist" / "Chart2"
        chart1.mkdir(parents=True)
        chart2.mkdir(parents=True)

        # Chart1 has all its files (with chart marker so fallback would find it)
        (chart1 / "song.ini").write_text("[song]")
        (chart1 / "notes.mid").write_bytes(b"midi data")

        # Chart2 is MISSING (deleted) - no files created

        # State tracks BOTH charts as extracted from the archive
        sync_state = SyncState(temp_dir)
        sync_state.load()
        sync_state.add_archive(
            "TestDrive/setlist/charts.7z",
            md5="abc123",
            archive_size=5000,
            files={
                "Chart1/song.ini": 6,
                "Chart1/notes.mid": 9,
                "Chart2/song.ini": 6,  # These don't exist on disk
                "Chart2/notes.mid": 9,
            }
        )

        files = [{"id": "1", "path": "setlist/charts.7z", "size": 5000, "md5": "abc123"}]
        tasks, skipped, _ = plan_downloads(
            files, temp_dir, sync_state=sync_state, folder_name="TestDrive"
        )

        # Should re-download: state says Chart2 files are missing
        # Disk fallback finding Chart1 must NOT override this
        assert len(tasks) == 1, (
            "Missing files from state should trigger re-download, "
            "even if disk fallback would find other chart folders"
        )


class TestPlanDownloadsRegularFiles:
    """Tests for regular (non-archive) file handling."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_new_file_downloaded(self, temp_dir):
        """Files not on disk are downloaded."""
        files = [{"id": "1", "path": "folder/song.ini", "size": 100, "md5": "abc"}]
        tasks, skipped, _ = plan_downloads(files, temp_dir)
        assert len(tasks) == 1
        assert not tasks[0].is_archive

    def test_existing_file_skipped_by_size_match(self, temp_dir):
        """Files matching local size are skipped."""
        local_file = temp_dir / "folder" / "song.ini"
        local_file.parent.mkdir(parents=True)
        local_file.write_text("content")  # 7 bytes

        files = [{"id": "1", "path": "folder/song.ini", "size": 7, "md5": "abc"}]
        tasks, skipped, _ = plan_downloads(files, temp_dir, delete_videos=True)
        assert len(tasks) == 0
        assert skipped == 1

    def test_size_mismatch_triggers_download(self, temp_dir):
        """Files with different size than local are downloaded."""
        local_file = temp_dir / "folder" / "song.ini"
        local_file.parent.mkdir(parents=True)
        local_file.write_text("old")  # 3 bytes

        files = [{"id": "1", "path": "folder/song.ini", "size": 100, "md5": "abc"}]
        tasks, skipped, _ = plan_downloads(files, temp_dir)
        assert len(tasks) == 1

    def test_sync_state_used_for_regular_files(self, temp_dir):
        """Regular files check sync_state if provided."""
        # Create file on disk
        local_file = temp_dir / "folder" / "song.ini"
        local_file.parent.mkdir(parents=True)
        local_file.write_text("content")  # 7 bytes

        sync_state = SyncState(temp_dir)
        sync_state.load()
        sync_state.add_file("TestDrive/folder/song.ini", size=7)

        files = [{"id": "1", "path": "folder/song.ini", "size": 7, "md5": "abc"}]
        tasks, skipped, _ = plan_downloads(
            files, temp_dir, sync_state=sync_state, folder_name="TestDrive"
        )
        assert len(tasks) == 0
        assert skipped == 1

    def test_sync_state_not_trusted_when_disk_size_wrong(self, temp_dir):
        """
        Even when sync_state matches manifest, file is re-downloaded if disk size is wrong.

        Correctness requires verifying actual disk state. If file was modified or
        corrupted after download, we need to re-download it.
        """
        # Create file on disk with DIFFERENT size than manifest
        local_file = temp_dir / "folder" / "song.ini"
        local_file.parent.mkdir(parents=True)
        local_file.write_text("modified content here")  # 21 bytes

        # sync_state says we downloaded it with manifest's expected size
        sync_state = SyncState(temp_dir)
        sync_state.load()
        sync_state.add_file("TestDrive/folder/song.ini", size=100)

        # Manifest says file should be 100 bytes (matches sync_state)
        files = [{"id": "1", "path": "folder/song.ini", "size": 100, "md5": "abc"}]
        tasks, skipped, _ = plan_downloads(
            files, temp_dir, sync_state=sync_state, folder_name="TestDrive"
        )

        # Disk file has wrong size (21 vs 100) - must re-download for correctness
        assert len(tasks) == 1, "should re-download when disk size differs from sync_state"
        assert skipped == 0

    def test_file_missing_from_disk_triggers_download(self, temp_dir):
        """
        Even if sync_state says file is synced, missing file triggers download.

        We trust sync_state for SIZE, but always verify file EXISTS.
        """
        # NO file on disk

        sync_state = SyncState(temp_dir)
        sync_state.load()
        sync_state.add_file("TestDrive/folder/song.ini", size=100)

        files = [{"id": "1", "path": "folder/song.ini", "size": 100, "md5": "abc"}]
        tasks, skipped, _ = plan_downloads(
            files, temp_dir, sync_state=sync_state, folder_name="TestDrive"
        )

        # File doesn't exist - must download
        assert len(tasks) == 1, "missing file should trigger download"
        assert skipped == 0

    def test_sync_state_size_differs_from_manifest_same_md5(self, temp_dir):
        """
        When sync_state has different size than manifest but same MD5, trust sync_state.

        This handles the case where manifest is stale (common with shortcuts).
        If MD5 matches, the content is the same - just different recorded sizes.
        """
        local_file = temp_dir / "folder" / "song.ini"
        local_file.parent.mkdir(parents=True)
        local_file.write_text("actual content")  # 14 bytes

        # sync_state tracked the actual downloaded size (14 bytes)
        sync_state = SyncState(temp_dir)
        sync_state.load()
        sync_state.add_file("TestDrive/folder/song.ini", size=14, md5="abc123")

        # Manifest has stale size (10 bytes) but same MD5
        files = [{"id": "1", "path": "folder/song.ini", "size": 10, "md5": "abc123"}]
        tasks, skipped, _ = plan_downloads(
            files, temp_dir, sync_state=sync_state, folder_name="TestDrive"
        )

        # Same MD5 means same content - trust sync_state, don't re-download
        assert len(tasks) == 0, "same MD5 should trust sync_state despite size mismatch"
        assert skipped == 1

    def test_md5_changed_triggers_redownload(self, temp_dir):
        """
        When manifest MD5 differs from sync_state, file was updated - re-download.
        """
        local_file = temp_dir / "folder" / "song.ini"
        local_file.parent.mkdir(parents=True)
        local_file.write_text("old content")

        # sync_state has old MD5
        sync_state = SyncState(temp_dir)
        sync_state.load()
        sync_state.add_file("TestDrive/folder/song.ini", size=11, md5="old_md5")

        # Manifest has NEW MD5 (file was updated upstream)
        files = [{"id": "1", "path": "folder/song.ini", "size": 15, "md5": "new_md5"}]
        tasks, skipped, _ = plan_downloads(
            files, temp_dir, sync_state=sync_state, folder_name="TestDrive"
        )

        # Different MD5 = content changed, must re-download
        assert len(tasks) == 1, "changed MD5 should trigger re-download"
        assert skipped == 0

    def test_ini_file_with_local_modifications_not_redownloaded(self, temp_dir):
        """
        INI files modified locally (game appends lines) should not trigger re-download.

        Clone Hero appends leaderboard data to song.ini files, making local size
        larger than original. If MD5 matches (file unchanged on host), skip it.
        """
        # Local file is LARGER than original (game appended lines)
        local_file = temp_dir / "folder" / "song.ini"
        local_file.parent.mkdir(parents=True)
        local_file.write_text("original content\n[leaderboard]\nscores=...")  # 45 bytes

        # sync_state recorded original size (16 bytes) when we downloaded
        sync_state = SyncState(temp_dir)
        sync_state.load()
        sync_state.add_file("TestDrive/folder/song.ini", size=16, md5="abc123")

        # Manifest still has original size and MD5 (unchanged on host)
        files = [{"id": "1", "path": "folder/song.ini", "size": 16, "md5": "abc123"}]
        tasks, skipped, _ = plan_downloads(
            files, temp_dir, sync_state=sync_state, folder_name="TestDrive"
        )

        # Same MD5 + .ini file + exists locally = don't re-download
        assert len(tasks) == 0, "locally modified .ini should not trigger re-download"
        assert skipped == 1

    def test_non_ini_file_with_local_modifications_redownloaded(self, temp_dir):
        """
        Non-INI files with size mismatch should still trigger re-download.

        The .ini exception only applies to .ini files.
        """
        # Local file is larger than original
        local_file = temp_dir / "folder" / "notes.mid"
        local_file.parent.mkdir(parents=True)
        local_file.write_bytes(b"original content plus extra")  # 27 bytes

        # sync_state recorded original size
        sync_state = SyncState(temp_dir)
        sync_state.load()
        sync_state.add_file("TestDrive/folder/notes.mid", size=16, md5="abc123")

        # Manifest unchanged
        files = [{"id": "1", "path": "folder/notes.mid", "size": 16, "md5": "abc123"}]
        tasks, skipped, _ = plan_downloads(
            files, temp_dir, sync_state=sync_state, folder_name="TestDrive"
        )

        # Non-INI file with wrong size = re-download
        assert len(tasks) == 1, "non-ini with size mismatch should re-download"
        assert skipped == 0


class TestPlanDownloadsMigration:
    """Tests for migration from rclone and sync_state recovery."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_file_not_in_sync_state_but_exists_with_correct_size(self, temp_dir):
        """
        Migration case: file exists on disk but not in sync_state.

        When sync_state doesn't know about a file (migration from rclone,
        or after deleting sync_state.json), fall back to filesystem check.
        If file exists with correct size, skip it.
        """
        # Create file on disk with correct size
        local_file = temp_dir / "folder" / "song.ini"
        local_file.parent.mkdir(parents=True)
        local_file.write_text("content")  # 7 bytes

        # Empty sync_state (simulates migration or deleted sync_state.json)
        sync_state = SyncState(temp_dir)
        sync_state.load()

        # Manifest says file should be 7 bytes
        files = [{"id": "1", "path": "folder/song.ini", "size": 7, "md5": "abc"}]
        tasks, skipped, _ = plan_downloads(
            files, temp_dir, sync_state=sync_state, folder_name="TestDrive"
        )

        # File exists with correct size - should be skipped
        assert len(tasks) == 0, "Existing file with correct size should be skipped"
        assert skipped == 1

    def test_file_not_in_sync_state_exists_with_wrong_size(self, temp_dir):
        """
        Migration case: file exists but with wrong size.

        File might be outdated or corrupted. Should re-download.
        """
        # Create file on disk with WRONG size
        local_file = temp_dir / "folder" / "song.ini"
        local_file.parent.mkdir(parents=True)
        local_file.write_text("old")  # 3 bytes

        # Empty sync_state
        sync_state = SyncState(temp_dir)
        sync_state.load()

        # Manifest says file should be 100 bytes
        files = [{"id": "1", "path": "folder/song.ini", "size": 100, "md5": "abc"}]
        tasks, skipped, _ = plan_downloads(
            files, temp_dir, sync_state=sync_state, folder_name="TestDrive"
        )

        # File exists but wrong size - should download
        assert len(tasks) == 1, "File with wrong size should be downloaded"
        assert skipped == 0

    def test_file_not_in_sync_state_does_not_exist(self, temp_dir):
        """
        Migration case: file not in sync_state and doesn't exist on disk.

        This is a genuinely new file that needs downloading.
        """
        # Empty sync_state, no file on disk
        sync_state = SyncState(temp_dir)
        sync_state.load()

        files = [{"id": "1", "path": "folder/song.ini", "size": 100, "md5": "abc"}]
        tasks, skipped, _ = plan_downloads(
            files, temp_dir, sync_state=sync_state, folder_name="TestDrive"
        )

        # File doesn't exist - should download
        assert len(tasks) == 1
        assert skipped == 0

    def test_sync_state_none_falls_back_to_filesystem(self, temp_dir):
        """
        When sync_state is None, always check filesystem.
        """
        # Create file on disk
        local_file = temp_dir / "folder" / "song.ini"
        local_file.parent.mkdir(parents=True)
        local_file.write_text("content")  # 7 bytes

        # No sync_state at all
        files = [{"id": "1", "path": "folder/song.ini", "size": 7, "md5": "abc"}]
        tasks, skipped, _ = plan_downloads(
            files, temp_dir, sync_state=None, folder_name="TestDrive"
        )

        # Should check filesystem and find the file
        assert len(tasks) == 0
        assert skipped == 1

    def test_manifest_size_changed_triggers_redownload(self, temp_dir):
        """
        When manifest has new size, file should be re-downloaded.

        sync_state tracks what we downloaded. If manifest is updated with
        a new version (different size), sync_state won't match and we
        fall back to filesystem check.
        """
        # Create file on disk with old size
        local_file = temp_dir / "folder" / "song.ini"
        local_file.parent.mkdir(parents=True)
        local_file.write_text("old content")  # 11 bytes

        # sync_state has old size
        sync_state = SyncState(temp_dir)
        sync_state.load()
        sync_state.add_file("TestDrive/folder/song.ini", size=11)

        # Manifest updated with NEW size (new version of file)
        files = [{"id": "1", "path": "folder/song.ini", "size": 200, "md5": "newmd5"}]
        tasks, skipped, _ = plan_downloads(
            files, temp_dir, sync_state=sync_state, folder_name="TestDrive"
        )

        # sync_state size (11) != manifest size (200), so is_file_synced returns False
        # Filesystem check: disk size (11) != manifest size (200)
        # Should re-download
        assert len(tasks) == 1, "Changed manifest size should trigger re-download"

    def test_multiple_files_mixed_states(self, temp_dir):
        """
        Test handling multiple files with different states.
        """
        # File 1: in sync_state, should be trusted
        # File 2: not in sync_state, exists with correct size
        # File 3: not in sync_state, exists with wrong size
        # File 4: not in sync_state, doesn't exist

        (temp_dir / "folder").mkdir(parents=True)
        (temp_dir / "folder" / "file1.ini").write_text("x" * 10)
        (temp_dir / "folder" / "file2.ini").write_text("x" * 20)
        (temp_dir / "folder" / "file3.ini").write_text("x" * 5)  # wrong size
        # file4 doesn't exist

        sync_state = SyncState(temp_dir)
        sync_state.load()
        sync_state.add_file("TestDrive/folder/file1.ini", size=10)

        files = [
            {"id": "1", "path": "folder/file1.ini", "size": 10, "md5": "a"},
            {"id": "2", "path": "folder/file2.ini", "size": 20, "md5": "b"},
            {"id": "3", "path": "folder/file3.ini", "size": 30, "md5": "c"},  # disk has 5
            {"id": "4", "path": "folder/file4.ini", "size": 40, "md5": "d"},
        ]
        tasks, skipped, _ = plan_downloads(
            files, temp_dir, sync_state=sync_state, folder_name="TestDrive"
        )

        # file1: skipped (sync_state)
        # file2: skipped (filesystem fallback, correct size)
        # file3: download (filesystem fallback, wrong size)
        # file4: download (doesn't exist)
        assert skipped == 2
        assert len(tasks) == 2
        task_paths = [str(t.local_path) for t in tasks]
        assert any("file3.ini" in p for p in task_paths)
        assert any("file4.ini" in p for p in task_paths)


class TestPlanDownloadsPathSanitization:
    """Tests for path sanitization during planning."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_colon_sanitized_in_path(self, temp_dir):
        """Colons in paths are sanitized to ' -'."""
        files = [{"id": "1", "path": "Title: Subtitle/song.ini", "size": 100, "md5": "abc"}]
        tasks, _, _ = plan_downloads(files, temp_dir)
        assert "Title - Subtitle" in str(tasks[0].local_path)

    def test_illegal_chars_sanitized(self, temp_dir):
        """Various illegal characters are sanitized."""
        files = [{"id": "1", "path": "What?/song*.ini", "size": 100, "md5": "abc"}]
        tasks, _, _ = plan_downloads(files, temp_dir)
        # ? and * should be removed
        assert "?" not in str(tasks[0].local_path)
        assert "*" not in str(tasks[0].local_path)


class TestPlanDownloadsLongPaths:
    """Tests for filesystem path/filename limit handling."""

    @pytest.fixture
    def temp_dir(self, monkeypatch):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            # Set up markers directory to avoid Path issues when monkeypatching os.name
            markers_dir = tmp_path / ".dm-sync" / "markers"
            markers_dir.mkdir(parents=True)
            monkeypatch.setattr("src.sync.markers.get_markers_dir", lambda: markers_dir)
            yield tmp_path

    def test_long_path_skipped_when_not_enabled(self, temp_dir, monkeypatch):
        """Paths exceeding 260 chars on Windows are skipped when long paths not enabled."""
        monkeypatch.setattr("os.name", "nt")
        # Simulate long paths NOT enabled in registry
        import src.sync.download_planner as dp
        monkeypatch.setattr(dp, "is_long_paths_enabled", lambda: False)

        # Create a path that will exceed 260 chars (but no single component > 255)
        files = [{"id": "1", "path": f"{'A' * 100}/{'B' * 100}/chart.7z", "size": 1000, "md5": "abc"}]
        tasks, skipped, long_paths = plan_downloads(files, temp_dir)

        # Should be skipped due to long total path
        assert len(tasks) == 0
        assert len(long_paths) == 1

    def test_long_path_allowed_when_enabled(self, temp_dir, monkeypatch):
        """Paths exceeding 260 chars on Windows are allowed when long paths enabled."""
        monkeypatch.setattr("os.name", "nt")
        # Simulate long paths ENABLED in registry
        import src.sync.download_planner as dp
        monkeypatch.setattr(dp, "is_long_paths_enabled", lambda: True)

        # Create a path that will exceed 260 chars (but no single component > 255)
        files = [{"id": "1", "path": f"{'A' * 100}/{'B' * 100}/chart.7z", "size": 1000, "md5": "abc"}]
        tasks, skipped, long_paths = plan_downloads(files, temp_dir)

        # Should NOT be skipped - long paths are enabled
        assert len(tasks) == 1
        assert len(long_paths) == 0

    def test_long_path_not_checked_on_unix(self, temp_dir, monkeypatch):
        """Total path length is not checked on non-Windows systems."""
        monkeypatch.setattr("os.name", "posix")

        # Long total path but no single component > 255
        files = [{"id": "1", "path": f"{'A' * 100}/{'B' * 100}/chart.7z", "size": 1000, "md5": "abc"}]
        tasks, skipped, long_paths = plan_downloads(files, temp_dir)

        # Should not be skipped on Unix (path length OK)
        assert len(tasks) == 1
        assert len(long_paths) == 0

    def test_long_filename_skipped_on_all_platforms(self, temp_dir):
        """Files with names > 255 chars are skipped on all platforms."""
        # Create a file with name > 255 chars
        long_name = "A" * 260 + ".7z"
        files = [{"id": "1", "path": f"folder/{long_name}", "size": 1000, "md5": "abc"}]
        tasks, skipped, long_paths = plan_downloads(files, temp_dir)

        # Should be skipped due to filename > 255
        assert len(tasks) == 0
        assert len(long_paths) == 1

    def test_long_folder_name_skipped(self, temp_dir):
        """Folders with names > 255 chars are skipped on all platforms."""
        # Create a folder with name > 255 chars
        long_folder = "A" * 260
        files = [{"id": "1", "path": f"{long_folder}/chart.7z", "size": 1000, "md5": "abc"}]
        tasks, skipped, long_paths = plan_downloads(files, temp_dir)

        # Should be skipped due to folder name > 255
        assert len(tasks) == 0
        assert len(long_paths) == 1

    def test_normal_length_paths_allowed(self, temp_dir):
        """Normal length paths work fine."""
        files = [{"id": "1", "path": "folder/subfolder/chart.7z", "size": 1000, "md5": "abc"}]
        tasks, skipped, long_paths = plan_downloads(files, temp_dir)

        assert len(tasks) == 1
        assert len(long_paths) == 0


class TestDownloadTaskDataclass:
    """Tests for DownloadTask dataclass."""

    def test_default_values(self):
        """DownloadTask has sensible defaults."""
        task = DownloadTask(file_id="123", local_path=Path("/tmp/file.txt"))
        assert task.size == 0
        assert task.md5 == ""
        assert task.is_archive is False
        assert task.rel_path == ""

    def test_all_fields_set(self):
        """All fields can be set explicitly."""
        task = DownloadTask(
            file_id="123",
            local_path=Path("/tmp/file.7z"),
            size=1000,
            md5="abc123",
            is_archive=True,
            rel_path="TestDrive/folder/file.7z"
        )
        assert task.file_id == "123"
        assert task.size == 1000
        assert task.md5 == "abc123"
        assert task.is_archive is True
        assert task.rel_path == "TestDrive/folder/file.7z"


class TestCleanupPartialDownloads:
    """Tests for FileDownloader._cleanup_partial_downloads."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_cleans_download_prefix_files(self, temp_dir):
        """Archive files with _download_ prefix are deleted."""
        from src.sync.downloader import FileDownloader

        # Create partial download file
        chart_folder = temp_dir / "Setlist" / "ChartFolder"
        chart_folder.mkdir(parents=True)
        partial = chart_folder / "_download_chart.7z"
        partial.write_bytes(b"partial data")

        task = DownloadTask(
            file_id="123",
            local_path=partial,
            is_archive=True,
        )

        downloader = FileDownloader()
        cleaned = downloader._cleanup_partial_downloads([task])

        assert cleaned == 1
        assert not partial.exists()

    def test_cleans_renamed_archive_files(self, temp_dir):
        """Archive files renamed (prefix removed) are also deleted."""
        from src.sync.downloader import FileDownloader

        chart_folder = temp_dir / "Setlist" / "ChartFolder"
        chart_folder.mkdir(parents=True)

        # Create both the _download_ version and the renamed version
        partial = chart_folder / "_download_chart.7z"
        renamed = chart_folder / "chart.7z"
        partial.write_bytes(b"partial")
        renamed.write_bytes(b"renamed")

        task = DownloadTask(
            file_id="123",
            local_path=partial,
            is_archive=True,
        )

        downloader = FileDownloader()
        cleaned = downloader._cleanup_partial_downloads([task])

        assert cleaned == 2
        assert not partial.exists()
        assert not renamed.exists()

    def test_ignores_non_archive_tasks(self, temp_dir):
        """Non-archive tasks are not cleaned up."""
        from src.sync.downloader import FileDownloader

        file_path = temp_dir / "song.ini"
        file_path.write_text("[song]")

        task = DownloadTask(
            file_id="123",
            local_path=file_path,
            is_archive=False,
        )

        downloader = FileDownloader()
        cleaned = downloader._cleanup_partial_downloads([task])

        assert cleaned == 0
        assert file_path.exists()

    def test_ignores_missing_files(self, temp_dir):
        """Missing files don't cause errors."""
        from src.sync.downloader import FileDownloader

        task = DownloadTask(
            file_id="123",
            local_path=temp_dir / "_download_missing.7z",
            is_archive=True,
        )

        downloader = FileDownloader()
        cleaned = downloader._cleanup_partial_downloads([task])

        assert cleaned == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
