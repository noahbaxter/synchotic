"""The data folder has to be reachable without a support conversation.

Its location differs per install (launcher, frozen exe, dev checkout), and users
are sent there for credentials.json, logs and settings. It used to sit on the
main menu; it now lives on the Account screen, one keypress further in, which is
still reachable without anyone having to explain a filesystem path.
"""
import pytest

from src.config.settings import UserSettings
from src.ui.screens.account import show_account_screen


@pytest.fixture
def rows(monkeypatch, tmp_path):
    def build(auth=None):
        captured = {}

        def fake_run(self, initial_index=0):
            captured["items"] = self.items
            return None  # user pressed Esc

        monkeypatch.setattr("src.ui.widgets.menu.Menu.run", fake_run, raising=False)
        monkeypatch.setattr("chotic_ui.widgets.menu.Menu.run", fake_run, raising=False)
        monkeypatch.setattr("src.drive.auth.has_custom_client_config",
                            lambda: True, raising=False)
        ret = show_account_screen(user_settings=UserSettings(tmp_path / "settings.json"),
                                  auth=auth, rclone_connected=True)
        captured["returned"] = ret
        return captured
    return build


def _find(items, text):
    return [i for i in items if text in (getattr(i, "label", "") or "")]


def test_the_row_is_always_present(rows):
    found = _find(rows()["items"], "Open data folder")
    assert len(found) == 1
    assert found[0].disabled is False
    assert found[0].value == "open_data_folder"


def test_it_has_a_hotkey_that_nothing_else_claims(rows):
    items = rows()["items"]
    row = _find(items, "Open data folder")[0]
    assert row.hotkey == "F"
    keys = [i.hotkey for i in items if getattr(i, "hotkey", None)]
    assert keys.count("F") == 1, f"hotkey collision: {keys}"


def test_escaping_the_screen_does_nothing(rows):
    """Esc is Back, not an action. Returning a stray value would fire a handler."""
    assert rows()["returned"] == ""
