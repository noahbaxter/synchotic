"""The first-run sign-in prompt must never offer a sign-in that cannot work.

Sign-in resolves its OAuth client from credentials.json and falls back to the
embedded one. That embedded client is the capped app: its 100-user limit is full
and verification was rejected, so for anyone new the sign-in fails. The prompt
used to run before any of that was considered, so choosing BYOC on the first-run
chooser led straight into a Synchotic sign-in that was guaranteed to fail.
"""
import pytest


class Auth:
    is_available = True

    def __init__(self, signed_in=False):
        self.is_signed_in = signed_in
        self.signed_in_called = False

    def sign_in(self):
        self.signed_in_called = True
        return True


def _should_prompt(prompted, auth, byoc_configured):
    """The gate as sync.run() applies it."""
    return (not prompted
            and auth.is_available
            and not auth.is_signed_in
            and byoc_configured)


class TestTheGate:
    def test_byoc_not_set_up_is_never_offered_sign_in(self):
        """The reported bug: pick BYOC, get asked to sign in with the capped app."""
        assert _should_prompt(False, Auth(), byoc_configured=False) is False

    def test_own_client_is_offered_sign_in(self):
        assert _should_prompt(False, Auth(), byoc_configured=True) is True

    def test_already_signed_in_is_not_asked_again(self):
        assert _should_prompt(False, Auth(signed_in=True), byoc_configured=True) is False

    def test_asking_once_is_remembered(self):
        assert _should_prompt(True, Auth(), byoc_configured=True) is False


class TestItStaysAskableLater:
    def test_the_flag_is_not_burned_when_the_prompt_is_skipped(self):
        """A user who sets BYOC up later must still get asked once.

        Marking oauth_prompted while skipping would silently consume their one
        prompt, and sign-in would then only ever be reachable by hunting through
        the Account screen.
        """
        import re
        from pathlib import Path
        src = Path(__file__).resolve().parents[2] / "sync.py"
        # encoding is not optional here: sync.py has box-drawing characters and
        # Windows defaults to cp1252, which fails on them.
        body = src.read_text(encoding="utf-8")
        block = body[body.index("# First-run OAuth prompt"):]
        block = block[:block.index("import time as _time")]
        gate = block.index("if (not self.user_settings.oauth_prompted")
        assign = block.index("self.user_settings.oauth_prompted = True")
        assert assign > gate, "the flag must be set inside the gate, not before it"
