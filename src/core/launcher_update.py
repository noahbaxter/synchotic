"""Keep the launcher current, from the app.

The app updates itself every launch; the launcher never did, and there was no
way to tell people to download it again. So Windows users sat on launchers as
old as 1.1, in whatever console Windows gave them, long after 1.4 moved them
into WezTerm. The app does the updating rather than the launcher because the
app can be fixed: a launcher with a broken updater would strand every copy of
itself, and the only way out would be the redownload this exists to avoid.

Only a release whose notes carry OPT_IN is taken, so a launcher release can
go out and be tested by hand before any install replaces itself with it.

A new launcher is run with --version before it goes anywhere near the old
one's place, since a launcher that cannot start is the one failure the app can
never repair: nothing would be left to run the app.
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from .logging import debug_log

# The most GitHub returns. App releases share the list, so a smaller page lets
# the newest launcher fall off it after enough of them.
RELEASES_URL = "https://api.github.com/repos/noahbaxter/synchotic/releases?per_page=100"
OPT_IN = "<!-- app-updates-launcher -->"
TAG = re.compile(r"^launcher-v(\d+(?:\.\d+)*)$")

# The asset each platform's launcher ships as. macOS is a zipped .app.
ASSETS = {
    "win32": "synchotic-launcher.exe",
    "darwin": "Synchotic-launcher-macos.zip",
    "linux": "Synchotic-launcher-x86_64.AppImage",
}

# Launchers from before 1.4 pass no version. Anything released beats them.
UNKNOWN = (0,)


def parse_version(text: str) -> tuple:
    """(1, 4) for "1.4". UNKNOWN for anything else, which reads as older
    than every release rather than stopping the app."""
    try:
        return tuple(int(part) for part in text.split("."))
    except ValueError:
        return UNKNOWN


def _platform() -> str:
    return "linux" if sys.platform.startswith("linux") else sys.platform


# --- which launcher started us -----------------------------------------------

def running_launcher(env=None, parent_exe=None):
    """(version, path to replace) for the launcher that started this app, or
    None when it cannot be told: a source run, or a launcher it cannot find.

    1.4 and later say so in the environment. Older ones are found from the
    process that started the app: on Windows every launcher waits on the app
    as its child, and on macOS 1.3 the app's parent is the WezTerm inside the
    launcher's own .app. On Linux the AppImage runtime names its file.
    """
    env = os.environ if env is None else env
    if "SYNCHOTIC_LAUNCHER_VERSION" in env:
        # 1.4 and later name themselves only when they may be replaced; a
        # dev, source or dev-channel run leaves the path out. Never guess
        # then: on Windows the parent of a source run is python.exe.
        if not env.get("SYNCHOTIC_LAUNCHER_PATH"):
            return None
        version = parse_version(env.get("SYNCHOTIC_LAUNCHER_VERSION") or "0")
        return version, Path(env["SYNCHOTIC_LAUNCHER_PATH"])
    if not env.get("SYNCHOTIC_START_TIME"):
        return None  # not started by a launcher

    platform = _platform()
    if platform == "linux":
        image = env.get("APPIMAGE")
        return (UNKNOWN, Path(image)) if image else None

    exe = parent_exe() if parent_exe else _parent_exe()
    if not exe:
        return None
    if platform == "win32":
        # The app's own exe is never the launcher, whatever started it.
        if exe.suffix.lower() == ".exe" and exe.name.lower() != "synchotic-app.exe":
            return UNKNOWN, exe
        return None
    if platform == "darwin":
        for folder in exe.parents:
            if folder.suffix == ".app":
                return UNKNOWN, folder
    return None


def _parent_exe():
    try:
        import psutil
        parent = psutil.Process().parent()
        return Path(parent.exe()) if parent else None
    except Exception:
        return None


# --- what is out there -------------------------------------------------------

def newest_launcher(releases: list, platform: str):
    """(version, tag, download url) of the newest opted-in launcher release
    with an asset for this platform, or None."""
    best = None
    for release in releases:
        match = TAG.match(release.get("tag_name", ""))
        if not match or release.get("draft") or release.get("prerelease"):
            continue
        if OPT_IN not in (release.get("body") or ""):
            continue
        asset = next((a for a in release.get("assets", [])
                      if a.get("name") == ASSETS.get(platform)), None)
        if not asset:
            continue
        version = parse_version(match.group(1))
        if best is None or version > best[0]:
            best = (version, release["tag_name"], asset["browser_download_url"])
    return best


# A local releases list in place of GitHub's, whose download urls may be file
# paths: how a launcher update is tested end to end without publishing one.
FEED_ENV = "SYNCHOTIC_LAUNCHER_FEED"


def _fetch_releases() -> list:
    feed = os.environ.get(FEED_ENV)
    if feed:
        import json
        return json.loads(Path(feed).read_text())
    import requests
    # Short: this runs before the first screen, on every launch.
    response = requests.get(RELEASES_URL, timeout=5,
                            headers={"Accept": "application/vnd.github+json"})
    response.raise_for_status()
    return response.json()


def _download(url: str, dest: Path) -> None:
    if os.environ.get(FEED_ENV) and Path(url).is_file():
        shutil.copyfile(url, dest)
        return
    import requests
    with requests.get(url, stream=True, timeout=60) as response:
        response.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in response.iter_content(1 << 20):
                f.write(chunk)


# --- putting it in place -----------------------------------------------------

def _old(target: Path) -> Path:
    """Where the replaced launcher is moved aside to. A running exe cannot be
    deleted on Windows but can be renamed, so it waits here for the next run."""
    return target.with_name(target.name + ".old")


def _remove(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path, ignore_errors=True)
    elif path.exists() or path.is_symlink():
        try:
            path.unlink()
        except OSError:
            pass  # still running (Windows); the next run gets it


def _stage(download: Path, platform: str, beside: Path) -> tuple:
    """Unpack the download next to where it goes, on the same volume so the
    swap is a rename. Returns (what replaces the launcher, what to run)."""
    if platform == "darwin":
        unpacked = Path(tempfile.mkdtemp(prefix=".launcher-", dir=beside))
        # ditto, not zipfile: the bundle is full of symlinks and signed files,
        # and zipfile flattens the one and breaks the other.
        subprocess.run(["ditto", "-x", "-k", str(download), str(unpacked)],
                       check=True, capture_output=True)
        bundle = next(unpacked.glob("*.app"))
        return bundle, bundle / "Contents" / "MacOS" / "Synchotic"
    download.chmod(0o755)
    return download, download


def _reports(exe: Path, version: str) -> bool:
    """Whether the launcher at `exe` starts and says it is `version`."""
    env = dict(os.environ)
    # Bazzite and the other atomic Fedoras have no libfuse2 to mount it with.
    env["APPIMAGE_EXTRACT_AND_RUN"] = "1"
    for key in ("SYNCHOTIC_LAUNCHER_PATH", "SYNCHOTIC_LAUNCHER_VERSION"):
        env.pop(key, None)
    flags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW
    try:
        result = subprocess.run([str(exe), "--version"], capture_output=True,
                                text=True, timeout=60, env=env, creationflags=flags)
    except (OSError, subprocess.TimeoutExpired) as e:
        debug_log(f"LAUNCHER_UPDATE | new launcher would not run | {e}")
        return False
    said = result.stdout.strip().splitlines()[-1:] or [""]
    return result.returncode == 0 and said[0] == version


def _swap(target: Path, replacement: Path) -> None:
    """Move the running launcher aside and the new one into its place, putting
    the old one back if the second move fails."""
    old = _old(target)
    _remove(old)
    target.rename(old)
    try:
        replacement.rename(target)
    except OSError:
        old.rename(target)
        raise


def update_launcher(fetch=_fetch_releases, download=_download, launcher=None,
                    platform=None, work=lambda job: job()) -> str:
    """Replace the launcher that started this app with the newest opted-in
    one, if it is newer. Returns what happened, for the log and for tests.

    `work` runs the download, check and swap once an update is certain, so a
    caller can put a spinner on the part that takes time and say nothing when
    there is nothing to do."""
    platform = platform or _platform()
    found = launcher if launcher is not None else running_launcher()
    if not found:
        return "no launcher"
    current, target = found
    _remove(_old(target))  # what the last update moved aside

    if platform not in ASSETS:
        return "no asset"
    newest = newest_launcher(fetch(), platform)
    if not newest or newest[0] <= current:
        return "current"
    version, tag, url = newest
    wanted = ".".join(str(part) for part in version)

    def install() -> str:
        scratch = Path(tempfile.mkdtemp(prefix=".launcher-", dir=target.parent))
        try:
            fetched = scratch / ASSETS[platform]
            download(url, fetched)
            replacement, exe = _stage(fetched, platform, scratch)
            if not _reports(exe, wanted):
                debug_log(f"LAUNCHER_UPDATE | {tag} did not report {wanted}, kept the old one")
                return "failed check"
            _swap(target, replacement)
            debug_log(f"LAUNCHER_UPDATE | {target} -> {tag}")
            return "updated"
        finally:
            _remove(scratch)

    return work(install)


def update_at_startup(work=None) -> bool:
    """Before the first screen: replace an outdated launcher, then close and
    start the new one, which reopens Synchotic. Returns only when there was
    nothing to do or the update failed, which leaves the working launcher and
    says why in the log. Built apps only: a run from source has no launcher.

    `work(job)` wraps the download and swap, which is where a caller shows
    that the app is about to reopen. It is never called when there is nothing
    to update.
    """
    if not getattr(sys, "frozen", False):
        return False
    try:
        launcher = running_launcher()
        # Now, while the window the user just opened is still the foreground one.
        window = _console_window(launcher[1] if launcher else None)
        result = update_launcher(launcher=launcher, **({"work": work} if work else {}))
    except Exception as e:
        debug_log(f"LAUNCHER_UPDATE | failed | {e!r}")
        return False
    debug_log(f"LAUNCHER_UPDATE | {result}")
    if result != "updated":
        return False
    try:
        reopen(launcher[1], close_window=window)
    except OSError as e:
        # Swapped but not started (an antivirus holding the new exe, say).
        # Carry on in this session; the next launch starts the new one.
        debug_log(f"LAUNCHER_UPDATE | could not start the new launcher | {e!r}")
        return False
    sys.exit(0)


# Handed to the new launcher: the window this app ran in, for it to close once
# its own is up. Windows Terminal keeps a window open after its program exits,
# so moving out of it would leave one behind. A WezTerm window closes itself.
CLOSE_WINDOW_ENV = "SYNCHOTIC_CLOSE_WINDOW"
CONSOLE_CLASSES = ("CASCADIA_HOSTING_WINDOW_CLASS", "ConsoleWindowClass")


def _console_window(launcher=None):
    """The Windows Terminal or console window this app is in, or None. Only
    the foreground window, only those two kinds, only if it carries the title
    the app sets, and only if nothing but the launcher and the app is attached
    to it, so nothing else is ever closed. The app retitles whatever console it
    runs in, including a cmd or PowerShell window the user started it from."""
    if _platform() != "win32":
        return None
    try:
        import ctypes
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        cls = ctypes.create_unicode_buffer(256)
        title = ctypes.create_unicode_buffer(512)
        user32.GetClassNameW(hwnd, cls, 256)
        user32.GetWindowTextW(hwnd, title, 512)
        others = _others_on_console(launcher)
        if others:
            debug_log(f"LAUNCHER_UPDATE | leaving a console shared with {sorted(others)}")
            return None
        if cls.value in CONSOLE_CLASSES and "Synchotic" in title.value:
            debug_log(f"LAUNCHER_UPDATE | will close {cls.value} window {int(hwnd)}")
            return int(hwnd)
        debug_log(f"LAUNCHER_UPDATE | leaving foreground window: {cls.value} {title.value!r}")
    except Exception as e:
        debug_log(f"LAUNCHER_UPDATE | no window to close: {e!r}")
    return None


# What a launcher sets for the app it starts, all describing its own install.
# Anything else named SYNCHOTIC_ is the user's (SYNCHOTIC_LIBRARY, an OAuth
# client, a theme) and has to reach the reopened session too.
_LAUNCHER_SET = ("SYNCHOTIC_OS_DIRS", "SYNCHOTIC_ROOT", "SYNCHOTIC_LEGACY_ROOT",
                 "SYNCHOTIC_LAUNCHER_VERSION", "SYNCHOTIC_LAUNCHER_PATH",
                 "SYNCHOTIC_START_TIME", "SYNCHOTIC_WINDOW_FILE", CLOSE_WINDOW_ENV)


def _others_on_console(launcher, pids=None, name_of=None) -> set:
    """Names of processes attached to this console that are neither the app
    nor the launcher: the shell it was started from, when there is one."""
    ours = {"synchotic-app.exe"}
    if launcher is not None:
        ours.add(Path(launcher).name.lower())
    if pids is None:
        import ctypes
        buffer = (ctypes.c_uint32 * 64)()
        count = ctypes.windll.kernel32.GetConsoleProcessList(buffer, 64)
        pids = list(buffer[:count])
    if name_of is None:
        import psutil

        def name_of(pid):
            try:
                return psutil.Process(pid).name()
            except psutil.Error:
                return ""
    return {name.lower() for name in map(name_of, pids) if name} - ours


def clean_environment(env: dict) -> dict:
    """The environment for the new launcher: none of what the old launcher or
    PyInstaller set for this app. A PyInstaller exe that inherits another's
    _PYI_* variables takes itself for a child of it and misbehaves, and the
    launcher's own variables describe the old launcher's install."""
    env = {k: v for k, v in env.items()
           if k not in _LAUNCHER_SET and not k.startswith(("_PYI", "_MEI"))}
    # PyInstaller points LD_LIBRARY_PATH at its own bundle and keeps the
    # original beside it.
    if "LD_LIBRARY_PATH_ORIG" in env:
        env["LD_LIBRARY_PATH"] = env.pop("LD_LIBRARY_PATH_ORIG")
    else:
        env.pop("LD_LIBRARY_PATH", None)
    return env


def reopen(target: Path, close_window=None) -> None:
    """Start the launcher at `target` as if it had been double-clicked. On
    Windows it gets a console of its own, which is how it knows to move into
    WezTerm rather than stay in the one this app ran in. `close_window` is the
    old window, for the new launcher to close once its own is open."""
    env = clean_environment(os.environ)
    if close_window:
        env[CLOSE_WINDOW_ENV] = str(close_window)
    platform = _platform()
    if platform == "darwin":
        subprocess.Popen(["open", "-n", str(target)], env=env)
    elif platform == "win32":
        CREATE_NEW_CONSOLE = 0x00000010
        subprocess.Popen([str(target)], cwd=str(target.parent), env=env,
                         creationflags=CREATE_NEW_CONSOLE, close_fds=True)
    else:
        # Off this terminal, or the new launcher finds a tty, stays in it
        # instead of opening WezTerm, and this window closes under it.
        subprocess.Popen([str(target)], cwd=str(target.parent), env=env,
                         start_new_session=True, close_fds=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
    debug_log(f"LAUNCHER_UPDATE | reopened {target}")
