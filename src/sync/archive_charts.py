"""Chart counts for setlists Drive cannot count.

An archive is one file on Drive, so `total_charts` comes back as 1 no matter how
many songs are inside. Telling someone a 94-chart pack contains one chart is
worse than an estimate, so a count can come from three places. In order:

1. **A forced count** in ``archive_charts.json``, which always wins. This is the
   escape hatch: any setlist whose count is wrong for any reason can be pinned
   there without touching code or waiting for a release.
2. **The disk**, once the archive has been downloaded and extracted -- what is
   actually there beats any estimate.
3. **The built-in table** below, which covers the gap before a download, and
   only ever corrects an undercount.

The file lives beside settings.json and looks like this::

    {
      "(2006) Guitar Hero II": 100,
      "Guitar Hero/(2005) Guitar Hero": 58
    }

A bare key matches the setlist wherever it appears; a "Drive/Setlist" key
matches only inside that drive, for when two drives use the same setlist name.
Punctuation and case are ignored on both sides, because Drive writes
"Guitar Hero: Metallica" where the extracted folder is "Guitar Hero - Metallica".

The built-in table is a stopgap and should not grow -- forced counts are the
place for new entries now. The real fix is reading an archive's listing without
downloading it, which would retire the table entirely.
"""

import json
import re

from src.core.logging import debug_log


OVERRIDE_FILENAME = "archive_charts.json"


# Counts measured from extracted copies on 2026-08-27. Packs that already ship
# as loose charts are deliberately absent: Drive counts those correctly, and an
# entry here would override a good number with a stale one.
_ARCHIVE_CHART_COUNTS = {
    "(2005) Guitar Hero": 58,
    "(2006) Guitar Hero II": 100,
    "(2007) Guitar Hero Encore: Rocks the 80s": 39,
    "(2007) Guitar Hero III: Legends of Rock": 75,
    "(2008) Guitar Hero On Tour": 31,
    "(2008) Guitar Hero On Tour: Modern Hits": 44,
    "(2008) Guitar Hero World Tour": 86,
    "(2008) Guitar Hero: Aerosmith": 47,
    "(2009) Band Hero": 71,
    "(2009) DJ Hero": 10,
    "(2009) Guitar Hero 5": 90,
    "(2009) Guitar Hero Smash Hits": 50,
    "(2009) Guitar Hero: Metallica": 49,
    "(2009) Guitar Hero: On Tour Decades": 36,
    "(2009) Guitar Hero: Van Halen": 47,
    "(2010) Guitar Hero: Warriors of Rock": 94,
}


def _key(name: str) -> str:
    """Fold punctuation and case away.

    >>> _key("(2009) Guitar Hero: Metallica") == _key("(2009) Guitar Hero - Metallica")
    True
    """
    return re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).strip()


def _scoped(drive: str, setlist: str) -> str:
    return f"{_key(drive)}/{_key(setlist)}"


_BY_KEY = {_key(name): count for name, count in _ARCHIVE_CHART_COUNTS.items()}

_forced_cache = None


def _override_path():
    from src.core.paths import get_data_dir
    return get_data_dir() / OVERRIDE_FILENAME


def load_forced_counts(path=None) -> dict:
    """Read the forced-count file. A missing file is the normal case; a broken
    one is logged and ignored rather than taking the app down over a stray
    comma."""
    path = path or _override_path()
    try:
        if not path.exists():
            return {}
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        debug_log(f"ARCHIVE_CHARTS | could not read {path}: {e}")
        return {}

    if not isinstance(raw, dict):
        debug_log(f"ARCHIVE_CHARTS | {path} is not an object, ignoring")
        return {}

    out = {}
    for name, count in raw.items():
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            debug_log(f"ARCHIVE_CHARTS | {name!r}: {count!r} is not a count, ignoring")
            continue
        if "/" in name:
            drive, _, setlist = name.partition("/")
            out[_scoped(drive, setlist)] = count
        else:
            out[_key(name)] = count
    return out


def forced_counts(reload: bool = False) -> dict:
    """Forced counts, read once per run unless asked to reload."""
    global _forced_cache
    if _forced_cache is None or reload:
        _forced_cache = load_forced_counts()
    return _forced_cache


def known_archive_charts(setlist_name: str) -> int:
    """Charts in a known single-archive setlist, or 0 if it is not one."""
    return _BY_KEY.get(_key(setlist_name), 0)


def effective_chart_count(setlist_name: str, total_charts: int, disk_charts: int,
                          drive_name: str = "", forced: dict = None) -> int:
    """The truest chart count available for a setlist.

    >>> effective_chart_count("(2006) Guitar Hero II", 1, 0, forced={})
    100
    >>> effective_chart_count("(2006) Guitar Hero II", 1, 97, forced={})
    97
    >>> effective_chart_count("(2015) Guitar Hero Live", 42, 0, forced={})
    42
    >>> effective_chart_count("Some Pack", 173, 0, forced={})
    173
    >>> effective_chart_count("Some Pack", 173, 200, forced={_key("Some Pack"): 5})
    5
    """
    table = forced_counts() if forced is None else forced
    # A forced count is a deliberate instruction, so it outranks even the disk.
    if drive_name:
        pinned = table.get(_scoped(drive_name, setlist_name))
        if pinned is not None:
            return pinned
    pinned = table.get(_key(setlist_name))
    if pinned is not None:
        return pinned

    if disk_charts > total_charts:
        return disk_charts
    known = known_archive_charts(setlist_name)
    return known if known > total_charts else total_charts
