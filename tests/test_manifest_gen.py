"""Tests for manifest_gen.py static sources loading."""

import json
from unittest.mock import patch

import pytest


class TestLoadStaticSources:
    """Tests for load_static_sources() function."""

    @pytest.fixture
    def temp_sources(self, tmp_path):
        """Create a temporary sources.json and patch SOURCES_PATH."""
        sources_file = tmp_path / "sources.json"

        def write_sources(data):
            sources_file.write_text(json.dumps(data))

        with patch("manifest_gen.SOURCES_PATH", sources_file):
            yield write_sources, sources_file

    def test_empty_sources_file_returns_empty_list(self, temp_sources):
        """No sources.json returns empty list."""
        from manifest_gen import load_static_sources

        # Don't write file - it doesn't exist, fixture patches path
        _, _ = temp_sources  # Use fixture to apply patch
        result = load_static_sources()
        assert result == []

    def test_parse_cdn_url_sources(self, temp_sources):
        """CDN sources with URLs are parsed correctly."""
        from manifest_gen import load_static_sources

        write_sources, _ = temp_sources
        write_sources({
            "types": [{
                "name": "Official",
                "groups": [{
                    "id": "test-group",
                    "name": "Test Group",
                    "setlists": [{
                        "id": "setlist1",
                        "name": "My Setlist",
                        "size": 12345,
                        "md5": "abc123",
                        "chart_count": 50,
                        "source": {
                            "type": "cdn_url",
                            "url": "https://cdn.example.com/files/archive.rar"
                        }
                    }]
                }]
            }]
        })

        result = load_static_sources()
        assert len(result) == 1
        folder = result[0]
        assert folder.name == "Test Group"
        assert len(folder.files) == 1
        assert folder.files[0]["url"] == "https://cdn.example.com/files/archive.rar"
        assert folder.files[0]["id"] == "cdn-test-group-setlist1"
        assert folder.files[0]["size"] == 12345
        assert folder.files[0]["md5"] == "abc123"

    def test_parse_gdrive_file_sources(self, temp_sources):
        """GDrive file sources are handled correctly."""
        from manifest_gen import load_static_sources

        write_sources, _ = temp_sources
        write_sources({
            "types": [{
                "name": "Official",
                "groups": [{
                    "id": "gdrive-group",
                    "name": "GDrive Group",
                    "setlists": [{
                        "name": "GDrive Setlist",
                        "size": 9999,
                        "md5": "def456",
                        "chart_count": 25,
                        "source": {
                            "type": "gdrive_file",
                            "file_id": "1abc123xyz"
                        }
                    }]
                }]
            }]
        })

        result = load_static_sources()
        assert len(result) == 1
        folder = result[0]
        assert folder.files[0]["id"] == "1abc123xyz"
        assert folder.files[0]["path"] == "GDrive Group/GDrive Setlist.7z"
        assert "url" not in folder.files[0]

    def test_skip_gdrive_folder_sources(self, temp_sources):
        """gdrive_folder type sources are skipped gracefully."""
        from manifest_gen import load_static_sources

        write_sources, _ = temp_sources
        write_sources({
            "types": [{
                "name": "Official",
                "groups": [{
                    "id": "folder-group",
                    "name": "Folder Group",
                    "setlists": [{
                        "name": "Folder Setlist",
                        "size": 5000,
                        "source": {
                            "type": "gdrive_folder",
                            "folder_id": "folder123"
                        }
                    }]
                }]
            }]
        })

        result = load_static_sources()
        # Entire group skipped because only setlist was a folder type
        assert len(result) == 0

    def test_skip_dynamic_sources(self, temp_sources):
        """Groups with setlists='discover' are skipped."""
        from manifest_gen import load_static_sources

        write_sources, _ = temp_sources
        write_sources({
            "types": [{
                "name": "Official",
                "groups": [{
                    "id": "dynamic-group",
                    "name": "Dynamic Group",
                    "setlists": "discover"
                }]
            }]
        })

        result = load_static_sources()
        assert len(result) == 0

    def test_extract_extension_with_query_params(self, temp_sources):
        """URL extension extracted correctly when query params present."""
        from manifest_gen import load_static_sources

        write_sources, _ = temp_sources
        write_sources({
            "types": [{
                "name": "Test",
                "groups": [{
                    "id": "g1",
                    "name": "Group",
                    "setlists": [{
                        "id": "s1",
                        "name": "Setlist",
                        "size": 100,
                        "source": {
                            "type": "cdn_url",
                            "url": "https://cdn.example.com/file.7z?token=abc&expires=123"
                        }
                    }]
                }]
            }]
        })

        result = load_static_sources()
        assert result[0].files[0]["name"] == "Setlist.7z"

    def test_extract_extension_with_fragment(self, temp_sources):
        """URL extension extracted correctly when fragment present."""
        from manifest_gen import load_static_sources

        write_sources, _ = temp_sources
        write_sources({
            "types": [{
                "name": "Test",
                "groups": [{
                    "id": "g1",
                    "name": "Group",
                    "setlists": [{
                        "id": "s1",
                        "name": "Setlist",
                        "size": 100,
                        "source": {
                            "type": "cdn_url",
                            "url": "https://cdn.example.com/file.rar#section"
                        }
                    }]
                }]
            }]
        })

        result = load_static_sources()
        # Fragment should be stripped, only .rar extension extracted
        assert result[0].files[0]["name"] == "Setlist.rar"

    def test_default_extension_fallback(self, temp_sources):
        """URLs without extension default to .rar."""
        from manifest_gen import load_static_sources

        write_sources, _ = temp_sources
        write_sources({
            "types": [{
                "name": "Test",
                "groups": [{
                    "id": "g1",
                    "name": "Group",
                    "setlists": [{
                        "id": "s1",
                        "name": "Setlist",
                        "size": 100,
                        "source": {
                            "type": "cdn_url",
                            "url": "https://cdn.example.com/download/12345"
                        }
                    }]
                }]
            }]
        })

        result = load_static_sources()
        assert result[0].files[0]["name"] == "Setlist.rar"

    def test_unique_file_ids_for_cdn_sources(self, temp_sources):
        """Synthetic IDs should be unique even for setlists without explicit id."""
        from manifest_gen import load_static_sources

        write_sources, _ = temp_sources
        write_sources({
            "types": [{
                "name": "Test",
                "groups": [{
                    "id": "group1",
                    "name": "Group",
                    "setlists": [
                        {
                            "name": "Setlist A",
                            "size": 100,
                            "source": {"type": "cdn_url", "url": "https://cdn.example.com/a.rar"}
                        },
                        {
                            "name": "Setlist B",
                            "size": 200,
                            "source": {"type": "cdn_url", "url": "https://cdn.example.com/b.rar"}
                        }
                    ]
                }]
            }]
        })

        result = load_static_sources()
        ids = [f["id"] for f in result[0].files]
        # IDs should be unique - uses index fallback when no explicit id
        assert len(ids) == len(set(ids)), f"IDs should be unique, got: {ids}"
        # Verify the fallback format uses index
        assert "idx0" in ids[0]
        assert "idx1" in ids[1]

    def test_chart_count_aggregation(self, temp_sources):
        """Total chart count calculated correctly across setlists."""
        from manifest_gen import load_static_sources

        write_sources, _ = temp_sources
        write_sources({
            "types": [{
                "name": "Test",
                "groups": [{
                    "id": "g1",
                    "name": "Group",
                    "setlists": [
                        {
                            "id": "s1",
                            "name": "Setlist 1",
                            "size": 100,
                            "chart_count": 50,
                            "source": {"type": "cdn_url", "url": "https://x.com/a.rar"}
                        },
                        {
                            "id": "s2",
                            "name": "Setlist 2",
                            "size": 200,
                            "chart_count": 75,
                            "source": {"type": "cdn_url", "url": "https://x.com/b.rar"}
                        }
                    ]
                }]
            }]
        })

        result = load_static_sources()
        assert result[0].chart_count == 125
        assert result[0].total_size == 300

    def test_invalid_json_handling(self, temp_sources):
        """Malformed sources.json raises appropriate error."""
        from manifest_gen import load_static_sources

        _, sources_file = temp_sources
        sources_file.write_text("{ invalid json }")

        with pytest.raises(json.JSONDecodeError):
            load_static_sources()

    def test_missing_required_fields_gracefully_handled(self, temp_sources):
        """Incomplete entries are skipped without crashing."""
        from manifest_gen import load_static_sources

        write_sources, _ = temp_sources
        write_sources({
            "types": [{
                "name": "Test",
                "groups": [{
                    "id": "g1",
                    "name": "Group",
                    "setlists": [
                        # Missing source entirely
                        {"name": "Bad Setlist", "size": 100},
                        # Good setlist
                        {
                            "id": "good",
                            "name": "Good Setlist",
                            "size": 200,
                            "source": {"type": "cdn_url", "url": "https://x.com/a.rar"}
                        }
                    ]
                }]
            }]
        })

        result = load_static_sources()
        # Should have processed the good setlist, skipped the bad one
        assert len(result) == 1
        assert len(result[0].files) == 1
        assert result[0].files[0]["name"] == "Good Setlist.rar"

    def test_multiple_groups_creates_multiple_folder_entries(self, temp_sources):
        """Each group becomes its own FolderEntry."""
        from manifest_gen import load_static_sources

        write_sources, _ = temp_sources
        write_sources({
            "types": [{
                "name": "Test",
                "groups": [
                    {
                        "id": "g1",
                        "name": "Group 1",
                        "setlists": [{
                            "id": "s1",
                            "name": "S1",
                            "size": 100,
                            "source": {"type": "cdn_url", "url": "https://x.com/1.rar"}
                        }]
                    },
                    {
                        "id": "g2",
                        "name": "Group 2",
                        "setlists": [{
                            "id": "s2",
                            "name": "S2",
                            "size": 200,
                            "source": {"type": "cdn_url", "url": "https://x.com/2.rar"}
                        }]
                    }
                ]
            }]
        })

        result = load_static_sources()
        assert len(result) == 2
        names = {f.name for f in result}
        assert names == {"Group 1", "Group 2"}
