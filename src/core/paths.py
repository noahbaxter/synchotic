"""
Centralized path management for DM Chart Sync.

All app data is stored in .dm-sync/ folder next to the executable.
This makes the app portable - everything stays together.

Directory structure:
    path/to/dm-sync.exe (or sync.py)
    path/to/.dm-sync/
        settings.json       - User preferences (drive toggles, etc.)
        token.json          - User OAuth token (required for scanning and syncing)
        local_manifest.json - Custom drives added by user
        markers/            - Archive sync markers (source of truth)
        logs/               - Debug logs
        stats_cache.json    - Persistent stats for fast startup
    path/to/Sync Charts/    - Downloaded chart files
"""

import os
import sys
from pathlib import Path

import certifi


def get_certifi_ssl_context() -> str:
    """Get path to certifi CA bundle, handling PyInstaller bundles."""
    if getattr(sys, "frozen", False):
        # PyInstaller bundles certifi's cacert.pem
        return str(Path(sys._MEIPASS) / "certifi" / "cacert.pem")
    return certifi.where()


# Directory name for app data (hidden on Unix)
DATA_DIR_NAME = ".dm-sync"

# OS-standard dirs, used when the app ships as a .app in /Applications, where
# writing beside the executable is neither possible nor wanted. Portable installs
# (launcher sitting in a folder, and every dev run) keep the .dm-sync layout, so
# SYNCHOTIC_ROOT still wins when it is set.
APP_DIRNAME = "Synchotic"


OS_DIRS_ENV = "SYNCHOTIC_OS_DIRS"


def _using_os_dirs() -> bool:
    """True only when the caller opts in.

    Opt-in, not inferred: every existing install is portable, and a mode that
    switched itself on whenever SYNCHOTIC_ROOT happened to be unset would also
    override an injected get_app_dir, which is how the tests and every dev run
    point the app at a scratch directory.
    """
    return os.environ.get(OS_DIRS_ENV) == "1"


def _os_dir(kind: str) -> Path:
    """OS-standard data/cache/log dir for this platform."""
    home = Path.home()
    if sys.platform == "darwin":
        return {
            "data": home / "Library" / "Application Support" / APP_DIRNAME,
            "cache": home / "Library" / "Caches" / APP_DIRNAME,
            "logs": home / "Library" / "Logs" / APP_DIRNAME,
        }[kind]
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or (home / "AppData" / "Local"))
        return base / APP_DIRNAME / {"data": "Data", "cache": "Cache", "logs": "Logs"}[kind]
    xdg = {
        "data": os.environ.get("XDG_DATA_HOME") or (home / ".local" / "share"),
        "cache": os.environ.get("XDG_CACHE_HOME") or (home / ".cache"),
        "logs": os.environ.get("XDG_STATE_HOME") or (home / ".local" / "state"),
    }[kind]
    return Path(xdg) / "synchotic"

# Default folder name for downloaded charts
DOWNLOAD_FOLDER_NAME = "Sync Charts"

# Sync state that describes the library rather than the machine. It lives inside
# the library so the library is self-contained: copy or move the folder and its
# state travels with it, and a library on an unmounted volume can never be
# described by markers that are still reachable.
LIBRARY_STATE_DIR_NAME = ".synchotic"

# Set once at startup from user settings. Kept as module state rather than read
# from settings.json on demand, because paths.py must not import settings.
_library_override: "Path | None" = None


# Windows caps a path at MAX_PATH (260) and a directory at 248 unless the call
# opts out with this prefix, and nested chart folders pass that routinely. The
# prefix goes on the library root only, so every derived path inherits it.
# Never mix the two forms: WindowsPath(r"\\?\C:\a") != WindowsPath(r"C:\a"), so
# purge would read tracked files as strays. Markers store library-relative
# paths and are unaffected.
EXTENDED_PREFIX = "\\\\?\\"
EXTENDED_UNC_PREFIX = "\\\\?\\UNC\\"


def _extend(text: str) -> str:
    """The string half of _extended, so it can be tested away from Windows."""
    if text.startswith(EXTENDED_PREFIX):
        return text
    if text.startswith("\\\\"):
        # A UNC share becomes \\?\UNC\NAS\charts, never \\?\\NAS\charts.
        return EXTENDED_UNC_PREFIX + text[2:]
    if len(text) < 2 or text[1] != ":":
        return text  # the prefix needs a full drive-letter path
    return EXTENDED_PREFIX + text


def _extended(path: Path) -> Path:
    """The library root, opted out of MAX_PATH. A no-op off Windows."""
    if os.name != "nt":
        return path
    return Path(_extend(str(path)))


def plain_path(path) -> str:
    """A path as the user would write it, without the MAX_PATH prefix, for
    screens, prompts, pickers and settings."""
    text = str(path)
    if text.startswith(EXTENDED_UNC_PREFIX):
        return "\\\\" + text[len(EXTENDED_UNC_PREFIX):]
    if text.startswith(EXTENDED_PREFIX):
        return text[len(EXTENDED_PREFIX):]
    return text


def set_library_path(path) -> None:
    """Point the app at a library. Call before anything resolves paths."""
    global _library_override
    _library_override = Path(path).expanduser() if path else None


def get_library_path() -> Path:
    """Where charts live. SYNCHOTIC_LIBRARY wins, then settings, then default."""
    env = os.environ.get("SYNCHOTIC_LIBRARY")
    if env:
        return _extended(Path(env).expanduser())
    if _library_override:
        return _extended(_library_override)
    if _using_os_dirs():
        # A .app has no meaningful "next to the executable": that would put the
        # library inside Contents/MacOS, and /Applications is no place for tens
        # of gigabytes of charts. Settings and logs go to the OS dirs; the
        # library is the one thing that needs somewhere a person can find, and
        # Settings > Library moves it.
        return _extended(Path.home() / "Synchotic" / DOWNLOAD_FOLDER_NAME)
    return _extended(get_app_dir() / DOWNLOAD_FOLDER_NAME)


class LibraryUnavailable(RuntimeError):
    """The configured library is not reachable, e.g. an unmounted volume."""


def library_is_available() -> bool:
    """True when a configured library actually exists on disk.

    The default library is created on demand, so it is always available. A
    library the user pointed us at is different: if it lives on a drive that is
    not mounted, the path simply is not there.
    """
    if not _configured_library():
        return True
    return get_library_path().is_dir()


def _configured_library():
    """The user's chosen library, if they chose one."""
    return os.environ.get("SYNCHOTIC_LIBRARY") or _library_override


def library_is_set() -> bool:
    """True when someone chose where charts go. There is no default: purge
    deletes what it did not download, so an unchosen folder must never be
    managed. get_library_path still answers for the state and log dirs, but
    nothing scans, syncs or purges until this is true."""
    return bool(_configured_library())


def library_blocked_reason() -> str:
    """Why nothing may scan or sync right now, or "" when the library is usable.

    A scan writes markers, staging and cache into the library, so an unset or
    unmounted library refuses the work up front rather than at the first mkdir.
    """
    if not library_is_set():
        return "Library not set"
    if not library_is_available():
        return "Library not connected"
    return ""


def get_library_state_dir() -> Path:
    """Library-owned state (markers, staging). Created on demand.

    Refuses to create anything when a configured library is missing. Blindly
    running mkdir on an unmounted volume writes a new empty tree at the
    mountpoint, which reads as a library with no markers, and the next sync
    re-downloads everything into a folder that vanishes on remount.
    """
    library = get_library_path()
    if _configured_library() and not library.is_dir():
        raise LibraryUnavailable(
            f"Library not found: {library}\n"
            "If it lives on an external or network drive, connect it and retry."
        )
    d = library / LIBRARY_STATE_DIR_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def is_library_state_path(path) -> bool:
    """True for anything under the library state dir.

    Library-wide walks must skip it. purge_planner.find_partial_downloads
    rglobs the whole library for _download_*, and staging lives here now.
    """
    state = plain_path(get_library_path() / LIBRARY_STATE_DIR_NAME)
    try:
        Path(plain_path(path)).relative_to(state)
        return True
    except ValueError:
        return False


def get_app_dir() -> Path:
    """
    Get the directory where the app is located.

    For launcher builds: uses SYNCHOTIC_ROOT env var (set by launcher)
    For frozen (PyInstaller): directory containing the executable
    For development: directory containing sync.py (repo root)
    """
    # Launcher sets this to point to the user-facing exe location
    root = os.environ.get("SYNCHOTIC_ROOT")
    if root:
        return Path(root)
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    # Development: repo root (parent of src/core/)
    return Path(__file__).parent.parent.parent


def get_bundle_dir() -> Path:
    """
    Get the directory where bundled resources are located.

    For PyInstaller builds, bundled files are extracted to a temp directory.
    For development, this is the same as get_app_dir().
    """
    if getattr(sys, "frozen", False):
        # PyInstaller extracts bundled files to _MEIPASS temp directory
        return Path(sys._MEIPASS)
    return get_app_dir()


def get_data_dir() -> Path:
    """
    Small precious state: settings, OAuth token, credentials, rclone config.

    Portable installs keep .dm-sync/ next to the executable; a .app uses the
    OS data dir.
    """
    data_dir = _os_dir("data") if _using_os_dirs() else get_app_dir() / DATA_DIR_NAME
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def get_cache_dir() -> Path:
    """Regenerable bulk: scan cache and folder stats. Safe to delete."""
    cache_dir = _os_dir("cache") if _using_os_dirs() else get_app_dir() / DATA_DIR_NAME
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def get_log_dir() -> Path:
    """Debug logs."""
    log_dir = (_os_dir("logs") if _using_os_dirs()
               else get_app_dir() / DATA_DIR_NAME / "logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def get_settings_path() -> Path:
    """Get path to user settings file."""
    return get_data_dir() / "settings.json"


def get_token_path() -> Path:
    """Get path to user OAuth token file."""
    return get_data_dir() / "token.json"


def get_local_manifest_path() -> Path:
    """Get path to local/custom drives manifest file."""
    return get_data_dir() / "local_manifest.json"


def get_sync_state_path() -> Path:
    """Get path to sync state file."""
    return get_data_dir() / "sync_state.json"


def get_download_path() -> Path:
    """Deprecated alias for get_library_path, kept for existing call sites."""
    return get_library_path()


def get_drives_config_path() -> Path:
    """Get path to drives config file (bundled with app)."""
    return get_bundle_dir() / "drives.json"


def get_tmp_dir() -> Path:
    """Staging for downloads and extraction.

    Must sit on the same filesystem as the library: a cross-device move is
    copy-then-delete, not an atomic rename, so a crash mid-move would leave a
    partial file at the destination for purge to judge.
    """
    tmp_dir = get_library_state_dir() / "tmp"
    tmp_dir.mkdir(exist_ok=True)
    return tmp_dir


def get_rclone_dir() -> Path:
    """Get the .dm-sync/rclone/ directory (binary, config, pidfile), creating it."""
    d = get_data_dir() / "rclone"
    d.mkdir(exist_ok=True)
    return d


def get_rclone_binary_path() -> Path:
    """Path to the managed rclone binary (.exe on Windows)."""
    import os
    name = "rclone.exe" if os.name == "nt" else "rclone"
    return get_rclone_dir() / name


def get_rclone_config_path() -> Path:
    """Path to Synchotic's isolated rclone.conf (never the user's global one)."""
    return get_rclone_dir() / "rclone.conf"


def get_rclone_pid_path() -> Path:
    """Path to the rcd daemon pidfile (host:port + pid)."""
    return get_rclone_dir() / "rcd.pid"


def get_extract_tmp_dir() -> Path:
    """Get temp directory for extraction staging."""
    extract_dir = get_tmp_dir() / "extract"
    extract_dir.mkdir(exist_ok=True)
    return extract_dir


# Staging older than this is from a run that is not coming back.
STAGING_MAX_AGE_SECONDS = 3600


def cleanup_tmp_dir():
    """Drop staging left behind by an interrupted run (call on startup).

    Extraction stages a whole unpacked chart inside the library, and purge
    deliberately never walks the library state dir, so a hard kill mid-extract
    leaves that copy with nothing in the app that would ever remove it. This
    pointed at the data dir until now, which is a folder nothing has staged into
    since staging moved into the library, so it cleaned nothing at all.

    Resolves the path without creating anything: an install that never syncs
    should not get a library folder made for it on startup.

    Only touches staging that has sat untouched for an hour. Nothing stops a
    second copy of the app being launched, and clearing the folder wholesale
    would delete the extraction the first one is in the middle of.
    """
    import shutil
    import time

    if not library_is_available():
        return
    tmp_dir = get_library_path() / LIBRARY_STATE_DIR_NAME / "tmp"
    if not tmp_dir.is_dir():
        return
    cutoff = time.time() - STAGING_MAX_AGE_SECONDS
    for parent in (tmp_dir, tmp_dir / "extract"):
        if not parent.is_dir():
            continue
        for entry in parent.iterdir():
            if entry.name == "extract":
                continue
            try:
                if entry.stat().st_mtime > cutoff:
                    continue
                if entry.is_dir():
                    shutil.rmtree(entry)
                else:
                    entry.unlink()
            except OSError:
                pass


# Callers reach migration through `paths`; it lives in legacy_migration.py.
from .legacy_migration import (  # noqa: E402,F401
    LEGACY_ROOT_ENV,
    legacy_install_candidates,
    adopt_legacy_install,
    stale_data_dir_warning,
    find_legacy_install,
    find_legacy_markers,
    migrate_to_os_dirs,
    migrate_legacy_files,
    migrate_unsanitized_paths,
)
