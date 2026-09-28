"""Walks every drive to find files nothing accounts for and deletes them,
using marker files as source of truth, drawn on the sync run's panel."""

from pathlib import Path

from .. import copy
from ..config.settings import purges
from ..core.formatting import count, format_size, sanitize_drive_name
from ..core.logging import debug_log
from .cache import clear_folder_cache, get_persistent_stats_cache
from .purge_planner import plan_purge, find_partial_downloads
from .purger import delete_files


# Low enough that a handful of someone's own charts in a drive's folder is
# asked about, not cleaned up quietly. A chart is often 5 to 10 files.
PURGE_CONFIRM_FILE_THRESHOLD = 50
PURGE_CONFIRM_SIZE_THRESHOLD = 100 * 1024**2  # 100 MB


def _disabled_drive_files(folder_path: Path) -> list[tuple[Path, int]]:
    """Every file under a disabled drive's folder."""
    return [(f, f.stat().st_size if f.exists() else 0)
            for f in folder_path.rglob("*") if f.is_file()]


def _plan_enabled_drive(
    folder: dict, base_path: Path, user_settings, failed_setlists,
    marker_norm: set, progress,
) -> tuple[list[tuple[Path, int]], int, int]:
    """Orphaned files on an enabled drive, and how many of them (and how many
    bytes) are partial downloads."""
    folder_name = folder.get("name", "")

    def walked(n: int) -> None:
        progress.set_stage(copy.STAGE_CHECKING_COUNT.format(name=folder_name, count=count(n, "file")))

    files, stats = plan_purge(
        [folder], base_path, user_settings, failed_setlists,
        precomputed_markers=marker_norm, on_walk=walked,
    )
    return files, stats.partial_count, stats.partial_size


def _confirmed(files: int, size: int, progress, pause_keys, resume_keys) -> bool:
    """The one question a sync asks before deleting anything."""
    from ..ui.widgets.confirm import ConfirmDialog
    # The dialog reads keys and draws itself: pause the key reader (or it
    # steals keystrokes) and the paint loop (or it paints over the dialog).
    if pause_keys:
        pause_keys()
    try:
        with progress.suspended():
            return ConfirmDialog(copy.PURGE_CONFIRM.format(
                files=count(files, "file"), size=format_size(size))).run()
    finally:
        if resume_keys:
            resume_keys()


def _delete_drive(
    folder_id: str, folder_path: Path, files: list, base_path: Path,
    persistent_cache, whole_drive: bool,
) -> tuple[int, int]:
    """Delete one drive's planned files. Returns (deleted, failed)."""
    # Invalidate BEFORE delete, which is crash-safe: an empty cache rebuilds
    if whole_drive:
        persistent_cache.invalidate(folder_id)
    else:
        affected_sanitized = set()
        for file_path, _ in files:
            try:
                affected_sanitized.add(file_path.relative_to(folder_path).parts[0])
            except (ValueError, IndexError):
                pass
        if affected_sanitized:
            for raw_name in list(persistent_cache.get_all_setlists(folder_id)):
                if sanitize_drive_name(raw_name) in affected_sanitized:
                    persistent_cache.invalidate_setlist(folder_id, raw_name)

    return delete_files(files, base_path, cleanup_path=folder_path)


def _purge_partial_downloads(base_path: Path, progress,
                             already_walked=(), found=()) -> tuple[int, int, int]:
    """Clean up incomplete downloads outside the drives just purged, whose
    own passes already took theirs, plus `found`, ones those passes turned up
    but did not delete."""
    progress.set_stage(copy.STAGE_CHECKING.format(name=copy.NOTE_PARTIALS.lower()))
    partial_files = list(found) + find_partial_downloads(base_path, skip_dirs=already_walked)
    if not partial_files:
        return 0, 0, 0

    partial_size = sum(size for _, size in partial_files)
    deleted, failed = delete_files(partial_files, base_path)
    progress.note(copy.NOTE_PARTIALS, context=copy.NOTE_DELETED.format(files=count(deleted, "file")))
    return deleted, failed, partial_size


def purge_all_folders(
    folders: list,
    base_path: Path,
    user_settings=None,
    failed_setlists: dict[str, set[str]] | None = None,
    *,
    progress,
    cancel_check=None,
    pause_keys=None,
    resume_keys=None,
):
    """Purge files that shouldn't be synced. Uses marker files as source of truth.

    Every drive is planned first and nothing is deleted until the whole list
    is known, so a sync asks at most once, about the total. Declining (or
    cancelling during the walk) deletes nothing but partial downloads, which
    are our own debris and never part of the question.

    Args:
        progress: The sync run's panel, which purge draws into.
        cancel_check: Polled between drives while planning.
        pause_keys/resume_keys: Hand stdin to ConfirmDialog and take it back.
    """
    from ..core.formatting import normalize_path_key
    from .markers import get_all_marker_files
    from .ownership import (backfill_owned_from_markers, is_library_adopted,
                            mark_library_adopted, resolve_owned_drives)

    progress.set_title("")  # the phase word already says PURGE

    # A library we have never synced may be one the user already had. Their
    # folders can share drive names, so deleting anything here is a guess.
    if purges(user_settings) and not is_library_adopted():
        mark_library_adopted()
        return set()

    # Markers we already have prove which drives are ours, so an upgrading user
    # does not lose purge on drives they synced before ownership existed.
    backfill_owned_from_markers(folders)

    total_deleted = 0
    total_failed = 0
    total_size = 0
    purged_folder_ids: set[str] = set()
    walked_paths: list[Path] = []  # the partials sweep skips these
    plans = []  # (folder, folder_path, files, whole_drive)
    asked_files = asked_size = 0
    declined = False
    sweep = True
    partials_found = []

    if purges(user_settings):
        owned = resolve_owned_drives(folders)
        persistent_cache = get_persistent_stats_cache()

        # Compute markers ONCE for all folders
        progress.set_stage("")
        all_marker_files = get_all_marker_files()
        marker_norm = {normalize_path_key(p) for p in all_marker_files}

        # Each drive is walked in full to find files nothing accounts for, which
        # is seconds per drive on a network library. Name the drive, or purge
        # looks like it has stopped.
        total_drives = len(folders)
        progress.set_run_total(total_drives, "drives")

        cancelled = False
        for drive_index, folder in enumerate(folders, start=1):
            # ESC stops the walk before the next drive. Nothing has been
            # deleted yet, and nothing will be.
            if cancel_check and cancel_check():
                debug_log(f"PURGE_CANCELLED | after={drive_index - 1}/{total_drives}")
                cancelled = True
                break

            folder_id = folder.get("folder_id", "")
            folder_path = base_path / folder.get("name", "")

            if not folder_path.exists():
                progress.advance_run()
                continue

            # No count: the bar above already says which drive of how many.
            progress.set_stage(copy.STAGE_CHECKING.format(name=folder.get("name", "")))

            drive_enabled = user_settings.is_drive_enabled(folder_id) if user_settings else True

            if not drive_enabled:
                # Emptying a whole folder is only safe when we made it. A
                # disabled drive whose folder we never synced is the user's own
                # collection that happens to share a name.
                if folder_id not in owned:
                    debug_log(f"PURGE_SKIP_UNOWNED | folder={folder.get('name', '')}")
                    progress.advance_run()
                    continue
                files = _disabled_drive_files(folder_path)
                partials = partial_size = 0
            else:
                files, partials, partial_size = _plan_enabled_drive(
                    folder, base_path, user_settings, failed_setlists,
                    marker_norm, progress)
            walked_paths.append(folder_path)
            if files:
                plans.append((folder, folder_path, files, not drive_enabled))
                asked_files += len(files) - partials
                asked_size += sum(size for _, size in files) - partial_size
            progress.advance_run()

        if cancelled:
            # Stop means stop: not even the partials sweep, another walk.
            plans, sweep = [], False
        elif (asked_files > PURGE_CONFIRM_FILE_THRESHOLD
              or asked_size > PURGE_CONFIRM_SIZE_THRESHOLD):
            if not _confirmed(asked_files, asked_size, progress, pause_keys, resume_keys):
                debug_log(f"PURGE_SKIPPED | files={asked_files} | user declined")
                declined = True
                # The walked drives' partials were never part of the question,
                # and are already found, so the sweep takes them unwalked.
                partials_found = [f for _, _, files, _ in plans for f in files
                                  if f[0].name.startswith("_download_")]
                plans = []

        progress.set_stage("")
        for folder, folder_path, files, whole_drive in plans:
            folder_id = folder.get("folder_id", "")
            deleted, failed = _delete_drive(
                folder_id, folder_path, files, base_path, persistent_cache, whole_drive)
            size = sum(size for _, size in files)
            total_deleted += deleted
            total_failed += failed
            total_size += size
            if deleted > 0:
                purged_folder_ids.add(folder_id)
                progress.note(folder.get("name", ""), context=copy.NOTE_DELETED_SIZE.format(
                    files=count(deleted, "file"), size=format_size(size)))
    else:
        debug_log("PURGE_SKIPPED | purge_on_sync off")

    # Drives not deleted from still get their partials swept: those are ours.
    if sweep:
        deleted, failed, size = _purge_partial_downloads(
            base_path, progress=progress, already_walked=walked_paths,
            found=partials_found)
        total_deleted += deleted
        total_failed += failed
        total_size += size

    progress.set_stage("")
    if declined:
        context = copy.CANCELLED  # swept partials have their own row
    elif total_deleted > 0 or total_failed > 0:
        context = copy.NOTE_DELETED_SIZE.format(files=count(total_deleted, "file"),
                                                size=format_size(total_size))
        if total_failed:
            context += f", {total_failed:,} {copy.FAIL_UNKNOWN}"
    else:
        context = copy.NOTE_DELETED.format(files=count(0, "file"))
    progress.note(copy.PURGE, context=context)

    # Invalidate in-memory filesystem cache for folders that changed
    for folder in folders:
        fid = folder.get("folder_id", "")
        if fid in purged_folder_ids:
            clear_folder_cache(base_path / folder.get("name", ""))

    return purged_folder_ids
