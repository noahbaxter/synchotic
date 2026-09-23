"""The home header when there are no numbers to show.

The numbers are zero for the whole first scan too, so reading "No drives
enabled" off them told someone whose previous library had just been restored
that nothing came back.
"""
import pytest

from src import copy
from src.config.settings import UserSettings
from src.ui.screens.home import _empty_hint, compute_main_menu_cache

FOLDERS = [{"folder_id": "drive-a", "name": "Drive A", "files": None}]


class _Scanning:
    def is_done(self):
        return False

    def __getattr__(self, name):
        return lambda *args, **kwargs: None


@pytest.fixture
def settings(tmp_path, monkeypatch):
    library = tmp_path / "library"
    library.mkdir()
    monkeypatch.setenv("SYNCHOTIC_LIBRARY", str(library))
    return UserSettings.load(tmp_path / "settings.json")


def _header(settings, tmp_path):
    return compute_main_menu_cache(FOLDERS, settings, tmp_path / "library", None,
                                   background_scanner=_Scanning()).subtitle


def test_a_drive_that_is_on_is_not_called_off_while_the_scan_runs(settings, tmp_path):
    settings.set_drive_enabled("drive-a", True)
    assert _header(settings, tmp_path) == ""


def test_nothing_on_says_so_even_mid_scan(settings, tmp_path):
    assert _header(settings, tmp_path) == copy.HOME_NO_DRIVES


def test_drives_on_with_nothing_picked_names_the_setlists(settings):
    settings.set_drive_enabled("drive-a", True)
    assert _empty_hint(FOLDERS, settings, scan_complete=True) == copy.HOME_NO_SETLISTS
