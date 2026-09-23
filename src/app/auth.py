"""Sign-in/out, library location, download mode, and the "can we even reach
Drive or the library right now" checks everything else gates on."""

from src.sync import FolderSync
from src.core.logging import debug_log
from src.ui.primitives import wait_with_skip
from src.ui.widgets import display


class AuthMixin:

    def handle_signin(self):
        """Handle Google sign-in."""
        display.auth_opening_browser()

        if self.auth.sign_in():
            print("  Signed in successfully!")
            # Recreate sync with new token
            self._refresh_sync_token()
        else:
            # Do not keep pointing at sign-in once it has already failed.
            display.sign_in_failed_notice()

        wait_with_skip(2)

    def handle_library(self) -> bool:
        """Change where charts live, then re-read what is actually there.

        Returns whether the library actually moved. Backing out with Esc used to
        cost the same two-second pause and the same full stats rebuild as a real
        move, which made cancelling feel like the app had hung.
        """
        from src.ui.screens import show_library_screen
        if not show_library_screen(self.user_settings):
            return False
        # A dict here would have replaced the cache object outright, leaving
        # later .invalidate()/.set() calls to fail on a plain dict.
        self.folder_stats_cache.invalidate_all()
        wait_with_skip(2)
        return True

    def handle_download_mode(self):
        """Change how blocked charts download, then connect straight away.

        Connecting here rather than at download time means a mode that cannot
        work says so now, instead of stalling for consent mid-sync.
        """
        from src.ui.screens import change_download_mode, connection_step_for

        chosen = change_download_mode(self.user_settings, self.sync)
        if not chosen:
            return

        try:
            import src.rclone as rclone
            # Whether it works, not whether it is configured: picking rclone is
            # how someone asks to fix a dead remote.
            rclone_authed = rclone.connection_state() == rclone.OK
        except Exception:
            rclone_authed = False

        from src.drive.auth import has_custom_client_config

        step = connection_step_for(
            chosen, rclone_authed=rclone_authed,
            signed_in=bool(self.auth and self.auth.is_signed_in),
            byoc_configured=has_custom_client_config(),
        )
        if step == "rclone":
            self._connect_rclone()
        elif step == "signin":
            self.handle_signin()
        elif step == "byoc_setup":
            self._start_byoc_setup()

    def handle_open_data_folder(self):
        """Open the data folder, and say nothing if that worked.

        The folder is now in front of the user; announcing it under the menu
        pushed the whole layout down and held it there for four seconds. The
        path is still worth printing when opening fails, which is the only case
        where the user has to find it themselves."""
        from src.core.files import open_folder
        from src.core.paths import get_data_dir

        data_dir = get_data_dir()
        data_dir.mkdir(parents=True, exist_ok=True)
        if open_folder(data_dir):
            return
        print()
        print("  Could not open your data folder. It is at:")
        print(f"    {data_dir}")
        print()
        wait_with_skip(4)

    def _start_byoc_setup(self):
        """Put the instructions where the credentials go, then open that folder."""
        from src.core.files import open_folder
        from src.drive.auth import write_byoc_instructions

        path = None
        opened = False
        try:
            path = write_byoc_instructions()
            opened = open_folder(path.parent)
        except OSError as e:
            debug_log(f"BYOC_SETUP | could not write instructions | {e}")
        display.byoc_not_configured(instructions_path=path, opened=opened)
        wait_with_skip(8)

    def _connect_rclone(self):
        """Connect rclone, or reconnect one whose access stopped working."""
        import src.rclone as rclone

        if not rclone.can_open_browser():
            display.rclone_no_browser()
            wait_with_skip(3)
            return

        state = rclone.connection_state()
        if state == rclone.OK:
            print("  rclone is already connected.")
            wait_with_skip(2)
            return

        try:
            display.rclone_consent_explainer()
            if state == rclone.DEAD:
                print("  rclone's access stopped working. Asking for it again.")
                connected = rclone.reconnect()
            else:
                connected = rclone.RcloneSession().ensure_authed()

            if connected:
                print("  rclone connected.")
            else:
                print("  Setup cancelled. Large charts stay blocked until rclone connects.")
        except Exception as e:
            print(f"  rclone setup failed: {e}")
        wait_with_skip(3)

    def handle_signout(self):
        """Handle Google sign-out."""
        self.auth.sign_out()
        # Recreate sync without user token (falls back to admin or anonymous)
        self._refresh_sync_token()
        print("\n  Signed out of Google.")
        wait_with_skip(2)

    def _refresh_sync_token(self):
        """Recreate FolderSync with current auth token getter."""
        self.sync = FolderSync(
            self.client,
            auth_token=self.auth.get_token_getter(),
            download_ignore=self.user_settings.download_ignore,
            download_mode=self.user_settings.download_mode or "rclone",
        )

    def _drive_blocked(self) -> str:
        """Why this install cannot reach Drive right now, or "" when it can.

        Not "are we signed in": rclone downloads through its own remote and
        anonymous mode has no token by design, and both scan public folders on
        the API key alone. Requiring OAuth here is what left rclone users
        unable to sync at all once embedded sign-in stopped being available.
        """
        from src.ui.screens.download_mode import mode_blocked_reason
        try:
            import src.rclone as rclone
            rclone_authed = rclone.is_authed()
        except Exception:
            rclone_authed = False
        return mode_blocked_reason(self.user_settings, self.auth, rclone_authed)

    def _library_blocked(self) -> str:
        """Why the library cannot take a scan right now, or "" when it can."""
        from src.core.paths import library_blocked_reason

        return library_blocked_reason()
