"""The whole sync run, end to end, on one panel: download, verify, purge and
stats, with the Drive, disk and terminal work stubbed. Unit tests of each piece
passed while the run itself crashed on its first line."""
import pytest

from src import copy
from src.config.settings import DOWNLOAD_MODE_ANONYMOUS, UserSettings


class _Scanner:
    """Nothing enabled, scan finished."""

    def get_enabled_setlist_count(self):
        return 0

    def is_done(self):
        return True

    def has_scan_failures(self):
        return False

    def get_stats(self):
        return None

    def __getattr__(self, name):
        return lambda *a, **k: False


@pytest.fixture
def run(tmp_path, monkeypatch):
    from sync import SyncApp

    library = tmp_path / "library"
    library.mkdir()
    monkeypatch.setenv("SYNCHOTIC_LIBRARY", str(library))
    for name in ("clear_screen", "print_header", "wait_with_skip"):
        monkeypatch.setattr(f"src.app.sync_flow.{name}", lambda *a, **k: None)
    monkeypatch.setattr("src.app.sync_flow.rebuild_markers_from_disk",
                        lambda *a, **k: (0, 0))

    class _Keys:
        def __init__(self, on_key):
            pass

        def start(self):
            return self

        def stop(self):
            pass

    monkeypatch.setattr("src.ui.primitives.keys.KeyMonitor", _Keys)

    calls = {}

    def purge(*args, **kwargs):
        calls["purge_progress"] = kwargs.get("progress")
        return set()

    monkeypatch.setattr("src.app.sync_flow.purge_all_folders", purge)
    monkeypatch.setattr("src.app.sync_flow.compute_main_menu_cache",
                        lambda *a, **k: "fresh menu cache")

    app = object.__new__(SyncApp)
    app.user_settings = UserSettings(tmp_path / "settings.json")
    app.user_settings.download_mode = DOWNLOAD_MODE_ANONYMOUS
    app.folders = []
    app.custom_folders = None
    app.drives_config = None
    app._background_scanner = _Scanner()
    app.folder_stats_cache = type("C", (), {"invalidate": lambda self, fid: None})()
    app.auth = type("A", (), {"is_signed_in": False, "is_available": False})()
    monkeypatch.setattr(type(app), "_get_combined_drives_config", lambda self: None)
    monkeypatch.setattr(type(app), "_preflight_ok", lambda self: True)
    return app, calls


def test_a_setlist_needing_nothing_resolves_quietly_on_the_panel(tmp_path, monkeypatch):
    """The bar counts it; no row, and nothing printed under the panel."""
    from src.sync.folder_sync import FolderSync
    from src.ui.widgets.progress import FolderProgress

    monkeypatch.setenv("SYNCHOTIC_LIBRARY", str(tmp_path))
    progress = FolderProgress(total_files=0, total_folders=0)
    result = FolderSync(client=None).sync_folder(
        {"name": "Drive", "folder_id": "d1", "files": []}, tmp_path, [],
        skip_marker_rebuild=True, progress=progress)
    assert result == (0, 0, 0, [], False, 0)
    assert progress.screen.entries.count() == 0


def test_a_run_with_nothing_to_do_goes_all_the_way_through(run, capsys):
    app, calls = run
    assert app.handle_sync() == "fresh menu cache"
    assert calls["purge_progress"] is not None, "purge must draw into the run's panel"
    assert copy.FINISHED_IN.split("{")[0] in capsys.readouterr().out


def test_a_failed_setlist_does_not_hold_the_run_for_disabled_ones(monkeypatch, tmp_path):
    """One enabled setlist downloaded, one failed to scan, and disabled game
    rips still scanning. There is nothing left to download, so the run moves
    on instead of waiting for scans it will never use."""
    from types import SimpleNamespace
    from sync import SyncApp

    monkeypatch.setenv("SYNCHOTIC_LIBRARY", str(tmp_path))
    ready = SimpleNamespace(setlist_id="s1", name="Pack", drive_name="Drive",
                            drive_id="d1", drive={"name": "Drive", "folder_id": "d1",
                                                  "files": []})

    class Scanner:
        def get_enabled_setlist_count(self):
            return 2  # s1 scanned, s2 failed

        def get_scanned_enabled_setlists(self):
            return [ready]

        def is_all_enabled_scanned(self):
            return True

        def is_done(self):
            return False  # disabled setlists still going

        def get_stats(self):
            return None

    class Progress:
        cancelled = False

        def __getattr__(self, name):
            return lambda *a, **k: None

    def waited(*a):
        raise AssertionError("the run waited on the disabled scans")
    monkeypatch.setattr("time.sleep", waited)

    app = object.__new__(SyncApp)
    app._background_scanner = Scanner()
    app.sync = SimpleNamespace(sync_folder=lambda *a, **k: (0, 0, 0, [], False, 0))

    cancelled, synced, *_ = app._sync_folders_sequentially(Progress())

    assert cancelled is False
    assert synced == {"d1"}
