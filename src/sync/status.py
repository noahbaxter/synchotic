"""
Sync status calculation for DM Chart Sync.

Determines what's synced by comparing local files against manifest.
Progress is based on manifest entries (archives/files), not chart counts.
"""

import os
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from ..core.constants import CHART_MARKERS, VIDEO_EXTENSIONS
from ..core.formatting import sanitize_path, dedupe_files_by_newest, normalize_fs_name
from ..core.logging import debug_log
from .cache import scan_actual_charts
from .state import SyncState
from .sync_checker import is_archive_synced, is_archive_file, is_file_synced


@dataclass
class SyncStatus:
    """Status of local charts vs manifest."""
    total_charts: int = 0
    synced_charts: int = 0
    total_size: int = 0
    synced_size: int = 0
    # True if counts are from actual folder scan (real charts)
    # False if counts are from manifest (archives, not yet extracted)
    is_actual_charts: bool = False

    @property
    def missing_charts(self) -> int:
        return self.total_charts - self.synced_charts

    @property
    def missing_size(self) -> int:
        return self.total_size - self.synced_size

    @property
    def is_synced(self) -> bool:
        return self.synced_charts == self.total_charts


def _file_in_disabled_setlist(file_path: str, disabled_setlists: set) -> bool:
    """Check if a file path belongs to a disabled setlist."""
    first_slash = file_path.find("/")
    setlist = file_path[:first_slash] if first_slash != -1 else file_path
    return setlist in disabled_setlists


def _is_video_file(path: str) -> bool:
    """Check if a path is a video file."""
    return Path(path).suffix.lower() in VIDEO_EXTENSIONS


def _build_chart_folders(manifest_files: list) -> dict:
    """
    Group manifest files by parent folder to identify charts.

    Returns dict: {parent_path: {files, is_chart, total_size, archive_md5, archive_name, checksum_path}}

    For loose files, 'files' contains (path, size, md5) tuples.
    For archives, 'files' contains (path, size) tuples (md5 stored separately).
    """
    chart_folders = defaultdict(lambda: {
        "files": [], "is_chart": False, "total_size": 0,
        "archive_md5": "", "archive_name": "", "checksum_path": ""
    })

    for f in manifest_files:
        file_path = f.get("path", "")
        file_size = f.get("size", 0)
        file_md5 = f.get("md5", "")

        sanitized_path = sanitize_path(file_path)
        slash_idx = sanitized_path.rfind("/")

        if slash_idx == -1:
            # Root-level file
            file_name = sanitized_path.lower()
            if is_archive_file(file_name):
                chart_folders[sanitized_path]["files"].append((sanitized_path, file_size))
                chart_folders[sanitized_path]["total_size"] += file_size
                chart_folders[sanitized_path]["is_chart"] = True
                chart_folders[sanitized_path]["archive_md5"] = file_md5
                chart_folders[sanitized_path]["archive_name"] = sanitized_path
                chart_folders[sanitized_path]["checksum_path"] = ""
            continue

        parent = sanitized_path[:slash_idx]
        file_name = sanitized_path[slash_idx + 1:].lower()
        archive_name = sanitized_path[slash_idx + 1:]

        if is_archive_file(file_name):
            chart_folders[sanitized_path]["files"].append((sanitized_path, file_size))
            chart_folders[sanitized_path]["total_size"] += file_size
            chart_folders[sanitized_path]["is_chart"] = True
            chart_folders[sanitized_path]["archive_md5"] = file_md5
            chart_folders[sanitized_path]["archive_name"] = archive_name
            chart_folders[sanitized_path]["checksum_path"] = parent
        else:
            chart_folders[parent]["files"].append((sanitized_path, file_size, file_md5))
            chart_folders[parent]["total_size"] += file_size
            if file_name in CHART_MARKERS:
                chart_folders[parent]["is_chart"] = True

    return chart_folders


def _count_synced_charts(
    chart_folders: dict,
    sync_state: SyncState,
    folder_name: str,
    skip_custom: bool = False,
    delete_videos: bool = True,
    folder_path: Path = None,
) -> tuple[int, int, int, int]:
    """
    Count total and synced charts from chart_folders.

    Returns: (total_charts, synced_charts, total_size, synced_size)
    """
    total_charts = 0
    synced_charts = 0
    total_size = 0
    synced_size = 0

    for _, data in chart_folders.items():
        if not data["is_chart"]:
            continue

        total_charts += 1

        if skip_custom:
            continue

        # Archive chart - use unified sync_checker
        if data["archive_name"]:
            synced, extracted_size = is_archive_synced(
                folder_name=folder_name,
                checksum_path=data["checksum_path"],
                archive_name=data["archive_name"],
                manifest_md5=data["archive_md5"],
                sync_state=sync_state,
                local_base=folder_path,
            )
            if synced:
                synced_charts += 1
                size_to_use = extracted_size if extracted_size else data["total_size"]
                synced_size += size_to_use
                total_size += size_to_use
            else:
                total_size += data["total_size"]
            continue

        # Folder chart - check if all (non-video) files are synced
        files_to_check = data["files"]
        if delete_videos:
            files_to_check = [(fp, fs, md5) for fp, fs, md5 in files_to_check if not _is_video_file(fp)]

        # Use is_file_synced for consistent logic with download_planner
        # This includes sync_state fallback for stale manifest sizes
        is_synced = all(
            is_file_synced(
                rel_path=fp,
                manifest_size=fs,
                manifest_md5=md5,
                sync_state=sync_state,
                local_path=folder_path / fp,
                folder_name=folder_name,
            )
            for fp, fs, md5 in files_to_check
        )

        # Calculate size excluding videos if delete_videos is enabled
        if delete_videos:
            chart_size = sum(fs for fp, fs, _ in data["files"] if not _is_video_file(fp))
        else:
            chart_size = data["total_size"]

        if is_synced:
            synced_charts += 1
            synced_size += chart_size
        total_size += chart_size

    return total_charts, synced_charts, total_size, synced_size


def get_sync_status(folders: list, base_path: Path, user_settings=None, sync_state: SyncState = None) -> SyncStatus:
    """
    Calculate sync status for enabled folders.

    Progress is based on manifest entries (1 archive = 1 entry).
    This gives accurate sync progress without needing to know chart contents.

    Args:
        folders: List of folder dicts from manifest
        base_path: Base download path
        user_settings: UserSettings for checking enabled states
        sync_state: SyncState for checking synced archives (optional)

    Returns:
        SyncStatus with totals and synced counts
    """
    status = SyncStatus()

    for folder in folders:
        folder_id = folder.get("folder_id", "")
        folder_name = folder.get("name", "")
        folder_path = base_path / folder_name
        is_custom = folder.get("is_custom", False)

        # Skip disabled drives
        if user_settings and not user_settings.is_drive_enabled(folder_id):
            continue

        manifest_files = folder.get("files", [])
        if not manifest_files:
            continue

        # Get disabled setlists FIRST so we can filter before expensive operations
        disabled_setlists = set()
        if user_settings:
            disabled_setlists = user_settings.get_disabled_subfolders(folder_id)

        # Filter out disabled setlists BEFORE dedupe (major optimization for large manifests)
        if disabled_setlists:
            manifest_files = [
                f for f in manifest_files
                if not _file_in_disabled_setlist(f.get("path", ""), disabled_setlists)
            ]

        # Deduplicate files with same path, keeping only newest version
        manifest_files = dedupe_files_by_newest(manifest_files)

        # For custom folders, scan actual charts on disk
        synced_from_scan = None
        downloaded_setlist_sizes = {}
        if is_custom and folder_path.exists():
            actual_charts, actual_size = scan_actual_charts(folder_path, disabled_setlists)
            debug_log(f"CUSTOM_SCAN | folder={folder_name} | disk_charts={actual_charts} | disk_size={actual_size}")
            if actual_charts > 0:
                synced_from_scan = (actual_charts, actual_size)
                status.is_actual_charts = True
                # Track per-setlist disk sizes
                try:
                    for entry in os.scandir(folder_path):
                        if entry.is_dir() and not entry.name.startswith('.'):
                            name = normalize_fs_name(entry.name)
                            if disabled_setlists and name in disabled_setlists:
                                continue
                            setlist_charts, setlist_size = scan_actual_charts(Path(entry.path), set())
                            if setlist_charts > 0:
                                downloaded_setlist_sizes[name] = setlist_size
                except OSError:
                    pass

        # Build chart folders from manifest
        chart_folders = _build_chart_folders(manifest_files)

        # Count charts and check sync status
        # Get delete_videos setting (default True if no settings)
        delete_videos = user_settings.delete_videos if user_settings else True
        total, synced, total_size, synced_size = _count_synced_charts(
            chart_folders, sync_state, folder_name,
            skip_custom=(synced_from_scan is not None),
            delete_videos=delete_videos,
            folder_path=folder_path,
        )
        status.total_charts += total
        status.synced_charts += synced
        status.total_size += total_size
        status.synced_size += synced_size

        debug_log(f"STATUS | folder={folder_name} | total={total} | synced={synced} | missing_size={total_size - synced_size}")

        # For custom folders, use scan results and calculate sizes per-setlist
        if synced_from_scan is not None:
            actual_charts, actual_size = synced_from_scan
            status.synced_charts += actual_charts
            status.synced_size += actual_size

            # Build per-setlist manifest sizes
            setlist_manifest_sizes = {}
            for parent, data in chart_folders.items():
                if not data["is_chart"]:
                    continue
                first_slash = parent.find("/")
                setlist_name = parent[:first_slash] if first_slash != -1 else parent
                setlist_manifest_sizes[setlist_name] = setlist_manifest_sizes.get(setlist_name, 0) + data["total_size"]

            # Use disk size for downloaded, manifest size for not-downloaded
            for setlist_name, manifest_size in setlist_manifest_sizes.items():
                if setlist_name in downloaded_setlist_sizes:
                    status.total_size += downloaded_setlist_sizes[setlist_name]
                else:
                    status.total_size += manifest_size

            debug_log(f"CUSTOM_FINAL | folder={folder_name} | total_charts={status.total_charts} | synced_charts={status.synced_charts} | total_size={status.total_size} | synced_size={status.synced_size}")

    return status


def get_setlist_sync_status(
    folder: dict,
    setlist_name: str,
    base_path: Path,
    sync_state: SyncState = None,
    delete_videos: bool = True,
) -> SyncStatus:
    """
    Calculate sync status for a single setlist within a folder.

    Args:
        folder: Folder dict from manifest
        setlist_name: Name of the setlist to check
        base_path: Base download path
        sync_state: SyncState for checking synced archives (optional)
        delete_videos: Whether to exclude video files from size calculations

    Returns:
        SyncStatus with totals and synced counts for just this setlist
    """
    status = SyncStatus()

    folder_name = folder.get("name", "")
    folder_path = base_path / folder_name

    manifest_files = folder.get("files", [])
    if not manifest_files:
        return status

    # Filter to only files in this setlist
    setlist_prefix = f"{setlist_name}/"
    manifest_files = [
        f for f in manifest_files
        if f.get("path", "").startswith(setlist_prefix) or f.get("path", "") == setlist_name
    ]

    if not manifest_files:
        return status

    # Deduplicate files with same path, keeping only newest version
    manifest_files = dedupe_files_by_newest(manifest_files)

    # Build chart folders from manifest
    chart_folders = _build_chart_folders(manifest_files)

    # Count charts and check sync status
    total, synced, total_size, synced_size = _count_synced_charts(
        chart_folders, sync_state, folder_name,
        skip_custom=False,
        delete_videos=delete_videos,
        folder_path=folder_path,
    )

    status.total_charts = total
    status.synced_charts = synced
    status.total_size = total_size
    status.synced_size = synced_size

    return status
