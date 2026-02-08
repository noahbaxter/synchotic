"""
Tests for path sanitization across the pipeline.

Verifies that Drive names with illegal characters (colons, angle brackets, etc.)
are sanitized consistently at every boundary: scanner, changes API, disabled
setlist filtering, download planning, purge planning, and cache operations.
"""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.core.formatting import (
    escape_name_slashes,
    sanitize_drive_name,
    sanitize_filename,
    sanitize_path,
)
from src.sync.cache import ScanCache, scan_actual_charts
from src.sync.download_planner import plan_downloads
from src.sync.status import _file_in_disabled_setlist, get_sync_status


# Common test names with illegal Windows characters
COLON_NAME = "Guitar Hero III: Legends of Rock"
COLON_SANITIZED = "Guitar Hero III - Legends of Rock"
MULTI_ILLEGAL = 'Best of <2007> "Hits": Vol|1'
MULTI_SANITIZED = "Best of -2007- 'Hits' - Vol-1"
SLASH_NAME = "AC/DC Greatest Hits"
SLASH_SANITIZED = "AC--DC Greatest Hits"


class TestSanitizeDriveName:
    """Tests for the sanitize_drive_name wrapper."""

    def test_colon_replaced(self):
        assert sanitize_drive_name(COLON_NAME) == COLON_SANITIZED

    def test_multiple_illegal_chars(self):
        assert sanitize_drive_name(MULTI_ILLEGAL) == MULTI_SANITIZED

    def test_slash_in_name_double_escaped(self):
        """Slash in a name becomes '--' (escaped then sanitized)."""
        assert sanitize_drive_name(SLASH_NAME) == SLASH_SANITIZED

    def test_matches_scanner_pattern(self):
        """sanitize_drive_name produces same result as old two-step pattern."""
        for name in [COLON_NAME, MULTI_ILLEGAL, SLASH_NAME, "Normal Name", ""]:
            expected = sanitize_filename(escape_name_slashes(name))
            assert sanitize_drive_name(name) == expected

    def test_idempotent(self):
        """Sanitizing an already-sanitized name is a no-op."""
        once = sanitize_drive_name(COLON_NAME)
        twice = sanitize_drive_name(once)
        assert once == twice

    def test_empty_string(self):
        assert sanitize_drive_name("") == ""

    def test_no_illegal_chars_unchanged(self):
        assert sanitize_drive_name("Perfectly Fine Name") == "Perfectly Fine Name"


class TestChangesAPISanitization:
    """Verify the Changes API path builder sanitizes names."""

    def test_changes_path_components_sanitized(self):
        """_get_file_path should produce sanitized path components."""
        from src.drive.changes import ChangeTracker

        mock_client = MagicMock()
        mock_manifest = MagicMock()
        tracker = ChangeTracker(mock_client, mock_manifest)

        root_id = "root_folder"
        file_id = "file_123"
        folder_id = "folder_456"

        # Simulate: file -> folder with colon -> root
        mock_client.get_file_metadata.side_effect = [
            {"name": "song.ini", "parents": [folder_id]},
            {"name": COLON_NAME, "parents": [root_id]},
        ]

        path = tracker._get_file_path(file_id, root_id)
        assert path is not None
        assert ":" not in path
        assert COLON_SANITIZED in path
        assert path == f"{COLON_SANITIZED}/song.ini"


class TestDisabledSetlistFiltering:
    """Disabled setlist names (raw from settings) must match sanitized paths."""

    def test_sanitized_disabled_name_matches_sanitized_path(self):
        """Raw disabled name → sanitize_drive_name → matches manifest path prefix."""
        disabled_raw = {COLON_NAME}
        disabled_sanitized = {sanitize_drive_name(n) for n in disabled_raw}

        manifest_path = f"{COLON_SANITIZED}/subfolder/chart.zip"
        assert _file_in_disabled_setlist(manifest_path, disabled_sanitized)

    def test_unsanitized_disabled_name_would_not_match(self):
        """Without sanitization, raw name doesn't match sanitized path."""
        disabled_raw = {COLON_NAME}
        manifest_path = f"{COLON_SANITIZED}/subfolder/chart.zip"
        assert not _file_in_disabled_setlist(manifest_path, disabled_raw)

    def test_slash_name_disabled_matches_path(self):
        disabled_sanitized = {sanitize_drive_name(SLASH_NAME)}
        manifest_path = f"{SLASH_SANITIZED}/subfolder/chart.zip"
        assert _file_in_disabled_setlist(manifest_path, disabled_sanitized)

    def test_multiple_disabled_setlists(self):
        disabled_raw = {COLON_NAME, MULTI_ILLEGAL, "Normal Setlist"}
        disabled_sanitized = {sanitize_drive_name(n) for n in disabled_raw}

        assert _file_in_disabled_setlist(f"{COLON_SANITIZED}/file.zip", disabled_sanitized)
        assert _file_in_disabled_setlist(f"{MULTI_SANITIZED}/file.zip", disabled_sanitized)
        assert _file_in_disabled_setlist("Normal Setlist/file.zip", disabled_sanitized)
        assert not _file_in_disabled_setlist("Other Setlist/file.zip", disabled_sanitized)


class TestDisabledSetlistAsFilesystemPath:
    """Disabled setlist names used as filesystem paths must be sanitized."""

    def test_sanitized_name_creates_valid_path(self):
        """folder_path / sanitize_drive_name(name) doesn't raise on Windows-illegal chars."""
        base = Path("/tmp/test")
        # This would raise WinError 267 on Windows if unsanitized
        path = base / sanitize_drive_name(COLON_NAME)
        assert ":" not in str(path)
        assert COLON_SANITIZED in str(path)

    def test_scan_actual_charts_with_sanitized_disabled(self, tmp_path):
        """scan_actual_charts works when disabled_setlists are sanitized."""
        # Create a folder structure with a sanitized name
        setlist_dir = tmp_path / COLON_SANITIZED
        chart_dir = setlist_dir / "some_chart"
        chart_dir.mkdir(parents=True)
        (chart_dir / "song.ini").write_text("chart")
        (chart_dir / "notes.mid").write_bytes(b"\x00" * 100)

        # Full scan should find the chart
        count, size = scan_actual_charts(tmp_path, set())
        assert count == 1

        # Disabled with sanitized name should exclude it
        disabled = {sanitize_drive_name(COLON_NAME)}
        count, size = scan_actual_charts(tmp_path, disabled)
        assert count == 0


class TestDownloadPlannerWithSanitizedPaths:
    """Download planner receives pre-sanitized paths from manifest."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_sanitized_paths_create_valid_local_paths(self, temp_dir):
        """Manifest files with sanitized colon paths produce valid download paths."""
        files = [{
            "id": "1",
            "path": f"{COLON_SANITIZED}/chart.zip",
            "size": 1000,
            "md5": "abc123",
        }]
        tasks, skipped, long_paths = plan_downloads(files, temp_dir, delete_videos=True)
        assert len(tasks) == 1
        # Check the relative portion only — full path includes drive letter (C:\) on Windows
        rel_path = str(tasks[0].local_path.relative_to(temp_dir))
        assert ":" not in rel_path

    def test_archive_dedup_with_sanitized_names(self, temp_dir):
        """Two archives normalizing to same sanitized path are deduped."""
        files = [
            {"id": "1", "path": "Setlist/chart.zip", "size": 1000, "md5": "abc", "modified": "2024-01-02"},
            {"id": "2", "path": "Setlist/chart.zip", "size": 1000, "md5": "def", "modified": "2024-01-01"},
        ]
        tasks, skipped, _ = plan_downloads(files, temp_dir, delete_videos=True)
        assert len(tasks) == 1
        assert tasks[0].md5 == "abc"  # Newest kept


class TestScanCacheVersioning:
    """Scan cache rejects old entries without version marker."""

    def test_old_cache_without_version_returns_none(self, tmp_path):
        """Cache entries from before versioning are treated as misses."""
        import json
        from datetime import datetime, timezone

        cache = ScanCache()
        cache._dir = tmp_path

        # Write a v1-style cache entry (no version field)
        old_data = {
            "scanned_at": datetime.now(timezone.utc).isoformat(),
            "files": [{"id": "1", "path": "test"}],
        }
        cache_file = tmp_path / "test_setlist.json"
        with open(cache_file, "w") as f:
            json.dump(old_data, f)

        assert cache.get("test_setlist") is None

    def test_current_version_cache_returned(self, tmp_path):
        """Cache entries with current version are returned."""
        cache = ScanCache()
        cache._dir = tmp_path

        files = [{"id": "1", "path": "test"}]
        cache.set("test_setlist", files)

        result = cache.get("test_setlist")
        assert result is not None
        assert len(result) == 1
        assert result[0]["id"] == "1"


class TestGetSyncStatusWithDisabledSetlists:
    """Integration: get_sync_status filters disabled setlists correctly."""

    def test_disabled_setlist_with_colon_filtered(self, tmp_path):
        """Files in a disabled setlist (raw name has colon) are excluded from status."""
        folders = [{
            "folder_id": "drive1",
            "name": "TestDrive",
            "files": [
                {"id": "1", "path": f"{COLON_SANITIZED}/chart1.zip", "size": 100, "md5": "abc", "modified": "2024-01-01"},
                {"id": "2", "path": "Enabled Setlist/chart2.zip", "size": 200, "md5": "def", "modified": "2024-01-01"},
            ],
        }]

        # Mock user_settings that disables the colon-named setlist
        settings = MagicMock()
        settings.is_drive_enabled.return_value = True
        settings.delete_videos = True
        settings.get_disabled_subfolders.return_value = {COLON_NAME}

        status = get_sync_status(folders, tmp_path, user_settings=settings)

        # Only the enabled setlist's chart should be counted
        assert status.total_charts == 1

    def test_no_disabled_setlists_counts_all(self, tmp_path):
        """With no disabled setlists, all charts are counted."""
        folders = [{
            "folder_id": "drive1",
            "name": "TestDrive",
            "files": [
                {"id": "1", "path": f"{COLON_SANITIZED}/chart1.zip", "size": 100, "md5": "abc", "modified": "2024-01-01"},
                {"id": "2", "path": "Enabled Setlist/chart2.zip", "size": 200, "md5": "def", "modified": "2024-01-01"},
            ],
        }]

        settings = MagicMock()
        settings.is_drive_enabled.return_value = True
        settings.delete_videos = True
        settings.get_disabled_subfolders.return_value = set()

        status = get_sync_status(folders, tmp_path, user_settings=settings)
        assert status.total_charts == 2


class TestEndToEndPathFlow:
    """Full pipeline: Drive name → sanitize → manifest → planner → valid path."""

    def test_colon_name_full_pipeline(self, tmp_path):
        """A Drive name with colon flows correctly through the entire pipeline."""
        # Step 1: Scanner sanitizes the name
        sanitized = sanitize_drive_name(COLON_NAME)
        assert ":" not in sanitized

        # Step 2: Path is built for manifest
        manifest_path = f"{sanitized}/Cool Song/chart.zip"
        assert ":" not in manifest_path

        # Step 3: sanitize_path is idempotent on already-sanitized paths
        re_sanitized = sanitize_path(manifest_path)
        assert re_sanitized == manifest_path

        # Step 4: Download planner creates valid local path
        files = [{"id": "1", "path": manifest_path, "size": 500, "md5": "abc"}]
        tasks, _, _ = plan_downloads(files, tmp_path, delete_videos=True)
        assert len(tasks) == 1
        # Check relative portion only — full path includes drive letter (C:\) on Windows
        rel_path = str(tasks[0].local_path.relative_to(tmp_path))
        assert ":" not in rel_path

        # Step 5: Disabled setlist filtering works
        disabled = {sanitize_drive_name(COLON_NAME)}
        assert _file_in_disabled_setlist(manifest_path, disabled)

    def test_multiple_illegal_chars_pipeline(self, tmp_path):
        """Name with multiple illegal chars flows correctly through pipeline."""
        sanitized = sanitize_drive_name(MULTI_ILLEGAL)
        manifest_path = f"{sanitized}/track.sng"

        files = [{"id": "1", "path": manifest_path, "size": 300, "md5": "xyz"}]
        tasks, _, _ = plan_downloads(files, tmp_path, delete_videos=True)
        assert len(tasks) == 1

        # No illegal chars in the relative path (exclude drive letter C:\ on Windows)
        rel_path = str(tasks[0].local_path.relative_to(tmp_path))
        for char in '<>:"|?*':
            assert char not in rel_path
