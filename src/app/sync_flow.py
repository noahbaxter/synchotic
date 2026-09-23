"""The sync run itself: preflight, downloading setlists as they're scanned,
then handing off to verify and purge."""

from src import copy
from src.core.formatting import count, format_duration, sanitize_drive_name
from src.core.logging import debug_log
from src.core.paths import get_download_path
from src.sync import purge_all_folders
from src.sync.markers import rebuild_markers_from_disk
from src.ui import compute_main_menu_cache, print_header
from src.ui.primitives import clear_screen, wait_with_skip
from src.ui.widgets import display


class SyncFlowMixin:

    def _preflight_ok(self) -> bool:
        """Stop, or ask, before a sync that cannot work, will not fit, or
        deletes a lot. Sizes come from the stats cache, so nothing waits on
        the scan."""
        from src.core.paths import plain_path
        from src.sync.cache import get_persistent_stats_cache
        from src.sync.preflight import concerns_for, read_setup
        from src.ui.screens.home import _get_setlist_names
        from src.ui.screens.preflight import confirm_sync

        library = get_download_path()
        folders = [
            {"folder_id": f.get("folder_id", ""), "name": f.get("name", ""),
             "setlists": _get_setlist_names(f, self._background_scanner)}
            for f in self.folders
        ]
        setup = read_setup(self.user_settings, self.auth, folders, library)
        concerns, free = concerns_for(folders, self.user_settings,
                                      get_persistent_stats_cache(), library,
                                      setup=setup)
        return confirm_sync(concerns, plain_path(library), free)

    def handle_sync(self):
        """Sync enabled setlists as they become ready, then purge extras.

        Downloads at setlist granularity — as soon as any setlist finishes scanning,
        its files are downloaded immediately. Only waits when no setlists are ready.
        Purge runs after all downloading is complete.

        Returns menu_cache if recomputed, or None if cancelled/no-op.
        """
        import time as _time

        # Sync streams its own progress, so give it the screen. Without this it
        # prints underneath the menu box that is still on screen.
        clear_screen()
        print_header()

        # Sign-in, library, what is turned on, space, deletions: silent unless
        # something is wrong. The one-line gates below stay as a backstop.
        if not self._preflight_ok():
            return None

        blocked = self._drive_blocked()
        if blocked:
            display.sync_blocked(blocked)
            wait_with_skip(3)
            return None

        blocked = self._library_blocked()
        if blocked:
            display.library_blocked(blocked)
            wait_with_skip(3)
            return None

        # Ensure background scanner is running
        if not self._background_scanner:
            self._start_background_scan()

        run_start = _time.time()

        from src.ui.widgets.progress import FolderProgress
        from src.ui.widgets.sync_screen import handle_key
        from src.ui.primitives.keys import KeyMonitor

        # One panel for the whole run (download, verify, purge, stats), so ESC
        # works throughout and nothing prints underneath it.
        progress = FolderProgress(total_files=0, total_folders=0)
        progress.set_phase(copy.PHASE_DOWNLOAD)
        progress.start()

        def handle_cancel():
            if not progress.cancelled:
                progress.cancel()

        # A holder so resume_keys can swap in a fresh KeyMonitor (a stopped one
        # cannot restart) after a ConfirmDialog has had stdin to itself.
        active_keys = [KeyMonitor(on_key=lambda key: handle_key(progress.screen, key, handle_cancel)).start()]

        def pause_keys():
            active_keys[0].stop()

        def resume_keys():
            active_keys[0] = KeyMonitor(
                on_key=lambda key: handle_key(progress.screen, key, handle_cancel)).start()

        menu_cache = None
        was_cancelled = False
        try:
            # Download setlists as they become ready from scanner
            t0 = _time.time()
            (was_cancelled, synced_drive_ids,
             total_downloaded, total_bytes, elapsed) = self._sync_folders_sequentially(progress)
            debug_log(f"TIMING | sync_folders: {_time.time() - t0:.1f}s")

            # Per-folder invalidation (only folders that were synced)
            for fid in synced_drive_ids:
                self.folder_stats_cache.invalidate(fid)

            # If cancelled, don't purge — but still invalidate synced folders
            if not was_cancelled:
                # Build failed setlists dict to protect from purge
                failed_setlists: dict[str, set[str]] | None = None
                if self._background_scanner and self._background_scanner.has_scan_failures():
                    failed_setlists = {}
                    for folder in self.folders:
                        folder_id = folder.get("folder_id", "")
                        failed = self._background_scanner.get_failed_setlist_names(folder_id)
                        if failed:
                            failed_setlists[folder_id] = failed
                    if failed_setlists:
                        all_failed = [name for names in failed_setlists.values() for name in names]
                        progress.note(copy.NOTE_SCAN_WARNING, context=copy.NOTE_SCAN_FAILED.format(
                            setlists=count(len(all_failed), "setlist")))

                # Rebuild markers for any extracted archives missing them (prevents mass deletion)
                progress.set_phase(copy.PHASE_VERIFY)
                progress.set_title("")
                progress.set_stage(copy.STAGE_MARKERS)
                t0 = _time.time()
                created, skipped = rebuild_markers_from_disk(self.folders, get_download_path())
                debug_log(f"TIMING | rebuild_markers: {_time.time() - t0:.1f}s | created={created}")
                if created:
                    progress.note(copy.NOTE_REBUILT, context=copy.NOTE_REBUILT_COUNT.format(n=created))

                # Purge extra files (no confirmation - sync means make it match)
                progress.set_phase(copy.PURGE)
                progress.set_title("")
                t0 = _time.time()
                purged_ids = purge_all_folders(
                    self.folders, get_download_path(), self.user_settings, failed_setlists,
                    progress=progress, cancel_check=lambda: progress.cancelled,
                    pause_keys=pause_keys, resume_keys=resume_keys,
                )
                debug_log(f"TIMING | purge: {_time.time() - t0:.1f}s")
                for fid in purged_ids:
                    self.folder_stats_cache.invalidate(fid)

                # Recompute menu cache now — this is the expensive part, do it here
                # with feedback instead of silently after "done"
                progress.set_phase(copy.PHASE_STATS)
                progress.set_stage(copy.STAGE_STATS)
                t0 = _time.time()
                combined_drives = self._get_combined_drives_config()
                menu_cache = compute_main_menu_cache(
                    self.folders, self.user_settings,
                    get_download_path(), combined_drives,
                    self.folder_stats_cache, self._background_scanner,
                )
                debug_log(f"TIMING | menu_recompute: {_time.time() - t0:.1f}s")
        finally:
            active_keys[0].stop()
            progress.close()
            progress.print_error_summary()

        if was_cancelled:
            display.sync_cancelled(total_downloaded)
        elif total_downloaded > 0:
            display.sync_complete(total_downloaded, total_bytes, elapsed)
        elif self._scan_failure():
            # Nothing downloaded because the scans died, not because the
            # library was already current. Saying "synced" here is how a
            # total failure reads as a clean run.
            reason, failed = self._scan_failure()
            display.sync_failed(reason, failed)
        else:
            display.sync_already_synced()

        # The whole run, not just the download phase's `elapsed`.
        print(f"  {copy.FINISHED_IN.format(time=format_duration(_time.time() - run_start))}")

        # NOW we can say "done" — because it actually is
        wait_with_skip(5, copy.CONTINUING_IN)
        return menu_cache

    def _sync_folders_sequentially(self, progress) -> tuple[bool, set[str], int, int, float]:
        """
        Download setlists as they become ready from background scanner.

        Works at setlist granularity, not drive level. As soon as any enabled
        setlist finishes scanning, its files are downloaded immediately.
        Only waits when no setlists are ready and scanning is still in progress.

        `progress` is the panel for the whole sync run (download, then verify,
        then purge): created, phased, and closed by the caller, so it stays
        open across all three stages instead of opening and closing per stage.

        Returns (was_cancelled, synced_drive_ids, total_downloaded, total_bytes, elapsed).
        """
        import time as _time

        scanner = self._background_scanner
        total_setlists = scanner.get_enabled_setlist_count()
        start_time = _time.time()

        if total_setlists == 0:
            progress.note(copy.SYNC, context=copy.NOTE_ALREADY_SYNCED)
            return False, set(), 0, 0, 0.0

        downloaded_ids: set[str] = set()
        synced_drive_ids: set[str] = set()
        total_downloaded = 0
        total_bytes = 0
        was_cancelled = False

        progress.set_scan_stats_getter(lambda: scanner.get_stats())
        progress.set_run_total(total_setlists, "setlists")

        while not was_cancelled:
            # Find next scanned setlist we haven't downloaded yet
            ready = scanner.get_scanned_enabled_setlists()
            next_setlist = None
            for s in ready:
                if s.setlist_id not in downloaded_ids:
                    next_setlist = s
                    break

            if next_setlist is not None:
                setlist = next_setlist
                drive = setlist.drive

                # Display name: "Drive/Setlist" for subfolders, just "Drive" for flat
                if setlist.name != setlist.drive_name:
                    display_name = f"{setlist.drive_name}/{setlist.name}"
                else:
                    display_name = setlist.drive_name

                # Filter drive files to just this setlist
                # File paths use sanitized names (colons etc. replaced), so match on sanitized prefix
                all_files = drive.get("files", [])
                if setlist.name != setlist.drive_name:
                    sanitized_name = sanitize_drive_name(setlist.name)
                    setlist_files = [f for f in all_files if f["path"].startswith(sanitized_name + "/")]
                    if not setlist_files:
                        prefixes = set(f["path"].split("/")[0] for f in all_files if "/" in f["path"])
                        debug_log(f"SETLIST_FILTER | name={setlist.name} | sanitized={sanitized_name} | all_files={len(all_files)} | matched=0 | prefixes={sorted(prefixes)[:5]}")
                else:
                    setlist_files = list(all_files)

                total_size = sum(f.get("size", 0) for f in setlist_files)

                # Build temp folder dict with just this setlist's files
                temp_folder = {
                    "name": drive.get("name", ""),
                    "folder_id": drive.get("folder_id", ""),
                    "files": setlist_files,
                    "total_size": total_size,
                }

                # On the divider, not the list, which is charts. No count: the
                # bar keeps it.
                progress.set_stage(copy.STAGE_CHECKING.format(name=display_name))
                downloaded, _, _, _, cancelled, bytes_down = self.sync.sync_folder(
                    temp_folder, get_download_path(), [],
                    setlist_name=setlist.name,
                    label=display_name,
                    skip_marker_rebuild=True,
                    progress=progress,
                    cancel_check=lambda: progress.cancelled,
                )

                total_downloaded += downloaded
                total_bytes += bytes_down
                downloaded_ids.add(setlist.setlist_id)
                synced_drive_ids.add(setlist.drive_id)

                if cancelled:
                    was_cancelled = True
                else:
                    progress.advance_run()
            else:
                # Nothing ready — are we done?
                if len(downloaded_ids) >= total_setlists or scanner.is_done():
                    break

                # Wait for the scanner; the divider shows its progress.
                if progress.cancelled:
                    was_cancelled = True
                    break
                _time.sleep(0.2)

        elapsed = _time.time() - start_time
        return was_cancelled, synced_drive_ids, total_downloaded, total_bytes, elapsed
