"""
Background folder scanning for lazy loading.

Scans ALL setlists in background thread, prioritizing enabled ones.
Uses three simple sets: all_setlists, enabled_setlists, scanned_setlists.
"""

import threading
import time
from dataclasses import dataclass, field
from typing import Callable, TYPE_CHECKING

from pathlib import Path

from ..drive import DriveClient, FolderScanner
from ..drive.client import DriveClientConfig
from ..core.logging import debug_log

if TYPE_CHECKING:
    from ..config import UserSettings


@dataclass
class ScanStats:
    """Real-time scanning statistics."""
    api_calls: int = 0
    start_time: float = 0
    end_time: float = 0
    current_folder: str = ""
    current_folder_start: float = 0
    folders_done: int = 0
    folders_total: int = 0

    @property
    def elapsed(self) -> float:
        if self.start_time == 0:
            return 0
        end = self.end_time if self.end_time > 0 else time.time()
        return end - self.start_time

    @property
    def current_folder_elapsed(self) -> float:
        if self.current_folder_start == 0:
            return 0
        return time.time() - self.current_folder_start


@dataclass
class SetlistInfo:
    """Info about a setlist."""
    setlist_id: str      # Google Drive folder ID for this setlist
    name: str            # Setlist name (folder name)
    drive_id: str        # Parent drive's folder ID
    drive_name: str      # Parent drive's name
    drive: dict          # Reference to parent drive dict (for accumulating files)


class BackgroundScanner:
    """
    Scans ALL setlists, prioritizing enabled ones.

    Three core data structures:
    - all_setlists: every setlist discovered
    - enabled_setlist_ids: setlists currently enabled (dynamic)
    - scanned_setlist_ids: setlists finished scanning

    Scanner always processes enabled first, then disabled.
    When user toggles a setlist, it's immediately reflected.
    """

    FOLDER_MIME = "application/vnd.google-apps.folder"
    SHORTCUT_MIME = "application/vnd.google-apps.shortcut"

    def __init__(
        self,
        folders: list[dict],
        auth,
        api_key: str,
        user_settings: "UserSettings" = None,
        on_folder_complete: Callable[[dict], None] = None,
        download_path: Path = None,
    ):
        self._folders = folders
        self._auth = auth
        self._api_key = api_key
        self._user_settings = user_settings
        self._on_folder_complete = on_folder_complete
        self._download_path = download_path

        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

        # The three core sets
        self._all_setlists: dict[str, SetlistInfo] = {}  # setlist_id -> SetlistInfo
        self._enabled_setlist_ids: set[str] = set()
        self._scanned_setlist_ids: set[str] = set()
        self._failed_setlist_ids: set[str] = set()  # Setlists that threw during scan

        # Per-drive tracking
        self._drive_setlist_ids: dict[str, list[str]] = {}  # drive_id -> [setlist_ids]
        self._drive_setlist_names: dict[str, list[str]] = {}  # drive_id -> [names]

        # Stats
        self._stats = ScanStats(folders_total=len(folders))
        self._client: DriveClient | None = None
        self._settings_changed = False

    # =========================================================================
    # Public API
    # =========================================================================

    def discover(self):
        """Run discovery synchronously. Call before start()."""
        if self._client is not None:
            return  # Already discovered

        self._stats.start_time = time.time()

        auth_token = self._auth.get_token()
        client_config = DriveClientConfig(api_key=self._api_key)
        self._client = DriveClient(client_config, auth_token=auth_token)

        self._discover_all_setlists()

        # Save settings if discovery caused migrations
        if self._settings_changed and self._user_settings:
            self._user_settings.save()
            self._settings_changed = False

        with self._lock:
            self._stats.folders_total = len(self._all_setlists)

    def start(self):
        """Start background scanning. Call discover() first."""
        if self._thread is not None:
            return

        if self._client is None:
            self.discover()

        self._thread = threading.Thread(target=self._scan_worker, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop background scanning."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=1.0)
            self._thread = None

    def is_scanning(self, drive_id: str) -> bool:
        """Check if a drive has any unscanned setlists."""
        with self._lock:
            setlist_ids = self._drive_setlist_ids.get(drive_id, [])
            return any(sid not in self._scanned_setlist_ids for sid in setlist_ids)

    def is_ready_for_sync(self, drive_id: str) -> bool:
        """Check if a drive's ENABLED setlists are scanned (ready to download)."""
        with self._lock:
            setlist_ids = self._drive_setlist_ids.get(drive_id, [])
            if not setlist_ids:
                return False
            # Only need enabled setlists to be scanned for sync
            # Failed setlists count as "done" — they'll be retried later,
            # but we don't block sync waiting for them
            done = self._scanned_setlist_ids | self._failed_setlist_ids
            enabled_ids = [sid for sid in setlist_ids if sid in self._enabled_setlist_ids]
            if not enabled_ids:
                return True  # No enabled setlists = ready (nothing to download)
            return all(sid in done for sid in enabled_ids)

    def is_scanned(self, drive_id: str) -> bool:
        """Check if ALL of a drive's setlists are scanned (stats complete)."""
        with self._lock:
            setlist_ids = self._drive_setlist_ids.get(drive_id, [])
            if not setlist_ids:
                return False
            return all(sid in self._scanned_setlist_ids for sid in setlist_ids)

    def is_done(self) -> bool:
        """Check if all setlists across all drives are scanned."""
        with self._lock:
            return len(self._scanned_setlist_ids) >= len(self._all_setlists)

    def check_updates(self) -> bool:
        """Check if any setlists were scanned since last check. Used for UI refresh."""
        with self._lock:
            current_count = len(self._scanned_setlist_ids)
            if not hasattr(self, '_last_check_count'):
                self._last_check_count = 0
            changed = current_count > self._last_check_count
            self._last_check_count = current_count
            return changed

    def get_stats(self) -> ScanStats:
        """Get current scanning statistics."""
        with self._lock:
            api_calls = self._client.api_calls if self._client else 0
            return ScanStats(
                api_calls=api_calls,
                start_time=self._stats.start_time,
                end_time=self._stats.end_time,
                current_folder=self._stats.current_folder,
                current_folder_start=self._stats.current_folder_start,
                folders_done=self._stats.folders_done,
                folders_total=self._stats.folders_total,
            )

    def get_discovered_setlist_count(self, drive_id: str) -> tuple[int, int] | None:
        """Get (enabled_count, total_count) for a drive."""
        with self._lock:
            setlist_ids = self._drive_setlist_ids.get(drive_id)
            if setlist_ids is None:
                return None
            total = len(setlist_ids)
            enabled = sum(1 for sid in setlist_ids if sid in self._enabled_setlist_ids)
            return (enabled, total)

    def get_scan_progress(self, drive_id: str) -> tuple[int, int] | None:
        """Get (scanned_count, total_count) for a drive's setlists.
        Failed setlists count toward progress so the UI doesn't stall."""
        with self._lock:
            setlist_ids = self._drive_setlist_ids.get(drive_id)
            if setlist_ids is None:
                return None
            total = len(setlist_ids)
            done = self._scanned_setlist_ids | self._failed_setlist_ids
            scanned = sum(1 for sid in setlist_ids if sid in done)
            return (scanned, total)

    def get_discovered_setlist_names(self, drive_id: str) -> list[str] | None:
        """Get setlist names for a drive."""
        with self._lock:
            return list(self._drive_setlist_names.get(drive_id, []))

    def is_setlist_scanned(self, drive_id: str, setlist_name: str) -> bool:
        """Check if a specific setlist was scanned this session."""
        with self._lock:
            for setlist_id, info in self._all_setlists.items():
                if info.drive_id == drive_id and info.name == setlist_name:
                    return setlist_id in self._scanned_setlist_ids
            return False

    def get_failed_setlist_names(self, drive_id: str) -> set[str]:
        """Get names of setlists that failed to scan for a given drive."""
        with self._lock:
            names = set()
            for setlist_id in self._failed_setlist_ids:
                info = self._all_setlists.get(setlist_id)
                if info and info.drive_id == drive_id:
                    names.add(info.name)
            return names

    def get_scanned_enabled_setlists(self) -> list[SetlistInfo]:
        """Get all enabled setlists that have finished scanning."""
        with self._lock:
            done = self._scanned_setlist_ids | self._failed_setlist_ids
            return [
                self._all_setlists[sid]
                for sid in self._enabled_setlist_ids
                if sid in done and sid in self._all_setlists
            ]

    def get_enabled_setlist_count(self) -> int:
        """Get total number of enabled setlists across all drives."""
        with self._lock:
            return len(self._enabled_setlist_ids)

    def has_scan_failures(self) -> bool:
        """Check if any setlists failed to scan."""
        with self._lock:
            return len(self._failed_setlist_ids) > 0

    def notify_setlist_toggled(self, drive_id: str, setlist_name: str, enabled: bool):
        """
        Called when user toggles a setlist. Updates enabled set.
        Scanner will prioritize newly enabled setlists on next iteration.
        """
        with self._lock:
            # Find the setlist_id for this name
            for setlist_id, info in self._all_setlists.items():
                if info.drive_id == drive_id and info.name == setlist_name:
                    if enabled:
                        self._enabled_setlist_ids.add(setlist_id)
                    else:
                        self._enabled_setlist_ids.discard(setlist_id)
                    break

    def add_folder(self, folder: dict):
        """Add a new folder to scan (for custom folders added at runtime)."""
        with self._lock:
            self._folders.append(folder)

        # Discover setlists for this folder
        if self._client:
            self._discover_folder_setlists(folder)

        # Restart scanner if it finished
        if self._thread is None or not self._thread.is_alive():
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._scan_worker, daemon=True)
            self._thread.start()

    # =========================================================================
    # Discovery
    # =========================================================================

    def _discover_all_setlists(self):
        """Discover all setlists from all folders."""
        for folder in self._folders:
            if self._stop_event.is_set():
                break
            self._discover_folder_setlists(folder)

    def _discover_folder_setlists(self, folder: dict):
        """Discover setlists within a single folder/drive."""
        drive_id = folder["folder_id"]
        drive_name = folder.get("name", "")
        is_custom = folder.get("is_custom", False)

        # Custom folders are single units (not containers of setlists)
        if is_custom:
            self._register_setlist(
                setlist_id=drive_id,
                name=drive_name,
                drive_id=drive_id,
                drive_name=drive_name,
                drive=folder,
            )
            return

        with self._lock:
            self._stats.current_folder = f"{drive_name} (discovering)"
            self._stats.current_folder_start = time.time()

        try:
            items = self._client.list_folder(drive_id)
        except Exception:
            # On error, treat whole drive as one unit
            self._register_setlist(
                setlist_id=drive_id,
                name=drive_name,
                drive_id=drive_id,
                drive_name=drive_name,
                drive=folder,
            )
            return

        discovered_names = []

        for item in items:
            mime_type = item.get("mimeType")

            if mime_type == self.FOLDER_MIME:
                setlist_id = item["id"]
                setlist_name = item["name"]
            elif mime_type == self.SHORTCUT_MIME:
                shortcut_details = item.get("shortcutDetails", {})
                target_mime = shortcut_details.get("targetMimeType", "")
                if target_mime != self.FOLDER_MIME:
                    continue
                setlist_id = shortcut_details.get("targetId")
                if not setlist_id:
                    continue
                setlist_name = item["name"]
            else:
                continue

            discovered_names.append(setlist_name)
            self._register_setlist(
                setlist_id=setlist_id,
                name=setlist_name,
                drive_id=drive_id,
                drive_name=drive_name,
                drive=folder,
            )

        # Sync settings with discovered names (Google Drive is source of truth)
        if self._user_settings and discovered_names:
            if self._user_settings.sync_subfolder_names(drive_id, discovered_names):
                self._settings_changed = True

        # Handle flat drives (no setlist subfolders)
        if not discovered_names:
            self._register_setlist(
                setlist_id=drive_id,
                name=drive_name,
                drive_id=drive_id,
                drive_name=drive_name,
                drive=folder,
            )

    def _register_setlist(
        self,
        setlist_id: str,
        name: str,
        drive_id: str,
        drive_name: str,
        drive: dict,
    ):
        """Register a discovered setlist."""
        info = SetlistInfo(
            setlist_id=setlist_id,
            name=name,
            drive_id=drive_id,
            drive_name=drive_name,
            drive=drive,
        )

        with self._lock:
            self._all_setlists[setlist_id] = info

            # Track per-drive
            if drive_id not in self._drive_setlist_ids:
                self._drive_setlist_ids[drive_id] = []
                self._drive_setlist_names[drive_id] = []
                if drive.get("files") is None:
                    drive["files"] = []
            self._drive_setlist_ids[drive_id].append(setlist_id)
            self._drive_setlist_names[drive_id].append(name)

            # Check if enabled
            if self._is_setlist_enabled(drive_id, name):
                self._enabled_setlist_ids.add(setlist_id)

    def _is_setlist_enabled(self, drive_id: str, setlist_name: str) -> bool:
        """Check if a setlist is enabled (drive enabled AND setlist enabled)."""
        if not self._user_settings:
            return True
        if not self._user_settings.is_drive_enabled(drive_id):
            return False
        return self._user_settings.is_subfolder_enabled(drive_id, setlist_name)

    # =========================================================================
    # Scanning
    # =========================================================================

    def _scan_worker(self):
        """Background thread: scan setlists, prioritizing enabled ones."""
        scanner = FolderScanner(self._client)

        while not self._stop_event.is_set():
            setlist = self._get_next_setlist_to_scan()
            if setlist is None:
                break  # All done

            self._scan_setlist(setlist, scanner)

        # Retry failed setlists once
        if not self._stop_event.is_set():
            with self._lock:
                retry_ids = list(self._failed_setlist_ids)
            for setlist_id in retry_ids:
                if self._stop_event.is_set():
                    break
                with self._lock:
                    setlist = self._all_setlists.get(setlist_id)
                    # Remove from failed so _scan_setlist can re-add on failure
                    self._failed_setlist_ids.discard(setlist_id)
                if setlist:
                    debug_log(f"SCAN_RETRY | setlist={setlist.name} | id={setlist_id}")
                    self._scan_setlist(setlist, scanner)
                    # If still not scanned after retry, it re-failed — mark as scanned
                    # so is_done()/is_ready_for_sync() don't hang
                    with self._lock:
                        if setlist_id in self._failed_setlist_ids:
                            self._scanned_setlist_ids.add(setlist_id)
                            self._stats.folders_done += 1

        # Done
        with self._lock:
            self._stats.current_folder = ""
            self._stats.end_time = time.time()

    def _get_next_setlist_to_scan(self) -> SetlistInfo | None:
        """Get next setlist to scan. Prioritizes enabled ones. Skips failed."""
        with self._lock:
            done = self._scanned_setlist_ids | self._failed_setlist_ids

            # Priority: enabled but not done
            for setlist_id in self._enabled_setlist_ids:
                if setlist_id not in done:
                    return self._all_setlists[setlist_id]

            # Then: any not done
            for setlist_id, info in self._all_setlists.items():
                if setlist_id not in done:
                    return info

            return None  # All scanned or failed

    def _scan_setlist(self, setlist: SetlistInfo, scanner: FolderScanner):
        """Scan a single setlist and accumulate files into its drive."""
        from .status import compute_setlist_stats
        from .cache import get_persistent_stats_cache

        drive = setlist.drive
        display_name = f"{setlist.drive_name}/{setlist.name}" if setlist.name != setlist.drive_name else setlist.drive_name

        scan_start = time.time()
        api_calls_before = self._client.api_calls

        with self._lock:
            self._stats.current_folder = display_name
            self._stats.current_folder_start = scan_start

        try:
            # base_path prefixes all file paths with the setlist name
            base_path = setlist.name if setlist.name != setlist.drive_name else ""
            result = scanner.scan(setlist.setlist_id, base_path=base_path)

            if result.cancelled or self._stop_event.is_set():
                return

            # Accumulate files into parent drive
            new_files = [
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

            with self._lock:
                if drive.get("files") is None:
                    drive["files"] = []
                drive["files"].extend(new_files)
                drive["file_count"] = len(drive["files"])
                drive["total_size"] = sum(f.get("size", 0) for f in drive["files"])

        except Exception:
            # Track failure — do NOT mark as scanned so purge can protect these files
            with self._lock:
                self._failed_setlist_ids.add(setlist.setlist_id)
                self._stats.current_folder_start = 0
            debug_log(f"SCAN_FAIL | setlist={display_name} | id={setlist.setlist_id}")
            return

        # Mark as scanned
        with self._lock:
            self._scanned_setlist_ids.add(setlist.setlist_id)
            self._stats.folders_done += 1
            self._stats.current_folder_start = 0

        # Compute and cache stats for this setlist
        if self._download_path:
            try:
                stats = compute_setlist_stats(
                    folder=drive,
                    setlist_name=setlist.name,
                    base_path=self._download_path,
                    user_settings=self._user_settings,
                )
                persistent_cache = get_persistent_stats_cache()
                persistent_cache.set_setlist(setlist.drive_id, setlist.name, stats)
            except Exception:
                pass  # Don't fail scan on stats computation error

        # Check if drive is now fully scanned
        if self.is_scanned(setlist.drive_id):
            drive["scan_duration"] = time.time() - self._stats.start_time
            drive["scan_api_calls"] = self._client.api_calls

            # Save persistent cache after drive completes
            if self._download_path:
                try:
                    persistent_cache = get_persistent_stats_cache()
                    persistent_cache.save()
                except Exception:
                    pass

            if self._on_folder_complete:
                try:
                    self._on_folder_complete(drive)
                except Exception:
                    pass
