"""Downloading and extracting one folder into the library, drawn on the sync
run's panel. Purging lives in purge_flow.py."""

from pathlib import Path
from typing import Callable, Optional, Union

from ..drive import DriveClient
from ..core.formatting import (dedupe_files_by_newest, extract_path_context,
                               format_download_name, sanitize_drive_name)
from ..core.logging import debug_log
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
        setlist_name: str = None,
        label: str = None,
        skip_marker_rebuild: bool = False,
        *,
        progress,
    ) -> tuple[int, int, int, list[str], bool, int]:
        """
        Sync a folder to local disk.

        Args:
            label: The folder's name on the panel's divider.
            progress: The sync run's panel. Nothing prints to the terminal,
                      which the panel owns.

        Returns:
            Tuple of (downloaded, skipped, errors, rate_limited_file_ids, cancelled, bytes_downloaded)
        """
        folder_path = base_path / folder["name"]
        disabled_prefixes = disabled_prefixes or []

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
            debug_log(f"DOWNLOAD_FILTER | folder={folder['name']} | original={original_count} | after_filter={len(manifest_files)}")

        manifest_files = dedupe_files_by_newest(manifest_files)

        # Rebuild markers for extracted archives missing them (prevents re-downloading
        # archives whose contents are already on disk from a pre-marker-era extraction)
        if not skip_marker_rebuild:
            from .markers import rebuild_markers_from_disk
            created, _ = rebuild_markers_from_disk([folder], base_path)
            if created > 0:
                debug_log(f"REBUILD_MARKERS | folder={folder['name']} | created={created}")

        caption = label or folder["name"]

        def _plan_progress(done, total):
            if total <= 200:  # fast enough that a counter is just noise
                return
            # A big folder takes a while to check; show that it is moving.
            progress.set_stage("" if done >= total else f"checking {caption} against disk... {done}/{total}")
            progress.set_current_fraction(done / total)

        tasks, skipped, _long_paths = plan_downloads(
            manifest_files, folder_path, self.download_ignore, folder_name=folder["name"],
            on_progress=_plan_progress, cancel_check=cancel_check,
        )

        debug_log(f"PLANNER | folder={folder['name']} | total={len(tasks) + skipped} | to_download={len(tasks)} | skipped={skipped}")

        if cancel_check and cancel_check():
            return 0, 0, 0, [], True, 0

        # A setlist that needs nothing says nothing: its bar already counts it
        # as done.
        if not tasks:
            return 0, skipped, 0, [], False, 0

        progress.set_stage(f"downloading {caption}")

        (downloaded, _, errors, rate_limited, cancelled,
         bytes_downloaded, blocked_tasks) = self.downloader.download_many(
            tasks, drive_name=folder["name"], cancel_check=cancel_check,
            scan_stats_getter=scan_stats_getter, progress=progress,
        )

        # Tier 4: route auth-blocked files through rclone (its verified, uncapped OAuth).
        if blocked_tasks and not cancelled:
            recovered, _ = self._rclone_second_pass(
                blocked_tasks, folder, cancel_check, progress)
            downloaded += recovered
            errors -= recovered

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

    def _rclone_second_pass(self, blocked_tasks, folder, cancel_check, progress):
        """Download auth-blocked tasks via rclone, then run existing archive processing.

        Reuses FileDownloader.process_archive so extraction/markers/purge-safety are
        identical to tiers 1-3. Returns (recovered_count, still_failed_count).
        Every task ends on the panel as arrived or failed, never silently lost.
        """
        from .. import rclone
        if self.download_mode != "rclone":
            debug_log(f"TIER4_SKIPPED | download_mode={self.download_mode} | "
                      f"blocked={len(blocked_tasks)}")
            self._blocked_rows(progress, blocked_tasks, f"{self.download_mode} mode")
            return 0, len(blocked_tasks)

        session = None
        if not rclone.is_authed():
            if not rclone.can_open_browser():
                self._blocked_rows(progress, blocked_tasks, "no browser to sign in with")
                return 0, len(blocked_tasks)
            # One-time consent: explain rclone, then open the browser, with the
            # panel suspended so the explanation stays readable while it waits.
            # A failure leaves the files blocked and says which failure. The
            # session is reused below so the binary resolves once.
            try:
                with progress.suspended():
                    display.rclone_consent_explainer()
                    session = rclone.RcloneSession()
                    authed = session.ensure_authed()
                if not authed:
                    self._blocked_rows(progress, blocked_tasks, "rclone sign-in not completed")
                    return 0, len(blocked_tasks)
            except Exception as err:
                debug_log(f"TIER4_AUTH_FAILED | {type(err).__name__}: {err}")
                self._blocked_rows(progress, blocked_tasks,
                                   f"rclone sign-in failed: {type(err).__name__}")
                return 0, len(blocked_tasks)

        progress.set_stage(f"rclone: fetching {len(blocked_tasks)} chart(s) "
                           f"Google would not serve")
        recovered = 0
        try:
            with (session or rclone.RcloneSession()) as active:
                ok_ids, _ = active.downloader.download(
                    blocked_tasks, cancel_check=cancel_check,
                    on_start=lambda task: self._rclone_row_started(progress, task),
                    on_bytes=lambda task, sent: self._rclone_row_bytes(progress, task, sent),
                )
        except Exception as err:
            debug_log(f"TIER4_FAILED | {type(err).__name__}: {err}")
            self._blocked_rows(progress, blocked_tasks, f"rclone failed: {type(err).__name__}")
            return 0, len(blocked_tasks)
        finally:
            progress.set_stage("")

        ok = set(ok_ids)
        for task in blocked_tasks:
            name = task.local_path.name.removeprefix("_download_")
            if task.file_id not in ok:
                self._blocked_rows(progress, [task], "rclone could not fetch it")
                continue
            if task.is_archive:
                success, error, _ = self.downloader.process_archive(task, task.rel_path)
                if success:
                    recovered += 1
                    debug_log(f"TIER | rclone | {name}")
                    # Its bytes count like any other chart's.
                    progress.add_downloaded_bytes(task.size, file_id=task.file_id)
                    progress.archive_completed(task.local_path, name,
                                               extract_path_context(task.rel_path),
                                               file_id=task.file_id)
                else:
                    progress.print_error(extract_path_context(task.rel_path),
                                         f"extract: {name} - {error}", file_id=task.file_id)
            else:
                recovered += 1  # loose file already at final temp path
                debug_log(f"TIER | rclone | {name}")
                # Its chart row comes from the folder resolving, not from here.
                progress.add_downloaded_bytes(task.size, file_id=task.file_id)
                progress.unregister_active_download(task.file_id)
        return recovered, len(blocked_tasks) - recovered

    @staticmethod
    def _rclone_row_started(progress, task) -> None:
        progress.register_active_download(
            task.file_id, format_download_name(task.local_path),
            extract_path_context(task.rel_path), task.size)

    @staticmethod
    def _rclone_row_bytes(progress, task, sent: int) -> None:
        progress.update_active_download(task.file_id, sent)

    @staticmethod
    def _blocked_rows(progress, tasks, detail: str) -> None:
        """Fail these charts on the panel as "needs sign-in"; `detail` carries
        the specific cause into the log."""
        for task in tasks:
            name = task.local_path.name.removeprefix("_download_")
            progress.print_error(extract_path_context(task.rel_path),
                                 f"NEEDS AUTH ({detail}): {name}",
                                 file_id=task.file_id)


