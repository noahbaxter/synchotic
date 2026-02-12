"""
Cache invalidation scoping tests.

Tests that cache operations are properly scoped — invalidating folder A
doesn't blow away folder B's cache. 7+ fix commits for cache invalidation bugs.
"""

import tempfile
from pathlib import Path
from unittest.mock import patch

from src.sync.cache import (
    PersistentStatsCache,
    CachedSetlistStats,
    CachedFolderStats,
)


def make_setlist_stats(**overrides):
    defaults = dict(
        total_charts=10,
        total_size=10000,
        synced_charts=5,
        synced_size=5000,
        disk_files=20,
        disk_size=8000,
        disk_charts=5,
        purgeable_files=0,
        purgeable_size=0,
        purgeable_charts=0,
    )
    defaults.update(overrides)
    return CachedSetlistStats(**defaults)


class TestPerSetlistInvalidation:
    """Invalidating one setlist doesn't affect others."""

    def test_invalidate_setlist_scoped(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(PersistentStatsCache, '_load'):
                cache = PersistentStatsCache.__new__(PersistentStatsCache)
                cache._cache = {}
                cache._setlist_cache = {}
                cache._dirty = False
                cache._path = Path(tmpdir) / "stats.json"

            folder_id = "drive1"
            cache.set_setlist(folder_id, "SetlistA", make_setlist_stats(total_charts=10))
            cache.set_setlist(folder_id, "SetlistB", make_setlist_stats(total_charts=20))
            cache.set_setlist(folder_id, "SetlistC", make_setlist_stats(total_charts=30))

            # Invalidate only A
            cache.invalidate_setlist(folder_id, "SetlistA")

            assert cache.get_setlist(folder_id, "SetlistA") is None
            assert cache.get_setlist(folder_id, "SetlistB") is not None
            assert cache.get_setlist(folder_id, "SetlistB").total_charts == 20
            assert cache.get_setlist(folder_id, "SetlistC") is not None
            assert cache.get_setlist(folder_id, "SetlistC").total_charts == 30


class TestPerFolderInvalidation:
    """Invalidating one folder doesn't affect another."""

    def test_invalidate_folder_scoped(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(PersistentStatsCache, '_load'):
                cache = PersistentStatsCache.__new__(PersistentStatsCache)
                cache._cache = {}
                cache._setlist_cache = {}
                cache._dirty = False
                cache._path = Path(tmpdir) / "stats.json"

            cache.set_setlist("driveX", "SetlistX", make_setlist_stats(total_charts=10))
            cache.set_setlist("driveY", "SetlistY", make_setlist_stats(total_charts=20))

            # Invalidate driveX
            cache.invalidate("driveX")

            assert cache.get_setlist("driveX", "SetlistX") is None
            assert cache.get_setlist("driveY", "SetlistY") is not None
            assert cache.get_setlist("driveY", "SetlistY").total_charts == 20


class TestFullInvalidation:
    """invalidate_all clears everything."""

    def test_invalidate_all(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(PersistentStatsCache, '_load'):
                cache = PersistentStatsCache.__new__(PersistentStatsCache)
                cache._cache = {}
                cache._setlist_cache = {}
                cache._dirty = False
                cache._path = Path(tmpdir) / "stats.json"

            cache.set_setlist("drive1", "A", make_setlist_stats())
            cache.set_setlist("drive2", "B", make_setlist_stats())
            cache.set_setlist("drive3", "C", make_setlist_stats())

            cache.invalidate_all()

            assert cache.get_setlist("drive1", "A") is None
            assert cache.get_setlist("drive2", "B") is None
            assert cache.get_setlist("drive3", "C") is None


class TestCacheSetGetRoundTrip:
    """set_setlist then get_setlist returns same data."""

    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(PersistentStatsCache, '_load'):
                cache = PersistentStatsCache.__new__(PersistentStatsCache)
                cache._cache = {}
                cache._setlist_cache = {}
                cache._dirty = False
                cache._path = Path(tmpdir) / "stats.json"

            original = make_setlist_stats(
                total_charts=42,
                synced_charts=21,
                total_size=99999,
                synced_size=50000,
                disk_files=100,
                disk_size=75000,
            )
            cache.set_setlist("drive1", "MySetlist", original)

            retrieved = cache.get_setlist("drive1", "MySetlist")
            assert retrieved is not None
            assert retrieved.total_charts == 42
            assert retrieved.synced_charts == 21
            assert retrieved.total_size == 99999
            assert retrieved.synced_size == 50000
            assert retrieved.disk_files == 100
            assert retrieved.disk_size == 75000


class TestSyncInvalidatesOnlyAffectedSetlist:
    """After sync, only the affected setlist cache is invalidated."""

    def test_sync_scoped_invalidation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(PersistentStatsCache, '_load'):
                cache = PersistentStatsCache.__new__(PersistentStatsCache)
                cache._cache = {}
                cache._setlist_cache = {}
                cache._dirty = False
                cache._path = Path(tmpdir) / "stats.json"

            folder_id = "drive1"
            cache.set_setlist(folder_id, "SyncedSetlist", make_setlist_stats(synced_charts=5))
            cache.set_setlist(folder_id, "UntouchedSetlist", make_setlist_stats(synced_charts=10))
            cache.set_setlist(folder_id, "AnotherSetlist", make_setlist_stats(synced_charts=15))

            # Simulate sync completing for SyncedSetlist — only invalidate that one
            cache.invalidate_setlist(folder_id, "SyncedSetlist")

            assert cache.get_setlist(folder_id, "SyncedSetlist") is None
            assert cache.get_setlist(folder_id, "UntouchedSetlist").synced_charts == 10
            assert cache.get_setlist(folder_id, "AnotherSetlist").synced_charts == 15


class TestPurgeInvalidatesOnlyAffectedSetlists:
    """After purge, only setlists with purged files are invalidated."""

    def test_purge_scoped_invalidation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(PersistentStatsCache, '_load'):
                cache = PersistentStatsCache.__new__(PersistentStatsCache)
                cache._cache = {}
                cache._setlist_cache = {}
                cache._dirty = False
                cache._path = Path(tmpdir) / "stats.json"

            folder_id = "drive1"
            cache.set_setlist(folder_id, "PurgedSetlistA", make_setlist_stats(disk_files=50))
            cache.set_setlist(folder_id, "PurgedSetlistB", make_setlist_stats(disk_files=30))
            cache.set_setlist(folder_id, "SafeSetlist", make_setlist_stats(disk_files=100))

            # Simulate purge affecting two setlists
            affected = ["PurgedSetlistA", "PurgedSetlistB"]
            for name in affected:
                cache.invalidate_setlist(folder_id, name)

            assert cache.get_setlist(folder_id, "PurgedSetlistA") is None
            assert cache.get_setlist(folder_id, "PurgedSetlistB") is None
            assert cache.get_setlist(folder_id, "SafeSetlist").disk_files == 100


class TestSettingsHashCacheMiss:
    """Cache set with hash "abc", get with hash "def" returns None."""

    def test_settings_hash_mismatch(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(PersistentStatsCache, '_load'):
                cache = PersistentStatsCache.__new__(PersistentStatsCache)
                cache._cache = {}
                cache._setlist_cache = {}
                cache._dirty = False
                cache._path = Path(tmpdir) / "stats.json"

            # The legacy folder-level cache uses settings_hash
            folder_stats = CachedFolderStats(
                total_charts=10, synced_charts=5,
                total_size=10000, synced_size=5000,
                purge_count=0, purge_charts=0, purge_size=0,
                enabled_setlists=3, total_setlists=5,
                settings_hash="abc",
            )
            cache.set("drive1", folder_stats)

            # Same hash → hit
            assert cache.get("drive1", "abc") is not None

            # Different hash → miss
            assert cache.get("drive1", "def") is None
