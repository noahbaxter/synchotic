"""Purge must never reach outside the library folder.

Modelled on a real install:

    Clone Hero/Charts/            <- launcher lives here, so this is the app dir
        .dm-sync/                 <- markers, settings, token
        Custom/CSC/               <- the user's own charts, nothing to do with us
        Sync Charts/              <- the library, the only thing we manage
            BirdmanExe Drive/
            Guitar Hero/
            Misc/

"Custom" sits beside the library, not inside it. Emptying it would destroy
charts Synchotic never downloaded.
"""
import pytest

from src.sync.cache import SyncCache
from src.sync.folder_sync import purge_all_folders
from src.sync.markers import save_marker

DRIVES = ["BirdmanExe Drive", "Drummer's Monthly Drive", "Guitar Hero", "Misc"]


@pytest.fixture
def install(tmp_path, monkeypatch):
    """Build the layout above and point the app at it."""
    app_dir = tmp_path / "Charts"
    library = app_dir / "Sync Charts"
    markers = app_dir / ".dm-sync" / "markers"
    markers.mkdir(parents=True)
    monkeypatch.setattr("src.sync.markers.get_markers_dir", lambda: markers)
    monkeypatch.setattr("src.sync.cache._cache", SyncCache())

    for d in DRIVES:
        (library / d).mkdir(parents=True)

    # The user's own charts, beside the library.
    theirs = app_dir / "Custom" / "CSC"
    theirs.mkdir(parents=True)
    (theirs / "song.ini").write_text("mine")
    (theirs / "notes.chart").write_text("mine")

    return {"app_dir": app_dir, "library": library, "theirs": theirs}


def _folders():
    return [{"name": d, "folder_id": f"fid_{d}", "files": []} for d in DRIVES]


def test_sibling_custom_folder_is_untouched(install, capsys):
    """The headline: purging the library must not reach into Custom."""
    theirs = install["theirs"]

    purge_all_folders(_folders(), install["library"], user_settings=None)

    assert (theirs / "song.ini").exists()
    assert (theirs / "notes.chart").exists()
    assert theirs.parent.exists()


def test_purge_is_actually_doing_something(install):
    """Otherwise the test above passes for the wrong reason.

    An unmarked file inside a managed drive folder is exactly what purge exists
    to remove, so it proves purge ran rather than no-opped.
    """
    stray = install["library"] / "Guitar Hero" / "not_from_us.chart"
    stray.write_text("x")

    purge_all_folders(_folders(), install["library"], user_settings=None)

    assert not stray.exists(), "purge did not run, so the sibling test proves nothing"
    assert (install["theirs"] / "song.ini").exists()


def test_marked_files_in_the_library_survive(install):
    """A real synced chart is protected by its marker."""
    library = install["library"]
    chart = library / "Guitar Hero" / "pack" / "song.ini"
    chart.parent.mkdir(parents=True)
    chart.write_text("synced")
    save_marker("Guitar Hero/pack.7z", "abc123", {"pack/song.ini": chart.stat().st_size})

    purge_all_folders(_folders(), library, user_settings=None)

    assert chart.exists()
    assert (install["theirs"] / "song.ini").exists()


def test_a_disabled_drive_does_not_leak_into_custom(install):
    """Disabling a drive empties its folder. That folder is inside the library."""
    class AllDisabled:
        def is_drive_enabled(self, drive_id):
            return False

    purge_all_folders(_folders(), install["library"], user_settings=AllDisabled())

    assert (install["theirs"] / "song.ini").exists()
    assert (install["theirs"] / "notes.chart").exists()


def test_the_data_dir_is_not_inside_the_library(install):
    """.dm-sync sits beside the library, so a library walk never sees it."""
    assert (install["app_dir"] / ".dm-sync").exists()
    assert not (install["library"] / ".dm-sync").exists()
