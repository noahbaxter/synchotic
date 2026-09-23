#!/usr/bin/env python3
"""
DM Chart Sync - Download charts from Google Drive.

This is the user-facing app that downloads chart files from Google Drive.
File lists are fetched directly from Google Drive API (no manifest needed).
"""

import argparse
import os
import sys

# Increase file descriptor limit for concurrent downloads + extraction
# macOS defaults to 256 which is too low for 24 concurrent downloads
def _increase_file_limit():
    try:
        import resource
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        # Try to increase soft limit to hard limit (or 4096, whichever is lower)
        target = min(hard, 4096)
        if soft < target:
            resource.setrlimit(resource.RLIMIT_NOFILE, (target, hard))
            new_soft, _ = resource.getrlimit(resource.RLIMIT_NOFILE)
            print(f"  File limit: {soft} → {new_soft}")
    except (ImportError, ValueError, OSError):
        pass  # Windows doesn't have resource module, or limit change failed

_increase_file_limit()
from datetime import datetime
from pathlib import Path

from src import copy
from src.core.formatting import count
from src.app.config import API_KEY
from src.app.onboarding import OnboardingMixin
from src.app.drive_management import DriveManagementMixin
from src.app.auth import AuthMixin
from src.app.scan import ScanMixin
from src.app.sync_flow import SyncFlowMixin
from src.drive import DriveClient, AuthManager
from src.sync import FolderSync
from src.config import UserSettings, DrivesConfig, CustomFolders
from src.config.settings import DOWNLOAD_MODES
from src.core.paths import (
    LibraryUnavailable,
    library_is_set,
    get_log_dir,
    get_settings_path,
    get_token_path,
    get_local_manifest_path,
    get_download_path,
    get_drives_config_path,
    migrate_legacy_files,
    migrate_unsanitized_paths,
    cleanup_tmp_dir,
)
from src.ui import (
    print_header,
    show_main_menu_panes,
    show_oauth_prompt,
    compute_main_menu_cache,
)
from src.sync import FolderStatsCache, BackgroundScanner
from src.ui.primitives import CancelInput, clear_screen
from src.ui.screens.first_run import run_setup, setup_needs
from src.ui.widgets import display
from src.ui.primitives.terminal import set_terminal_size
from src.core.logging import TeeOutput, prune_old_logs
from src.drive.client import DriveClientConfig

# ============================================================================
# Main Application
# ============================================================================


class SyncApp(OnboardingMixin, DriveManagementMixin, AuthMixin, ScanMixin, SyncFlowMixin):
    """Main application controller. Behavior lives in the src/app mixins; this
    class owns the state they share and the menu loop in run()."""

    def __init__(self):
        import time as _t
        _t0 = _t.time()

        client_config = DriveClientConfig(api_key=API_KEY)
        self.client = DriveClient(client_config)

        # Load user settings first (needed for sync options)
        self.user_settings = UserSettings.load(get_settings_path())
        self.drives_config = DrivesConfig.load(get_drives_config_path())

        # Load custom folders
        self.custom_folders = CustomFolders.load(get_local_manifest_path())

        # Unified auth manager (handles user + admin fallback, token refresh)
        self.auth = AuthManager(token_path=get_token_path())

        print(f"    [init] configs loaded: {(_t.time() - _t0)*1000:.0f}ms")

        # Clean up any leftover temp files from interrupted operations
        _t1 = _t.time()
        cleanup_tmp_dir()
        print(f"    [init] cleanup_tmp_dir: {(_t.time() - _t1)*1000:.0f}ms")

        self.sync = FolderSync(
            self.client,
            auth_token=self.auth.get_token_getter(),
            download_ignore=self.user_settings.download_ignore,
            download_mode=self.user_settings.download_mode or "rclone",
        )
        self.folders = []
        self.folder_stats_cache = FolderStatsCache()
        self._background_scanner: BackgroundScanner | None = None
        self._library_found: dict = {}

    def _should_offer_signin(self) -> bool:
        """Offered on every start while the chosen mode is missing a sign-in
        and nothing else. Asked of the mode, not of the disk: a credentials.json
        left from trying BYOC once must not prompt an rclone user forever."""
        return (self.auth.is_available
                and not self.auth.is_signed_in
                and self._drive_blocked_step() == "signin")

    def run(self):
        """Main application loop."""
        clear_screen()
        print_header()

        if self._should_offer_signin():
            if show_oauth_prompt():
                self.handle_signin()
                clear_screen()
                print_header()

        import time as _time
        _t_drives = _time.time()
        self.load_drives()
        print(f"  [timing] drives: {(_time.time() - _t_drives)*1000:.0f}ms")
        # However the library got here (setup, SYNCHOTIC_LIBRARY, adoption),
        # a drive it holds charts for is never left off by default.
        self._turn_on_library_drives(undecided_only=True)

        # Start background scanning of folders (if signed in)
        # Force rescan if scan cache is stale (>1hr old)
        from src.sync.cache import get_scan_cache
        newest_scan = get_scan_cache().get_newest_time()
        force = newest_scan is None  # No cache at all
        if newest_scan:
            from datetime import datetime, timezone
            age = (datetime.now(timezone.utc) - newest_scan).total_seconds()
            force = age > get_scan_cache().MAX_AGE_SECONDS
        _t_scan = _time.time()
        self._start_background_scan(force_rescan=force)
        if self._background_scanner:
            print(f"  [timing] bg_scanner started: {(_time.time() - _t_scan)*1000:.0f}ms")

        selected_index = 0  # Track selected position for maintaining after actions
        menu_cache = None  # Cache for expensive menu calculations
        start_time = os.environ.get("SYNCHOTIC_START_TIME")  # For startup timing

        while True:
            # Compute cache if needed (first run or after state-changing actions)
            # Use combined drives config that includes custom folders
            combined_drives = self._get_combined_drives_config()

            if menu_cache is None:
                menu_cache = compute_main_menu_cache(
                    self.folders, self.user_settings,
                    get_download_path(), combined_drives,
                    self.folder_stats_cache,
                    self._background_scanner,
                )

            # Show startup time after first cache computation (actual "ready" state)
            if start_time:
                import time
                elapsed = time.time() - float(start_time)
                print(f"  Ready in {elapsed:.2f}s")
                start_time = None  # Only show once

            action, value, menu_pos = show_main_menu_panes(
                self.folders, self.user_settings, selected_index,
                get_download_path(), combined_drives, cache=menu_cache,
                auth=self.auth,
                background_scanner=self._background_scanner,
                folder_stats_cache=self.folder_stats_cache,
            )
            selected_index = menu_pos  # Always preserve menu position

            if action == "quit":
                self._stop_background_scan()
                from chotic_ui.primitives.host import leave_alt_screen
                leave_alt_screen()
                break

            elif action == "sync":
                if self.folders:
                    result = self.handle_sync()
                    if result is not None:
                        menu_cache = result  # Pre-computed during sync
                    else:
                        menu_cache = None  # Cancelled or no-op, recompute normally
                    # The sync is where a dead grant surfaces, and the menu row
                    # alone does not explain a sign-in that keeps dying weekly.
                    if self.auth and self.auth.session_expired:
                        display.session_expired_notice()
                        from src.ui.primitives import wait_with_skip
                        wait_with_skip(4.0)

            elif action == "rescan":
                self._handle_force_rescan()
                menu_cache = None

            elif action == "library":
                if self.handle_library():
                    menu_cache = None  # different library means different stats


            elif action == "signin":
                self.handle_signin()
                # No cache invalidation needed - just auth state changed

            elif action == "signout":
                self.handle_signout()
                # No cache invalidation needed - just auth state changed

            elif action == "open_data_folder":
                self.handle_open_data_folder()

            elif action == "open_library":
                self.handle_open_library_folder()

            elif action == "download_mode":
                self.handle_download_mode()
                # No cache invalidation needed - only the download tier changed

            elif action == "add_custom":
                if self.handle_add_custom_folder():
                    # Folder already added to self.folders by handle_add_custom_folder
                    menu_cache = None  # Invalidate cache - new folder added

            elif action == "scan_custom":
                folder = self._get_folder_by_id(value)
                if folder:
                    self._scan_single_custom_folder(folder)
                    self.folder_stats_cache.invalidate(value)
                menu_cache = None

            elif action == "remove_custom":
                folder = self._get_folder_by_id(value)
                if folder:
                    self._remove_custom_folder(folder.get("folder_id"), folder.get("name"))
                menu_cache = None


def use_first_run_sandbox() -> Path:
    """Point this run at an empty install in a throwaway temp folder, so a
    machine that already runs Synchotic can show what a new user sees.
    Nothing installed is read or adopted. Returns the folder."""
    import shutil
    import tempfile

    from src.core.legacy_migration import FRESH_ENV
    from src.core.paths import get_drives_config_path

    sandbox = Path(tempfile.mkdtemp(prefix="synchotic-first-run-"))
    # SYNCHOTIC_ROOT moves the bundled drives.json too. Without it the sandbox
    # has no drives, which no real install ever sees.
    drives = get_drives_config_path()
    if drives.exists():
        shutil.copy2(drives, sandbox / drives.name)
    os.environ["SYNCHOTIC_ROOT"] = str(sandbox)
    os.environ["SYNCHOTIC_OS_DIRS"] = "0"
    os.environ[FRESH_ENV] = "1"
    # Both would hand the sandbox a real install to adopt.
    os.environ.pop("SYNCHOTIC_LIBRARY", None)
    os.environ.pop("SYNCHOTIC_LEGACY_ROOT", None)
    return sandbox


def startup_setup(app) -> bool:
    """Ask whatever setup this launch still needs. False means quit.

    Every launch, not just the first: a library and a download mode that can
    download are required, so anything missing or broken since last time is
    asked again here and setup repairs itself.
    """
    first_run = not library_is_set()
    needs = setup_needs(library_set=not first_run,
                        mode_chosen=bool(app.user_settings.download_mode),
                        mode_blocked=app._drive_blocked_step())
    if not needs:
        return True
    if not sys.stdin.isatty():
        print(f"  {copy.SETUP_NEEDS_TERMINAL}")
        sys.exit(1)
    return run_setup(
        needs,
        choose_library=lambda intro, at: app.handle_library(
            intro=intro, setup_step=at),
        choose_mode=lambda intro, at: app.handle_download_mode(
            intro=intro, setup_step=at, esc_label=copy.BTN_QUIT),
        library_is_set=library_is_set,
        mode_chosen=lambda: bool(app.user_settings.download_mode),
        blocked_step=lambda: app._drive_blocked_step(),
        pick_starting_drives=lambda: _found_summary(app),
        first_run=first_run,
    )


def _found_summary(app) -> str:
    """The drives the picked library held, for the last setup page, in home
    screen order. "" when it held none."""
    found = app._library_found
    return display.library_contents(tuple(
        (d.group, d.name, len(found[d.folder_id]))
        for d in app._get_combined_drives_config().drives if d.folder_id in found))


def main():
    """Entry point."""
    import time as _time
    _t0 = _time.time()

    # The menu repaints from cursor-home on every frame and draws the banner
    # itself via chotic-ui's print_header, which is a no-op until the app hands
    # it the art. Without this the first paint wipes the banner for good, and
    # the menu still reserves its 8 lines of height for it.
    from chotic_ui import set_theme
    from chotic_ui.primitives.host import bootstrap, use_alt_screen
    from src.ui.components.header import install_header
    from src.ui.theme import DEFAULT_THEME

    # The .app renames the binary to synchotic-tui so it does not collide with
    # the bundle wrapper, and WezTerm titles the window after whatever program
    # it is running. Say the name we actually want. Also turns on VT processing
    # on Windows consoles, where raw ANSI otherwise renders as literal garbage.
    bootstrap("Synchotic")

    parser = argparse.ArgumentParser(
        description="Synchotic - sync Clone Hero chart packs from Google Drive"
    )
    parser.add_argument(
        "--first-run", "--firsttime", action="store_true", dest="first_run",
        help="run against an empty throwaway install, for seeing what a new "
             "user sees. Nothing on this machine is read or written: no "
             "settings, no sign-in, no library, and no adoption of either.",
    )
    parser.add_argument(
        "--download-mode", choices=DOWNLOAD_MODES, default=None,
        help="how to fetch virus-scan-blocked files: rclone (one Google consent "
             "click), anonymous (skip them), byoc (your own credentials). Saved "
             "for next time. Use anonymous on a machine with no browser.",
    )
    # Parsed before the alternate screen opens. --help and a bad argument both
    # print and exit, and anything printed into that buffer is discarded when
    # the exit handler closes it, so --help showed the user nothing at all.
    cli_args = parser.parse_args()

    if cli_args.first_run:
        sandbox = use_first_run_sandbox()
        # Before the alternate screen opens, so it is still there after quitting.
        print(f"  first-run sandbox: {sandbox}")

    # Everything below draws in the alternate screen buffer. The menus repaint
    # in place from the home position, which only holds if home stays put: on
    # the primary buffer a frame that scrolls, or a window the user drags
    # taller, drags old rows back under the new frame.
    use_alt_screen()

    install_header()

    set_theme(os.environ.get("SYNCHOTIC_THEME") or DEFAULT_THEME)

    # Set terminal size (skip if launched via launcher - it handles this)
    if not os.environ.get("SYNCHOTIC_ROOT"):
        set_terminal_size(90, 40)

    # Always log to .dm-sync/logs/YYYY-MM-DD.log
    logs_dir = get_log_dir()
    logs_dir.mkdir(exist_ok=True)
    prune_old_logs(logs_dir)
    log_path = logs_dir / f"{datetime.now().strftime('%Y-%m-%d')}.log"
    # Read version for log header
    version = None
    version_file = Path(__file__).parent / "VERSION"
    if version_file.exists():
        version = version_file.read_text().strip()
    tee = TeeOutput(log_path, version=version)
    sys.stdout = tee

    print(f"  [timing] imports done: {(_time.time() - _t0)*1000:.0f}ms")

    # The library location has to be known before anything resolves a path.
    # migrate_legacy_files moves markers INTO the library, so if this ran after
    # it, every marker would land in the default library and the real one would
    # look empty, re-downloading the whole collection.
    from src.config.settings import UserSettings as _EarlySettings
    from src.core.paths import get_settings_path as _early_settings_path
    from src.core.paths import set_library_path as _set_library_path
    _early = _EarlySettings.load(_early_settings_path())
    _set_library_path(_early.library_path or None)

    # A library is required now, so an install running on the old default is
    # handed that folder explicitly rather than upgrading into "not set".
    if not _early.library_path:
        from src.core.legacy_migration import default_library_to_adopt
        _adopted = default_library_to_adopt()
        if _adopted:
            from src.core.logging import debug_log as _debug_log
            _early.library_path = str(_adopted)
            _early.save()
            _set_library_path(_adopted)
            _debug_log(f"LIBRARY | adopted former default | {_adopted}")

    # An unreachable library has to stop startup right here. Every path helper
    # below raises once the library is gone, and mkdir on an absent mountpoint
    # would quietly build an empty library that the next sync fills and the
    # remount then hides. Offer a retry so plugging the drive in is enough.
    from src.core.paths import get_library_path as _get_library_path
    from src.core.paths import library_is_available as _library_is_available
    from src.core.paths import plain_path as _plain_path
    while not _library_is_available():
        display.library_unavailable(_plain_path(_get_library_path()))
        if not sys.stdin.isatty():
            sys.exit(1)
        from src.ui.widgets.confirm import ConfirmDialog
        if not ConfirmDialog(f"{copy.UNFINISHED_RETRY}?", copy.LIBRARY_MISSING).run():
            sys.exit(1)

    # A bundle that used to be portable has its settings, token and rclone
    # config in a .dm-sync somewhere. The shim and the launcher both name that
    # folder in SYNCHOTIC_LEGACY_ROOT, so bring it across before anything reads
    # a setting, or the upgrade reads as a factory reset: signed out, no drives
    # enabled, and a re-download of the whole library. Copies, never
    # overwrites, and leaves the old folder alone.
    from src.core.paths import adopt_legacy_install, stale_data_dir_warning
    adopted = adopt_legacy_install()
    if adopted:
        print(f"  {copy.ADOPTED.format(what=', '.join(adopted))}")
    stale = stale_data_dir_warning()
    if stale:
        # Silence here is what turns an upgrade into a factory reset: signed
        # out, no drives, and an empty default library that the next sync fills
        # by downloading the whole collection again.
        print()
        display.say(copy.ADOPT_SKIPPED.format(path=stale))
        print()

    # settings.json is meant to be edited, so write it on the first run, after
    # adoption has had its say about what goes in it.
    from src.core.paths import get_settings_path
    if not get_settings_path().exists():
        UserSettings.load(get_settings_path()).save()

    # Migrate legacy files from old locations to .dm-sync/
    # Must run BEFORE creating SyncApp so paths resolve correctly
    migrated = migrate_legacy_files()
    if migrated:
        print(f"  {copy.ADOPTED.format(what=', '.join(migrated))}")

    renamed = migrate_unsanitized_paths()
    if renamed:
        print(copy.SANITIZED.format(paths=count(len(renamed), "path")))
        for r in renamed:
            print(f"  {r}")

    _t1 = _time.time()
    app = SyncApp()
    if cli_args.download_mode:
        app.user_settings.download_mode = cli_args.download_mode
        app.user_settings.save()
        app.sync.download_mode = cli_args.download_mode

    if not startup_setup(app):
        from chotic_ui.primitives.host import leave_alt_screen
        leave_alt_screen()
        sys.exit(0)
    print(f"  [timing] SyncApp init: {(_time.time() - _t1)*1000:.0f}ms")

    app.run()


def run():
    """main() with Ctrl+C turned into a clean exit."""
    try:
        main()
    except KeyboardInterrupt:
        # Back to the real screen first, or the parting message is written to a
        # buffer that atexit is about to throw away.
        from chotic_ui.primitives.host import leave_alt_screen
        leave_alt_screen()
        print(f"\n\n{copy.CANCELLED}.")
        sys.exit(0)
    except CancelInput:
        # Esc backs out of any prompt, including ones that read a key rather
        # than a line. Uncaught it ended the run on a traceback.
        from chotic_ui.primitives.host import leave_alt_screen
        leave_alt_screen()
        print(f"\n\n{copy.CANCELLED}.")
        sys.exit(0)
    except LibraryUnavailable:
        # The library went away mid-run (a drive unplugged): every path helper
        # raises, and uncaught that is a traceback inside the alternate screen.
        from chotic_ui.primitives.host import leave_alt_screen
        from src.core.paths import get_library_path, plain_path
        leave_alt_screen()
        try:
            display.library_unavailable(plain_path(get_library_path()))
        except Exception:
            print(f"\n\n{copy.LIBRARY_MISSING}. {copy.FIX_RECONNECT}")
        sys.exit(1)


def cli():
    """The `synchotic` command: a checkout run like the installed bundles, which
    export SYNCHOTIC_OS_DIRS=1. SYNCHOTIC_OS_DIRS=0 opts out.

    Only this entry point defaults it. Frozen builds run this file as __main__,
    and the Windows launcher starts a loose executable in the portable layout
    it has always had.
    """
    os.environ.setdefault("SYNCHOTIC_OS_DIRS", "1")
    run()


if __name__ == "__main__":
    run()
