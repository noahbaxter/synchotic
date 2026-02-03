"""
Filesystem cache for DM Chart Sync.

Provides cached scanning of local files and chart folders.
Cache is invalidated after downloads/purges.
"""

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from ..stats import clear_local_stats_cache
from ..core.formatting import normalize_fs_name
from ..core.paths import get_data_dir

if TYPE_CHECKING:
    from .status import SyncStatus


@dataclass
class FolderStats:
    """Cached stats for a single folder."""
    folder_id: str
    sync_status: "SyncStatus"
    purge_count: int  # File count
    purge_charts: int  # Estimated chart count
    purge_size: int
    display_string: str | None


class FolderStatsCache:
    """Per-folder stats cache with selective invalidation (in-memory)."""

    def __init__(self):
        self._cache: dict[str, FolderStats] = {}

    def invalidate(self, folder_id: str):
        """Invalidate one folder's stats."""
        self._cache.pop(folder_id, None)

    def invalidate_all(self):
        """Full invalidation (after sync/purge)."""
        self._cache.clear()

    def get(self, folder_id: str) -> FolderStats | None:
        """Get cached stats for a folder, or None if not cached."""
        return self._cache.get(folder_id)

    def set(self, folder_id: str, stats: FolderStats):
        """Store stats for a folder."""
        self._cache[folder_id] = stats


@dataclass
class CachedFolderStats:
    """Persistent stats for a folder, saved to disk."""
    total_charts: int
    synced_charts: int
    total_size: int
    synced_size: int
    purge_count: int
    purge_charts: int
    purge_size: int
    settings_hash: str  # Hash of enabled setlists to detect settings changes


class PersistentStatsCache:
    """
    Persistent folder stats cache stored in .dm-sync/folder_stats.json.

    Caches accurate sync stats after files are loaded, so subsequent startups
    show real values instead of lazy estimates.
    """
    CACHE_FILE = "folder_stats.json"

    def __init__(self):
        self._cache: dict[str, CachedFolderStats] = {}
        self._dirty = False
        self._path = get_data_dir() / self.CACHE_FILE
        self._load()

    def _load(self):
        """Load cache from disk."""
        if not self._path.exists():
            return
        try:
            with open(self._path) as f:
                data = json.load(f)
            for folder_id, entry in data.items():
                self._cache[folder_id] = CachedFolderStats(
                    total_charts=entry.get("total_charts", 0),
                    synced_charts=entry.get("synced_charts", 0),
                    total_size=entry.get("total_size", 0),
                    synced_size=entry.get("synced_size", 0),
                    purge_count=entry.get("purge_count", 0),
                    purge_charts=entry.get("purge_charts", 0),
                    purge_size=entry.get("purge_size", 0),
                    settings_hash=entry.get("settings_hash", ""),
                )
        except (json.JSONDecodeError, OSError):
            self._cache = {}

    def save(self):
        """Save cache to disk (only if dirty)."""
        if not self._dirty:
            return
        data = {}
        for folder_id, stats in self._cache.items():
            data[folder_id] = {
                "total_charts": stats.total_charts,
                "synced_charts": stats.synced_charts,
                "total_size": stats.total_size,
                "synced_size": stats.synced_size,
                "purge_count": stats.purge_count,
                "purge_charts": stats.purge_charts,
                "purge_size": stats.purge_size,
                "settings_hash": stats.settings_hash,
            }
        try:
            with open(self._path, "w") as f:
                json.dump(data, f)
            self._dirty = False
        except OSError:
            pass

    def get(self, folder_id: str, settings_hash: str) -> CachedFolderStats | None:
        """
        Get cached stats for a folder if settings hash matches.

        Returns None if no cache exists or settings have changed.
        """
        cached = self._cache.get(folder_id)
        if cached and cached.settings_hash == settings_hash:
            return cached
        return None

    def set(self, folder_id: str, stats: CachedFolderStats):
        """Store stats for a folder."""
        self._cache[folder_id] = stats
        self._dirty = True

    def invalidate(self, folder_id: str):
        """Remove cached stats for a folder."""
        if folder_id in self._cache:
            del self._cache[folder_id]
            self._dirty = True

    def invalidate_all(self):
        """Clear all cached stats."""
        if self._cache:
            self._cache.clear()
            self._dirty = True

    @staticmethod
    def compute_settings_hash(folder_id: str, user_settings) -> str:
        """
        Compute a hash of the settings that affect stats calculation.

        Includes: drive enabled state, disabled setlists
        """
        if not user_settings:
            return ""
        enabled = user_settings.is_drive_enabled(folder_id)
        disabled_setlists = sorted(user_settings.get_disabled_subfolders(folder_id))
        key = f"{enabled}:{','.join(disabled_setlists)}"
        return hashlib.md5(key.encode()).hexdigest()[:8]


# Global persistent cache instance
_persistent_stats_cache: PersistentStatsCache | None = None


def get_persistent_stats_cache() -> PersistentStatsCache:
    """Get the global persistent stats cache instance."""
    global _persistent_stats_cache
    if _persistent_stats_cache is None:
        _persistent_stats_cache = PersistentStatsCache()
    return _persistent_stats_cache


class SyncCache:
    """Cache for expensive filesystem scan operations."""

    def __init__(self):
        self.local_files: dict[str, dict[str, int]] = {}  # folder_path -> {rel_path: size}
        self.actual_charts: dict[str, tuple[int, int]] = {}  # folder_path -> (count, size)

    def clear(self):
        """Clear all cached data (call after download/purge)."""
        self.local_files.clear()
        self.actual_charts.clear()

    def clear_folder(self, folder_path: str):
        """Clear cached data for a specific folder."""
        self.local_files.pop(folder_path, None)
        # Clear actual_charts for this folder and all subfolders
        to_remove = [k for k in self.actual_charts if k.startswith(folder_path)]
        for k in to_remove:
            self.actual_charts.pop(k, None)


# Global cache instance
_cache = SyncCache()


def get_cache() -> SyncCache:
    """Get the global cache instance."""
    return _cache


def clear_cache():
    """Clear the filesystem scan cache. Call after downloads or purges."""
    _cache.clear()
    clear_local_stats_cache()


def clear_folder_cache(folder_path: Path):
    """Clear cache for a specific folder. Call after downloading to that folder."""
    _cache.clear_folder(str(folder_path))
    clear_local_stats_cache(folder_path)


def scan_local_files(folder_path: Path) -> dict[str, int]:
    """
    Scan local folder and return dict of {relative_path: size}.

    Uses os.scandir for better performance than individual exists()/stat() calls.
    Results are cached until clear_cache() is called.
    """
    cache_key = str(folder_path)
    if cache_key in _cache.local_files:
        return _cache.local_files[cache_key]

    local_files = {}
    if not folder_path.exists():
        return local_files

    def scan_dir(dir_path: Path, prefix: str = ""):
        try:
            with os.scandir(dir_path) as entries:
                for entry in entries:
                    name = normalize_fs_name(entry.name)
                    rel_path = f"{prefix}{name}" if prefix else name
                    if entry.is_file(follow_symlinks=False):
                        try:
                            local_files[rel_path] = entry.stat(follow_symlinks=False).st_size
                        except OSError:
                            pass
                    elif entry.is_dir(follow_symlinks=False):
                        scan_dir(Path(entry.path), f"{rel_path}/")
        except OSError:
            pass

    scan_dir(folder_path)
    _cache.local_files[cache_key] = local_files
    return local_files


def _scan_actual_charts_uncached(folder_path: Path) -> tuple[int, int]:
    """
    Scan folder for actual chart folders (containing song.ini, notes.mid, etc).
    Internal uncached version.

    Returns:
        Tuple of (chart_count, total_size_bytes)
    """
    if not folder_path.exists():
        return 0, 0

    chart_count = 0
    total_size = 0
    chart_markers = {"song.ini", "notes.mid", "notes.chart"}

    def scan_for_charts(dir_path: Path) -> int:
        """
        Recursively scan for chart folders, including nested charts.
        Returns: size of non-chart content for parent to include.
        """
        nonlocal chart_count, total_size
        try:
            has_marker = False
            subdirs = []
            direct_size = 0

            with os.scandir(dir_path) as entries:
                for entry in entries:
                    if entry.is_file(follow_symlinks=False):
                        if entry.name.lower() in chart_markers:
                            has_marker = True
                        try:
                            direct_size += entry.stat(follow_symlinks=False).st_size
                        except OSError:
                            pass
                    elif entry.is_dir(follow_symlinks=False):
                        subdirs.append(Path(entry.path))

            # Recurse into ALL subdirs first (before checking has_marker)
            subdir_non_chart_size = 0
            for subdir in subdirs:
                subdir_non_chart_size += scan_for_charts(subdir)

            if has_marker:
                # This folder is a chart - include direct files + non-chart subdirs
                chart_count += 1
                total_size += direct_size + subdir_non_chart_size
                return 0  # Chart content doesn't bubble up to parent
            else:
                # Not a chart - return size for parent to potentially include
                return direct_size + subdir_non_chart_size
        except OSError:
            return 0

    scan_for_charts(folder_path)
    return chart_count, total_size


def scan_actual_charts(folder_path: Path, disabled_setlists: set[str] = None) -> tuple[int, int]:
    """
    Scan folder for actual chart folders (containing song.ini, notes.mid, etc).
    Results are cached until clear_cache() is called.

    Args:
        folder_path: Path to scan
        disabled_setlists: Set of top-level subfolder names to skip

    Returns:
        Tuple of (chart_count, total_size_bytes)
    """
    cache_key = str(folder_path)

    # Get or compute full scan (no filtering)
    if cache_key in _cache.actual_charts:
        full_count, full_size = _cache.actual_charts[cache_key]
    else:
        full_count, full_size = _scan_actual_charts_uncached(folder_path)
        _cache.actual_charts[cache_key] = (full_count, full_size)

    if not disabled_setlists:
        return full_count, full_size

    # Subtract disabled setlists (each cached separately)
    result_count = full_count
    result_size = full_size

    for setlist_name in disabled_setlists:
        setlist_path = folder_path / setlist_name
        setlist_key = str(setlist_path)

        if setlist_key in _cache.actual_charts:
            setlist_count, setlist_size = _cache.actual_charts[setlist_key]
        else:
            setlist_count, setlist_size = _scan_actual_charts_uncached(setlist_path)
            _cache.actual_charts[setlist_key] = (setlist_count, setlist_size)

        result_count -= setlist_count
        result_size -= setlist_size

    return max(0, result_count), max(0, result_size)
