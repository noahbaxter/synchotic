"""
Marker file management for archive sync tracking.

Each extracted archive gets a marker file that records:
- The archive path and MD5 it was extracted from
- When extraction happened
- All extracted files with their sizes

Markers are stored in .dm-sync/markers/ and named based on archive path + MD5.
This survives sync_state.json corruption/loss.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..core.formatting import normalize_path_key
from ..core.paths import get_data_dir


def get_markers_dir() -> Path:
    """Get the markers directory, creating it if needed."""
    markers_dir = get_data_dir() / "markers"
    markers_dir.mkdir(exist_ok=True)
    return markers_dir


def get_marker_path(archive_path: str, md5: str) -> Path:
    """
    Compute marker file path for an archive.

    Args:
        archive_path: Relative archive path (e.g., "DriveName/Setlist/pack.7z")
        md5: Archive MD5 hash

    Returns:
        Path to marker file
    """
    import hashlib

    # Normalize for case-insensitive matching (NFC + lowercase)
    safe_name = normalize_path_key(archive_path).replace("/", "_").replace("\\", "_")

    # Filename: {safe_name}_{md5[:8]}.json
    # Max filename on most filesystems: 255 chars
    # Reserve: .json (5) + _md5prefix (9) + safety margin for .tmp (10) = 24 chars
    max_base_len = 230

    if len(safe_name) > max_base_len:
        # Truncate and add path hash for uniqueness
        path_hash = hashlib.md5(archive_path.encode()).hexdigest()[:8]
        safe_name = safe_name[:max_base_len - 9] + "_" + path_hash

    return get_markers_dir() / f"{safe_name}_{md5[:8]}.json"


def load_marker(archive_path: str, md5: str) -> Optional[dict]:
    """
    Load marker file for an archive if it exists.

    Returns:
        Marker dict or None if not found/invalid
    """
    marker_path = get_marker_path(archive_path, md5)
    if not marker_path.exists():
        return None
    try:
        with open(marker_path) as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None


def save_marker(
    archive_path: str,
    md5: str,
    extracted_files: dict,
    extracted_to: str = "",
) -> Path:
    """
    Save marker file for an extracted archive.

    Args:
        archive_path: Relative archive path (e.g., "DriveName/Setlist/pack.7z")
        md5: Archive MD5 hash
        extracted_files: Dict of {relative_path: size} for extracted files
        extracted_to: Path where files were extracted (relative to download base)

    Returns:
        Path to created marker file
    """
    marker = {
        "archive_path": archive_path,
        "md5": md5,
        "extracted_at": datetime.now().isoformat(),
        "extracted_to": extracted_to,
        "files": extracted_files,
    }

    marker_path = get_marker_path(archive_path, md5)
    marker_path.parent.mkdir(parents=True, exist_ok=True)

    # Atomic write: write to .tmp then rename
    tmp_path = marker_path.with_suffix(".json.tmp")
    with open(tmp_path, "w") as f:
        json.dump(marker, f, indent=2)
    tmp_path.replace(marker_path)

    return marker_path


def verify_marker(marker: dict, base_path: Path) -> bool:
    """
    Verify all files in marker exist on disk with correct sizes.

    Args:
        marker: Marker dict with "files" key
        base_path: Base path where files should exist

    Returns:
        True if all files verified, False if any missing or wrong size
    """
    files = marker.get("files", {})
    if not files:
        return False

    for rel_path, expected_size in files.items():
        full_path = base_path / rel_path
        if not full_path.exists():
            return False
        try:
            actual_size = full_path.stat().st_size
            is_ini = full_path.suffix.lower() == ".ini"
            # .ini files: Clone Hero appends leaderboard data, so just check >= original
            if is_ini and actual_size < expected_size:
                return False
            if not is_ini and actual_size != expected_size:
                return False
        except OSError:
            return False

    return True


def _find_markers_by_prefix(archive_path: str) -> list[Path]:
    """Find all marker files matching an archive path prefix (any MD5)."""
    markers_dir = get_markers_dir()
    if not markers_dir.exists():
        return []

    safe_name = normalize_path_key(archive_path).replace("/", "_").replace("\\", "_")
    return [
        f for f in markers_dir.glob("*.json")
        if normalize_path_key(f.stem).startswith(safe_name + "_")
    ]


def find_any_marker_for_path(archive_path: str) -> Optional[dict]:
    """
    Find ANY marker for an archive path, regardless of MD5.

    This handles the case where Google Drive has two files with names
    differing only in case (e.g., "Carol of" vs "Carol Of"). On case-insensitive
    filesystems, these extract to the same folder and conflict. We consider
    either version as "synced" to prevent infinite re-download loops.

    Returns:
        First matching marker dict, or None if no markers exist
    """
    for marker_file in _find_markers_by_prefix(archive_path):
        try:
            with open(marker_file) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            continue

    return None


def delete_marker(archive_path: str, md5: str) -> bool:
    """
    Delete marker file for an archive.

    Returns:
        True if deleted, False if not found
    """
    marker_path = get_marker_path(archive_path, md5)
    if marker_path.exists():
        try:
            marker_path.unlink()
            return True
        except OSError:
            pass
    return False


def get_all_marker_files() -> set[str]:
    """
    Get all file paths tracked by all markers.

    Returns:
        Set of file paths relative to drive folder (e.g., "Setlist/ChartFolder/song.ini")
    """
    all_files = set()
    markers_dir = get_markers_dir()

    if not markers_dir.exists():
        return all_files

    for marker_file in markers_dir.glob("*.json"):
        try:
            with open(marker_file) as f:
                marker = json.load(f)
            for file_path in marker.get("files", {}).keys():
                all_files.add(file_path)
        except (json.JSONDecodeError, IOError):
            continue

    return all_files


def get_all_markers() -> list[dict]:
    """
    Load all marker files.

    Returns:
        List of marker dicts
    """
    markers = []
    markers_dir = get_markers_dir()

    if not markers_dir.exists():
        return markers

    for marker_file in markers_dir.glob("*.json"):
        try:
            with open(marker_file) as f:
                marker = json.load(f)
            markers.append(marker)
        except (json.JSONDecodeError, IOError):
            continue

    return markers


def get_files_for_archive(archive_path: str) -> dict[str, int]:
    """
    Get all files tracked by markers for an archive path (any MD5).

    Used to find old extracted files before re-downloading an updated archive.

    Returns:
        Dict of {file_path: size} from all markers for this archive
    """
    files = {}
    for marker_file in _find_markers_by_prefix(archive_path):
        try:
            with open(marker_file) as f:
                marker = json.load(f)
            files.update(marker.get("files", {}))
        except (json.JSONDecodeError, IOError):
            pass
    return files


def delete_markers_for_archive(archive_path: str) -> int:
    """
    Delete ALL marker files for an archive path (any MD5).

    Used when archive MD5 changes - delete old marker before redownloading.

    Returns:
        Number of markers deleted
    """
    deleted = 0
    for marker_file in _find_markers_by_prefix(archive_path):
        try:
            marker_file.unlink()
            deleted += 1
        except OSError:
            pass
    return deleted


def is_migration_done() -> bool:
    """Check if sync_state → marker migration has been completed."""
    return (get_markers_dir() / ".migrated").exists()


def mark_migration_done():
    """Mark sync_state → marker migration as complete."""
    (get_markers_dir() / ".migrated").touch()


def rebuild_markers_from_disk(
    folders: list[dict],
    base_path: Path,
) -> tuple[int, int]:
    """
    Rebuild markers by scanning disk and matching to manifest archives.

    For each archive in manifest, check if its extraction folder exists on disk.
    If so, scan the files and create a marker.

    This is useful when:
    - Migrating from old sync_state system
    - Recovering from lost/corrupted markers
    - After manual file operations

    Args:
        folders: List of folder dicts from manifest (with files loaded)
        base_path: Base download path (Sync Charts folder)

    Returns:
        Tuple of (created_count, skipped_count)
    """
    from ..core.constants import CHART_ARCHIVE_EXTENSIONS

    created = 0
    skipped = 0

    def is_archive(filename: str) -> bool:
        return any(filename.lower().endswith(ext) for ext in CHART_ARCHIVE_EXTENSIONS)

    for folder in folders:
        folder_name = folder.get("name", "")
        folder_path = base_path / folder_name
        if not folder_path.exists():
            continue

        files = folder.get("files") or []
        if not files:
            continue

        # Group files by archive
        archives: dict[str, dict] = {}  # archive_path -> {md5, parent_path}
        for f in files:
            file_path = f.get("path", "")
            file_name = file_path.split("/")[-1] if "/" in file_path else file_path
            if is_archive(file_name):
                full_archive_path = f"{folder_name}/{file_path}"
                parent = file_path.rsplit("/", 1)[0] if "/" in file_path else ""
                archives[full_archive_path] = {
                    "md5": f.get("md5", ""),
                    "parent": parent,
                    "name": file_name,
                }

        # Check each archive
        for archive_path, info in archives.items():
            md5 = info["md5"]
            if not md5:
                skipped += 1
                continue

            # Skip if marker already exists
            existing = load_marker(archive_path, md5)
            if existing:
                skipped += 1
                continue

            # Figure out extraction location
            # Archive at: folder_name/Setlist/pack.7z
            # Extracts to: folder_name/Setlist/ (same folder as archive)
            if info["parent"]:
                extract_path = folder_path / info["parent"]
            else:
                extract_path = folder_path

            if not extract_path.exists():
                skipped += 1
                continue

            # Scan files in extraction folder
            # We need paths relative to the drive folder (folder_name)
            extracted_files = {}
            try:
                for item in extract_path.rglob("*"):
                    if item.is_file():
                        # Get path relative to folder_path (drive folder)
                        rel = item.relative_to(folder_path)
                        rel_str = str(rel).replace("\\", "/")
                        try:
                            extracted_files[rel_str] = item.stat().st_size
                        except OSError:
                            pass
            except OSError:
                skipped += 1
                continue

            if not extracted_files:
                skipped += 1
                continue

            # Create marker
            save_marker(
                archive_path=archive_path,
                md5=md5,
                extracted_files=extracted_files,
            )
            created += 1

    return created, skipped


def migrate_sync_state_to_markers(
    sync_state,
    base_path: Path,
    manifest_md5s: dict,
) -> tuple[int, int]:
    """
    One-time migration from sync_state to marker files.

    IMPORTANT: We verify every file exists with correct size before creating marker.
    This prevents false positives from corrupted sync_state.

    Args:
        sync_state: SyncState instance with loaded data
        base_path: Base download path (Sync Charts folder)
        manifest_md5s: Dict of {archive_path: md5} from current manifest

    Returns:
        Tuple of (migrated_count, skipped_count)
    """
    if is_migration_done():
        return 0, 0

    migrated = 0
    skipped = 0

    # Iterate over all tracked archives in sync_state
    for archive_path, archive_data in sync_state._archives.items():
        md5 = archive_data.get("md5")
        if not md5:
            skipped += 1
            continue

        # Skip if MD5 doesn't match current manifest (archive was updated)
        if archive_path in manifest_md5s and manifest_md5s[archive_path] != md5:
            skipped += 1  # Will re-download with new version
            continue

        # Get extracted files from sync_state
        extracted_files = {}
        archive_files = sync_state.get_archive_files(archive_path)
        for file_path in archive_files:
            file_data = sync_state.get_file(file_path) or {}
            if file_data:
                extracted_files[file_path] = file_data.get("size", 0)

        if not extracted_files:
            skipped += 1
            continue

        # VERIFY: Check every file actually exists with correct size
        # Files are stored with full path (DriveName/Setlist/ChartFolder/file.ext)
        # We need to strip the drive name to get path relative to base_path
        all_verified = True
        for rel_path, expected_size in extracted_files.items():
            # rel_path is like "DriveName/Setlist/file.ext"
            # base_path is like "/path/to/Sync Charts"
            # We need: base_path / "DriveName/Setlist/file.ext"
            full_path = base_path / rel_path
            if not full_path.exists():
                all_verified = False
                break
            try:
                if full_path.stat().st_size != expected_size:
                    all_verified = False
                    break
            except OSError:
                all_verified = False
                break

        if not all_verified:
            skipped += 1  # Will re-download - files missing or wrong size
            continue

        # All files verified - safe to create marker
        # Convert file paths to be relative to drive folder for marker storage
        # archive_path is like "DriveName/Setlist/pack.7z"
        # We store files relative to DriveName (same as sync_state)
        save_marker(
            archive_path=archive_path,
            md5=md5,
            extracted_files=extracted_files,
        )
        migrated += 1

    mark_migration_done()
    return migrated, skipped

