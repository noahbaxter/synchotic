"""
OAuth authentication manager for DM Chart Sync.

Handles Google OAuth 2.0 flow for the Changes API.
"""

import sys
from pathlib import Path
from typing import Callable, Optional

# OAuth imports are optional (only needed for admin script)
try:
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from google_auth_oauthlib.flow import InstalledAppFlow
    OAUTH_AVAILABLE = True
except ImportError:
    OAUTH_AVAILABLE = False


class OAuthManager:
    """
    Manages OAuth 2.0 authentication for Google Drive.

    The Changes API requires OAuth (not just an API key), so this class
    handles the authentication flow for admin operations.
    """

    SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

    def __init__(
        self,
        credentials_path: Optional[Path] = None,
        token_path: Optional[Path] = None,
    ):
        """
        Initialize OAuth manager.

        Args:
            credentials_path: Path to OAuth credentials JSON
            token_path: Path to save/load token
        """
        base_path = self._get_base_path()
        self.credentials_path = credentials_path or base_path / "credentials.json"
        self.token_path = token_path or base_path / "token.json"
        self._credentials: Optional[Credentials] = None

    @staticmethod
    def _get_base_path() -> Path:
        """Get base path for credential files (for local dev)."""
        if getattr(sys, "frozen", False):
            return Path(sys.executable).parent
        # Look in repo root for local credential files
        return Path(__file__).parent.parent.parent

    @property
    def is_available(self) -> bool:
        """Check if OAuth libraries are available."""
        return OAUTH_AVAILABLE

    @property
    def is_configured(self) -> bool:
        """Check if OAuth credentials or token are available."""
        return self.credentials_path.exists() or self.token_path.exists()

    @property
    def has_token(self) -> bool:
        """Check if we have a saved token."""
        return self.token_path.exists()

    def get_credentials(self) -> Optional[Credentials]:
        """
        Get or refresh OAuth credentials.

        Returns:
            Credentials object or None if not available
        """
        if not OAUTH_AVAILABLE:
            return None

        creds = None

        # Try to load existing token
        if self.token_path.exists():
            try:
                creds = Credentials.from_authorized_user_file(
                    str(self.token_path),
                    self.SCOPES
                )
            except Exception:
                pass

        # Refresh if expired
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception:
                creds = None

        # Get new credentials via interactive flow if needed (requires credentials.json)
        if (not creds or not creds.valid) and self.credentials_path.exists():
            try:
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(self.credentials_path),
                    self.SCOPES
                )
                creds = flow.run_local_server(port=0)
            except Exception as e:
                print(f"OAuth error: {e}")
                return None

        # Save token for next time
        if creds:
            self._save_token(creds)
            self._credentials = creds

        return creds

    def _save_token(self, creds: Credentials):
        """Save credentials to token file."""
        try:
            with open(self.token_path, "w") as f:
                f.write(creds.to_json())
        except Exception:
            pass

    def get_token(self) -> Optional[str]:
        """
        Get the access token string.

        Returns:
            Access token string or None
        """
        creds = self.get_credentials()
        if creds:
            return creds.token
        return None

    def clear_token(self):
        """Remove saved token (force re-authentication)."""
        if self.token_path.exists():
            self.token_path.unlink()
        self._credentials = None


def has_custom_client_config() -> bool:
    """True when BYOC credentials are actually present.

    load_client_config falls back to the embedded client when they are not, and
    that is the capped one new users are blocked from. Signing in with it is the
    exact failure BYOC exists to avoid, so callers must check before offering it.
    """
    import os, json
    from ..core.paths import get_data_dir

    if (os.environ.get("SYNCHOTIC_OAUTH_CLIENT_ID")
            and os.environ.get("SYNCHOTIC_OAUTH_CLIENT_SECRET")):
        return True
    creds_file = get_data_dir() / "credentials.json"
    if not creds_file.exists():
        return False
    try:
        data = json.loads(creds_file.read_text())
        inst = data.get("installed") or data.get("web") or {}
        return bool(inst.get("client_id") and inst.get("client_secret"))
    except Exception:
        return False


def load_client_config() -> dict:
    """Resolve OAuth client config: env vars -> credentials.json -> embedded defaults."""
    import os, json
    from ..core.paths import get_data_dir
    from ..core.constants import USER_OAUTH_CLIENT_ID, USER_OAUTH_CLIENT_SECRET

    env_id = os.environ.get("SYNCHOTIC_OAUTH_CLIENT_ID")
    env_secret = os.environ.get("SYNCHOTIC_OAUTH_CLIENT_SECRET")
    if env_id and env_secret:
        client_id, client_secret = env_id, env_secret
    else:
        creds_file = get_data_dir() / "credentials.json"
        if creds_file.exists():
            try:
                data = json.loads(creds_file.read_text())
                inst = data.get("installed") or data.get("web") or {}
                if inst.get("client_id") and inst.get("client_secret"):
                    return {"installed": {
                        "client_id": inst["client_id"],
                        "client_secret": inst["client_secret"],
                        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                        "token_uri": "https://oauth2.googleapis.com/token",
                        "redirect_uris": ["http://localhost"],
                    }}
            except Exception:
                pass
        client_id, client_secret = USER_OAUTH_CLIENT_ID, USER_OAUTH_CLIENT_SECRET

    return {"installed": {
        "client_id": client_id,
        "client_secret": client_secret,
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": ["http://localhost"],
    }}


class UserOAuthManager:
    """
    OAuth manager for end-user authentication using embedded credentials.

    Unlike OAuthManager (for admin use), this class:
    - Uses embedded OAuth client credentials (no credentials.json needed)
    - Stores user token at .dm-sync/token.json
    - Provides explicit sign_in/sign_out methods
    - Required for scanning and syncing
    """

    def __init__(self, token_path: Optional[Path] = None):
        """
        Initialize user OAuth manager.

        Args:
            token_path: Path to save/load user token (default: .dm-sync/token.json)
        """
        if token_path is None:
            from ..core.paths import get_token_path
            token_path = get_token_path()
        self.token_path = token_path
        self._credentials: Optional[Credentials] = None

    @property
    def is_available(self) -> bool:
        """Check if OAuth libraries are available."""
        return OAUTH_AVAILABLE

    @property
    def is_signed_in(self) -> bool:
        """Check if user has a valid saved token."""
        if not OAUTH_AVAILABLE:
            return False

        if not self.token_path.exists():
            return False

        # Try to load and validate token
        try:
            creds = Credentials.from_authorized_user_file(str(self.token_path))
            # Valid if not expired, or if we can refresh
            return creds.valid or (creds.expired and creds.refresh_token)
        except Exception:
            return False

    def get_credentials(self) -> Optional[Credentials]:
        """
        Load existing credentials, refresh if needed.

        Returns:
            Credentials object or None if not signed in
        """
        if not OAUTH_AVAILABLE:
            return None

        if not self.token_path.exists():
            return None

        creds = None

        # Load existing token
        try:
            creds = Credentials.from_authorized_user_file(str(self.token_path))
        except Exception:
            return None

        # Refresh if expired
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                self._save_token(creds)
            except Exception:
                # Refresh failed - token is invalid
                return None

        if creds and creds.valid:
            self._credentials = creds
            return creds

        return None

    def get_token(self) -> Optional[str]:
        """
        Get the access token string.

        Returns:
            Access token string or None if not signed in
        """
        creds = self.get_credentials()
        if creds:
            return creds.token
        return None

    def sign_in(self) -> bool:
        """
        Interactive sign-in flow. Opens browser for user to authorize.

        Returns:
            True if sign-in successful, False otherwise
        """
        if not OAUTH_AVAILABLE:
            return False

        # Scopes still come from constants; client config is resolved
        # from env vars -> credentials.json -> embedded defaults (BYOC).
        from ..core.constants import USER_OAUTH_SCOPES

        client_config = load_client_config()

        try:
            flow = InstalledAppFlow.from_client_config(client_config, USER_OAUTH_SCOPES)
            creds = flow.run_local_server(port=0)

            if creds:
                self._save_token(creds)
                self._credentials = creds
                return True
        except Exception as e:
            print(f"  Sign-in error: {e}")

        return False

    def sign_out(self):
        """Remove saved token (sign out)."""
        if self.token_path.exists():
            try:
                self.token_path.unlink()
            except Exception:
                pass
        self._credentials = None

    def get_user_email(self) -> Optional[str]:
        """
        Get signed-in user's email for display.

        Returns:
            Email string or None if not available
        """
        if not self._credentials:
            self.get_credentials()

        if self._credentials:
            # The token file stores the email in the 'account' field if available
            # Otherwise we'd need to make an API call to get it
            try:
                import json
                with open(self.token_path) as f:
                    data = json.load(f)
                    return data.get("account") or None
            except Exception:
                pass

        return None

    def _save_token(self, creds: Credentials):
        """Save credentials to token file."""
        try:
            with open(self.token_path, "w") as f:
                f.write(creds.to_json())
        except Exception:
            pass


class AuthManager:
    """
    Unified authentication manager for DM Chart Sync.

    Provides a single interface for all OAuth operations:
    - User authentication (preferred, uses user's quota)
    - Admin/dev authentication (fallback, for testing)

    Usage:
        auth = AuthManager()

        # For downloads - pass the getter for auto-refresh
        downloader = FileDownloader(auth_token=auth.get_token_getter())

        # For UI
        if auth.is_signed_in:
            print(f"Signed in as {auth.user_email}")
        else:
            auth.sign_in()
    """

    def __init__(self, token_path: Optional[Path] = None):
        """
        Initialize unified auth manager.

        Args:
            token_path: Path for user token (default: .dm-sync/token.json)
        """
        self._user_oauth = UserOAuthManager(token_path=token_path)
        self._admin_oauth: Optional[OAuthManager] = None

    def _get_admin_oauth(self) -> OAuthManager:
        """Lazy-load admin OAuth manager."""
        if self._admin_oauth is None:
            self._admin_oauth = OAuthManager()
        return self._admin_oauth

    # -------------------------------------------------------------------------
    # Token access (for downloads)
    # -------------------------------------------------------------------------

    def get_token(self) -> Optional[str]:
        """
        Get the best available access token.

        Priority: user token > admin token > None

        This method handles token refresh automatically.

        Returns:
            Access token string or None if not authenticated
        """
        # Try user token first (preferred - uses their quota)
        if self._user_oauth.is_signed_in:
            token = self._user_oauth.get_token()
            if token:
                return token

        # Fall back to admin token (dev/testing only)
        admin = self._get_admin_oauth()
        if admin.is_available and admin.is_configured:
            return admin.get_token()

        return None

    def get_token_getter(self) -> Optional[Callable[[], Optional[str]]]:
        """
        Get a callable that returns fresh tokens (for long-running downloads).

        Pass this to FileDownloader instead of a static token string
        to enable automatic token refresh during long downloads.

        Returns:
            Callable that returns current token, or None if not authenticated
        """
        if self._user_oauth.is_signed_in:
            return self._user_oauth.get_token

        admin = self._get_admin_oauth()
        if admin.is_available and admin.is_configured:
            return admin.get_token

        return None

    @property
    def has_auth(self) -> bool:
        """Check if any authentication is available."""
        if self._user_oauth.is_signed_in:
            return True
        admin = self._get_admin_oauth()
        return admin.is_available and admin.is_configured

    # -------------------------------------------------------------------------
    # User authentication (sign in/out UI)
    # -------------------------------------------------------------------------

    @property
    def is_signed_in(self) -> bool:
        """Check if user is signed in."""
        return self._user_oauth.is_signed_in

    @property
    def is_available(self) -> bool:
        """Check if OAuth libraries are available."""
        return self._user_oauth.is_available

    def sign_in(self) -> bool:
        """
        Interactive sign-in flow. Opens browser for user to authorize.

        Returns:
            True if sign-in successful
        """
        return self._user_oauth.sign_in()

    def sign_out(self):
        """Sign out the current user."""
        self._user_oauth.sign_out()

    @property
    def user_email(self) -> Optional[str]:
        """Get signed-in user's email for display."""
        return self._user_oauth.get_user_email()

    # -------------------------------------------------------------------------
    # Admin authentication (for manifest generation, dev tools)
    # -------------------------------------------------------------------------

    @property
    def admin_oauth(self) -> OAuthManager:
        """
        Access admin OAuth manager directly.

        Use this for admin operations like manifest generation
        that require the admin credentials.
        """
        return self._get_admin_oauth()


BYOC_INSTRUCTIONS_FILE = "BYOC_SETUP_INSTRUCTIONS.txt"

_BYOC_INSTRUCTIONS = """\
Bring Your Own Credentials - Setup Instructions
===============================================

If you find that you keep hitting rate limits with rclone or would prefer
higher download speeds, you can create your own Google OAuth credentials to
use with Synchotic! This takes about ten minutes to set up in a browser but
guarantees you get your own drive quota at full speeds rather than sharing it
with every other rclone user.

Instructions:

1. MAKE A PROJECT
   Go to console.cloud.google.com and sign in.
   Project dropdown at the top, then "New Project".
   Name it "synchotic-byoc" and click Create.
   Wait a few seconds, then select it in that same dropdown.

2. TURN ON GOOGLE DRIVE
   Left menu: "APIs and Services", then "Library".
   Search "Google Drive API". Open it, click Enable.

3. FILL IN THE APP INFO
   Left menu: "APIs and Services", then "OAuth consent screen".
   Choose "External", click Create.
   Any app name, your own email in both email boxes. Skip the rest.
   Save and continue until it finishes.

   IMPORTANT: set the publishing status to "In production".
   If it remains "Testing" by default, Google will sign you out every 7 days.

4. MAKE THE KEY
   Left menu: "APIs and Services", then "Credentials".
   "Create Credentials", then "OAuth client ID".
   Application type: "Desktop app". Any name. Create.

5. DOWNLOAD IT
   Click "Download JSON" in the box that pops up.

6. INSTALL IT
   Rename the file you just downloaded to "credentials.json" exactly.
   Move it into this folder, right next to these instructions.

7. ENABLE IT
   Start Synchotic, press D, choose "Use your own Google credentials", and
   sign in with the same Google account.
   Google will say the app is not verified. It is yours. Click "Advanced",
   then "Go to ... (unsafe)".


FAQ
---
Why am I being signed out every 7 days?
   Step 3, publishing status is still "Testing". Set it to "In production".

Why does Synchotic say it is not set up?
   The file must be named exactly "credentials.json", not "credentials(1).json",
   and must sit in this folder, beside these instructions.
"""


def write_byoc_instructions() -> "Path":
    """Drop setup instructions where credentials.json needs to go.

    The target folder differs per install (launcher, frozen exe, dev checkout),
    so telling people to "find .dm-sync" is not an answer. Put the steps in the
    folder itself and open it for them.
    """
    from ..core.paths import get_data_dir

    data_dir = get_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / BYOC_INSTRUCTIONS_FILE
    path.write_text(_BYOC_INSTRUCTIONS, encoding="utf-8")
    return path
