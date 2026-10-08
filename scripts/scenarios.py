"""Scripted runs of the real app, start to finish, in a tmux pane.

A scenario (scenarios/*.scn) is a list of steps: set up a throwaway install,
launch the app, press keys, wait for what the screen should say, and check the
library against Google Drive with the app's own planners. Every run starts
from an empty install signed in with this machine's BYOC token, and syncs real
packs from real Drive.

    scripts/scenarios.py                  every scenario, one after another
    scripts/scenarios.py purge_setlist    the named ones
    scripts/scenarios.py --app /Applications/Synchotic.app/Contents/MacOS/synchotic-tui
    scripts/scenarios.py --keep           leave each run's install in place

One at a time on purpose: every run scans Drive on the same Google project,
and two at once (or one beside a running app) fail with "Quota exceeded".
A pass line each, exit 1 on any failure. Screens, the app log and the steps
are kept in runs/<scenario>/.

Steps, one per line, # for comments:

    include common/synced.scn     another file's steps, in place
    setup                         a fresh install, signed in, purge on
    on Drive/Setlist              turn on this setlist (others in its drive off)
    launch / quit / relaunch      start the app, leave it with Esc, both
    wait "text" [secs]            until the screen shows text (default 60)
    gone "text" [secs]            until it no longer does
    expect "text" / refute "text" the screen shows it now / does not
    press KEY ...                 S, y, n, Enter, Escape, Up, Down, Tab, Space
    type "text"                   literal text; $CUSTOM is a small chart folder
                                  a custom drive can be made from
    select "text"                 move the focused pane's cursor onto a row
    sleep secs
    shot name                     keep the screen as <n>-name.txt
    settled                       Drive and library agree: nothing to download,
                                  nothing to purge, no partial downloads
    exists "path" / missing "path"  under the library
"""

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import time
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCENARIOS = REPO / "scenarios"
RUNS = REPO / "runs"
SOCKET = "synchotic-scenarios"
COLS, ROWS = 100, 34
CURSOR_BG = "48;2;55;62;82"  # chotic-ui Colors.HIGHLIGHT_BG, the focused row
PROMPTS = ("Sync anyway?", "Delete ")  # questions a sync can stop on
KEYS = {"enter": "Enter", "escape": "Escape", "esc": "Escape", "up": "Up",
        "down": "Down", "tab": "Tab", "space": "Space"}


class Failed(Exception):
    pass


def parse(path: Path, seen=()) -> list:
    """(file, line number, step, args) for every step, includes expanded."""
    steps = []
    for n, raw in enumerate(path.read_text().splitlines(), 1):
        words = shlex.split(raw, comments=True)
        if not words:
            continue
        if words[0] == "include":
            target = (path.parent / words[1]).resolve()
            if target in seen:
                raise ValueError(f"{path.name}:{n} includes itself")
            steps += parse(target, seen + (path.resolve(),))
        else:
            steps.append((path.name, n, words[0], words[1:]))
    return steps


# ---- the app in a tmux pane ------------------------------------------------

def tmux(*args, check=True) -> str:
    out = subprocess.run(["tmux", "-L", SOCKET, "-f", "/dev/null", *args],
                         capture_output=True, text=True)
    if check and out.returncode:
        raise Failed(f"tmux {' '.join(args[:2])}: {out.stderr.strip()}")
    return out.stdout


class Pane:
    def __init__(self, name, command, env):
        self.name, self.command, self.env = name, command, env

    def launch(self, command=None):
        tmux("kill-session", "-t", self.name, check=False)
        command = command or self.command
        # Run from source, the app needs its own vendored UI importable, which
        # only a venv with it installed editable would otherwise give it.
        ui = Path(command[-1]).parent / "vendor" / "chotic-ui"
        env = {**self.env, **({"PYTHONPATH": str(ui)} if ui.exists() else {})}
        flags = [x for k, v in env.items() for x in ("-e", f"{k}={v}")]
        tmux("new-session", "-d", "-s", self.name, "-x", str(COLS), "-y", str(ROWS),
             *flags, "--", *command, ";", "set-option", "-t", self.name,
             "remain-on-exit", "on")

    def screen(self, escapes=False) -> str:
        return tmux("capture-pane", "-p", *(["-e"] if escapes else []), "-t", self.name,
                    check=False)

    def dead(self):
        """The app's exit status once it has exited, else None."""
        out = tmux("display-message", "-p", "-t", self.name,
                   "#{pane_dead} #{pane_dead_status}", check=False).split()
        return int(out[1]) if out and out[0] == "1" else None

    def press(self, *keys):
        for key in keys:
            tmux("send-keys", "-t", self.name, KEYS.get(key.lower(), key))
            time.sleep(0.15)

    def type(self, text):
        tmux("send-keys", "-t", self.name, "-l", text)

    def wait(self, text, secs, present=True):
        end = time.time() + secs
        start = time.time()
        while time.time() < end:
            screen = self.screen()
            if (text in screen) == present:
                return
            # A question the scenario is not waiting for never goes away on
            # its own: say so now, not when the timeout runs out. Not at once,
            # though: one just answered stays on screen until the next frame.
            for prompt in PROMPTS:
                if prompt in screen and prompt not in text and time.time() - start > 5:
                    raise Failed(f"stopped at {prompt!r} waiting for {text!r}:\n"
                                 + "\n".join(l for l in screen.splitlines() if l.strip()))
            status = self.dead()
            if status is not None:
                raise Failed(f"the app exited ({status}) waiting for {text!r}")
            time.sleep(0.3)
        raise Failed(f"{'never showed' if present else 'still shows'} {text!r} after {secs}s")

    def select(self, text):
        """Down until the focused row holds text; from the bottom, back up."""
        def focused():
            for line in self.screen(escapes=True).splitlines():
                if CURSOR_BG in line:
                    return line
            return ""
        for key in ("Down", "Up"):
            last = None
            for _ in range(120):
                row = focused()
                if text in _plain(row):
                    return
                if row == last:
                    break  # this end of the list
                last = row
                self.press(key)
        raise Failed(f"no row {text!r} to select")

    def quit(self):
        for _ in range(8):
            if self.dead() is not None:
                return
            self.press("Escape")
            time.sleep(1)
        raise Failed("the app did not quit on Esc")

    def kill(self):
        tmux("kill-session", "-t", self.name, check=False)


def _plain(line):
    import re
    return re.sub(r"\x1b\[[0-9;:]*[A-Za-z]", "", line)


# ---- one scenario, in its own process --------------------------------------

def run_one(path: Path, out: Path, app: list, auth: Path, keep: bool):
    root = out / "root"
    if root.exists():
        shutil.rmtree(root)
    data, library = root / ".dm-sync", root / "Sync Charts"
    env = {"SYNCHOTIC_ROOT": str(root), "SYNCHOTIC_OS_DIRS": "0",
           "COLORTERM": "truecolor", "TERM": "xterm-256color"}
    os.environ.update(env)
    for k in ("SYNCHOTIC_LIBRARY", "SYNCHOTIC_LEGACY_ROOT"):
        os.environ.pop(k, None)
    sys.path[:0] = [str(REPO), str(REPO / "vendor" / "chotic-ui")]
    os.chdir(REPO)
    from src.core.legacy_migration import FRESH_ENV
    env[FRESH_ENV] = os.environ[FRESH_ENV] = "1"

    pane = Pane(f"scn-{path.stem}", app, env)
    steps = parse(path)
    shots = 0
    log = (out / "steps.txt").open("w")
    try:
        for file, n, step, args in steps:
            log.write(f"{file}:{n} {step} {' '.join(args)}\n")
            log.flush()
            try:
                if step == "setup":
                    _setup(data, library, auth)
                elif step == "on":
                    _turn_on(args[0])
                elif step == "off":
                    _turn_off(args[0])
                elif step == "custom":
                    _add_custom(args[0], on=args[1:] != ["off"])
                elif step == "notepad":
                    _notepad_settings()
                elif step == "launch":
                    pane.launch(_release(args[0], out) if args else None)
                elif step == "quit":
                    pane.quit()
                elif step == "relaunch":
                    pane.quit()
                    pane.launch()
                elif step == "wait":
                    pane.wait(args[0], float(args[1]) if len(args) > 1 else 60)
                elif step == "gone":
                    pane.wait(args[0], float(args[1]) if len(args) > 1 else 60, present=False)
                elif step in ("expect", "refute"):
                    shown = args[0] in pane.screen()
                    if shown != (step == "expect"):
                        raise Failed(f"screen {'lacks' if step == 'expect' else 'shows'} {args[0]!r}")
                elif step == "press":
                    pane.press(*args)
                elif step == "type":
                    pane.type(args[0].replace("$CUSTOM", _custom_folder()))
                elif step == "select":
                    pane.select(args[0])
                elif step == "sleep":
                    time.sleep(float(args[0]))
                elif step == "shot":
                    shots += 1
                    (out / f"{shots:02}-{args[0]}.txt").write_text(pane.screen())
                elif step == "settled":
                    _settled(library)
                elif step in ("exists", "missing"):
                    there = any(library.glob(args[0]))
                    if there != (step == "exists"):
                        raise Failed(f"{args[0]} {'is missing' if step == 'exists' else 'is still there'}")
                else:
                    raise Failed(f"unknown step {step!r}")
            except Failed as e:
                raise Failed(f"{file}:{n} {step} {' '.join(args)}: {e}") from None
        return None
    except Failed as e:
        return str(e)
    except Exception:
        return traceback.format_exc(limit=6)
    finally:
        (out / "last-screen.txt").write_text(pane.screen())
        log.close()
        pane.kill()
        for f in (data / "logs").glob("*.log") if (data / "logs").exists() else ():
            shutil.copy2(f, out / f"app-{f.name}")
        if not keep:
            shutil.rmtree(root, ignore_errors=True)


def _setup(data: Path, library: Path, auth: Path):
    data.mkdir(parents=True)
    library.mkdir(parents=True)
    # SYNCHOTIC_ROOT moves the bundled drives.json too, as for --first-run.
    shutil.copy2(REPO / "drives.json", data.parent / "drives.json")
    for name in ("token.json", "credentials.json"):
        shutil.copy2(auth / name, data / name)
    from src.config.settings import UserSettings
    from src.core import paths
    settings = UserSettings.load(paths.get_settings_path())
    settings.library_path = str(library)
    settings.download_mode = "byoc"
    settings.purge_on_sync = True
    settings.save()


def _release(ref: str, out: Path) -> list:
    """The command that runs `ref` (a tag such as v1.5.6) from source, with the
    chotic-ui it pinned and this checkout's UnRAR, which a git archive leaves
    out."""
    src = out / f"src-{ref}"
    if not src.exists():
        src.mkdir()

        def unpack(repo, rev, dest):
            dest.mkdir(parents=True, exist_ok=True)
            archive = subprocess.run(["git", "-C", str(repo), "archive", rev],
                                     capture_output=True, check=True).stdout
            subprocess.run(["tar", "xf", "-", "-C", str(dest)], input=archive, check=True)

        unpack(REPO, ref, src)
        ui = subprocess.run(["git", "-C", str(REPO), "rev-parse", f"{ref}:vendor/chotic-ui"],
                            capture_output=True, text=True, check=True).stdout.strip()
        unpack(REPO / "vendor" / "chotic-ui", ui, src / "vendor" / "chotic-ui")
        if (REPO / "libs").exists():
            shutil.copytree(REPO / "libs", src / "libs", dirs_exist_ok=True)
    return [sys.executable, str(src / "sync.py")]


def _drives():
    from src.config import DrivesConfig
    from src.core import paths
    return {d.name: d for d in DrivesConfig.load(paths.get_drives_config_path()).drives}


def _client():
    from src.app.config import API_KEY
    from src.core import paths
    from src.drive import DriveClient
    from src.drive.auth import AuthManager
    from src.drive.client import DriveClientConfig
    auth = AuthManager(token_path=paths.get_token_path())
    return DriveClient(DriveClientConfig(api_key=API_KEY), auth_token=auth.get_token_getter())


FOLDER = "application/vnd.google-apps.folder"


def _subfolders(client, folder_id):
    """Folders, and shortcuts to folders: a drive's setlists can be either,
    and one left out stays undecided, which the app treats as on."""
    return [f for f in client.list_folder(folder_id)
            if f.get("mimeType") == FOLDER
            or (f.get("shortcutDetails") or {}).get("targetMimeType") == FOLDER]


def _turn_on(target: str):
    """The setlist on; its drive on with every other setlist off, unless an
    earlier `on` already turned some on."""
    from src.config.settings import UserSettings
    from src.core import paths
    drive_name, setlist = target.split("/", 1)
    drive = _drives()[drive_name]
    settings = UserSettings.load(paths.get_settings_path())
    if not settings.is_drive_enabled(drive.folder_id):
        settings.set_drive_enabled(drive.folder_id, True)
        names = [f["name"] for f in _subfolders(_client(), drive.folder_id)]
        if setlist not in names:
            raise Failed(f"{drive_name} has no setlist {setlist!r}")
        for name in names:
            settings.set_subfolder_enabled(drive.folder_id, name, False)
    settings.set_subfolder_enabled(drive.folder_id, setlist, True)
    settings.save()


def _turn_off(target: str):
    """The setlist off in a drive that stays on."""
    from src.config.settings import UserSettings
    from src.core import paths
    drive_name, setlist = target.split("/", 1)
    settings = UserSettings.load(paths.get_settings_path())
    settings.set_subfolder_enabled(_drives()[drive_name].folder_id, setlist, False)
    settings.save()


def _add_custom(target: str, on: bool):
    """A shipped setlist added as a custom drive, as someone did before it
    shipped or with a shortcut to it: same folder id, its own name."""
    from src.config.custom import CustomFolders
    from src.config.settings import UserSettings
    from src.core import paths
    drive_name, setlist = target.split("/", 1)
    folder = next(f for f in _subfolders(_client(), _drives()[drive_name].folder_id)
                  if f["name"] == setlist)
    folder_id = (folder.get("shortcutDetails") or {}).get("targetId") or folder["id"]
    custom = CustomFolders.load(paths.get_local_manifest_path())
    custom.add_folder(folder_id, setlist)
    custom.save()
    settings = UserSettings.load(paths.get_settings_path())
    settings.set_drive_enabled(folder_id, on)
    settings.save()


def _notepad_settings():
    """settings.json as Notepad saves a hand edit: a BOM in front."""
    from src.core import paths
    path = paths.get_settings_path()
    raw = path.read_bytes()
    if not raw.startswith(b"\xef\xbb\xbf"):
        path.write_bytes(b"\xef\xbb\xbf" + raw)


def _custom_folder() -> str:
    """A chart folder inside a shipped setlist: small, public, and not a
    drive or a setlist itself, so it can be added as a custom drive."""
    client = _client()
    drive = _drives()["BirdmanExe Drive"]
    setlist = next(f for f in _subfolders(client, drive.folder_id) if f["name"] == "FractalWizz")
    return _subfolders(client, setlist["id"])[0]["id"]


def _settled(library: Path):
    """What the next sync would do, from a fresh scan: nothing."""
    from src.config import DrivesConfig
    from src.config.custom import CustomFolders
    from src.config.settings import UserSettings
    from src.core import paths
    from src.core.formatting import sanitize_drive_name
    from src.drive import FolderScanner
    from src.drive.auth import AuthManager
    from src.app.config import API_KEY
    from src.sync.background_scanner import BackgroundScanner
    from src.sync.download_planner import plan_downloads
    from src.sync.purge_planner import find_partial_downloads, plan_purge

    settings = UserSettings.load(paths.get_settings_path())
    paths.set_library_path(library)
    folders = [{"name": d.name, "folder_id": d.folder_id, "files": None}
               for d in DrivesConfig.load(paths.get_drives_config_path()).drives if not d.hidden]
    folders += [{"name": c.name, "folder_id": c.folder_id, "files": None, "is_custom": True}
                for c in CustomFolders.load(paths.get_local_manifest_path()).folders]
    auth = AuthManager(token_path=paths.get_token_path())
    scanner = BackgroundScanner(folders, auth, API_KEY, user_settings=settings,
                                download_path=library)
    scanner.discover()
    lister = FolderScanner(scanner._client)
    downloads = []
    for key, s in list(scanner.all_setlists.items()):
        if key not in scanner._enabled_setlist_ids:
            continue
        scanner._scan_setlist(s, lister)
    for key, s in list(scanner.all_setlists.items()):
        if key not in scanner._enabled_setlist_ids:
            continue
        files = s.drive["files"] or []
        if s.name != s.drive_name:
            prefix = sanitize_drive_name(s.name) + "/"
            files = [f for f in files if f["path"].startswith(prefix)]
        tasks, _, _ = plan_downloads(files, library / s.drive_name, settings.download_ignore,
                                     folder_name=s.drive_name)
        downloads += [f"{t.reason}: {t.rel_path}" for t in tasks]
    if downloads:
        raise Failed(f"{len(downloads)} would download: {downloads[:4]}")
    purge, _ = plan_purge(folders, library, settings, {})
    if purge:
        raise Failed(f"{len(purge)} would be purged: {[str(p) for p, _ in purge[:4]]}")
    partials = find_partial_downloads(library)
    if partials:
        raise Failed(f"partial downloads left: {[str(p) for p, _ in partials[:4]]}")


# ---- the suite ---------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("names", nargs="*")
    ap.add_argument("--app", default="", help="a built app to run instead of sync.py")
    ap.add_argument("--ref", default="",
                    help="run a release from git (e.g. v1.5.6) instead, to show a scenario "
                         "catches the bug it was written for")
    ap.add_argument("--auth", default=str(Path.home() / "Library/Application Support/Synchotic"),
                    help="folder holding token.json and credentials.json")
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--one", default="")  # internal: run one scenario in this process
    args = ap.parse_args()
    app = [args.app] if args.app else [sys.executable, str(REPO / "sync.py")]

    if args.one:
        path = Path(args.one)
        out = RUNS / (path.stem + (f"@{args.ref}" if args.ref else ""))
        if args.ref:
            app = _release(args.ref, out)
        error = run_one(path, out, app, Path(args.auth), args.keep)
        print(json.dumps({"error": error}))
        return

    paths = ([SCENARIOS / f"{n.removesuffix('.scn')}.scn" for n in args.names]
             or sorted(SCENARIOS.glob("*.scn")))
    failed = 0
    for path in paths:
        out = RUNS / (path.stem + (f"@{args.ref}" if args.ref else ""))
        shutil.rmtree(out, ignore_errors=True)
        out.mkdir(parents=True)
        t = time.time()
        child = subprocess.run(
            [sys.executable, __file__, "--one", str(path), "--auth", args.auth,
             *(["--app", args.app] if args.app else []), *(["--ref", args.ref] if args.ref else []),
             *(["--keep"] if args.keep else [])],
            capture_output=True, text=True)
        try:
            error = json.loads(child.stdout.strip().splitlines()[-1])["error"]
        except (ValueError, IndexError, KeyError):
            error = (child.stdout + child.stderr)[-1500:] or f"exited {child.returncode}"
        failed += bool(error)
        print(f"[{'FAIL' if error else 'PASS'}] {out.name} ({time.time() - t:.0f}s)"
              + (f"\n    {error}" if error else ""), flush=True)
    print(f"{len(paths) - failed}/{len(paths)} passed, runs in {RUNS}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
