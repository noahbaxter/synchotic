"""Nothing scans into a library that is not there.

A scan writes markers, staging and the scan cache into the library, so one
that is unset or sitting on an unmounted drive has to stop the work up front.
get_library_state_dir would otherwise mkdir an empty tree at a bare
mountpoint, which reads as a library with no markers: the next sync refetches
the whole collection into a folder that disappears on remount.
"""

import pytest

from src.config.settings import UserSettings, DOWNLOAD_MODE_ANONYMOUS
from src.core import paths


class _Auth:
    is_signed_in = True
    session_expired = False


@pytest.fixture
def app(tmp_path, monkeypatch):
    from sync import SyncApp

    def build(library):
        monkeypatch.setenv("SYNCHOTIC_LIBRARY", str(library))
        a = object.__new__(SyncApp)
        a.user_settings = UserSettings(tmp_path / "settings.json")
        a.user_settings.download_mode = DOWNLOAD_MODE_ANONYMOUS
        a.user_settings.library_path = str(library)
        a.auth = _Auth()
        a.folders = [{"folder_id": "drive1", "name": "Drive One", "files": None}]
        a.custom_folders = None
        a._background_scanner = None
        monkeypatch.setattr("src.rclone.is_authed", lambda: False)
        monkeypatch.setattr("sync.get_download_path", lambda: tmp_path)
        monkeypatch.setattr(a, "_migrate_subfolder_customs", lambda: None)
        started = {}

        class _Scanner:
            def __init__(self, folders, *a_, **kw_):
                started["folders"] = folders

            def discover(self, on_progress=None):
                started["discovered"] = True

            def start(self):
                started["started"] = True

            def stop(self):
                pass

        monkeypatch.setattr("sync.BackgroundScanner", _Scanner)
        return a, started

    return build


@pytest.fixture
def missing(tmp_path):
    return tmp_path / "not-mounted"


@pytest.fixture
def mounted(tmp_path):
    lib = tmp_path / "mounted"
    lib.mkdir()
    return lib


def test_background_scan_does_not_start(app, missing):
    a, started = app(missing)

    a._start_background_scan()

    assert not started.get("started")
    assert not missing.exists(), "created a library at an absent mountpoint"


def test_background_scan_starts_when_the_library_is_there(app, mounted):
    a, started = app(mounted)

    a._start_background_scan()

    assert started.get("started")


def test_a_forced_rescan_keeps_the_caches(app, missing, monkeypatch, capsys):
    """It cannot restart, so throwing every cache away first would leave the
    home screen empty with no way to refill it."""
    a, _ = app(missing)
    invalidated = []
    monkeypatch.setattr("src.ui.primitives.wait_with_skip", lambda *a_: None)
    monkeypatch.setattr("sync.wait_with_skip", lambda *a_: None)

    class _Cache:
        def invalidate_all(self):
            invalidated.append(True)

    monkeypatch.setattr("src.sync.cache.get_scan_cache", lambda: _Cache())
    monkeypatch.setattr("src.sync.cache.get_persistent_stats_cache", lambda: _Cache())
    a.folder_stats_cache = _Cache()

    a._handle_force_rescan()

    assert invalidated == []
    assert a.folders[0]["files"] is None
    assert "Cannot scan" in capsys.readouterr().out


def test_sync_refuses_and_says_why(app, missing, monkeypatch, capsys):
    a, started = app(missing)
    monkeypatch.setattr("sync.wait_with_skip", lambda *a_: None)
    monkeypatch.setattr("sync.clear_screen", lambda: None)
    monkeypatch.setattr("sync.print_header", lambda: None)

    assert a.handle_sync() is None
    out = capsys.readouterr().out
    assert "Cannot scan: Library not connected" in out
    assert "Library" in out
    assert not started.get("started")


def test_the_menu_and_the_scan_cannot_disagree(app, missing, mounted):
    """The greyed row and the gate read the same rule, so a row you can click
    never fails once you are past it."""
    for library, expected in [(missing, True), (mounted, False)]:
        a, _ = app(library)
        assert bool(paths.library_blocked_reason()) is expected
        assert bool(a._library_blocked()) is expected
