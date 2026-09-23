from src.ui.widgets import sync_display

def test_consent_prompt_mentions_rclone_and_readonly(capsys):
    sync_display.rclone_consent_explainer()
    out = capsys.readouterr().out.lower()
    assert "rclone" in out
    assert "read-only" in out or "read only" in out
