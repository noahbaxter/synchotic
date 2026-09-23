"""
Folder sync orchestration for DM Chart Sync.

Coordinates downloading and extraction for folder synchronization. Purging
lives in purge_flow.py.
"""

import time
from pathlib import Path
from typing import Callable, Optional, Union

from ..drive import DriveClient
from ..core.formatting import dedupe_files_by_newest, sanitize_drive_name
from ..core.logging import debug_log
from ..ui.primitives import print_long_path_warning, print_section_header, print_separator, wait_with_skip
from ..ui.widgets import display
from .cache import clear_folder_cache, get_persistent_stats_cache
from .download_planner import plan_downloads


class FolderSync:
    """Handles syncing folders from Google Drive to local disk."""

    def __init__(
        self,
        client: DriveClient,
        auth_token: Optional[Union[str, Callable[[], Optional[str]]]] = None,
        download_ignore=None,
        download_mode: str = "rclone",
    ):
        self.client = client
        self.auth_token = auth_token
        self.download_ignore = download_ignore
        # Which tier-4 behaviour the user chose. Anything other than "rclone"
        # means never open a consent browser, which is what makes headless and
        # privacy-conscious runs work.
        self.download_mode = download_mode
        from .downloader import FileDownloader
        self.downloader = FileDownloader(auth_token=auth_token, download_ignore=download_ignore)

    def sync_folder(
        self,
        folder: dict,
        base_path: Path,
        disabled_prefixes: list[str] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
        scan_stats_getter: Optional[Callable] = None,
        header: str = None,
        setlist_name: str = None,
        label: str = None,
        skip_marker_rebuild: bool = False,
        progress=None,
    ) -> tuple[int, int, int, list[str], bool, int]:
        """
        Sync a folder to local disk.

        Args:
            header: If provided, handles section header display. Without a
                    shared `progress` screen: synced folders get a compact
                    one-liner, downloads get a full ━━━ header.
            label: The folder's name on the panel's divider (header carries a
                   "[17/80]" count the bar already shows).
            progress: The sync run's panel. When given, nothing prints to the
                      terminal, which the panel owns.

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
        if not skip_marker_rebuild:
            from .markers import rebuild_markers_from_disk
            created, _ = rebuild_markers_from_disk([folder], base_path)
            if created > 0:
                debug_log(f"REBUILD_MARKERS | folder={folder['name']} | created={created}")

        caption = label or header or folder["name"]

        def _plan_progress(done, total):
            if total <= 200:  # fast enough that a counter is just noise
                return
            label = caption
            if progress:
                # A big folder takes a while to check; show that it is moving.
                progress.set_stage("" if done >= total else f"checking {label} against disk... {done}/{total}")
                progress.set_current_fraction(done / total)
                return
            from ..ui.primitives import print_progress
            if done >= total:
                # Wipe the counter, or the section header prints onto the end of it.
                print("\033[2K\r", end="", flush=True)
                return
            print_progress(f"Checking {label}... {done}/{total}")

        tasks, skipped, long_paths = plan_downloads(
            manifest_files, folder_path, self.download_ignore, folder_name=folder["name"],
            on_progress=_plan_progress, cancel_check=cancel_check,
        )

        debug_log(f"PLANNER | folder={folder['name']} | total={len(tasks) + skipped} | to_download={len(tasks)} | skipped={skipped}")

        if cancel_check and cancel_check():
            return 0, 0, 0, [], True, 0

        if long_paths and not progress:
            print_long_path_warning(len(long_paths))

        # A setlist that needs nothing says nothing on the shared panel: its bar
        # already counts it as done. Only the printed output reports it.
        if not tasks and not skipped:
            if not progress:
                if header:
                    print_section_header(header)
                display.folder_status_empty(filtered_count)
            return 0, 0, 0, [], False, 0

        if not tasks:
            if not progress:
                if header:
                    display.folder_synced_inline(header, skipped)
                else:
                    display.folder_status_synced(skipped, filtered_count)
            return 0, skipped, 0, [], False, 0

        if header and not progress:
            print_section_header(header)
        elif progress:
            progress.set_stage(f"downloading {caption}")

        download_start = time.time()
        (downloaded, _, errors, rate_limited, cancelled,
         bytes_downloaded, blocked_tasks) = self.downloader.download_many(
            tasks, drive_name=folder["name"], cancel_check=cancel_check,
            scan_stats_getter=scan_stats_getter, skipped=skipped,
            progress=progress,
        )

        # Tier 4: route auth-blocked files through rclone (its verified, uncapped OAuth).
        if blocked_tasks and not cancelled:
            recovered, still_blocked = self._rclone_second_pass(
                blocked_tasks, folder, cancel_check)
            downloaded += recovered
            errors -= recovered
            # Nothing was said about these while they were blocked, so say it
            # here, once, and only about the ones that really did not arrive.
            if not progress:
                display.blocked_outcome(recovered, still_blocked, self.download_mode)

        download_time = time.time() - download_start

        if not cancelled and not progress:
            display.folder_complete(downloaded, bytes_downloaded, download_time, errors)

        if downloaded > 0:
            from .ownership import mark_drive_owned
            mark_drive_owned(folder.get("folder_id", ""))

        clear_folder_cache(folder_path)

        # Invalidate persistent stats cache - synced state may have changed
        # This ensures UI deltas are recomputed from fresh marker state
        folder_id = folder.get("folder_id", "")
        if folder_id:
            if setlist_name:
                get_persistent_stats_cache().invalidate_setlist(folder_id, setlist_name)
            else:
                get_persistent_stats_cache().invalidate(folder_id)

        return downloaded, skipped, errors, rate_limited, cancelled, bytes_downloaded

    def _rclone_second_pass(self, blocked_tasks, folder, cancel_check):
        """Download auth-blocked tasks via rclone, then run existing archive processing.

        Reuses FileDownloader.process_archive so extraction/markers/purge-safety are
        identical to tiers 1-3. Returns (recovered_count, still_failed_count)."""
        from .. import rclone
        if self.download_mode != "rclone":
            debug_log(f"TIER4_SKIPPED | download_mode={self.download_mode} | "
                      f"blocked={len(blocked_tasks)}")
            return 0, len(blocked_tasks)
        session = None
        if not rclone.is_authed():
            if not rclone.can_open_browser():
                display.rclone_no_browser()
                return 0, len(blocked_tasks)
            # One-time consent: pre-explain rclone before it opens the browser,
            # then attempt setup. Defensive: a failure here just leaves the files
            # blocked (counted as errors), same as before. The session is reused
            # below so the binary resolves once rather than twice.
            try:
                display.rclone_consent_explainer()
                session = rclone.RcloneSession()
                if not session.ensure_authed():
                    return 0, len(blocked_tasks)
            except Exception:
                return 0, len(blocked_tasks)  # caller already counted them as errors
        recovered = 0
        try:
            with (session or rclone.RcloneSession()) as active:
                ok_ids, _ = active.downloader.download(
                    blocked_tasks, cancel_check=cancel_check
                )
        except Exception:
            return 0, len(blocked_tasks)
        ok = set(ok_ids)
        for task in blocked_tasks:
            if task.file_id not in ok:
                continue
            if task.is_archive:
                success, _, _ = self.downloader.process_archive(task, task.rel_path)
                if success:
                    recovered += 1
                    debug_log(f"TIER | rclone | {task.local_path.name.removeprefix('_download_')}")
            else:
                recovered += 1  # loose file already at final temp path
                debug_log(f"TIER | rclone | {task.local_path.name.removeprefix('_download_')}")
        return recovered, len(blocked_tasks) - recovered

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


