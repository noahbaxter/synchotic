"""Check a Synchotic source tree on Windows against real Google Drive, in an
isolated test install. Nothing outside --root is touched: the machine's own
install in %LOCALAPPDATA% is never read or written, and the test install,
downloads included, is deleted at the end unless --keep.

Normally run from the Mac with scripts/run_windows_check.sh <host>. On the box:
  python windows_check.py --src C:\\path\\to\\synchotic --root C:\\path\\to\\test-root
         --auth C:\\folder\\with\\token-and-credentials [--budget-mb 900]
         [--library-dir WEIRD|LONG|<path>] [--anonymous] [--keep]
An upgrade: run an older tree with --only setup --keep, then this one with --reuse.

Cases, each PASS or FAIL with what it saw:
  token_race       an expired token refreshed by 16 threads at once: no
                   request goes out without credentials, token.json stays whole
  token_held_open  token.json replaced while a reader holds it open (Windows
                   refuses the swap): the file stays valid
  toggles_kept     (--reuse) the older version's toggles read back as written
  scan             discovery and scan of a few small setlists plus the
                   smallest .zip, .7z and .rar packs of three pack setlists
  sync_first       download and extract them, markers written
  guessed_markers  a pack setlist synced in part still lists the rest
  sync_again       a second sync right after plans no download and no purge;
                   after an upgrade, the new version's first sync runs first
  purge_setlist    one setlist turned off: purge plans exactly its files,
                   deletes them, leaves the rest; turned back on, it returns
  interrupted      a sync cut off mid-download marks nothing done that is not,
                   and the next one finishes and settles
  custom_becomes_shipped  a custom folder that is a shipped setlist stays
                   custom, never turns its drive on, turns only the drive's
                   own copy off, downloads and purges nothing
  found_drives     a switched-off drive with a folder stays off; with purge
                   off nothing is turned on
  one_log          the log folder is the data folder's logs/
  launcher_check   the real launcher-v1.4 exe passes the update check, and
                   only our own launcher names are taken for one
  adoption         an old install's import cut off partway finishes on the
                   next launch (Windows paths, MAX_PATH prefix)
"""

import argparse
import contextlib
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path

# Small setlists seen in the field logs, mostly zip packs plus loose charts.
CANDIDATES = {
    "BirdmanExe Drive": ["BirdmanExe", "Jarod Fedele", "ShadeGH", "PuppetMaster9",
                         "FractalWizz", "TheLieInKing", "Jameos"],
    "Drummer's Monthly Drive": ["bonk", "Anic"],
}

# Setlists of packs. Only a few of the smallest of each kind are synced from
# them, which is what exercises extraction and markers.
ARCHIVE_CANDIDATES = {
    "Rock Band": ["Rock Band 4 DLC", "Rock Band Network"],
    "Misc": ["Joshwantsmaccas"],
}
PACKS_PER_KIND = 3
SUBSET = {}  # setlist key -> the files of it to sync
MODE = ["byoc"]  # the download mode every sync here uses


def skey(s):
    """A setlist's identity, the same on 1.5.6 (no SetlistInfo.key) and later."""
    return f"{s.drive_id}/{s.setlist_id}"

results = []


def case(name):
    def wrap(fn):
        def run(*a, **k):
            t = time.time()
            try:
                detail = fn(*a, **k)
                results.append((name, "PASS", detail or "", time.time() - t))
            except AssertionError as e:
                results.append((name, "FAIL", str(e), time.time() - t))
            except Exception:
                results.append((name, "FAIL", traceback.format_exc(limit=4), time.time() - t))
            print(f"[{results[-1][1]}] {name} ({results[-1][3]:.0f}s) {results[-1][2]}", flush=True)
        return run
    return wrap


class Progress:
    """The sync panel, headless."""
    cancelled = False

    def suspended(self):
        return contextlib.nullcontext()

    def __getattr__(self, name):
        return lambda *a, **k: None


def setup_root(root: Path, auth: Path, library_dir: str = ""):
    """A fresh portable install at root: .dm-sync with the copied sign-in."""
    if root.exists():
        shutil.rmtree("\\\\?\\" + str(root.resolve()))  # may hold paths past MAX_PATH
    data = root / ".dm-sync"
    data.mkdir(parents=True)
    for name in ("token.json", "credentials.json"):
        shutil.copy2(auth / name, data / name)
    library = root / (library_dir or "Sync Charts")
    os.makedirs("\\\\?\\" + str(library.resolve()), exist_ok=True)
    return data, library


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--root", required=True)
    ap.add_argument("--auth", required=True)
    ap.add_argument("--budget-mb", type=int, default=600)
    ap.add_argument("--library-dir", default="",
                    help="library path under --root, to test long or unusual paths")
    ap.add_argument("--keep", action="store_true", help="leave the test install in place")
    ap.add_argument("--reuse", action="store_true",
                    help="start from the test install already at --root (an upgrade)")
    ap.add_argument("--only", default="", help="'setup': scan and sync, nothing else")
    ap.add_argument("--anonymous", action="store_true", help="no sign-in, API key only")
    ap.add_argument("--child", default="")  # internal: run one case in a clean process
    args = ap.parse_args()

    src, root, auth = Path(args.src), Path(args.root), Path(args.auth)
    args.library_dir = {
        "WEIRD": "Clone Hero songs\\Ünïcødé's [D&G] Charts\\Sync Charts",
        "LONG": "L" * 110 + "\\" + "M" * 110 + "\\Sync Charts",
    }.get(args.library_dir, args.library_dir)
    os.environ["SYNCHOTIC_ROOT"] = str(root)
    os.environ["SYNCHOTIC_OS_DIRS"] = "0"
    for k in ("SYNCHOTIC_LIBRARY", "SYNCHOTIC_LEGACY_ROOT"):
        os.environ.pop(k, None)
    sys.path[:0] = [str(src), str(src / "vendor" / "chotic-ui")]
    os.chdir(src)

    if args.child == "adoption":
        return child_adoption(root)

    if args.reuse:
        data, library = root / ".dm-sync", root / (args.library_dir or "Sync Charts")
        assert library.exists(), f"--reuse but no library at {library}"
    else:
        data, library = setup_root(root, auth, args.library_dir)
        if args.anonymous:
            (data / "token.json").unlink()
    print(f"library: {library} ({len(str(library))} chars)", flush=True)
    # The form the app itself uses (paths.get_library_path), so the harness's
    # own walks reach past MAX_PATH where the app's do.
    library = Path("\\\\?\\" + str(library.resolve()))

    from src.config.settings import UserSettings
    from src.core import paths

    settings = UserSettings.load(paths.get_settings_path())
    if not args.reuse:  # an upgrade keeps whatever the old version wrote
        settings.library_path = str(library)
        settings.download_mode = "anonymous" if args.anonymous else "byoc"
        settings.purge_on_sync = True
        settings.save()
    MODE[0] = settings.download_mode or "byoc"
    if args.reuse:
        toggles_kept(paths, settings)
        startup_tagging()
    paths.set_library_path(library)
    assert paths.get_data_dir() == data, f"data dir is {paths.get_data_dir()}, not the test root"

    from src.app.config import API_KEY
    from src.drive import DriveClient
    from src.drive.auth import AuthManager
    from src.drive.client import DriveClientConfig

    auth_mgr = AuthManager(token_path=paths.get_token_path())
    if args.anonymous:
        assert not auth_mgr.get_token(), "anonymous run is signed in"
        assert API_KEY, "anonymous needs the API key from the checkout's .env"
    else:
        assert auth_mgr.get_token(), "not signed in with the copied token"
    client = DriveClient(DriveClientConfig(api_key=API_KEY), auth_token=auth_mgr.get_token_getter())

    # From the checkout: a source run's bundle dir is the test root, which has none.
    from src.config import DrivesConfig
    drives = [d for d in DrivesConfig.load(src / "drives.json").drives if not d.hidden]
    assert drives, "no drives loaded"
    by_name = {d.name: d for d in drives}

    if not args.anonymous and args.only != "setup":
        token_race(paths, client, drives)
        token_held_open(paths)
    state = {}
    scan(settings, auth_mgr, API_KEY, by_name, library, args.budget_mb * 1024 * 1024, state)
    if state.get("scanner"):
        if not args.reuse:
            sync_first(settings, client, auth_mgr, library, state)
        if args.only == "setup":
            return finish(args, root, src)
        guessed_markers(settings, library, state)
        sync_again(settings, client, auth_mgr, library, state, upgraded=args.reuse)
        purge_setlist(settings, client, auth_mgr, library, state)
        interrupted(settings, client, auth_mgr, library, state)
        if not args.anonymous:
            custom_becomes_shipped(settings, client, auth_mgr, library, by_name, API_KEY)
        found_drives(paths, settings, library, by_name, state)
    one_log(paths, data)
    launcher_check(root)

    # In its own process: it points the app at the OS dirs, under the test root.
    child = subprocess.run([sys.executable, __file__, "--src", str(src), "--root", str(root),
                            "--auth", str(auth), "--child", "adoption"],
                           capture_output=True, text=True)
    print(child.stdout.strip(), flush=True)
    passed = "[PASS] adoption" in child.stdout
    results.append(("adoption", "PASS" if passed else "FAIL",
                    "" if passed else (child.stdout + child.stderr)[-1500:], 0))
    finish(args, root, src)


def finish(args, root, src):
    print("\n==== SUMMARY ====")
    for name, status, detail, secs in results:
        print(f"{status:4}  {name}")
    failed = [r for r in results if r[1] != "PASS"]
    print(f"{len(results) - len(failed)}/{len(results)} passed")
    # The test install goes, charts and all: nothing downloaded is kept.
    if args.keep:
        print(f"kept {root}")
    else:
        os.chdir(src)
        shutil.rmtree("\\\\?\\" + str(root.resolve()), ignore_errors=True)
        print(f"removed {root}" if not root.exists() else f"could not fully remove {root}")
    sys.exit(1 if failed else 0)


@case("startup_tagging")
def startup_tagging():
    """What sync.py does at startup on an upgraded library: tag the guesses the
    older version's rebuild wrote untagged. Once, and never a marker of a pack
    that really extracted on its own."""
    from src.sync.markers import GUESSED, flag_guessed_markers, get_markers_dir

    tagged = flag_guessed_markers()
    again = flag_guessed_markers()
    assert again == 0, f"tagged {again} more on a second launch"
    markers = [json.loads(p.read_text()) for p in get_markers_dir().glob("*.json")]
    guessed = sum(1 for m in markers if m.get(GUESSED))
    return f"{tagged} tagged on first launch, 0 on the next; {guessed} of {len(markers)} markers are guesses"


@case("toggles_kept")
def toggles_kept(paths, settings):
    """What the old version wrote is what this one reads."""
    from src.config import jsonc

    raw = jsonc.loads(paths.get_settings_path().read_text(encoding="utf-8-sig"))
    assert settings.drive_toggles == (raw.get("drive_toggles") or {}), "drive toggles changed on load"
    assert settings.subfolder_toggles == (raw.get("subfolder_toggles") or {}), "setlist toggles changed on load"
    assert settings.library_path == raw.get("library_path"), "library path changed on load"
    return (f"{len(settings.drive_toggles)} drive and "
            f"{sum(map(len, settings.subfolder_toggles.values()))} setlist toggles read as written")


@case("token_race")
def token_race(paths, client, drives):
    """Expire the token, then list every drive from 16 threads at once: every
    one refreshes and rewrites token.json while the others read it."""
    import requests
    from concurrent.futures import ThreadPoolExecutor

    assert drives, "no drives to list"
    token_file = paths.get_token_path()
    errors, rounds = [], 3
    for _ in range(rounds):
        data = json.loads(token_file.read_text())
        data["expiry"] = "2000-01-01T00:00:00Z"
        token_file.write_text(json.dumps(data))

        def listing(d):
            try:
                client.list_folder(d.folder_id)
            except requests.exceptions.HTTPError as e:
                errors.append(f"{d.name}: {e.response.status_code} {e.response.text[:120]}")
            except Exception as e:
                errors.append(f"{d.name}: {e!r}")

        with ThreadPoolExecutor(16) as pool:
            list(pool.map(listing, drives * 2))
    json.loads(token_file.read_text())  # still whole
    assert not errors, f"{len(errors)} failed requests: {errors[:3]}"
    return f"{rounds * len(drives) * 2} listings across forced refreshes, 0 failures"


@case("token_held_open")
def token_held_open(paths):
    from src.drive.auth import _write_token

    import threading

    token_file = paths.get_token_path()
    before = json.loads(token_file.read_text())
    after = json.dumps({**before, "windows_check": time.time()})
    # A reader holding it, as another thread would, letting go mid-write.
    reader = open(token_file)
    threading.Timer(0.2, reader.close).start()
    _write_token(token_file, after)
    assert token_file.read_text() == after, "the write was dropped while a reader held the file"
    _write_token(token_file, json.dumps(before))
    leftovers = [p.name for p in token_file.parent.glob(".token.json.*.tmp")]
    assert not leftovers, f"temp files left behind: {leftovers}"
    return "written while a reader held it, no temp files left"


@case("scan")
def scan(settings, auth_mgr, api_key, by_name, library, budget, state):
    from src.sync.background_scanner import BackgroundScanner

    folders = []
    every = {**CANDIDATES, **ARCHIVE_CANDIDATES}
    for drive_name in every:
        d = by_name[drive_name]
        settings.set_drive_enabled(d.folder_id, True)
        folders.append({"name": d.name, "folder_id": d.folder_id, "files": None})
    scanner = BackgroundScanner(folders, auth_mgr, api_key, user_settings=settings,
                                download_path=library)
    scanner.discover()
    # Only the candidates on, every other setlist of these drives off.
    for drive_name, wanted in every.items():
        fid = by_name[drive_name].folder_id
        for name in scanner.get_discovered_setlist_names(fid) or []:
            settings.set_subfolder_enabled(fid, name, name in wanted)
            scanner.notify_setlist_toggled(fid, name, name in wanted)
    settings.save()
    enabled = [s for k, s in scanner.all_setlists.items() if k in scanner._enabled_setlist_ids]
    assert enabled, "none of the candidate setlists exist anymore"
    from src.drive import FolderScanner
    folder_scanner = FolderScanner(scanner._client)
    for s in enabled:
        scanner._scan_setlist(s, folder_scanner)
    assert not scanner.has_scan_failures(), f"scan failed: {scanner.get_failure_reason()}"

    # From the pack setlists, only the smallest few packs of each kind.
    from src.core.formatting import sanitize_drive_name
    for s in enabled:
        if s.name not in ARCHIVE_CANDIDATES.get(s.drive_name, []):
            continue
        prefix = sanitize_drive_name(s.name) + "/"
        files = [f for f in s.drive["files"] if f["path"].startswith(prefix)]
        picked = []
        for ext in (".zip", ".7z", ".rar"):
            packs = sorted((f for f in files if f["path"].lower().endswith(ext) and f.get("size")),
                           key=lambda f: f["size"])
            picked += packs[:PACKS_PER_KIND]
        SUBSET[skey(s)] = picked

    # Keep within budget, smallest first.
    def size(s):
        return sum(f.get("size", 0) for f in _setlist_folder(s)["files"])
    chosen, total = [], 0
    for s in sorted(enabled, key=size):
        if skey(s) in SUBSET and not SUBSET[skey(s)]:
            continue  # no packs in it at all
        if total + size(s) > budget:
            settings.set_subfolder_enabled(s.drive_id, s.name, False)
            scanner.notify_setlist_toggled(s.drive_id, s.name, False)
            continue
        chosen.append(s)
        total += size(s)
    settings.save()
    assert chosen, "every candidate is over budget"
    state.update(scanner=scanner, chosen=chosen, folders=folders)
    kinds = {}
    for s in chosen:
        for f in _setlist_folder(s)["files"]:
            ext = Path(f["path"]).suffix.lower()
            if ext in (".zip", ".7z", ".rar"):
                kinds[ext] = kinds.get(ext, 0) + 1
    assert kinds, "no packs in the chosen setlists, so extraction goes untested"
    archives = ", ".join(f"{n} {ext}" for ext, n in sorted(kinds.items()))
    return (f"{len(chosen)} setlists, {total / 1e6:.0f} MB, {archives} archives: "
            + ", ".join(f"{s.drive_name}/{s.name}" for s in chosen))


def _setlist_folder(s):
    from src.core.formatting import sanitize_drive_name
    prefix = sanitize_drive_name(s.name) + "/"
    if s.name == s.drive_name:  # a flat drive is its own one setlist, as sync_flow has it
        files = list(s.drive["files"] or [])
    else:
        files = SUBSET.get(skey(s)) or [f for f in s.drive["files"] if f["path"].startswith(prefix)]
    return {"name": s.drive_name, "folder_id": s.drive_id, "files": files,
            "total_size": sum(f.get("size", 0) for f in files)}


def _sync(settings, client, auth_mgr, library, chosen):
    from src.sync.folder_sync import FolderSync
    from src.sync.markers import rebuild_markers_from_disk

    sync = FolderSync(client, auth_token=auth_mgr.get_token_getter(),
                      download_ignore=settings.download_ignore, download_mode=MODE[0])
    downloaded, errors = 0, []
    for s in chosen:
        n, _, failed, rate_limited, cancelled, _ = sync.sync_folder(
            _setlist_folder(s), library, [], setlist_name=s.name, label=s.name,
            skip_marker_rebuild=True, progress=Progress())
        downloaded += n
        if failed or rate_limited or cancelled:
            errors.append(f"{s.drive_name}/{s.name}: {failed} failed, "
                          f"{len(rate_limited)} rate limited, cancelled={cancelled}")
    return downloaded, errors


@case("sync_first")
def sync_first(settings, client, auth_mgr, library, state):
    from src.sync.markers import rebuild_markers_from_disk, get_markers_dir

    downloaded, errors = _sync(settings, client, auth_mgr, library, state["chosen"])
    rebuild_markers_from_disk(state["folders"], library)
    assert not errors, f"{len(errors)} errors: {errors[:3]}"
    assert downloaded, "nothing was downloaded"
    on_disk = sum(1 for p in library.rglob("*") if p.is_file() and ".synchotic" not in p.parts)
    markers = len(list(get_markers_dir().glob("*.json")))
    packs = sum(1 for s in state["chosen"] for f in _setlist_folder(s)["files"]
                if Path(f["path"]).suffix.lower() in (".zip", ".7z", ".rar"))
    assert markers >= packs, f"{packs} packs extracted but only {markers} markers written"
    leftover = [p.name for p in library.rglob("*") if p.is_file()
                and p.suffix.lower() in (".zip", ".7z", ".rar")]
    return (f"{downloaded} downloads, {on_disk} files on disk, {markers} markers for {packs} packs"
            + (f", packs left on disk: {leftover[:3]}" if leftover else ""))


def _plans(settings, library, state):
    from src.sync.download_planner import plan_downloads
    from src.sync.purge_planner import plan_purge

    downloads = {}
    for s in state["chosen"]:
        tasks, _, _ = plan_downloads(_setlist_folder(s)["files"], library / s.drive_name,
                                     settings.download_ignore, folder_name=s.drive_name)
        if tasks:
            downloads[f"{s.drive_name}/{s.name}"] = [f"{t.reason}: {t.rel_path}" for t in tasks[:3]]
    purge, _ = plan_purge(state["folders"], library, settings, {})
    return downloads, purge


@case("guessed_markers")
def guessed_markers(settings, library, state):
    """After the post-sync rebuild, a pack setlist synced only in part must
    still list the rest as downloads: its folder says nothing about them."""
    from src.core.formatting import sanitize_drive_name
    from src.sync.download_planner import plan_downloads

    s = next(s for s in state["chosen"] if skey(s) in SUBSET)
    prefix = sanitize_drive_name(s.name) + "/"
    full = [f for f in s.drive["files"] if f["path"].startswith(prefix)]
    packs = [f for f in full if Path(f["path"]).suffix.lower() in (".zip", ".7z", ".rar")]
    synced = len(SUBSET[skey(s)])
    tasks, _, _ = plan_downloads(full, library / s.drive_name, settings.download_ignore,
                                 folder_name=s.drive_name)
    pending = [t for t in tasks if t.is_archive]
    assert len(pending) >= len(packs) - synced, (
        f"{len(packs)} packs, {synced} synced, but only {len(pending)} planned: "
        f"the rest were taken as done")
    return f"{s.drive_name}/{s.name}: {len(packs)} packs, {synced} synced, {len(pending)} still to download"


@case("sync_again")
def sync_again(settings, client, auth_mgr, library, state, upgraded):
    """After an upgrade this is the new version's first sync, which may fetch
    again a pack whose marker the startup tagging took for a guess. What it
    fetches is reported; after it, nothing is left either way."""
    from src.sync.markers import rebuild_markers_from_disk

    first = ""
    if upgraded:
        planned, _ = _plans(settings, library, state)
        downloaded, errors = _sync(settings, client, auth_mgr, library, state["chosen"])
        rebuild_markers_from_disk(state["folders"], library)
        assert not errors, f"{len(errors)} errors: {errors[:3]}"
        packs = [p.rsplit("/", 1)[-1] for paths in planned.values() for p in paths]
        first = f"first sync after the upgrade fetched {downloaded} again {packs}, then "
    downloads, purge = _plans(settings, library, state)
    assert not downloads, f"a second sync would download again: {downloads}"
    assert not purge, f"a second sync would purge {len(purge)} files: {[str(p) for p, _ in purge[:3]]}"
    return first + "nothing to download, nothing to purge"


@case("purge_setlist")
def purge_setlist(settings, client, auth_mgr, library, state):
    from src.core.formatting import sanitize_drive_name
    from src.sync import purge_flow

    victim = max(state["chosen"], key=lambda s: len(_setlist_folder(s)["files"]))
    folder = library / victim.drive_name / sanitize_drive_name(victim.name)
    others_before = {p for p in library.rglob("*") if p.is_file() and folder not in p.parents
                     and ".synchotic" not in p.parts}
    victim_files = {p for p in folder.rglob("*") if p.is_file()}
    settings.set_subfolder_enabled(victim.drive_id, victim.name, False)

    from src.sync.purge_planner import plan_purge
    planned = {Path(str(p)) for p, _ in plan_purge(state["folders"], library, settings, {})[0]}
    from src.core.paths import unextended
    planned = {unextended(p) for p in planned}
    assert planned == {unextended(p) for p in victim_files}, (
        f"plan is {len(planned)} files, the setlist has {len(victim_files)}; "
        f"outside it: {[str(p) for p in planned if folder not in unextended(p).parents][:3]}")

    purge_flow._confirmed = lambda *a, **k: True  # the prompt, answered yes
    purge_flow.purge_all_folders(state["folders"], library, settings, {}, progress=Progress())
    left = [p for p in victim_files if p.exists()]
    others_after = {p for p in library.rglob("*") if p.is_file() and folder not in p.parents
                    and ".synchotic" not in p.parts}
    assert not left, f"{len(left)} of its files survived the purge"
    assert others_after == others_before, f"purge touched other setlists: {sorted(others_before - others_after)[:3]}"

    settings.set_subfolder_enabled(victim.drive_id, victim.name, True)
    downloaded, errors = _sync(settings, client, auth_mgr, library, [victim])
    assert not errors and downloaded, f"turned back on, it did not return: {errors[:3]}"
    downloads, purge = _plans(settings, library, state)
    assert not downloads and not purge, f"not settled after returning: {downloads} {len(purge)} to purge"
    return f"{victim.drive_name}/{victim.name}: {len(victim_files)} files purged alone, {downloaded} back"


@case("interrupted")
def interrupted(settings, client, auth_mgr, library, state):
    """A pack setlist cut off two seconds into its download, the way ESC or a
    closed window leaves it, then synced again."""
    from src.core.formatting import sanitize_drive_name
    from src.core.paths import unextended
    from src.sync import purge_flow
    from src.sync.folder_sync import FolderSync
    from src.sync.markers import load_marker, verify_marker

    packs = [s for s in state["chosen"] if skey(s) in SUBSET]
    assert packs, "no pack setlist to interrupt"
    s = max(packs, key=lambda s: sum(f["size"] for f in SUBSET[skey(s)]))
    folder = library / s.drive_name / sanitize_drive_name(s.name)
    shutil.rmtree(folder)
    for f in SUBSET[skey(s)]:
        from src.sync.markers import delete_marker
        delete_marker(f"{s.drive_name}/{f['path']}", f["md5"])

    # Cut off the moment a download is in flight, not on a timer: small packs
    # can finish inside any fixed window, and then nothing was interrupted.
    def in_flight():
        return folder.exists() and any(folder.rglob("_download_*"))
    sync = FolderSync(client, auth_token=auth_mgr.get_token_getter(),
                      download_ignore=settings.download_ignore, download_mode=MODE[0])
    sync.sync_folder(_setlist_folder(s), library, [], setlist_name=s.name, label=s.name,
                     skip_marker_rebuild=True, progress=Progress(), cancel_check=in_flight)

    # Whatever claims to be done must really be there.
    lying = []
    for f in SUBSET[skey(s)]:
        marker = load_marker(f"{s.drive_name}/{f['path']}", f["md5"])
        if marker and not verify_marker(marker, library / s.drive_name):
            lying.append(f["path"])
    assert not lying, f"markers for packs not fully on disk: {lying}"
    partials = [p.name for p in folder.rglob("_download_*")] if folder.exists() else []

    done_at_cut = sum(1 for f in SUBSET[skey(s)]
                      if load_marker(f"{s.drive_name}/{f['path']}", f["md5"]))
    assert done_at_cut < len(SUBSET[skey(s)]), "the cut came after every pack finished"
    downloaded, errors = _sync(settings, client, auth_mgr, library, [s])
    assert not errors, f"resumed sync failed: {errors}"
    assert downloaded, "the resumed sync downloaded nothing, so the cut packs were taken as done"
    purge_flow._confirmed = lambda *a, **k: True
    purge_flow.purge_all_folders(state["folders"], library, settings, {}, progress=Progress())
    left = [p.name for p in folder.rglob("_download_*")]
    assert not left, f"partial downloads left after the next sync: {left}"
    downloads, purge = _plans(settings, library, state)
    assert not downloads and not purge, f"not settled: {downloads} {len(purge)} to purge"
    return (f"{s.drive_name}/{s.name}: cut off with {len(partials)} partial file(s), "
            f"resumed with {downloaded} downloads, settled, no partials left")


@case("custom_becomes_shipped")
def custom_becomes_shipped(settings, client, auth_mgr, library, by_name, api_key):
    """A shipped setlist the user had added as a custom folder before it
    shipped, in a drive they have off. Synced as custom, it stays custom: the
    drive stays off, and on, only its own copy of the setlist goes off."""
    from sync import SyncApp
    from src.config import DrivesConfig
    from src.config.custom import CustomFolders
    from src.core import paths
    from src.core.formatting import sanitize_drive_name
    from src.drive import FolderScanner
    from src.sync.background_scanner import BackgroundScanner
    from src.sync.download_planner import plan_downloads
    from src.sync.markers import rebuild_markers_from_disk
    from src.sync.purge_planner import plan_purge

    drive = by_name["CSC Released Packs"]
    assert not settings.is_drive_enabled(drive.folder_id), "the shipped drive should start off"
    shipped = {"name": drive.name, "folder_id": drive.folder_id, "files": None}
    listing = BackgroundScanner([shipped], auth_mgr, api_key)
    listing.discover()
    lister = FolderScanner(listing._client)
    for s in list(listing.all_setlists.values()):
        listing._scan_setlist(s, lister)

    def size(s):
        prefix = sanitize_drive_name(s.name) + "/"
        return sum(f.get("size", 0) for f in shipped["files"] or [] if f["path"].startswith(prefix))
    candidates = sorted((s for s in listing.all_setlists.values() if 0 < size(s) < 300e6), key=size)
    assert candidates, "no setlist under 300 MB to try it with"
    target = candidates[0]

    # Added as custom before it shipped, under its Drive name.
    custom_name = target.name
    custom = CustomFolders.load(paths.get_local_manifest_path())
    custom.add_folder(target.setlist_id, custom_name)
    custom.save()
    settings.set_drive_enabled(target.setlist_id, True)
    custom_folder = {"name": custom_name, "folder_id": target.setlist_id, "files": None, "is_custom": True}
    as_custom = BackgroundScanner([custom_folder], auth_mgr, api_key, user_settings=settings)
    as_custom.discover()
    for s in list(as_custom.all_setlists.values()):
        as_custom._scan_setlist(s, lister)
    downloaded, errors = _sync(settings, client, auth_mgr, library, list(as_custom.all_setlists.values()))
    rebuild_markers_from_disk([custom_folder], library)
    assert not errors and downloaded, f"syncing it as custom failed: {errors}"

    app = object.__new__(SyncApp)
    app.drives_config = DrivesConfig.load(Path.cwd() / "drives.json")
    app.custom_folders = CustomFolders.load(paths.get_local_manifest_path())
    app.folders = [custom_folder]
    app.user_settings = settings
    app._background_scanner = listing
    app._turn_off_shipped_copies()
    assert not settings.is_drive_enabled(drive.folder_id), "the shipped drive was turned on"

    # With the drive on, its own copy goes off and nothing else does.
    settings.set_drive_enabled(drive.folder_id, True)
    app._turn_off_shipped_copies()
    off = settings.get_disabled_subfolders(drive.folder_id)
    assert off == {target.name}, f"off in the drive: {sorted(off)}"
    assert CustomFolders.load(paths.get_local_manifest_path()).has_folder(target.setlist_id), \
        "the custom folder was removed"
    assert settings.is_drive_enabled(target.setlist_id), "the custom folder was turned off"
    assert any((library / custom_name).rglob("*")), "the custom folder's charts are gone"
    assert not (library / drive.name / sanitize_drive_name(target.name)).exists(), \
        "something moved into the shipped drive"

    tasks, _, _ = plan_downloads(custom_folder["files"], library / custom_name,
                                 settings.download_ignore, folder_name=custom_name)
    assert not tasks, f"{len(tasks)} would download again: {[t.reason for t in tasks[:3]]}"
    purge, _ = plan_purge([custom_folder], library, settings, {})
    assert not purge, f"{len(purge)} would be purged: {[str(p) for p, _ in purge[:3]]}"
    settings.set_drive_enabled(drive.folder_id, False)
    settings.save()
    return (f"{drive.name}/{target.name} ({size(target) / 1e6:.0f} MB, {downloaded} downloads as custom): "
            f"stays custom, drive left off, on it turns only its own copy off, "
            f"nothing to download, nothing to purge")


@case("found_drives")
def found_drives(paths, settings, library, by_name, state):
    from src.sync.library_probe import turn_on_found

    drive = state["chosen"][0]
    d = by_name[drive.drive_name]
    settings.set_drive_enabled(d.folder_id, False)
    turn_on_found(settings, library, [d], undecided_only=True)
    assert settings.is_drive_enabled(d.folder_id) is False, "a switched-off drive was turned on"

    settings.drive_toggles.pop(d.folder_id, None)
    settings.purge_on_sync = False
    turn_on_found(settings, library, [d], undecided_only=True)
    assert settings.is_drive_enabled(d.folder_id) is False, "with purge off a drive was turned on"

    settings.purge_on_sync = True
    turn_on_found(settings, library, [d], undecided_only=True)
    assert settings.is_drive_enabled(d.folder_id) is True, "an undecided drive with charts was left off"
    settings.save()
    return "off stays off, purge off turns nothing on, undecided with charts turns on"


@case("one_log")
def one_log(paths, data):
    assert paths.unextended(paths.get_log_dir()) == data / "logs", f"logs go to {paths.get_log_dir()}"
    return str(data / "logs")


@case("launcher_check")
def launcher_check(root):
    import requests
    from src.core import launcher_update as lu

    target = root / "launcher-test" / "synchotic-launcher.exe"
    target.parent.mkdir(parents=True, exist_ok=True)
    url = "https://github.com/noahbaxter/synchotic/releases/download/launcher-v1.4/synchotic-launcher.exe"
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(target, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
    os.environ["_PYI_ARCHIVE_FILE"] = r"C:\fake\_app\synchotic-app.exe"  # as the app has
    try:
        assert lu._reports(target, "1.4"), "the real 1.4 launcher failed the --version check"
    finally:
        os.environ.pop("_PYI_ARCHIVE_FILE", None)
    env = {"SYNCHOTIC_START_TIME": "1"}
    for name, ours in (("synchotic-launcher.exe", True), ("synchotic-launcher (1).exe", True),
                       ("synchotic-launcher-dev.exe", False), ("cmd.exe", False),
                       ("synchotic-app.exe", False)):
        exe = Path(r"D:\Charts") / name
        got = lu.running_launcher(env, parent_exe=lambda: exe)
        assert (got is not None) == ours, f"{name}: taken={got is not None}, expected {ours}"
    return "real 1.4 exe reports 1.4 with app env; name matching right for 5 names"


def child_adoption(root: Path):
    """The import of an old install, cut off after 2 markers, then relaunched."""
    @case("adoption")
    def run():
        import shutil as sh

        base = root / "adoption"
        if base.exists():
            sh.rmtree(base)
        legacy_root = base / "D_Charts"
        legacy = legacy_root / ".dm-sync"
        library = legacy_root / "Sync Charts"
        (legacy / "markers").mkdir(parents=True)
        # A real old library has charts in it; an empty one is not adopted.
        (library / "BirdmanExe Drive" / "set" / "chart").mkdir(parents=True)
        (library / "BirdmanExe Drive" / "set" / "chart" / "song.ini").write_text("x")
        for i in range(8):
            (legacy / "markers" / f"birdmanexe drive_set_pack{i}_abcd.json").write_text('{"files": {}}')
        (legacy / "token.json").write_text("{}")
        (legacy / "settings.json").write_text(json.dumps(
            {"drive_toggles": {"x": True}, "oauth_prompted": True}))

        os.environ.update(SYNCHOTIC_OS_DIRS="1", SYNCHOTIC_LEGACY_ROOT=str(legacy_root),
                          LOCALAPPDATA=str(base / "AppData" / "Local"))
        os.environ.pop("SYNCHOTIC_ROOT", None)
        # The import also looks under the home folder, where this machine's
        # real install may be. Keep it inside the test folder.
        home = base / "home"
        home.mkdir()
        Path.home = staticmethod(lambda: home)
        from src.config.settings import UserSettings
        from src.core import legacy_migration, paths

        payload = paths.get_data_dir() / "_app"
        payload.mkdir(parents=True, exist_ok=True)
        paths.get_app_dir = lambda: payload  # a built app's folder, not the checkout
        assert str(base) in str(paths.get_data_dir()), f"data dir escaped: {paths.get_data_dir()}"
        for c in legacy_migration.former_default_libraries() + legacy_migration.legacy_install_candidates():
            assert str(base) in str(c), f"would look outside the test folder: {c}"

        def launch():
            paths.set_library_path(None)
            early = UserSettings.load(paths.get_settings_path())
            paths.set_library_path(early.library_path or None)
            if not early.library_path:
                found = legacy_migration.default_library_to_adopt()
                if found:
                    early.library_path = str(found)
                    early.save()
                    paths.set_library_path(found)
            return paths.adopt_legacy_install()

        real, seen = sh.copy2, []

        def cut(src, dst, *a, **k):
            if "markers" in str(src):
                seen.append(src)
                if len(seen) > 2:
                    raise KeyboardInterrupt
            return real(src, dst, *a, **k)

        sh.copy2 = cut
        try:
            launch()
        except KeyboardInterrupt:
            pass
        sh.copy2 = real
        arrived = paths.get_library_state_dir() / "markers"
        first = len(list(arrived.glob("*.json")))
        second = launch()
        n = len(list(arrived.glob("*.json")))
        assert paths.unextended(paths.get_library_path()) == library, f"library is {paths.get_library_path()}"
        assert n == 8, f"{n}/8 markers after relaunch ({first} before), relaunch said {second}"
        assert str(paths.get_library_path()).startswith("\\\\?\\"), "library path has no MAX_PATH prefix"
        return f"{first}/8 after the cut, 8/8 after relaunch ({second}), through {paths.get_library_path()}"

    run()


if __name__ == "__main__":
    main()
