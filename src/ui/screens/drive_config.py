"""
Drive configuration screen - setlist toggle settings for a drive.

Allows enabling/disabling individual setlists within a chart pack.
"""

from pathlib import Path
import re

from src.core.formatting import sort_by_name
from src.core.logging import debug_log
from src.config import UserSettings, extract_subfolders_from_files
from src.sync import SyncStatus, CachedSetlistStats, get_persistent_stats_cache, compute_setlist_stats
from ..primitives import Colors
from ..components import format_drive_status, format_setlist_item, format_column_header
from ..widgets import Menu, MenuItem, MenuDivider


class DriveConfigScreen:
    """Screen for configuring setlist toggles within a drive."""

    def __init__(
        self,
        folder: dict,
        user_settings: UserSettings,
        download_path: Path = None,
    ):
        self.folder = folder
        self.user_settings = user_settings
        self.download_path = download_path

    def run(self) -> str | bool:
        """Run the config screen. Returns True/False for changes, or 'scan'/'remove' for actions."""
        return show_subfolder_settings(
            self.folder,
            self.user_settings,
            self.download_path,
        )


def show_subfolder_settings(
    folder: dict,
    user_settings: UserSettings,
    download_path: Path = None,
    scanner=None,  # BackgroundScanner for discovered setlist names
) -> str | bool:
    """Show toggle menu for setlists within a drive."""
    folder_id = folder.get("folder_id", "")
    folder_name = folder.get("name", "Unknown")
    is_custom = folder.get("is_custom", False)
    has_files = bool(folder.get("files"))

    # Prefer discovered setlist names from scanner (includes shortcuts)
    discovered_names = scanner.get_discovered_setlist_names(folder_id) if scanner else None
    if discovered_names:
        setlists = sort_by_name(discovered_names)
    else:
        # Fallback: extract from file paths (doesn't know about shortcuts)
        setlists = extract_subfolders_from_files(folder)

    if not setlists and not is_custom:
        return False

    if not setlists and is_custom:
        menu = Menu(title=f"{folder_name}:", subtitle="Folder not yet scanned")
        scan_label = "Re-scan folder" if has_files else "Scan folder"
        scan_desc = "Refresh file list from Google Drive" if has_files else "Get file list from Google Drive"
        menu.add_item(MenuItem(scan_label, hotkey="S", value="scan", description=scan_desc))
        menu.add_item(MenuItem("Remove folder", hotkey="X", value="remove", description="Remove from custom folders"))
        menu.add_item(MenuDivider())
        menu.add_item(MenuItem("Back", value="back"))

        result = menu.run()
        if result and result.value in ("scan", "remove"):
            return result.value
        return False

    selected_index = 0
    needs_cache_update = True  # First iteration ensures all setlist stats are cached

    # Get persistent cache
    persistent_cache = get_persistent_stats_cache()

    while True:
        drive_enabled = user_settings.is_drive_enabled(folder_id)

        # Ensure all setlist stats are cached (compute if missing)
        if needs_cache_update and download_path and has_files:
            for setlist_name in setlists:
                if not persistent_cache.get_setlist(folder_id, setlist_name):
                    stats = compute_setlist_stats(folder, setlist_name, download_path, user_settings)
                    persistent_cache.set_setlist(folder_id, setlist_name, stats)
            persistent_cache.save()
            needs_cache_update = False

        # Aggregate stats using cached setlist data (fast!)
        status = SyncStatus()
        excess_files = 0
        excess_size = 0
        excess_charts = 0

        for setlist_name in setlists:
            cached = persistent_cache.get_setlist(folder_id, setlist_name)
            if not cached:
                continue

            setlist_enabled = user_settings.is_subfolder_enabled(folder_id, setlist_name)

            if drive_enabled and setlist_enabled:
                status.total_charts += cached.total_charts
                status.synced_charts += cached.synced_charts
                status.total_size += cached.total_size
                status.synced_size += cached.synced_size
            elif drive_enabled and not setlist_enabled and cached.disk_files > 0:
                excess_files += cached.disk_files
                excess_size += cached.disk_size
                excess_charts += cached.disk_charts

        debug_log(f"SETLIST_PAGE | === {folder_name} ===")
        debug_log(f"SETLIST_PAGE | drive_enabled={drive_enabled} | +{status.missing_size} -{excess_size}")

        enabled_setlist_count = sum(
            1 for s in setlists
            if user_settings.is_subfolder_enabled(folder_id, s)
        )

        delta_mode = user_settings.delta_mode if user_settings else "size"

        # Drive delta is estimated if any enabled setlist hasn't been scanned this session
        drive_is_estimate = scanner is not None and scanner.is_scanning(folder_id)

        subtitle = format_drive_status(
            synced_charts=status.synced_charts,
            total_charts=status.total_charts,
            enabled_setlists=enabled_setlist_count,
            total_setlists=len(setlists),
            total_size=status.total_size,
            synced_size=status.synced_size,
            missing_charts=status.missing_charts,
            purgeable_files=excess_files,
            purgeable_charts=excess_charts,
            purgeable_size=excess_size,
            disabled=not drive_enabled,
            delta_mode=delta_mode,
            is_estimate=drive_is_estimate,
        )

        mode_label = {"size": "Size  ", "files": "Files ", "charts": "Charts"}.get(delta_mode, "Size  ")
        legend = f"{Colors.MUTED}[Tab]{Colors.RESET} {mode_label}   {Colors.RESET}+{Colors.MUTED} add   {Colors.RED}-{Colors.MUTED} remove"
        menu = Menu(title=f"{folder_name}", subtitle=subtitle, space_hint="Toggle", footer=legend,
                    column_header=format_column_header("setlist"))

        for i, setlist_name in enumerate(setlists):
            setlist_enabled = user_settings.is_subfolder_enabled(folder_id, setlist_name)
            cached = persistent_cache.get_setlist(folder_id, setlist_name)

            # Determine state: scanned this session, cached from previous, or currently scanning
            if scanner and scanner.is_setlist_scanned(folder_id, setlist_name):
                setlist_state = "current"  # Scanned this session
            elif scanner and scanner.is_scanning(folder_id):
                setlist_state = "scanning"  # Drive has unscanned setlists, this one not done yet
            elif cached:
                setlist_state = "cached"  # Has persistent cache but not scanned this session
            else:
                setlist_state = "current"  # No scanner, no cache - show as-is

            if cached:
                setlist_total_charts = cached.total_charts
                setlist_total_size = cached.total_size
                synced_charts = cached.synced_charts
                synced_size = cached.synced_size
                setlist_disk_files = cached.disk_files
                setlist_disk_size = cached.disk_size
                setlist_disk_charts = cached.disk_charts
            else:
                setlist_total_charts = 0
                setlist_total_size = 0
                synced_charts = 0
                synced_size = 0
                setlist_disk_files = 0
                setlist_disk_size = 0
                setlist_disk_charts = 0

            is_fully_synced = synced_charts == setlist_total_charts and setlist_total_charts > 0

            # Calculate purgeable for this setlist
            setlist_purgeable_files = 0
            setlist_purgeable_size = 0
            setlist_purgeable_charts = 0
            missing_charts = 0

            if drive_enabled:
                if not setlist_enabled and setlist_disk_files > 0:
                    setlist_purgeable_files = setlist_disk_files
                    setlist_purgeable_size = setlist_disk_size
                    setlist_purgeable_charts = setlist_disk_charts

                if setlist_enabled and not is_fully_synced:
                    missing_charts = setlist_total_charts - synced_charts

            columns, delta, show_checkmark = format_setlist_item(
                total_charts=setlist_total_charts,
                synced_charts=synced_charts,
                total_size=setlist_total_size,
                synced_size=synced_size,
                purgeable_files=setlist_purgeable_files,
                purgeable_charts=setlist_purgeable_charts,
                purgeable_size=setlist_purgeable_size,
                missing_charts=missing_charts,
                disabled=not setlist_enabled or not drive_enabled,
                delta_mode=delta_mode,
                state=setlist_state,
            )

            # Build label with checkmark, italic for scanning, delta appended
            is_scanning = (setlist_state == "scanning")
            is_disabled_item = not setlist_enabled or not drive_enabled
            check = f"{Colors.GREEN}✓\x1b[39m" if show_checkmark else " "

            if is_scanning:
                if is_disabled_item:
                    label = f"{check} {Colors.ITALIC}{Colors.DIM}{setlist_name}{Colors.RESET}"
                else:
                    label = f"{check} {Colors.ITALIC}{setlist_name}{Colors.RESET}"
            else:
                label = f"{check} {setlist_name}"
            if delta:
                label = f"{label} {delta}"

            desc_clean = re.sub(r'\x1b\[[0-9;]*m', '', columns) if columns else ""
            debug_log(f"SETLIST_PAGE | [{'+' if setlist_enabled else '-'}] {setlist_name}: {desc_clean}")

            item_disabled = not setlist_enabled or not drive_enabled
            show_toggle_colored = setlist_enabled and drive_enabled

            menu.add_item(MenuItem(label, value=("toggle", i, setlist_name), description=columns if columns else None, disabled=item_disabled, show_toggle=show_toggle_colored))

        menu.add_item(MenuDivider(pinned=True))

        menu.add_item(MenuItem("Enable ALL", hotkey="E", value=("enable_all", None, None), pinned=True))
        menu.add_item(MenuItem("Disable ALL", hotkey="D", value=("disable_all", None, None), pinned=True))

        if is_custom:
            menu.add_item(MenuDivider(pinned=True))
            has_files = bool(folder.get("files"))
            scan_label = "Re-scan folder" if has_files else "Scan folder"
            scan_desc = "Refresh file list from Google Drive" if has_files else "Get file list from Google Drive"
            menu.add_item(MenuItem(scan_label, hotkey="S", value=("scan", None, None), description=scan_desc, pinned=True))
            menu.add_item(MenuItem("Remove folder", hotkey="X", value=("remove", None, None), description="Remove from custom folders", pinned=True))

        menu.add_item(MenuDivider(pinned=True))
        menu.add_item(MenuItem("Back", value=("back", None, None), pinned=True))

        subtitle_clean = re.sub(r'\x1b\[[0-9;]*m', '', subtitle)
        debug_log(f"SETLIST_PAGE | subtitle: {subtitle_clean}")
        debug_log(f"SETLIST_PAGE | === End {folder_name} ===")

        # Set up scanning status line and auto-refresh
        if scanner and not scanner.is_done():
            from src.core.formatting import format_duration

            initial_scan_progress = scanner.get_scan_progress(folder_id)
            initial_scanned = initial_scan_progress[0] if initial_scan_progress else 0

            def on_menu_update(menu_instance) -> bool | str:
                current_progress = scanner.get_scan_progress(folder_id)
                current_scanned = current_progress[0] if current_progress else 0
                if current_scanned > initial_scanned:
                    return "rebuild"

                stats = scanner.get_stats()
                if stats.current_folder:
                    folder_elapsed = format_duration(stats.current_folder_elapsed)
                    total_elapsed = format_duration(stats.elapsed)
                    new_status = (
                        f"Scanning: {stats.current_folder} "
                        f"({stats.folders_done + 1}/{stats.folders_total}) | "
                        f"{folder_elapsed} | {total_elapsed} total | {stats.api_calls} API calls"
                    )
                else:
                    if stats.elapsed > 0:
                        new_status = f"Ready | {format_duration(stats.elapsed)} | {stats.api_calls} API calls"
                    else:
                        new_status = f"Ready | {stats.api_calls} API calls this session"

                menu_instance.update_status_line_in_place(new_status)
                return False

            menu.update_callback = on_menu_update
            stats = scanner.get_stats()
            if stats.current_folder:
                menu.status_line = f"Scanning: {stats.current_folder} ({stats.folders_done + 1}/{stats.folders_total}) | {stats.api_calls} API calls"
            else:
                menu.status_line = "Starting scan..."

        result = menu.run(initial_index=selected_index)

        if result is None or result.value[0] == "back":
            break

        if result.action == "rebuild":
            selected_index = menu._selected
            needs_cache_update = True
            continue

        if result.action == "tab":
            selected_index = menu._selected
            user_settings.cycle_delta_mode()
            user_settings.save()
            continue

        action, idx, setlist_name = result.value

        if action == "enable_all":
            selected_index = menu._selected_before_hotkey
            if not user_settings.is_drive_enabled(folder_id):
                user_settings.enable_drive(folder_id)
            user_settings.enable_all(folder_id, setlists)
            if scanner:
                for name in setlists:
                    scanner.notify_setlist_toggled(folder_id, name, True)
            user_settings.save()

        elif action == "disable_all":
            selected_index = menu._selected_before_hotkey
            user_settings.disable_all(folder_id, setlists)
            if scanner:
                for name in setlists:
                    scanner.notify_setlist_toggled(folder_id, name, False)
            user_settings.save()

        elif action == "toggle":
            selected_index = menu._selected
            if not user_settings.is_drive_enabled(folder_id):
                user_settings.enable_drive(folder_id)
            else:
                new_state = user_settings.toggle_subfolder(folder_id, setlist_name)
                if scanner:
                    scanner.notify_setlist_toggled(folder_id, setlist_name, new_state)
            user_settings.save()

        elif action == "scan":
            return "scan"

        elif action == "remove":
            return "remove"

    return True
