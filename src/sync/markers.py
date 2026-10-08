"""
Marker file management for archive sync tracking.

Each extracted archive gets a marker file that records:
- The archive path and MD5 it was extracted from
- When extraction happened
- All extracted files with their sizes

Markers are stored in .dm-sync/markers/ and named based on archive path + MD5.
Markers are the primary source of truth for sync verification.
"""

import json
import os
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..core.formatting import normalize_path_key, resolve_existing_path
from ..core.paths import get_library_state_dir


def _marker_files(markers_dir: Path, pattern: str = "*.json") -> list:
    """Real marker files, never macOS AppleDouble sidecars.

    Markers live inside the library now, and a library on an SMB share (or any
    volume without native xattr support) collects a binary ._name.json beside
    every file. Those match the glob, are not UTF-8, and are not markers.
    """
    return [f for f in markers_dir.glob(pattern) if not f.name.startswith("._")]


def _read_markers(marker_files, on_progress=None) -> list:
    """(file, marker) for each file, None for one that does not parse. On a
    library over SMB, reading 3000 markers one at a time took a minute; most
    of that is waiting on the network, so read many at once."""
    from concurrent.futures import ThreadPoolExecutor

    def load(marker_file):
        try:
            return marker_file, json.loads(marker_file.read_text())
        except (ValueError, OSError):
            return marker_file, None

    loaded = []
    with ThreadPoolExecutor(32) as pool:
        for result in pool.map(load, marker_files):
            loaded.append(result)
            if on_progress:
                on_progress(len(loaded), len(marker_files))
    return loaded


def get_markers_dir() -> Path:
    """Get the markers directory, creating it if needed."""
    markers_dir = get_library_state_dir() / "markers"
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
    # Atomic writes use .json.tmp suffix (4 chars longer than .json)
    # suffix_len: _md5prefix(9) + .json.tmp(9) = 18
    suffix_len = 18
    markers_dir = get_markers_dir()

    if os.name == "nt":
        # Windows MAX_PATH = 260. Full path = markers_dir / filename
        # Must fit: dir_sep(1) + safe_name + suffix(18) <= 260 - len(markers_dir)
        max_base_len = 260 - len(str(markers_dir)) - 1 - suffix_len
    else:
        # macOS/Linux: 255 char filename limit, no full-path limit
        max_base_len = 255 - suffix_len  # = 237

    max_base_len = max(max_base_len, 50)  # floor to keep filenames usable

    if len(safe_name) > max_base_len:
        path_hash = hashlib.md5(archive_path.encode()).hexdigest()[:8]
        safe_name = safe_name[:max_base_len - 9] + "_" + path_hash

    return markers_dir / f"{safe_name}_{md5[:8]}.json"


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
    except (ValueError, OSError):
        return None


# A marker the rebuild wrote for an archive it never saw extract, crediting it
# with its whole folder. Purge still honours it, so the files stay protected,
# but nothing counts it as proof the archive is synced: in a folder holding
# other archives, the folder's contents say nothing about this one, and taking
# them as proof marked packs that never downloaded as done, forever.
GUESSED = "guessed"


def save_marker(
    archive_path: str,
    md5: str,
    extracted_files: dict,
    extracted_to: str = "",
    guessed: bool = False,
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
    if guessed:
        marker[GUESSED] = True

    marker_path = get_marker_path(archive_path, md5)
    marker_path.parent.mkdir(parents=True, exist_ok=True)

    # Atomic write: write to .tmp then rename
    tmp_path = marker_path.with_suffix(".json.tmp")
    with open(tmp_path, "w") as f:
        json.dump(marker, f, indent=2)
    tmp_path.replace(marker_path)

    _invalidate_claims()
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
        full_path = resolve_existing_path(base_path / rel_path)
        if full_path is None:
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
        f for f in _marker_files(markers_dir)
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
        except (ValueError, OSError):
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
            _invalidate_claims()
            return True
        except OSError:
            pass
    return False


GUESSES_FLAGGED = ".guessed_markers_flagged"


def flag_guessed_markers(on_progress=None) -> int:
    """Tag the guesses older versions wrote untagged, once per library.

    A guess credits its archive with the whole folder, so every archive the
    rebuild guessed in one folder carries the same file list. Markers sharing
    a folder and an identical list are those guesses.

    Only a group whose list holds fewer charts than the packs claiming it is
    tagged: then at least that many packs never arrived, and the next sync
    downloads the group. With a chart for every pack, all of them can be
    there, and tagging would re-download what the library has. Measured on a
    real library by opening every pack: tagging every group spent 7.48 GB
    re-downloading to recover 1.17 GB; this recovers 26 of those 27 packs for
    0.62 GB. Purge keeps protecting the files of a tagged marker.
    `on_progress(done, total)` follows the reading. Returns how many were
    tagged.
    """
    from collections import defaultdict

    from ..core.constants import CHART_MARKERS
    from ..core.logging import debug_log

    flag = get_library_state_dir() / GUESSES_FLAGGED
    if flag.exists():
        return 0

    loaded = _read_markers([f for f in _marker_files(get_markers_dir())
                            if not f.name.startswith("failed_")], on_progress)

    groups = defaultdict(list)
    for marker_file, marker in loaded:
        if marker is None:
            continue
        files = marker.get("files") or {}
        if not files or marker.get(GUESSED):
            continue
        folder = marker.get("archive_path", "").rsplit("/", 1)[0]
        groups[(folder, frozenset(files))].append((marker_file, marker))

    tagged = 0
    for (_, files), members in groups.items():
        if len(members) < 2:
            continue
        charts = {p.rsplit("/", 1)[0] for p in files
                  if p.rsplit("/", 1)[-1].lower() in CHART_MARKERS}
        if len(members) <= len(charts):
            continue  # a chart for every pack: all of them may be there
        for marker_file, marker in members:
            marker[GUESSED] = True
            tmp = marker_file.with_suffix(".json.tmp")
            try:
                tmp.write_text(json.dumps(marker, indent=2))
                tmp.replace(marker_file)
                tagged += 1
            except OSError:
                pass
    _invalidate_claims()
    flag.write_text(f"{tagged}\n")
    debug_log(f"MARKERS | tagged {tagged} guessed markers")
    return tagged


def count_drive_markers(drive_name: str) -> int:
    """How many markers the library has for one drive, by file name alone."""
    markers_dir = get_markers_dir()
    prefix = normalize_path_key(drive_name).replace("/", "_").replace("\\", "_") + "_"
    return sum(1 for f in _marker_files(markers_dir)
               if normalize_path_key(f.stem).startswith(prefix))


def get_marked_drive_names() -> set[str]:
    """Drive folder names that have at least one marker.

    A marker is proof we extracted into that folder, which is the evidence
    ownership needs. `get_all_marker_files` cannot answer this: its paths are
    relative to the drive folder and so have already dropped the drive name.
    """
    names = set()
    markers_dir = get_markers_dir()
    if not markers_dir.exists():
        return names
    for _, marker in _read_markers(_marker_files(markers_dir)):
        archive_path = (marker or {}).get("archive_path", "")
        top = archive_path.split("/")[0] if archive_path else ""
        if top:
            names.add(top)
    return names


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

    for _, marker in _read_markers(_marker_files(markers_dir)):
        if marker:
            all_files.update(marker.get("files", {}).keys())

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

    markers.extend(m for _, m in _read_markers(_marker_files(markers_dir)) if m is not None)

    return markers


_claims_index: "dict | None" = None


def _invalidate_claims():
    """Drop the cached claims index. Every marker write calls this."""
    global _claims_index
    _claims_index = None


def _claims() -> dict:
    """Map of extracted file path -> markers claiming to have produced it.

    Built once and reused: callers hit this per archive, and rereading every
    marker each time would cost far more than the lookup saves.
    """
    global _claims_index
    if _claims_index is not None:
        return _claims_index

    index: dict = {}
    for marker in get_all_markers():
        for rel_path in marker.get("files", {}):
            index.setdefault(normalize_path_key(rel_path), []).append(marker)
    _claims_index = index
    return index


def find_marker_delivering(files, archive_path: str, base_path: Path) -> Optional[dict]:
    """A different archive that already put these exact files on disk.

    Two archives on Drive can unpack to the same chart folder: the same chart
    uploaded twice, once loose and once inside a folder, or names differing
    only in case or punctuation. They overwrite each other, so whichever went
    last is what is on disk, and the other's marker can never verify again.
    Treating the loser as missing re-downloads it every sync forever, and
    reports the chart as unsynced the whole time.

    So whichever archive is actually on disk wins. Returns its marker, or None
    when the files are genuinely absent rather than delivered by a twin.
    """
    index = _claims()
    seen = set()
    for rel_path in files:
        for other in index.get(normalize_path_key(rel_path), ()):
            other_path = other.get("archive_path", "")
            if other_path == archive_path or other_path in seen or other.get(GUESSED):
                continue
            seen.add(other_path)
            if verify_marker(other, base_path):
                return other
    return None


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
        except (ValueError, OSError):
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


# ---------------------------------------------------------------------------
# Failed markers — extraction failures (e.g., path length limits)
# Markers expire after FAILED_MARKER_TTL_DAYS so environment changes
# (e.g., enabling Windows long paths) trigger an automatic retry.
# ---------------------------------------------------------------------------

FAILED_MARKER_TTL_DAYS = 7

def _get_failed_marker_path(archive_path: str, md5: str) -> Path:
    """Compute failed marker file path for an archive (same naming as get_marker_path but with failed_ prefix)."""
    import hashlib

    safe_name = normalize_path_key(archive_path).replace("/", "_").replace("\\", "_")
    suffix_len = 18  # _md5prefix(9) + .json.tmp(9)
    markers_dir = get_markers_dir()

    if os.name == "nt":
        max_base_len = 260 - len(str(markers_dir)) - 1 - suffix_len - 7  # 7 for "failed_"
    else:
        max_base_len = 255 - suffix_len - 7  # = 230

    max_base_len = max(max_base_len, 50)

    if len(safe_name) > max_base_len:
        path_hash = hashlib.md5(archive_path.encode()).hexdigest()[:8]
        safe_name = safe_name[:max_base_len - 9] + "_" + path_hash

    return markers_dir / f"failed_{safe_name}_{md5[:8]}.json"


def save_failed_marker(archive_path: str, md5: str, error: str) -> Path:
    """Save a failed marker for an archive that permanently failed extraction."""
    marker = {
        "archive_path": archive_path,
        "md5": md5,
        "error": error,
        "failed_at": datetime.now().isoformat(),
    }

    marker_path = _get_failed_marker_path(archive_path, md5)
    marker_path.parent.mkdir(parents=True, exist_ok=True)

    tmp_path = marker_path.with_suffix(".json.tmp")
    with open(tmp_path, "w") as f:
        json.dump(marker, f, indent=2)
    tmp_path.replace(marker_path)

    return marker_path


def is_permanently_failed(archive_path: str, md5: str) -> bool:
    """Check if an archive has a non-expired failed marker."""
    marker_path = _get_failed_marker_path(archive_path, md5)
    if not marker_path.exists():
        return False
    try:
        age_seconds = (datetime.now() - datetime.fromtimestamp(marker_path.stat().st_mtime)).total_seconds()
        if age_seconds > FAILED_MARKER_TTL_DAYS * 86400:
            marker_path.unlink(missing_ok=True)
            return False
    except OSError:
        return False
    return True


def load_failed_marker(archive_path: str, md5: str) -> Optional[dict]:
    """Load failed marker for an archive if it exists."""
    marker_path = _get_failed_marker_path(archive_path, md5)
    if not marker_path.exists():
        return None
    try:
        with open(marker_path) as f:
            return json.load(f)
    except (ValueError, OSError):
        return None


def get_all_failed_markers() -> list[dict]:
    """Load all failed marker files."""
    markers = []
    markers_dir = get_markers_dir()
    if not markers_dir.exists():
        return markers

    for marker_file in _marker_files(markers_dir, "failed_*.json"):
        try:
            with open(marker_file) as f:
                markers.append(json.load(f))
        except (ValueError, OSError):
            continue

    return markers


def delete_failed_markers_for_archive(archive_path: str) -> int:
    """Delete ALL failed markers for an archive path (any MD5)."""
    markers_dir = get_markers_dir()
    if not markers_dir.exists():
        return 0

    safe_name = normalize_path_key(archive_path).replace("/", "_").replace("\\", "_")
    deleted = 0
    for marker_file in _marker_files(markers_dir, "failed_*.json"):
        if normalize_path_key(marker_file.stem).startswith(f"failed_{safe_name}_"):
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

    An archive sharing its folder with other archives gets a GUESSED marker:
    purge honours it, nothing takes it as proof the archive is synced.

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
        packs_in = Counter(info["parent"] for info in archives.values())

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
                        # Never claim a partial download or OS litter. Both are
                        # things purge will not keep: a partial gets removed, and
                        # a ._ sidecar is regenerated rather than tracked. Either
                        # one in a marker leaves it describing files that do not
                        # match disk, and the planner re-fetches the whole
                        # archive. The sidecar of a partial is named
                        # ".__download_x.zip", so the prefix check alone misses it.
                        from ..sync.purge_planner import _is_ignored
                        if item.name.startswith("_download_") or _is_ignored(item.name, None):
                            continue
                        # An archive is never its own extracted output. When an
                        # extraction failed, the archive is all that is left in
                        # the folder, and recording it here writes a marker that
                        # says "done" while listing nothing that came out of it.
                        # That marker then verifies forever, because the archive
                        # really is on disk, so the chart is never retried and
                        # the summary reports it as synced.
                        if item.name == info["name"]:
                            continue
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

            # Alone in its folder, the folder is its output. Beside other
            # archives it may be one that failed or never ran: a guess.
            save_marker(
                archive_path=archive_path,
                md5=md5,
                extracted_files=extracted_files,
                guessed=packs_in[info["parent"]] > 1,
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

