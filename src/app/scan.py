"""Background scanning: discovering and refreshing what's actually on each
drive, off the input thread so the menu stays responsive while it runs."""

from src import copy
from src.app.config import API_KEY
from src.core.paths import get_download_path
from src.sync import BackgroundScanner
from src.ui.primitives import wait_with_skip
from src.ui.widgets import display


class ScanMixin:

    def _start_background_scan(self, force_rescan: bool = False):
        """
        Start background scanning of ALL folders.

        Scans folders in the background so the UI shows live progress.
        Enabled folders are scanned first (priority), then disabled folders.
        Only scans folders that don't have files loaded yet.

        Args:
            force_rescan: If True, bypass scan cache and hit the API for every setlist.
        """
        # Whether the mode can reach Drive, not whether we hold a token. This
        # is the gate handle_sync stopped applying and this one kept: rclone
        # users got past sync's front door and then no scanner was ever built,
        # so nothing scanned, every drive kept files=None, and the home screen
        # read that back as "No drives enabled".
        if self._drive_blocked():
            return

        # Scans write markers and the scan cache into the library. With no
        # library set, or one on a drive that is not mounted, get_library_state_dir
        # would either raise or mkdir an empty tree at a bare mountpoint, which
        # the next sync then fills and a remount hides.
        if self._library_blocked():
            return

        # Find folders that need scanning (files not loaded)
        # Order: enabled first, then disabled; within each group, smallest first
        enabled = [
            f for f in self.folders
            if f.get("files") is None
            and self.user_settings.is_drive_enabled(f.get("folder_id", ""))
        ]
        disabled = [
            f for f in self.folders
            if f.get("files") is None
            and not self.user_settings.is_drive_enabled(f.get("folder_id", ""))
        ]
        # Sort each group by size (smallest first) so downloads can start sooner
        enabled.sort(key=lambda f: f.get("total_size", 0) or f.get("chart_count", 0) or 0)
        disabled.sort(key=lambda f: f.get("total_size", 0) or f.get("chart_count", 0) or 0)
        folders_to_scan = enabled + disabled

        if not folders_to_scan:
            # No folders need scanning - keep existing scanner for its discovery data
            # (setlist names are needed even if files are already loaded)
            return

        # Stop any existing scanner before creating new one
        if self._background_scanner:
            self._background_scanner.stop()
            self._background_scanner = None

        # Callback when a folder finishes scanning - save custom folder data
        def on_folder_complete(folder: dict):
            if folder.get("is_custom"):
                folder_id = folder.get("folder_id")
                self.custom_folders.set_files(folder_id, (folder.get("files") or []))
                self.custom_folders.save()

        self._background_scanner = BackgroundScanner(
            folders_to_scan,
            self.auth,
            API_KEY,
            user_settings=self.user_settings,
            on_folder_complete=on_folder_complete,
            download_path=get_download_path(),
            force_rescan=force_rescan,
        )
        # Discovery first (synchronous) - gives accurate setlist counts immediately
        from src.ui.primitives import print_progress

        def _discovery_progress(done, total, name):
            # done counts completions, which land out of order now that the
            # drives are queried concurrently.
            if total and done >= total:
                print_progress(copy.DISCOVERING.format(done=total, total=total))
                print()
            else:
                suffix = f" - {name}" if name else ""
                print_progress(copy.DISCOVERING.format(done=done, total=total) + suffix)

        self._background_scanner.discover(on_progress=_discovery_progress)
        # Migrate custom folders that are subfolders of released drives
        self._migrate_subfolder_customs()
        # Then start background scanning
        self._background_scanner.start()

    def _stop_background_scan(self):
        """Stop background scanning if running."""
        if self._background_scanner:
            self._background_scanner.stop()
            self._background_scanner = None

    def _handle_force_rescan(self):
        """Invalidate all caches and restart background scan for all drives."""
        from src.sync.cache import get_scan_cache, get_persistent_stats_cache

        # Checked before anything is thrown away: with no library to scan into
        # the rescan cannot restart, and dropping every cache first would leave
        # the home screen empty with no way to refill it.
        blocked = self._library_blocked()
        if blocked:
            display.library_blocked(blocked)
            wait_with_skip(3)
            return

        self._stop_background_scan()

        get_scan_cache().invalidate_all()
        get_persistent_stats_cache().invalidate_all()
        self.folder_stats_cache.invalidate_all()

        for folder in self.folders:
            folder["files"] = None

        self._start_background_scan(force_rescan=True)

    def _scan_failure(self) -> tuple[str, int] | None:
        """(reason, failed setlist count) when scans failed, else None."""
        scanner = self._background_scanner
        if not (scanner and scanner.has_scan_failures()):
            return None
        reason = scanner.get_failure_reason() or copy.FAIL_UNKNOWN
        count = sum(len(scanner.get_failed_setlist_names(f.get("folder_id", "")))
                    for f in self.folders)
        return reason, count
