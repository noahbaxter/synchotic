"""
Centralized path management for DM Chart Sync.

All app data is stored in .dm-sync/ folder next to the executable.
This makes the app portable - everything stays together.

Directory structure:
    path/to/dm-sync.exe (or sync.py)
    path/to/.dm-sync/
        settings.json       - User preferences (drive toggles, etc.)
        token.json          - User OAuth token (optional sign-in)
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

# Default folder name for downloaded charts
DOWNLOAD_FOLDER_NAME = "Sync Charts"


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
    Get the .dm-sync/ data directory, creating it if needed.

    All user-writable app data goes here.
    """
    data_dir = get_app_dir() / DATA_DIR_NAME
    data_dir.mkdir(exist_ok=True)
    return data_dir


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
    """Get the download directory for chart files."""
    return get_app_dir() / DOWNLOAD_FOLDER_NAME


def get_drives_config_path() -> Path:
    """Get path to drives config file (bundled with app)."""
    return get_bundle_dir() / "drives.json"


def get_tmp_dir() -> Path:
    """Get temp directory for downloads and extraction staging."""
    tmp_dir = get_data_dir() / "tmp"
    tmp_dir.mkdir(exist_ok=True)
    return tmp_dir


def get_extract_tmp_dir() -> Path:
    """Get temp directory for extraction staging."""
    extract_dir = get_tmp_dir() / "extract"
    extract_dir.mkdir(exist_ok=True)
    return extract_dir


def cleanup_tmp_dir():
    """Clean up temp directory (call on startup)."""
    import shutil
    tmp_dir = get_data_dir() / "tmp"
    if tmp_dir.exists():
        try:
            shutil.rmtree(tmp_dir)
        except Exception:
            pass


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
