"""Tests for manifest_gen.py static sources loading."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest


class TestLoadStaticSources:
    """Tests for load_static_sources() function."""

    @pytest.fixture
    def temp_sources_dir(self, tmp_path):
        """Create a temporary sources/ directory and patch STATIC_SOURCES_DIR."""
        sources_dir = tmp_path / "sources"
        sources_dir.mkdir()

        with patch("manifest_gen.STATIC_SOURCES_DIR", sources_dir):
            yield sources_dir

    def test_empty_sources_dir_returns_empty_list(self, temp_sources_dir):
        """Empty sources/ directory returns empty list."""
        from manifest_gen import load_static_sources
        result = load_static_sources()
        assert result == []

    def test_missing_sources_dir_returns_empty_list(self, tmp_path):
        """Non-existent sources/ directory returns empty list."""
        from manifest_gen import load_static_sources

        with patch("manifest_gen.STATIC_SOURCES_DIR", tmp_path / "nonexistent"):
            result = load_static_sources()
        assert result == []

    def test_parse_static_source_json(self, temp_sources_dir):
        """Static source JSON files are parsed correctly."""
        from manifest_gen import load_static_sources

        # Create a source file
        collection_dir = temp_sources_dir / "Test Collection"
        collection_dir.mkdir()
        (collection_dir / "Test Setlist.json").write_text(json.dumps({
            "name": "Test Setlist",
            "folder_id": "static-test",
            "group": "Games",
            "collection": "Test Collection",
            "chart_count": 50,
            "total_size": 12345,
            "file_count": 1,
            "files": [{
                "id": "abc123",
                "path": "Test Setlist/Test Setlist.7z",
                "name": "Test Setlist.7z",
                "size": 12345,
                "md5": "deadbeef"
            }]
        }))

        result = load_static_sources()
        assert len(result) == 1
        folder = result[0]
        assert folder.name == "Test Setlist"
        assert folder.folder_id == "static-test"
        assert folder.group == "Games"
        assert folder.collection == "Test Collection"
        assert folder.chart_count == 50
        assert folder.total_size == 12345
        assert len(folder.files) == 1
        assert folder.files[0]["id"] == "abc123"

    def test_cdn_url_source(self, temp_sources_dir):
        """CDN sources with URLs are parsed correctly."""
        from manifest_gen import load_static_sources

        collection_dir = temp_sources_dir / "CSC"
        collection_dir.mkdir()
        (collection_dir / "CTH.json").write_text(json.dumps({
            "name": "Carpal Tunnel Hero",
            "folder_id": "static-cth",
            "group": "Community",
            "collection": "CSC",
            "chart_count": 100,
            "total_size": 1000000,
            "file_count": 1,
            "files": [{
                "id": "cdn-csc-cth",
                "path": "CTH/CTH.rar",
                "name": "CTH.rar",
                "size": 1000000,
                "md5": "abc123",
                "url": "https://cdn.example.com/cth.rar"
            }]
        }))

        result = load_static_sources()
        assert len(result) == 1
        assert result[0].files[0]["url"] == "https://cdn.example.com/cth.rar"

    def test_group_collection_from_json(self, temp_sources_dir):
        """Group and collection are read from JSON."""
        from manifest_gen import load_static_sources

        collection_dir = temp_sources_dir / "Whatever"
        collection_dir.mkdir()
        (collection_dir / "Test.json").write_text(json.dumps({
            "name": "Test",
            "group": "CustomGroup",
            "collection": "CustomCollection",
            "files": []
        }))

        result = load_static_sources()
        assert result[0].group == "CustomGroup"
        assert result[0].collection == "CustomCollection"

    def test_collection_fallback_to_parent_folder(self, temp_sources_dir):
        """Collection falls back to parent folder name if not in JSON."""
        from manifest_gen import load_static_sources

        collection_dir = temp_sources_dir / "Guitar Hero"
        collection_dir.mkdir()
        (collection_dir / "GH1.json").write_text(json.dumps({
            "name": "GH1",
            "group": "Games",
            "files": []
        }))

        result = load_static_sources()
        assert result[0].collection == "Guitar Hero"

    def test_folder_id_fallback(self, temp_sources_dir):
        """folder_id falls back to static-{filename} if not in JSON."""
        from manifest_gen import load_static_sources

        collection_dir = temp_sources_dir / "Test"
        collection_dir.mkdir()
        (collection_dir / "MySetlist.json").write_text(json.dumps({
            "name": "My Setlist",
            "files": []
        }))

        result = load_static_sources()
        assert result[0].folder_id == "static-MySetlist"

    def test_multiple_collections(self, temp_sources_dir):
        """Multiple collections with multiple setlists work."""
        from manifest_gen import load_static_sources

        # Create Guitar Hero collection
        gh_dir = temp_sources_dir / "Guitar Hero"
        gh_dir.mkdir()
        (gh_dir / "GH1.json").write_text(json.dumps({
            "name": "GH1", "group": "Games", "files": []
        }))
        (gh_dir / "GH2.json").write_text(json.dumps({
            "name": "GH2", "group": "Games", "files": []
        }))

        # Create CSC collection
        csc_dir = temp_sources_dir / "CSC"
        csc_dir.mkdir()
        (csc_dir / "CTH.json").write_text(json.dumps({
            "name": "CTH", "group": "Community", "files": []
        }))

        result = load_static_sources()
        assert len(result) == 3
        names = {f.name for f in result}
        assert names == {"GH1", "GH2", "CTH"}

    def test_malformed_json_skipped_with_warning(self, temp_sources_dir, capsys):
        """Malformed JSON files are skipped with warning."""
        from manifest_gen import load_static_sources

        collection_dir = temp_sources_dir / "Test"
        collection_dir.mkdir()
        (collection_dir / "bad.json").write_text("{ invalid json }")
        (collection_dir / "good.json").write_text(json.dumps({
            "name": "Good", "files": []
        }))

        result = load_static_sources()
        assert len(result) == 1
        assert result[0].name == "Good"

        captured = capsys.readouterr()
        assert "Warning" in captured.out
        assert "bad.json" in captured.out

    def test_missing_name_raises_error(self, temp_sources_dir):
        """Missing 'name' field causes file to be skipped."""
        from manifest_gen import load_static_sources

        collection_dir = temp_sources_dir / "Test"
        collection_dir.mkdir()
        (collection_dir / "noname.json").write_text(json.dumps({
            "files": []
        }))

        result = load_static_sources()
        assert len(result) == 0

    def test_file_count_from_files_array(self, temp_sources_dir):
        """file_count defaults to len(files) if not specified."""
        from manifest_gen import load_static_sources

        collection_dir = temp_sources_dir / "Test"
        collection_dir.mkdir()
        (collection_dir / "test.json").write_text(json.dumps({
            "name": "Test",
            "files": [
                {"id": "1", "path": "a", "name": "a", "size": 100},
                {"id": "2", "path": "b", "name": "b", "size": 200},
            ]
        }))

        result = load_static_sources()
        assert result[0].file_count == 2

    def test_sorted_output(self, temp_sources_dir):
        """Output is sorted by file path."""
        from manifest_gen import load_static_sources

        collection_dir = temp_sources_dir / "Test"
        collection_dir.mkdir()
        # Create files in reverse alphabetical order
        (collection_dir / "Z.json").write_text(json.dumps({"name": "Z", "files": []}))
        (collection_dir / "A.json").write_text(json.dumps({"name": "A", "files": []}))
        (collection_dir / "M.json").write_text(json.dumps({"name": "M", "files": []}))

        result = load_static_sources()
        names = [f.name for f in result]
        assert names == ["A", "M", "Z"]
