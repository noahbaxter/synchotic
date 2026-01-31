"""Shared helpers for debug scripts."""

import sys
from pathlib import Path

# Add repo root to path for src imports
REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

# Import from src - single source of truth
from src.manifest import MANIFEST_URL, fetch_manifest as _src_fetch_manifest
from src.core.constants import CHART_MARKERS, CHART_ARCHIVE_EXTENSIONS


def fetch_manifest() -> dict:
    """Fetch manifest from GitHub releases (wrapper around src/manifest.py)."""
    print(f"Fetching manifest from GitHub releases...")
    return _src_fetch_manifest(use_local=False)


def find_folder_in_manifest(manifest: dict, folder_name: str) -> dict:
    """Find a folder in the manifest by name."""
    matching = [f for f in manifest.get("folders", []) if f.get("name") == folder_name]
    if not matching:
        available = [f.get("name") for f in manifest.get("folders", [])]
        raise ValueError(f"Folder '{folder_name}' not found. Available: {available}")
    return matching[0]


def load_settings_from_sync_path(sync_path: Path):
    """Load UserSettings from the .dm-sync folder relative to sync path."""
    from src.config import UserSettings

    # sync_path is like /path/to/Sync Charts/DriveName
    # settings are at /path/to/Sync Charts/../.dm-sync/settings.json
    # or /path/to/.dm-sync/settings.json (parent of Sync Charts)
    settings_path = sync_path.parent.parent / ".dm-sync" / "settings.json"

    if not settings_path.exists():
        # Try one level up
        settings_path = sync_path.parent / ".dm-sync" / "settings.json"

    if not settings_path.exists():
        raise FileNotFoundError(f"No settings.json found near {sync_path}")

    print(f"Loading settings from: {settings_path}")
    return UserSettings.load(settings_path)  # Use .load() classmethod!


def count_disk_charts(folder_path: Path, disabled_setlists: set = None) -> int:
    """Count actual chart folders on disk (folders with chart markers).

    A chart is a FOLDER containing at least one marker file (song.ini, notes.mid, notes.chart).
    We count unique folders, not marker files.

    Args:
        folder_path: Path to scan
        disabled_setlists: Set of setlist names to skip (for respecting user settings)
    """
    if not folder_path.exists():
        return 0

    chart_folders = set()
    markers_lower = {m.lower() for m in CHART_MARKERS}
    disabled_setlists = disabled_setlists or set()

    for item in folder_path.rglob("*"):
        if item.is_file() and item.name.lower() in markers_lower:
            chart_folder = item.parent

            # Check if this folder is in a disabled setlist
            if disabled_setlists:
                try:
                    rel = chart_folder.relative_to(folder_path)
                    parts = rel.parts
                    if parts and parts[0] in disabled_setlists:
                        continue
                except ValueError:
                    pass

            chart_folders.add(chart_folder)

    return len(chart_folders)


def count_manifest_charts(files: list, setlist_filter: str = None) -> int:
    """Count charts in a file list from manifest.

    Args:
        files: List of file dicts with 'path' and 'name' keys
        setlist_filter: Only count files in this setlist (optional)
    """
    archive_exts = {ext.lower() for ext in CHART_ARCHIVE_EXTENSIONS}
    markers_lower = {m.lower() for m in CHART_MARKERS}
    charts = set()

    for f in files:
        path = f.get("path", "")

        if setlist_filter and not path.startswith(setlist_filter + "/"):
            continue

        name = f.get("name", "").lower()

        if any(name.endswith(ext) for ext in archive_exts):
            charts.add(path)
        elif name in markers_lower:
            parent = str(Path(path).parent)
            charts.add(parent)

    return len(charts)


def get_setlists_from_manifest(folder: dict, include_size: bool = False) -> list:
    """Get list of setlists from a folder's manifest.

    Args:
        folder: Folder dict with 'files' key
        include_size: If True, returns (name, chart_count, size_bytes)
                      If False, returns (name, chart_count)
    """
    files = folder.get("files", [])
    setlist_data: dict[str, dict] = {}

    archive_exts = {ext.lower() for ext in CHART_ARCHIVE_EXTENSIONS}
    markers_lower = {m.lower() for m in CHART_MARKERS}

    for f in files:
        path = f.get("path", "")
        if "/" not in path:
            continue

        setlist = path.split("/")[0]
        name = f.get("name", "").lower()

        if setlist not in setlist_data:
            setlist_data[setlist] = {"charts": set(), "size": 0}

        if include_size:
            setlist_data[setlist]["size"] += f.get("size", 0)

        if any(name.endswith(ext) for ext in archive_exts):
            setlist_data[setlist]["charts"].add(path)
        elif name in markers_lower:
            parent = str(Path(path).parent)
            setlist_data[setlist]["charts"].add(parent)

    if include_size:
        return sorted(
            (name, len(data["charts"]), data["size"])
            for name, data in setlist_data.items()
        )
    else:
        return sorted(
            (name, len(data["charts"]))
            for name, data in setlist_data.items()
        )
