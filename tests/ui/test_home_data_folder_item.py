"""The data folder has to be reachable without a support conversation.

Its location differs per install (launcher, frozen exe, dev checkout), and
users are sent there for credentials.json, logs and settings. Making it
reachable only during BYOC setup would leave everyone else guessing.
"""
import pytest

from src.config.settings import UserSettings
from src.ui.screens.home import show_main_menu


@pytest.fixture
def rows(monkeypatch, tmp_path):
    def build():
        captured = {}

        def fake_run(self, initial_index=0):
            captured["items"] = self.items

            class Result:
                value = ("quit", None)
            return Result()

        monkeypatch.setattr("src.ui.widgets.menu.Menu.run", fake_run, raising=False)
        monkeypatch.setattr("chotic_ui.widgets.menu.Menu.run", fake_run, raising=False)
        monkeypatch.setattr("src.rclone.is_authed", lambda: True, raising=False)
        show_main_menu([], user_settings=UserSettings(tmp_path / "settings.json"))
        return captured["items"]
    return build


def _find(items, text):
    return [i for i in items if text in (getattr(i, "label", "") or "")]


def test_the_row_is_always_present(rows):
    found = _find(rows(), "Open data folder")
    assert len(found) == 1
    assert found[0].disabled is False
    assert found[0].value == ("open_data_folder", None)


def test_it_has_a_hotkey_that_nothing_else_claims(rows):
    items = rows()
    row = _find(items, "Open data folder")[0]
    assert row.hotkey == "F"
    keys = [i.hotkey for i in items if getattr(i, "hotkey", None)]
    assert keys.count("F") == 1, f"hotkey collision: {keys}"
