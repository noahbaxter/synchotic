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
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from typing import NoReturn
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

_start_time = time.time()

GITHUB_REPO = "noahbaxter/synchotic"
GITHUB_API_BASE = f"https://api.github.com/repos/{GITHUB_REPO}/releases"


def get_release_url() -> str:
    """Get the release API URL, checking for test override."""
    for i, arg in enumerate(sys.argv):
        if arg == "--test-release" and i + 1 < len(sys.argv):
            tag = sys.argv[i + 1]
            print(f"  [TEST MODE] Using release: {tag}")
            return f"{GITHUB_API_BASE}/tags/{tag}"
    return f"{GITHUB_API_BASE}/latest"


def is_offline_mode() -> bool:
    """Check if running in offline mode (skip update check)."""
    return "--offline" in sys.argv


def get_launcher_dir() -> Path:
    """Get directory containing the launcher exe."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent


def get_launcher_path() -> Path:
    """Get full path to the launcher exe."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable)
    return Path(__file__)


def get_app_dir() -> Path:
    """Get the extracted app directory."""
    return get_launcher_dir() / ".dm-sync" / "_app"


def get_dm_sync_dir() -> Path:
    """Get the .dm-sync directory."""
    return get_launcher_dir() / ".dm-sync"


def get_app_exe_name() -> str:
    """Get the main app executable name for this platform."""
    if sys.platform == "win32":
        return "synchotic-app.exe"
    return "synchotic-app"


def get_asset_name() -> str:
    """Get the release asset name for this platform."""
    if sys.platform == "win32":
        return "app-windows.zip"
    return "app-macos.zip"


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


# --- Directory change handling ---

def _save_launcher_state(current_path: str):
    """Save current launcher path to state file."""
    state = read_state()
    state["launcher_path"] = current_path
    state["last_run"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    write_state(state)


def _prompt_directory_action() -> str:
    """Prompt user for directory change action. Returns 'M', 'D', or 'I'."""
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
    print(f"\nDeleting old data at {old_dm_sync}...")
    try:
        shutil.rmtree(old_dm_sync)
        print("Done!")
    except Exception as e:
        print(f"Warning: Failed to delete: {e}")
        print("Continuing anyway...")


def _do_move(old_dm_sync: Path) -> bool:
    """Move old .dm-sync to new location. Returns True on success."""
    new_dm_sync = get_dm_sync_dir()

    if new_dm_sync.exists():
        print(f"\nNote: {new_dm_sync} already exists, removing it first...")
        try:
            shutil.rmtree(new_dm_sync)
        except Exception as e:
            print(f"Failed to remove existing folder: {e}")
            return False

    print("\nMoving data to new location...")
    try:
        shutil.move(str(old_dm_sync), str(new_dm_sync))
        print("Done!")
        return True
    except Exception as e:
        print(f"Failed to move: {e}")
        return False


def _prompt_fallback() -> str:
    """Prompt for fallback action after move fails. Returns 'D' or 'I'."""
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
    old_path = read_state().get("launcher_path")

    # First run or same location
    if not old_path or old_path == current_path:
        _save_launcher_state(current_path)
        return

    old_dm_sync = Path(old_path).parent / ".dm-sync"

    # Old location has no data
    if not old_dm_sync.exists():
        _save_launcher_state(current_path)
        return

    # Prompt user
    print(f"\nIt looks like you moved the launcher from:")
    print(f"  {Path(old_path).parent}")
    print(f"\nFound cached app data at old location.")

    choice = _prompt_directory_action()

    if choice == "M":
        if not _do_move(old_dm_sync):
            choice = _prompt_fallback()

    if choice == "D":
        _do_delete(old_dm_sync)
    elif choice == "I":
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
        with urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except HTTPError as e:
        if e.code == 403:
            error_exit("GitHub API rate limit reached. Try again in a few minutes.")
        elif e.code == 404:
            error_exit("Release not found. Check the repository URL.")
        else:
            error_exit(f"GitHub API error: HTTP {e.code}")
    except URLError as e:
        error_exit(f"Could not reach GitHub. Check your internet connection.\n\nDetails: {e.reason}")
    except Exception as e:
        error_exit(f"Unexpected error checking for updates: {e}")


def get_download_url(release: dict) -> tuple[str, str]:
    """Get download URL and version from release info."""
    version = release.get("tag_name", "").lstrip("v")
    asset_name = get_asset_name()

    for asset in release.get("assets", []):
        if asset.get("name") == asset_name:
            return asset.get("browser_download_url"), version

    error_exit(f"Release asset '{asset_name}' not found.\nThis platform may not be supported yet.")


def download_with_progress(url: str, dest: Path):
    """Download file with progress bar."""
    req = Request(url)
    req.add_header("User-Agent", "synchotic-launcher")

    try:
        with urlopen(req, timeout=120) as resp:
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
        error_exit(f"Download failed. Check your connection.\n\nDetails: {e.reason}")
    except Exception as e:
        error_exit(f"Download failed: {e}")


# --- Extraction ---

def extract_app(zip_path: Path, version: str):
    """Extract app zip to .dm-sync/_app/ atomically."""
    app_dir = get_app_dir()
    temp_dir = app_dir.parent / "_app_temp"

    if temp_dir.exists():
        shutil.rmtree(temp_dir)

    print("  Extracting...")
    try:
        temp_dir.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(temp_dir)

        if app_dir.exists():
            shutil.rmtree(app_dir)

        temp_dir.rename(app_dir)
        (app_dir / ".version").write_text(version)

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

def error_exit(message: str) -> NoReturn:
    """Print error message and exit."""
    print(f"\n{'=' * 40}")
    print("ERROR")
    print("=" * 40)
    print(f"\n{message}")
    print("\nPress Enter to exit...")
    try:
        input()
    except (EOFError, KeyboardInterrupt):
        pass
    sys.exit(1)


def set_terminal_size(cols: int = 90, rows: int = 40):
    """Set terminal window size."""
    if sys.platform == "win32":
        try:
            subprocess.run(
                f"mode con: cols={cols} lines={rows}",
                shell=True,
                capture_output=True,
            )
        except Exception:
            pass


def main():
    set_terminal_size(90, 40)

    print("\nSynchotic Launcher")
    print("=" * 40)

    handle_directory_change()

    app_exe = get_app_dir() / get_app_exe_name()

    if is_offline_mode():
        print("[OFFLINE MODE] Skipping update check...")
        if not app_exe.exists():
            error_exit("No cached app found. Run without --offline to download.")
    else:
        print("Checking for updates...")
        release = fetch_latest_release()
        download_url, remote_version = get_download_url(release)

        installed_version = get_installed_version()

        needs_download = False
        if not app_exe.exists():
            print(f"  App not installed, downloading v{remote_version}...")
            needs_download = True
        elif installed_version != remote_version:
            print(f"  Update available: v{installed_version} -> v{remote_version}")
            needs_download = True
        else:
            print(f"  Up to date (v{installed_version})")

        if needs_download:
            with tempfile.TemporaryDirectory() as tmp:
                zip_path = Path(tmp) / "app.zip"
                print("\nDownloading...")
                download_with_progress(download_url, zip_path)
                extract_app(zip_path, remote_version)
                print("  Done!")

    if not app_exe.exists():
        error_exit(f"App executable not found after installation:\n{app_exe}")

    print(f"\nLaunching synchotic...")
    print("=" * 40 + "\n")

    # Filter out launcher-specific args before passing to app
    launcher_flags = {"--offline"}
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
    env = os.environ.copy()
    env["SYNCHOTIC_ROOT"] = str(get_launcher_dir())
    env["SYNCHOTIC_START_TIME"] = str(_start_time)

    if sys.platform == "win32":
        result = subprocess.run(args, env=env)
        sys.exit(result.returncode)
    else:
        os.execve(str(app_exe), args, env)


if __name__ == "__main__":
    main()
