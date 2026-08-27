"""Which drive folders Synchotic created, and whether this library is adopted.

Library Path lets people point at a folder they already have. Drive names like
"Guitar Hero", "Rock Band" and "Misc" are exactly what players call their own
folders, so a name match is a guess, and acting on a wrong guess deletes someone's
collection. Purge therefore needs evidence that a folder is ours, not just that
the name lines up.

One file, two guarantees:
  * a library with no record is freshly adopted, so the first sync never purges
  * a drive folder we have never synced into is never mass-deleted when disabled
"""

import json
from pathlib import Path

from ..core.logging import debug_log
from ..core.paths import get_library_state_dir

OWNED_FILE = "owned_drives.json"


def _path() -> Path:
    return get_library_state_dir() / OWNED_FILE


def is_library_adopted() -> bool:
    """False until a sync has completed here. False means: do not purge.

    Markers count as proof. A v1.4 install upgrading has thousands of them and
    no ownership file, and treating that as an unknown library would silently
    stop purge working for every existing user.
    """
    if _path().exists():
        return True
    from .markers import get_marked_drive_names
    return bool(get_marked_drive_names())


def get_owned_drives() -> set[str]:
    """Drive folder ids this library has actually synced."""
    try:
        return set(json.loads(_path().read_text()).get("drives", []))
    except Exception:
        return set()


def mark_drive_owned(folder_id: str) -> None:
    """Record that we synced into this drive's folder, so purge may manage it."""
    if not folder_id:
        return
    owned = get_owned_drives()
    if folder_id in owned:
        return
    owned.add(folder_id)
    _write(owned)
    debug_log(f"OWNERSHIP | now own {folder_id} | total={len(owned)}")


def mark_library_adopted() -> None:
    """Finish adoption without claiming any drive, so later syncs may purge."""
    if not _path().exists():
        _write(get_owned_drives())


def resolve_owned_drives(folders) -> set[str]:
    """Drive ids we may manage: recorded, plus any a marker proves we synced.

    `mark_drive_owned` only fires when a sync actually downloaded something
    (`folder_sync.py`), and a fully synced drive returns before reaching it. On
    its own that means an upgrading user owns nothing, so disabling any drive
    would skip its purge forever. Markers close that gap and self-heal.
    """
    from .markers import get_marked_drive_names

    owned = get_owned_drives()
    marked = get_marked_drive_names()
    for folder in folders:
        name = folder.get("name", "")
        folder_id = folder.get("folder_id", "")
        if name and folder_id and name in marked:
            owned.add(folder_id)
    return owned


def backfill_owned_from_markers(folders) -> int:
    """Persist marker-derived ownership. Returns how many drives were added."""
    before = get_owned_drives()
    resolved = resolve_owned_drives(folders)
    added = resolved - before
    if added or not _path().exists():
        _write(resolved)
    if added:
        debug_log(f"OWNERSHIP | backfilled {len(added)} drive(s) from markers")
    return len(added)


def _write(owned: set[str]) -> None:
    try:
        _path().write_text(json.dumps({"drives": sorted(owned)}, indent=2))
    except OSError as e:
        debug_log(f"OWNERSHIP | write failed | {e}")
