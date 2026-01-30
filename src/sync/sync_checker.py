"""
Unified sync checking logic for DM Chart Sync.

Single source of truth for "is this file/archive synced?"
Uses marker files as primary verification, with sync_state fallback during migration.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..core.constants import CHART_ARCHIVE_EXTENSIONS
from ..core.files import file_exists_with_size
from ..core.paths import get_download_path
from .state import SyncState
from .markers import load_marker, verify_marker


@dataclass
class FileSpec:
    """Expected file specification from any manifest source."""
    rel_path: str       # Path relative to drive folder (e.g., "Setlist/chart.7z")
    size: int           # Expected size in bytes
    md5: str            # Expected MD5 hash
    is_archive: bool = False  # If True, extracts to folder


def is_archive_file(filename: str) -> bool:
    """Check if a filename is an archive type we handle."""
    return any(filename.lower().endswith(ext) for ext in CHART_ARCHIVE_EXTENSIONS)


def is_archive_synced(
    folder_name: str,
    checksum_path: str,
    archive_name: str,
    manifest_md5: str,
    sync_state: Optional[SyncState],
    local_base: Path,
) -> tuple[bool, int]:
    """
    Check if an archive is synced. Returns (is_synced, synced_size).

    Logic priority:
    1. Check marker file - if exists with matching MD5 and all files verified → synced
    2. Check sync_state (migration fallback) - if tracked with matching MD5 and files exist → synced

    No disk heuristics. If marker/state doesn't exist, archive needs download.

    Args:
        folder_name: Drive/folder name (e.g., "TestDrive")
        checksum_path: Parent path within folder (e.g., "Setlist") or ""
        archive_name: Archive filename (e.g., "pack.7z")
        manifest_md5: Expected MD5 from manifest
        sync_state: SyncState instance (can be None)
        local_base: Base folder path on disk (e.g., /path/to/TestDrive)

    Returns:
        Tuple of (is_synced, extracted_size)
        extracted_size is from sync_state if available, else 0
    """
    # Build full archive path for lookups
    if checksum_path:
        archive_path = f"{folder_name}/{checksum_path}/{archive_name}"
    else:
        archive_path = f"{folder_name}/{archive_name}"

    # 1. Check marker file first (primary source of truth)
    marker = load_marker(archive_path, manifest_md5)
    if marker:
        # Marker exists with matching MD5 - verify extracted files
        # Files in marker are relative to drive folder (e.g., "Setlist/ChartFolder/song.ini")
        if verify_marker(marker, local_base):
            # All files exist with correct sizes
            total_size = sum(marker.get("files", {}).values())
            return True, total_size

    # 2. Fallback to sync_state during migration period
    if sync_state:
        if sync_state.is_archive_synced(archive_path, manifest_md5):
            # State says archive was synced with matching MD5
            # Verify extracted files still exist on disk
            archive_files = sync_state.get_archive_files(archive_path)
            if archive_files:
                missing = sync_state.check_files_exist(archive_files)
                if len(missing) == 0:
                    # All tracked files exist with correct sizes
                    archive = sync_state.get_archive(archive_path)
                    extracted_size = archive.get("archive_size", 0) if archive else 0
                    return True, extracted_size
            # Files missing or wrong size - NOT synced
            return False, 0

    # Not synced - needs download
    return False, 0


def is_file_synced(
    rel_path: str,
    manifest_size: int,
    manifest_md5: str,
    sync_state: Optional[SyncState],
    local_path: Path,
    folder_name: str = "",
) -> bool:
    """
    Check if a regular (non-archive) file is synced.

    Logic: file exists on disk with expected size from manifest.

    Args:
        rel_path: Relative path within folder (e.g., "Setlist/song.ini")
        manifest_size: Expected size from manifest
        manifest_md5: Expected MD5 from manifest
        sync_state: SyncState instance (can be None) - used for size reconciliation
        local_path: Full local path to file
        folder_name: Drive/folder name for sync_state lookup

    Returns:
        True if file is synced, False otherwise
    """
    # Primary check: file exists with manifest size
    if file_exists_with_size(local_path, manifest_size):
        return True

    # Fallback: check if sync_state has different size but same MD5
    # This handles stale manifest sizes (common with Google Drive shortcuts)
    if sync_state:
        full_path = f"{folder_name}/{rel_path}" if folder_name else rel_path
        tracked = sync_state._files.get(full_path)
        if tracked and tracked.get("md5") == manifest_md5:
            tracked_size = tracked.get("size", 0)
            if file_exists_with_size(local_path, tracked_size):
                return True

    return False
