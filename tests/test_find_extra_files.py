"""
Tests for find_extra_files.

Verifies that files tracked in marker_files or manifest aren't flagged as purgeable.
"""

import tempfile
from pathlib import Path

import pytest

from src.core.formatting import normalize_path_key
from src.sync import clear_cache
from src.sync.purge_planner import find_extra_files
from src.sync.cache import scan_local_files

# Backwards compat
_scan_local_files = scan_local_files
clear_scan_cache = clear_cache


class TestSyncStateExtraFiles:
    """Tests for marker_files-based extra file detection."""

    @pytest.fixture
    def temp_dir(self):
        clear_scan_cache()  # Ensure clean state
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_tracked_files_not_flagged_as_extra(self, temp_dir):
        """
        Files tracked in marker_files should not be flagged as extra.
        """
        folder_name = "TestDrive"
        folder_path = temp_dir / folder_name
        chart_folder = folder_path / "Setlist" / "SomeChart"
        chart_folder.mkdir(parents=True)

        # Create files on disk
        (chart_folder / "song.ini").write_text("[song]\nname=Test")
        (chart_folder / "notes.mid").write_bytes(b"midi data")
        (chart_folder / "song.ogg").write_bytes(b"audio data")

        # Build marker_files with normalized paths (relative to folder_path, no drive prefix)
        marker_files = {
            normalize_path_key("Setlist/SomeChart/song.ini"),
            normalize_path_key("Setlist/SomeChart/notes.mid"),
            normalize_path_key("Setlist/SomeChart/song.ogg"),
        }

        # Find extra files (no manifest paths)
        extras = find_extra_files(folder_name, folder_path, marker_files, set())

        # Assert: tracked files should NOT be flagged as extra
        extra_names = [f.name for f, _ in extras]
        assert "song.ini" not in extra_names, "song.ini was incorrectly flagged as extra"
        assert "notes.mid" not in extra_names, "notes.mid was incorrectly flagged as extra"
        assert "song.ogg" not in extra_names, "song.ogg was incorrectly flagged as extra"

    def test_untracked_files_flagged_as_extra(self, temp_dir):
        """Files not in marker_files or manifest should be flagged as extra."""
        folder_name = "TestDrive"
        folder_path = temp_dir / folder_name
        chart_folder = folder_path / "Setlist" / "SomeChart"
        chart_folder.mkdir(parents=True)

        # Create files on disk
        (chart_folder / "song.ini").write_text("[song]\nname=Test")
        (chart_folder / "extra_file.txt").write_text("not tracked")

        # Only song.ini is tracked (relative to folder_path, no drive prefix)
        marker_files = {
            normalize_path_key("Setlist/SomeChart/song.ini"),
        }

        extras = find_extra_files(folder_name, folder_path, marker_files, set())

        extra_names = [f.name for f, _ in extras]
        assert "extra_file.txt" in extra_names, "Untracked file should be flagged"
        assert "song.ini" not in extra_names, "Tracked file should not be flagged"

    def test_empty_marker_files_flags_all_files_without_manifest(self, temp_dir):
        """With empty marker_files and no manifest, all files should be flagged as extra."""
        folder_name = "TestDrive"
        folder_path = temp_dir / folder_name
        folder_path.mkdir(parents=True)

        # Create files on disk
        (folder_path / "file1.txt").write_text("content1")
        (folder_path / "file2.txt").write_text("content2")

        extras = find_extra_files(folder_name, folder_path, set(), set())

        assert len(extras) == 2, "All files should be extras with empty marker_files and no manifest"

    def test_manifest_paths_protect_files(self, temp_dir):
        """Files in manifest should not be flagged as extra even without marker_files."""
        folder_name = "TestDrive"
        folder_path = temp_dir / folder_name
        folder_path.mkdir(parents=True)

        # Create files on disk
        (folder_path / "in_manifest.txt").write_text("content1")
        (folder_path / "not_in_manifest.txt").write_text("content2")

        manifest_paths = {normalize_path_key(f"{folder_name}/in_manifest.txt")}
        extras = find_extra_files(folder_name, folder_path, set(), manifest_paths)

        extra_names = [f.name for f, _ in extras]
        assert "in_manifest.txt" not in extra_names, "Manifest file should be protected"
        assert "not_in_manifest.txt" in extra_names, "Non-manifest file should be flagged"

    def test_no_marker_files_with_manifest(self, temp_dir):
        """With empty marker_files, manifest paths should still protect files."""
        folder_name = "TestDrive"
        folder_path = temp_dir / folder_name
        folder_path.mkdir(parents=True)

        # Create files on disk
        (folder_path / "protected.txt").write_text("protected")
        (folder_path / "extra.txt").write_text("extra")

        manifest_paths = {normalize_path_key(f"{folder_name}/protected.txt")}
        extras = find_extra_files(folder_name, folder_path, set(), manifest_paths)

        extra_names = [f.name for f, _ in extras]
        assert len(extras) == 1
        assert "extra.txt" in extra_names

    def test_case_insensitive_marker_files_matching(self, temp_dir):
        """
        Files should match marker_files entries regardless of case.

        This prevents case mismatches (e.g., "And" vs "and") from causing
        files to be incorrectly flagged as extra on case-insensitive filesystems.
        """
        folder_name = "TestDrive"
        folder_path = temp_dir / folder_name
        chart_folder = folder_path / "Setlist" / "Song Name"
        chart_folder.mkdir(parents=True)

        # Create file on disk with one casing
        (chart_folder / "song.ini").write_text("[song]\nname=Test")

        # Track with DIFFERENT casing in path (normalize_path_key lowercases)
        marker_files = {
            normalize_path_key("Setlist/SONG NAME/song.ini"),
        }

        extras = find_extra_files(folder_name, folder_path, marker_files, set())

        # File should NOT be flagged as extra despite case mismatch
        extra_names = [f.name for f, _ in extras]
        assert "song.ini" not in extra_names, "Case mismatch should not flag file as extra"

    def test_case_insensitive_manifest_matching(self, temp_dir):
        """
        Files should match manifest paths regardless of case.
        """
        folder_name = "TestDrive"
        folder_path = temp_dir / folder_name
        folder_path.mkdir(parents=True)

        # Create file on disk with lowercase
        (folder_path / "myfile.txt").write_text("content")

        # Manifest has UPPERCASE (normalized for case-insensitive matching)
        manifest_paths = {normalize_path_key(f"{folder_name}/MYFILE.TXT")}

        extras = find_extra_files(folder_name, folder_path, set(), manifest_paths)

        # File should NOT be flagged as extra
        assert len(extras) == 0, "Case mismatch should not flag file as extra"


    def test_drive_prefix_fallback_protects_files(self, temp_dir):
        """
        Files should be protected when markers store paths WITH drive prefix.

        This covers the Windows bug where markers store "DriveName/Setlist/file"
        but find_extra_files checks without the prefix first. The fallback
        should catch the prefixed form.
        """
        folder_name = "TestDrive"
        folder_path = temp_dir / folder_name
        chart_folder = folder_path / "Setlist" / "SomeChart"
        chart_folder.mkdir(parents=True)

        (chart_folder / "song.ini").write_text("[song]\nname=Test")
        (chart_folder / "notes.mid").write_bytes(b"midi data")

        # Markers store WITH drive prefix (the mismatch scenario)
        marker_files = {
            normalize_path_key("TestDrive/Setlist/SomeChart/song.ini"),
            normalize_path_key("TestDrive/Setlist/SomeChart/notes.mid"),
        }

        extras = find_extra_files(folder_name, folder_path, marker_files, set())

        extra_names = [f.name for f, _ in extras]
        assert "song.ini" not in extra_names, "Prefixed marker should protect file via fallback"
        assert "notes.mid" not in extra_names, "Prefixed marker should protect file via fallback"
        assert len(extras) == 0


class TestFindExtraFilesWithCache:
    """Tests for find_extra_files when passed pre-scanned local_files."""

    @pytest.fixture
    def temp_dir(self):
        clear_scan_cache()
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_with_explicit_local_files_param(self, temp_dir):
        """find_extra_files should work correctly when passed cached local_files."""
        folder_name = "TestDrive"
        folder_path = temp_dir / folder_name
        folder_path.mkdir()

        # Create expected and extra files
        (folder_path / "expected.txt").write_text("expected")
        (folder_path / "extra.txt").write_text("extra")

        # Track expected.txt in marker_files (relative to folder_path, no drive prefix)
        marker_files = {
            normalize_path_key("expected.txt"),
        }

        # Pre-scan and pass explicitly (the optimized path)
        local_files = _scan_local_files(folder_path)
        extras = find_extra_files(folder_name, folder_path, marker_files, set(), local_files)

        assert len(extras) == 1
        assert extras[0][0].name == "extra.txt"

    def test_empty_folder_returns_empty(self, temp_dir):
        """Empty folder should return no extras, not crash."""
        folder_name = "EmptyDrive"
        folder_path = temp_dir / folder_name
        folder_path.mkdir()

        extras = find_extra_files(folder_name, folder_path, set(), set())
        assert extras == []

    def test_nonexistent_folder_returns_empty(self, temp_dir):
        """Non-existent folder should return no extras, not crash."""
        folder_name = "DoesNotExist"
        folder_path = temp_dir / folder_name

        extras = find_extra_files(folder_name, folder_path, set(), set())
        assert extras == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
