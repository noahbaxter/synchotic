"""
Folder sync orchestration for DM Chart Sync.

Coordinates downloading, extraction, and purging for folder synchronization.
"""

import time
from pathlib import Path
from typing import Callable, Optional, Union

from ..drive import DriveClient
from ..core.formatting import dedupe_files_by_newest, sanitize_drive_name
from ..core.logging import debug_log
from ..ui.primitives import print_long_path_warning, print_section_header, print_separator, wait_with_skip
from ..ui.widgets import display
from .cache import clear_cache, clear_folder_cache, get_persistent_stats_cache, scan_local_files
from .download_planner import plan_downloads
from .purge_planner import plan_purge, find_partial_downloads, check_purge_safety
from .purger import delete_files


class FolderSync:
    """Handles syncing folders from Google Drive to local disk."""

    def __init__(
        self,
        client: DriveClient,
        auth_token: Optional[Union[str, Callable[[], Optional[str]]]] = None,
        delete_videos: bool = True,
    ):
        self.client = client
        self.auth_token = auth_token
        self.delete_videos = delete_videos
        from .downloader import FileDownloader
        self.downloader = FileDownloader(auth_token=auth_token, delete_videos=delete_videos)

    def sync_folder(
        self,
        folder: dict,
        base_path: Path,
        disabled_prefixes: list[str] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
        scan_stats_getter: Optional[Callable] = None,
        header: str = None,
    ) -> tuple[int, int, int, list[str], bool, int]:
        """
        Sync a folder to local disk.

        Args:
            header: If provided, handles section header display. Synced folders
                    get a compact one-liner; downloads get a full ━━━ header.

        Returns:
            Tuple of (downloaded, skipped, errors, rate_limited_file_ids, cancelled, bytes_downloaded)
        """
        folder_path = base_path / folder["name"]
        disabled_prefixes = disabled_prefixes or []
        filtered_count = 0

        manifest_files = folder.get("files")

        # Require files to be scanned before sync
        if manifest_files is None:
            raise ValueError(f"Cannot sync '{folder['name']}': not scanned. Run scanner first.")

        if disabled_prefixes:
            original_count = len(manifest_files)
            # Sanitize prefixes to match how paths appear on disk (handles : -> - etc)
            sanitized_prefixes = {sanitize_drive_name(p) for p in disabled_prefixes}
            debug_log(f"DOWNLOAD_FILTER | folder={folder['name']} | disabled={len(disabled_prefixes)} | sanitized={list(sanitized_prefixes)[:3]}")

            def is_path_disabled(path: str) -> bool:
                """Check if path matches any disabled prefix."""
                first_slash = path.find("/")
                setlist_name = path[:first_slash] if first_slash != -1 else path
                # Sanitize the setlist name from scanner to match sanitized prefixes
                sanitized_name = sanitize_drive_name(setlist_name)
                return sanitized_name in sanitized_prefixes

            manifest_files = [f for f in manifest_files if not is_path_disabled(f.get("path", ""))]
            filtered_count = original_count - len(manifest_files)
            debug_log(f"DOWNLOAD_FILTER | folder={folder['name']} | original={original_count} | after_filter={len(manifest_files)}")

        manifest_files = dedupe_files_by_newest(manifest_files)

        # Rebuild markers for extracted archives missing them (prevents re-downloading
        # archives whose contents are already on disk from a pre-marker-era extraction)
        from .markers import rebuild_markers_from_disk
        created, _ = rebuild_markers_from_disk([folder], base_path)
        if created > 0:
            debug_log(f"REBUILD_MARKERS | folder={folder['name']} | created={created}")

        tasks, skipped, long_paths = plan_downloads(
            manifest_files, folder_path, self.delete_videos, folder_name=folder["name"]
        )

        debug_log(f"PLANNER | folder={folder['name']} | total={len(tasks) + skipped} | to_download={len(tasks)} | skipped={skipped}")

        if long_paths:
            print_long_path_warning(len(long_paths))

        if not tasks and not skipped:
            if header:
                print_section_header(header)
            display.folder_status_empty(filtered_count)
            return 0, 0, 0, [], False, 0

        if not tasks:
            if header:
                display.folder_synced_inline(header, skipped)
            else:
                display.folder_status_synced(skipped, filtered_count)
            return 0, skipped, 0, [], False, 0

        if header:
            print_section_header(header)

        download_start = time.time()
        downloaded, _, errors, rate_limited, cancelled, bytes_downloaded = self.downloader.download_many(
            tasks, drive_name=folder["name"], cancel_check=cancel_check,
            scan_stats_getter=scan_stats_getter, skipped=skipped,
        )
        download_time = time.time() - download_start

        if not cancelled:
            display.folder_complete(downloaded, bytes_downloaded, download_time, errors)

        clear_folder_cache(folder_path)

        # Invalidate persistent stats cache - synced state may have changed
        # This ensures UI deltas are recomputed from fresh marker state
        folder_id = folder.get("folder_id", "")
        if folder_id:
            get_persistent_stats_cache().invalidate(folder_id)

        return downloaded, skipped, errors, rate_limited, cancelled, bytes_downloaded

    def download_folders(
        self,
        folders: list,
        indices: list,
        download_path: Path,
        disabled_prefixes_map: dict[str, list[str]] = None
    ) -> bool:
        """Download folders. Returns True if cancelled."""
        download_path.mkdir(parents=True, exist_ok=True)
        disabled_prefixes_map = disabled_prefixes_map or {}

        total_downloaded = 0
        total_skipped = 0
        total_errors = 0
        total_bytes = 0
        total_rate_limited = 0
        was_cancelled = False
        rate_limited_folders: set[str] = set()
        start_time = time.time()

        total_folders = len(indices)
        for i, idx in enumerate(indices, 1):
            folder = folders[idx]
            folder_header = f"[{i}/{total_folders}] {folder['name']}" if total_folders > 1 else folder['name']

            folder_id = folder.get("folder_id", "")
            disabled_prefixes = disabled_prefixes_map.get(folder_id, [])

            downloaded, skipped, errors, rate_limited_ids, cancelled, bytes_down = self.sync_folder(
                folder, download_path, disabled_prefixes, header=folder_header,
            )

            total_downloaded += downloaded
            total_skipped += skipped
            total_errors += errors
            total_bytes += bytes_down
            total_rate_limited += len(rate_limited_ids)

            if rate_limited_ids:
                rate_limited_folders.add(folder['name'])

            if cancelled:
                was_cancelled = True
                break

        elapsed = time.time() - start_time
        print()
        print_separator()

        debug_log(f"SYNC_SUMMARY | downloaded={total_downloaded} | skipped={total_skipped} | errors={total_errors} | bytes={total_bytes}")

        if was_cancelled:
            display.sync_cancelled(total_downloaded)
        elif total_downloaded > 0:
            display.sync_complete(total_downloaded, total_bytes, elapsed)
        else:
            display.sync_already_synced()

        if total_errors > 0:
            display.sync_errors(total_errors)
        if total_rate_limited > 0:
            display.sync_rate_limited(total_rate_limited)

        if rate_limited_folders:
            display.rate_limit_guidance(rate_limited_folders)

        if was_cancelled:
            wait_with_skip(5, "Continuing in 5s (press any key to skip)")

        return was_cancelled


def purge_all_folders(
    folders: list,
    base_path: Path,
    user_settings=None,
    failed_setlists: dict[str, set[str]] | None = None,
):
    """
    Purge files that shouldn't be synced.

    Uses marker files as source of truth for what's valid.
    """
    from ..core.formatting import normalize_path_key
    from ..ui.components import format_purge_tree
    from .markers import get_all_marker_files

    print_section_header("Purge")

    total_deleted = 0
    total_failed = 0
    total_size = 0
    purged_folder_ids: set[str] = set()

    # Compute markers ONCE for all folders
    all_marker_files = get_all_marker_files()
    marker_norm = {normalize_path_key(p) for p in all_marker_files}

    for folder in folders:
        folder_id = folder.get("folder_id", "")
        folder_name = folder.get("name", "")
        folder_path = base_path / folder_name

        if not folder_path.exists():
            continue

        drive_enabled = user_settings.is_drive_enabled(folder_id) if user_settings else True

        if not drive_enabled:
            local_files = [(f, f.stat().st_size if f.exists() else 0)
                          for f in folder_path.rglob("*") if f.is_file()]
            if local_files:
                folder_size = sum(size for _, size in local_files)
                display.purge_drive_disabled(folder_name, len(local_files), folder_size)

                deleted, failed = delete_files(local_files, base_path)
                total_deleted += deleted
                total_failed += failed
                total_size += folder_size
                if deleted > 0:
                    purged_folder_ids.add(folder_id)
                display.purge_removed(deleted, failed)
            continue

        files_to_purge, stats = plan_purge(
            [folder], base_path, user_settings, failed_setlists,
            precomputed_markers=marker_norm,
        )

        if not files_to_purge:
            continue

        folder_size = sum(size for _, size in files_to_purge)

        # Safety check: only for "extra" files (orphans not in markers/manifest).
        # Disabled setlists and videos are intentional user-driven purges — skip safety.
        if stats.extra_file_count > 0:
            local_files = scan_local_files(folder_path)
            is_safe, reason = check_purge_safety(len(local_files), stats.extra_file_count, stats.extra_file_size)
            if not is_safe:
                debug_log(f"PURGE_BLOCKED | folder={folder_name} | reason={reason}")
                print(f"  WARNING: Purge blocked for {folder_name} ({reason})")
                print(f"  This looks like a sync error — check debug log for details.")
                continue

        display.purge_folder(folder_name, len(files_to_purge), folder_size)

        tree_lines = format_purge_tree(files_to_purge, base_path)
        display.purge_tree_lines(tree_lines)

        deleted, failed = delete_files(files_to_purge, base_path)
        total_deleted += deleted
        total_failed += failed
        total_size += folder_size
        if deleted > 0:
            purged_folder_ids.add(folder_id)
        display.purge_removed(deleted, failed)

    partial_files = find_partial_downloads(base_path)
    if partial_files:
        partial_size = sum(size for _, size in partial_files)
        display.purge_partial_downloads(len(partial_files), partial_size)
        deleted, failed = delete_files(partial_files, base_path)
        total_deleted += deleted
        total_failed += failed
        total_size += partial_size
        display.purge_partial_cleaned(deleted, failed)

    print()
    print_separator()
    if total_deleted > 0 or total_failed > 0:
        display.purge_summary(total_deleted, total_size, total_failed)
    else:
        display.purge_nothing()

    clear_cache()

    # Invalidate persistent stats cache only for folders that changed
    persistent_cache = get_persistent_stats_cache()
    for folder_id in purged_folder_ids:
        persistent_cache.invalidate(folder_id)

    return purged_folder_ids
