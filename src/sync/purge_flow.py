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
    persistent_cache, progress=None,
) -> tuple[int, int, int]:
    """Purge all files from a disabled drive. Returns (deleted, failed, size)."""
    local_files = [(f, f.stat().st_size if f.exists() else 0)
                  for f in folder_path.rglob("*") if f.is_file()]
    if not local_files:
        return 0, 0, 0

    folder_size = sum(size for _, size in local_files)
    if not progress:
        display.purge_drive_disabled(folder_name, len(local_files), folder_size)

    # Invalidate BEFORE delete — crash-safe (empty cache rebuilds correctly)
    persistent_cache.invalidate(folder_id)
    deleted, failed = delete_files(local_files, base_path, cleanup_path=folder_path)
    if not progress:
        display.purge_removed(deleted, failed)
    return deleted, failed, folder_size


def _purge_enabled_drive(
    folder: dict, folder_path: Path, base_path: Path,
    user_settings, failed_setlists, marker_norm: set, persistent_cache,
    progress=None, pause_keys=None, resume_keys=None,
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
    if not progress:
        display.purge_folder(folder_name, len(files_to_purge), folder_size)
        display.purge_tree_lines(format_purge_tree(files_to_purge, base_path))

    purge_count = len(files_to_purge)
    if purge_count > PURGE_CONFIRM_FILE_THRESHOLD or folder_size > PURGE_CONFIRM_SIZE_THRESHOLD:
        from contextlib import nullcontext

        from ..ui.widgets.confirm import ConfirmDialog
        # The dialog reads keys and draws itself: pause the key reader (or it
        # steals keystrokes) and the paint loop (or it paints over the dialog).
        if pause_keys:
            pause_keys()
        try:
            with (progress.suspended() if progress else nullcontext()):
                dialog = ConfirmDialog(
                    f"Purge {purge_count:,} files ({format_size(folder_size)}) from {folder_name}?"
                )
                confirmed = dialog.run()
        finally:
            if resume_keys:
                resume_keys()
        if not confirmed:
            debug_log(f"PURGE_SKIPPED | folder={folder_name} | user declined")
            if progress:
                progress.note(folder_name, context="purge skipped")
            else:
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
    if not progress:
        display.purge_removed(deleted, failed)
    return deleted, failed, folder_size


def _purge_partial_downloads(base_path: Path, progress=None) -> tuple[int, int, int]:
    """Clean up incomplete downloads. Returns (deleted, failed, size)."""
    partial_files = find_partial_downloads(base_path)
    if not partial_files:
        return 0, 0, 0

    partial_size = sum(size for _, size in partial_files)
    if not progress:
        display.purge_partial_downloads(len(partial_files), partial_size)
    deleted, failed = delete_files(partial_files, base_path)
    if progress:
        progress.note("Partial downloads", context=f"{deleted} cleaned up")
    else:
        display.purge_partial_cleaned(deleted, failed)
    return deleted, failed, partial_size


def purge_all_folders(
    folders: list,
    base_path: Path,
    user_settings=None,
    failed_setlists: dict[str, set[str]] | None = None,
    progress=None,
    cancel_check=None,
    pause_keys=None,
    resume_keys=None,
):
    """Purge files that shouldn't be synced. Uses marker files as source of truth.

    Args:
        progress: The sync run's panel; purge draws into it instead of printing.
        cancel_check: Polled between drives. A drive already deleting finishes.
        pause_keys/resume_keys: Hand stdin to ConfirmDialog and take it back.
    """
    from ..core.formatting import normalize_path_key
    from .markers import get_all_marker_files
    from .ownership import (backfill_owned_from_markers, is_library_adopted,
                            mark_library_adopted, resolve_owned_drives)

    if progress:
        progress.set_title("")  # the phase word already says PURGE
    else:
        print_section_header("Purge")

    # A library we have never synced may be one the user already had. Their
    # folders can share drive names, so deleting anything here is a guess.
    if not is_library_adopted():
        if progress:
            progress.note("Purge", context="skipped: new library")
        else:
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

    if progress:
        progress.set_stage("reading markers...")
    else:
        print_progress("Purge: reading markers...")
    all_marker_files = get_all_marker_files()
    marker_norm = {normalize_path_key(p) for p in all_marker_files}

    # Each drive is walked in full to find files nothing accounts for, which is
    # seconds per drive on a network library. Name the drive, or purge looks
    # like it has stopped at the point where it is about to delete things.
    total_drives = len(folders)
    if progress:
        progress.set_run_total(total_drives, "drives")

    for drive_index, folder in enumerate(folders, start=1):
        # ESC finishes the drive already in flight, then stops here, before
        # the next one starts. Nothing already deleted is undone.
        if cancel_check and cancel_check():
            debug_log(f"PURGE_CANCELLED | after={drive_index - 1}/{total_drives}")
            break

        folder_id = folder.get("folder_id", "")
        folder_path = base_path / folder.get("name", "")

        if not folder_path.exists():
            if progress:
                progress.advance_run()
            continue

        if progress:
            # No count: the bar above already says which drive of how many.
            progress.set_stage(f"checking {folder.get('name', '')}")
        else:
            print_progress(
                f"Purge: checking {folder.get('name', '')} ({drive_index}/{total_drives})"
            )

        drive_enabled = user_settings.is_drive_enabled(folder_id) if user_settings else True

        if not drive_enabled:
            # Emptying a whole folder is only safe when we made it. A disabled
            # drive whose folder we never synced is the user's own collection
            # that happens to share a name.
            if folder_id not in owned:
                if not progress:
                    display.purge_skipped_unowned(folder.get("name", ""))
                debug_log(f"PURGE_SKIP_UNOWNED | folder={folder.get('name', '')}")
                if progress:
                    progress.advance_run()
                continue
            deleted, failed, size = _purge_disabled_drive(
                folder_id, folder.get("name", ""), folder_path, base_path, persistent_cache,
                progress=progress,
            )
        else:
            deleted, failed, size = _purge_enabled_drive(
                folder, folder_path, base_path,
                user_settings, failed_setlists, marker_norm, persistent_cache,
                progress=progress, pause_keys=pause_keys, resume_keys=resume_keys,
            )

        total_deleted += deleted
        total_failed += failed
        total_size += size
        if deleted > 0:
            purged_folder_ids.add(folder_id)
            if progress:
                from ..core.formatting import format_size
                progress.note(folder.get("name", ""),
                              context=f"{deleted} purged ({format_size(size)})")
        if progress:
            progress.advance_run()
        if not progress:
            print("\033[2K\r", end="", flush=True)

    deleted, failed, size = _purge_partial_downloads(base_path, progress=progress)
    total_deleted += deleted
    total_failed += failed
    total_size += size

    if progress:
        progress.set_stage("")
        from ..core.formatting import format_size
        if total_deleted > 0 or total_failed > 0:
            context = f"{total_deleted} removed ({format_size(total_size)})"
            if total_failed:
                context += f", {total_failed} failed"
        else:
            context = "nothing to remove"
        progress.note("Purge complete", context=context)
    else:
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
