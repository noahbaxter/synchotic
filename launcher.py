#!/usr/bin/env python3
"""
Synchotic Launcher

Tiny launcher that fetches the app from GitHub releases.
- Checks for updates on every launch
- Downloads and extracts new versions automatically
- Handles directory changes (prompts to move/delete old data)
"""

import json
import os
import shutil
import ssl
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from typing import NoReturn
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

LAUNCHER_VERSION = "1.2"
RELEASE_TAG = ""  # Injected to "dev-latest" for dev launcher builds
WEZTERM_VERSION = "20240203-110809-5046fc22"  # Windows/Linux host, downloaded first-run
LINUX_WM_CLASS = "synchotic"  # must match the .desktop basename, or KDE cannot pair them


def get_ssl_context():
    """Get SSL context with certifi certs, handling PyInstaller bundles."""
    try:
        import certifi

        if getattr(sys, "frozen", False):
            cafile = str(Path(sys._MEIPASS) / "certifi" / "cacert.pem")
        else:
            cafile = certifi.where()
        return ssl.create_default_context(cafile=cafile)
    except ImportError:
        return ssl.create_default_context()

_start_time = time.time()
_log_file = None

GITHUB_REPO = "noahbaxter/synchotic"
GITHUB_API_BASE = f"https://api.github.com/repos/{GITHUB_REPO}/releases"


def get_release_url() -> str:
    """Get the release API URL, checking for test override and build-time channel."""
    for i, arg in enumerate(sys.argv):
        if arg == "--test-release" and i + 1 < len(sys.argv):
            tag = sys.argv[i + 1]
            print(f"  [TEST MODE] Using release: {tag}")
            return f"{GITHUB_API_BASE}/tags/{tag}"
    if RELEASE_TAG:
        return f"{GITHUB_API_BASE}/tags/{RELEASE_TAG}"
    return f"{GITHUB_API_BASE}/latest"


def is_offline_mode() -> bool:
    """Check if running in offline mode (skip update check)."""
    return "--offline" in sys.argv


def is_dev_mode() -> bool:
    """Check if running in dev mode (use local zip, no GitHub).

    Dev mode is active if:
    - --dev flag is passed, OR
    - A local app zip exists in the launcher directory (auto-detect for dev builds)
    """
    if "--dev" in sys.argv:
        return True
    # Auto-detect: if local zip exists, assume dev mode
    return get_local_zip_path().exists()


def is_clean_mode() -> bool:
    """Check if running in clean mode (nuke .dm-sync/ first)."""
    return "--clean" in sys.argv


def is_bundled() -> bool:
    """True when we are a .app or an AppImage rather than a loose executable.

    Those installs belong in /Applications or the app menu, not in the user's
    chart folder, so nothing may be written beside them: a .app would be
    writing into itself, and an AppImage into a mount that disappears.
    """
    if os.environ.get("APPIMAGE"):
        return True
    if not getattr(sys, "frozen", False):
        return False
    return any(p.suffix == ".app" for p in Path(sys.executable).parents)


def os_data_dir() -> Path:
    """The platform's application-support directory, matching src/core/paths.

    Both halves have to agree on this: the launcher writes its payload and logs
    here, and the app it starts resolves the same place from SYNCHOTIC_OS_DIRS.
    """
    home = Path.home()
    if sys.platform == "darwin":
        d = home / "Library" / "Application Support" / "Synchotic"
    elif sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or (home / "AppData" / "Local"))
        d = base / "Synchotic" / "Data"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or (home / ".local" / "share"))
        d = base / "synchotic"
    d.mkdir(parents=True, exist_ok=True)
    return d


def app_environment() -> dict:
    """The environment the app is started with, which is where it puts its files.

    A bundle gets SYNCHOTIC_OS_DIRS, not SYNCHOTIC_ROOT. SYNCHOTIC_ROOT is the
    portable layout and takes priority in src/core/paths.get_app_dir, so setting
    it as well would nest a .dm-sync inside Application Support. A loose
    executable keeps the portable layout it has always had.
    """
    env = os.environ.copy()
    if is_bundled():
        env["SYNCHOTIC_OS_DIRS"] = "1"
        env.pop("SYNCHOTIC_ROOT", None)
        # Bundles were portable until now, keeping .dm-sync beside themselves.
        # Name that folder so the app can adopt the settings and sign-in that
        # are sitting in it rather than starting from nothing.
        legacy = portable_dir()
        if legacy:
            env["SYNCHOTIC_LEGACY_ROOT"] = str(legacy)
    else:
        env["SYNCHOTIC_ROOT"] = str(get_launcher_dir())
    return env


def portable_dir() -> Path | None:
    """Where this install would have kept its files under the portable layout.

    Only used to find what an older version left behind: beside the .app, or
    beside the AppImage. None when neither applies.
    """
    appimage = os.environ.get("APPIMAGE")
    if appimage:
        return Path(appimage).parent
    if getattr(sys, "frozen", False):
        for parent in Path(sys.executable).parents:
            if parent.suffix == ".app":
                return parent.parent
    return None


def get_launcher_dir() -> Path:
    """The folder the launcher owns: the downloaded payload and its logs.

    A loose executable keeps the portable layout it has always had, writing
    .dm-sync/ beside itself. A bundle cannot, so it uses the OS data dir. Note
    this is no longer where charts go: the app resolves the library itself and
    defaults it to ~/Synchotic/Sync Charts.
    """
    override = os.environ.get("SYNCHOTIC_LAUNCHER_DIR")
    if override:
        return Path(override)
    if is_bundled():
        return os_data_dir()
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent


def get_launcher_path() -> Path:
    """Get full path to the launcher exe."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable)
    return Path(__file__)


def desktop_exec_path() -> Path:
    """What a .desktop entry should point Exec at.

    Inside an AppImage the running binary lives in a squashfs mount that is
    unmounted on exit, so an entry naming it would be dead by the time anyone
    clicked it. $APPIMAGE is the file the user actually keeps.
    """
    appimage = os.environ.get("APPIMAGE")
    return Path(appimage) if appimage else get_launcher_path()


def get_app_dir() -> Path:
    """Get the extracted app directory. Dev channel uses separate dir to coexist with production."""
    subdir = "_app_dev" if RELEASE_TAG else "_app"
    return get_dm_sync_dir() / subdir


def get_dm_sync_dir() -> Path:
    """Where the payload and the launcher's own logs go.

    A portable install hides them in .dm-sync so the folder the user picked for
    charts is not littered with our files. The OS data dir is already ours and
    already out of sight, so nesting a hidden folder inside it buys nothing.
    """
    return get_launcher_dir() if is_bundled() else get_launcher_dir() / ".dm-sync"


def get_app_exe_name() -> str:
    """Get the main app executable name for this platform."""
    if sys.platform == "win32":
        return "synchotic-app.exe"
    return "synchotic-app"


def get_asset_name() -> str:
    """Get the release asset name for this platform."""
    if sys.platform == "win32":
        return "app-windows.zip"
    if sys.platform.startswith("linux"):
        return "app-linux.zip"
    return "app-macos.zip"


def get_local_zip_path() -> Path:
    """Get path to local app zip (same folder as launcher)."""
    return get_launcher_dir() / get_asset_name()


def get_version_file() -> Path:
    """Get path to version marker file."""
    return get_app_dir() / ".version"


def get_installed_version() -> str:
    """Get version of currently extracted app."""
    version_file = get_version_file()
    if version_file.exists():
        return version_file.read_text().strip()
    return ""


# --- State file management ---

def get_state_dir() -> Path:
    """Get the directory for launcher state file."""
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA", "")
        if appdata:
            return Path(appdata) / "synchotic"
    return Path.home() / ".synchotic"


def get_state_file() -> Path:
    """Get path to state file."""
    return get_state_dir() / "state.json"


def read_state() -> dict:
    """Read launcher state from file."""
    state_file = get_state_file()
    if state_file.exists():
        try:
            return json.loads(state_file.read_text())
        except (json.JSONDecodeError, IOError):
            pass
    return {}


def write_state(state: dict):
    """Write launcher state to file."""
    state_file = get_state_file()
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps(state, indent=2))


# --- Logging ---

def init_logging():
    """Initialize daily log file."""
    global _log_file
    log_dir = get_dm_sync_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    date_str = time.strftime("%Y-%m-%d")
    log_path = log_dir / f"launcher-{date_str}.log"
    try:
        _log_file = open(log_path, "a", encoding="utf-8")
        log(f"=== Launcher started at {time.strftime('%Y-%m-%d %H:%M:%S')} ===")
    except Exception:
        pass


def log(message: str):
    """Write message to log file."""
    if _log_file:
        try:
            timestamp = time.strftime("%H:%M:%S")
            _log_file.write(f"[{timestamp}] {message}\n")
            _log_file.flush()
        except Exception:
            pass


def close_logging():
    """Close log file."""
    global _log_file
    if _log_file:
        try:
            log("=== Launcher exiting ===")
            _log_file.close()
        except Exception:
            pass
        _log_file = None


# --- Directory change handling ---

def _state_key() -> str:
    """State key prefix so dev and prod launchers don't share state."""
    return "dev" if RELEASE_TAG else "prod"


def _save_launcher_state(current_path: str):
    """Save current launcher path to state file."""
    key = _state_key()
    state = read_state()
    state[f"launcher_path_{key}"] = current_path
    state[f"last_run_{key}"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    # Migrate: remove old shared keys so they don't cause false triggers
    state.pop("launcher_path", None)
    state.pop("last_run", None)
    write_state(state)


def _has_terminal() -> bool:
    """Check if we have an interactive terminal for prompts."""
    try:
        return sys.stdin is not None and sys.stdin.isatty()
    except Exception:
        return False


def _prompt_directory_action() -> str:
    """Prompt user for directory change action. Returns 'M', 'D', or 'I'."""
    # No terminal - auto-ignore to avoid blocking
    if not _has_terminal():
        log("No terminal available, auto-ignoring old data")
        return "I"

    print("\nWhat would you like to do?")
    print("  [M] Move the data to the new location (faster startup)")
    print("  [D] Delete the old data (fresh download)")
    print("  [I] Ignore (leave old data, download fresh here)")

    while True:
        try:
            choice = input("\nChoice [M/D/I]: ").strip().upper()
        except (EOFError, KeyboardInterrupt):
            print("\nCancelled.")
            sys.exit(1)

        if choice in ("M", "D", "I"):
            return choice
        print("Please enter M, D, or I.")


def _do_delete(old_dm_sync: Path):
    """Delete old .dm-sync folder."""
    log(f"Deleting old data: {old_dm_sync}")
    print(f"\nDeleting old data at {old_dm_sync}...")
    try:
        shutil.rmtree(old_dm_sync)
        print("Done!")
    except Exception as e:
        log(f"Delete failed: {e}")
        print(f"Warning: Failed to delete: {e}")
        print("Continuing anyway...")


def _do_move(old_dm_sync: Path) -> bool:
    """Move old .dm-sync to new location. Returns True on success."""
    new_dm_sync = get_dm_sync_dir()
    log(f"Moving data: {old_dm_sync} -> {new_dm_sync}")

    if new_dm_sync.exists():
        print(f"\nNote: {new_dm_sync} already exists, removing it first...")
        try:
            shutil.rmtree(new_dm_sync)
        except Exception as e:
            log(f"Failed to remove existing folder: {e}")
            print(f"Failed to remove existing folder: {e}")
            return False

    print("\nMoving data to new location...")
    try:
        shutil.move(str(old_dm_sync), str(new_dm_sync))
        print("Done!")
        return True
    except Exception as e:
        log(f"Move failed: {e}")
        print(f"Failed to move: {e}")
        return False


def _prompt_fallback() -> str:
    """Prompt for fallback action after move fails. Returns 'D' or 'I'."""
    # No terminal - auto-ignore
    if not _has_terminal():
        log("No terminal available, auto-ignoring after move failure")
        return "I"

    print("\nWould you like to:")
    print("  [D] Delete the old data instead")
    print("  [I] Ignore and download fresh")

    while True:
        try:
            choice = input("\nChoice [D/I]: ").strip().upper()
        except (EOFError, KeyboardInterrupt):
            print("\nCancelled.")
            sys.exit(1)

        if choice in ("D", "I"):
            return choice
        print("Please enter D or I.")


def handle_directory_change():
    """Check if launcher moved and handle old .dm-sync folder."""
    current_path = str(get_launcher_path())
    key = _state_key()
    state = read_state()
    old_path = state.get(f"launcher_path_{key}") or state.get("launcher_path")

    # First run or same location
    if not old_path or old_path == current_path:
        _save_launcher_state(current_path)
        return

    old_dm_sync = Path(old_path).parent / ".dm-sync"

    # Old location has no data
    if not old_dm_sync.exists():
        _save_launcher_state(current_path)
        return

    log(f"Launcher moved: {old_path} -> {current_path}")

    # Prompt user
    print(f"\nIt looks like you moved the launcher from:")
    print(f"  {Path(old_path).parent}")
    print(f"\nFound cached app data at old location.")

    choice = _prompt_directory_action()
    log(f"User chose: {choice}")

    if choice == "M":
        if not _do_move(old_dm_sync):
            choice = _prompt_fallback()

    if choice == "D":
        _do_delete(old_dm_sync)
    elif choice == "I":
        log("Ignoring old data")
        print("\nIgnoring old data, will download fresh.")

    _save_launcher_state(current_path)
    print()


# --- GitHub API ---

def fetch_latest_release() -> dict:
    """Fetch latest release info from GitHub API."""
    url = get_release_url()
    req = Request(url)
    req.add_header("Accept", "application/vnd.github.v3+json")
    req.add_header("User-Agent", "synchotic-launcher")

    try:
        with urlopen(req, timeout=30, context=get_ssl_context()) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except HTTPError as e:
        if e.code == 403:
            error_exit("GitHub API rate limit reached. Try again in a few minutes.")
        elif e.code == 404:
            error_exit("Release not found. Check the repository URL.")
        else:
            error_exit(f"GitHub API error: HTTP {e.code}")
    except URLError as e:
        reason = str(e.reason)
        if "WRONG_VERSION_NUMBER" in reason:
            error_exit(
                "Could not reach GitHub: SSL/TLS error.\n\n"
                "This usually means a proxy or firewall is intercepting the connection.\n"
                "Try disabling VPN/proxy or using a different network.\n"
                f"\nDetails: {reason}"
            )
        elif "CERTIFICATE" in reason:
            error_exit(
                f"Could not reach GitHub: SSL certificate error.\n\n"
                f"Launcher v{LAUNCHER_VERSION} - update at https://github.com/{GITHUB_REPO}/releases\n"
                f"\nDetails: {reason}"
            )
        else:
            error_exit(f"Could not reach GitHub. Check your internet connection.\n\nDetails: {reason}")
    except Exception as e:
        error_exit(f"Unexpected error checking for updates: {e}")


def get_download_url(release: dict) -> tuple[str, str]:
    """Get download URL and version from release info.

    For dev builds, uses asset's updated_at as version since the tag
    (dev-latest) never changes but the asset does on every push.
    """
    version = release.get("tag_name", "").lstrip("v")
    asset_name = get_asset_name()

    for asset in release.get("assets", []):
        if asset.get("name") == asset_name:
            if RELEASE_TAG:
                version = asset.get("updated_at", version)
            return asset.get("browser_download_url"), version

    error_exit(f"Release asset '{asset_name}' not found.\nThis platform may not be supported yet.")


def download_with_progress(url: str, dest: Path):
    """Download file with progress bar."""
    req = Request(url)
    req.add_header("User-Agent", "synchotic-launcher")

    try:
        with urlopen(req, timeout=120, context=get_ssl_context()) as resp:
            total_size = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            chunk_size = 64 * 1024

            dest.parent.mkdir(parents=True, exist_ok=True)

            with open(dest, "wb") as f:
                while True:
                    chunk = resp.read(chunk_size)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)

                    if total_size > 0:
                        pct = downloaded * 100 // total_size
                        bar_len = 30
                        filled = pct * bar_len // 100
                        bar = "=" * filled + "-" * (bar_len - filled)
                        mb_down = downloaded / (1024 * 1024)
                        mb_total = total_size / (1024 * 1024)
                        print(f"\r  [{bar}] {pct:3}% ({mb_down:.1f}/{mb_total:.1f} MB)", end="", flush=True)

            print()

    except HTTPError as e:
        error_exit(f"Failed to download update: HTTP {e.code}")
    except URLError as e:
        reason = str(e.reason)
        if "WRONG_VERSION_NUMBER" in reason:
            error_exit(
                "Download failed: SSL/TLS error.\n\n"
                "This usually means a proxy or firewall is intercepting the connection.\n"
                "Try disabling VPN/proxy or using a different network.\n"
                f"\nDetails: {reason}"
            )
        elif "CERTIFICATE" in reason:
            error_exit(
                f"Download failed: SSL certificate error.\n\n"
                f"Launcher v{LAUNCHER_VERSION} - update at https://github.com/{GITHUB_REPO}/releases\n"
                f"\nDetails: {reason}"
            )
        else:
            error_exit(f"Download failed. Check your connection.\n\nDetails: {reason}")
    except Exception as e:
        error_exit(f"Download failed: {e}")


# --- Extraction ---

def extract_app(zip_path: Path, version: str):
    """Extract app zip to .dm-sync/_app/ atomically."""
    app_dir = get_app_dir()
    temp_dir = app_dir.parent / "_app_temp"
    old_dir = app_dir.parent / "_app_old"

    if temp_dir.exists():
        shutil.rmtree(temp_dir)

    print("  Extracting...")
    try:
        temp_dir.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(zip_path, "r") as zf:
            # Not extractall: it drops the Unix permission bits, which the zip
            # carries in the top half of external_attr. The app exe gets a chmod
            # later, but every other bundled binary does not, so unrar installed
            # non-executable and rarfile failed every RAR with "Cannot find
            # working tool". Windows zips record mode 0, so they skip this.
            for info in zf.infolist():
                target = zf.extract(info, temp_dir)
                mode = info.external_attr >> 16
                if mode & 0o777:
                    os.chmod(target, mode & 0o777)

        # Swap: rename old out of the way, move new in, then delete old.
        # If anything fails mid-swap, at least one copy survives.
        if old_dir.exists():
            shutil.rmtree(old_dir)
        if app_dir.exists():
            app_dir.rename(old_dir)

        temp_dir.rename(app_dir)
        (app_dir / ".version").write_text(version)

        # Clean up old version
        if old_dir.exists():
            shutil.rmtree(old_dir, ignore_errors=True)

    except zipfile.BadZipFile:
        error_exit("Downloaded file is corrupted. Please try again.")
    except PermissionError as e:
        error_exit(f"Permission denied during extraction.\n\nDetails: {e}")
    except Exception as e:
        error_exit(f"Extraction failed: {e}")
    finally:
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)


# --- Main ---

def wait_for_keypress():
    """Wait for any key press."""
    if sys.platform == "win32":
        import msvcrt
        msvcrt.getch()
    else:
        import termios
        import tty
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            sys.stdin.read(1)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)


def error_exit(message: str) -> NoReturn:
    """Print error message and exit."""
    log(f"ERROR: {message}")
    close_logging()
    print(f"\n{'=' * 40}")
    print("ERROR")
    print("=" * 40)
    print(f"\n{message}")
    print("\nPress any key to exit...")
    try:
        wait_for_keypress()
    except (EOFError, KeyboardInterrupt, Exception):
        pass
    sys.exit(1)


def set_terminal_size(cols: int = 90, rows: int = 40):
    """Set terminal window size. Works on cmd.exe and PowerShell, not Windows Terminal."""
    if sys.platform == "win32":
        os.system(f"mode con: cols={cols} lines={rows}")
    else:
        # macOS/Linux: ANSI escape sequence
        print(f"\x1b[8;{rows};{cols}t", end="", flush=True)




# =============================================================================
# WezTerm host
#
# A Finder or Explorer launch has no usable terminal, and this is a TUI. Rather
# than hand the app to Terminal.app and inherit whatever the user configured
# there, run it inside a WezTerm we control: bundled in the .app on macOS,
# downloaded once on Windows and Linux.
# =============================================================================

def should_relaunch_in_host(argv, has_terminal: bool, wezterm_exists: bool) -> bool:
    """True when we should re-exec into the WezTerm host: a GUI launch (no
    controlling terminal), not already hosted, and WezTerm present. The
    `--hosted` sentinel is the recursion guard; the hosted copy has a tty."""
    return "--hosted" not in argv and not has_terminal and wezterm_exists


def build_host_command(wezterm: str, lua: str, cwd: str, launcher_path: str, forward_args: list,
                       wm_class: str = "") -> list:
    """argv to run this launcher inside the WezTerm GUI with our config.

    wm_class sets WezTerm's Wayland app_id / X11 window class. Without it the
    window reports itself as org.wezfurlong.wezterm, so the desktop pairs it
    with WezTerm's own .desktop file and the taskbar shows a WezTerm button
    instead of Synchotic."""
    klass = ["--class", wm_class] if wm_class else []
    return [
        wezterm, "--config-file", lua,
        "start", "--always-new-process", "--cwd", cwd, *klass,
        "--", launcher_path, *forward_args, "--hosted",
    ]


def host_environment() -> dict:
    """The environment to hand the WezTerm host.

    PyInstaller's onefile bootloader marks its process tree with _PYI_*
    variables. Those survive the exec into WezTerm and reach the launcher copy
    WezTerm spawns, which then sees _PYI_PARENT_PROCESS_LEVEL, decides it is an
    unpacking child, checks that its parent runs the same executable, finds
    wezterm-gui instead, and exits before it can log anything.

    On Linux the onefile bootloader also points LD_LIBRARY_PATH at _MEIPASS,
    which would shadow the system libssl/libcrypto for WezTerm. PyInstaller
    stashes the pre-launch value in LD_LIBRARY_PATH_ORIG; put it back."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("_PYI_")}
    if sys.platform.startswith("linux") and getattr(sys, "frozen", False):
        orig = env.pop("LD_LIBRARY_PATH_ORIG", None)
        if orig is None:
            env.pop("LD_LIBRARY_PATH", None)
        else:
            env["LD_LIBRARY_PATH"] = orig
    env["SYNCHOTIC_WINDOW_FILE"] = str(window_state_file())
    return env


def window_state_file() -> Path:
    """Where the host config remembers the window size. The lua has no way to
    work out an OS data dir, so hand it the path."""
    home = Path.home()
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or (home / "AppData" / "Local"))
        return base / "Synchotic" / "Data" / "window.txt"
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / "Synchotic" / "window.txt"
    base = Path(os.environ.get("XDG_DATA_HOME") or (home / ".local" / "share"))
    return base / "synchotic" / "window.txt"


def wezterm_dir() -> Path:
    """Cache dir for the first-run-downloaded Windows WezTerm."""
    return get_dm_sync_dir() / "wezterm"


def host_paths() -> tuple:
    """(wezterm-gui, wezterm.lua) for this platform's host."""
    if sys.platform == "win32":
        d = wezterm_dir()
        return d / "wezterm-gui.exe", d / "wezterm.lua"
    if sys.platform.startswith("linux"):
        d = wezterm_dir()
        return d / "squashfs-root" / "usr" / "bin" / "wezterm-gui", d / "wezterm.lua"
    exe_dir = Path(sys.executable).parent
    return exe_dir / "wezterm-gui", exe_dir.parent / "Resources" / "wezterm.lua"


def _resource_path(name: str):
    """Locate a data file bundled into the frozen exe, falling back to the
    source tree for dev runs."""
    candidates = []
    meipass = getattr(sys, "_MEIPASS", "")
    if meipass:
        candidates.append(Path(meipass) / name)
    here = Path(__file__).parent / "packaging"
    candidates += [here / "macos" / name, here / "windows" / name, here / "linux" / name]
    return next((c for c in candidates if c.exists()), None)


def _double_clicked_windows() -> bool:
    """True when launched from Explorer (we own our console), so a launch from
    an existing cmd/PowerShell is left alone."""
    try:
        import ctypes

        arr = (ctypes.c_uint32 * 8)()
        n = ctypes.windll.kernel32.GetConsoleProcessList(arr, 8)
        return n <= 1
    except Exception:
        return False


def _hide_windows_console():
    """Hide our own console so the re-exec into WezTerm does not flash one."""
    try:
        import ctypes

        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)  # SW_HIDE
    except Exception:
        pass


def ensure_wezterm_windows() -> bool:
    """Download and cache the Windows WezTerm portable build on first run."""
    d = wezterm_dir()
    gui = d / "wezterm-gui.exe"
    lua = d / "wezterm.lua"
    d.mkdir(parents=True, exist_ok=True)
    lua_src = _resource_path("wezterm.lua")
    if lua_src and not lua.exists():
        shutil.copyfile(lua_src, lua)
    if gui.exists():
        return True
    url = (f"https://github.com/wezterm/wezterm/releases/download/"
           f"{WEZTERM_VERSION}/WezTerm-windows-{WEZTERM_VERSION}.zip")
    print("  Fetching WezTerm (terminal window, ~25MB, first run only)...")
    log(f"Downloading WezTerm: {url}")
    try:
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "wezterm.zip"
            with urlopen(Request(url, headers={"User-Agent": "synchotic-launcher"}),
                         context=get_ssl_context()) as r, open(archive, "wb") as f:
                shutil.copyfileobj(r, f)
            with zipfile.ZipFile(archive) as zf:
                zf.extractall(tmp)
            found = list(Path(tmp).rglob("wezterm-gui.exe"))
            if not found:
                log("WezTerm archive missing wezterm-gui.exe")
                return False
            for item in found[0].parent.iterdir():
                dest = d / item.name
                if item.is_dir():
                    shutil.copytree(item, dest, dirs_exist_ok=True)
                else:
                    shutil.copyfile(item, dest)
        return gui.exists()
    except Exception as e:
        log(f"WezTerm download failed: {e}")
        return False


def ensure_wezterm_linux() -> bool:
    """Download and unpack the WezTerm AppImage on first run.

    Unpacked with --appimage-extract rather than run as an AppImage: mounting one
    needs libfuse2, which the atomic Fedora spins (Bazzite, Kinoite) do not ship.
    The extracted tree runs straight from disk with no FUSE involved."""
    d = wezterm_dir()
    gui, lua = host_paths()
    d.mkdir(parents=True, exist_ok=True)
    lua_src = _resource_path("wezterm.lua")
    if lua_src and not lua.exists():
        shutil.copyfile(lua_src, lua)
    if gui.exists():
        return True
    url = (f"https://github.com/wezterm/wezterm/releases/download/"
           f"{WEZTERM_VERSION}/WezTerm-{WEZTERM_VERSION}-Ubuntu20.04.AppImage")
    print("  Fetching WezTerm (terminal window, ~50MB, first run only)...")
    log(f"Downloading WezTerm: {url}")
    try:
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "wezterm.AppImage"
            with urlopen(Request(url, headers={"User-Agent": "synchotic-launcher"}),
                         context=get_ssl_context()) as r, open(image, "wb") as f:
                shutil.copyfileobj(r, f)
            os.chmod(image, 0o755)
            shutil.rmtree(d / "squashfs-root", ignore_errors=True)
            result = subprocess.run(
                [str(image), "--appimage-extract"], cwd=str(d),
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            )
            if result.returncode != 0:
                log(f"AppImage extract failed: {result.stderr.decode(errors='replace')[:400]}")
                return False
        return gui.exists()
    except Exception as e:
        log(f"WezTerm download failed: {e}")
        return False


def maybe_relaunch_in_host():
    """Re-exec into a WezTerm window when launched from a GUI."""
    if "--hosted" in sys.argv:
        return
    if sys.platform == "darwin":
        wezterm, lua = host_paths()
        if not should_relaunch_in_host(sys.argv, _has_terminal(), wezterm.exists()):
            return
    elif sys.platform == "win32":
        if not _double_clicked_windows():
            return
        wezterm, lua = host_paths()
        if wezterm.exists():
            _hide_windows_console()  # cached: skip the console flash
        if not ensure_wezterm_windows():
            return  # download failed: run inline in this console
    elif sys.platform.startswith("linux"):
        if _has_terminal():
            return  # started from a shell: stay in it
        wezterm, lua = host_paths()
        if not ensure_wezterm_linux():
            return
    else:
        return

    cmd = build_host_command(
        str(wezterm), str(lua), str(get_launcher_dir()),
        str(get_launcher_path()), sys.argv[1:],
        LINUX_WM_CLASS if sys.platform.startswith("linux") else "",
    )
    env = host_environment()
    if sys.platform == "win32":
        DETACHED_PROCESS = 0x00000008
        subprocess.Popen(cmd, creationflags=DETACHED_PROCESS, close_fds=True, env=env)
        sys.exit(0)
    os.execve(str(wezterm), cmd, env)  # replaces this process; does not return


def ensure_linux_desktop():
    """Install a .desktop entry + icon so Synchotic shows up in the app menu.

    Terminal=false on purpose: the launcher opens its own WezTerm window, and
    handing the entry to the distro's terminal is what it used to do -- on KDE
    that produced an empty window and no app."""
    if not sys.platform.startswith("linux") or not getattr(sys, "frozen", False):
        return
    try:
        share = Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share"))
        apps = share / "applications"
        icons = share / "icons" / "hicolor" / "256x256" / "apps"
        apps.mkdir(parents=True, exist_ok=True)
        icons.mkdir(parents=True, exist_ok=True)

        icon_dest = icons / "synchotic.png"
        icon_src = _resource_path("synchotic.png")
        if icon_src and not icon_dest.exists():
            shutil.copyfile(icon_src, icon_dest)

        content = (
            "[Desktop Entry]\n"
            "Type=Application\n"
            "Name=Synchotic\n"
            "Comment=Sync Clone Hero charts from Google Drive\n"
            f'Exec="{desktop_exec_path()}"\n'
            "Terminal=false\n"
            "Icon=synchotic\n"
            "Categories=Game;\n"  # one main category: two makes it show up twice in some menus
            f"StartupWMClass={LINUX_WM_CLASS}\n"  # X11 pairing; Wayland matches on app_id
            "StartupNotify=true\n"
        )
        desktop = apps / "synchotic.desktop"
        if not desktop.exists() or desktop.read_text() != content:
            desktop.write_text(content)
            log("Installed/updated synchotic.desktop")
    except Exception as e:
        log(f"desktop install skipped: {e}")


def main():
    maybe_relaunch_in_host()  # may re-exec into WezTerm and not return
    set_terminal_size(90, 40)
    init_logging()
    log(f"Launcher v{LAUNCHER_VERSION}")
    ensure_linux_desktop()

    if RELEASE_TAG:
        print(f"\nSynchotic Launcher v{LAUNCHER_VERSION} [DEV]")
    else:
        print(f"\nSynchotic Launcher v{LAUNCHER_VERSION}")
    print("=" * 40)

    # Handle --dev: local development mode
    if is_dev_mode():
        log("Dev mode")
        print("[DEV MODE]")

        local_zip = get_local_zip_path()
        app_dir = get_app_dir()

        # --clean: nuke entire .dm-sync/
        if is_clean_mode():
            dm_sync = get_dm_sync_dir()
            if dm_sync.exists():
                log(f"Clean mode - deleting {dm_sync}")
                close_logging()
                print(f"  Cleaning {dm_sync}...")
                shutil.rmtree(dm_sync)
                init_logging()

        if local_zip.exists():
            # Zip found: replace _app only, delete zip after
            log(f"Found local zip: {local_zip}")
            print(f"  Found: {local_zip.name}")

            # Remove old _app if exists
            if app_dir.exists():
                shutil.rmtree(app_dir)

            extract_app(local_zip, "dev")
            print("  Extracted!")

            # Delete the zip
            local_zip.unlink()
            log("Deleted zip after extraction")
            print("  Zip deleted.")
        elif app_dir.exists():
            # No zip, but _app exists - use it
            log("No zip found, using existing _app")
            print("  No zip found, using existing app.")
        else:
            error_exit("No local zip and no existing app. Run build.sh dev first.")

    elif is_offline_mode():
        log("Offline mode - skipping update check")
        print("[OFFLINE MODE] Skipping update check...")
        app_exe = get_app_dir() / get_app_exe_name()
        if not app_exe.exists():
            error_exit("No cached app found. Run without --offline to download.")
    else:
        handle_directory_change()

        print("Checking for updates...")
        release = fetch_latest_release()
        download_url, remote_version = get_download_url(release)
        log(f"Remote version: v{remote_version}")

        installed_version = get_installed_version()
        log(f"Installed version: v{installed_version}" if installed_version else "No version installed")

        needs_download = False
        app_exe = get_app_dir() / get_app_exe_name()
        if not app_exe.exists():
            log("App not installed, will download")
            print(f"  App not installed, downloading v{remote_version}...")
            needs_download = True
        elif installed_version != remote_version:
            log(f"Update available: v{installed_version} -> v{remote_version}")
            print(f"  Update available: v{installed_version} -> v{remote_version}")
            needs_download = True
        else:
            log("Already up to date")
            print(f"  Up to date (v{installed_version})")

        if needs_download:
            with tempfile.TemporaryDirectory() as tmp:
                zip_path = Path(tmp) / "app.zip"
                print("\nDownloading...")
                log(f"Downloading from: {download_url}")
                download_with_progress(download_url, zip_path)
                extract_app(zip_path, remote_version)
                log(f"Extracted v{remote_version}")
                print("  Done!")

    app_exe = get_app_dir() / get_app_exe_name()

    if not app_exe.exists():
        error_exit(f"App executable not found after installation:\n{app_exe}")

    # Ensure executable permission on macOS/Linux
    if sys.platform != "win32":
        os.chmod(app_exe, 0o755)

    log(f"Launching app: {app_exe}")
    print(f"\nLaunching synchotic...")
    print("=" * 40 + "\n")

    # Filter out launcher-specific args before passing to app
    launcher_flags = {"--offline", "--dev", "--clean", "--hosted"}
    launcher_opts = {"--test-release"}  # These consume the next arg too
    filtered_args = []
    skip_next = False
    for arg in sys.argv[1:]:
        if skip_next:
            skip_next = False
        elif arg in launcher_opts:
            skip_next = True
        elif arg not in launcher_flags:
            filtered_args.append(arg)

    args = [str(app_exe)] + filtered_args
    env = app_environment()
    env["SYNCHOTIC_START_TIME"] = str(_start_time)

    close_logging()

    if sys.platform == "win32":
        result = subprocess.run(args, env=env)
        sys.exit(result.returncode)
    else:
        os.execve(str(app_exe), args, env)


if __name__ == "__main__":
    main()
