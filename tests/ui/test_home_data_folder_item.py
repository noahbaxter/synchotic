"""The settings pane rows, and the "go to X" pointers aimed at them.

The data folder's location differs per install (launcher, frozen exe, dev
checkout), and users are sent there for credentials.json, logs and settings,
so it has to be reachable without a support conversation.
"""
import pytest

from src import copy
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
        monkeypatch.setattr("src.rclone.is_authed", lambda: False)
        captured["returned"] = show_main_menu_panes(
            folders=[],
            user_settings=UserSettings(tmp_path / "settings.json"),
            download_path=tmp_path / "charts",
            auth=auth,
        )
        return captured
    return build


def _paths(rows):
    """Every row as "Settings > Header > Label", the way a pointer names it."""
    out, header = set(), None
    for r in rows:
        text = strip_ansi(r[0](False, False)).strip()
        if not text:
            continue
        if r[1] is None:
            header = text
            continue
        label = text.split("  ")[0].strip()
        out.add(f"{copy.SETTINGS} > {header} > {label}".lower())
    return out


def test_every_pointer_names_a_row_that_exists(rows):
    """A renamed row must not leave "Go to Settings > ..." aimed at nothing."""
    pointers = [copy.SETTINGS_MODE, copy.SETTINGS_SIGN_IN, copy.SETTINGS_LOCATION,
                copy.SETTINGS_OPEN_DATA]
    have = _paths(rows()["rows"])
    assert [p for p in pointers if p.lower() not in have] == []


def test_the_data_folder_row_is_always_present(rows):
    found = [r for r in rows()["rows"] if r[1] == ("act", "open_data_folder")]
    assert len(found) == 1
    assert found[0][2] is True


def test_it_is_not_under_the_library_heading(rows):
    """Two folders, two places. One "Open folder" under Library that opened
    the settings dir is how people went looking for their charts in
    Application Support."""
    out = rows()["rows"]
    labels = [strip_ansi(r[0](False, False)).strip().lower() for r in out]
    library = labels.index(copy.ROW_LIBRARY.lower())
    app = labels.index(copy.ROW_APP.lower())
    data = next(i for i, r in enumerate(out) if r[1] == ("act", "open_data_folder"))
    charts = next(i for i, r in enumerate(out) if r[1] == ("act", "open_library"))
    assert library < charts < app < data


class TestOpeningTheLibrary:
    @pytest.fixture
    def app(self, monkeypatch):
        from sync import SyncApp
        opened = []
        monkeypatch.setattr("src.core.files.open_folder",
                            lambda p: opened.append(p) or True)
        monkeypatch.setattr("src.app.auth.wait_with_skip", lambda *a, **k: None)
        a = object.__new__(SyncApp)
        a.opened = opened
        return a

    def test_it_opens_the_library_not_the_data_folder(self, app, monkeypatch, tmp_path):
        from pathlib import Path
        from src.core import paths
        monkeypatch.setenv("SYNCHOTIC_LIBRARY", str(tmp_path))
        app.handle_open_library_folder()
        assert [Path(paths.plain_path(p)) for p in app.opened] == [tmp_path]

    def test_a_disconnected_library_says_so_instead_of_opening(self, app, monkeypatch,
                                                               tmp_path, capsys):
        monkeypatch.setenv("SYNCHOTIC_LIBRARY", str(tmp_path / "unplugged"))
        app.handle_open_library_folder()
        assert app.opened == []
        assert copy.LIBRARY_MISSING in capsys.readouterr().out


def test_escaping_the_screen_quits_rather_than_acting(rows):
    """Esc is not an action. Returning a stray value would fire a handler."""
    assert rows()["returned"][0] == "quit"
