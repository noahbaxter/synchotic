from src import copy
from src.ui.widgets import sync_display


def test_consent_prompt_says_what_google_will_ask(capsys):
    sync_display.rclone_consent_explainer()
    assert copy.RCLONE_CONSENT in capsys.readouterr().out
