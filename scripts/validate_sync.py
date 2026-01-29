#!/usr/bin/env python3
"""
Validate that sync status reports match reality.

This tool verifies the app tells the truth by comparing three sources:
1. MANIFEST (from GitHub) - what SHOULD exist
2. STATUS (get_sync_status) - what the app REPORTS
3. DISK - what ACTUALLY exists

If these disagree, the app is lying to users.

Usage:
    python scripts/validate_sync.py              # Interactive mode
    python scripts/validate_sync.py --drive X    # Check specific drive
"""

import argparse
import sys
from pathlib import Path
from _helpers import (
    REPO_ROOT,
    count_disk_charts,
    count_manifest_charts,
    get_setlists_from_manifest,
)

sys.path.insert(0, str(REPO_ROOT))

from src.manifest import fetch_manifest
from src.sync.state import SyncState
from src.sync.status import get_sync_status, get_setlist_sync_status
from src.config import UserSettings
from src.core.paths import get_download_path, get_settings_path


def interactive_select(manifest: dict, settings: UserSettings) -> tuple[dict | None, str | None, bool, bool]:
    """Interactive menu. Returns (folder, setlist_name, deep, failfast)."""
    folders = manifest.get("folders", [])

    if not folders:
        print("No folders in manifest.")
        return None, None, False, False

    failfast = True
    deep = True

    def print_drive_menu():
        print("Select drive to validate:\n")
        print("  [0] All enabled drives")
        for i, folder in enumerate(folders, 1):
            name = folder.get("name", "unknown")
            chart_count = count_manifest_charts(folder.get("files", []))
            enabled = "enabled" if settings.is_drive_enabled(folder.get("folder_id")) else "disabled"
            print(f"  [{i}] {name} ({chart_count} charts, {enabled})")
        print()
        ff_status = "ON" if failfast else "OFF"
        deep_status = "ON" if deep else "OFF"
        print(f"  [f] Stop at first failure: {ff_status}")
        print(f"  [d] Check each setlist: {deep_status}")
        print()

    print_drive_menu()

    while True:
        try:
            choice = input("Drive [0]: ").strip().lower()
            if choice == "f":
                failfast = not failfast
                print_drive_menu()
                continue
            if choice == "d":
                deep = not deep
                print_drive_menu()
                continue
            if choice == "":
                choice = 0
            else:
                choice = int(choice)
            if 0 <= choice <= len(folders):
                break
            print(f"Enter 0-{len(folders)}, f, or d")
        except ValueError:
            print(f"Enter 0-{len(folders)}, f, or d")
        except (KeyboardInterrupt, EOFError):
            print("\nCancelled.")
            sys.exit(0)

    selected_folder = None
    selected_setlist = None

    if choice > 0:
        selected_folder = folders[choice - 1]

        # Show setlists for selected drive
        setlists = get_setlists_from_manifest(selected_folder)

        if setlists:
            print(f"\nSelect setlist in {selected_folder.get('name')}:\n")
            print("  [0] All setlists")
            for i, (name, count) in enumerate(setlists, 1):
                print(f"  [{i}] {name} ({count} charts)")
            print()

            while True:
                try:
                    sl_choice = input("Setlist [0]: ").strip()
                    if sl_choice == "":
                        sl_choice = 0
                    else:
                        sl_choice = int(sl_choice)
                    if 0 <= sl_choice <= len(setlists):
                        break
                    print(f"Enter 0-{len(setlists)}")
                except ValueError:
                    print(f"Enter 0-{len(setlists)}")
                except (KeyboardInterrupt, EOFError):
                    print("\nCancelled.")
                    sys.exit(0)

            if sl_choice > 0:
                selected_setlist = setlists[sl_choice - 1][0]

    print()
    return selected_folder, selected_setlist, deep, failfast


def validate_drive(folder: dict, base_path: Path, sync_state: SyncState,
                   settings: UserSettings, setlist_filter: str = None) -> dict:
    """Validate a single drive. Returns validation results."""
    name = folder.get("name", "unknown")
    folder_id = folder.get("folder_id", "")
    folder_path = base_path / name

    results = {
        "name": name,
        "setlist": setlist_filter,
        "enabled": settings.is_drive_enabled(folder_id),
        "status_total": 0,
        "status_synced": 0,
        "status_percent": 0.0,
        "disk_charts": 0,
        "passed": False,
        "issues": []
    }

    # Get disabled setlists to filter disk count properly
    disabled_setlists = settings.get_disabled_subfolders(folder_id)

    # 1. STATUS: What app reports (this already respects enabled/disabled)
    if setlist_filter:
        status = get_setlist_sync_status(
            folder=folder,
            setlist_name=setlist_filter,
            base_path=base_path,
            sync_state=sync_state,
            delete_videos=settings.delete_videos
        )
        # For single setlist, no need to filter
        disabled_setlists = set()
    else:
        status = get_sync_status(
            folders=[folder],
            base_path=base_path,
            user_settings=settings,
            sync_state=sync_state
        )

    results["status_total"] = status.total_charts
    results["status_synced"] = status.synced_charts
    if status.total_charts > 0:
        results["status_percent"] = (status.synced_charts / status.total_charts) * 100

    # 2. DISK: What actually exists (respecting same enabled/disabled filters)
    if setlist_filter:
        disk_path = folder_path / setlist_filter
        results["disk_charts"] = count_disk_charts(disk_path)
    else:
        results["disk_charts"] = count_disk_charts(folder_path, disabled_setlists)

    # Compare: Status synced should match disk reality
    issues = []

    if results["status_synced"] != results["disk_charts"]:
        diff = results["disk_charts"] - results["status_synced"]
        if diff > 0:
            issues.append(
                f"Status says {results['status_synced']} synced but disk has {results['disk_charts']} (+{diff} untracked)"
            )
        else:
            issues.append(
                f"Status says {results['status_synced']} synced but disk has {results['disk_charts']} ({diff} missing)"
            )

    results["issues"] = issues
    results["passed"] = len(issues) == 0

    return results


def print_results(results: dict):
    """Print validation results for a drive/setlist."""
    name = results["name"]
    if results["setlist"]:
        name = f"{name}/{results['setlist']}"

    pct = results["status_percent"]
    synced = results["status_synced"]
    total = results["status_total"]
    disk = results["disk_charts"]

    if results["passed"]:
        # Compact format for passing - mirrors sync.py UI
        if pct == 100:
            print(f"  {name}: {pct:.0f}% ({synced}/{total}) ✓")
        else:
            print(f"  {name}: {pct:.1f}% ({synced}/{total}) ✓")
    else:
        # Expanded format for failures
        print(f"\n{'=' * 60}")
        print(f"  {name}: MISMATCH")
        print(f"{'=' * 60}")
        print(f"  Status reports: {synced}/{total} ({pct:.1f}%)")
        print(f"  Disk reality:   {disk} charts")
        for issue in results["issues"]:
            print(f"  [!] {issue}")


def print_drive_summary(drive_name: str, results: list[dict]):
    """Print consolidated summary for a drive's setlists."""
    passed = [r for r in results if r["passed"]]
    failed = [r for r in results if not r["passed"]]

    total_synced = sum(r["status_synced"] for r in results)
    total_expected = sum(r["status_total"] for r in results)
    pct = (total_synced / total_expected * 100) if total_expected > 0 else 0

    if failed:
        # Show failures
        for r in failed:
            print_results(r)
    else:
        # All passed - show compact summary
        if pct == 100:
            print(f"  {drive_name}: {pct:.0f}% ({total_synced}/{total_expected}) - {len(passed)} setlists ✓")
        else:
            print(f"  {drive_name}: {pct:.1f}% ({total_synced}/{total_expected}) - {len(passed)} setlists ✓")


def main():
    parser = argparse.ArgumentParser(
        description="Validate sync status matches reality",
        epilog="Compares manifest (truth) vs status (reported) vs disk (reality)"
    )
    parser.add_argument("--drive", help="Drive name to validate")
    parser.add_argument("--setlist", help="Setlist name within drive")
    parser.add_argument("--all", action="store_true", help="Validate all enabled drives")
    parser.add_argument("--deep", action="store_true", help="Check each setlist individually (with --all)")
    parser.add_argument("--failfast", action="store_true", help="Stop at first failure")
    args = parser.parse_args()

    # Always fetch fresh manifest
    print("Fetching manifest from GitHub...")
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

    # Load settings
    settings_path = get_settings_path()
    if settings_path.exists():
        settings = UserSettings.load(settings_path)
    else:
        settings = UserSettings()

    base_path = get_download_path()

    # Determine what to validate
    if args.all:
        # Validate all enabled drives (and optionally each setlist)
        all_results = []
        for folder in folders:
            if not settings.is_drive_enabled(folder.get("folder_id")):
                continue

            if args.deep:
                # Check each setlist individually
                setlists = get_setlists_from_manifest(folder)
                for setlist_name, _ in setlists:
                    results = validate_drive(folder, base_path, sync_state, settings, setlist_name)
                    all_results.append(results)
                    print_results(results)
                    if args.failfast and not results["passed"]:
                        print(f"\nStopped at first failure (--failfast)")
                        return 1
            else:
                # Check drive as a whole
                results = validate_drive(folder, base_path, sync_state, settings)
                all_results.append(results)
                print_results(results)
                if args.failfast and not results["passed"]:
                    print(f"\nStopped at first failure (--failfast)")
                    return 1
    elif args.drive:
        # Find drive by name
        folder = next((f for f in folders if f.get("name") == args.drive), None)
        if not folder:
            print(f"Drive '{args.drive}' not found in manifest.")
            print("\nAvailable drives:")
            for f in folders:
                print(f"  - {f.get('name')}")
            return 1

        results = validate_drive(folder, base_path, sync_state, settings, args.setlist)
        print_results(results)
        all_results = [results]
    else:
        # Interactive mode
        folder, setlist, deep, failfast = interactive_select(manifest, settings)

        all_results = []

        if folder is None:
            # Validate all enabled drives
            for f in folders:
                if not settings.is_drive_enabled(f.get("folder_id")):
                    continue

                drive_name = f.get("name", "unknown")

                if deep:
                    # Collect results for this drive (only enabled setlists)
                    drive_results = []
                    setlists = get_setlists_from_manifest(f)
                    disabled = settings.get_disabled_subfolders(f.get("folder_id", ""))
                    for setlist_name, _ in setlists:
                        if setlist_name in disabled:
                            continue  # Skip disabled setlists
                        results = validate_drive(f, base_path, sync_state, settings, setlist_name)
                        drive_results.append(results)
                        all_results.append(results)
                        if failfast and not results["passed"]:
                            print_results(results)
                            print(f"\nStopped at first failure.")
                            return 1
                    # Print consolidated summary for this drive
                    if drive_results:
                        print_drive_summary(drive_name, drive_results)
                else:
                    results = validate_drive(f, base_path, sync_state, settings)
                    all_results.append(results)
                    print_results(results)
                    if failfast and not results["passed"]:
                        print(f"\nStopped at first failure.")
                        return 1
        elif setlist:
            # Single setlist
            results = validate_drive(folder, base_path, sync_state, settings, setlist)
            all_results.append(results)
            print_results(results)
        else:
            # Single drive, optionally deep
            if deep:
                drive_name = folder.get("name", "unknown")
                drive_results = []
                setlists = get_setlists_from_manifest(folder)
                disabled = settings.get_disabled_subfolders(folder.get("folder_id", ""))
                for setlist_name, _ in setlists:
                    if setlist_name in disabled:
                        continue  # Skip disabled setlists
                    results = validate_drive(folder, base_path, sync_state, settings, setlist_name)
                    drive_results.append(results)
                    all_results.append(results)
                    if failfast and not results["passed"]:
                        print_results(results)
                        print(f"\nStopped at first failure.")
                        return 1
                if drive_results:
                    print_drive_summary(drive_name, drive_results)
            else:
                results = validate_drive(folder, base_path, sync_state, settings)
                all_results.append(results)
                print_results(results)

    # Summary
    print(f"\n{'=' * 60}")
    passed = sum(1 for r in all_results if r["passed"])
    failed = len(all_results) - passed

    if failed == 0:
        print(f"All {passed} check(s) passed. Status reports match reality.")
        return 0
    else:
        print(f"{failed} check(s) failed, {passed} passed.")
        print("The app is reporting incorrect sync status.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
