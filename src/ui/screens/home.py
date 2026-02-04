"""
Home screen - main menu of the application.

Shows available chart packs, sync status, and navigation options.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from src.config import UserSettings, DrivesConfig, extract_subfolders_from_files
from src.core.logging import debug_log
from src.sync import (
    SyncStatus, FolderStats, FolderStatsCache, get_persistent_stats_cache,
    PersistentStatsCache, aggregate_folder_stats, compute_setlist_stats,
)
from ..primitives import Colors
from ..components import format_status_line, format_home_item, format_delta
from ..widgets import Menu, MenuItem, MenuDivider, MenuGroupHeader

if TYPE_CHECKING:
    from src.drive.auth import AuthManager
    from src.sync import BackgroundScanner


@dataclass
class MainMenuCache:
    """Cache for expensive main menu calculations."""
    subtitle: str = ""
    sync_action_desc: str = ""
    folder_stats: dict = field(default_factory=dict)
    group_enabled_counts: dict = field(default_factory=dict)


def update_menu_cache_on_toggle(
    menu_cache: MainMenuCache,
    folder_id: str,
    folders: list,
    user_settings: UserSettings,
    folder_stats_cache: FolderStatsCache,
    drives_config: DrivesConfig = None,
    background_scanner: "BackgroundScanner" = None,
) -> None:
    """
    Quickly update menu cache after a drive toggle using setlist-centric aggregation.

    Uses aggregate_folder_stats for instant re-aggregation without disk I/O.
    """
    drive_enabled = user_settings.is_drive_enabled(folder_id)
    delta_mode = user_settings.delta_mode
    scan_complete = not background_scanner or background_scanner.is_done()
    persistent_cache = get_persistent_stats_cache()

    # Update toggled folder's display string using aggregation
    for folder in folders:
        if folder.get("folder_id") == folder_id:
            # Get setlist names
            setlist_names = background_scanner.get_discovered_setlist_names(folder_id) if background_scanner else None
            if not setlist_names:
                setlists = extract_subfolders_from_files(folder)
                setlist_names = list(setlists) if setlists else []
            is_custom = folder.get("is_custom", False)
            if is_custom and not setlist_names:
                setlist_names = [folder.get("name", "")]

            has_files = folder.get("files") is not None
            has_cache = persistent_cache.has_setlist_stats(folder_id) if persistent_cache else False
            state = _get_display_state(folder_id, has_files, has_cache, background_scanner)
            scan_progress = background_scanner.get_scan_progress(folder_id) if background_scanner and state == "scanning" else None

            if has_cache and setlist_names:
                # Re-aggregate from setlist stats (instant!)
                agg = aggregate_folder_stats(folder_id, setlist_names, user_settings, persistent_cache)
                display_string = format_home_item(
                    enabled_setlists=agg.enabled_setlists,
                    total_setlists=agg.total_setlists,
                    total_size=agg.total_size,
                    synced_size=agg.synced_size,
                    purgeable_files=agg.purgeable_files,
                    purgeable_charts=agg.purgeable_charts,
                    purgeable_size=agg.purgeable_size,
                    missing_charts=agg.total_charts - agg.synced_charts,
                    disabled=not drive_enabled,
                    delta_mode=delta_mode,
                    state=state,
                    scan_progress=scan_progress,
                )
                # Update in-memory cache as well
                folder_stats_cache.set(folder_id, FolderStats(
                    folder_id=folder_id,
                    sync_status=SyncStatus(
                        total_charts=agg.total_charts,
                        synced_charts=agg.synced_charts,
                        total_size=agg.total_size,
                        synced_size=agg.synced_size,
                    ),
                    purge_count=agg.purgeable_files,
                    purge_charts=agg.purgeable_charts,
                    purge_size=agg.purgeable_size,
                    enabled_setlists=agg.enabled_setlists,
                    total_setlists=agg.total_setlists,
                    display_string=display_string,
                ))
            else:
                # No cache - show minimal info
                display_string = format_home_item(
                    enabled_setlists=0,
                    total_setlists=len(setlist_names) if setlist_names else 0,
                    total_size=0,
                    synced_size=0,
                    disabled=not drive_enabled,
                    delta_mode=delta_mode,
                    state=state,
                    scan_progress=scan_progress,
                )
            menu_cache.folder_stats[folder_id] = display_string
            break

    # Update group enabled counts (fast - just counting)
    if drives_config:
        for group_name in drives_config.get_groups():
            group_drives = drives_config.get_drives_in_group(group_name)
            enabled_count = sum(
                1 for d in group_drives
                if user_settings.is_drive_enabled(d.folder_id)
            )
            menu_cache.group_enabled_counts[group_name] = enabled_count

    # Only update global totals if ALL folders are scanned
    if not scan_complete:
        return

    # Reaggregate global stats from all cached folder stats
    global_status = SyncStatus()
    global_purge_count = 0
    global_purge_charts = 0
    global_purge_size = 0
    global_enabled_setlists = 0
    global_total_setlists = 0

    for folder in folders:
        fid = folder.get("folder_id", "")
        folder_cached = folder_stats_cache.get(fid)
        if not folder_cached:
            continue

        is_enabled = user_settings.is_drive_enabled(fid)
        if is_enabled:
            global_status.total_charts += folder_cached.sync_status.total_charts
            global_status.synced_charts += folder_cached.sync_status.synced_charts
            global_status.total_size += folder_cached.sync_status.total_size
            global_status.synced_size += folder_cached.sync_status.synced_size
            global_total_setlists += folder_cached.total_setlists
            global_enabled_setlists += folder_cached.enabled_setlists
        global_purge_count += folder_cached.purge_count
        global_purge_charts += folder_cached.purge_charts
        global_purge_size += folder_cached.purge_size

    menu_cache.subtitle = format_status_line(
        synced_charts=global_status.synced_charts,
        total_charts=global_status.total_charts,
        enabled_setlists=global_enabled_setlists,
        total_setlists=global_total_setlists,
        total_size=global_status.total_size,
        synced_size=global_status.synced_size,
        missing_charts=global_status.missing_charts,
        purgeable_files=global_purge_count,
        purgeable_charts=global_purge_charts,
        purgeable_size=global_purge_size,
        delta_mode=delta_mode,
    )

    menu_cache.sync_action_desc = format_delta(
        add_size=global_status.missing_size,
        add_files=global_status.missing_charts,
        add_charts=global_status.missing_charts,
        remove_size=global_purge_size,
        remove_files=global_purge_count,
        remove_charts=global_purge_charts,
        mode=delta_mode,
        empty_text="Everything in sync",
    )


def _get_display_state(
    folder_id: str,
    has_files: bool,
    has_cache: bool,
    scanner: BackgroundScanner,
) -> str:
    """
    Determine display state for a folder.

    Returns: "current" | "cached" | "scanning" | "none"
    """
    if scanner and scanner.is_scanned(folder_id):
        # Scanned this session - compute real values
        return "current"

    if scanner and scanner.is_scanning(folder_id):
        # Currently scanning - show cached values (if any) with SCANNING indicator
        return "scanning"

    # Not scanned yet this session
    if has_files:
        # Files loaded from manifest - current data
        return "current"

    if has_cache:
        return "cached"  # Show italicized

    return "none"  # Show "not scanned"


def _compute_folder_stats(
    folder: dict,
    download_path: Path,
    user_settings: UserSettings,
    persistent_cache: PersistentStatsCache = None,
    scanner: BackgroundScanner = None,
) -> FolderStats | None:
    """Compute stats for a single folder using setlist-centric aggregation."""
    import re
    folder_id = folder.get("folder_id", "")
    has_files = folder.get("files") is not None
    is_custom = folder.get("is_custom", False)

    # Get setlist names from scanner (preferred) or extract from file paths
    setlist_names = scanner.get_discovered_setlist_names(folder_id) if scanner else None
    if not setlist_names:
        setlists = extract_subfolders_from_files(folder)
        setlist_names = list(setlists) if setlists else []

    # For custom folders, the folder itself is the setlist
    if is_custom and not setlist_names:
        setlist_names = [folder.get("name", "")]

    # Check if we have cached setlist stats
    has_setlist_cache = persistent_cache.has_setlist_stats(folder_id) if persistent_cache else False

    # Determine display state
    state = _get_display_state(folder_id, has_files, has_setlist_cache, scanner)

    if state == "none":
        return None

    # If files are loaded, ensure all setlist stats are cached (compute if missing)
    if has_files and persistent_cache and download_path:
        for setlist_name in setlist_names:
            if not persistent_cache.get_setlist(folder_id, setlist_name):
                stats = compute_setlist_stats(folder, setlist_name, download_path, user_settings)
                persistent_cache.set_setlist(folder_id, setlist_name, stats)

    # Use aggregation for stats (fast - no disk I/O!)
    if persistent_cache and setlist_names:
        agg = aggregate_folder_stats(folder_id, setlist_names, user_settings, persistent_cache)
        status = SyncStatus(
            total_charts=agg.total_charts,
            synced_charts=agg.synced_charts,
            total_size=agg.total_size,
            synced_size=agg.synced_size,
        )
        purge_files = agg.purgeable_files
        purge_size = agg.purgeable_size
        purge_charts = agg.purgeable_charts
        enabled_setlists = agg.enabled_setlists
        total_setlists = agg.total_setlists
    else:
        # No cache available - show scanning state
        scan_progress = scanner.get_scan_progress(folder_id) if scanner else None
        display_string = format_home_item(
            enabled_setlists=0,
            total_setlists=len(setlist_names) if setlist_names else 0,
            total_size=0,
            synced_size=0,
            state="scanning" if scanner and scanner.is_scanning(folder_id) else "none",
            scan_progress=scan_progress,
        )
        return FolderStats(
            folder_id=folder_id,
            sync_status=SyncStatus(),
            purge_count=0,
            purge_charts=0,
            purge_size=0,
            enabled_setlists=0,
            total_setlists=len(setlist_names) if setlist_names else 0,
            display_string=display_string,
        )

    # Check if drive is enabled
    drive_enabled = user_settings.is_drive_enabled(folder_id) if user_settings else True
    delta_mode = user_settings.delta_mode if user_settings else "size"

    # Build display string with state styling
    scan_progress = scanner.get_scan_progress(folder_id) if scanner and state == "scanning" else None
    display_string = format_home_item(
        enabled_setlists=enabled_setlists,
        total_setlists=total_setlists,
        total_size=status.total_size,
        synced_size=status.synced_size,
        purgeable_files=purge_files,
        purgeable_charts=purge_charts,
        purgeable_size=purge_size,
        missing_charts=status.missing_charts,
        disabled=not drive_enabled,
        delta_mode=delta_mode,
        is_estimate=status.is_estimate,
        state=state,
        scan_progress=scan_progress,
    )

    display_clean = re.sub(r'\x1b\[[0-9;]*m', '', display_string)
    debug_log(f"HOME_STATS | {folder_id[:8]} | +{status.missing_size} -{purge_size} | charts: +{status.missing_charts} -{purge_charts} | display: {display_clean}")

    return FolderStats(
        folder_id=folder_id,
        sync_status=status,
        purge_count=purge_files,
        purge_charts=purge_charts,
        purge_size=purge_size,
        enabled_setlists=enabled_setlists,
        total_setlists=total_setlists,
        display_string=display_string,
    )


def compute_main_menu_cache(
    folders: list,
    user_settings: UserSettings,
    download_path: Path,
    drives_config: DrivesConfig,
    folder_stats_cache: FolderStatsCache = None,
    background_scanner: BackgroundScanner = None,
) -> MainMenuCache:
    """Compute all expensive stats for the main menu.

    Uses folder_stats_cache (in-memory) and persistent_stats_cache (disk) to
    avoid recalculating unchanged folders. Persistent cache survives restarts.

    If background_scanner is provided, folders being scanned will show
    "scanning..." indicator (italics with cached values, or just "scanning..."
    if no cache exists).
    """
    cache = MainMenuCache()

    if not download_path or not folders:
        return cache

    # Get persistent cache for cross-session stats
    persistent_cache = get_persistent_stats_cache()

    global_status = SyncStatus()
    global_purge_count = 0
    global_purge_charts = 0
    global_purge_size = 0
    global_enabled_setlists = 0
    global_total_setlists = 0

    for folder in folders:
        folder_id = folder.get("folder_id", "")

        # Check if this folder is currently being scanned or was scanned this session
        is_scanning = background_scanner.is_scanning(folder_id) if background_scanner else False
        is_scanned = background_scanner.is_scanned(folder_id) if background_scanner else False

        # Try to use in-memory cached stats for this folder
        # But don't use cache if folder just finished scanning (need to recompute)
        use_memory_cache = folder_stats_cache and not is_scanned
        cached = folder_stats_cache.get(folder_id) if use_memory_cache else None

        if cached and not is_scanning:
            # Only use memory cache if not scanning (scanning state changes display)
            stats = cached
            debug_log(f"CACHE | {folder.get('name', '?')[:20]} | HIT")
        else:
            stats = _compute_folder_stats(
                folder, download_path, user_settings, persistent_cache,
                scanner=background_scanner,
            )
            if stats is None:
                # No cache, no files - show "not scanned" in dim color
                cache.folder_stats[folder_id] = f"{Colors.STALE}not scanned{Colors.RESET}"
                debug_log(f"CACHE | {folder.get('name', '?')[:20]} | NOT_SCANNED")
                continue
            # Cache the stats (but clear scanning display when scanner completes)
            if folder_stats_cache and not is_scanning:
                folder_stats_cache.set(folder_id, stats)
            debug_log(f"CACHE | {folder.get('name', '?')[:20]} | {'SCANNING' if is_scanning else 'MISS'}")

        status = stats.sync_status
        folder_purge_count = stats.purge_count
        folder_purge_charts = stats.purge_charts
        folder_purge_size = stats.purge_size
        enabled_setlists = stats.enabled_setlists
        total_setlists = stats.total_setlists

        # Check if drive is enabled (for display string and aggregation)
        drive_enabled = user_settings.is_drive_enabled(folder_id) if user_settings else True
        delta_mode = user_settings.delta_mode if user_settings else "size"

        # Determine display state
        has_files = folder.get("files") is not None
        has_cache = persistent_cache.has_setlist_stats(folder_id) if persistent_cache else False
        state = _get_display_state(folder_id, has_files, has_cache, background_scanner)

        # Always regenerate display string with current enabled state
        scan_progress = background_scanner.get_scan_progress(folder_id) if background_scanner and state == "scanning" else None
        display_string = format_home_item(
            enabled_setlists=enabled_setlists,
            total_setlists=total_setlists,
            total_size=status.total_size,
            synced_size=status.synced_size,
            purgeable_files=folder_purge_count,
            purgeable_charts=folder_purge_charts,
            purgeable_size=folder_purge_size,
            missing_charts=status.missing_charts,
            disabled=not drive_enabled,
            delta_mode=delta_mode,
            is_estimate=status.is_estimate,
            state=state,
            scan_progress=scan_progress,
        )

        # Only aggregate enabled drives into global stats for add/sync
        if drive_enabled:
            global_status.total_charts += status.total_charts
            global_status.synced_charts += status.synced_charts
            global_status.total_size += status.total_size
            global_status.synced_size += status.synced_size
            if status.is_actual_charts:
                global_status.is_actual_charts = True
            # Count setlists only for enabled drives
            global_total_setlists += total_setlists
            global_enabled_setlists += enabled_setlists
        # Always aggregate purgeable (disabled drives may have content to remove)
        global_purge_count += folder_purge_count
        global_purge_charts += folder_purge_charts
        global_purge_size += folder_purge_size

        cache.folder_stats[folder_id] = display_string

    delta_mode = user_settings.delta_mode if user_settings else "size"

    # Check if scanning is complete - only show deltas when all drives are scanned
    # (partial data gives misleading totals like "+149GB" when only 1 drive scanned)
    scan_complete = not background_scanner or background_scanner.is_done()

    # Build status line: 100% | 562/562 charts, 10/15 setlists (4.0 GB) [+50 charts / -80 charts]
    # Hide delta while scanning - the numbers are incomplete/misleading
    cache.subtitle = format_status_line(
        synced_charts=global_status.synced_charts,
        total_charts=global_status.total_charts,
        enabled_setlists=global_enabled_setlists,
        total_setlists=global_total_setlists,
        total_size=global_status.total_size,
        synced_size=global_status.synced_size if scan_complete else 0,
        missing_charts=global_status.missing_charts if scan_complete else 0,
        purgeable_files=global_purge_count if scan_complete else 0,
        purgeable_charts=global_purge_charts if scan_complete else 0,
        purgeable_size=global_purge_size if scan_complete else 0,
        delta_mode=delta_mode,
    )

    # Build sync action description: [+2.6 MB / -317.3 MB] or [+50 files / -80 files]
    # Hide delta while scanning - show neutral text instead
    if scan_complete:
        cache.sync_action_desc = format_delta(
            add_size=global_status.missing_size,
            add_files=global_status.missing_charts,
            add_charts=global_status.missing_charts,
            remove_size=global_purge_size,
            remove_files=global_purge_count,
            remove_charts=global_purge_charts,
            mode=delta_mode,
            empty_text="Everything in sync",
        )
    else:
        cache.sync_action_desc = "Scanning..."

    if drives_config:
        for group_name in drives_config.get_groups():
            group_drives = drives_config.get_drives_in_group(group_name)
            enabled_count = sum(
                1 for d in group_drives
                if (user_settings.is_drive_enabled(d.folder_id) if user_settings else True)
            )
            cache.group_enabled_counts[group_name] = enabled_count

    # Log full home page state
    import re
    debug_log("HOME_PAGE | === Full State ===")
    for folder in folders:
        fid = folder.get("folder_id", "")
        fname = folder.get("name", "?")
        enabled = user_settings.is_drive_enabled(fid) if user_settings else True
        display = cache.folder_stats.get(fid, "")
        display_clean = re.sub(r'\x1b\[[0-9;]*m', '', str(display)) if display else ""
        debug_log(f"HOME_PAGE | [{'+' if enabled else '-'}] {fname}: {display_clean}")
    subtitle_clean = re.sub(r'\x1b\[[0-9;]*m', '', cache.subtitle)
    sync_desc_clean = re.sub(r'\x1b\[[0-9;]*m', '', cache.sync_action_desc)
    debug_log(f"HOME_PAGE | subtitle: {subtitle_clean}")
    debug_log(f"HOME_PAGE | sync_btn: {sync_desc_clean}")
    debug_log("HOME_PAGE | === End State ===")

    # Save persistent cache to disk (only writes if dirty)
    persistent_cache.save()

    return cache


class HomeScreen:
    """Main menu screen showing available chart packs."""

    def __init__(
        self,
        folders: list,
        user_settings: UserSettings = None,
        download_path: Path = None,
        drives_config: DrivesConfig = None,
        auth: "AuthManager" = None,
    ):
        self.folders = folders
        self.user_settings = user_settings
        self.download_path = download_path
        self.drives_config = drives_config
        self.auth = auth
        self._cache = None
        self._selected_index = 0

    def run(self) -> tuple[str, str | int | None, int]:
        """Run the home screen. Returns (action, value, menu_position)."""
        return show_main_menu(
            self.folders,
            self.user_settings,
            self._selected_index,
            self.download_path,
            self.drives_config,
            self._cache,
            self.auth,
        )


def show_main_menu(
    folders: list,
    user_settings: UserSettings = None,
    selected_index: int = 0,
    download_path: Path = None,
    drives_config: DrivesConfig = None,
    cache: MainMenuCache = None,
    auth=None,
    background_scanner: BackgroundScanner = None,
    folder_stats_cache: FolderStatsCache = None,
) -> tuple[str, str | int | None, int]:
    """
    Show main menu and get user selection.

    Returns tuple of (action, value, menu_position).

    If background_scanner is provided, the menu will periodically refresh
    as folders complete scanning.
    """
    if cache is None:
        cache = compute_main_menu_cache(
            folders, user_settings, download_path, drives_config,
            background_scanner=background_scanner,
        )

    delta_mode = user_settings.delta_mode if user_settings else "size"
    mode_label = {"size": "Size  ", "files": "Files ", "charts": "Charts"}.get(delta_mode, "Size  ")
    legend = f"{Colors.MUTED}[Tab]{Colors.RESET} {mode_label}   {Colors.RESET}+{Colors.MUTED} add   {Colors.RED}-{Colors.MUTED} remove"
    menu = Menu(title="Available chart packs:", subtitle=cache.subtitle, space_hint="Toggle", footer=legend, esc_label="Quit")

    # Set up update callback for background scanning
    def on_menu_update(menu_instance: Menu) -> bool:
        """Called periodically to check for background scan updates."""
        from src.core.formatting import format_duration

        if not background_scanner:
            return False

        # Build new status line
        stats = background_scanner.get_stats()
        if stats.current_folder:
            # Currently scanning - show current folder stats + running totals
            folder_elapsed = format_duration(stats.current_folder_elapsed)
            total_elapsed = format_duration(stats.elapsed)
            new_status = (
                f"Scanning: {stats.current_folder} "
                f"({stats.folders_done + 1}/{stats.folders_total}) | "
                f"{folder_elapsed} | {total_elapsed} total | {stats.api_calls} API calls"
            )
        else:
            # Done scanning - show total time
            if stats.elapsed > 0:
                new_status = f"Ready | {format_duration(stats.elapsed)} | {stats.api_calls} API calls"
            else:
                new_status = f"Ready | {stats.api_calls} API calls this session"

        # Check if any setlists were scanned since last check
        folders_changed = background_scanner.check_updates()

        # Update status line in-place (no full re-render needed for this)
        menu_instance.update_status_line_in_place(new_status)

        if not folders_changed:
            return False  # Status line updated, nothing else changed

        # Setlist(s) completed - recompute stats and re-render
        # Mutate existing cache object so sync.py's menu_cache reference stays current
        if folder_stats_cache:
            folder_stats_cache.invalidate_all()

        new_cache = compute_main_menu_cache(
            folders, user_settings, download_path, drives_config,
            folder_stats_cache, background_scanner,
        )
        cache.subtitle = new_cache.subtitle
        cache.sync_action_desc = new_cache.sync_action_desc
        cache.folder_stats = new_cache.folder_stats
        cache.group_enabled_counts = new_cache.group_enabled_counts

        for folder in folders:
            folder_id = folder.get("folder_id", "")
            new_desc = cache.folder_stats.get(folder_id, "")
            menu_instance.update_item_description(folder_id, new_desc)

        menu_instance.subtitle = cache.subtitle
        menu_instance.update_item_description(("sync", None), cache.sync_action_desc)

        return True  # Re-render with updated values

    if background_scanner and not background_scanner.is_done():
        menu.update_callback = on_menu_update
        # Set initial status line
        stats = background_scanner.get_stats()
        if stats.current_folder:
            menu.status_line = f"Scanning: {stats.current_folder} ({stats.folders_done + 1}/{stats.folders_total}) | {stats.api_calls} API calls"
        else:
            menu.status_line = "Starting scan..."

    folder_lookup = {f.get("folder_id", ""): f for f in folders}

    grouped_folder_ids = set()
    groups = []
    if drives_config:
        groups = drives_config.get_groups()
        for drive in drives_config.drives:
            if drive.group:
                grouped_folder_ids.add(drive.folder_id)

    added_folders = set()
    hotkey_num = 1

    def add_folder_item(folder: dict, indent: bool = False):
        nonlocal hotkey_num
        folder_id = folder.get("folder_id", "")
        drive_enabled = user_settings.is_drive_enabled(folder_id) if user_settings else True
        stats = cache.folder_stats.get(folder_id)

        hotkey = None
        if not indent and hotkey_num <= 9:
            hotkey = str(hotkey_num)
            hotkey_num += 1

        label = f"  {folder['name']}" if indent else folder['name']
        menu.add_item(MenuItem(
            label,
            hotkey=hotkey,
            value=folder_id,
            description=stats,
            disabled=not drive_enabled
        ))
        added_folders.add(folder_id)

    if drives_config:
        for drive in drives_config.get_ungrouped_drives():
            folder = folder_lookup.get(drive.folder_id)
            if folder:
                add_folder_item(folder)

    for group_name in groups:
        expanded = user_settings.is_group_expanded(group_name) if user_settings else False

        group_drives = drives_config.get_drives_in_group(group_name) if drives_config else []
        drive_count = len(group_drives)
        enabled_count = cache.group_enabled_counts.get(group_name, 0)

        menu.add_item(MenuGroupHeader(
            label=group_name,
            group_name=group_name,
            expanded=expanded,
            drive_count=drive_count,
            enabled_count=enabled_count
        ))

        for drive in group_drives:
            added_folders.add(drive.folder_id)
            if expanded:
                folder = folder_lookup.get(drive.folder_id)
                if folder:
                    add_folder_item(folder, indent=True)

    for folder in folders:
        folder_id = folder.get("folder_id", "")
        if folder_id not in added_folders:
            add_folder_item(folder)

    menu.add_item(MenuDivider())
    menu.add_item(MenuItem("Sync", hotkey="S", value=("sync", None), description=cache.sync_action_desc))

    menu.add_item(MenuDivider())
    menu.add_item(MenuItem("Add Custom Folder", hotkey="A", value=("add_custom", None), description="Add your own Google Drive folder"))

    if auth and auth.is_signed_in:
        email = auth.user_email
        label = f"Sign out ({email})" if email else "Sign out of Google"
        menu.add_item(MenuItem(label, hotkey="G", value=("signout", None), description="Remove saved Google credentials"))
    else:
        menu.add_item(MenuItem("Sign in to Google", hotkey="G", value=("signin", None), description="Faster downloads with your own quota"))

    menu.add_item(MenuDivider())
    menu.add_item(MenuItem("Quit", value=("quit", None)))

    result = menu.run(initial_index=selected_index)
    if result is None:
        return ("quit", None, selected_index)

    # Handle Tab to cycle delta mode
    if result.action == "tab":
        return ("cycle_delta_mode", None, menu._selected)

    restore_pos = menu._selected_before_hotkey if menu._selected_before_hotkey != menu._selected else menu._selected

    if isinstance(result.value, tuple) and len(result.value) == 2 and result.value[0] == "group":
        return ("toggle_group", result.value[1], menu._selected)

    if isinstance(result.value, str) and not result.value.startswith(("download", "purge", "quit")):
        if result.action == "space":
            return ("toggle", result.value, menu._selected)
        else:
            return ("configure", result.value, menu._selected)

    action, value = result.value
    return (action, value, restore_pos)
