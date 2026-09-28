"""purge_on_sync: off means sync only adds and updates, and every place that
counts or performs a deletion has to agree. On, purge plans every drive before
deleting anything and asks at most once per sync, about the total."""
import pytest

from src import copy
from src.config.settings import UserSettings, purges
from src.core.formatting import format_size
from src.sync.cache import (CachedSetlistStats, PersistentStatsCache, SyncCache,
                            aggregate_folder_stats)


class Settings:
    """Drives in `enabled` are on, setlists in `off` are off."""

    def __init__(self, purge=True, enabled=("d1",), off=()):
        self.purge_on_sync = purge
        self._enabled = set(enabled)
        self._off = set(off)

    def is_drive_enabled(self, folder_id):
        return folder_id in self._enabled

    def is_subfolder_enabled(self, folder_id, name):
        return (folder_id, name) not in self._off

    def get_disabled_subfolders(self, folder_id):
        return {name for fid, name in self._off if fid == folder_id}


class TestTheSetting:
    def test_it_is_on_by_default(self, tmp_path):
        assert UserSettings(tmp_path / "settings.json").purge_on_sync is True

    def test_off_survives_a_save(self, tmp_path):
        path = tmp_path / "settings.json"
        settings = UserSettings.load(path)
        settings.purge_on_sync = False
        settings.save()
        assert UserSettings.load(path).purge_on_sync is False

    def test_junk_reads_as_on(self, tmp_path):
        path = tmp_path / "settings.json"
        path.write_text('{"version": 1, "purge_on_sync": "nope"}')
        assert UserSettings.load(path).purge_on_sync is True

    @pytest.mark.parametrize("typed", ['"false"', '"off"', '"no"', "0", '"FALSE"'])
    def test_off_typed_by_hand_is_off(self, tmp_path, typed):
        """Reading these as the default turned deleting on."""
        path = tmp_path / "settings.json"
        path.write_text('{"version": 1, "purge_on_sync": %s}' % typed)
        assert UserSettings.load(path).purge_on_sync is False

    def test_no_settings_means_the_default(self):
        assert purges(None) is True
        assert purges(object()) is True


# --- the planners -----------------------------------------------------------

@pytest.fixture
def library(tmp_path, monkeypatch):
    """Two drives we own, each holding a file nothing accounts for, and a
    partial download in the first."""
    markers = tmp_path / "state" / "markers"
    markers.mkdir(parents=True)
    monkeypatch.setattr("src.sync.markers.get_markers_dir", lambda: markers)
    monkeypatch.setattr("src.sync.cache._cache", SyncCache())
    monkeypatch.setattr("src.sync.ownership.is_library_adopted", lambda: True)
    monkeypatch.setattr("src.sync.ownership.resolve_owned_drives",
                        lambda folders: {f["folder_id"] for f in folders})
    lib = tmp_path / "library"
    for name in ("One", "Two"):
        (lib / name).mkdir(parents=True)
        (lib / name / "stray.txt").write_text("not ours")
    (lib / "One" / "_download_x.7z").write_text("half")
    return lib


FOLDERS = [{"name": "One", "folder_id": "d1", "files": []},
           {"name": "Two", "folder_id": "d2", "files": []}]


class TestThePurgePlanner:
    def test_off_plans_nothing(self, library):
        from src.sync.purge_planner import plan_purge
        files, _ = plan_purge(FOLDERS, library, Settings(purge=False, enabled=("d1",)))
        assert files == []

    def test_on_plans_extras_and_the_disabled_drive(self, library):
        from src.sync.purge_planner import plan_purge
        files, _ = plan_purge(FOLDERS, library, Settings(enabled=("d1",)))
        assert {p.name for p, _ in files} == {"stray.txt", "_download_x.7z"}
        assert {p.parent.name for p, _ in files} == {"One", "Two"}


class TestTheDownloadPlanner:
    def test_off_still_downloads_what_is_missing(self, tmp_path):
        """The download planner never deletes, so off changes nothing there:
        a missing chart is still fetched."""
        from src.sync.download_planner import plan_downloads
        files = [{"id": "1", "path": "Set/c1/song.ini", "size": 1, "md5": ""}]
        tasks, _, _ = plan_downloads(files, tmp_path)
        assert [t.rel_path for t in tasks] == ["Set/c1/song.ini"]


class TestTheStatusFigures:
    """compute_setlist_stats stores what is on disk; aggregation decides what
    of it is going to be deleted, which is where the setting applies."""

    @pytest.fixture
    def cache(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.sync.cache.get_cache_dir", lambda: tmp_path)
        cache = PersistentStatsCache()
        cache.set_setlist("d1", "Off", CachedSetlistStats(
            total_charts=5, synced_charts=5, total_size=500, synced_size=500,
            disk_files=10, disk_size=500, disk_charts=5))
        return cache

    def test_on_counts_a_disabled_setlist_as_purgeable(self, cache):
        agg = aggregate_folder_stats("d1", ["Off"], Settings(off={("d1", "Off")}), cache)
        assert (agg.purgeable_files, agg.purgeable_size) == (10, 500)

    def test_off_counts_nothing(self, cache):
        agg = aggregate_folder_stats(
            "d1", ["Off"], Settings(purge=False, off={("d1", "Off")}), cache)
        assert (agg.purgeable_files, agg.purgeable_size, agg.purgeable_charts) == (0, 0, 0)

    def test_off_changes_the_stats_hash_and_on_does_not(self, cache):
        on = cache.compute_settings_hash("d1", Settings())
        assert cache.compute_settings_hash("d1", Settings(purge=False)) != on
        assert cache.compute_settings_hash("d1", Settings(purge=True)) == on


class TestPreflight:
    def test_off_has_nothing_to_purge(self):
        from src.sync.preflight import GB, gather

        class Stats:
            total_size = synced_size = 0
            disk_files, disk_size, disk_charts = 100, 5 * GB, 80

        class Cache:
            def get_setlist(self, folder_id, name):
                return Stats()

        folders = [{"folder_id": "d1", "name": "One", "setlists": ["Off"]}]
        on = gather(folders, Settings(off={("d1", "Off")}), Cache())
        off = gather(folders, Settings(purge=False, off={("d1", "Off")}), Cache())
        assert on[2:] == (80, 5 * GB)
        assert off[2:] == (0, 0)

    def test_a_disabled_drive_we_never_synced_is_not_counted(self):
        """Purge leaves that folder alone, so the warning must not count it."""
        from src.sync.preflight import GB, gather

        class Stats:
            total_size = synced_size = 0
            disk_files, disk_size, disk_charts = 100, 5 * GB, 80

        class Cache:
            def get_setlist(self, folder_id, name):
                return Stats()

        folders = [{"folder_id": "d2", "name": "Two", "setlists": ["Pack"]}]
        off = Settings(enabled=())
        assert gather(folders, off, Cache(), owned={"d2"})[2:] == (80, 5 * GB)
        assert gather(folders, off, Cache(), owned=set())[2:] == (0, 0)

    def test_off_drops_the_unowned_library_warning(self):
        """It says the folder's contents WILL BE DELETED, which off makes false."""
        from src.sync.preflight import Setup, check_setup
        base = dict(colliding_folders=("One",), library_adopted=False,
                    drives_enabled=1, setlists_enabled=1)
        assert "unowned_library" in [c.kind for c in check_setup(Setup(**base))]
        assert "unowned_library" not in [
            c.kind for c in check_setup(Setup(deletes=False, **base))]


# --- the purge itself -------------------------------------------------------

class Dialog:
    asked = []
    answer = True

    def __init__(self, text):
        Dialog.asked.append(text)

    def run(self):
        return Dialog.answer


@pytest.fixture
def dialog(monkeypatch):
    Dialog.asked = []
    Dialog.answer = True
    monkeypatch.setattr("src.ui.widgets.confirm.ConfirmDialog", Dialog)
    return Dialog


def _purge(library, settings):
    from src.sync.purge_flow import purge_all_folders
    from src.ui.widgets.progress import FolderProgress
    progress = FolderProgress(0, 0)
    purge_all_folders(FOLDERS, library, settings, progress=progress)
    return progress


class TestPurgeAsksOnce:
    @pytest.fixture(autouse=True)
    def ask_for_anything(self, monkeypatch):
        monkeypatch.setattr("src.sync.purge_flow.PURGE_CONFIRM_FILE_THRESHOLD", 0)

    def test_one_question_for_every_drive_with_the_total(self, library, dialog):
        """Two drives with something to delete, one of them disabled, which
        used to be emptied without asking at all."""
        _purge(library, Settings(enabled=("d1",)))
        assert dialog.asked == [copy.PURGE_CONFIRM.format(
            files="2 files", size=format_size(16))]
        assert not (library / "One" / "stray.txt").exists()
        assert not (library / "Two" / "stray.txt").exists()

    def test_declining_deletes_nothing_but_partials(self, library, dialog):
        dialog.answer = False
        _purge(library, Settings(enabled=("d1",)))
        assert (library / "One" / "stray.txt").exists()
        assert (library / "Two" / "stray.txt").exists()
        assert not (library / "One" / "_download_x.7z").exists()

    def test_declining_still_reads_as_cancelled(self, library, dialog):
        dialog.answer = False
        progress = _purge(library, Settings(enabled=("d1",)))
        rows = [(e.name, e.context) for e in progress.screen.entries._history]
        assert (copy.PURGE, copy.CANCELLED) in rows
        assert any(name == copy.NOTE_PARTIALS for name, _ in rows), "partials get their own row"

    def test_cancelling_the_walk_deletes_nothing_at_all(self, library, dialog):
        """Not even the partials sweep, which walks the library again."""
        from src.sync.purge_flow import purge_all_folders
        from src.ui.widgets.progress import FolderProgress
        purge_all_folders(FOLDERS, library, Settings(enabled=("d1",)),
                          progress=FolderProgress(0, 0), cancel_check=lambda: True)
        assert (library / "One" / "_download_x.7z").exists()
        assert (library / "Two" / "stray.txt").exists()

    def test_partials_alone_ask_nothing(self, library, dialog):
        (library / "One" / "stray.txt").unlink()
        (library / "Two" / "stray.txt").unlink()
        _purge(library, Settings(enabled=("d1", "d2")))
        assert dialog.asked == []
        assert not (library / "One" / "_download_x.7z").exists()


class TestPurgeBelowTheThreshold:
    def test_deletes_without_asking(self, library, dialog):
        _purge(library, Settings(enabled=("d1",)))
        assert dialog.asked == []
        assert not (library / "Two" / "stray.txt").exists()


class TestPurgeOff:
    def test_deletes_nothing_and_asks_nothing(self, library, dialog, monkeypatch):
        monkeypatch.setattr("src.sync.purge_flow.PURGE_CONFIRM_FILE_THRESHOLD", 0)
        _purge(library, Settings(purge=False, enabled=("d1",)))
        assert dialog.asked == []
        assert (library / "One" / "stray.txt").exists()
        assert (library / "Two" / "stray.txt").exists()

    def test_does_not_use_up_the_first_sync_guard(self, library, dialog, monkeypatch):
        """The first purge in a library we never synced deletes nothing, since
        its folders may be the user's own. A sync with purge off warned about
        nothing either, so it must leave that guard for when purge turns on."""
        adopted = []
        monkeypatch.setattr("src.sync.ownership.is_library_adopted", lambda: bool(adopted))
        monkeypatch.setattr("src.sync.ownership.mark_library_adopted", lambda: adopted.append(1))
        _purge(library, Settings(purge=False, enabled=("d1",)))
        assert adopted == []
        _purge(library, Settings(enabled=("d1",)))
        assert adopted == [1]
        assert (library / "One" / "stray.txt").exists(), "the first purge only adopts"

    def test_still_sweeps_partial_downloads(self, library, dialog):
        _purge(library, Settings(purge=False, enabled=("d1",)))
        assert not (library / "One" / "_download_x.7z").exists()
