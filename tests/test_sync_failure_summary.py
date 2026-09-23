"""A failed scan must not report success.

A user whose every setlist 400'd saw "All files synced" above the warning
that seven of them had failed. Nothing downloaded, so the summary took the
"already synced" branch, which cannot tell an up-to-date library from a
dead one.
"""

import requests

from src import copy
from src.sync.background_scanner import describe_scan_failure
from src.ui.widgets import sync_display


class _Response:
    def __init__(self, status_code, text=""):
        self.status_code = status_code
        self.text = text


def _http_error(status, body=""):
    err = requests.exceptions.HTTPError(f"{status}")
    err.response = _Response(status, body)
    return err


def test_cross_project_failure_names_the_cause():
    body = '{"error": {"message": "The API Key and the authentication credential are from different projects."}}'
    reason = describe_scan_failure(_http_error(400, body))
    assert reason == copy.SCAN_MIXED_PROJECTS


def test_expired_signin_is_distinguished_from_denial():
    assert describe_scan_failure(_http_error(401)) == copy.FAIL_SIGNED_OUT
    assert describe_scan_failure(_http_error(403)) == copy.SCAN_DENIED


def test_unrecognised_failure_falls_back_to_the_exception():
    """Better a raw exception than a vague stand-in that hides the cause."""
    reason = describe_scan_failure(ValueError("something odd"))
    assert "ValueError" in reason and "something odd" in reason


def test_summary_line_states_the_reason(capsys):
    sync_display.sync_failed(copy.FAIL_SIGNED_OUT, failed_count=7)
    out = capsys.readouterr().out

    assert copy.SYNC_FAILED.format(reason=copy.FAIL_SIGNED_OUT) in out
    assert "(7 setlists)" in out
    assert copy.ALL_SYNCED not in out


def test_single_failure_is_not_pluralised(capsys):
    sync_display.sync_failed(copy.FAIL_RATE_LIMITED, failed_count=1)
    assert "(1 setlist)" in capsys.readouterr().out
