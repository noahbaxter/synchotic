"""Drive list and custom-folder management: loading, configuring, scanning,
adding, and removing them."""

from src.app.config import API_KEY
from src.config import DrivesConfig
from src.core.formatting import format_size
from src.core.paths import get_download_path
from src.drive import DriveClient
from src.drive.client import DriveClientConfig
from src.ui import show_add_custom_folder, show_confirmation, show_subfolder_settings
from src.ui.primitives import wait_with_skip
from src.ui.widgets import display


class DriveManagementMixin:

    def load_drives(self, quiet: bool = False):
        """Load drive list from drives.json. File data comes from scanner.

        Builds folder list from static drive config only. Files are populated
        by the BackgroundScanner when scanning completes.
        """
        # Migrate custom folders that are now released drives
        self._migrate_custom_to_released()

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

        # An upgraded install had unseen drives on by default. Once the drives
        # are known, write that down as toggles (a no-op after the first run).
        self.user_settings.settle_drive_defaults(
            [f["folder_id"] for f in self.folders])

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

    def _scan_single_custom_folder(self, folder: dict):
        """Scan a single custom folder."""
        from src.drive import FolderScanner

        # Same rule as every other Drive call, not OAuth: a public folder
        # resolves on the API key, and rclone downloads through its own remote.
        blocked = self._drive_blocked()
        if blocked:
            display.sync_blocked(blocked)
            wait_with_skip(3)
            return

        blocked = self._library_blocked()
        if blocked:
            display.library_blocked(blocked)
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

    def handle_toggle_group(self, group_name: str):
        """Toggle a group expanded/collapsed."""
        self.user_settings.toggle_group_expanded(group_name)
        self.user_settings.save()

    def handle_add_custom_folder(self) -> bool:
        """
        Handle adding a custom Google Drive folder.

        Returns True if a folder was added successfully.
        """
        # A public folder resolves on the API key alone, so this asks only that
        # the mode works. A genuinely private folder still fails validation
        # below, with the access error that actually describes the problem.
        blocked = self._drive_blocked()
        if blocked:
            display.custom_folder_blocked(blocked)
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

        # Block adding folders that are already released drives
        released_by_id = {d.folder_id: d.name for d in self.drives_config.drives}
        released_ids = set(released_by_id)
        if folder_id in released_ids:
            print(f"\n  This folder is already available as a built-in drive.")
            wait_with_skip(2)
            return False

        # Block subfolders of released drives (one API call)
        metadata = auth_client.get_file_metadata(folder_id, "parents")
        if metadata:
            parents = set(metadata.get("parents", []))
            parent_match = parents & released_ids
            if parent_match:
                drive_name = released_by_id[parent_match.pop()]
                print(f"\n  This folder is inside the built-in drive: {drive_name}")
                print(f"  Enable it from the drive list instead.")
                wait_with_skip(3)
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

    def _get_folder_by_id(self, folder_id: str) -> dict | None:
        """Get folder dict by folder_id."""
        for folder in self.folders:
            if folder.get("folder_id", "") == folder_id:
                return folder
        return None

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
