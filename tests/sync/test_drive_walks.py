"""A drive's folder is listed for purge as soon as its downloads are done,
while other drives are still downloading, so purge finds it already walked.
Deleting still waits for the end."""

from types import SimpleNamespace

import pytest

from src.sync import cache as cache_mod
from src.sync.cache import DriveWalks


@pytest.fixture
def app(tmp_path, monkeypatch):
    from sync import SyncApp

    monkeypatch.setenv("SYNCHOTIC_LIBRARY", str(tmp_path))
    monkeypatch.setattr(cache_mod, "_cache", cache_mod.SyncCache())
    (tmp_path / "Drive" / "pack").mkdir(parents=True)
    (tmp_path / "Drive" / "pack" / "song.ini").write_text("x")

    app = object.__new__(SyncApp)
    app._background_scanner = SimpleNamespace(
        enabled_setlist_keys=lambda drive_id: {"d1/a", "d1/b"})
    app._drive_walks = DriveWalks()
    return app


DRIVE = {"folder_id": "d1", "name": "Drive"}


def _walked(tmp_path):
    return str(tmp_path / "Drive") in cache_mod.get_cache().local_files


def test_it_waits_for_the_drives_last_setlist(app, tmp_path):
    app._walk_if_drive_done(DRIVE, {"d1/a"})
    app._drive_walks.wait()
    assert not _walked(tmp_path)


def test_it_walks_the_drive_once_its_last_setlist_is_down(app, tmp_path):
    app._walk_if_drive_done(DRIVE, {"d1/a", "d1/b"})
    app._drive_walks.wait()
    assert cache_mod.get_cache().local_files[str(tmp_path / "Drive")] == {"pack/song.ini": 1}


def test_a_drive_is_walked_once(app, tmp_path, monkeypatch):
    calls = []
    real = cache_mod.scan_local_files
    monkeypatch.setattr(cache_mod, "scan_local_files",
                        lambda *a, **k: calls.append(a) or real(*a, **k))
    for _ in range(3):
        app._walk_if_drive_done(DRIVE, {"d1/a", "d1/b"})
    app._drive_walks.wait()
    assert len(calls) == 1


def test_with_deleting_off_nothing_is_walked(app, tmp_path):
    app._drive_walks = None
    app._walk_if_drive_done(DRIVE, {"d1/a", "d1/b"})
    assert not _walked(tmp_path)
