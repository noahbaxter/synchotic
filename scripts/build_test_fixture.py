#!/usr/bin/env python3
"""Resolve the pinned fixture IDs against Drive and fill in md5/modified/size.

Metadata only, no file bytes. Run when a pinned ID goes stale.
See docs/downloads.md for the tier model.
"""

import argparse
import json
import os
import sys
from pathlib import Path
from pathlib import Path as pathlib_Path

REPO = Path(__file__).resolve().parent.parent
FIXTURE = REPO / "tests" / "manual" / "fixture_drive.json"

sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _env_loader import load_env  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=FIXTURE)
    args = parser.parse_args()

    env_path = load_env(REPO)
    api_key = os.environ.get("GOOGLE_API_KEY", "")
    if not api_key:
        print(f"no GOOGLE_API_KEY (env file: {env_path or 'none found'})")
        return 2

    from src.drive.client import DriveClient, DriveClientConfig

    client = DriveClient(DriveClientConfig(api_key=api_key))
    data = json.loads(args.fixture.read_text())

    stale = []
    for entry in data["files"]:
        meta = client.get_file_metadata(
            entry["id"], fields="id,name,size,md5Checksum,modifiedTime"
        )
        if not meta:
            stale.append(entry)
            print(f"  STALE  {entry['id']}  {entry['name']}")
            continue

        old_size = entry.get("size", 0)
        entry["size"] = int(meta.get("size", 0))
        entry["md5"] = meta.get("md5Checksum", "")
        entry["modified"] = meta.get("modifiedTime", "")
        drive_name = meta.get("name", entry["name"])
        entry["name"] = drive_name
        if drive_name != pathlib_Path(entry["path"]).name:
            print(f"  WARN   path basename {pathlib_Path(entry['path']).name!r} "
                  f"!= drive name {drive_name!r}; harness matches on path")

        drift = "" if old_size == entry["size"] else f"  (was {old_size})"
        print(f"  ok     {entry['size']:>12,} B  {entry['name']}{drift}")

    args.fixture.write_text(json.dumps(data, indent=2) + "\n")
    try:
        shown = args.fixture.relative_to(REPO)
    except ValueError:
        shown = args.fixture
    print(f"\nwrote {shown}")

    if stale:
        print(f"\n{len(stale)} pinned id(s) no longer resolve. Pick replacements from")
        print("anon_failure_results.json (outcome=virus_scan for blocked, ok for loose).")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
