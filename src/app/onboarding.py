"""One-time migrations run as drives load: custom folders that turned out to
already be released drives, or subfolders of them."""

from src.core.formatting import normalize_path_key
from src.core.paths import get_download_path


class OnboardingMixin:

    def _migrate_custom_to_released(self):
        """Migrate custom folders that now match released drives.

        When a user added a Google Drive folder as custom before it became
        an official released pack, they end up with duplicates. This renames
        the download folder and marker files to match the released name,
        then removes the custom entry.
        """
        from src.sync.markers import get_markers_dir

        released_by_id = {d.folder_id: d.name for d in self.drives_config.drives}

        # Same-name duplicates: just remove the custom entry, no renames needed
        same_name_ids = [
            c.folder_id for c in self.custom_folders.folders
            if c.folder_id in released_by_id and released_by_id[c.folder_id] == c.name
        ]
        for folder_id in same_name_ids:
            print(f"  Removing duplicate custom entry: {released_by_id[folder_id]}")
            self.custom_folders.remove_folder(folder_id)
        if same_name_ids:
            self.custom_folders.save()

        # Different-name duplicates: rename folder + markers, then remove
        to_migrate = []
        for custom in self.custom_folders.folders:
            released_name = released_by_id.get(custom.folder_id)
            if released_name and released_name != custom.name:
                to_migrate.append((custom.folder_id, custom.name, released_name))

        if not to_migrate:
            return

        download_path = get_download_path()
        markers_dir = get_markers_dir()

        for folder_id, custom_name, released_name in to_migrate:
            print(f"  Migrating custom folder: {custom_name} → {released_name}")

            # a) Rename download folder on disk
            old_dir = download_path / custom_name
            new_dir = download_path / released_name
            if old_dir.exists() and not new_dir.exists():
                try:
                    old_dir.rename(new_dir)
                    print(f"    Renamed download folder")
                except OSError as e:
                    print(f"    Warning: could not rename folder: {e}")
            elif old_dir.exists() and new_dir.exists():
                print(f"    Warning: both '{custom_name}' and '{released_name}' exist on disk, skipping folder rename")

            # b) Rename marker files
            old_prefix = normalize_path_key(custom_name).replace("/", "_").replace("\\", "_") + "_"
            new_prefix = normalize_path_key(released_name).replace("/", "_").replace("\\", "_") + "_"
            renamed = 0
            if markers_dir.exists():
                for marker_file in markers_dir.glob("*.json"):
                    lower_stem = marker_file.stem.lower()
                    if lower_stem.startswith(old_prefix):
                        new_name = new_prefix + marker_file.name[len(old_prefix):]
                        new_path = markers_dir / new_name
                        if not new_path.exists():
                            try:
                                marker_file.rename(new_path)
                                renamed += 1
                            except OSError:
                                pass
            if renamed:
                print(f"    Renamed {renamed} marker file(s)")

            # c) Remove custom folder entry
            self.custom_folders.remove_folder(folder_id)

        self.custom_folders.save()
        print(f"  Migration complete: {len(to_migrate)} folder(s) migrated")

    def _migrate_subfolder_customs(self):
        """Migrate custom folders that are subfolders of released drives.

        After discovery, the scanner knows every setlist inside every drive.
        If a custom folder's ID matches a discovered setlist, it means the
        user added a subfolder of a built-in drive as custom. Silently migrate
        the download folder and markers to the correct drive/setlist structure.
        """
        if not self._background_scanner:
            return

        all_setlists = self._background_scanner.all_setlists
        if not all_setlists:
            return

        released_ids = {d.folder_id for d in self.drives_config.drives}
        from src.sync.markers import get_markers_dir

        to_migrate = []
        for custom in self.custom_folders.folders:
            setlist = all_setlists.get(custom.folder_id)
            if setlist and setlist.drive_id in released_ids:
                to_migrate.append((custom.folder_id, custom.name, setlist))

        if not to_migrate:
            return

        download_path = get_download_path()
        markers_dir = get_markers_dir()

        for folder_id, custom_name, setlist in to_migrate:
            drive_name = setlist.drive_name
            setlist_name = setlist.name
            print(f"  Migrating subfolder custom: {custom_name} → {drive_name}/{setlist_name}")

            # a) Move download folder into drive subfolder
            old_dir = download_path / custom_name
            drive_dir = download_path / drive_name
            new_dir = drive_dir / setlist_name
            if old_dir.exists() and not new_dir.exists():
                try:
                    drive_dir.mkdir(parents=True, exist_ok=True)
                    old_dir.rename(new_dir)
                    print(f"    Moved download folder")
                except OSError as e:
                    print(f"    Warning: could not move folder: {e}")
            elif old_dir.exists() and new_dir.exists():
                print(f"    Warning: target '{drive_name}/{setlist_name}' already exists, skipping folder move")

            # b) Rename marker files
            old_prefix = normalize_path_key(custom_name).replace("/", "_").replace("\\", "_") + "_"
            new_prefix = normalize_path_key(drive_name).replace("/", "_").replace("\\", "_") + "_" + \
                normalize_path_key(setlist_name).replace("/", "_").replace("\\", "_") + "_"
            renamed = 0
            if markers_dir.exists():
                for marker_file in markers_dir.glob("*.json"):
                    lower_stem = marker_file.stem.lower()
                    if lower_stem.startswith(old_prefix):
                        new_name = new_prefix + marker_file.name[len(old_prefix):]
                        new_path = markers_dir / new_name
                        if not new_path.exists():
                            try:
                                marker_file.rename(new_path)
                                renamed += 1
                            except OSError:
                                pass
            if renamed:
                print(f"    Renamed {renamed} marker file(s)")

            # c) Remove custom folder entry
            self.custom_folders.remove_folder(folder_id)

            # d) Remove from self.folders so it doesn't appear as a separate drive
            self.folders[:] = [f for f in self.folders if f.get("folder_id") != folder_id]

        self.custom_folders.save()
        print(f"  Subfolder migration complete: {len(to_migrate)} folder(s) migrated")
