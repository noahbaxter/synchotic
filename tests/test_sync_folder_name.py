"""Tests for get_sync_folder_name() helper."""

import pytest
from src.sync.utils import get_sync_folder_name


class TestGetSyncFolderName:
    """Test collection-based folder naming for static sources."""

    def test_static_source_uses_collection(self):
        """Static sources (with collection) should use collection as folder_name."""
        folder = {
            "name": "(2007) Rock Band 1",
            "collection": "Rock Band",
            "folder_id": "static-xxx",
        }
        assert get_sync_folder_name(folder) == "Rock Band"

    def test_static_source_guitar_hero(self):
        """Guitar Hero static sources use Guitar Hero collection."""
        folder = {
            "name": "(2005) Guitar Hero",
            "collection": "Guitar Hero",
            "folder_id": "static-xxx",
        }
        assert get_sync_folder_name(folder) == "Guitar Hero"

    def test_scan_source_uses_name(self):
        """Scan sources (no collection) should use name as folder_name."""
        folder = {
            "name": "BirdmanExe Drive",
            "folder_id": "1OTcP60...",
        }
        assert get_sync_folder_name(folder) == "BirdmanExe Drive"

    def test_scan_source_with_empty_collection(self):
        """Empty collection string should fall back to name."""
        folder = {
            "name": "Some Drive",
            "collection": "",
            "folder_id": "xxx",
        }
        assert get_sync_folder_name(folder) == "Some Drive"

    def test_missing_name_returns_empty(self):
        """Missing name should return empty string."""
        folder = {"folder_id": "xxx"}
        assert get_sync_folder_name(folder) == ""

    def test_collection_takes_precedence(self):
        """Collection should always take precedence over name when present."""
        folder = {
            "name": "Specific Source Name",
            "collection": "Parent Collection",
        }
        assert get_sync_folder_name(folder) == "Parent Collection"
