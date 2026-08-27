#!/usr/bin/env python3
"""Prove a cancelled sync resumes to a complete, purge-safe state.

Cancel mid-download is the data-integrity path most at risk from the chotic-ui
toolkit swap, which deleted esc_monitor.py. A cancel that leaves half-written
files behind means purge either deletes real data or leaves junk that never
reconciles.

  1. clean full sync in root A            -> reference tree
  2. sync in root B, cancel mid-archive   -> partial state
  3. sync B again, no cancel              -> must converge on A
  4. B must want 0 purges and hold no partial files

Each phase runs in its own process. src/sync/cache.py keeps module-level
singletons (`_persistent_stats_cache`, `_cache`) that would otherwise carry root
A's paths into root B and quietly invalidate the comparison.

Covers the sync-side handling of cancellation. It does NOT cover ESC key
detection itself, which needs a real terminal. See TESTING_AUTH.md.
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
REPO = SCRIPTS.parent
FIXTURE = REPO / "tests" / "manual" / "fixture_drive.json"

sys.path.insert(0, str(SCRIPTS))
from _env_loader import load_env  # noqa: E402
from _harness import (bootstrap, diff_snapshots, fixture_folder, load_fixture,  # noqa: E402
                      snapshot_tree, stub_rclone)

# downloader.py:515 polls cancel_check every 0.1s inside the `while pending` loop.
# Keying on bytes-on-disk does not work: writes are buffered, so the bytes only
# appear once the download has essentially finished, and the cancel lands too late
# to interrupt anything.
#
# Useful window on a ~7 MB archive: poll 2 interrupts before anything lands, poll
# 12 interrupts with the loose files done and the archive partial (the case worth
# testing), poll 25+ is after everything finished and the run proves nothing. The
# incomplete-tree check exists to catch that last case.
DEFAULT_CANCEL_ON_POLL = 12


def run_phase(phase: str, root: Path, out: Path, cancel_on_poll: int) -> int:
    """One sync in one process. Writes a snapshot JSON."""
    load_env(REPO)
    if not os.environ.get("GOOGLE_API_KEY"):
        print("no GOOGLE_API_KEY")
        return 2

    bootstrap(REPO, root)
    stub_rclone()  # else a blocked file parks this run in rclone consent forever
    spec = load_fixture(FIXTURE)
    folder = fixture_folder(spec)

    from src.core.logging import TeeOutput
    from src.core.paths import get_data_dir, get_download_path
    from src.drive.auth import AuthManager
    from src.drive.client import DriveClient, DriveClientConfig
    from src.sync.folder_sync import FolderSync
    from src.sync.purge_planner import find_partial_downloads, plan_purge

    data_dir = get_data_dir()
    download_path = get_download_path()
    logs = data_dir / "logs"
    logs.mkdir(parents=True, exist_ok=True)

    polls = {"n": 0}

    def cancel_check() -> bool:
        polls["n"] += 1
        return polls["n"] >= cancel_on_poll

    client = DriveClient(DriveClientConfig(api_key=os.environ["GOOGLE_API_KEY"]))
    auth = AuthManager()

    real_stdout = sys.stdout
    tee = TeeOutput(logs / f"{datetime.now().strftime('%Y-%m-%d')}.log", version=phase)
    sys.stdout = tee
    try:
        sync = FolderSync(client, auth_token=auth.get_token_getter(), delete_videos=True)
        downloaded, skipped, errors, rate_limited, cancelled, sync_bytes = sync.sync_folder(
            folder, download_path,
            cancel_check=cancel_check if phase == "cancel" else None,
        )
        purge_wants, _ = plan_purge([folder], download_path, None, None)
        partials = find_partial_downloads(download_path)
    finally:
        sys.stdout = real_stdout
        tee.close()

    out.write_text(json.dumps({
        "phase": phase,
        "tree": snapshot_tree(download_path),
        "downloaded": downloaded, "errors": errors, "cancelled": cancelled,
        "purge_wants": len(purge_wants), "partials": len(partials),
    }, indent=2) + "\n")
    print(f"  {phase}: downloaded={downloaded} errors={errors} cancelled={cancelled} "
          f"purge_wants={len(purge_wants)} partials={len(partials)}")
    return 0


def spawn(phase: str, root: Path, out: Path, cancel_on_poll: int) -> None:
    subprocess.run(
        [sys.executable, str(Path(__file__).resolve()),
         "--phase", phase, "--root", str(root), "--out", str(out),
         "--cancel-on-poll", str(cancel_on_poll)],
        check=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--phase", choices=["reference", "cancel", "resume"])
    parser.add_argument("--root", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--cancel-on-poll", type=int, default=DEFAULT_CANCEL_ON_POLL,
                        help="fire cancel on this poll of cancel_check (0.1s apart). "
                             "low = interrupt before anything lands, higher = "
                             "interrupt with completed files and a partial one")
    args = parser.parse_args()

    if args.phase:
        return run_phase(args.phase, args.root, args.out, args.cancel_on_poll)

    tmp = Path(tempfile.mkdtemp(prefix="synchotic-cancel-"))
    root_a, root_b = tmp / "a", tmp / "b"
    snaps = {p: tmp / f"{p}.json" for p in ("reference", "cancel", "resume")}

    print(f"A (reference): {root_a}")
    spawn("reference", root_a, snaps["reference"], args.cancel_on_poll)
    print(f"\nB (cancel then resume): {root_b}")
    spawn("cancel", root_b, snaps["cancel"], args.cancel_on_poll)
    spawn("resume", root_b, snaps["resume"], args.cancel_on_poll)

    ref = json.loads(snaps["reference"].read_text())
    cancelled = json.loads(snaps["cancel"].read_text())
    resumed = json.loads(snaps["resume"].read_text())

    problems = diff_snapshots(ref["tree"], resumed["tree"], "reference", "resumed")
    checks = [
        (cancelled["cancelled"], "pass 1 actually cancelled (else this proves nothing)"),
        (len(cancelled["tree"]) < len(ref["tree"]),
         f"cancel left an incomplete tree ({len(cancelled['tree'])} of {len(ref['tree'])})"),
        (not problems, f"resumed tree matches reference ({len(ref['tree'])} files)"),
        (resumed["purge_wants"] == 0,
         f"purge wants 0 after resume (wants {resumed['purge_wants']})"),
        (resumed["partials"] == 0,
         f"no partial files after resume ({resumed['partials']} found)"),
    ]

    print()
    for ok, label in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {label}")
    if problems:
        print("\ntree differences:")
        for p in problems:
            print(f"  {p}")

    failed = [c for c in checks if not c[0]]
    print(f"\n{len(checks) - len(failed)}/{len(checks)} passed")
    print(f"artifacts: {tmp}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
