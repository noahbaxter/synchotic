"""
Tests for download planner logic.

Integration tests for plan_downloads() - what gets downloaded, skipped, or flagged.
Helper functions (is_archive_file) are tested implicitly through archive detection tests.
"""

import tempfile
from pathlib import Path

import pytest

from src.sync.download_planner import plan_downloads, DownloadTask
from src.sync.markers import save_marker


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

    def test_synced_archive_skipped_via_marker(self, temp_dir, monkeypatch):
        """Archives with matching marker and verified files on disk are skipped."""
        markers_dir = temp_dir / ".dm-sync" / "markers"
        markers_dir.mkdir(parents=True)
        monkeypatch.setattr("src.sync.markers.get_markers_dir", lambda: markers_dir)

        # Create extracted files on disk
        (temp_dir / "TestDrive" / "folder").mkdir(parents=True)
        (temp_dir / "TestDrive" / "folder" / "song.ini").write_text("[song]")

        # Save marker — archive_path includes folder_name prefix
        save_marker(
            archive_path="TestDrive/folder/chart.7z",
            md5="abc123",
            extracted_files={"folder/song.ini": 6},
        )

        folder_path = temp_dir / "TestDrive"
        files = [{"id": "1", "path": "folder/chart.7z", "size": 1000, "md5": "abc123"}]
        tasks, skipped, _ = plan_downloads(files, folder_path, folder_name="TestDrive")
        assert len(tasks) == 0
        assert skipped == 1

    def test_archive_redownloaded_when_md5_changed(self, temp_dir, monkeypatch):
        """Archives with different MD5 than marker are re-downloaded."""
        markers_dir = temp_dir / ".dm-sync" / "markers"
        markers_dir.mkdir(parents=True)
        monkeypatch.setattr("src.sync.markers.get_markers_dir", lambda: markers_dir)

        # Save marker with old MD5
        save_marker(
            archive_path="TestDrive/folder/chart.7z",
            md5="old_md5",
            extracted_files={"folder/song.ini": 6},
        )

        # Manifest has new MD5
        files = [{"id": "1", "path": "folder/chart.7z", "size": 1000, "md5": "new_md5"}]
        tasks, skipped, _ = plan_downloads(files, temp_dir, folder_name="TestDrive")
        assert len(tasks) == 1  # MD5 changed, need to re-download

    def test_archive_redownloaded_when_extracted_files_missing(self, temp_dir, monkeypatch):
        """Archives re-downloaded if extracted files no longer exist on disk."""
        markers_dir = temp_dir / ".dm-sync" / "markers"
        markers_dir.mkdir(parents=True)
        monkeypatch.setattr("src.sync.markers.get_markers_dir", lambda: markers_dir)

        # Save marker but don't create extracted files on disk
        save_marker(
            archive_path="TestDrive/folder/chart.7z",
            md5="abc123",
            extracted_files={"folder/song.ini": 6},
        )

        files = [{"id": "1", "path": "folder/chart.7z", "size": 1000, "md5": "abc123"}]
        tasks, skipped, _ = plan_downloads(files, temp_dir, folder_name="TestDrive")
        assert len(tasks) == 1  # Extracted files missing, need to re-download

    def test_archive_redownloaded_when_extracted_file_size_wrong(self, temp_dir, monkeypatch):
        """
        Bug #9 regression test: archive extracted files exist but have wrong size.

        Markers track extracted files with their sizes. If disk size differs
        (file corrupted, modified, or extraction was incomplete), should re-download.
        """
        markers_dir = temp_dir / ".dm-sync" / "markers"
        markers_dir.mkdir(parents=True)
        monkeypatch.setattr("src.sync.markers.get_markers_dir", lambda: markers_dir)

        # Create extracted file with WRONG size
        (temp_dir / "TestDrive" / "folder").mkdir(parents=True)
        (temp_dir / "TestDrive" / "folder" / "song.ini").write_text("short")  # 5 bytes

        # Marker says file should be 100 bytes
        save_marker(
            archive_path="TestDrive/folder/chart.7z",
            md5="abc123",
            extracted_files={"folder/song.ini": 100},
        )

        files = [{"id": "1", "path": "folder/chart.7z", "size": 1000, "md5": "abc123"}]
        tasks, skipped, _ = plan_downloads(
            files, temp_dir / "TestDrive", folder_name="TestDrive"
        )

        # Should re-download because extracted file size is wrong
        assert len(tasks) == 1, "Should re-download when extracted file size differs"

    def test_missing_file_not_masked_by_disk_fallback(self, temp_dir, monkeypatch):
        """
        Regression test: disk fallback must not override marker-based missing file detection.

        Scenario: Archive extracted to folder with multiple charts. One chart folder
        is deleted. Marker correctly detects missing files, but disk fallback could
        find OTHER chart folders and incorrectly say "synced".
        """
        markers_dir = temp_dir / ".dm-sync" / "markers"
        markers_dir.mkdir(parents=True)
        monkeypatch.setattr("src.sync.markers.get_markers_dir", lambda: markers_dir)

        # Create chart folder structure - simulating extracted archive with 2 charts
        chart1 = temp_dir / "TestDrive" / "setlist" / "Chart1"
        chart2 = temp_dir / "TestDrive" / "setlist" / "Chart2"
        chart1.mkdir(parents=True)
        # Chart2 directory NOT created - simulating deleted chart

        # Chart1 has all its files
        (chart1 / "song.ini").write_text("[song]")
        (chart1 / "notes.mid").write_bytes(b"midi data")

        # Marker tracks BOTH charts as extracted from the archive
        save_marker(
            archive_path="TestDrive/setlist/charts.7z",
            md5="abc123",
            extracted_files={
                "setlist/Chart1/song.ini": 6,
                "setlist/Chart1/notes.mid": 9,
                "setlist/Chart2/song.ini": 6,  # These don't exist on disk
                "setlist/Chart2/notes.mid": 9,
            },
        )

        files = [{"id": "1", "path": "setlist/charts.7z", "size": 5000, "md5": "abc123"}]
        tasks, skipped, _ = plan_downloads(
            files, temp_dir / "TestDrive", folder_name="TestDrive"
        )

        # Should re-download: marker says Chart2 files are missing
        assert len(tasks) == 1, (
            "Missing files from marker should trigger re-download, "
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

    def test_disk_size_wrong_triggers_redownload(self, temp_dir):
        """File on disk with wrong size is re-downloaded."""
        # Create file on disk with DIFFERENT size than manifest
        local_file = temp_dir / "folder" / "song.ini"
        local_file.parent.mkdir(parents=True)
        local_file.write_text("modified content here")  # 21 bytes

        # Manifest says file should be 100 bytes
        files = [{"id": "1", "path": "folder/song.ini", "size": 100, "md5": "abc"}]
        tasks, skipped, _ = plan_downloads(files, temp_dir)

        # Disk file has wrong size (21 vs 100) - must re-download
        assert len(tasks) == 1, "should re-download when disk size differs from manifest"
        assert skipped == 0

    def test_file_missing_from_disk_triggers_download(self, temp_dir):
        """Missing file triggers download regardless."""
        # NO file on disk
        files = [{"id": "1", "path": "folder/song.ini", "size": 100, "md5": "abc"}]
        tasks, skipped, _ = plan_downloads(files, temp_dir)

        # File doesn't exist - must download
        assert len(tasks) == 1, "missing file should trigger download"
        assert skipped == 0

    def test_manifest_size_changed_triggers_redownload(self, temp_dir):
        """When manifest has new size, file should be re-downloaded."""
        local_file = temp_dir / "folder" / "song.ini"
        local_file.parent.mkdir(parents=True)
        local_file.write_text("old content")  # 11 bytes

        # Manifest updated with NEW size (new version of file)
        files = [{"id": "1", "path": "folder/song.ini", "size": 200, "md5": "newmd5"}]
        tasks, skipped, _ = plan_downloads(files, temp_dir)

        # Disk size (11) != manifest size (200) → re-download
        assert len(tasks) == 1, "Changed manifest size should trigger re-download"

    def test_multiple_files_mixed_states(self, temp_dir):
        """Test handling multiple files with different states."""
        # file1: 10 bytes on disk, manifest 10 → skip
        # file2: 20 bytes on disk, manifest 20 → skip
        # file3: 5 bytes on disk, manifest 30 → download
        # file4: doesn't exist, manifest 40 → download

        (temp_dir / "folder").mkdir(parents=True)
        (temp_dir / "folder" / "file1.ini").write_text("x" * 10)
        (temp_dir / "folder" / "file2.ini").write_text("x" * 20)
        (temp_dir / "folder" / "file3.ini").write_text("x" * 5)  # wrong size
        # file4 doesn't exist

        files = [
            {"id": "1", "path": "folder/file1.ini", "size": 10, "md5": "a"},
            {"id": "2", "path": "folder/file2.ini", "size": 20, "md5": "b"},
            {"id": "3", "path": "folder/file3.ini", "size": 30, "md5": "c"},  # disk has 5
            {"id": "4", "path": "folder/file4.ini", "size": 40, "md5": "d"},
        ]
        tasks, skipped, _ = plan_downloads(files, temp_dir)

        # file1: skipped (correct size)
        # file2: skipped (correct size)
        # file3: download (wrong size)
        # file4: download (doesn't exist)
        assert skipped == 2
        assert len(tasks) == 2
        task_paths = [str(t.local_path) for t in tasks]
        assert any("file3.ini" in p for p in task_paths)
        assert any("file4.ini" in p for p in task_paths)


class TestPlanDownloadsPathSanitization:
    """Tests that plan_downloads works with pre-sanitized paths from scanner.

    Path sanitization happens at the scanner level (sanitize_filename on each
    component), so plan_downloads receives already-clean paths.
    """

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_sanitized_colon_path(self, temp_dir):
        """Pre-sanitized colon paths (: -> ' -') are used as-is."""
        files = [{"id": "1", "path": "Title - Subtitle/song.ini", "size": 100, "md5": "abc"}]
        tasks, _, _ = plan_downloads(files, temp_dir)
        assert "Title - Subtitle" in str(tasks[0].local_path)

    def test_sanitized_special_chars_path(self, temp_dir):
        """Pre-sanitized paths with special chars removed are used as-is."""
        files = [{"id": "1", "path": "What/song.ini", "size": 100, "md5": "abc"}]
        tasks, _, _ = plan_downloads(files, temp_dir)
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

    def test_long_path_skipped_when_exceeds_limit(self, temp_dir, monkeypatch):
        """Paths exceeding Windows MAX_PATH are skipped when long paths not enabled."""
        import src.sync.download_planner as dp
        monkeypatch.setattr(dp, "exceeds_windows_path_limit", lambda path: len(str(path)) >= 260)

        # Create a path that will exceed 260 chars with temp_dir prefix (no single component > 255)
        files = [{"id": "1", "path": f"{'A' * 120}/{'B' * 120}/chart.7z", "size": 1000, "md5": "abc"}]
        tasks, skipped, long_paths = plan_downloads(files, temp_dir)

        # Should be skipped due to long total path
        assert len(tasks) == 0
        assert len(long_paths) == 1

    def test_long_path_allowed_when_no_limit(self, temp_dir, monkeypatch):
        """Paths are allowed when path limit check passes."""
        import src.sync.download_planner as dp
        monkeypatch.setattr(dp, "exceeds_windows_path_limit", lambda path: False)

        # Create a path that will exceed 260 chars with temp_dir prefix (no single component > 255)
        files = [{"id": "1", "path": f"{'A' * 120}/{'B' * 120}/chart.7z", "size": 1000, "md5": "abc"}]
        tasks, skipped, long_paths = plan_downloads(files, temp_dir)

        # Should NOT be skipped (limit disabled)
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


class TestPlanDownloadsArchiveDedup:
    """Tests for case-insensitive archive deduplication."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_multiple_archives_in_same_folder_all_downloaded(self, temp_dir):
        """Multiple distinct archives in the same folder should ALL be downloaded.

        Regression: old logic deduped by extraction folder, causing numbered pack
        files (TBRB 1.7z, TBRB 2.7z, ...) to be silently skipped.
        """
        files = [
            {"id": "1", "path": "Setlist/pack1.7z", "size": 1000, "md5": "aaa"},
            {"id": "2", "path": "Setlist/pack2.7z", "size": 1000, "md5": "bbb"},
            {"id": "3", "path": "Setlist/pack3.7z", "size": 1000, "md5": "ccc"},
        ]
        tasks, skipped, _ = plan_downloads(files, temp_dir, folder_name="Drive")
        assert len(tasks) == 3
        assert skipped == 0

    def test_case_only_duplicate_archives_deduped(self, temp_dir):
        """Archives differing only in case should be deduped (case-insensitive FS)."""
        files = [
            {"id": "1", "path": "Carol of the Bells/pack.7z", "size": 1000, "md5": "aaa"},
            {"id": "2", "path": "Carol Of The Bells/pack.7z", "size": 1000, "md5": "bbb"},
        ]
        tasks, skipped, _ = plan_downloads(files, temp_dir, folder_name="Drive")
        assert len(tasks) == 1
        assert skipped == 1

    def test_numbered_packs_like_rock_band(self, temp_dir):
        """Realistic scenario: 44 numbered .7z packs in one folder."""
        files = [
            {"id": str(i), "path": f"Beatles/TBRB {i}.7z", "size": 1000, "md5": f"md5_{i}"}
            for i in range(1, 45)
        ]
        tasks, skipped, _ = plan_downloads(files, temp_dir, folder_name="Rock Band")
        assert len(tasks) == 44
        assert skipped == 0


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
