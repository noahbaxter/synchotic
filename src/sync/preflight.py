"""What sync checks before it starts: the few things worth stopping for, and
nothing when there is nothing to say, since a prompt on every run goes unread.

Sizes come from the stats cache, so nothing waits on this run's scan. A drive
never scanned contributes nothing, which makes the total a floor, and the
wording says so.
"""
from dataclasses import dataclass

from .. import copy
from ..core.formatting import count

GB = 1024 ** 3

# An archive occupies its own size and its unpacked contents at the same time,
# so the disk has to hold more than the download.
EXTRACTION_PAD = 1.25

# Landing a sync with nothing left on the disk is its own problem.
HEADROOM = 10 * GB

# A floor this close to the free space will cross it once the rest is measured.
UNMEASURED_MARGIN = 2.0

# Below these, a deletion is the routine result of turning something off.
PURGE_CHARTS = 25
PURGE_BYTES = 1 * GB


BLOCK = "block"
WARN = "warn"


@dataclass(frozen=True)
class Concern:
    """One reason to stop and ask: a headline, a line of explanation, and
    `fix`, what to do about it. `severity` is BLOCK when a sync cannot work
    and WARN when it can but will go badly."""
    kind: str
    headline: str
    detail: str
    fix: str = ""
    severity: str = WARN


def _size(num_bytes: int) -> str:
    from ..core.formatting import format_size
    return format_size(num_bytes)


def gather(folders, user_settings, cache) -> tuple[int, int, int, int]:
    """(bytes to download, unmeasured drives, charts to delete, bytes to
    delete), from the stats cache. A drive with no cached setlist at all has
    never been measured; one measured in part still counts toward the floor."""
    needed = purge_bytes = purge_charts = unmeasured = 0

    for folder in folders:
        folder_id = folder.get("folder_id", "")
        drive_on = user_settings.is_drive_enabled(folder_id) if user_settings else True
        measured = False

        for name in folder.get("setlists") or []:
            stats = cache.get_setlist(folder_id, name)
            if not stats:
                continue
            measured = True
            setlist_on = (user_settings.is_subfolder_enabled(folder_id, name)
                          if user_settings else True)

            if drive_on and setlist_on:
                needed += max(0, stats.total_size - stats.synced_size)
            elif stats.disk_files > 0:
                # Off, but its files are still on disk, so sync removes them.
                purge_bytes += stats.disk_size
                purge_charts += stats.disk_charts

        if drive_on and not measured:
            unmeasured += 1

    return needed, unmeasured, purge_charts, purge_bytes


def concerns_for(folders, user_settings, cache, library_path,
                 disk_usage=None) -> tuple[list["Concern"], int]:
    """Every concern about syncing into `library_path`, and the free space."""
    import shutil

    try:
        free = (disk_usage or shutil.disk_usage)(library_path).free
    except OSError:
        return [], 0

    needed, unmeasured, purge_charts, purge_bytes = gather(
        folders, user_settings, cache)
    return preflight(needed_bytes=needed, free_bytes=free,
                     unmeasured_drives=unmeasured, purge_charts=purge_charts,
                     purge_bytes=purge_bytes), free


def preflight(*, needed_bytes: int, free_bytes: int, unmeasured_drives: int = 0,
              purge_charts: int = 0, purge_bytes: int = 0) -> list[Concern]:
    """Everything worth a confirmation before this sync runs, or an empty list."""
    concerns: list[Concern] = []
    wants = int(needed_bytes * EXTRACTION_PAD)
    kind = headline = None
    if wants > free_bytes:
        kind, headline = "space", copy.PRE_SPACE
    elif free_bytes - wants < HEADROOM:
        kind, headline = "headroom", copy.PRE_LOW_SPACE
    elif unmeasured_drives and wants * UNMEASURED_MARGIN > free_bytes:
        # The measured part fits, but it is only part, and the rest is unknown.
        kind, headline = "space", copy.PRE_LOW_SPACE
    if kind:
        concerns.append(Concern(
            kind=kind,
            headline=headline,
            detail=copy.PRE_SPACE_DETAIL.format(
                floor=" at least" if unmeasured_drives else "",
                needed=_size(needed_bytes), free=_size(free_bytes)),
            fix=copy.PRE_FREE_UP,
        ))

    if purge_charts > PURGE_CHARTS or purge_bytes > PURGE_BYTES:
        concerns.append(Concern(
            kind="purge",
            headline=copy.PRE_PURGE.format(charts=count(purge_charts, "chart")),
            detail=copy.PRE_PURGE_DETAIL.format(size=_size(purge_bytes)),
        ))

    return concerns
