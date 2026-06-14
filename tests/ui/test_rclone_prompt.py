from src.ui.widgets import sync_display

def test_consent_prompt_mentions_rclone_and_readonly(capsys):
    sync_display.rclone_consent_explainer()
    out = capsys.readouterr().out.lower()
    assert "rclone" in out
    assert "read-only" in out or "read only" in out

def test_rate_limited_message_distinct_from_needs_auth(capsys):
    sync_display.report_blocked_summary(needs_auth=0, rate_limited=3)
    out = capsys.readouterr().out.lower()
    assert "rate-limited" in out or "rate limited" in out
    assert "google" in out
