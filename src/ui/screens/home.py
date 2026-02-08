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
from ..components import format_status_line, format_home_item, format_delta, format_column_header
from ..widgets import Menu, MenuItem, MenuDivider, MenuGroupHeader

if TYPE_CHECKING:
    from src.drive.auth import AuthManager
    from src.sync import BackgroundScanner


@dataclass
class MainMenuCache:
    """Cache for expensive main menu calculations."""
    subtitle: str = ""
    sync_action_desc: str = ""
    sync_delta: str = ""  # delta string for sync label (e.g. "[-9.2 GB]")
    folder_stats: dict = field(default_factory=dict)  # folder_id -> columns string
    folder_deltas: dict = field(default_factory=dict)  # folder_id -> delta string
    folder_states: dict = field(default_factory=dict)  # folder_id -> state string
    folder_checkmarks: dict = field(default_factory=dict)  # folder_id -> bool (show green ✓)
    folder_scan_progress: dict = field(default_factory=dict)  # folder_id -> (scanned, total) or None
    group_enabled_counts: dict = field(default_factory=dict)
    sync_checkmark: bool = False  # True when all enabled setlists verified synced


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
            setlist_names = _get_setlist_names(folder, background_scanner)

            has_files = folder.get("files") is not None
            has_cache = persistent_cache.has_setlist_stats(folder_id) if persistent_cache else False
            state = _get_display_state(folder_id, has_files, has_cache, background_scanner)
            is_still_scanning = background_scanner and background_scanner.is_scanning(folder_id)
            scan_progress = background_scanner.get_scan_progress(folder_id) if is_still_scanning else None

            if has_cache and setlist_names:
                # Re-aggregate from setlist stats (instant!)
                agg = aggregate_folder_stats(folder_id, setlist_names, user_settings, persistent_cache)
                columns, delta, show_checkmark = format_home_item(
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
                    disk_size=agg.disk_size,
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
                    display_string=columns,
                    disk_size=agg.disk_size,
                ))
            else:
                # No cache - show minimal info
                columns, delta, show_checkmark = format_home_item(
                    enabled_setlists=0,
                    total_setlists=len(setlist_names) if setlist_names else 0,
                    total_size=0,
                    synced_size=0,
                    disabled=not drive_enabled,
                    delta_mode=delta_mode,
                    state=state,
                    scan_progress=scan_progress,
                )
            menu_cache.folder_stats[folder_id] = columns
            menu_cache.folder_deltas[folder_id] = delta
            menu_cache.folder_checkmarks[folder_id] = show_checkmark
            menu_cache.folder_states[folder_id] = state
            menu_cache.folder_scan_progress[folder_id] = scan_progress
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

    # Reaggregate global stats from persistent cache (works during scanning)
    global_status = SyncStatus()
    global_purge_count = 0
    global_purge_charts = 0
    global_purge_size = 0
    global_enabled_setlists = 0
    global_total_setlists = 0
    global_disk_size = 0

    for folder in folders:
        fid = folder.get("folder_id", "")
        setlist_names = _get_setlist_names(folder, background_scanner)

        if not setlist_names or not persistent_cache.has_setlist_stats(fid):
            continue

        agg = aggregate_folder_stats(fid, setlist_names, user_settings, persistent_cache)

        if user_settings.is_drive_enabled(fid):
            global_status.total_charts += agg.total_charts
            global_status.synced_charts += agg.synced_charts
            global_status.total_size += agg.total_size
            global_status.synced_size += agg.synced_size
            global_total_setlists += agg.total_setlists
            global_enabled_setlists += agg.enabled_setlists
            global_disk_size += agg.disk_size
        global_purge_count += agg.purgeable_files
        global_purge_charts += agg.purgeable_charts
        global_purge_size += agg.purgeable_size

    _apply_global_stats(
        menu_cache, global_status,
        global_purge_count, global_purge_charts, global_purge_size,
        global_enabled_setlists, global_total_setlists,
        delta_mode, scan_complete, background_scanner,
        global_disk_size=global_disk_size,
    )


def _get_setlist_names(
    folder: dict,
    scanner: "BackgroundScanner" = None,
) -> list[str]:
    """Resolve setlist names for a folder from scanner, files, or folder name."""
    folder_id = folder.get("folder_id", "")
    setlist_names = scanner.get_discovered_setlist_names(folder_id) if scanner else None
    if not setlist_names:
        setlists = extract_subfolders_from_files(folder)
        setlist_names = list(setlists) if setlists else []
    if not setlist_names and folder.get("is_custom", False):
        setlist_names = [folder.get("name", "")]
    return setlist_names


def _apply_global_stats(
    cache: MainMenuCache,
    global_status: SyncStatus,
    global_purge_count: int,
    global_purge_charts: int,
    global_purge_size: int,
    global_enabled_setlists: int,
    global_total_setlists: int,
    delta_mode: str,
    scan_complete: bool,
    scanner: "BackgroundScanner" = None,
    global_disk_size: int = 0,
) -> None:
    """Format accumulated global stats and write them to the menu cache."""
    cache.subtitle = format_status_line(
        synced_charts=global_status.synced_charts,
        total_charts=global_status.total_charts,
        enabled_setlists=global_enabled_setlists,
        total_setlists=global_total_setlists,
        total_size=global_status.total_size,
        disk_size=global_disk_size,
    )
    cache.sync_delta = format_delta(
        add_size=global_status.missing_size,
        add_files=global_status.missing_charts,
        add_charts=global_status.missing_charts,
        remove_size=global_purge_size,
        remove_files=global_purge_count,
        remove_charts=global_purge_charts,
        mode=delta_mode,
        is_estimate=not scan_complete,
    )
    enabled_complete = scan_complete or (scanner and scanner.is_all_enabled_scanned())
    cache.sync_checkmark = enabled_complete and global_status.missing_size <= 0
    cache.sync_action_desc = "Everything in sync" if cache.sync_checkmark else ""


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
        # Enabled setlists done? Show normal colors (scanning only affects disabled now)
        if scanner.is_ready_for_sync(folder_id):
            return "current"
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
    folder_id = folder.get("folder_id", "")
    has_files = folder.get("files") is not None

    setlist_names = _get_setlist_names(folder, scanner)

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
        agg_disk_size = agg.disk_size
    else:
        # No cache available - show scanning state
        scan_progress = scanner.get_scan_progress(folder_id) if scanner else None
        columns, _delta, _checkmark = format_home_item(
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
            display_string=columns,
        )

    # Check if drive is enabled
    drive_enabled = user_settings.is_drive_enabled(folder_id) if user_settings else True
    delta_mode = user_settings.delta_mode if user_settings else "size"

    # Build display string with state styling
    scan_progress = scanner.get_scan_progress(folder_id) if scanner and state == "scanning" else None
    columns, _delta, _checkmark = format_home_item(
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
        disk_size=agg_disk_size,
    )

    # Only log when there's actual work (not for fully synced folders)
    if status.missing_size > 0 or purge_size > 0:
        debug_log(f"HOME_STATS | {folder_id[:8]} | +{status.missing_size} -{purge_size} | charts: +{status.missing_charts} -{purge_charts}")

    return FolderStats(
        folder_id=folder_id,
        sync_status=status,
        purge_count=purge_files,
        purge_charts=purge_charts,
        purge_size=purge_size,
        enabled_setlists=enabled_setlists,
        total_setlists=total_setlists,
        display_string=columns,
        disk_size=agg_disk_size,
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
    global_disk_size = 0
    cache_hits = 0
    cache_misses = 0
    cache_scanning = 0

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
            stats = cached
            cache_hits += 1
        else:
            stats = _compute_folder_stats(
                folder, download_path, user_settings, persistent_cache,
                scanner=background_scanner,
            )
            if stats is None:
                # No cache, no files - show "not scanned" in dim color
                cache.folder_stats[folder_id] = f"{Colors.STALE}not scanned{Colors.RESET}"
                cache.folder_deltas[folder_id] = ""
                cache.folder_states[folder_id] = "none"
                continue
            # Cache the stats (but clear scanning display when scanner completes)
            if folder_stats_cache and not is_scanning:
                folder_stats_cache.set(folder_id, stats)
            if is_scanning:
                cache_scanning += 1
            else:
                cache_misses += 1

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
        is_still_scanning = background_scanner and background_scanner.is_scanning(folder_id)
        scan_progress = background_scanner.get_scan_progress(folder_id) if is_still_scanning else None
        columns, delta, show_checkmark = format_home_item(
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
            disk_size=stats.disk_size,
        )

        # Only aggregate enabled drives into global stats for add/sync
        if drive_enabled:
            global_status.total_charts += status.total_charts
            global_status.synced_charts += status.synced_charts
            global_status.total_size += status.total_size
            global_status.synced_size += status.synced_size
            global_disk_size += stats.disk_size
            if status.is_actual_charts:
                global_status.is_actual_charts = True
            # Count setlists only for enabled drives
            global_total_setlists += total_setlists
            global_enabled_setlists += enabled_setlists
        # Always aggregate purgeable (disabled drives may have content to remove)
        global_purge_count += folder_purge_count
        global_purge_charts += folder_purge_charts
        global_purge_size += folder_purge_size

        cache.folder_stats[folder_id] = columns
        cache.folder_deltas[folder_id] = delta
        cache.folder_checkmarks[folder_id] = show_checkmark
        cache.folder_states[folder_id] = state
        cache.folder_scan_progress[folder_id] = scan_progress

    delta_mode = user_settings.delta_mode if user_settings else "size"
    scan_complete = not background_scanner or background_scanner.is_done()

    _apply_global_stats(
        cache, global_status,
        global_purge_count, global_purge_charts, global_purge_size,
        global_enabled_setlists, global_total_setlists,
        delta_mode, scan_complete, background_scanner,
        global_disk_size=global_disk_size,
    )

    if drives_config:
        for group_name in drives_config.get_groups():
            group_drives = drives_config.get_drives_in_group(group_name)
            enabled_count = sum(
                1 for d in group_drives
                if (user_settings.is_drive_enabled(d.folder_id) if user_settings else True)
            )
            cache.group_enabled_counts[group_name] = enabled_count

    enabled_count = sum(1 for f in folders if user_settings and user_settings.is_drive_enabled(f.get("folder_id", "")))
    debug_log(f"HOME_PAGE | {enabled_count}/{len(folders)} drives | cache: {cache_hits} hit, {cache_misses} miss, {cache_scanning} scanning | checkmark={cache.sync_checkmark}")

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


def _build_sync_label(cache: MainMenuCache) -> str:
    if cache.sync_checkmark:
        return f"{Colors.GREEN}✓\x1b[39m Sync"
    if cache.sync_delta:
        return f"  Sync {cache.sync_delta}"
    return "  Sync"


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

    legend = f"{Colors.RESET}+{Colors.MUTED} add   {Colors.RED}-{Colors.MUTED} remove"
    menu = Menu(title="Chart Packs", subtitle=cache.subtitle, space_hint="Toggle", footer=legend, esc_label="Quit",
                column_header=format_column_header("home"))

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
            if stats.api_calls > 0:
                new_status = (
                    f"Scanning: {stats.current_folder} "
                    f"({stats.folders_done + 1}/{stats.folders_total}) | "
                    f"{folder_elapsed} | {total_elapsed} total | {stats.api_calls} API calls"
                )
            else:
                new_status = (
                    f"Loading cache: {stats.current_folder} "
                    f"({stats.folders_done + 1}/{stats.folders_total}) | "
                    f"{total_elapsed}"
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
        cache.sync_delta = new_cache.sync_delta
        cache.sync_checkmark = new_cache.sync_checkmark
        cache.folder_stats = new_cache.folder_stats
        cache.folder_deltas = new_cache.folder_deltas
        cache.folder_checkmarks = new_cache.folder_checkmarks
        cache.folder_states = new_cache.folder_states
        cache.folder_scan_progress = new_cache.folder_scan_progress
        cache.group_enabled_counts = new_cache.group_enabled_counts

        for folder in folders:
            folder_id = folder.get("folder_id", "")
            new_columns = cache.folder_stats.get(folder_id, "")
            menu_instance.update_item_description(folder_id, new_columns)
            # Check if this folder is in a group (indented)
            is_indent = folder_id in grouped_folder_ids
            new_label = _build_folder_label(folder.get("name", ""), folder_id, is_indent)
            menu_instance.update_item_label(folder_id, new_label)

        menu_instance.subtitle = cache.subtitle
        menu_instance.update_item_description(("sync", None), cache.sync_action_desc)
        sync_label = _build_sync_label(cache)
        menu_instance.update_item_label(("sync", None), sync_label)

        # Update rescan item when scanning finishes
        if background_scanner.is_done():
            menu_instance.update_item_description(("rescan", None), "Last scan: just now")
            menu_instance.enable_item(("rescan", None))

        return True  # Re-render with updated values

    if background_scanner and not background_scanner.is_done():
        menu.update_callback = on_menu_update
        # Set initial status line
        stats = background_scanner.get_stats()
        if stats.current_folder:
            if stats.api_calls > 0:
                menu.status_line = f"Scanning: {stats.current_folder} ({stats.folders_done + 1}/{stats.folders_total}) | {stats.api_calls} API calls"
            else:
                menu.status_line = f"Loading cache: {stats.current_folder} ({stats.folders_done + 1}/{stats.folders_total})"
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

    def _build_folder_label(name: str, folder_id: str, indent: bool) -> str:
        """Build label with checkmark, italic for scanning, scan progress, and delta."""
        state = cache.folder_states.get(folder_id, "current")
        delta = cache.folder_deltas.get(folder_id, "")
        show_checkmark = cache.folder_checkmarks.get(folder_id, False)
        scan_progress = cache.folder_scan_progress.get(folder_id)
        is_scanning = (state == "scanning")
        disabled = not (user_settings.is_drive_enabled(folder_id) if user_settings else True)

        prefix = "   " if indent else " "

        check = f"{Colors.GREEN}✓\x1b[39m" if show_checkmark else " "

        if is_scanning:
            if disabled:
                label = f"{prefix}{check} {Colors.ITALIC}{Colors.DIM}{name}{Colors.RESET}"
            else:
                label = f"{prefix}{check} {Colors.ITALIC}{name}{Colors.RESET}"
        else:
            label = f"{prefix}{check} {name}"

        # Show scan progress (X/Y) while drive still has unscanned setlists
        if scan_progress:
            scanned, total = scan_progress
            progress_color = Colors.CYAN_DIM if disabled else Colors.CYAN
            label = f"{label} {progress_color}{scanned}/{total}{Colors.RESET}"

        if delta:
            label = f"{label} {delta}"
        return label

    def add_folder_item(folder: dict, indent: bool = False):
        nonlocal hotkey_num
        folder_id = folder.get("folder_id", "")
        drive_enabled = user_settings.is_drive_enabled(folder_id) if user_settings else True
        columns = cache.folder_stats.get(folder_id)

        hotkey = None
        if not indent and hotkey_num <= 9:
            hotkey = str(hotkey_num)
            hotkey_num += 1

        label = _build_folder_label(folder['name'], folder_id, indent)
        menu.add_item(MenuItem(
            label,
            hotkey=hotkey,
            value=folder_id,
            description=columns,
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
    sync_label = _build_sync_label(cache)
    menu.add_item(MenuItem(sync_label, hotkey="S", value=("sync", None), description=cache.sync_action_desc))

    # Rescan item with scan age or scanning state
    is_scanning = background_scanner and not background_scanner.is_done()
    if is_scanning:
        api_calls = background_scanner.get_stats().api_calls
        label = "Scanning..." if api_calls > 0 else "Loading cache..."
        rescan_desc = f"{Colors.CYAN}{label}{Colors.RESET}"
    else:
        from datetime import datetime, timezone
        from src.sync.cache import get_scan_cache
        newest = get_scan_cache().get_newest_time()
        if newest:
            age_s = (datetime.now(timezone.utc) - newest).total_seconds()
            if age_s < 60:
                rescan_desc = "Last scan: just now"
            elif age_s < 3600:
                rescan_desc = f"Last scan: {int(age_s // 60)}m ago"
            else:
                rescan_desc = f"Last scan: {int(age_s // 3600)}h {int((age_s % 3600) // 60)}m ago"
        else:
            rescan_desc = "Force re-scan all drives"
    menu.add_item(MenuItem("  Rescan", hotkey="R", value=("rescan", None), description=rescan_desc, disabled=is_scanning))

    menu.add_item(MenuDivider())
    menu.add_item(MenuItem("  Add Custom Folder", hotkey="A", value=("add_custom", None), description="Add your own Google Drive folder"))

    if auth and auth.is_signed_in:
        email = auth.user_email
        label = f"  Sign out ({email})" if email else "  Sign out of Google"
        menu.add_item(MenuItem(label, hotkey="G", value=("signout", None), description="Remove saved Google credentials"))
    else:
        menu.add_item(MenuItem("  Sign in to Google", hotkey="G", value=("signin", None), description="Faster downloads with your own quota"))

    menu.add_item(MenuDivider())
    menu.add_item(MenuItem("  Quit", hotkey="ESC", value=("quit", None)))

    result = menu.run(initial_index=selected_index)
    if result is None:
        return ("quit", None, selected_index)

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
