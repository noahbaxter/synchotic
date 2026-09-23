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


@dataclass(frozen=True)
class Setup:
    """Everything the checks may look at, gathered once by read_setup."""
    mode: str = "rclone"
    rclone_authed: bool = False
    # rclone answered just now; None when the mode does not use it.
    rclone_working: bool | None = None
    signed_in: bool = False
    # A token the app could actually refresh, not just a file that parses.
    token_works: bool | None = None
    byoc_configured: bool = False

    library_path: str = ""
    library_set: bool = True
    library_available: bool = True
    library_writable: bool = True
    library_adopted: bool = False   # has a sync ever completed into it
    colliding_folders: tuple = ()   # folders here sharing a name with a drive

    drives_enabled: int = 0
    setlists_enabled: int = 0


_GO_LOCATION = copy.FIX_FROM.format(where=copy.SETTINGS_LOCATION)
_GO_MODE = copy.FIX_FROM.format(where=copy.SETTINGS_MODE)

# Every setup case worth stopping for, in the order shown: (kind, severity,
# predicate on a Setup, headline, detail, fix). Space and purge need this run's
# numbers, so preflight() owns those.
CASES = (
    ("library_unset", BLOCK,
     lambda s: not s.library_set,
     copy.LIBRARY_UNSET, "", _GO_LOCATION),

    ("mode_rclone", BLOCK,
     lambda s: s.mode == "rclone" and not s.rclone_authed,
     copy.STATUS_RCLONE, "", _GO_MODE),

    ("mode_rclone_dead", BLOCK,
     lambda s: s.mode == "rclone" and s.rclone_authed and s.rclone_working is False,
     copy.PRE_RCLONE_DEAD, "", _GO_MODE),

    ("mode_byoc_creds", BLOCK,
     lambda s: s.mode == "byoc" and not s.byoc_configured,
     copy.STATUS_BYOC, "", copy.PRE_BYOC_FIX),

    ("mode_byoc_signin", BLOCK,
     lambda s: s.mode == "byoc" and s.byoc_configured and not s.signed_in,
     copy.STATUS_SIGNED_OUT, "", copy.FIX_SIGN_IN),

    ("signin_expired", BLOCK,
     lambda s: s.mode == "byoc" and s.byoc_configured and s.signed_in
               and s.token_works is False,
     copy.STATUS_SIGNIN_EXPIRED, "", copy.FIX_SIGN_IN),

    ("library_missing", BLOCK,
     lambda s: s.library_set and not s.library_available,
     copy.LIBRARY_MISSING, "", copy.FIX_RECONNECT),

    ("library_readonly", BLOCK,
     lambda s: s.library_set and s.library_available and not s.library_writable,
     copy.PRE_READONLY, "", _GO_LOCATION),

    ("nothing_on", BLOCK,
     lambda s: s.drives_enabled == 0,
     copy.NO_DRIVES, "", copy.TOGGLE_DRIVE),

    ("no_setlists", BLOCK,
     lambda s: s.drives_enabled > 0 and s.setlists_enabled == 0,
     copy.NO_SETLISTS, "", copy.TOGGLE_SETLIST),

    ("mode_anonymous", WARN,
     lambda s: s.mode == "anonymous",
     copy.PRE_ANON, copy.ANON_LIMIT, _GO_MODE),

    # The detail is filled in from the folder names, see _describe.
    ("unowned_library", WARN,
     lambda s: bool(s.colliding_folders) and not s.library_adopted,
     copy.PRE_UNOWNED, "", _GO_LOCATION),
)


def _describe(kind: str, setup: Setup) -> str:
    """The detail line for cases whose wording depends on what was found."""
    if kind == "unowned_library":
        found = setup.colliding_folders
        more = copy.PRE_UNOWNED_MORE.format(n=len(found) - 3) if len(found) > 3 else ""
        return copy.PRE_UNOWNED_DETAIL.format(names=", ".join(found[:3]), more=more)
    return ""


def check_setup(setup: Setup) -> list[Concern]:
    """Run every case in CASES against `setup`, blockers first. Reads nothing
    beyond the Setup, so it runs anywhere, tests included."""
    found = [
        Concern(kind=kind, severity=severity, headline=headline,
                detail=_describe(kind, setup) or detail, fix=fix)
        for kind, severity, applies, headline, detail, fix in CASES
        if applies(setup)
    ]
    return sorted(found, key=lambda c: 0 if c.severity == BLOCK else 1)


def read_setup(user_settings, auth, folders, library_path) -> Setup:
    """Look up everything CASES asks about: settings, one listing of the
    library's top level, and one probe of whichever service the mode uses."""
    import os
    from pathlib import Path

    from ..config.settings import DOWNLOAD_MODE_RCLONE
    from ..drive.auth import has_custom_client_config
    from .ownership import is_library_adopted

    mode = (getattr(user_settings, "download_mode", "") if user_settings else "") \
        or DOWNLOAD_MODE_RCLONE

    # Each probe costs a round trip, so only the mode that depends on it asks.
    rclone_authed = False
    rclone_working = None
    if mode == DOWNLOAD_MODE_RCLONE:
        try:
            import src.rclone as rclone
            state = rclone.connection_state()
            rclone_authed = state != rclone.MISSING
            rclone_working = state == rclone.OK
        except Exception:
            rclone_authed = False

    signed_in = bool(auth and getattr(auth, "is_signed_in", False))
    token_works = None
    if signed_in and mode == "byoc":
        # is_signed_in only proves a token file parses; get_token refreshes.
        try:
            token_works = bool(auth.get_token())
        except Exception:
            token_works = False

    from ..core.paths import library_is_available, library_is_set

    library = Path(library_path)
    library_set = library_is_set()
    available = library_set and library_is_available()

    # Permission is asked of the nearest folder that exists: a library not
    # created yet is written by creating it.
    probe = library
    while available and not probe.exists() and probe != probe.parent:
        probe = probe.parent
    writable = available and os.access(probe, os.W_OK)

    enabled_drives = [
        f for f in folders
        if not user_settings or user_settings.is_drive_enabled(f.get("folder_id", ""))
    ]
    setlists_on = 0
    for folder in enabled_drives:
        names = folder.get("setlists") or []
        setlists_on += sum(
            1 for name in names
            if not user_settings
            or user_settings.is_subfolder_enabled(folder.get("folder_id", ""), name)
        )

    # A folder here named after a drive about to sync into it is the one case
    # where purge can reach charts nobody downloaded through us. Both the raw
    # and sanitized drive names count, since Windows gets the sanitized one.
    colliding = ()
    if available and library.is_dir():
        try:
            from ..core.formatting import sanitize_drive_name
            expected = set()
            for folder in enabled_drives:
                raw = folder.get("name", "")
                expected.update({raw, sanitize_drive_name(raw)})
            expected.discard("")
            on_disk = {p.name for p in library.iterdir() if p.is_dir()}
            colliding = tuple(sorted(on_disk & expected))
        except OSError:
            colliding = ()

    return Setup(
        mode=mode,
        rclone_authed=rclone_authed,
        rclone_working=rclone_working,
        signed_in=signed_in,
        token_works=token_works,
        byoc_configured=has_custom_client_config(),
        library_path=str(library),
        library_set=library_set,
        library_available=available,
        library_writable=writable,
        library_adopted=is_library_adopted() if available and library.is_dir() else False,
        colliding_folders=colliding,
        drives_enabled=len(enabled_drives),
        setlists_enabled=setlists_on,
    )


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
                 disk_usage=None, setup=None) -> tuple[list["Concern"], int]:
    """Every concern about syncing into `library_path`, blockers first, and the
    free space. A library that cannot be measured still reports the setup
    problems (an unplugged drive is exactly that case)."""
    import shutil

    found = check_setup(setup) if setup else []

    try:
        free = (disk_usage or shutil.disk_usage)(library_path).free
    except OSError:
        return found, 0

    needed, unmeasured, purge_charts, purge_bytes = gather(
        folders, user_settings, cache)
    found += preflight(needed_bytes=needed, free_bytes=free,
                       unmeasured_drives=unmeasured, purge_charts=purge_charts,
                       purge_bytes=purge_bytes)
    return sorted(found, key=lambda c: 0 if c.severity == BLOCK else 1), free


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
                floor=copy.PRE_AT_LEAST if unmeasured_drives else "",
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
