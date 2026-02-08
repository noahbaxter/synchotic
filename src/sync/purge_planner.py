"""
Purge planning for DM Chart Sync.

Determines what files should be deleted (disabled drives, extra files, videos, partials).
Uses marker files as the source of truth for extracted archive contents.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple, Set

from ..core.constants import VIDEO_EXTENSIONS
from ..core.formatting import relative_posix, parent_posix, sanitize_path, sanitize_filename, normalize_path_key
from ..core.logging import debug_log
from .cache import scan_local_files
from .markers import get_all_marker_files, get_all_markers
from .sync_checker import is_archive_file


PURGE_RATIO_LIMIT = 0.15   # 15%
PURGE_SIZE_LIMIT = 2 * 1024**3  # 2 GB


def check_purge_safety(local_file_count, purge_count, purge_size):
    """Returns (is_safe, reason) — blocks if >15% of files or >2GB."""
    if local_file_count == 0:
        return True, ""
    ratio = purge_count / local_file_count
    if ratio > PURGE_RATIO_LIMIT:
        return False, f"{ratio:.0%} of files ({purge_count:,}/{local_file_count:,})"
    if purge_size > PURGE_SIZE_LIMIT:
        return False, f"{purge_size / 1024**3:.1f} GB exceeds limit"
    return True, ""


@dataclass
class PurgeStats:
    """Detailed breakdown of what would be purged."""
    chart_count: int = 0
    chart_size: int = 0
    extra_file_count: int = 0
    extra_file_size: int = 0
    partial_count: int = 0
    partial_size: int = 0
    video_count: int = 0
    video_size: int = 0
    estimated_charts: int = 0

    @property
    def total_files(self) -> int:
        return self.chart_count + self.extra_file_count + self.partial_count + self.video_count

    @property
    def total_size(self) -> int:
        return self.chart_size + self.extra_file_size + self.partial_size + self.video_size


def find_partial_downloads(base_path: Path, local_files: dict = None) -> List[Tuple[Path, int]]:
    """
    Find partial download files (files with _download_ prefix).
    """
    partial_files = []
    if not base_path.exists():
        return partial_files

    if local_files is not None:
        for rel_path, size in local_files.items():
            filename = rel_path.split("/")[-1] if "/" in rel_path else rel_path
            if filename.startswith("_download_"):
                partial_files.append((base_path / rel_path, size))
        return partial_files

    for f in base_path.rglob("_download_*"):
        if f.is_file():
            try:
                partial_files.append((f, f.stat().st_size))
            except Exception:
                partial_files.append((f, 0))

    return partial_files


def find_extra_files(
    folder_name: str,
    folder_path: Path,
    marker_files: Set[str],
    manifest_paths: Set[str],
    local_files: dict = None,
) -> List[Tuple[Path, int]]:
    """
    Find local files not tracked in markers AND not in manifest.

    Args:
        folder_name: Name of the folder (for building paths)
        folder_path: Path to the folder on disk
        marker_files: Set of file paths from all markers (lowercase)
        manifest_paths: Set of manifest paths for this folder (lowercase)
        local_files: Optional pre-scanned local files dict

    Returns:
        List of (Path, size) tuples for extra files
    """
    if local_files is None:
        local_files = scan_local_files(folder_path)
    if not local_files:
        return []

    extras = []
    for rel_path, size in local_files.items():
        # Skip partial downloads - handled by find_partial_downloads()
        filename = rel_path.split("/")[-1] if "/" in rel_path else rel_path
        if filename.startswith("_download_"):
            continue

        # Markers store paths relative to drive folder (no drive prefix)
        marker_path = normalize_path_key(rel_path)
        # Manifest paths include drive prefix
        manifest_path = normalize_path_key(f"{folder_name}/{rel_path}")

        # Check markers (extracted archive contents)
        if marker_path in marker_files:
            continue

        # Fallback: markers may store paths with drive prefix
        if manifest_path in marker_files:
            continue

        # Check manifest (loose files + archives themselves)
        if manifest_path in manifest_paths:
            continue

        extras.append((folder_path / rel_path, size))

    # Diagnostic logging for suspicious purge volumes
    if len(extras) > 50:
        debug_log(f"PURGE_DIAG | folder={folder_name} | extras={len(extras)} | local_files={len(local_files)} | marker_count={len(marker_files)}")
        for i, (path, size) in enumerate(extras[:5]):
            rel = str(path.relative_to(folder_path)).replace("\\", "/")
            norm = normalize_path_key(rel)
            prefixed = normalize_path_key(f"{folder_name}/{rel}")
            in_markers = norm in marker_files
            in_markers_prefixed = prefixed in marker_files
            debug_log(f"PURGE_DIAG | extra[{i}] raw={rel} | norm={norm} | in_markers={in_markers} | prefixed_in_markers={in_markers_prefixed}")

        sample = list(marker_files)[:5]
        for i, p in enumerate(sample):
            debug_log(f"PURGE_DIAG | marker_sample[{i}]={p}")

        for marker in get_all_markers()[:3]:
            archive = marker.get("archive_path", "?")
            files_sample = list(marker.get("files", {}).keys())[:3]
            debug_log(f"PURGE_DIAG | marker_raw | archive={archive} | files={files_sample}")

    return extras


def plan_purge(
    folders: list,
    base_path: Path,
    user_settings=None,
    failed_setlists: dict[str, set[str]] | None = None,
    precomputed_markers: set[str] | None = None,
) -> Tuple[List[Tuple[Path, int]], PurgeStats]:
    """
    Plan what files should be purged.

    Valid files come from two sources:
    1. Marker files - track extracted archive contents
    2. Manifest - tracks loose files and archive files themselves

    Everything else on disk is "extra" and should be purged.
    """
    stats = PurgeStats()
    all_files = []

    # Get ALL tracked files from markers (one lookup, used for all folders)
    if precomputed_markers is not None:
        marker_files_normalized = precomputed_markers
    else:
        all_marker_files = get_all_marker_files()
        marker_files_normalized = {normalize_path_key(p) for p in all_marker_files}
    debug_log(f"PURGE | marker_files={len(marker_files_normalized)}")

    for folder in folders:
        folder_name = folder.get("name", "")
        prefix = normalize_path_key(folder_name + "/")
        with_prefix = sum(1 for p in marker_files_normalized if p.startswith(prefix))
        debug_log(f"PURGE_MARKERS | folder={folder_name} | paths_with_prefix={with_prefix} | paths_without={len(marker_files_normalized) - with_prefix}")

    for folder in folders:
        folder_id = folder.get("folder_id", "")
        folder_name = folder.get("name", "")
        folder_path = base_path / folder_name

        if not folder_path.exists():
            continue

        local_files = scan_local_files(folder_path)
        if not local_files:
            continue

        drive_enabled = user_settings.is_drive_enabled(folder_id) if user_settings else True

        if not drive_enabled:
            # Drive is disabled - purge ALL local files
            chart_parents = set()
            for rel_path, size in local_files.items():
                stats.chart_count += 1
                stats.chart_size += size
                all_files.append((folder_path / rel_path, size))
                if is_archive_file(rel_path):
                    stats.estimated_charts += 1
                else:
                    chart_parents.add(parent_posix(rel_path))
            stats.estimated_charts += len(chart_parents)
            continue

        # Find partial downloads
        partial_files = find_partial_downloads(folder_path, local_files)
        if partial_files:
            stats.partial_count += len(partial_files)
            stats.partial_size += sum(size for _, size in partial_files)
            stats.estimated_charts += len(partial_files)
            all_files.extend(partial_files)

        # Get disabled setlists (sanitize names to match local filesystem paths)
        disabled_setlists_raw = user_settings.get_disabled_subfolders(folder_id) if user_settings else set()
        disabled_setlists = {sanitize_filename(name) for name in disabled_setlists_raw}

        # Get failed setlists (scan failed — protect their files from purge)
        failed_names_raw = failed_setlists.get(folder_id, set()) if failed_setlists else set()
        failed_names = {sanitize_filename(name) for name in failed_names_raw}
        if failed_names:
            debug_log(f"PURGE_SKIP | folder={folder_name} | protecting {len(failed_names)} failed setlists: {failed_names}")

        # Count files in disabled setlists (these get purged)
        # Also track files in failed setlists (these are protected)
        disabled_setlist_paths = set()
        failed_setlist_paths = set()
        disabled_chart_parents = set()
        for rel_path, size in local_files.items():
            first_slash = rel_path.find("/")
            setlist_name = rel_path[:first_slash] if first_slash != -1 else rel_path
            # Sanitize to match disabled_setlists (which are also sanitized)
            setlist_name = sanitize_filename(setlist_name)
            if setlist_name in failed_names:
                failed_setlist_paths.add(rel_path)
                continue  # Don't purge files in failed setlists
            if setlist_name in disabled_setlists:
                disabled_setlist_paths.add(rel_path)
                stats.chart_count += 1
                stats.chart_size += size
                all_files.append((folder_path / rel_path, size))
                if is_archive_file(rel_path):
                    stats.estimated_charts += 1
                else:
                    disabled_chart_parents.add(parent_posix(rel_path))
        stats.estimated_charts += len(disabled_chart_parents)

        # Build manifest paths (loose files + archives in enabled setlists)
        manifest_paths: Set[str] = set()
        manifest_files = folder.get("files")

        if manifest_files is None:
            # Folder not scanned - skip entirely to avoid purging valid content
            debug_log(f"PURGE_SKIP | folder={folder_name} | not scanned, skipping entirely")
            continue

        for f in manifest_files:
            file_path = f.get("path", "")
            first_slash = file_path.find("/")
            setlist_name = file_path[:first_slash] if first_slash != -1 else file_path
            if setlist_name in disabled_setlists:
                continue
            sanitized = sanitize_path(file_path)
            manifest_paths.add(normalize_path_key(f"{folder_name}/{sanitized}"))

        # Find extra files (not in markers, not in manifest)
        extras = find_extra_files(
            folder_name, folder_path, marker_files_normalized, manifest_paths, local_files
        )

        extra_paths = set()
        for f, size in extras:
            rel_path = relative_posix(f, folder_path)
            extra_paths.add(rel_path)
            if rel_path in failed_setlist_paths:
                continue  # Don't purge files in failed setlists
            if rel_path not in disabled_setlist_paths:
                stats.extra_file_count += 1
                stats.extra_file_size += size
                all_files.append((f, size))
                if is_archive_file(rel_path):
                    stats.estimated_charts += 1

        # Video files
        delete_videos = user_settings.delete_videos if user_settings else True
        if delete_videos:
            for rel_path, size in local_files.items():
                if rel_path in disabled_setlist_paths or rel_path in extra_paths or rel_path in failed_setlist_paths:
                    continue
                if Path(rel_path).suffix.lower() in VIDEO_EXTENSIONS:
                    stats.video_count += 1
                    stats.video_size += size
                    all_files.append((folder_path / rel_path, size))

    # Deduplicate
    seen = set()
    unique_files = []
    for f, size in all_files:
        if f not in seen:
            seen.add(f)
            unique_files.append((f, size))

    return unique_files, stats


def count_purgeable_files(
    folders: list,
    base_path: Path,
    user_settings=None,
    failed_setlists: dict[str, set[str]] | None = None,
) -> Tuple[int, int, int]:
    """Count files that would be purged."""
    _, stats = plan_purge(folders, base_path, user_settings, failed_setlists)
    return stats.total_files, stats.total_size, stats.estimated_charts


def count_purgeable_detailed(
    folders: list,
    base_path: Path,
    user_settings=None,
    failed_setlists: dict[str, set[str]] | None = None,
) -> PurgeStats:
    """Count files that would be purged with detailed breakdown."""
    _, stats = plan_purge(folders, base_path, user_settings, failed_setlists)
    return stats
