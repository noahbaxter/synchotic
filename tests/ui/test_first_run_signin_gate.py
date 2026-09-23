"""The startup sign-in prompt must never offer a sign-in that cannot work.
Without credentials.json of your own it falls back to the embedded client,
whose user cap is full, so for anyone new it fails."""
import pytest


class Auth:
    is_available = True

    def __init__(self, signed_in=False):
        self.is_signed_in = signed_in
        self.signed_in_called = False

    def sign_in(self):
        self.signed_in_called = True
        return True


@pytest.fixture
def _should_prompt(monkeypatch):
    """The app's own gate. A copy of the condition here is what once let it
    drift: this file passed while rclone users got a BYOC sign-in every launch."""
    from types import SimpleNamespace

    from sync import SyncApp

    def gate(auth, byoc_configured, mode="", rclone_authed=True):
        monkeypatch.setattr("src.drive.auth.has_custom_client_config",
                            lambda: byoc_configured)
        monkeypatch.setattr("src.rclone.is_authed", lambda: rclone_authed)
        app = object.__new__(SyncApp)
        app.auth = auth
        app.user_settings = SimpleNamespace(download_mode=mode)
        return app._should_offer_signin()
    return gate


class TestTheGate:
    def test_byoc_not_set_up_is_never_offered_sign_in(self, _should_prompt):
        """The reported bug: pick BYOC, get asked to sign in with the capped app."""
        assert _should_prompt(Auth(), byoc_configured=False, mode="byoc") is False

    def test_byoc_with_its_own_client_is_offered_sign_in(self, _should_prompt):
        assert _should_prompt(Auth(), byoc_configured=True, mode="byoc") is True

    def test_already_signed_in_is_not_asked_again(self, _should_prompt):
        assert _should_prompt(Auth(signed_in=True), byoc_configured=True,
                              mode="byoc") is False

    def test_anonymous_mode_is_never_asked(self, _should_prompt):
        """The one mode that never needs a token."""
        assert _should_prompt(Auth(), byoc_configured=True, mode="anonymous") is False

    def test_rclone_is_not_offered_a_byoc_sign_in(self, _should_prompt):
        """Leftover credentials.json from a BYOC attempt used to keep the
        prompt coming on every launch, for a mode that never signs in. The
        gate asked the disk what was there instead of asking the mode what it
        still needed."""
        assert _should_prompt(Auth(), byoc_configured=True, mode="rclone") is False

    def test_rclone_that_is_not_connected_asks_rclone_not_google(self, _should_prompt):
        assert _should_prompt(Auth(), byoc_configured=True, mode="rclone",
                              rclone_authed=False) is False


class TestNothingRecordsThatWeAsked:
    def test_the_prompt_leaves_no_flag_behind(self):
        """Being asked is not a setting. Whether they signed in is the token,
        and whether they need to is the mode."""
        from pathlib import Path
        src = Path(__file__).resolve().parents[2] / "sync.py"
        # encoding is not optional here: sync.py has box-drawing characters and
        # Windows defaults to cp1252, which fails on them.
        body = src.read_text(encoding="utf-8")
        assert "oauth_prompted" not in body
