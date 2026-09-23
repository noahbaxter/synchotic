"""Whatever the library holds is on, so pressing S never deletes it.

A drive nobody has toggled is off, and purge empties an owned drive that is
off. Ownership is recorded inside the library, so a fresh install pointed at a
previous library saw every drive off and owned, and planned to delete all of
it on the first sync. Found drives are turned on, and a found drive's setlists
are only ever turned off when nothing of theirs is on disk.
"""
from pathlib import Path

import pytest

from src.config.settings import UserSettings
from src.sync.background_scanner import BackgroundScanner
from src.sync.library_probe import setlist_on_disk, turn_on_found
from src.sync.ownership import mark_drive_owned
from src.sync.purge_planner import plan_purge

DRIVE = "drv1"
NAME = "Guitar Hero"
# Drive's name for the setlist, and the name sync gave its folder.
KEPT = "Guitar Hero: Metallica"
KEPT_ON_DISK = "Guitar Hero - Metallica"
ABSENT = "Guitar Hero: Van Halen"


class _Drive:
    name = NAME
    folder_id = DRIVE
    group = ""


class _Listed:
    def list_folder(self, folder_id):
        return [{"id": n, "name": n, "mimeType": BackgroundScanner.FOLDER_MIME}
                for n in (KEPT, ABSENT)]


@pytest.fixture
def library(tmp_path, monkeypatch):
    library = tmp_path / "library"
    chart = library / NAME / KEPT_ON_DISK / "song" / "song.ini"
    chart.parent.mkdir(parents=True)
    chart.write_text("x")
    monkeypatch.setenv("SYNCHOTIC_LIBRARY", str(library))
    monkeypatch.setattr("src.sync.markers.get_markers_dir", lambda: tmp_path / "markers")
    mark_drive_owned(DRIVE)
    return library


def _pick(library, settings):
    """A library picked, then discovery naming the drive's setlists."""
    turn_on_found(settings, library, [_Drive()])
    scanner = BackgroundScanner([{"folder_id": DRIVE, "name": NAME}], None, "key",
                                user_settings=settings, download_path=library)
    scanner._client = _Listed()
    scanner._discover_all_setlists()
    return scanner


def test_a_fresh_install_deletes_nothing_it_found(library, tmp_path):
    settings = UserSettings.load(tmp_path / "settings.json")
    _pick(library, settings)

    files, _ = plan_purge([{"folder_id": DRIVE, "name": NAME, "files": None}],
                          library, settings)
    assert files == []


def test_setlists_with_nothing_on_disk_start_off(library, tmp_path):
    """Or turning a previous library back on means downloading the rest."""
    settings = UserSettings.load(tmp_path / "settings.json")
    scanner = _pick(library, settings)

    assert settings.get_disabled_subfolders(DRIVE) == {ABSENT}
    assert scanner.get_enabled_setlist_count() == 1


def test_a_drive_somebody_switched_off_stays_off_at_startup(library, tmp_path):
    settings = UserSettings.load(tmp_path / "settings.json")
    settings.set_drive_enabled(DRIVE, False)

    turn_on_found(settings, library, [_Drive()], undecided_only=True)
    assert settings.is_drive_enabled(DRIVE) is False


def test_an_unreadable_drive_folder_counts_as_holding_everything(tmp_path):
    assert setlist_on_disk(tmp_path / "not-there", NAME)(ABSENT) is True
