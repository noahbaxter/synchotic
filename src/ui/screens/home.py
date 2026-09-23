"""Chart-pack stats for the home screen.

Everything expensive the home screen needs: per-drive sync status, deltas,
purgeable counts and the totals line, computed once and refreshed in place as a
background scan lands.

This used to own the one-column main menu as well. That screen is gone -- the
home screen is two panes now (see home_panes.py) -- and what is left here is the
cache it renders from.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from src import copy
from src.config import UserSettings, DrivesConfig, extract_subfolders_from_files
from src.core.logging import debug_log
from src.sync import (
    SyncStatus, FolderStats, FolderStatsCache, get_persistent_stats_cache,
    PersistentStatsCache, aggregate_folder_stats, compute_setlist_stats,
)
from ..components import format_status_line, format_home_item, format_delta

if TYPE_CHECKING:
    from src.drive.auth import AuthManager
    from src.sync import BackgroundScanner


@dataclass
class MainMenuCache:
    """Cache for expensive main menu calculations."""
    subtitle: str = ""
    sync_delta: str = ""  # delta string for sync label (e.g. "[-9.2 GB]")
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
                    purgeable_size=agg.purgeable_size,
                    disabled=not drive_enabled,
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
                    state=state,
                    scan_progress=scan_progress,
                )
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
        global_purge_size += agg.purgeable_size

    _apply_global_stats(
        menu_cache, global_status, global_purge_size,
        global_enabled_setlists, global_total_setlists,
        scan_complete, background_scanner,
        global_disk_size=global_disk_size,
        empty_hint=_empty_hint(folders, user_settings, scan_complete),
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
    if not setlist_names:
        setlist_names = [folder.get("name", "")]
    return setlist_names


def _empty_hint(folders, user_settings, scan_complete: bool) -> str:
    """What the header says with nothing measured, asked of the settings: the
    numbers are also zero for the whole first scan, when restored drives are
    on but nothing is counted yet."""
    on = any(user_settings.is_drive_enabled(f.get("folder_id", ""))
             for f in folders) if user_settings else False
    if not on:
        return copy.HOME_NO_DRIVES
    if not scan_complete:
        return ""  # the footer already says what the scan is doing
    return copy.HOME_NO_SETLISTS


def _apply_global_stats(
    cache: MainMenuCache,
    global_status: SyncStatus,
    global_purge_size: int,
    global_enabled_setlists: int,
    global_total_setlists: int,
    scan_complete: bool,
    scanner: "BackgroundScanner" = None,
    global_disk_size: int = 0,
    empty_hint: str = "",
) -> None:
    """Format accumulated global stats and write them to the menu cache."""
    cache.subtitle = format_status_line(
        synced_charts=global_status.synced_charts,
        total_charts=global_status.total_charts,
        enabled_setlists=global_enabled_setlists,
        total_setlists=global_total_setlists,
        total_size=global_status.total_size,
        disk_size=global_disk_size,
        empty_hint=empty_hint,
    )
    cache.sync_delta = format_delta(
        add_size=global_status.missing_size,
        remove_size=global_purge_size,
        is_estimate=not scan_complete,
    )
    enabled_complete = scan_complete or (scanner and scanner.is_all_enabled_scanned())
    cache.sync_checkmark = enabled_complete and global_status.missing_size <= 0


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
    # A drive whose listing threw would otherwise report its stand-in as
    # scanned: one setlist, zero charts, everything in sync.
    if scanner and scanner.discovery_failed(folder_id):
        return "none"

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

    # Build display string with state styling
    scan_progress = scanner.get_scan_progress(folder_id) if scanner and state == "scanning" else None
    columns, _delta, _checkmark = format_home_item(
        enabled_setlists=enabled_setlists,
        total_setlists=total_setlists,
        total_size=status.total_size,
        synced_size=status.synced_size,
        purgeable_size=purge_size,
        disabled=not drive_enabled,
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
    global_purge_size = 0
    global_enabled_setlists = 0
    global_total_setlists = 0
    global_disk_size = 0
    cache_hits = 0
    cache_misses = 0
    cache_scanning = 0

    for folder in folders:
        folder_id = folder.get("folder_id", "")

        # Check if this folder is currently being scanned
        is_scanning = background_scanner.is_scanning(folder_id) if background_scanner else False

        # Use in-memory cache when available (already invalidated per-folder after sync/purge)
        use_memory_cache = folder_stats_cache is not None
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
                # No cache and no files yet
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
        folder_purge_size = stats.purge_size
        enabled_setlists = stats.enabled_setlists
        total_setlists = stats.total_setlists

        # Check if drive is enabled (for display string and aggregation)
        drive_enabled = user_settings.is_drive_enabled(folder_id) if user_settings else True

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
            purgeable_size=folder_purge_size,
            disabled=not drive_enabled,
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
        global_purge_size += folder_purge_size

        cache.folder_deltas[folder_id] = delta
        cache.folder_checkmarks[folder_id] = show_checkmark
        cache.folder_states[folder_id] = state
        cache.folder_scan_progress[folder_id] = scan_progress

    scan_complete = not background_scanner or background_scanner.is_done()

    _apply_global_stats(
        cache, global_status, global_purge_size,
        global_enabled_setlists, global_total_setlists,
        scan_complete, background_scanner,
        global_disk_size=global_disk_size,
        empty_hint=_empty_hint(folders, user_settings, scan_complete),
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
