"""
Download planning for DM Chart Sync.

Determines what files need to be downloaded by comparing manifest to local state.
Uses marker files as source of truth for archive sync status.
"""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

from ..core.constants import VIDEO_EXTENSIONS
from ..core.formatting import sanitize_path, normalize_path_key
from .sync_checker import is_archive_synced, is_file_synced, is_archive_file

WINDOWS_MAX_PATH = 260
MAX_FILENAME_LENGTH = 255

# Files to skip during download planning (known conflicts with existing directories)
EXCLUDED_FILES = {
    "vianova - Wheel of Fortune_PS.zip",
}


def is_long_paths_enabled() -> bool:
    """Check if Windows long paths are enabled in registry."""
    if os.name != 'nt':
        return True
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Control\FileSystem"
        )
        value, _ = winreg.QueryValueEx(key, "LongPathsEnabled")
        winreg.CloseKey(key)
        return value == 1
    except (OSError, FileNotFoundError):
        return False


def exceeds_windows_path_limit(path: Path) -> bool:
    """Check if path exceeds Windows MAX_PATH and long paths aren't enabled."""
    return os.name == 'nt' and not is_long_paths_enabled() and len(str(path)) >= WINDOWS_MAX_PATH


def has_long_filename(file_path: str) -> bool:
    """Check if any path component exceeds the 255 char filename limit."""
    parts = file_path.replace("\\", "/").split("/")
    return any(len(part) > MAX_FILENAME_LENGTH for part in parts)


@dataclass
class DownloadTask:
    """A file to be downloaded."""
    file_id: str
    local_path: Path
    size: int = 0
    md5: str = ""
    is_archive: bool = False
    rel_path: str = ""  # Relative path for marker tracking


def plan_downloads(
    files: List[dict],
    local_base: Path,
    delete_videos: bool = True,
    folder_name: str = "",
) -> Tuple[List[DownloadTask], int, List[str]]:
    """
    Plan which files need to be downloaded.

    For regular files: check if exists on disk with matching size.
    For archives: check if marker exists with matching MD5 and files verified.

    Handles case-insensitive duplicates: if Google Drive has two archives with
    names differing only in case (e.g., "Carol of" vs "Carol Of"), they would
    extract to the same folder on macOS/Windows. We only process the first one
    encountered; duplicates are skipped.
    """
    to_download = []
    skipped = 0
    long_paths = []

    # Track seen archive extraction paths (normalized for case-insensitive comparison)
    # This handles Google Drive having duplicate archives with case-only differences
    seen_archive_paths: set[str] = set()

    for f in files:
        file_path = sanitize_path(f["path"])
        file_name = file_path.split("/")[-1] if "/" in file_path else file_path
        file_size = f.get("size", 0)
        file_md5 = f.get("md5", "")

        rel_path = f"{folder_name}/{file_path}" if folder_name else file_path

        if file_name in EXCLUDED_FILES:
            skipped += 1
            continue

        # Skip Google Docs/Sheets
        if not file_md5 and "." not in file_name:
            skipped += 1
            continue

        is_archive = is_archive_file(file_name)
        local_path = local_base / file_path

        if is_archive:
            # Check for case-insensitive duplicates
            # Archives extract to their parent folder, so normalize that path
            extract_folder = file_path.rsplit("/", 1)[0] if "/" in file_path else ""
            normalized_extract = normalize_path_key(f"{folder_name}/{extract_folder}")

            if normalized_extract in seen_archive_paths:
                # Duplicate - another archive already extracts here, skip
                skipped += 1
                continue
            seen_archive_paths.add(normalized_extract)

            download_path = local_path.parent / f"_download_{file_name}"
        else:
            download_path = local_path
            if delete_videos and Path(file_name).suffix.lower() in VIDEO_EXTENSIONS:
                skipped += 1
                continue

        if has_long_filename(file_path):
            long_paths.append(file_path)
            continue
        if exceeds_windows_path_limit(download_path):
            long_paths.append(file_path)
            continue

        # Check if already synced
        if is_archive:
            if "/" in file_path:
                checksum_path = file_path.rsplit("/", 1)[0]
            else:
                checksum_path = ""

            synced, _ = is_archive_synced(
                folder_name=folder_name,
                checksum_path=checksum_path,
                archive_name=file_name,
                manifest_md5=file_md5,
                local_base=local_base,
            )
            is_synced = synced
        else:
            is_synced = is_file_synced(
                rel_path=file_path,
                manifest_size=file_size,
                local_path=local_path,
            )

        if is_synced:
            skipped += 1
        else:
            to_download.append(DownloadTask(
                file_id=f["id"],
                local_path=download_path,
                size=file_size,
                md5=file_md5,
                is_archive=is_archive,
                rel_path=rel_path,
            ))

    return to_download, skipped, long_paths
