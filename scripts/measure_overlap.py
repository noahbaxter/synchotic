#!/usr/bin/env python3
"""
Measure actual chart overlap across default drives using MD5.

Groups files into charts (folder/archive/sng), then matches charts
across drives by their identity files (notes.mid/notes.chart MD5).

Caches raw scan results to .overlap_cache.json so reruns skip API calls.
Use --no-cache to force a fresh scan.

Usage:
    .venv/bin/python scripts/measure_overlap.py
    .venv/bin/python scripts/measure_overlap.py --no-cache
"""

import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.drive.client import DriveClient, DriveClientConfig
from src.drive.scanner import FolderScanner
from src.manifest.counter import (
    CHART_NOTE_FILES,
    is_sng_file,
    is_zip_file,
    has_folder_chart_markers,
)

CACHE_FILE = Path(__file__).parent.parent / ".overlap_cache.json"


def load_api_key() -> str:
    key = os.environ.get("GOOGLE_API_KEY", "")
    if key:
        return key
    env_file = Path(__file__).parent.parent / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line.startswith("GOOGLE_API_KEY=") and not line.endswith("_here"):
                return line.split("=", 1)[1].strip()
    return ""


def load_drives() -> list[dict]:
    drives_file = Path(__file__).parent.parent / "drives.json"
    with open(drives_file) as f:
        return json.load(f)["drives"]


def load_cache() -> dict[str, list[dict]] | None:
    if not CACHE_FILE.exists():
        return None
    try:
        with open(CACHE_FILE) as f:
            data = json.load(f)
        print(f"Loaded cached scan from {CACHE_FILE.name} ({data.get('timestamp', 'unknown')})\n")
        return data["drives"]
    except Exception as e:
        print(f"Cache load failed ({e}), rescanning...\n")
        return None


def save_cache(drive_files: dict[str, list[dict]]):
    data = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "drives": drive_files,
    }
    with open(CACHE_FILE, "w") as f:
        json.dump(data, f)
    print(f"Cached scan results to {CACHE_FILE.name}\n")


FOLDER_MIME = "application/vnd.google-apps.folder"
SHORTCUT_MIME = "application/vnd.google-apps.shortcut"


def scan_drive(scanner: FolderScanner, drive: dict) -> list[dict]:
    """Scan all setlists in a drive, return flat file list.

    Setlist discovery mirrors BackgroundScanner._discover_folder_setlists:
    top-level folders AND shortcuts-to-folders are treated as setlists.
    """
    folder_id = drive["folder_id"]
    items = scanner.client.list_folder(folder_id)

    setlists = []
    for item in items:
        mime = item.get("mimeType")
        if mime == FOLDER_MIME:
            setlists.append((item["id"], item["name"]))
        elif mime == SHORTCUT_MIME:
            details = item.get("shortcutDetails", {})
            if details.get("targetMimeType") == FOLDER_MIME and details.get("targetId"):
                setlists.append((details["targetId"], item["name"]))

    all_files = []
    for setlist_id, setlist_name in setlists:
        result = scanner.scan(setlist_id, base_path=setlist_name)
        all_files.extend(result.files)
        print(f"    {setlist_name}: {len(result.files)} files")

    # Flat drives (no setlist subfolders) — scan the drive root directly
    if not setlists:
        result = scanner.scan(folder_id)
        all_files.extend(result.files)

    return all_files


def scan_all_drives(drives: list[dict], use_cache: bool) -> dict[str, list[dict]]:
    """Scan all drives, using cache per-drive where available."""
    cached = load_cache() if use_cache else None
    cached = cached or {}

    client = None
    scanner = None
    drive_files: dict[str, list[dict]] = {}
    rescanned = False

    for drive in drives:
        name = drive["name"]
        if name in cached and len(cached[name]) > 0:
            drive_files[name] = cached[name]
            total_size = sum(f.get("size", 0) for f in cached[name])
            print(f"[{name}] (cached) {len(cached[name])} files, {fmt_size(total_size)}")
            print()
            continue

        # Need to scan — lazy-init client
        if client is None:
            api_key = load_api_key()
            if not api_key:
                print("Error: No GOOGLE_API_KEY found in environment or .env")
                sys.exit(1)
            client = DriveClient(DriveClientConfig(api_key=api_key))
            scanner = FolderScanner(client)

        print(f"[{name}]")
        start = time.time()
        files = scan_drive(scanner, drive)
        elapsed = time.time() - start
        drive_files[name] = files
        rescanned = True

        total_size = sum(f.get("size", 0) for f in files)
        print(f"  Total: {len(files)} files, {fmt_size(total_size)}, {elapsed:.1f}s")
        print(f"  API calls so far: {client.api_calls}")
        print()

    if rescanned:
        save_cache(drive_files)

    return drive_files


def extract_charts(files: list[dict], drive_name: str) -> list[dict]:
    """Group flat file list into charts. Returns list of chart dicts.

    Each chart dict has:
      - drive: str
      - path: str (chart folder path, or archive/sng file path)
      - type: "folder" | "archive" | "sng"
      - identity_md5s: set of MD5s from notes.mid/notes.chart (folder charts)
                       or the archive/sng file MD5 itself
      - total_size: int (sum of all files in the chart)
      - file_count: int
    """
    charts = []

    # Group files by parent folder
    files_by_parent: dict[str, list[dict]] = defaultdict(list)
    for f in files:
        parts = Path(f["path"]).parts
        if len(parts) >= 2:
            parent = "/".join(parts[:-1])
            files_by_parent[parent].append(f)
        else:
            files_by_parent["__root__"].append(f)

    claimed_parents = set()

    # Pass 1: Find folder charts (folders with song.ini / notes.mid / notes.chart)
    for parent, parent_files in files_by_parent.items():
        if parent == "__root__":
            continue
        filenames = {Path(f["path"]).name for f in parent_files}
        if not has_folder_chart_markers(filenames):
            continue

        identity_md5s = set()
        for f in parent_files:
            fname = Path(f["path"]).name.lower()
            if fname in CHART_NOTE_FILES and f.get("md5"):
                identity_md5s.add(f["md5"])

        if not identity_md5s:
            continue

        charts.append({
            "drive": drive_name,
            "path": parent,
            "type": "folder",
            "identity_md5s": identity_md5s,
            "total_size": sum(f.get("size", 0) for f in parent_files),
            "file_count": len(parent_files),
        })
        claimed_parents.add(parent)

    # Pass 2: Archives and .sng files (anywhere not already claimed as folder chart)
    for parent, parent_files in files_by_parent.items():
        if parent in claimed_parents and parent != "__root__":
            continue
        for f in parent_files:
            fname = Path(f["path"]).name
            md5 = f.get("md5", "")
            if not md5:
                continue

            if is_sng_file(fname):
                charts.append({
                    "drive": drive_name,
                    "path": f["path"],
                    "type": "sng",
                    "identity_md5s": {md5},
                    "total_size": f.get("size", 0),
                    "file_count": 1,
                })
            elif is_zip_file(fname):
                charts.append({
                    "drive": drive_name,
                    "path": f["path"],
                    "type": "archive",
                    "identity_md5s": {md5},
                    "total_size": f.get("size", 0),
                    "file_count": 1,
                })

    return charts


def fmt_size(n: int) -> str:
    if n >= 1024**3:
        return f"{n / 1024**3:.1f} GB"
    if n >= 1024**2:
        return f"{n / 1024**2:.1f} MB"
    return f"{n / 1024:.0f} KB"


def analyze(drive_files: dict[str, list[dict]]):
    """Run the overlap analysis on scan data."""
    all_charts: list[dict] = []
    for drive_name, files in drive_files.items():
        charts = extract_charts(files, drive_name)
        all_charts.extend(charts)
        total_size = sum(f.get("size", 0) for f in files)
        print(f"  {drive_name}: {len(files)} files, {len(charts)} charts, {fmt_size(total_size)}")
    print()

    # Build identity index: md5 -> list of charts
    # Two charts are dupes if they share ANY identity MD5
    md5_to_charts: dict[str, list[dict]] = defaultdict(list)
    for chart in all_charts:
        for md5 in chart["identity_md5s"]:
            md5_to_charts[md5].append(chart)

    # Find ALL dupes: cross-drive, within-drive, within-setlist
    dupe_groups: list[list[dict]] = []
    seen_charts = set()

    for md5, charts in md5_to_charts.items():
        if len(charts) < 2:
            continue

        group = []
        for c in charts:
            key = (c["drive"], c["path"])
            if key not in seen_charts:
                seen_charts.add(key)
                group.append(c)
        if len(group) >= 2:
            dupe_groups.append(group)

    # Categorize dupes
    cross_drive_groups = [g for g in dupe_groups if len({c["drive"] for c in g}) >= 2]
    within_drive_groups = [g for g in dupe_groups if len({c["drive"] for c in g}) == 1]

    # Stats
    total_charts = len(all_charts)
    total_files = sum(len(f) for f in drive_files.values())
    total_size = sum(f.get("size", 0) for files in drive_files.values() for f in files)

    extra_charts = sum(len(g) - 1 for g in dupe_groups)
    extra_cross = sum(len(g) - 1 for g in cross_drive_groups)
    extra_within = sum(len(g) - 1 for g in within_drive_groups)
    extra_bytes = sum(
        sum(sorted(c["total_size"] for c in g)[:-1])
        for g in dupe_groups
    )

    print("=" * 60)
    print("RESULTS")
    print("=" * 60)
    print(f"  Total files:      {total_files}")
    print(f"  Total size:       {fmt_size(total_size)}")
    print(f"  Total charts:     {total_charts}")
    print()
    print(f"  Dupe groups:      {len(dupe_groups)} charts have duplicates")
    print(f"    Cross-drive:    {len(cross_drive_groups)} groups, {extra_cross} extra copies")
    print(f"    Within-drive:   {len(within_drive_groups)} groups, {extra_within} extra copies")
    print(f"  Total extra:      {extra_charts} charts could be skipped")
    print(f"  Wasted space:     {fmt_size(extra_bytes)}")
    if total_charts > 0:
        print(f"  Dupe rate:        {extra_charts / total_charts * 100:.1f}% of charts are redundant")
    print()
    print("  NOTE: MD5 matching only — charts packaged differently")
    print("  (same song, different upload) won't be detected.")
    print()

    # Per-drive breakdown
    print("=" * 60)
    print("PER-DRIVE BREAKDOWN")
    print("=" * 60)
    for drive_name, files in drive_files.items():
        drive_charts = [c for c in all_charts if c["drive"] == drive_name]
        drive_size = sum(f.get("size", 0) for f in files)
        duped = [c for c in drive_charts if (c["drive"], c["path"]) in seen_charts]
        duped_size = sum(c["total_size"] for c in duped)
        pct = (len(duped) / len(drive_charts) * 100) if drive_charts else 0
        print(f"  {drive_name}")
        print(f"    {len(drive_charts)} charts, {fmt_size(drive_size)} total")
        print(f"    {len(duped)} duped ({pct:.0f}%), {fmt_size(duped_size)} overlap")
        print()

    # Top 20 dupe groups by wasted size
    if dupe_groups:
        print("=" * 60)
        print("MOST DUPLICATED (top 20 by wasted size)")
        print("=" * 60)
        by_waste = sorted(
            dupe_groups,
            key=lambda g: sum(c["total_size"] for c in g) - max(c["total_size"] for c in g),
            reverse=True,
        )[:20]
        for group in by_waste:
            drives_in = sorted({c["drive"] for c in group})
            label = Path(group[0]["path"]).name
            chart_type = group[0]["type"]
            copies = len(group)
            waste = sum(c["total_size"] for c in group) - max(c["total_size"] for c in group)
            scope = "same drive" if len(drives_in) == 1 else ", ".join(drives_in)
            print(f"  {copies}x  {label} [{chart_type}] — wastes {fmt_size(waste)} — {scope}")


def main():
    use_cache = "--no-cache" not in sys.argv

    drives = load_drives()
    drive_files = scan_all_drives(drives, use_cache)
    analyze(drive_files)


if __name__ == "__main__":
    main()
