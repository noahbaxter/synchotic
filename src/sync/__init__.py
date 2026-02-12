"""
Sync operations module.

Handles file downloading, sync logic, and progress tracking.
"""

from ..core.progress import ProgressTracker  # Re-export from core for backwards compat
from .cache import (
    clear_cache, clear_folder_cache, FolderStats, FolderStatsCache,
    CachedFolderStats, CachedSetlistStats, AggregatedFolderStats,
    PersistentStatsCache, get_persistent_stats_cache, aggregate_folder_stats,
    ScanCache, get_scan_cache,
)
from .status import SyncStatus, get_sync_status, get_setlist_sync_status, get_lazy_sync_status, compute_setlist_stats
from .download_planner import DownloadTask, plan_downloads
from .purge_planner import PurgeStats, count_purgeable_files, count_purgeable_detailed
from .purger import delete_files
from .folder_sync import FolderSync, purge_all_folders
from .downloader import FileDownloader, DownloadResult
from .background_scanner import BackgroundScanner, ScanStats

# Backwards compatibility aliases
clear_scan_cache = clear_cache

__all__ = [
    # Progress
    "ProgressTracker",
    # Cache
    "clear_cache",
    "clear_folder_cache",
    "clear_scan_cache",  # Backwards compat
    "FolderStats",
    "FolderStatsCache",
    "CachedFolderStats",
    "CachedSetlistStats",
    "AggregatedFolderStats",
    "PersistentStatsCache",
    "get_persistent_stats_cache",
    "aggregate_folder_stats",
    # Sync status
    "SyncStatus",
    "get_sync_status",
    "get_setlist_sync_status",
    "get_lazy_sync_status",
    "compute_setlist_stats",
    # Download planning
    "DownloadTask",
    "plan_downloads",
    # Purge planning
    "PurgeStats",
    "count_purgeable_files",
    "count_purgeable_detailed",
    # Purger
    "delete_files",
    # Folder sync
    "FolderSync",
    "purge_all_folders",
    # Downloader
    "FileDownloader",
    "DownloadResult",
    # Background scanning
    "BackgroundScanner",
    "ScanStats",
]
