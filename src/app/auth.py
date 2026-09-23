"""Sign-in/out, library location, download mode, and the "can we even reach
Drive or the library right now" checks everything else gates on."""

from src import copy
from src.sync import FolderSync
from src.core.logging import debug_log
from src.ui.primitives import CancelInput, wait_for_key, wait_with_skip
from src.ui.widgets import display


def _pause(prompt: str) -> None:
    """Hold a screen until the user is done with it. Esc ends it too: this is
    the end of a screen, not a question."""
    try:
        wait_for_key(prompt)
    except CancelInput:
        pass


class AuthMixin:

    def _uses_rclone(self) -> bool:
        from src.config.settings import DOWNLOAD_MODE_RCLONE
        return (self.user_settings.download_mode or DOWNLOAD_MODE_RCLONE) == DOWNLOAD_MODE_RCLONE

    def handle_signin(self):
        """Sign in to Google through whatever the mode downloads with: rclone's
        own remote, or Synchotic's OAuth."""
        if self._uses_rclone():
            import src.rclone as rclone
            self._connect_rclone(rclone.connection_state())
            return

        display.auth_opening_browser()

        if self.auth.sign_in():
            print("  Signed in successfully!")
            # Recreate sync with new token
            self._refresh_sync_token()
        else:
            # Do not keep pointing at sign-in once it has already failed.
            display.sign_in_failed_notice()

        wait_with_skip(2)

    def handle_library(self, intro: str = "", setup_step=None) -> bool:
        """Change where charts live, then re-read what is actually there.

        Returns whether the library actually moved. Backing out with Esc used to
        cost the same two-second pause and the same full stats rebuild as a real
        move, which made cancelling feel like the app had hung.
        """
        from src.ui.screens import show_library_screen
        if not show_library_screen(self.user_settings, intro=intro,
                                   setup_step=setup_step):
            return False
        # A dict here would have replaced the cache object outright, leaving
        # later .invalidate()/.set() calls to fail on a plain dict.
        self.folder_stats_cache.invalidate_all()
        wait_with_skip(2)
        return True

    def handle_download_mode(self, intro: str = "", setup_step=None, **kw):
        """Change how blocked charts download, then connect straight away.
        Returns the mode picked, or None when the chooser was escaped.

        Connecting here rather than at download time means a mode that cannot
        work says so now, instead of stalling for consent mid-sync.
        """
        from src.ui.screens import change_download_mode, connection_step_for

        chosen = change_download_mode(self.user_settings, self.sync, intro=intro,
                                      setup_step=setup_step, **kw)
        if not chosen:
            return None

        try:
            import src.rclone as rclone
            # Whether it works, not whether it is configured: picking rclone is
            # how someone asks to fix a dead remote.
            rclone_state = rclone.connection_state()
            rclone_authed = rclone_state == rclone.OK
        except Exception:
            rclone_state = None
            rclone_authed = False

        from src.drive.auth import has_custom_client_config

        step = connection_step_for(
            chosen, rclone_authed=rclone_authed,
            signed_in=bool(self.auth and self.auth.is_signed_in),
            byoc_configured=has_custom_client_config(),
        )
        if step == "rclone":
            self._connect_rclone(rclone_state)
        elif step == "signin":
            self.handle_signin()
        elif step == "byoc_setup":
            self._start_byoc_setup()
        return chosen

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
        print(f"  {copy.OPEN_FAILED}")
        print(f"    {data_dir}")
        print()
        wait_with_skip(4)

    def handle_open_library_folder(self):
        """Open the charts folder, and say nothing if that worked."""
        from src.core.files import open_folder
        from src.core.paths import get_library_path, library_is_set, plain_path

        if not library_is_set():
            return
        library = get_library_path()
        there = library.is_dir()
        if there and open_folder(library):
            return
        print()
        print(f"  {copy.OPEN_FAILED if there else copy.LIBRARY_MISSING + ':'}")
        print(f"    {plain_path(library)}")
        print()
        wait_with_skip(4)

    def _start_byoc_setup(self):
        """Put the instructions where the credentials go, then open that folder."""
        from src.core.files import open_folder
        from src.drive.auth import write_byoc_instructions

        try:
            open_folder(write_byoc_instructions().parent)
        except OSError as e:
            debug_log(f"BYOC_SETUP | could not write instructions | {e}")
        display.byoc_not_configured()
        # A key, not a timer: this screen names a folder the user has to go to.
        _pause(f"  {copy.PRESS_ENTER}")

    def _connect_rclone(self, state):
        """Connect rclone, or reconnect one whose access stopped working.
        `state` is the caller's connection_state(), which can take twenty
        seconds to probe again."""
        import src.rclone as rclone

        if not rclone.can_open_browser():
            display.rclone_no_browser()
            _pause(f"  {copy.PRESS_ENTER}")
            return

        message = copy.FAILURE
        try:
            display.rclone_consent_explainer()
            if state == rclone.DEAD:
                connected = rclone.reconnect()
            else:
                connected = rclone.RcloneSession().ensure_authed()
            if connected:
                message = copy.SUCCESS
        except Exception as e:
            message = f"{copy.FAILURE}: {e}"
        print(f"  {message}")
        _pause(f"  {copy.PRESS_ENTER}")

    def handle_signout(self):
        """Sign out of whichever Google sign-in the mode downloads with."""
        if self._uses_rclone():
            import src.rclone as rclone
            try:
                rclone.sign_out()
            except Exception as e:
                print(f"\n  {copy.FAILURE}: {e}")
                _pause(f"  {copy.PRESS_ENTER}")
                return
        else:
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
        return mode_blocked_reason(self.user_settings, self.auth,
                                   self._rclone_authed())

    def _drive_blocked_step(self) -> str:
        """Which connection step this install still owes, or "" when none."""
        from src.ui.screens.download_mode import mode_blocked_step
        return mode_blocked_step(self.user_settings, self.auth,
                                 self._rclone_authed())

    def _rclone_authed(self) -> bool:
        try:
            import src.rclone as rclone
            return rclone.is_authed()
        except Exception:
            return False

    def _library_blocked(self) -> str:
        """Why the library cannot take a scan right now, or "" when it can."""
        from src.core.paths import library_blocked_reason

        return library_blocked_reason()
