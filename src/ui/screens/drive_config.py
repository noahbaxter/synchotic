"""
Drive configuration screen - setlist toggle settings for a drive.

Allows enabling/disabling individual setlists within a chart pack.
"""

from pathlib import Path
import re

from src.core.formatting import dedupe_files_by_newest, sort_by_name
from src.core.logging import debug_log
from src.core.constants import CHART_MARKERS
from src.config import UserSettings, extract_subfolders_from_files
from src.sync import get_setlist_sync_status, SyncStatus
from src.sync.download_planner import is_archive_file
from ..primitives import Colors
from ..components import format_drive_status, format_setlist_item
from ..widgets import Menu, MenuItem, MenuDivider


def _compute_setlist_stats_from_files(folder: dict, dedupe: bool = True) -> dict:
    """Compute setlist stats from files list."""
    stats = {}
    files = (folder.get("files") or [])

    if dedupe:
        files = dedupe_files_by_newest(files)

    chart_folders = {}

    for f in files:
        path = f.get("path", "")
        size = f.get("size", 0)

        if "/" not in path:
            continue

        setlist = path.split("/")[0]
        if setlist not in stats:
            stats[setlist] = {"archives": 0, "charts": 0, "total_size": 0}

        stats[setlist]["total_size"] += size

        parts = path.split("/")
        if len(parts) >= 2:
            filename = parts[-1].lower()

            if is_archive_file(filename):
                stats[setlist]["archives"] += 1
                chart_key = (setlist, path)
                chart_folders[chart_key] = {"setlist": setlist, "is_chart": True}
            elif len(parts) >= 3:
                parent = "/".join(parts[:-1])
                chart_key = (setlist, parent)
                if chart_key not in chart_folders:
                    chart_folders[chart_key] = {"setlist": setlist, "is_chart": False}
                if filename in {m.lower() for m in CHART_MARKERS}:
                    chart_folders[chart_key]["is_chart"] = True

    for key, data in chart_folders.items():
        if data["is_chart"]:
            stats[data["setlist"]]["charts"] += 1

    return stats


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
        # Note: extract_subfolders_from_files already sorts
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

    # Compute setlist stats from files (works for both custom and regular folders)
    computed_stats = _compute_setlist_stats_from_files(folder, dedupe=True)
    local_folder_path = download_path / folder_name if download_path else None

    setlist_stats = {}
    for name, data in computed_stats.items():
        setlist_stats[name] = {
            "charts": {"total": data["charts"]},
            "archives": data["archives"],
            "total_size": data["total_size"],
        }

    selected_index = 0
    needs_scan = True  # First iteration does full scan

    # Cache for setlist data (doesn't change on toggle - shows what's on disk)
    # {setlist_name: {"sync": SyncStatus, "disk_files": int, "disk_size": int}}
    cached_setlist_data = {}

    while True:
        drive_enabled = user_settings.is_drive_enabled(folder_id)

        # Full scan only on first iteration - expensive disk operations
        if needs_scan and download_path:
            delete_videos = user_settings.delete_videos if user_settings else True
            for setlist_name in setlists:
                # Get sync status from manifest comparison
                if not is_custom:
                    sync_status = get_setlist_sync_status(
                        folder, setlist_name, download_path,
                        delete_videos=delete_videos,
                    )
                else:
                    sync_status = SyncStatus()

                # Get actual disk content (includes orphaned files)
                disk_files = 0
                disk_size = 0
                if local_folder_path:
                    setlist_path = local_folder_path / setlist_name
                    if setlist_path.exists():
                        try:
                            for f in setlist_path.rglob("*"):
                                if f.is_file():
                                    disk_files += 1
                                    disk_size += f.stat().st_size
                        except OSError:
                            pass

                cached_setlist_data[setlist_name] = {
                    "sync": sync_status,
                    "disk_files": disk_files,
                    "disk_size": disk_size,
                }
            needs_scan = False

        # Aggregate stats from cache based on current enabled/disabled state (fast!)
        status = SyncStatus()
        excess_files = 0
        excess_size = 0
        excess_charts = 0

        for setlist_name in setlists:
            data = cached_setlist_data.get(setlist_name, {})
            sync = data.get("sync", SyncStatus())
            disk_files = data.get("disk_files", 0)
            disk_size = data.get("disk_size", 0)
            setlist_enabled = user_settings.is_subfolder_enabled(folder_id, setlist_name)

            if drive_enabled and setlist_enabled:
                # Enabled: contributes to sync totals
                status.total_charts += sync.total_charts
                status.synced_charts += sync.synced_charts
                status.total_size += sync.total_size
                status.synced_size += sync.synced_size
            elif drive_enabled and not setlist_enabled and disk_files > 0:
                # Disabled with content: contributes to purgeable
                excess_files += disk_files
                excess_size += disk_size
                excess_charts += setlist_stats.get(setlist_name, {}).get("charts", {}).get("total", 0)

        # Log full setlist page state
        debug_log(f"SETLIST_PAGE | === {folder_name} ===")
        debug_log(f"SETLIST_PAGE | drive_enabled={drive_enabled} | +{status.missing_size} -{excess_size}")

        # Count enabled setlists
        enabled_setlist_count = sum(
            1 for s in setlists
            if user_settings.is_subfolder_enabled(folder_id, s)
        )

        delta_mode = user_settings.delta_mode if user_settings else "size"

        # Build subtitle using format_drive_status
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
        )

        mode_label = {"size": "Size  ", "files": "Files ", "charts": "Charts"}.get(delta_mode, "Size  ")
        legend = f"{Colors.MUTED}[Tab]{Colors.RESET} {mode_label}   {Colors.RESET}+{Colors.MUTED} add   {Colors.RED}-{Colors.MUTED} remove"
        menu = Menu(title=f"{folder_name} - Setlists:", subtitle=subtitle, space_hint="Toggle", footer=legend)

        for i, setlist_name in enumerate(setlists):
            setlist_enabled = user_settings.is_subfolder_enabled(folder_id, setlist_name)

            stats = setlist_stats.get(setlist_name, {})
            total_size = stats.get("total_size", 0)

            if is_custom:
                item_count = stats.get("archives", 0)
            else:
                item_count = stats.get("charts", {}).get("total", 0)
            unit = "files" if item_count != 1 else "file"

            # Get sync status and disk stats from cache (fast!)
            cached_data = cached_setlist_data.get(setlist_name, {})
            setlist_status = cached_data.get("sync", SyncStatus())
            setlist_disk_files = cached_data.get("disk_files", 0)
            setlist_disk_size = cached_data.get("disk_size", 0)

            if not is_custom and download_path:
                synced_charts = setlist_status.synced_charts
                synced_size = setlist_status.synced_size
                setlist_total_charts = setlist_status.total_charts
                setlist_total_size = setlist_status.total_size
                is_fully_synced = synced_charts == setlist_total_charts and setlist_total_charts > 0
            else:
                # Custom folders: use disk size for synced check
                synced_size = setlist_disk_size
                synced_charts = item_count if synced_size >= total_size and total_size > 0 else 0
                setlist_total_charts = item_count
                setlist_total_size = total_size
                is_fully_synced = synced_charts == setlist_total_charts and setlist_total_charts > 0

            # Calculate purgeable for this setlist (from cache - fast!)
            setlist_purgeable_files = 0
            setlist_purgeable_size = 0
            missing_charts = 0

            if drive_enabled:
                if not setlist_enabled and setlist_disk_files > 0:
                    # Disabled setlist with content: all content is purgeable
                    setlist_purgeable_files = setlist_disk_files
                    setlist_purgeable_size = setlist_disk_size

                # Calculate missing charts (only if enabled and not fully synced)
                if setlist_enabled and not is_fully_synced:
                    missing_charts = setlist_total_charts - synced_charts

            # Format using new function
            description = format_setlist_item(
                total_charts=setlist_total_charts,
                synced_charts=synced_charts,
                total_size=setlist_total_size,
                synced_size=synced_size,
                purgeable_files=setlist_purgeable_files,
                purgeable_charts=item_count if setlist_purgeable_files > 0 else 0,
                purgeable_size=setlist_purgeable_size,
                missing_charts=missing_charts,
                disabled=not setlist_enabled or not drive_enabled,
                unit=unit,
                delta_mode=delta_mode,
            )

            # Log each setlist's state
            desc_clean = re.sub(r'\x1b\[[0-9;]*m', '', description) if description else ""
            debug_log(f"SETLIST_PAGE | [{'+' if setlist_enabled else '-'}] {setlist_name}: {desc_clean}")

            item_disabled = not setlist_enabled or not drive_enabled
            show_toggle_colored = setlist_enabled and drive_enabled

            menu.add_item(MenuItem(setlist_name, value=("toggle", i, setlist_name), description=description if description else None, disabled=item_disabled, show_toggle=show_toggle_colored))

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

        # Log subtitle after all setlists
        subtitle_clean = re.sub(r'\x1b\[[0-9;]*m', '', subtitle)
        debug_log(f"SETLIST_PAGE | subtitle: {subtitle_clean}")
        debug_log(f"SETLIST_PAGE | === End {folder_name} ===")

        # Set up scanning status line and auto-refresh (same as home screen)
        if scanner and not scanner.is_done():
            from src.core.formatting import format_duration

            # Track scan progress at menu build time
            initial_scan_progress = scanner.get_scan_progress(folder_id)
            initial_scanned = initial_scan_progress[0] if initial_scan_progress else 0

            def on_menu_update(menu_instance) -> bool | str:
                # Check if any new setlists finished scanning for THIS drive
                current_progress = scanner.get_scan_progress(folder_id)
                current_scanned = current_progress[0] if current_progress else 0
                if current_scanned > initial_scanned:
                    return "rebuild"  # Signal to rebuild menu items

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
                return False  # No full re-render needed

            menu.update_callback = on_menu_update
            stats = scanner.get_stats()
            if stats.current_folder:
                menu.status_line = f"Scanning: {stats.current_folder} ({stats.folders_done + 1}/{stats.folders_total}) | {stats.api_calls} API calls"
            else:
                menu.status_line = "Starting scan..."

        result = menu.run(initial_index=selected_index)

        if result is None or result.value[0] == "back":
            break

        # Handle rebuild signal from scanner completing setlists
        if result.action == "rebuild":
            selected_index = menu._selected
            cached_setlist_data.clear()  # Clear cache to recalculate with new data
            needs_scan = True  # Trigger full rescan
            continue

        # Handle Tab to cycle delta mode
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
            # Notify scanner about all setlists being enabled
            if scanner:
                for name in setlists:
                    scanner.notify_setlist_toggled(folder_id, name, True)
            user_settings.save()
            # No rescan needed - aggregation uses current enabled state

        elif action == "disable_all":
            selected_index = menu._selected_before_hotkey
            user_settings.disable_all(folder_id, setlists)
            # Notify scanner about all setlists being disabled
            if scanner:
                for name in setlists:
                    scanner.notify_setlist_toggled(folder_id, name, False)
            user_settings.save()
            # No rescan needed - aggregation uses current enabled state

        elif action == "toggle":
            selected_index = menu._selected
            if not user_settings.is_drive_enabled(folder_id):
                # Drive is disabled - just enable it, don't toggle setlist
                user_settings.enable_drive(folder_id)
            else:
                # Drive is enabled - toggle the setlist
                new_state = user_settings.toggle_subfolder(folder_id, setlist_name)
                # Notify scanner so it can reprioritize if needed
                if scanner:
                    scanner.notify_setlist_toggled(folder_id, setlist_name, new_state)
            user_settings.save()
            # No rescan needed - aggregation uses current enabled state

        elif action == "scan":
            return "scan"

        elif action == "remove":
            return "remove"

    return True  # Settings may have changed
