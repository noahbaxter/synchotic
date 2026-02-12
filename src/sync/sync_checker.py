"""
Unified sync checking logic for DM Chart Sync.

Single source of truth for "is this file/archive synced?"
Uses marker files as the ONLY authority for archive sync status.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..core.constants import CHART_ARCHIVE_EXTENSIONS
from .markers import load_marker, verify_marker, find_any_marker_for_path


@dataclass
class FileSpec:
    """Specification for a file in the manifest."""
    rel_path: str
    size: int
    md5: str
    is_archive: bool = False


def is_archive_file(filename: str) -> bool:
    """Check if a filename is an archive type we handle."""
    return any(filename.lower().endswith(ext) for ext in CHART_ARCHIVE_EXTENSIONS)


def is_archive_synced(
    folder_name: str,
    checksum_path: str,
    archive_name: str,
    manifest_md5: str,
    local_base: Path,
) -> tuple[bool, int]:
    """
    Check if an archive is synced. Returns (is_synced, synced_size).

    Logic: marker exists with matching MD5 AND all extracted files verified on disk.

    Args:
        folder_name: Drive/folder name (e.g., "TestDrive")
        checksum_path: Parent path within folder (e.g., "Setlist") or ""
        archive_name: Archive filename (e.g., "pack.7z")
        manifest_md5: Expected MD5 from manifest
        local_base: Base folder path on disk (e.g., /path/to/TestDrive)

    Returns:
        Tuple of (is_synced, extracted_size)
    """
    # Build full archive path for marker lookup
    if checksum_path:
        archive_path = f"{folder_name}/{checksum_path}/{archive_name}"
    else:
        archive_path = f"{folder_name}/{archive_name}"

    # Check marker file (single source of truth)
    marker = load_marker(archive_path, manifest_md5)
    if marker:
        # Marker exists with matching MD5 - verify extracted files still exist
        if verify_marker(marker, local_base):
            total_size = sum(marker.get("files", {}).values())
            return True, total_size

    # Handle case-insensitive filesystem conflicts:
    # Google Drive may have two files with names differing only in case
    # (e.g., "Carol of" vs "Carol Of"). On macOS/Windows they extract to
    # the same folder and conflict. If a marker exists for a DIFFERENT path
    # (case variant), consider it synced to prevent infinite re-download loops.
    #
    # But if the marker's archive_path is identical to ours, this is an MD5
    # update (charter uploaded a new version) — NOT a case duplicate. In that
    # case, fall through so the user gets the update.
    any_marker = find_any_marker_for_path(archive_path)
    if any_marker and verify_marker(any_marker, local_base):
        marker_archive_path = any_marker.get("archive_path", "")
        if marker_archive_path != archive_path:
            total_size = sum(any_marker.get("files", {}).values())
            return True, total_size

    # No valid marker = not synced
    return False, 0


def is_file_synced(
    rel_path: str,
    manifest_size: int,
    local_path: Path = None,
) -> bool:
    """
    Check if a regular (non-archive) file is synced.

    Logic: file exists on disk with expected size from manifest.
    .ini files get size tolerance since Clone Hero appends leaderboard data.
    """
    if not local_path or not local_path.exists():
        return False
    try:
        actual_size = local_path.stat().st_size
    except OSError:
        return False
    if local_path.suffix.lower() == ".ini":
        return actual_size >= manifest_size
    return actual_size == manifest_size
