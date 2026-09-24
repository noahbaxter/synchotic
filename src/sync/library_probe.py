"""Guess what a folder is before Synchotic starts managing it.

"Not empty" is true of a previous Synchotic library, of someone's own songs
folder, and of their Downloads, and those deserve different questions. A
Synchotic library puts drive names at the top; a songs folder puts chart
folders near the top and matches no drive name. Nothing here reads Drive.

It runs between picking a folder and being asked about it, on libraries of six
figures of files, sometimes over a network mount. So it is one bounded walk:
os.scandir, a depth limit, an entry cap and a deadline, and whatever it has
seen when one trips is reported as "at least".
"""
import os
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from ..core.constants import CHART_MARKERS
from ..core.formatting import sanitize_drive_name

# A library is drive/setlist/chart, so a chart folder shows up by the third
# level in either layout.
DEPTH = 3

# Generous on purpose: an external drive managed 492 of its 2,885 charts in
# ten seconds, so a tight budget gives a wrong answer, not a smaller one.
MAX_ENTRIES = 20000
TIME_BUDGET = 3.0

# Finder litter, in their thousands on any drive that has been near a Mac.
NOISE_PREFIX = "._"


@dataclass(frozen=True)
class Look:
    """What a folder appears to be."""
    drive_matches: tuple = ()     # top-level names that match a known drive
    chart_folders: int = 0        # folders holding song.ini/notes.chart/notes.mid
    files: int = 0
    folders: int = 0
    capped: bool = False          # gave up early, so the counts are a floor


def probe_library(path, drive_names=(), skip=(), on_progress=None) -> Look:
    """Look at `path` and say what it resembles, in one bounded walk.

    Drive and folder names are both sanitized before comparing, since that is
    what sync does when it creates the folder. `skip` names folders to ignore,
    such as our own state dir. on_progress(chart_folders, files) is called
    after each folder.
    """
    path = Path(path)
    if not path.is_dir():
        return Look()

    wanted = {sanitize_drive_name(n) for n in drive_names if n}
    wanted.discard("")
    skip = set(skip)

    deadline = time.monotonic() + TIME_BUDGET
    matches, chart_folders, files, folders, entries = [], 0, 0, 0, 0
    capped = False

    # Breadth first, so a walk that runs out of time has covered the top of
    # the tree evenly rather than one deep branch of it.
    queue = deque([(path, 0)])
    first = True
    while queue:
        current, depth = queue.popleft()
        try:
            with os.scandir(current) as scan:
                names = []
                for entry in scan:
                    if entry.name in skip or entry.name.startswith(NOISE_PREFIX):
                        continue
                    names.append(entry.name)
                    if _is_dir(entry):
                        folders += 1
                        # A chart's marker files sit one level below the last
                        # folder worth listing.
                        if depth < DEPTH:
                            queue.append((entry.path, depth + 1))
                        if first and sanitize_drive_name(entry.name) in wanted:
                            matches.append(entry.name)
                    else:
                        files += 1
                    entries += 1
                    if entries >= MAX_ENTRIES:
                        capped = True
                        break
                if any(name.lower() in CHART_MARKERS for name in names):
                    chart_folders += 1
                first = False
        except OSError:
            if first:
                return Look()
            continue

        if on_progress:
            on_progress(chart_folders, files)

        if capped or time.monotonic() > deadline:
            capped = True
            break

    return Look(drive_matches=tuple(sorted(matches)), chart_folders=chart_folders,
                files=files, folders=folders, capped=capped)


def previous_selection(path, drives, skip=()) -> dict:
    """What a folder Synchotic synced before says was turned on:
    {folder_id: [setlist names]}, read from its drive and setlist folders.

    Two levels is the whole layout sync writes, so what is on disk is the
    previous choice. `drives` are manifest entries with .name and .folder_id.
    """
    path = Path(path)
    by_name = {sanitize_drive_name(d.name): d.folder_id
               for d in drives if getattr(d, "name", "")}
    skip = set(skip)
    found = {}

    try:
        with os.scandir(path) as top:
            drive_dirs = [e for e in top
                          if e.name not in skip
                          and not e.name.startswith(NOISE_PREFIX)
                          and _is_dir(e)]
    except OSError:
        return {}

    for entry in drive_dirs:
        folder_id = by_name.get(sanitize_drive_name(entry.name))
        if not folder_id:
            continue
        setlists = []
        try:
            with os.scandir(entry.path) as inner:
                setlists = sorted(e.name for e in inner
                                  if not e.name.startswith(NOISE_PREFIX)
                                  and _is_dir(e))
        except OSError:
            pass
        found[folder_id] = setlists
    return found


def turn_on_found(user_settings, path, drives, undecided_only=False) -> dict:
    """Turn on every drive this library holds a folder for, and return
    previous_selection's answer. Never turns anything off: a drive that is off
    with charts on disk is a drive the next sync deletes.

    `undecided_only` leaves alone a drive somebody switched off, which is how
    a drive gets removed on purpose.
    """
    from ..core.paths import LIBRARY_STATE_DIR_NAME

    found = previous_selection(path, drives, skip=(LIBRARY_STATE_DIR_NAME,))
    changed = False
    for folder_id in found:
        if undecided_only and folder_id in user_settings.drive_toggles:
            continue
        if not user_settings.is_drive_enabled(folder_id):
            user_settings.turn_on_from_disk(folder_id)
            changed = True
    if changed:
        user_settings.save()
    return found


def setlist_on_disk(library, drive_name):
    """A check for whether a setlist has a folder under this drive's folder.

    Matches loosely on purpose, and says yes when the folder cannot be read:
    a setlist called absent is turned off, and off is what purge deletes.
    The folder is read on the first call, not before.
    """
    from ..config.settings import normalize_setlist_name

    present = []

    def read():
        drive_dir = Path(library) / drive_name
        if not drive_dir.is_dir():
            drive_dir = Path(library) / sanitize_drive_name(drive_name)
        try:
            with os.scandir(drive_dir) as entries:
                return {normalize_setlist_name(e.name) for e in entries if _is_dir(e)}
        except OSError:
            return None

    def on_disk(name):
        if not present:
            present.append(read())
        names = present[0]
        return (names is None
                or normalize_setlist_name(name) in names
                or normalize_setlist_name(sanitize_drive_name(name)) in names)
    return on_disk


def entries_on_disk(library, drive_name, setlist_name):
    """How many entries this setlist's folder holds, or None when it is not
    on disk. A size hint for scan order only: bigger on disk, bigger on
    Drive, longer to scan."""
    for drive in (drive_name, sanitize_drive_name(drive_name)):
        for name in (setlist_name, sanitize_drive_name(setlist_name)):
            try:
                with os.scandir(Path(library) / drive / name) as entries:
                    return sum(1 for _ in entries)
            except OSError:
                continue
    return None


def _is_dir(entry) -> bool:
    try:
        return entry.is_dir(follow_symlinks=False)
    except OSError:
        return False
