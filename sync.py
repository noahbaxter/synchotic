#!/usr/bin/env python3
"""
DM Chart Sync - Download charts from Google Drive.

This is the user-facing app that downloads chart files from Google Drive.
File lists are fetched directly from Google Drive API (no manifest needed).
"""

import argparse
import os
import sys
import threading

# Increase file descriptor limit for concurrent downloads + extraction
# macOS defaults to 256 which is too low for 24 concurrent downloads
def _increase_file_limit():
    try:
        import resource
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        # Try to increase soft limit to hard limit (or 4096, whichever is lower)
        target = min(hard, 4096)
        if soft < target:
            resource.setrlimit(resource.RLIMIT_NOFILE, (target, hard))
            new_soft, _ = resource.getrlimit(resource.RLIMIT_NOFILE)
            print(f"  File limit: {soft} → {new_soft}")
    except (ImportError, ValueError, OSError):
        pass  # Windows doesn't have resource module, or limit change failed

_increase_file_limit()
from datetime import datetime
from pathlib import Path

from src.drive import DriveClient, AuthManager
from src.sync import FolderSync, purge_all_folders
from src.sync.markers import rebuild_markers_from_disk
from src.config import UserSettings, DrivesConfig, CustomFolders
from src.core.formatting import format_size, sanitize_drive_name
from src.core.paths import (
    get_data_dir,
    get_settings_path,
    get_token_path,
    get_local_manifest_path,
    get_download_path,
    get_drives_config_path,
    migrate_legacy_files,
    migrate_unsanitized_paths,
    cleanup_tmp_dir,
)
from src.ui import (
    print_header,
    show_main_menu,
    show_subfolder_settings,
    show_confirmation,
    show_oauth_prompt,
    show_add_custom_folder,
    compute_main_menu_cache,
    update_menu_cache_on_toggle,
)
from src.sync import FolderStatsCache, BackgroundScanner
from src.ui.primitives import clear_screen, wait_with_skip
from src.ui.widgets import display
from src.ui.primitives.terminal import set_terminal_size
from src.core.logging import TeeOutput, debug_log
from src.drive.client import DriveClientConfig

# ============================================================================
# Configuration
# ============================================================================

API_KEY = os.environ.get("GOOGLE_API_KEY", "")


# ============================================================================
# Main Application
# ============================================================================


class SyncApp:
    """Main application controller."""

    def __init__(self):
        import time as _t
        _t0 = _t.time()

        client_config = DriveClientConfig(api_key=API_KEY)
        self.client = DriveClient(client_config)

        # Load user settings first (needed for sync options)
        self.user_settings = UserSettings.load(get_settings_path())
        self.drives_config = DrivesConfig.load(get_drives_config_path())

        # Load custom folders
        self.custom_folders = CustomFolders.load(get_local_manifest_path())

        # Unified auth manager (handles user + admin fallback, token refresh)
        self.auth = AuthManager(token_path=get_token_path())

        print(f"    [init] configs loaded: {(_t.time() - _t0)*1000:.0f}ms")

        # Clean up any leftover temp files from interrupted operations
        _t1 = _t.time()
        cleanup_tmp_dir()
        print(f"    [init] cleanup_tmp_dir: {(_t.time() - _t1)*1000:.0f}ms")

        self.sync = FolderSync(
            self.client,
            auth_token=self.auth.get_token_getter(),
            delete_videos=self.user_settings.delete_videos,
        )
        self.folders = []
        self.folder_stats_cache = FolderStatsCache()
        self._background_scanner: BackgroundScanner | None = None

    def load_drives(self, quiet: bool = False):
        """Load drive list from drives.json. File data comes from scanner.

        Builds folder list from static drive config only. Files are populated
        by the BackgroundScanner when scanning completes.
        """
        if not quiet:
            print("Loading drives...")

        # Filter out hidden drives
        hidden_ids = {d.folder_id for d in self.drives_config.drives if d.hidden}
        self.folders = []

        for drive in self.drives_config.drives:
            if drive.folder_id in hidden_ids:
                continue

            # Build folder with static metadata only - files come from scanner
            folder = {
                "name": drive.name,
                "folder_id": drive.folder_id,
                "description": drive.description or "",
                "file_count": 0,      # Unknown until scanned
                "total_size": 0,      # Unknown until scanned
                "chart_count": 0,     # Unknown until scanned
                "files": None,        # MUST be scanned before sync
            }
            self.folders.append(folder)

        # Add custom folders
        for custom in self.custom_folders.folders:
            cached_files = self.custom_folders.get_files(custom.folder_id)
            folder_dict = {
                "name": custom.name,
                "folder_id": custom.folder_id,
                "description": "Custom folder",
                "file_count": len(cached_files),
                "total_size": sum(f.get("size", 0) for f in cached_files),
                "chart_count": len(cached_files),
                "files": None,  # Loaded on demand or by scanner
                "complete": True,
                "is_custom": True,
            }
            self.folders.append(folder_dict)

    def handle_sync(self):
        """Sync enabled setlists as they become ready, then purge extras.

        Downloads at setlist granularity — as soon as any setlist finishes scanning,
        its files are downloaded immediately. Only waits when no setlists are ready.
        Purge runs after all downloading is complete.

        Returns menu_cache if recomputed, or None if cancelled/no-op.
        """
        import time as _time

        # Need OAuth for scanning and downloading
        if not self.auth.is_signed_in:
            display.auth_required_scan()
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

    def handle_configure_drive(self, folder_id: str):
        """Configure setlists for a specific drive, or show options for custom folders."""
        folder = self._get_folder_by_id(folder_id)
        if not folder:
            return

        # Files come from BackgroundScanner - no need to load separately
        # Show subfolder settings (works for both regular and custom folders)
        result = show_subfolder_settings(folder, self.user_settings, get_download_path(), self._background_scanner)

        # Invalidate this folder's stats (setlists may have changed)
        self.folder_stats_cache.invalidate(folder_id)

        # Handle custom folder actions
        if result == "scan":
            self._scan_single_custom_folder(folder)
        elif result == "remove":
            self._remove_custom_folder(folder.get("folder_id"), folder.get("name"))

    def _show_custom_folder_options(self, folder: dict):
        """Show options menu for a custom folder."""
        from src.ui import Menu, MenuItem, MenuDivider
        from src.config import extract_subfolders_from_files

        folder_id = folder.get("folder_id")
        folder_name = folder.get("name")
        has_files = bool(folder.get("files"))

        # Check if folder has setlists (subfolders)
        setlists = extract_subfolders_from_files(folder) if has_files else []

        menu = Menu(title=folder_name)

        # Setlist settings (if folder has subfolders)
        if setlists:
            enabled_count = sum(
                1 for s in setlists
                if self.user_settings.is_subfolder_enabled(folder_id, s)
            )
            menu.add_item(MenuItem(
                "Configure setlists",
                hotkey="C",
                value="setlists",
                description=f"{enabled_count}/{len(setlists)} enabled"
            ))
            menu.add_item(MenuDivider())

        # Scan option
        if has_files:
            menu.add_item(MenuItem("Re-scan folder", hotkey="S", value="scan", description="Refresh file list from Google Drive"))
        else:
            menu.add_item(MenuItem("Scan folder", hotkey="S", value="scan", description="Get file list from Google Drive"))

        menu.add_item(MenuDivider())
        menu.add_item(MenuItem("Remove folder", hotkey="X", value="remove", description="Remove from custom folders"))
        menu.add_item(MenuDivider())
        menu.add_item(MenuItem("Back", value="back"))

        result = menu.run()
        if not result or result.value == "back":
            return

        if result.value == "setlists":
            show_subfolder_settings(folder, self.user_settings, get_download_path(), self._background_scanner)
        elif result.value == "scan":
            self._scan_single_custom_folder(folder)
        elif result.value == "remove":
            self._remove_custom_folder(folder_id, folder_name)

    def _scan_single_custom_folder(self, folder: dict):
        """Scan a single custom folder."""
        from src.drive import FolderScanner

        if not self.auth.is_signed_in:
            print("\n  Please sign in to Google first to scan custom folders.")
            wait_with_skip(3)
            return

        folder_id = folder.get("folder_id")
        folder_name = folder.get("name")

        display.scan_header(folder_name)

        auth_token = self.auth.get_token()
        client_config = DriveClientConfig(api_key=API_KEY)
        auth_client = DriveClient(client_config, auth_token=auth_token)
        scanner = FolderScanner(auth_client)

        def progress_cb(folders_scanned, files_found, shortcuts_found, files_list=None):
            print(f"\r  Scanning... {folders_scanned} folders, {files_found} files found", end="", flush=True)

        result = scanner.scan(folder_id, progress_callback=progress_cb)
        print()

        if result.cancelled:
            print("  Scan cancelled.")
            wait_with_skip(2)
            return

        # Update folder dict with scan results
        folder["files"] = [
            {
                "id": f["id"],
                "path": f["path"],
                "name": f["name"],
                "size": f.get("size", 0),
                "md5": f.get("md5", ""),
                "modified": f.get("modified", ""),
            }
            for f in result.files
        ]
        folder["file_count"] = len(result.files)
        folder["total_size"] = sum(f.get("size", 0) for f in result.files)

        # Save to custom folders storage
        self.custom_folders.set_files(folder_id, folder["files"])
        self.custom_folders.save()

        print(f"  Done! Found {len(result.files)} files ({format_size(folder['total_size'])})")
        print()
        wait_with_skip(2)

    def _remove_custom_folder(self, folder_id: str, folder_name: str):
        """Remove a custom folder after confirmation."""
        if not show_confirmation(
            "Remove custom folder?",
            f"This will remove '{folder_name}' from your custom folders.\nDownloaded files will NOT be deleted."
        ):
            return

        self.custom_folders.remove_folder(folder_id)
        self.custom_folders.save()

        # Remove from folders list
        self.folders = [f for f in self.folders if f.get("folder_id") != folder_id]

        print(f"\n  Removed: {folder_name}")
        wait_with_skip(2)

    def handle_toggle_drive(self, folder_id: str):
        """Toggle a drive on/off at the top level (preserves setlist settings)."""
        self.user_settings.toggle_drive(folder_id)
        self.user_settings.save()
        if self._background_scanner:
            enabled = self.user_settings.is_drive_enabled(folder_id)
            self._background_scanner.notify_drive_toggled(folder_id, enabled)
        # Purge numbers will be updated on next scan completion

    def handle_toggle_group(self, group_name: str):
        """Toggle a group expanded/collapsed."""
        self.user_settings.toggle_group_expanded(group_name)
        self.user_settings.save()

    def handle_signin(self):
        """Handle Google sign-in."""
        display.auth_opening_browser()

        if self.auth.sign_in():
            print("  Signed in successfully!")
            # Recreate sync with new token
            self._refresh_sync_token()
        else:
            print("  Sign-in cancelled or failed.")

        wait_with_skip(2)

    def handle_signout(self):
        """Handle Google sign-out."""
        self.auth.sign_out()
        # Recreate sync without user token (falls back to admin or anonymous)
        self._refresh_sync_token()
        print("\n  Signed out of Google.")
        wait_with_skip(2)

    def handle_add_custom_folder(self) -> bool:
        """
        Handle adding a custom Google Drive folder.

        Returns True if a folder was added successfully.
        """
        # Require sign-in for custom folders (need OAuth to access user's Drive)
        if not self.auth.is_signed_in:
            display.auth_required_custom_folders()
            wait_with_skip(3)
            return False

        # Create a client with user's OAuth token for validation
        auth_token = self.auth.get_token()
        client_config = DriveClientConfig(api_key=API_KEY)
        auth_client = DriveClient(client_config, auth_token=auth_token)

        # Show add folder screen
        folder_id, folder_name = show_add_custom_folder(auth_client, self.auth)

        if not folder_id:
            return False

        # Check if already exists
        if self.custom_folders.has_folder(folder_id):
            print(f"\n  Folder already added: {folder_name}")
            wait_with_skip(2)
            return False

        # Add to custom folders
        is_first_custom = len(self.custom_folders.folders) == 0
        self.custom_folders.add_folder(folder_id, folder_name)
        self.custom_folders.save()

        # Enable the drive by default
        self.user_settings.set_drive_enabled(folder_id, True)
        # Expand Custom group when first custom folder is added
        if is_first_custom:
            self.user_settings.group_expanded["Custom"] = True
        self.user_settings.save()

        print(f"\n  Added: {folder_name}")

        # Create folder dict and add to app's folder list
        folder_dict = {
            "name": folder_name,
            "folder_id": folder_id,
            "description": "Custom folder",
            "file_count": 0,
            "total_size": 0,
            "chart_count": 0,
            "files": None,  # Will be populated by scanner
            "complete": True,
            "is_custom": True,
        }
        self.folders.append(folder_dict)

        # Queue for scanning (scanner handles it automatically)
        if self._background_scanner:
            self._background_scanner.add_folder(folder_dict)

        return True

    def _refresh_sync_token(self):
        """Recreate FolderSync with current auth token getter."""
        self.sync = FolderSync(
            self.client,
            auth_token=self.auth.get_token_getter(),
            delete_videos=self.user_settings.delete_videos,
        )

    def _start_background_scan(self, force_rescan: bool = False):
        """
        Start background scanning of ALL folders.

        Scans folders in the background so the UI shows live progress.
        Enabled folders are scanned first (priority), then disabled folders.
        Only scans folders that don't have files loaded yet.

        Args:
            force_rescan: If True, bypass scan cache and hit the API for every setlist.
        """
        # Need OAuth for scanning
        if not self.auth.is_signed_in:
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
        print("  Discovering setlists...")
        slow_hint = threading.Timer(5.0, lambda: print("  (waiting for Google Drive API rate limit...)"))
        slow_hint.start()
        try:
            self._background_scanner.discover()
        finally:
            slow_hint.cancel()
        # Then start background scanning
        self._background_scanner.start()

    def _stop_background_scan(self):
        """Stop background scanning if running."""
        if self._background_scanner:
            self._background_scanner.stop()
            self._background_scanner = None

    def _get_folder_by_id(self, folder_id: str) -> dict | None:
        """Get folder dict by folder_id."""
        for folder in self.folders:
            if folder.get("folder_id", "") == folder_id:
                return folder
        return None

    def _handle_force_rescan(self):
        """Invalidate all caches and restart background scan for all drives."""
        from src.sync.cache import get_scan_cache, get_persistent_stats_cache

        self._stop_background_scan()

        get_scan_cache().invalidate_all()
        get_persistent_stats_cache().invalidate_all()
        self.folder_stats_cache.invalidate_all()

        for folder in self.folders:
            folder["files"] = None

        self._start_background_scan(force_rescan=True)

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
        else:
            display.sync_already_synced()

        return was_cancelled, synced_drive_ids

    def _scan_enabled_folders(self, enabled_indices: list):
        """
        Scan all enabled folders via API to get fresh file lists.

        This ensures downloads are always based on current Drive state,
        not potentially stale manifest data.

        NOTE: This method is deprecated - use _sync_folders_sequentially instead.
        """
        from src.drive import FolderScanner

        # Collect all enabled folders
        folders_to_scan = [(idx, self.folders[idx]) for idx in enabled_indices]

        if not folders_to_scan:
            return

        # Need user OAuth for scanning
        if not self.auth.is_signed_in:
            display.auth_required_scan()
            wait_with_skip(3)
            return

        # Show scanning header
        print("\n" + "=" * 50)
        print("Scanning folders...")
        print("=" * 50 + "\n")

        # Create scanner with user's OAuth
        auth_token = self.auth.get_token()
        client_config = DriveClientConfig(api_key=API_KEY)
        auth_client = DriveClient(client_config, auth_token=auth_token)
        scanner = FolderScanner(auth_client)

        for idx, folder in folders_to_scan:
            folder_id = folder.get("folder_id")
            folder_name = folder.get("name")
            is_custom = folder.get("is_custom", False)

            display.scan_folder_header(folder_name)

            def progress_cb(folders_scanned, files_found, shortcuts_found, files_list=None):
                print(f"\r  Scanning... {folders_scanned} folders, {files_found} files found", end="", flush=True)

            result = scanner.scan(folder_id, progress_callback=progress_cb)
            print()

            if result.cancelled:
                print("  Scan cancelled.")
                continue

            # Update folder dict with scan results
            folder["files"] = [
                {
                    "id": f["id"],
                    "path": f["path"],
                    "name": f["name"],
                    "size": f.get("size", 0),
                    "md5": f.get("md5", ""),
                    "modified": f.get("modified", ""),
                }
                for f in result.files
            ]
            folder["file_count"] = len(result.files)
            folder["total_size"] = sum(f.get("size", 0) for f in result.files)

            # Save to custom folders storage (only for custom folders)
            if is_custom:
                self.custom_folders.set_files(folder_id, folder["files"])
                self.custom_folders.save()

            print(f"  Done! Found {len(result.files)} files ({format_size(folder['total_size'])})")

        display.scan_complete_header()

    def _get_combined_drives_config(self) -> DrivesConfig:
        """Get drives config with custom folders added as a group."""
        from src.config import DriveConfig

        # Create a copy of drives list with custom folders appended
        combined = DrivesConfig(self.drives_config.path)
        combined.drives = list(self.drives_config.drives)

        # Add custom folders as a group
        for custom in self.custom_folders.folders:
            combined.drives.append(DriveConfig(
                name=custom.name,
                folder_id=custom.folder_id,
                description="Custom folder",
                group="Custom",
            ))

        return combined

    def run(self):
        """Main application loop."""
        clear_screen()
        print_header()

        # First-run OAuth prompt (only shown once)
        if not self.user_settings.oauth_prompted and self.auth.is_available:
            self.user_settings.oauth_prompted = True
            self.user_settings.save()

            if show_oauth_prompt():
                self.handle_signin()
                clear_screen()
                print_header()

        import time as _time
        _t_drives = _time.time()
        self.load_drives()
        print(f"  [timing] drives: {(_time.time() - _t_drives)*1000:.0f}ms")

        # Start background scanning of folders (if signed in)
        # Force rescan if scan cache is stale (>1hr old)
        from src.sync.cache import get_scan_cache
        newest_scan = get_scan_cache().get_newest_time()
        force = newest_scan is None  # No cache at all
        if newest_scan:
            from datetime import datetime, timezone
            age = (datetime.now(timezone.utc) - newest_scan).total_seconds()
            force = age > get_scan_cache().MAX_AGE_SECONDS
        _t_scan = _time.time()
        self._start_background_scan(force_rescan=force)
        if self._background_scanner:
            print(f"  [timing] bg_scanner started: {(_time.time() - _t_scan)*1000:.0f}ms")

        selected_index = 0  # Track selected position for maintaining after actions
        menu_cache = None  # Cache for expensive menu calculations
        start_time = os.environ.get("SYNCHOTIC_START_TIME")  # For startup timing

        while True:
            if not self.folders:
                clear_screen()
                print_header()
                print("No folders available!")
                print()

            # Compute cache if needed (first run or after state-changing actions)
            # Use combined drives config that includes custom folders
            combined_drives = self._get_combined_drives_config()

            if menu_cache is None:
                menu_cache = compute_main_menu_cache(
                    self.folders, self.user_settings,
                    get_download_path(), combined_drives,
                    self.folder_stats_cache,
                    self._background_scanner,
                )

            # Show startup time after first cache computation (actual "ready" state)
            if start_time:
                import time
                elapsed = time.time() - float(start_time)
                print(f"  Ready in {elapsed:.2f}s")
                start_time = None  # Only show once

            action, value, menu_pos = show_main_menu(
                self.folders, self.user_settings, selected_index,
                get_download_path(), combined_drives, cache=menu_cache,
                auth=self.auth,
                background_scanner=self._background_scanner,
                folder_stats_cache=self.folder_stats_cache,
            )
            selected_index = menu_pos  # Always preserve menu position

            if action == "quit":
                self._stop_background_scan()
                print("\nGoodbye!")
                break

            elif action == "sync":
                if self.folders:
                    result = self.handle_sync()
                    if result is not None:
                        menu_cache = result  # Pre-computed during sync
                    else:
                        menu_cache = None  # Cancelled or no-op, recompute normally

            elif action == "configure":
                # Enter on a drive - go directly to configure that drive
                self.handle_configure_drive(value)
                # Fast update: just regenerate this folder + global totals
                if menu_cache:
                    update_menu_cache_on_toggle(
                        menu_cache, value, self.folders, self.user_settings,
                        self.folder_stats_cache, combined_drives, self._background_scanner
                    )

            elif action == "toggle":
                # Space on a drive - toggle drive on/off
                self.handle_toggle_drive(value)
                # Fast update: just regenerate toggled folder + global totals
                if menu_cache:
                    update_menu_cache_on_toggle(
                        menu_cache, value, self.folders, self.user_settings,
                        self.folder_stats_cache, combined_drives, self._background_scanner
                    )

            elif action == "toggle_group":
                # Enter/Space on a group - expand/collapse (NO cache invalidation!)
                self.handle_toggle_group(value)
                # Keep using the same cache - just showing/hiding items

            elif action == "rescan":
                self._handle_force_rescan()
                menu_cache = None


            elif action == "signin":
                self.handle_signin()
                # No cache invalidation needed - just auth state changed

            elif action == "signout":
                self.handle_signout()
                # No cache invalidation needed - just auth state changed

            elif action == "add_custom":
                if self.handle_add_custom_folder():
                    # Folder already added to self.folders by handle_add_custom_folder
                    menu_cache = None  # Invalidate cache - new folder added


def main():
    """Entry point."""
    import time as _time
    _t0 = _time.time()

    # Set terminal size (skip if launched via launcher - it handles this)
    if not os.environ.get("SYNCHOTIC_ROOT"):
        set_terminal_size(90, 40)

    parser = argparse.ArgumentParser(
        description="DM Chart Sync - Download charts from Google Drive"
    )
    parser.parse_args()

    # Always log to .dm-sync/logs/YYYY-MM-DD.log
    logs_dir = get_data_dir() / "logs"
    logs_dir.mkdir(exist_ok=True)
    log_path = logs_dir / f"{datetime.now().strftime('%Y-%m-%d')}.log"
    # Read version for log header
    version = None
    version_file = Path(__file__).parent / "VERSION"
    if version_file.exists():
        version = version_file.read_text().strip()
    tee = TeeOutput(log_path, version=version)
    sys.stdout = tee

    print(f"  [timing] imports done: {(_time.time() - _t0)*1000:.0f}ms")

    # Migrate legacy files from old locations to .dm-sync/
    # Must run BEFORE creating SyncApp so paths resolve correctly
    migrated = migrate_legacy_files()
    if migrated:
        print(f"Migrated settings to .dm-sync/: {', '.join(migrated)}")

    renamed = migrate_unsanitized_paths()
    if renamed:
        print(f"Sanitized {len(renamed)} path(s) on disk:")
        for r in renamed:
            print(f"  {r}")

    _t1 = _time.time()
    app = SyncApp()
    print(f"  [timing] SyncApp init: {(_time.time() - _t1)*1000:.0f}ms")

    app.run()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nCancelled by user.")
        sys.exit(0)
