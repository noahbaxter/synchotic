#!/usr/bin/env python3
"""
Rebuild sync_state.json from disk by matching extracted folders to manifest archives.

This fixes malformed sync_state entries where archives were extracted but not properly tracked.
The script:
1. Scans disk for extracted chart folders
2. Matches them to manifest archives (by folder name = archive stem)
3. Rebuilds sync_state with proper archive entries including extracted files

Usage:
    python scripts/rebuild_sync_state.py              # Interactive mode
    python scripts/rebuild_sync_state.py --drive Misc # Rebuild specific drive
    python scripts/rebuild_sync_state.py --all        # Rebuild all drives
    python scripts/rebuild_sync_state.py --dry-run    # Show what would change
"""

import argparse
import sys
from pathlib import Path
from _helpers import REPO_ROOT

sys.path.insert(0, str(REPO_ROOT))

from src.manifest import fetch_manifest
from src.sync.state import SyncState
from src.sync.extractor import scan_extracted_files
from src.core.constants import CHART_MARKERS, CHART_ARCHIVE_EXTENSIONS
from src.core.paths import get_download_path, get_settings_path
from src.core.formatting import normalize_fs_name
from src.config import UserSettings


def find_extracted_charts(folder_path: Path) -> dict[str, Path]:
    """Find chart folders on disk. Returns {relative_path: absolute_path}."""
    charts = {}
    if not folder_path.exists():
        return charts

    markers_lower = {m.lower() for m in CHART_MARKERS}

    for item in folder_path.rglob("*"):
        if item.is_file() and item.name.lower() in markers_lower:
            chart_folder = item.parent
            try:
                rel_path = chart_folder.relative_to(folder_path)
                key = str(rel_path).replace("\\", "/")
                if key not in charts:
                    charts[key] = chart_folder
            except ValueError:
                continue

    return charts


def get_archive_stem(archive_name: str) -> str:
    """Get folder name from archive name (strip extension)."""
    for ext in CHART_ARCHIVE_EXTENSIONS:
        if archive_name.lower().endswith(ext):
            return archive_name[:-len(ext)]
    return archive_name


def rebuild_drive(
    folder: dict,
    base_path: Path,
    sync_state: SyncState,
    dry_run: bool = False,
) -> tuple[int, int, int]:
    """
    Rebuild sync_state entries for a single drive.

    Handles both:
    - Archive charts: match disk folders to manifest archives
    - Folder charts: match individual files on disk to manifest files

    Returns: (matched, unmatched_disk, unmatched_manifest)
    """
    folder_name = folder.get("name", "")
    folder_path = base_path / folder_name

    if not folder_path.exists():
        print(f"  {folder_name}: folder doesn't exist, skipping")
        return 0, 0, 0

    manifest_files = folder.get("files", [])
    if not manifest_files:
        print(f"  {folder_name}: no files in manifest, skipping")
        return 0, 0, 0

    # Separate archives from regular files
    archives = []
    regular_files = []
    for f in manifest_files:
        path = f.get("path", "")
        if any(path.lower().endswith(ext) for ext in CHART_ARCHIVE_EXTENSIONS):
            archives.append(f)
        else:
            regular_files.append(f)

    matched = 0
    unmatched_disk = 0
    matched_keys = set()

    # === Handle archives ===
    if archives:
        archive_lookup = {}
        for f in archives:
            path = f.get("path", "")
            name = path.split("/")[-1] if "/" in path else path
            stem = get_archive_stem(name)
            normalized_stem = normalize_fs_name(stem)
            parent = path.rsplit("/", 1)[0] if "/" in path else ""

            parent_normalized = normalize_fs_name(parent.split("/")[-1]) if parent else ""
            if parent and parent_normalized.lower() == normalized_stem.lower():
                chart_folder_key = parent
            else:
                chart_folder_key = f"{parent}/{normalized_stem}" if parent else normalized_stem

            archive_lookup[chart_folder_key.lower()] = {
                "path": path,
                "md5": f.get("md5", ""),
                "size": f.get("size", 0),
            }

        disk_charts = find_extracted_charts(folder_path)

        for chart_name, chart_path in disk_charts.items():
            try:
                rel_path = chart_path.relative_to(folder_path)
                lookup_key = str(rel_path).replace("\\", "/")
            except ValueError:
                continue

            if lookup_key.lower() in archive_lookup:
                archive_info = archive_lookup[lookup_key.lower()]
                archive_path = f"{folder_name}/{archive_info['path']}"
                extracted_files = scan_extracted_files(chart_path, chart_path)

                if not dry_run:
                    sync_state.add_archive(
                        path=archive_path,
                        md5=archive_info["md5"],
                        archive_size=archive_info["size"],
                        files=extracted_files,
                    )

                matched += 1
                matched_keys.add(lookup_key.lower())
            else:
                unmatched_disk += 1

        unmatched_manifest = len(archive_lookup) - len(matched_keys)
    else:
        unmatched_manifest = 0

    # === Handle folder charts (individual files) ===
    if regular_files:
        # Build lookup of manifest files by path
        file_lookup = {}
        for f in regular_files:
            path = f.get("path", "")
            file_lookup[path.lower()] = {
                "path": path,
                "md5": f.get("md5", ""),
                "size": f.get("size", 0),
            }

        # Scan all files on disk
        files_matched = 0
        for disk_file in folder_path.rglob("*"):
            if not disk_file.is_file():
                continue

            try:
                rel_path = disk_file.relative_to(folder_path)
                lookup_key = str(rel_path).replace("\\", "/")
            except ValueError:
                continue

            if lookup_key.lower() in file_lookup:
                file_info = file_lookup[lookup_key.lower()]
                full_path = f"{folder_name}/{file_info['path']}"

                if not dry_run:
                    actual_size = disk_file.stat().st_size
                    sync_state.add_file(full_path, actual_size, file_info["md5"])

                files_matched += 1

        matched += files_matched
        # Don't count unmatched manifest files for folder charts - too noisy
        # (many files per chart, ~12% not synced is expected)

    return matched, unmatched_disk, unmatched_manifest


def main():
    parser = argparse.ArgumentParser(description="Rebuild sync_state from disk")
    parser.add_argument("--drive", help="Drive name to rebuild")
    parser.add_argument("--all", action="store_true", help="Rebuild all drives")
    parser.add_argument("--dry-run", action="store_true", help="Show what would change")
    args = parser.parse_args()

    print("Fetching manifest...")
    try:
        manifest = fetch_manifest(use_local=False)
    except Exception as e:
        print(f"Failed to fetch manifest: {e}")
        print("Falling back to cached manifest...")
        manifest = fetch_manifest(use_local=True)

    folders = manifest.get("folders", [])
    print(f"Manifest has {len(folders)} drives\n")

    # Load sync state
    sync_state = SyncState()
    sync_state.load()

    stats = sync_state.get_stats()
    print(f"Current sync_state: {stats['total_files']} files, {stats['total_archives']} archives")

    base_path = get_download_path()

    if args.all:
        drives_to_rebuild = [f.get("name") for f in folders]
    elif args.drive:
        drives_to_rebuild = [args.drive]
    else:
        # Interactive mode
        print("\nSelect drive to rebuild:\n")
        print("  [0] All drives")
        for i, folder in enumerate(folders, 1):
            name = folder.get("name", "unknown")
            print(f"  [{i}] {name}")
        print()

        while True:
            try:
                choice = input("Drive [0]: ").strip()
                if choice == "":
                    choice = 0
                else:
                    choice = int(choice)
                if 0 <= choice <= len(folders):
                    break
                print(f"Enter 0-{len(folders)}")
            except ValueError:
                print(f"Enter 0-{len(folders)}")
            except (KeyboardInterrupt, EOFError):
                print("\nCancelled.")
                return 1

        if choice == 0:
            drives_to_rebuild = [f.get("name") for f in folders]
        else:
            drives_to_rebuild = [folders[choice - 1].get("name")]

    print()
    if args.dry_run:
        print("DRY RUN - no changes will be made\n")

    total_matched = 0
    total_unmatched_disk = 0
    total_unmatched_manifest = 0

    for drive_name in drives_to_rebuild:
        folder = next((f for f in folders if f.get("name") == drive_name), None)
        if not folder:
            print(f"  {drive_name}: not found in manifest")
            continue

        matched, unmatched_disk, unmatched_manifest = rebuild_drive(
            folder, base_path, sync_state, dry_run=args.dry_run
        )

        if matched > 0 or unmatched_disk > 0:
            print(f"  {drive_name}: {matched} matched, {unmatched_disk} disk-only, {unmatched_manifest} manifest-only")

        total_matched += matched
        total_unmatched_disk += unmatched_disk
        total_unmatched_manifest += unmatched_manifest

    print(f"\nTotal: {total_matched} archives matched to disk folders")
    if total_unmatched_disk > 0:
        print(f"  {total_unmatched_disk} folders on disk not in manifest (untracked content)")
    if total_unmatched_manifest > 0:
        print(f"  {total_unmatched_manifest} archives in manifest not on disk (not synced)")

    if not args.dry_run and total_matched > 0:
        sync_state.save()
        new_stats = sync_state.get_stats()
        print(f"\nSync state saved: {new_stats['total_files']} files, {new_stats['total_archives']} archives")
    elif args.dry_run:
        print("\nNo changes made (dry run)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
