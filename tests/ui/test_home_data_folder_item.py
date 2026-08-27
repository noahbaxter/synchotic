"""The data folder has to be reachable without a support conversation.

Its location differs per install (launcher, frozen exe, dev checkout), and users
are sent there for credentials.json, logs and settings. It sat on the main menu,
then on an Account screen; it is now a row in the home screen's settings pane,
alongside the library location it belongs with.
"""
import pytest

from src.config.settings import UserSettings
from src.ui.components import strip_ansi
from src.ui.screens.home_panes import show_main_menu_panes, SETTINGS


@pytest.fixture
def rows(monkeypatch, tmp_path):
    def build(auth=None):
        captured = {}

        def fake_run(self):
            captured["rows"] = self._right_rows(SETTINGS, "")
            return None  # user pressed Esc

        monkeypatch.setattr("chotic_ui.widgets.two_pane.TwoPane.run",
                            fake_run, raising=False)
        monkeypatch.setattr("src.drive.auth.has_custom_client_config",
                            lambda: True, raising=False)
        captured["returned"] = show_main_menu_panes(
            folders=[],
            user_settings=UserSettings(tmp_path / "settings.json"),
            download_path=tmp_path / "charts",
            auth=auth,
        )
        return captured
    return build


def _find(rows, text):
    return [r for r in rows if text in strip_ansi(r[0](False, False))]


def test_the_row_is_always_present(rows):
    found = _find(rows()["rows"], "Open folder")
    assert len(found) == 1
    assert found[0][2] is True
    assert found[0][1] == ("act", "open_data_folder")


def test_it_says_what_is_in_there(rows):
    """"Open folder" alone does not tell anyone why they were sent to it."""
    row = _find(rows()["rows"], "Open folder")[0]
    text = strip_ansi(row[0](False, False))
    assert "credentials" in text and "logs" in text


def test_it_sits_with_the_library_location(rows):
    """Both answer "where does Synchotic keep things", so they share a section."""
    pane_rows = rows()["rows"]
    labels = [strip_ansi(r[0](False, False)) for r in pane_rows]
    location = next(i for i, l in enumerate(labels) if "Location" in l)
    folder = next(i for i, l in enumerate(labels) if "Open folder" in l)
    assert folder == location + 1


def test_escaping_the_screen_quits_rather_than_acting(rows):
    """Esc is not an action. Returning a stray value would fire a handler."""
    assert rows()["returned"][0] == "quit"
