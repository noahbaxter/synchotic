#!/usr/bin/env python3
"""Prove a sync downloads what is new and purge removes what is stale.

The other gates prove a sync converges and matches dev. Neither proves the two
halves of the trust invariant against each other on the same tree:

  1. seed the library with an OLD set nothing claims (a stale pack, a stale
     loose chart, and a leftover partial download)
  2. sync the fixture drive                -> the NEW set must land
  3. purge                                 -> must remove exactly the OLD set
  4. re-sync wants 0, purge wants 0        -> and every NEW file survives

Purge deciding "extra" from markers plus manifest is what makes updated packs
safe and what makes a stranded marker eat real charts, so it is worth exercising
end to end rather than trusting the unit tests on plan_purge alone.
"""

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
REPO = SCRIPTS.parent
FIXTURE = REPO / "tests" / "manual" / "fixture_drive.json"

sys.path.insert(0, str(SCRIPTS))
from _env_loader import load_env  # noqa: E402
from _harness import bootstrap, fixture_folder, load_fixture, stub_rclone  # noqa: E402


def seed_old_set(drive_dir: Path) -> list[Path]:
    """Files no manifest and no marker will ever claim. Purge must take these."""
    old = []

    # Deliberately NOT under a setlist that holds an archive. Marker backfill
    # attributes everything under an extraction folder to that archive, so a
    # stale file there gets adopted and is legitimately protected from purge.
    stale_chart = drive_dir / "02 Loose" / "Stale Pack" / "Old Song"
    stale_chart.mkdir(parents=True, exist_ok=True)
    for name, body in (("song.ini", "[Song]\nname=Old Song\n"),
                       ("notes.chart", "[Song]\n{\n}\n")):
        p = stale_chart / name
        p.write_text(body)
        old.append(p)

    loose = drive_dir / "02 Loose" / "Removed Chart" / "song.ini"
    loose.parent.mkdir(parents=True, exist_ok=True)
    loose.write_text("[Song]\nname=Removed\n")
    old.append(loose)

    partial = drive_dir / "03 Archive" / "_download_leftover.zip"
    partial.parent.mkdir(parents=True, exist_ok=True)
    partial.write_bytes(b"\x00" * 4096)
    old.append(partial)

    return old


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, help="sandbox to reuse (default: temp)")
    args = ap.parse_args()

    spec = load_fixture(FIXTURE)
    load_env(REPO)
    if not os.environ.get("GOOGLE_API_KEY"):
        print("no GOOGLE_API_KEY")
        return 2

    root = bootstrap(REPO, args.root)
    from src.core.logging import TeeOutput
    from src.core.paths import get_data_dir, get_download_path
    from src.drive.auth import AuthManager
    from src.drive.client import DriveClient, DriveClientConfig
    from src.sync.download_planner import plan_downloads
    from src.sync.folder_sync import FolderSync, purge_all_folders
    from src.sync.purge_planner import plan_purge

    stub_rclone()

    folder = fixture_folder(spec)
    base = get_download_path()
    drive_dir = base / folder["name"]
    drive_dir.mkdir(parents=True, exist_ok=True)

    old_files = seed_old_set(drive_dir)
    print(f"seeded OLD set: {len(old_files)} files")

    logs = get_data_dir() / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    log_path = logs / f"{datetime.now().strftime('%Y-%m-%d')}.log"

    client = DriveClient(DriveClientConfig(api_key=os.environ["GOOGLE_API_KEY"]))
    auth = AuthManager()

    real_stdout = sys.stdout
    tee = TeeOutput(log_path, version="newold")
    sys.stdout = tee
    try:
        sync = FolderSync(client, auth_token=auth.get_token_getter(), delete_videos=True)
        downloaded, skipped, errors, rate_limited, cancelled, _ = \
            sync.sync_folder(folder, base)
        planned, _ = plan_purge([folder], base, None, None)
        purge_all_folders([folder], base, None, None)
        tasks_after, _, _ = plan_downloads(
            folder["files"], drive_dir, True, folder_name=folder["name"])
        purge_after, _ = plan_purge([folder], base, None, None)
    finally:
        sys.stdout = real_stdout
        tee.close()

    print(f"downloaded={downloaded} skipped={skipped} errors={errors}")

    problems = []

    # NEW set landed. Archives are extracted and removed, so an archive counts
    # as delivered when a marker claims it, not when the .zip is still on disk.
    from src.sync.markers import find_any_marker_for_path
    for entry in spec["files"]:
        if entry.get("expect") != "ok":
            continue
        rel = entry["path"]
        if rel.lower().endswith((".zip", ".7z", ".rar")):
            if not find_any_marker_for_path(f"{folder['name']}/{rel}"):
                problems.append(f"NEW archive unmarked: {rel}")
        elif not (drive_dir / rel).exists():
            problems.append(f"NEW missing: {rel}")

    # purge targeted exactly the OLD set
    planned_set = {p for p, _ in planned}
    for p in old_files:
        if p not in planned_set:
            problems.append(f"OLD not planned for purge: {p.relative_to(base)}")
    for p in planned_set - set(old_files):
        problems.append(f"purge wanted something NEW: {p.relative_to(base)}")

    # and actually removed it
    for p in old_files:
        if p.exists():
            problems.append(f"OLD survived purge: {p.relative_to(base)}")

    # The blocked fixture file cannot land anonymously with rclone stubbed, so
    # it is expected to remain wanted. Anything else is a convergence failure.
    blocked = {e["path"] for e in spec["files"] if e.get("expect") == "blocked"}
    unexpected = [t for t in tasks_after
                  if not any(b in str(getattr(t, "path", t)) for b in blocked)]
    if unexpected:
        problems.append(f"re-sync still wants {len(unexpected)} unexpected file(s)")
    if purge_after:
        problems.append(f"purge still wants {len(purge_after)} file(s)")

    print(f"\nroot: {root}")
    if problems:
        print(f"FAIL, {len(problems)} problem(s):")
        for p in problems:
            print(f"  {p}")
        return 1
    print(f"PASS, downloaded the new set, removed all {len(old_files)} stale files, "
          f"re-sync wants 0, purge wants 0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
