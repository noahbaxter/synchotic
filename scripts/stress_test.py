#!/usr/bin/env python3
"""Sync one real setlist and prove its markers describe what they extracted.

Multi-archive setlists are the shape that breaks marker attribution. A game like
Rock Band Rivals is ~25 archives that all extract into the SAME folder, and
marker backfill attributes every file under an extraction folder to the archive
being processed. On a real install that produced 84 Rock Band 2 markers all
claiming the same 10 files, which leaves the rest of the setlist claimed by
nobody and therefore purgeable.

  scripts/stress_test.py                          Rock Band Rivals (0.7 GB)
  scripts/stress_test.py --setlist "(2012) Rock Band Blitz"

Asserts, after a real sync:
  * every archive gets a marker
  * sibling archives do not claim each other's files
  * every extracted file on disk is claimed by exactly one marker
  * re-sync wants 0 and purge wants 0
"""

import argparse
import collections
import os
import sys
from datetime import datetime
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
REPO = SCRIPTS.parent
DRIVE_NAME = "Rock Band"
DRIVE_ID = "1jUnIkQ3k6j3vnMxxIAfyOewNB10Tygb8"

sys.path.insert(0, str(SCRIPTS))
from _env_loader import load_env  # noqa: E402
from _harness import bootstrap, stub_rclone  # noqa: E402


def build_folder(client, setlist: str) -> dict:
    """The folder dict sync_folder expects, for one real setlist.

    Entries under the drive are Drive shortcuts, not folders, so the target has
    to be resolved before anything can be listed.
    """
    items = client.list_folder(DRIVE_ID)
    match = [i for i in items if i["name"] == setlist]
    if not match:
        raise SystemExit(f"no setlist named {setlist!r}")
    target = (match[0].get("shortcutDetails") or {}).get("targetId") or match[0]["id"]

    files = []
    for k in client.list_folder(target):
        if k.get("mimeType", "").endswith("folder"):
            continue
        files.append({
            "id": k["id"],
            "path": f"{setlist}/{k['name']}",
            "name": k["name"],
            "size": int(k.get("size", 0) or 0),
            "md5": k.get("md5Checksum", ""),
            "modified": k.get("modifiedTime", ""),
        })
    return {"name": DRIVE_NAME, "folder_id": DRIVE_ID, "files": files}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--setlist", default="(2016) Rock Band Rivals")
    ap.add_argument("--root", type=Path, help="sandbox to reuse (default: temp)")
    args = ap.parse_args()

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
    from src.sync.folder_sync import FolderSync
    from src.sync.markers import get_all_markers
    from src.sync.purge_planner import plan_purge

    stub_rclone()
    client = DriveClient(DriveClientConfig(api_key=os.environ["GOOGLE_API_KEY"]))
    folder = build_folder(client, args.setlist)
    archives = [f for f in folder["files"]
                if f["name"].lower().endswith((".7z", ".zip", ".rar"))]
    gb = sum(f["size"] for f in folder["files"]) / 1e9
    print(f"{args.setlist}: {len(folder['files'])} files, {len(archives)} archives, {gb:.2f} GB")

    base = get_download_path()
    logs = get_data_dir() / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    log_path = logs / f"{datetime.now().strftime('%Y-%m-%d')}.log"

    auth = AuthManager()
    real_stdout = sys.stdout
    tee = TeeOutput(log_path, version="stress")
    sys.stdout = tee
    try:
        sync = FolderSync(client, auth_token=auth.get_token_getter(), delete_videos=True)
        downloaded, skipped, errors, rate_limited, cancelled, _ = \
            sync.sync_folder(folder, base)
        tasks_after, _, _ = plan_downloads(
            folder["files"], base / DRIVE_NAME, True, folder_name=DRIVE_NAME)
        purge_after, _ = plan_purge([folder], base, None, None)
    finally:
        sys.stdout = real_stdout
        tee.close()

    print(f"downloaded={downloaded} skipped={skipped} errors={errors} "
          f"rate_limited={len(rate_limited)}")

    problems = []
    marked = {m.get("archive_path", ""): set(m.get("files", {}))
              for m in get_all_markers() if m.get("archive_path")}

    for a in archives:
        key = f"{DRIVE_NAME}/{a['path']}"
        if key not in marked:
            problems.append(f"archive has no marker: {a['path']}")

    claims = collections.Counter()
    for files in marked.values():
        claims.update(files)
    shared = [f for f, n in claims.items() if n > 1]
    if shared:
        problems.append(f"{len(shared)} file(s) claimed by more than one archive, "
                        f"e.g. {shared[0]}")

    if tasks_after:
        problems.append(f"re-sync still wants {len(tasks_after)} file(s)")
    if purge_after:
        problems.append(f"purge wants {len(purge_after)} file(s) after a clean sync")

    print(f"\nroot: {root}")
    print(f"markers: {len(marked)}  distinct files claimed: {len(claims)}")
    if problems:
        print(f"FAIL, {len(problems)} problem(s):")
        for p in problems:
            print(f"  {p}")
        return 1
    print(f"PASS, {len(archives)} archives each claim their own files, "
          f"re-sync wants 0, purge wants 0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
