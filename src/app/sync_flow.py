"""The sync run itself: preflight, downloading setlists as they're scanned,
then handing off to verify and purge."""

import os

from src.core.formatting import sanitize_drive_name
from src.core.logging import debug_log
from src.core.paths import get_download_path
from src.sync import purge_all_folders
from src.sync.markers import rebuild_markers_from_disk
from src.ui import compute_main_menu_cache, print_header
from src.ui.primitives import clear_screen, wait_with_skip
from src.ui.widgets import display


class SyncFlowMixin:

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

        # Whether the chosen mode can reach Drive, not whether we hold an OAuth
        # token: rclone and anonymous both sync without one.
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

        # Download setlists as they become ready from scanner
        t0 = _time.time()
        was_cancelled, synced_drive_ids = self._sync_folders_sequentially()
        debug_log(f"TIMING | sync_folders: {_time.time() - t0:.1f}s")

        # Per-folder invalidation (only folders that were synced)
        for fid in synced_drive_ids:
            self.folder_stats_cache.invalidate(fid)

        # If cancelled, don't purge — but still invalidate synced folders
        if was_cancelled:
            return None

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
                print(f"\n  Warning: {len(all_failed)} setlist(s) failed to scan (files preserved): {', '.join(sorted(all_failed))}")

        # Rebuild markers for any extracted archives missing them (prevents mass deletion)
        print("  Rebuilding markers...", end="", flush=True)
        t0 = _time.time()
        created, skipped = rebuild_markers_from_disk(self.folders, get_download_path())
        debug_log(f"TIMING | rebuild_markers: {_time.time() - t0:.1f}s | created={created}")
        if created > 0:
            print(f" {created} rebuilt.", flush=True)
        else:
            print(" ok.", flush=True)

        # Purge extra files (no confirmation - sync means make it match)
        t0 = _time.time()
        purged_ids = purge_all_folders(self.folders, get_download_path(), self.user_settings, failed_setlists)
        debug_log(f"TIMING | purge: {_time.time() - t0:.1f}s")
        for fid in purged_ids:
            self.folder_stats_cache.invalidate(fid)

        # Recompute menu cache now — this is the expensive part, do it here
        # with feedback instead of silently after "done"
        print("  Updating stats...", end="", flush=True)
        t0 = _time.time()
        combined_drives = self._get_combined_drives_config()
        menu_cache = compute_main_menu_cache(
            self.folders, self.user_settings,
            get_download_path(), combined_drives,
            self.folder_stats_cache, self._background_scanner,
        )
        debug_log(f"TIMING | menu_recompute: {_time.time() - t0:.1f}s")
        print(" done.")

        # NOW we can say "done" — because it actually is
        wait_with_skip(5, "Continuing in 5s (press any key to skip)")
        return menu_cache

    def _sync_folders_sequentially(self) -> tuple[bool, set[str]]:
        """
        Download setlists as they become ready from background scanner.

        Works at setlist granularity, not drive level. As soon as any enabled
        setlist finishes scanning, its files are downloaded immediately.
        Only waits when no setlists are ready and scanning is still in progress.

        Returns (was_cancelled, synced_drive_ids).
        """
        import time as _time
        from src.core.formatting import format_duration
        from src.ui.primitives import getch_with_timeout, KEY_ESC, cbreak_noecho

        scanner = self._background_scanner
        total_setlists = scanner.get_enabled_setlist_count()

        if total_setlists == 0:
            display.sync_already_synced()
            return False, set()

        downloaded_ids: set[str] = set()
        synced_drive_ids: set[str] = set()
        completed_count = 0
        total_downloaded = 0
        total_bytes = 0
        was_cancelled = False
        start_time = _time.time()

        while not was_cancelled:
            # Find next scanned setlist we haven't downloaded yet
            ready = scanner.get_scanned_enabled_setlists()
            next_setlist = None
            for s in ready:
                if s.setlist_id not in downloaded_ids:
                    next_setlist = s
                    break

            if next_setlist is not None:
                completed_count += 1
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

                setlist_header = f"[{completed_count}/{total_setlists}] {display_name}"
                scan_getter = lambda: scanner.get_stats()
                downloaded, _, _, _, cancelled, bytes_down = self.sync.sync_folder(
                    temp_folder, get_download_path(), [],
                    scan_stats_getter=scan_getter, header=setlist_header,
                    setlist_name=setlist.name,
                    skip_marker_rebuild=True,
                )

                total_downloaded += downloaded
                total_bytes += bytes_down
                downloaded_ids.add(setlist.setlist_id)
                synced_drive_ids.add(setlist.drive_id)

                if cancelled:
                    was_cancelled = True
            else:
                # Nothing ready — are we done?
                if len(downloaded_ids) >= total_setlists or scanner.is_done():
                    break

                # Wait for scanner (ephemeral status line, erased when a setlist becomes ready)
                CLEAR_LINE = "\033[2K\r"
                # Clear current line (scanning status), move up, clear that line (blank line)
                ERASE_WAIT = "\033[2K\033[A\033[2K\r"
                try:
                    term_width = os.get_terminal_size().columns
                except OSError:
                    term_width = 80

                def show_wait(msg: str):
                    truncated = msg[:term_width - 1]
                    print(f"{CLEAR_LINE}{truncated}", end="", flush=True)

                print()  # blank line before scanning status
                show_wait("  Scanning... (ESC to cancel)")

                with cbreak_noecho():
                    while True:
                        key = getch_with_timeout(200)
                        if key == KEY_ESC:
                            print(f"{ERASE_WAIT}{CLEAR_LINE}  Cancelled.")
                            was_cancelled = True
                            break

                        # Check if any setlist became ready
                        ready = scanner.get_scanned_enabled_setlists()
                        if any(s.setlist_id not in downloaded_ids for s in ready):
                            # Erase status line + blank line above it
                            print(f"{ERASE_WAIT}", end="", flush=True)
                            break

                        # Show scanner progress
                        stats = scanner.get_stats()
                        if stats.current_folder:
                            elapsed_str = format_duration(stats.current_folder_elapsed)
                            show_wait(f"  Scanning {stats.current_folder}... ({elapsed_str}, {stats.api_calls} API calls)")

        # Final summary
        elapsed = _time.time() - start_time
        print()
        print("━" * 50)

        if was_cancelled:
            display.sync_cancelled(total_downloaded)
            wait_with_skip(5, "Continuing in 5s (press any key to skip)")
        elif total_downloaded > 0:
            display.sync_complete(total_downloaded, total_bytes, elapsed)
        elif self._scan_failure():
            # Nothing downloaded because the scans died, not because the
            # library was already current. Saying "synced" here is how a
            # total failure reads as a clean run.
            reason, count = self._scan_failure()
            display.sync_failed(reason, count)
        else:
            display.sync_already_synced()

        return was_cancelled, synced_drive_ids
