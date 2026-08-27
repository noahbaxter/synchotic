#!/usr/bin/env python3
"""Prove a branch downloads exactly what dev downloads.

The trust invariant (re-sync wants 0, purge deletes 0) says the files we got are
respected. It says nothing about whether we got the same files as before. This
does: sync the identical fixture under two checkouts, hash both trees, diff.

  scripts/parity_check.py --snapshot /tmp/dev.json    --repo ../../synchotic
  scripts/parity_check.py --snapshot /tmp/branch.json --repo .
  scripts/parity_check.py --compare  /tmp/dev.json /tmp/branch.json

The fixture is always read from THIS script's tree, so both runs get identical
input and any difference is attributable to the code.
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
REPO = SCRIPTS.parent
FIXTURE = REPO / "tests" / "manual" / "fixture_drive.json"

sys.path.insert(0, str(SCRIPTS))
from _env_loader import load_env  # noqa: E402
from _harness import (bootstrap, diff_snapshots, fixture_folder, load_fixture,  # noqa: E402
                      snapshot_markers, snapshot_tree, stub_rclone)


def take_snapshot(repo: Path, out_path: Path) -> int:
    spec = load_fixture(FIXTURE)
    load_env(REPO)
    root = bootstrap(repo)

    from src.core.logging import TeeOutput
    from src.core.paths import get_data_dir, get_download_path
    from src.drive.auth import AuthManager
    from src.drive.client import DriveClient, DriveClientConfig
    from src.sync.download_planner import plan_downloads
    from src.sync.folder_sync import FolderSync
    from src.sync.purge_planner import plan_purge

    import os
    if not os.environ.get("GOOGLE_API_KEY"):
        print("no GOOGLE_API_KEY")
        return 2

    # dev has no tier 4, so measure the branch with it off or the trees are not
    # comparable. Absent on branches predating the rclone tier.
    try:
        stub_rclone()
    except ImportError:
        pass

    data_dir = get_data_dir()
    download_path = get_download_path()
    folder = fixture_folder(spec)

    logs = data_dir / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    log_path = logs / f"{datetime.now().strftime('%Y-%m-%d')}.log"

    client = DriveClient(DriveClientConfig(api_key=os.environ["GOOGLE_API_KEY"]))
    auth = AuthManager()

    real_stdout = sys.stdout
    tee = TeeOutput(log_path, version="parity")
    sys.stdout = tee
    try:
        sync = FolderSync(client, auth_token=auth.get_token_getter(), delete_videos=True)
        downloaded, skipped, errors, rate_limited, cancelled, sync_bytes = \
            sync.sync_folder(folder, download_path)
        tasks_after, _, _ = plan_downloads(
            folder["files"], download_path / folder["name"], True,
            folder_name=folder["name"],
        )
        purge_after, _ = plan_purge([folder], download_path, None, None)
    finally:
        sys.stdout = real_stdout
        tee.close()

    snap = {
        "repo": str(Path(repo).resolve()),
        "root": str(root),
        "tree": snapshot_tree(download_path),
        "markers": snapshot_markers(data_dir, download_path),
        "counts": {
            "downloaded": downloaded, "skipped": skipped, "errors": errors,
            "rate_limited": len(rate_limited), "cancelled": cancelled,
            "bytes": sync_bytes,
        },
        "resync_wants": len(tasks_after),
        "purge_wants": len(purge_after),
    }
    out_path.write_text(json.dumps(snap, indent=2) + "\n")

    print(f"repo:     {snap['repo']}")
    print(f"files:    {len(snap['tree'])}  markers: {len(snap['markers'])}")
    print(f"counts:   {snap['counts']}")
    print(f"re-sync wants {snap['resync_wants']}, purge wants {snap['purge_wants']}")
    print(f"wrote {out_path}")
    return 0


def compare(a_path: Path, b_path: Path) -> int:
    a = json.loads(a_path.read_text())
    b = json.loads(b_path.read_text())
    la, lb = "A", "B"

    print(f"A: {a['repo']}\nB: {b['repo']}\n")
    print(f"A: {len(a['tree'])} files, {len(a['markers'])} markers, "
          f"resync_wants={a['resync_wants']}, purge_wants={a['purge_wants']}")
    print(f"B: {len(b['tree'])} files, {len(b['markers'])} markers, "
          f"resync_wants={b['resync_wants']}, purge_wants={b['purge_wants']}\n")

    problems = diff_snapshots(a["tree"], b["tree"], la, lb)

    only_a = sorted(set(a["markers"]) - set(b["markers"]))
    only_b = sorted(set(b["markers"]) - set(a["markers"]))
    problems += [f"marker missing from {lb}: {m}" for m in only_a]
    problems += [f"marker extra in {lb}: {m}" for m in only_b]

    if a["resync_wants"] != b["resync_wants"]:
        problems.append(f"re-sync disagreement: A wants {a['resync_wants']}, "
                        f"B wants {b['resync_wants']}")
    if a["purge_wants"] != b["purge_wants"]:
        problems.append(f"purge disagreement: A wants {a['purge_wants']}, "
                        f"B wants {b['purge_wants']}")

    if problems:
        print(f"FAIL, {len(problems)} difference(s):")
        for p in problems:
            print(f"  {p}")
        return 1
    print(f"PASS, identical trees ({len(a['tree'])} files), markers, and planner verdicts")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--snapshot", type=Path, help="write a snapshot here")
    parser.add_argument("--repo", type=Path, help="checkout to run (with --snapshot)")
    parser.add_argument("--compare", nargs=2, type=Path, metavar=("A", "B"))
    args = parser.parse_args()

    if args.compare:
        return compare(*args.compare)
    if args.snapshot:
        if not args.repo:
            print("--snapshot needs --repo")
            return 2
        return take_snapshot(args.repo, args.snapshot)
    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
