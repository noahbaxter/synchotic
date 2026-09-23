"""What a failed chart is called: a reason a person can act on, in their words."""
import pytest

from src.ui.widgets.sync_display import ADVICE, _FAILURE_WORDS, describe_failure
from src.ui.widgets.sync_screen import STATUS_W


@pytest.mark.parametrize("message, reason", [
    # A full disk is the one failure the person must act on immediately, and it
    # arrives as an extract error, where it used to read as a corrupt archive.
    ("extract: Pack - [Errno 28] No space left on device", "disk full"),
    ("ERR: x.7z - [Errno 28] No space left on device", "disk full"),
    # Status codes are not words. Each of these has a plain meaning and a
    # different answer: sign in again, wait, or nothing.
    ("ERR (HTTP 401): x.7z", "signed out"),
    ("ERR (HTTP 403): x.7z", "rate limited"),
    ("ERR (HTTP 429): x.7z", "rate limited"),
    ("ERR: x.7z - Cannot connect to host www.googleapis.com", "no connection"),
    ("extract: Pack - Unsupported archive format: .tar", "unknown format"),
    ("extract: Pack - py7zr library not available", "unpack failed"),
    ("NEEDS AUTH (authenticated download set up automatically): x.7z", "needs sign-in"),
    ("ERR (rate limited): x.7z", "rate limited"),
    ("ERR (folder rate limited): x.7z", "rate limited"),
    ("ERR (timeout): x.7z", "timed out"),
    ("ERR (got 400 of 1200 bytes): x.7z", "cut short"),
    ("ERR (HTTP 404): x.7z", "not on Drive"),
    ("ERR (HTTP 500): x.7z [file_id=abc]", "Drive error"),
    ("extract: Pack - x.7z - bad archive", "unpack failed"),
])
def test_a_person_could_act_on_every_reason(message, reason):
    assert describe_failure(message) == reason


def test_every_reason_says_what_to_do_or_that_there_is_nothing_to_do():
    """A reason with no answer leaves the person stuck, which is where this started.

    Some failures are genuinely nothing to do with the user (a chart pulled from
    Drive, a bad archive upstream). Those still have to say so, rather than
    sitting there looking like something they got wrong.
    """
    for _, reason in _FAILURE_WORDS:
        assert reason in ADVICE, f"{reason} has no advice line"
        assert ADVICE[reason], f"{reason} has an empty advice line"


def test_an_unrecognised_failure_keeps_what_it_said():
    """Better a raw message than a vague stand-in that hides the cause."""
    assert describe_failure("ERR (something odd): x.7z") == "something odd"


def test_every_reason_fits_the_column_it_is_shown_in():
    """"! " plus the reason has to fit STATUS_W, or the reason is truncated.

    "could not unpack" rendered as "could not u...", which tells nobody
    anything. The words have to fit the space they are shown in.
    """
    for _, reason in _FAILURE_WORDS:
        assert len(f"! {reason}") <= STATUS_W, reason
