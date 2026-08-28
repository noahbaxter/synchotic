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


LEGACY_ROOT_ENV = "SYNCHOTIC_LEGACY_ROOT"  # test hook

# Which legacy .dm-sync entries belong in which new home. "markers" is absent on
# purpose: it goes into the library, not a machine dir, and is handled below.
_MIGRATION_MAP = {
    "data": ["settings.json", "token.json", "credentials.json",
             "local_manifest.json", "sync_state.json", "rclone",
             ".paths_sanitized"],
    "cache": ["folder_stats.json", "scan_cache", "stats_cache.json"],
    "logs": ["logs"],
}


def legacy_install_candidates(explicit=None) -> list:
    """Every folder a previous install could have left its state in, newest first.

    There are three, and missing any of them reads to the user as a factory
    reset: signed out, no drives, and a library default that points somewhere
    empty, which the next sync fills by downloading everything again.

    * the folder the user just picked in the library screen
    * SYNCHOTIC_LEGACY_ROOT, which the bundles set to the folder they sit in
      (os.pathsep separates several)
    * ~/Synchotic, where the macOS shim put everything before the OS dirs

    Ordered by the mtime of the settings inside, so the liveliest install wins
    over one left behind by an old build.
    """
    roots = []
    if explicit:
        roots.append(Path(explicit))
    env = os.environ.get(LEGACY_ROOT_ENV) or ""
    roots += [Path(r) for r in env.split(os.pathsep) if r]
    roots.append(Path.home() / APP_DIRNAME)

    found = {}
    for root in roots:
        for base in (root, root.parent):
            for name in (DATA_DIR_NAME, LIBRARY_STATE_DIR_NAME):
                candidate = base / name
                if candidate.is_dir() and candidate not in found:
                    settings = candidate / "settings.json"
                    found[candidate] = settings.stat().st_mtime if settings.exists() else 0
    return [c for c, _ in sorted(found.items(), key=lambda kv: kv[1], reverse=True)]


def adopt_legacy_install() -> list:
    """Bring a previous install into the OS dirs, once, at startup.

    Only when there is nothing here yet. An OS data dir that already holds
    settings is either a real install or, for anyone who ever ran a dev build,
    months-old leftovers. Copying over the first would be destructive and
    telling the two apart automatically is guesswork, so that case is reported
    rather than resolved.
    """
    if not _using_os_dirs():
        return []
    candidates = legacy_install_candidates()
    if not candidates:
        return []
    if get_settings_path().exists():
        return []
    return migrate_to_os_dirs(candidates[0])


def stale_data_dir_warning() -> str:
    """A settings file here, and a livelier one in an install we did not adopt.

    Says so instead of booting into whichever happened to be in the way, which
    is how a February dev build silently beat a live install.
    """
    if not _using_os_dirs():
        return ""
    dest = get_settings_path()
    if not dest.exists():
        return ""
    for candidate in legacy_install_candidates():
        settings = candidate / "settings.json"
        if settings.exists() and settings.stat().st_mtime > dest.stat().st_mtime:
            return str(candidate)
    return ""


def find_legacy_install(library_path):
    """Locate a pre-1.5 install given the library the user just pointed at.

    v1.4.2 told users to drop the launcher into a folder; it then made
    `.dm-sync/` and `Sync Charts/` beside itself. So the state dir is either in
    the folder they picked or one level up if they picked the charts folder.
    `.synchotic` is checked too because that is the current name.
    """
    library_path = Path(library_path)
    for base in (library_path, library_path.parent):
        for name in (DATA_DIR_NAME, LIBRARY_STATE_DIR_NAME):
            if (base / name).is_dir():
                return base / name
    return None


def find_legacy_markers(library_path):
    """Markers from any pre-1.5 layout, under either state-dir name."""
    state = find_legacy_install(library_path)
    if state is None:
        return None
    markers = state / "markers"
    return markers if markers.is_dir() else None


def migrate_to_os_dirs(legacy_root=None) -> list:
    """Copy a portable .dm-sync into the OS dirs the .app uses.

    Copies rather than moves, and never overwrites: the source folder holds the
    OAuth token and the library_path setting, so a half-finished move would cost
    a user their sign-in and point the purge planner at an empty library. The
    legacy folder is left exactly as it was and can be deleted by hand.
    """
    import shutil

    if not _using_os_dirs():
        return []
    # v1.4.2 and earlier told users to drop the launcher into their own songs
    # folder (README step 2), so the legacy root is wherever they put it. There
    # is no default worth guessing: the caller supplies it, normally from the
    # folder the user picks in the library screen.
    root = legacy_root or os.environ.get(LEGACY_ROOT_ENV)
    if not root:
        return []
    root = Path(root)
    # Accept either the folder that holds the state dir or the state dir itself.
    legacy = root if root.name in (DATA_DIR_NAME, LIBRARY_STATE_DIR_NAME) else (root / DATA_DIR_NAME)
    if not legacy.is_dir():
        return []

    done = []
    for kind, names in _MIGRATION_MAP.items():
        dest_dir = {"data": get_data_dir, "cache": get_cache_dir, "logs": get_log_dir}[kind]()
        for name in names:
            src = legacy / name
            if not src.exists():
                continue
            # logs/ maps onto the log dir itself, not a "logs" child of it
            dest = dest_dir if (kind == "logs" and name == "logs") else dest_dir / name
            try:
                # Settings must merge, never skip: the library screen has
                # already written a settings.json holding the new library_path,
                # so a plain skip would silently drop every v1.4.2 preference
                # (drive toggles, download_mode, purge_ignore).
                if name == "settings.json" and dest.exists():
                    if _merge_settings(src, dest):
                        done.append("settings.json (merged)")
                    continue
                if src.is_dir():
                    # Skip when the copy would add nothing: dest already has
                    # content, or src is an empty dir we already created.
                    if dest.exists() and (any(dest.iterdir()) or not any(src.iterdir())):
                        continue
                    shutil.copytree(src, dest, dirs_exist_ok=True)
                else:
                    if dest.exists():
                        continue
                    shutil.copy2(src, dest)
                done.append(name)
            except Exception:
                pass

    # The settings we just brought across name the library. Startup resolved
    # that before this file existed, so until it is applied the session is still
    # pointed at the default, and everything below writes into the wrong folder.
    _apply_adopted_library()

    # Markers describe the charts, so they belong with them rather than in a
    # machine dir. 2500 of these are the difference between adopting a library
    # and re-downloading it.
    try:
        legacy_markers = legacy / "markers"
        if legacy_markers.is_dir() and library_is_available():
            dest_markers = get_library_state_dir() / "markers"
            dest_markers.mkdir(parents=True, exist_ok=True)
            copied = 0
            for m in legacy_markers.iterdir():
                # macOS writes ._ AppleDouble sidecars on non-native volumes.
                if m.name.startswith("._") or not m.is_file():
                    continue
                target = dest_markers / m.name
                if target.exists():
                    continue
                shutil.copy2(m, target)
                copied += 1
            if copied:
                done.append(f"markers ({copied})")
    except Exception:
        pass
    return done


def _apply_adopted_library() -> None:
    """Point this session at the library the adopted settings name.

    Startup has to resolve the library before it can read a setting, and on the
    launch that adopts a previous install there is no setting to read yet. The
    marker copy below then lands in the default library, and every path for the
    rest of the run resolves there too: markers split across two folders, and a
    sync that downloads a second copy of the collection into the wrong one.

    Never overrides a library already chosen. The library screen calls adoption
    with the folder the user just picked, and that pick wins.
    """
    import json

    if _library_override or os.environ.get("SYNCHOTIC_LIBRARY"):
        return
    try:
        data = json.loads(get_settings_path().read_text())
    except Exception:
        return
    adopted = data.get("library_path") if isinstance(data, dict) else ""
    if adopted:
        set_library_path(adopted)


# The library screen writes the folder the user just picked before adopting, so
# that one field is always right in the destination. Everything else in a
# destination file is only trustworthy if it is not older than what we are
# adopting.
_PICKED_BY_THIS_SESSION = ("library_path",)

_MISSING = object()


def _default_settings() -> dict:
    """What a settings file holds before anyone has chosen anything.

    A value equal to its default is the absence of a preference, not one, so it
    must never beat a real choice from the install being adopted. Without this
    the destination file the library screen has just written is a wall of
    defaults that wins every key it has: an import kept the drive toggles, whose
    default is empty, and silently reset delete_videos, delta_mode and
    purge_ignore, whose defaults are not.
    """
    from ..config.settings import UserSettings

    probe = vars(UserSettings(Path(".")))
    defaults = {k: v for k, v in probe.items()
                if k != "path" and not k.startswith("_")}
    defaults["use_default_drives"] = probe.get("_is_new")
    return defaults


def _merge_settings(legacy_file, dest_file) -> bool:
    """Fill the new settings from the old, keeping anything already set.

    A destination written more recently wins conflicts, which is the point: the
    library screen has just put the new library_path there. When the
    destination is the older file it wins nothing but that path, or a stale
    settings.json left by a build from months ago silently beats a live
    install, taking the sign-in and every drive toggle with it.
    """
    import json

    try:
        legacy = json.loads(legacy_file.read_text())
        current = json.loads(dest_file.read_text())
    except Exception:
        return False
    if not isinstance(legacy, dict) or not isinstance(current, dict):
        return False
    defaults = _default_settings()
    keep = {k: v for k, v in current.items()
            if v not in ("", None, {}, []) and v != defaults.get(k, _MISSING)}
    if legacy_file.stat().st_mtime > dest_file.stat().st_mtime:
        keep = {k: v for k, v in keep.items() if k in _PICKED_BY_THIS_SESSION}
    merged = {**legacy, **keep}
    if merged == current:
        return False
    dest_file.write_text(json.dumps(merged, indent=2))
    return True


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


def set_library_path(path) -> None:
    """Point the app at a library. Call before anything resolves paths."""
    global _library_override
    _library_override = Path(path).expanduser() if path else None


def get_library_path() -> Path:
    """Where charts live. SYNCHOTIC_LIBRARY wins, then settings, then default."""
    env = os.environ.get("SYNCHOTIC_LIBRARY")
    if env:
        return Path(env).expanduser()
    if _library_override:
        return _library_override
    if _using_os_dirs():
        # A .app has no meaningful "next to the executable": that would put the
        # library inside Contents/MacOS, and /Applications is no place for tens
        # of gigabytes of charts. Settings and logs go to the OS dirs; the
        # library is the one thing that needs somewhere a person can find, and
        # Settings > Library moves it.
        return Path.home() / "Synchotic" / DOWNLOAD_FOLDER_NAME
    return get_app_dir() / DOWNLOAD_FOLDER_NAME


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


def library_blocked_reason() -> str:
    """Why nothing may scan or sync right now, or "" when the library is usable.

    A scan writes into the library: markers, staging, the scan cache keyed to
    it. A library on a drive that is no longer mounted has nowhere to put that,
    so the work is refused up front instead of at the first mkdir several
    screens in. An unset library is not a case: every install resolves to a
    default, and only a folder that went missing can be unusable.
    """
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
    try:
        Path(path).relative_to(get_library_path() / LIBRARY_STATE_DIR_NAME)
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


def _is_marker_name(name: str) -> bool:
    """A real marker, not a macOS AppleDouble sidecar sitting beside one."""
    return name.endswith(".json") and not name.startswith("._")


def migrate_legacy_files() -> list[str]:
    """
    Migrate files from old locations and clean up obsolete files.

    This is the SINGLE place for all legacy file handling. If we stop using
    a file/format, add it here for cleanup.

    Returns:
        List of files that were migrated/cleaned (for logging).
    """
    import shutil

    migrated = []
    data_dir = get_data_dir()
    app_dir = get_app_dir()
    download_dir = get_download_path()

    # =========================================================================
    # MIGRATIONS: Old locations -> new .dm-sync/ folder
    # =========================================================================
    migrations = [
        (app_dir / "user_settings.json", get_settings_path(), "user_settings.json"),
        (app_dir / "user_token.json", get_token_path(), "user_token.json"),
    ]

    for old_path, new_path, name in migrations:
        if old_path.exists() and not new_path.exists():
            try:
                old_path.rename(new_path)
                migrated.append(f"migrated {name}")
            except Exception:
                try:
                    shutil.copy2(old_path, new_path)
                    old_path.unlink()
                    migrated.append(f"migrated {name}")
                except Exception:
                    pass

    # Markers moved from the machine data dir into the library, so they travel
    # with the charts they describe. Without this move a v1.4 user loses every
    # marker and the next sync re-downloads everything.
    #
    # Every decision here is per marker, never "has the migration run yet". A
    # library on another volume makes each move a cross-device copy-then-delete,
    # so a run over thousands of markers can be interrupted part way. Keying the
    # work off whether the destination directory is empty would strand whatever
    # had not moved yet: the next launch would see a non-empty destination and
    # skip the rest forever. A stranded marker is not a cosmetic loss. Purge
    # treats files that no marker claims as extras, so the charts it described
    # get deleted on the next sync.
    legacy_markers = data_dir / "markers"
    if library_is_available() and legacy_markers.is_dir():
        new_markers = get_library_state_dir() / "markers"
        new_markers.mkdir(parents=True, exist_ok=True)
        moved = failed = 0
        for marker in legacy_markers.iterdir():
            if not marker.is_file():
                continue
            dest = new_markers / marker.name
            if dest.exists():
                # A resumed run already moved this one. Marker filenames carry
                # the archive path and md5, so the same name is the same marker.
                try:
                    marker.unlink()
                except OSError:
                    failed += 1
                continue
            try:
                shutil.move(str(marker), str(dest))
                # Count real markers only. macOS writes ._ AppleDouble sidecars
                # next to every file on SMB shares, and they are worth draining
                # with the rest but not worth reporting as migrated markers.
                if _is_marker_name(marker.name):
                    moved += 1
            except Exception:
                failed += 1
        if moved:
            migrated.append(f"moved {moved} markers into the library")
        if failed:
            # Never silent. Reporting a short count beats claiming success while
            # the charts those markers described are queued for deletion.
            migrated.append(
                f"{failed} marker(s) could not be moved, retrying on next launch"
            )
        try:
            legacy_markers.rmdir()
        except OSError:
            pass

    # =========================================================================
    # OBSOLETE FILES: Delete files we no longer use
    # =========================================================================
    obsolete_files = [
        # sync_state.json - replaced by marker files
        data_dir / "sync_state.json",
        download_dir / ".dm-sync" / "sync_state.json",
        # manifest.json - no longer used, data comes from Google Drive API
        data_dir / "manifest.json",
        app_dir / "manifest.json",
    ]

    for path in obsolete_files:
        if path.exists():
            try:
                path.unlink()
                migrated.append(f"removed {path.name}")
            except Exception:
                pass

    # =========================================================================
    # OBSOLETE DIRECTORIES: Remove empty/obsolete directories
    # =========================================================================
    obsolete_dirs = [
        # Old .dm-sync under Sync Charts (data moved to app-level .dm-sync)
        download_dir / ".dm-sync",
    ]

    for dir_path in obsolete_dirs:
        if dir_path.exists():
            try:
                # Try to remove if empty
                dir_path.rmdir()
                migrated.append(f"removed {dir_path.name}/")
            except OSError:
                # Not empty - try removing all contents if it's truly obsolete
                # For now, just leave non-empty dirs alone
                pass

    return migrated


def migrate_unsanitized_paths() -> list[str]:
    """
    One-time migration: rename files/dirs that don't match sanitized names.

    Introduced when sanitize_drive_name() started replacing colons with " -".
    Directories on disk still had old names (with colons), causing marker/path
    mismatches and unnecessary re-downloads.

    Walks Sync Charts/ bottom-up and renames anything where
    sanitize_filename(name) != name. Skips if already done (flag file).
    """
    from src.core.formatting import sanitize_filename

    flag_file = get_data_dir() / ".paths_sanitized"
    if flag_file.exists():
        return []

    download_dir = get_download_path()
    if not download_dir.exists():
        flag_file.touch()
        return []

    renamed = []
    for dirpath, dirnames, filenames in os.walk(download_dir, topdown=False):
        parent = Path(dirpath)

        for name in filenames + dirnames:
            sanitized = sanitize_filename(name)
            if sanitized != name:
                old = parent / name
                new = parent / sanitized
                if new.exists():
                    continue
                try:
                    old.rename(new)
                    renamed.append(f"{name} -> {sanitized}")
                except OSError:
                    pass

    flag_file.touch()
    return renamed
