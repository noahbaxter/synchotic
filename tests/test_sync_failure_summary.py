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

    def json(self):
        import json
        return json.loads(self.text)


def _http_error(status, body=""):
    err = requests.exceptions.HTTPError(f"{status}")
    err.response = _Response(status, body)
    return err


def test_a_google_error_says_googles_own_message():
    """The cross-project 400 is only fixable once you know it is that."""
    message = "The API Key and the authentication credential are from different projects."
    body = '{"error": {"message": "%s"}}' % message
    assert describe_scan_failure(_http_error(400, body)) == message


def test_a_google_error_without_a_message_still_says_something():
    assert describe_scan_failure(_http_error(403, "<html>")) == "HTTP 403"


def test_expired_signin_is_distinguished_from_denial():
    assert describe_scan_failure(_http_error(401)) == copy.FAIL_SIGNED_OUT
    assert describe_scan_failure(_http_error(403)) != copy.FAIL_SIGNED_OUT


def test_unrecognised_failure_falls_back_to_the_exception():
    """Better a raw exception than a vague stand-in that hides the cause."""
    reason = describe_scan_failure(ValueError("something odd"))
    assert "ValueError" in reason and "something odd" in reason


def test_summary_line_states_the_reason(capsys):
    sync_display.sync_failed(copy.FAIL_SIGNED_OUT, failed_count=7)
    out = capsys.readouterr().out

    assert f"{copy.FAILURE}: {copy.FAIL_SIGNED_OUT}" in out
    assert "(7 setlists)" in out
    assert copy.ALL_SYNCED not in out


def test_single_failure_is_not_pluralised(capsys):
    sync_display.sync_failed(copy.FAIL_RATE_LIMITED, failed_count=1)
    assert "(1 setlist)" in capsys.readouterr().out


class TestOnlyWhatIsTurnedOnCounts:
    """An up to date library whose disabled game rips failed to scan was told
    FAILURE: timed out (63 setlists). Those scans cost the sync nothing."""

    def _app(self, tmp_path, failed, wont_list=()):
        from sync import SyncApp
        from src.config.settings import UserSettings

        settings = UserSettings(tmp_path / "settings.json")
        settings.set_drive_enabled("rb", True)
        settings.set_drive_enabled("csc", False)
        settings.set_subfolder_enabled("rb", "Rock Band Network", False)

        class Scanner:
            def has_scan_failures(self):
                return True

            def get_failure_reason(self):
                return copy.FAIL_SIGNED_OUT

            def get_failed_setlist_names(self, folder_id):
                return set(failed.get(folder_id, ()))

            def discovery_failed(self, folder_id):
                return folder_id in wont_list

        app = object.__new__(SyncApp)
        app.user_settings = settings
        app.folders = [{"folder_id": "rb"}, {"folder_id": "csc"}]
        app._background_scanner = Scanner()
        return app

    def test_failures_in_things_turned_off_are_not_a_failure(self, tmp_path):
        app = self._app(tmp_path, {"rb": {"Rock Band Network"},
                                   "csc": {"Anti Hero", "CHARTS"}})
        assert app._scan_failure() is None

    def test_a_setlist_that_is_on_still_counts(self, tmp_path):
        app = self._app(tmp_path, {"rb": {"Rock Band 1", "Rock Band Network"}})
        assert app._scan_failure() == (copy.FAIL_SIGNED_OUT, 1)

    def test_an_enabled_drive_that_would_not_list_counts(self, tmp_path):
        app = self._app(tmp_path, {}, wont_list={"rb"})
        assert app._scan_failure() == (copy.FAIL_SIGNED_OUT, 1)
