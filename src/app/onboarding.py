"""Run as drives load: custom folders that turned out to already be released
drives, or setlists of them."""

from src import copy
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
            print(f"  {copy.MIGRATE_CUSTOM.format(old=custom_name, new=released_name)}")

            # a) Rename download folder on disk
            old_dir = download_path / custom_name
            new_dir = download_path / released_name
            if old_dir.exists() and not new_dir.exists():
                try:
                    old_dir.rename(new_dir)
                except OSError as e:
                    print(f"    {copy.FAILURE}: {e}")
            elif old_dir.exists() and new_dir.exists():
                print(f"    {copy.MIGRATE_EXISTS.format(target=released_name)}")

            # b) Rename marker files
            old_prefix = normalize_path_key(custom_name).replace("/", "_").replace("\\", "_") + "_"
            new_prefix = normalize_path_key(released_name).replace("/", "_").replace("\\", "_") + "_"
            if markers_dir.exists():
                for marker_file in markers_dir.glob("*.json"):
                    lower_stem = marker_file.stem.lower()
                    if lower_stem.startswith(old_prefix):
                        new_name = new_prefix + marker_file.name[len(old_prefix):]
                        new_path = markers_dir / new_name
                        if not new_path.exists():
                            try:
                                marker_file.rename(new_path)
                            except OSError:
                                pass

            # c) Remove custom folder entry
            self.custom_folders.remove_folder(folder_id)

        self.custom_folders.save()

    def _turn_off_shipped_copies(self):
        """A custom folder that turns out to be a setlist of a shipped drive
        stays a custom folder. While it is on, the drive's own copy of that
        setlist is off, or the same charts download twice. While it is off,
        the drive's copy is left as the user had it: turning it off then
        would purge a setlist they sync through the drive."""
        from src.core.logging import debug_log

        scanner = self._background_scanner
        if not scanner or not scanner.all_setlists:
            return

        settings = self.user_settings
        released_ids = {d.folder_id for d in self.drives_config.drives}
        customs_on = {c.folder_id: c.name for c in self.custom_folders.folders
                      if settings.is_drive_enabled(c.folder_id)}
        changed = False
        for s in list(scanner.all_setlists.values()):
            if (s.drive_id in released_ids and s.setlist_id in customs_on
                    and settings.is_subfolder_enabled(s.drive_id, s.name)):
                settings.set_subfolder_enabled(s.drive_id, s.name, False)
                scanner.notify_setlist_toggled(s.drive_id, s.name, False)
                debug_log(f"TOGGLES | {s.drive_name}/{s.name} | off, "
                          f"custom folder {customs_on[s.setlist_id]} is the same")
                changed = True
        if changed:
            settings.save()
