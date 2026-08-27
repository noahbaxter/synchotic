"""Drive-touching settings rows are offered only when the mode can reach Drive.

Gating on sign-in would be wrong: anonymous mode has no token by design and
still resolves public folders on the API key alone, so it would disable rows
that work. The gate follows connection_step_for, the same rule the first-run
flow uses to decide what still needs connecting.
"""

import pytest

from src.config.settings import (DOWNLOAD_MODE_ANONYMOUS, DOWNLOAD_MODE_BYOC,
                                 DOWNLOAD_MODE_RCLONE)
from src.ui.screens.home_panes import _mode_blocked_reason


class _Settings:
    def __init__(self, mode):
        self.download_mode = mode


class _Auth:
    def __init__(self, signed_in):
        self.is_signed_in = signed_in


def _reason(mode, *, signed_in=False, rclone=False, byoc_creds=False, monkeypatch=None):
    monkeypatch.setattr("src.drive.auth.has_custom_client_config", lambda: byoc_creds)
    return _mode_blocked_reason(_Settings(mode), _Auth(signed_in), rclone)


def test_anonymous_mode_is_never_blocked(monkeypatch):
    """No token by design, and key-only requests resolve public folders."""
    assert _reason(DOWNLOAD_MODE_ANONYMOUS, signed_in=False, monkeypatch=monkeypatch) == ""


def test_connected_rclone_is_not_blocked(monkeypatch):
    assert _reason(DOWNLOAD_MODE_RCLONE, rclone=True, monkeypatch=monkeypatch) == ""


def test_unconnected_rclone_is_blocked(monkeypatch):
    assert _reason(DOWNLOAD_MODE_RCLONE, rclone=False, monkeypatch=monkeypatch) == "Connect rclone first"


def test_byoc_without_credentials_asks_for_them(monkeypatch):
    reason = _reason(DOWNLOAD_MODE_BYOC, byoc_creds=False, monkeypatch=monkeypatch)
    assert reason == "Needs your Google credentials"


def test_byoc_with_credentials_but_signed_out_asks_for_signin(monkeypatch):
    reason = _reason(DOWNLOAD_MODE_BYOC, byoc_creds=True, signed_in=False, monkeypatch=monkeypatch)
    assert reason == "Sign in first"


def test_fully_configured_byoc_is_not_blocked(monkeypatch):
    reason = _reason(DOWNLOAD_MODE_BYOC, byoc_creds=True, signed_in=True, monkeypatch=monkeypatch)
    assert reason == ""


def test_every_reason_is_shown_to_the_user(monkeypatch):
    """A greyed row with no reason reads as broken, so each step maps to text."""
    from src.ui.screens.download_mode import connection_step_for

    steps = {
        connection_step_for(DOWNLOAD_MODE_RCLONE, rclone_authed=False,
                            signed_in=False, byoc_configured=False),
        connection_step_for(DOWNLOAD_MODE_BYOC, rclone_authed=False,
                            signed_in=False, byoc_configured=False),
        connection_step_for(DOWNLOAD_MODE_BYOC, rclone_authed=False,
                            signed_in=False, byoc_configured=True),
    }
    monkeypatch.setattr("src.drive.auth.has_custom_client_config", lambda: False)
    assert steps == {"rclone", "byoc_setup", "signin"}
