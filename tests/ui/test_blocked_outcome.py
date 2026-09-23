"""What is said about charts Google would not serve anonymously: nothing until
rclone's second pass has run, then only the outcome."""
import io
from contextlib import redirect_stdout

from src.ui.widgets.sync_display import blocked_outcome


def _said(recovered, still_blocked, mode="rclone"):
    out = io.StringIO()
    with redirect_stdout(out):
        blocked_outcome(recovered, still_blocked, mode)
    return out.getvalue()


def test_a_clean_recovery_is_reported_as_success():
    said = _said(recovered=12, still_blocked=0)
    assert "12" in said
    assert "rclone" in said
    assert "AUTH" not in said.upper()


def test_charts_that_really_failed_say_what_to_do():
    said = _said(recovered=9, still_blocked=3)
    assert "3" in said
    assert "sign in" in said.lower()


def test_anonymous_mode_names_the_reason_it_could_not_try():
    """Tier 4 only runs in rclone mode, so anonymous users get told why."""
    said = _said(recovered=0, still_blocked=4, mode="anonymous")
    assert "rclone" in said.lower() or "sign in" in said.lower()


def test_nothing_blocked_says_nothing():
    assert _said(recovered=0, still_blocked=0) == ""
