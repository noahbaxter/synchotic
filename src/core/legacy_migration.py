"""
Legacy-install migration for DM Chart Sync.

Brings a previous install's state (settings, token, markers, custom folders,
unsanitized paths on disk) into wherever this version expects it.

Path getters are called as `paths.<name>` so a later set_library_path() or a
monkeypatched getter is still seen.
"""

import os
from pathlib import Path

from . import paths


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
    roots.append(Path.home() / paths.APP_DIRNAME)

    found = {}
    for root in roots:
        for base in (root, root.parent):
            for name in (paths.DATA_DIR_NAME, paths.LIBRARY_STATE_DIR_NAME):
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
    if not paths._using_os_dirs():
        return []
    candidates = legacy_install_candidates()
    if not candidates:
        return []
    if paths.get_settings_path().exists():
        return []
    return migrate_to_os_dirs(candidates[0])


def stale_data_dir_warning() -> str:
    """A settings file here, and a livelier one in an install we did not adopt.

    Says so instead of booting into whichever happened to be in the way, which
    is how a February dev build silently beat a live install.
    """
    if not paths._using_os_dirs():
        return ""
    dest = paths.get_settings_path()
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
        for name in (paths.DATA_DIR_NAME, paths.LIBRARY_STATE_DIR_NAME):
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

    if not paths._using_os_dirs():
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
    legacy = root if root.name in (paths.DATA_DIR_NAME, paths.LIBRARY_STATE_DIR_NAME) else (root / paths.DATA_DIR_NAME)
    if not legacy.is_dir():
        return []

    done = []
    for kind, names in _MIGRATION_MAP.items():
        dest_dir = {"data": paths.get_data_dir, "cache": paths.get_cache_dir, "logs": paths.get_log_dir}[kind]()
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
        if legacy_markers.is_dir() and paths.library_is_available():
            dest_markers = paths.get_library_state_dir() / "markers"
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

    if paths._library_override or os.environ.get("SYNCHOTIC_LIBRARY"):
        return
    try:
        data = json.loads(paths.get_settings_path().read_text())
    except Exception:
        return
    adopted = data.get("library_path") if isinstance(data, dict) else ""
    if adopted:
        paths.set_library_path(adopted)


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
    data_dir = paths.get_data_dir()
    app_dir = paths.get_app_dir()
    download_dir = paths.get_download_path()

    # =========================================================================
    # MIGRATIONS: Old locations -> new .dm-sync/ folder
    # =========================================================================
    migrations = [
        (app_dir / "user_settings.json", paths.get_settings_path(), "user_settings.json"),
        (app_dir / "user_token.json", paths.get_token_path(), "user_token.json"),
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
    if paths.library_is_available() and legacy_markers.is_dir():
        new_markers = paths.get_library_state_dir() / "markers"
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

    flag_file = paths.get_data_dir() / ".paths_sanitized"
    if flag_file.exists():
        return []

    download_dir = paths.get_download_path()
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
