#!/usr/bin/env python3
"""Release gate for the four auth modes, run against real Drive in a temp root.

Syncs a pinned 4-file fixture (one 26 MB virus-scan-blocked archive, three tiny
loose files), then asserts which tier delivered what, that a re-sync wants
nothing, and that purge deletes nothing.

  scripts/manual_auth_test.py --mode anonymous
  scripts/manual_auth_test.py --mode rclone --keep /tmp/sc-authtest

See AUTH_TEST_HARNESS_DESIGN.md.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FIXTURE = REPO / "tests" / "manual" / "fixture_drive.json"

# sign_in:      harness runs the interactive OAuth flow before syncing
# allow_rclone: if False, the rclone tier is stubbed out so a tier-2 failure
#               surfaces instead of being silently rescued by tier 4
MODES = {
    "anonymous": {"sign_in": False, "allow_rclone": False, "blocked_tier": None,
                  "token": False, "creds": False, "rclone_dir": False},
    "oauth":     {"sign_in": True,  "allow_rclone": False, "blocked_tier": "oauth",
                  "token": True,  "creds": False, "rclone_dir": False},
    "byoc":      {"sign_in": True,  "allow_rclone": False, "blocked_tier": "oauth",
                  "token": True,  "creds": True,  "rclone_dir": False},
    "rclone":    {"sign_in": False, "allow_rclone": True,  "blocked_tier": "rclone",
                  "token": False, "creds": False, "rclone_dir": True},
}

TIER_RE = re.compile(r"TIER \| (anonymous|oauth|rclone) \| (.+)$")


sys.path.insert(0, str(Path(__file__).resolve().parent))
from _env_loader import load_env  # noqa: E402
from _harness import bootstrap, stub_rclone  # noqa: E402


def reset_root(data_dir: Path, mode: str, keep: bool = False) -> None:
    """Clear auth artifacts so each mode starts from the state it claims to test.

    With keep, the rclone setup survives. Caching the binary and the consent is
    the whole point of --keep, and wiping it leaves a repeat run unable to
    re-verify tier 4.
    """
    for name in ("token.json", "credentials.json"):
        (data_dir / name).unlink(missing_ok=True)
    if not keep:
        shutil.rmtree(data_dir / "rclone", ignore_errors=True)
    if mode != "byoc":
        os.environ.pop("SYNCHOTIC_OAUTH_CLIENT_ID", None)
        os.environ.pop("SYNCHOTIC_OAUTH_CLIENT_SECRET", None)


def build_folder(fixture_mode: str, shortcut_id: str, client) -> tuple[dict, list[dict]]:
    """Return (folder dict for sync_folder, fixture entries with 'expect')."""
    spec = json.loads(FIXTURE.read_text())
    entries = spec["files"]

    if fixture_mode == "pinned":
        files = [{k: v for k, v in e.items() if k != "expect"} for e in entries]
        return {"name": spec["name"], "folder_id": spec["folder_id"], "files": files}, entries

    from src.drive.scanner import FolderScanner

    result = FolderScanner(client).scan(shortcut_id, "")
    print(f"  scanned {len(result.files)} files, {result.folder_count} folders, "
          f"{result.shortcut_count} shortcuts, {result.api_calls} api calls")
    if result.shortcut_count == 0:
        print("  WARNING: 0 shortcuts resolved. File shortcuts at the drive root are")
        print("  invisible to setlist discovery (background_scanner.py:374-375).")

    # Match scanned files back to the fixture by id so 'expect' still applies.
    by_id = {e["id"]: e for e in entries}
    matched = [by_id[f["id"]] for f in result.files if f["id"] in by_id]
    return {"name": spec["name"], "folder_id": shortcut_id, "files": result.files}, matched


def parse_tiers(log_path: Path, start_offset: int = 0) -> dict[str, str]:
    """Map delivered filename -> tier, from TIER lines written after start_offset.

    The offset matters. The daily log is appended across runs, so parsing the
    whole file makes a no-op run inherit the previous run's TIER lines and report
    passes for files it never touched.
    """
    if not log_path.exists():
        return {}
    tiers = {}
    with open(log_path, "r", errors="replace") as f:
        f.seek(start_offset)
        for line in f:
            m = TIER_RE.search(line)
            if m:
                tiers[m.group(2).strip()] = m.group(1)
    return tiers


def rclone_procs() -> list[str]:
    try:
        out = subprocess.run(["ps", "ax", "-o", "pid=,command="],
                             capture_output=True, text=True, timeout=10).stdout
    except Exception:
        return []
    return [l.strip() for l in out.splitlines()
            if "rclone" in l and "manual_auth_test" not in l]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mode", required=True, choices=sorted(MODES))
    parser.add_argument("--fixture", default="pinned", choices=["pinned", "shortcut"])
    parser.add_argument("--shortcut-folder-id", default="",
                        help="Drive folder id for --fixture shortcut")
    parser.add_argument("--keep", type=Path,
                        help="reuse this root instead of mkdtemp, preserving rclone "
                             "binary and consent so a repeat run skips the browser")
    parser.add_argument("--refetch", action="store_true",
                        help="wipe downloaded files and markers but keep auth, so a "
                             "--keep run re-downloads. this is how you test rate-limit "
                             "repeatability without re-consenting each time")
    args = parser.parse_args()

    cfg = MODES[args.mode]
    if args.fixture == "shortcut" and not args.shortcut_folder_id:
        print("--fixture shortcut needs --shortcut-folder-id")
        return 2

    env_path = load_env(REPO)
    if not os.environ.get("GOOGLE_API_KEY"):
        print(f"no GOOGLE_API_KEY (env file: {env_path or 'none found'})")
        return 2

    root = bootstrap(REPO, args.keep)

    from src.config import UserSettings
    from src.core.logging import TeeOutput
    from src.core.paths import (get_data_dir, get_download_path, get_settings_path,
                                get_token_path)
    from src.drive.auth import AuthManager
    from src.drive.client import DriveClient, DriveClientConfig
    from src.sync.download_planner import plan_downloads
    from src.sync.folder_sync import FolderSync
    from src.sync.purge_planner import plan_purge

    data_dir = get_data_dir()
    print(f"root:    {root}")
    print(f"mode:    {args.mode}   fixture: {args.fixture}")

    reset_root(data_dir, args.mode, keep=bool(args.keep))
    if args.refetch:
        shutil.rmtree(get_download_path(), ignore_errors=True)
        shutil.rmtree(data_dir / "markers", ignore_errors=True)
        print("refetch: cleared downloads and markers, auth preserved")

    if cfg["creds"] and not (data_dir / "credentials.json").exists() \
            and not os.environ.get("SYNCHOTIC_OAUTH_CLIENT_ID"):
        print(f"\nbyoc mode needs your own client. Drop credentials.json in {data_dir}")
        print("or export SYNCHOTIC_OAUTH_CLIENT_ID / _SECRET. See docs/byoc.md.")
        return 2

    client = DriveClient(DriveClientConfig(api_key=os.environ["GOOGLE_API_KEY"]))
    folder, entries = build_folder(args.fixture, args.shortcut_folder_id, client)

    settings = UserSettings.load(get_settings_path())
    settings.set_drive_enabled(folder["folder_id"], True)
    settings.save()

    auth = AuthManager(token_path=get_token_path())
    if cfg["sign_in"]:
        print("\nsigning in, a browser will open")
        if not auth.sign_in():
            print("sign-in failed")
            return 1

    if not cfg["allow_rclone"]:
        stub_rclone()
    else:
        print("\nrclone consent will open a browser on the first blocked file")

    download_path = get_download_path()
    logs_dir = data_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / f"{datetime.now().strftime('%Y-%m-%d')}.log"

    # debug_log is a no-op unless sys.stdout is a TeeOutput (core/logging.py:82-87),
    # so without this the TIER lines never reach the log and every check below fails.
    log_offset = log_path.stat().st_size if log_path.exists() else 0
    real_stdout = sys.stdout
    tee = TeeOutput(log_path, version="authtest")
    sys.stdout = tee
    try:
        sync = FolderSync(client, auth_token=auth.get_token_getter(), delete_videos=True)
        downloaded, skipped, errors, rate_limited, cancelled, sync_bytes = \
            sync.sync_folder(folder, download_path)

        tasks_after, _, _ = plan_downloads(
            folder["files"], download_path / folder["name"], True, folder_name=folder["name"]
        )
        purge_after, _ = plan_purge([folder], download_path, settings, None)
    finally:
        sys.stdout = real_stdout
        tee.close()

    tiers = parse_tiers(log_path, log_offset)
    procs = rclone_procs()
    checks: list[tuple[str, str]] = []

    # A run that fetched nothing because everything was already on disk cannot
    # verify which tier delivers what. Report that instead of a stale verdict.
    no_op = downloaded == 0 and skipped > 0

    def verdict(cond: bool) -> str:
        return "PASS" if cond else "FAIL"

    for e in entries:
        got = tiers.get(e["name"])
        if no_op:
            checks.append(("SKIP",
                           f"{e['name']}: nothing fetched this run (already synced)"))
        elif e["expect"] == "ok":
            checks.append((verdict(got == "anonymous"),
                           f"{e['name']}: anonymous (got {got or 'not delivered'})"))
        elif cfg["blocked_tier"] is None:
            checks.append((verdict(got is None),
                           f"{e['name']}: correctly not delivered (got {got or 'nothing'})"))
        else:
            checks.append((verdict(got == cfg["blocked_tier"]),
                           f"{e['name']}: {cfg['blocked_tier']} (got {got or 'not delivered'})"))

    # In anonymous mode the blocked file never lands, so a re-sync correctly still
    # wants it. Every other mode must reach a fully-synced state.
    want = (sum(1 for e in entries if e["expect"] == "blocked")
            if cfg["blocked_tier"] is None else 0)
    checks.append((verdict(len(tasks_after) == want),
                   f"re-sync wants {want} files (wants {len(tasks_after)})"))
    checks.append((verdict(not purge_after), f"purge deletes 0 files (wants {len(purge_after)})"))
    checks.append((verdict(not procs), f"no orphan rclone process ({len(procs)} found)"))
    checks.append((verdict((data_dir / "token.json").exists() == cfg["token"]),
                   f"token.json present={cfg['token']}"))
    checks.append((verdict((data_dir / "rclone").exists() == cfg["rclone_dir"]),
                   f"rclone/ present={cfg['rclone_dir']}"))
    if not cancelled:
        checks.append(("PASS", "sync ran to completion"))

    used = (f"{sync_bytes / 1e6:.1f} MB" if sync_bytes >= 1e6
            else f"{sync_bytes / 1e3:.1f} KB")
    print(f"\ndownloaded={downloaded} skipped={skipped} errors={errors} "
          f"rate_limited={len(rate_limited)} bytes={used}")
    print()
    for status, label in checks:
        print(f"  {status}  {label}")

    failed = [c for c in checks if c[0] == "FAIL"]
    skips = [c for c in checks if c[0] == "SKIP"]
    print(f"\n{len(checks) - len(failed) - len(skips)}/{len(checks)} passed, "
          f"{len(failed)} failed, {len(skips)} skipped, {used} used")
    if skips:
        print("this run fetched nothing, so tier checks proved nothing. "
              "drop --keep for a fresh root to actually re-verify.")
    print(f"log: {log_path}")
    if not args.keep:
        print(f"temp root left in place for inspection: {root}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
