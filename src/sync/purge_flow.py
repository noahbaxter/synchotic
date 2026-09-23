"""
Purge orchestration for DM Chart Sync.

Walks every drive to find files nothing accounts for and deletes them, using
marker files as source of truth. Split out of folder_sync.py, which now only
covers downloading; this covers only deleting.
"""

from pathlib import Path

from ..core.formatting import sanitize_drive_name
from ..core.logging import debug_log
from ..ui.primitives import print_section_header, print_separator
from ..ui.widgets import display
from .cache import clear_folder_cache, get_persistent_stats_cache
from .purge_planner import plan_purge, find_partial_downloads
from .purger import delete_files


PURGE_CONFIRM_FILE_THRESHOLD = 100
PURGE_CONFIRM_SIZE_THRESHOLD = 500 * 1024**2  # 500 MB


def _purge_disabled_drive(
    folder_id: str, folder_name: str, folder_path: Path, base_path: Path,
    persistent_cache,
) -> tuple[int, int, int]:
    """Purge all files from a disabled drive. Returns (deleted, failed, size)."""
    local_files = [(f, f.stat().st_size if f.exists() else 0)
                  for f in folder_path.rglob("*") if f.is_file()]
    if not local_files:
        return 0, 0, 0

    folder_size = sum(size for _, size in local_files)
    display.purge_drive_disabled(folder_name, len(local_files), folder_size)

    # Invalidate BEFORE delete — crash-safe (empty cache rebuilds correctly)
    persistent_cache.invalidate(folder_id)
    deleted, failed = delete_files(local_files, base_path, cleanup_path=folder_path)
    display.purge_removed(deleted, failed)
    return deleted, failed, folder_size


def _purge_enabled_drive(
    folder: dict, folder_path: Path, base_path: Path,
    user_settings, failed_setlists, marker_norm: set, persistent_cache,
) -> tuple[int, int, int]:
    """Purge orphaned files from an enabled drive. Returns (deleted, failed, size)."""
    from ..core.formatting import format_size
    from ..ui.components import format_purge_tree

    folder_id = folder.get("folder_id", "")
    folder_name = folder.get("name", "")

    files_to_purge, _ = plan_purge(
        [folder], base_path, user_settings, failed_setlists,
        precomputed_markers=marker_norm,
    )
    if not files_to_purge:
        return 0, 0, 0

    folder_size = sum(size for _, size in files_to_purge)
    display.purge_folder(folder_name, len(files_to_purge), folder_size)
    display.purge_tree_lines(format_purge_tree(files_to_purge, base_path))

    purge_count = len(files_to_purge)
    if purge_count > PURGE_CONFIRM_FILE_THRESHOLD or folder_size > PURGE_CONFIRM_SIZE_THRESHOLD:
        from ..ui.widgets.confirm import ConfirmDialog
        dialog = ConfirmDialog(
            f"Purge {purge_count:,} files ({format_size(folder_size)}) from {folder_name}?"
        )
        if not dialog.run():
            debug_log(f"PURGE_SKIPPED | folder={folder_name} | user declined")
            print(f"  Skipped.")
            return 0, 0, 0

    # Invalidate affected setlists BEFORE delete — crash-safe
    affected_sanitized = set()
    for file_path, _ in files_to_purge:
        try:
            affected_sanitized.add(file_path.relative_to(folder_path).parts[0])
        except (ValueError, IndexError):
            pass
    if affected_sanitized:
        for raw_name in list(persistent_cache.get_all_setlists(folder_id)):
            if sanitize_drive_name(raw_name) in affected_sanitized:
                persistent_cache.invalidate_setlist(folder_id, raw_name)

    deleted, failed = delete_files(files_to_purge, base_path, cleanup_path=folder_path)
    display.purge_removed(deleted, failed)
    return deleted, failed, folder_size


def _purge_partial_downloads(base_path: Path) -> tuple[int, int, int]:
    """Clean up incomplete downloads. Returns (deleted, failed, size)."""
    partial_files = find_partial_downloads(base_path)
    if not partial_files:
        return 0, 0, 0

    partial_size = sum(size for _, size in partial_files)
    display.purge_partial_downloads(len(partial_files), partial_size)
    deleted, failed = delete_files(partial_files, base_path)
    display.purge_partial_cleaned(deleted, failed)
    return deleted, failed, partial_size


def purge_all_folders(
    folders: list,
    base_path: Path,
    user_settings=None,
    failed_setlists: dict[str, set[str]] | None = None,
):
    """Purge files that shouldn't be synced. Uses marker files as source of truth."""
    from ..core.formatting import normalize_path_key
    from .markers import get_all_marker_files
    from .ownership import (backfill_owned_from_markers, is_library_adopted,
                            mark_library_adopted, resolve_owned_drives)

    print_section_header("Purge")

    # A library we have never synced may be one the user already had. Their
    # folders can share drive names, so deleting anything here is a guess.
    if not is_library_adopted():
        display.purge_skipped_new_library(base_path)
        mark_library_adopted()
        return set()

    # Markers we already have prove which drives are ours, so an upgrading user
    # does not lose purge on drives they synced before ownership existed.
    backfill_owned_from_markers(folders)
    owned = resolve_owned_drives(folders)

    total_deleted = 0
    total_failed = 0
    total_size = 0
    purged_folder_ids: set[str] = set()
    persistent_cache = get_persistent_stats_cache()

    # Compute markers ONCE for all folders
    from ..ui.primitives import print_progress

    print_progress("Purge: reading markers...")
    all_marker_files = get_all_marker_files()
    marker_norm = {normalize_path_key(p) for p in all_marker_files}

    # Each drive is walked in full to find files nothing accounts for, which is
    # seconds per drive on a network library. Name the drive, or purge looks
    # like it has stopped at the point where it is about to delete things.
    total_drives = len(folders)
    for drive_index, folder in enumerate(folders, start=1):
        folder_id = folder.get("folder_id", "")
        folder_path = base_path / folder.get("name", "")

        if not folder_path.exists():
            continue

        print_progress(
            f"Purge: checking {folder.get('name', '')} ({drive_index}/{total_drives})"
        )

        drive_enabled = user_settings.is_drive_enabled(folder_id) if user_settings else True

        if not drive_enabled:
            # Emptying a whole folder is only safe when we made it. A disabled
            # drive whose folder we never synced is the user's own collection
            # that happens to share a name.
            if folder_id not in owned:
                display.purge_skipped_unowned(folder.get("name", ""))
                debug_log(f"PURGE_SKIP_UNOWNED | folder={folder.get('name', '')}")
                continue
            deleted, failed, size = _purge_disabled_drive(
                folder_id, folder.get("name", ""), folder_path, base_path, persistent_cache,
            )
        else:
            deleted, failed, size = _purge_enabled_drive(
                folder, folder_path, base_path,
                user_settings, failed_setlists, marker_norm, persistent_cache,
            )

        total_deleted += deleted
        total_failed += failed
        total_size += size
        if deleted > 0:
            purged_folder_ids.add(folder_id)
        print("\033[2K\r", end="", flush=True)

    deleted, failed, size = _purge_partial_downloads(base_path)
    total_deleted += deleted
    total_failed += failed
    total_size += size

    print()
    print_separator()
    if total_deleted > 0 or total_failed > 0:
        display.purge_summary(total_deleted, total_size, total_failed)
    else:
        display.purge_nothing()

    # Invalidate in-memory filesystem cache for folders that changed
    for folder in folders:
        fid = folder.get("folder_id", "")
        if fid in purged_folder_ids:
            clear_folder_cache(base_path / folder.get("name", ""))

    return purged_folder_ids
