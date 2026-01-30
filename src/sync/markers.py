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

    safe_name = archive_path.replace("/", "_").replace("\\", "_")

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
            if full_path.stat().st_size != expected_size:
                return False
        except OSError:
            return False

    return True


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


def is_migration_done() -> bool:
    """Check if sync_state → marker migration has been completed."""
    return (get_markers_dir() / ".migrated").exists()


def mark_migration_done():
    """Mark sync_state → marker migration as complete."""
    (get_markers_dir() / ".migrated").touch()


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
            file_data = sync_state._files.get(file_path, {})
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

