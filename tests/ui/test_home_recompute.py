"""A home screen refresh adds up what is measured; it does not measure.

Once a drive's first setlist was scanned the drive had files, and every refresh
then walked each of its unmeasured setlists on disk. On an external drive one
refresh took minutes, so the header sat blank through a whole first scan.
"""
import pytest

from src.config.settings import UserSettings
from src.ui.screens.home import compute_main_menu_cache

FOLDERS = [{"folder_id": "drive-a", "name": "Drive A", "files": [
    {"path": "Setlist A/song/notes.chart", "size": 10, "id": "f1"},
    {"path": "Setlist B/song/notes.chart", "size": 20, "id": "f2"},
]}]


@pytest.fixture
def settings(tmp_path, monkeypatch):
    library = tmp_path / "library"
    library.mkdir()
    monkeypatch.setenv("SYNCHOTIC_LIBRARY", str(library))
    s = UserSettings.load(tmp_path / "settings.json")
    s.set_drive_enabled("drive-a", True)
    return s


@pytest.fixture
def walks(monkeypatch):
    calls = []

    def walk(folder, setlist, *args, **kwargs):
        calls.append(setlist)
        raise AssertionError("measured on disk during a refresh")
    monkeypatch.setattr("src.ui.screens.home.compute_setlist_stats", walk)
    return calls


def test_a_refresh_never_walks_the_disk(settings, walks, tmp_path):
    compute_main_menu_cache(FOLDERS, settings, tmp_path / "library", None,
                            measure=False)
    assert walks == []


def test_startup_still_measures(settings, walks, tmp_path):
    """Before the home screen opens nothing else measures, so this one must."""
    with pytest.raises(AssertionError, match="measured on disk"):
        compute_main_menu_cache(FOLDERS, settings, tmp_path / "library", None)
