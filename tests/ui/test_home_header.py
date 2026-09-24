"""The home header is the library as it is on disk.

It used to be "97% | 276/283 charts, 22/94 setlists", a comparison with Drive
that only meant the whole library once a scan had finished, and was blank or
wrong until then. Charts and size on disk need nothing from Drive; checking
Drive, and what sync would change, are the footer's.
"""
import pytest

from src import copy
from src.config.settings import UserSettings
from src.core.formatting import count, format_size
from src.sync.cache import CachedSetlistStats, PersistentStatsCache
from src.ui.components import calc_percent
from src.ui.screens.home import compute_main_menu_cache

DRIVE = "gh"
A, B = "Setlist A", "Setlist B"
FOLDERS = [{"folder_id": DRIVE, "name": "Guitar Hero", "files": None}]


def _on_disk(charts, size, on_drive=None):
    """Stats for a setlist holding `charts` chart folders on disk. Drive's
    count differs on purpose: the header must not read it."""
    remote = on_drive if on_drive is not None else charts
    return CachedSetlistStats(total_charts=remote, total_size=size,
                              synced_charts=charts, synced_size=size,
                              disk_files=charts, disk_size=size, disk_charts=charts)


class _Scanner:
    def __init__(self, done):
        self.done = done

    def is_done(self):
        return self.done

    def is_scanning(self, folder_id):
        return not self.done

    def discovery_failed(self, folder_id):
        return False

    def get_discovered_setlist_names(self, folder_id):
        return [A, B]

    def __getattr__(self, name):
        return lambda *a, **kw: None


@pytest.fixture
def stats(monkeypatch):
    cache = PersistentStatsCache()
    setlists = {}
    cache._setlist_cache = {DRIVE: setlists}
    monkeypatch.setattr("src.ui.screens.home.get_persistent_stats_cache", lambda: cache)
    return setlists


@pytest.fixture
def settings(tmp_path, monkeypatch):
    library = tmp_path / "library"
    library.mkdir()
    monkeypatch.setenv("SYNCHOTIC_LIBRARY", str(library))
    s = UserSettings.load(tmp_path / "settings.json")
    s.set_drive_enabled(DRIVE, True)
    return s


def _header(settings, tmp_path, done):
    return compute_main_menu_cache(FOLDERS, settings, tmp_path / "library", None,
                                   background_scanner=_Scanner(done),
                                   measure=False).subtitle


def _synced(synced, total):
    return f" · {calc_percent(synced, total)}% {copy.FOOTER_SYNCED}"


def test_it_is_what_is_on_disk_then_how_much_of_drive_that_is(settings, stats, tmp_path):
    """Charts and size are the disk's; the percentage compares with Drive,
    by charts. Every setlist has a comparison, so it shows mid-rescan too."""
    stats[A] = _on_disk(4, 100, on_drive=90)
    stats[B] = _on_disk(3, 50, on_drive=3)
    assert _header(settings, tmp_path, done=False) == \
        f"{count(7, 'chart')} · {format_size(150)}" + _synced(7, 93)


def test_a_first_scan_marks_it_as_a_floor_with_no_percentage(settings, stats, tmp_path):
    """Setlist B is not measured yet, so there are at least this many, and a
    percentage of part of the library would read as the whole of it."""
    stats[A] = _on_disk(4, 100)
    assert _header(settings, tmp_path, done=False) == \
        f"{count(4, 'chart', more=True)} · {format_size(100)}"


def test_a_finished_scan_drops_the_floor_even_if_one_failed(settings, stats, tmp_path):
    """A setlist that failed to scan is never measured; waiting for it would
    leave the "+" there, and the percentage away, for good."""
    stats[A] = _on_disk(4, 100)
    assert _header(settings, tmp_path, done=True) == \
        f"{count(4, 'chart')} · {format_size(100)}" + _synced(4, 4)
