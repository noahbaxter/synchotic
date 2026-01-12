"""
Sync operations module.

Handles file downloading, sync logic, and progress tracking.
"""

from ..core.progress import ProgressTracker  # Re-export from core for backwards compat
from .cache import clear_cache, clear_folder_cache, FolderStats, FolderStatsCache
from .status import SyncStatus, get_sync_status, get_setlist_sync_status
from .download_planner import DownloadTask, plan_downloads
from .purge_planner import PurgeStats, count_purgeable_files, count_purgeable_detailed
from .purger import delete_files
from .folder_sync import FolderSync, purge_all_folders
from .utils import get_sync_folder_name
from .downloader import FileDownloader, DownloadResult
from .state import SyncState
from .existing_scanner import scan_existing_archives, collect_archives_from_sources
from .extractor import is_system_junk, scan_extracted_files, find_extra_files, delete_extra_files

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
    # Sync status
    "SyncStatus",
    "get_sync_status",
    "get_setlist_sync_status",
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
    "get_sync_folder_name",
    # Downloader
    "FileDownloader",
    "DownloadResult",
    # Sync state
    "SyncState",
    # Existing content scanner
    "scan_existing_archives",
    "collect_archives_from_sources",
    "is_system_junk",
    "scan_extracted_files",
    "find_extra_files",
    "delete_extra_files",
]
