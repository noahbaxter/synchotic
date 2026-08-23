# tests/sync/test_ownership.py
"""Purge must not delete a library it did not create.

Drive names include "Guitar Hero", "Rock Band" and "Misc", which is what players
call their own folders. Once Library Path lets someone point at an existing
collection, a name match is a guess and acting on it destroys real data.
"""
import pytest

from src.core import paths
from src.sync import ownership


@pytest.fixture(autouse=True)
def library(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNCHOTIC_ROOT", str(tmp_path))
    (tmp_path / "lib").mkdir(parents=True, exist_ok=True)
    paths.set_library_path(tmp_path / "lib")
    yield tmp_path / "lib"
    paths.set_library_path(None)


class TestAdoption:
    def test_new_library_is_not_adopted(self):
        assert ownership.is_library_adopted() is False

    def test_marking_makes_it_adopted(self):
        ownership.mark_library_adopted()
        assert ownership.is_library_adopted() is True

    def test_owning_a_drive_also_adopts(self):
        ownership.mark_drive_owned("drive-1")
        assert ownership.is_library_adopted() is True
        assert ownership.get_owned_drives() == {"drive-1"}


class TestOwnership:
    def test_nothing_owned_initially(self):
        assert ownership.get_owned_drives() == set()

    def test_owned_drives_persist(self):
        ownership.mark_drive_owned("drive-1")
        ownership.mark_drive_owned("drive-2")
        assert ownership.get_owned_drives() == {"drive-1", "drive-2"}

    def test_custom_drives_are_tracked_the_same_way(self):
        """Custom folders key on folder_id too, so they get the same protection."""
        ownership.mark_drive_owned("1CGS-E8pZa85sjsh-b8Tzh8U3Xj_r-64t")
        assert "1CGS-E8pZa85sjsh-b8Tzh8U3Xj_r-64t" in ownership.get_owned_drives()

    def test_empty_id_is_ignored(self):
        ownership.mark_drive_owned("")
        assert ownership.get_owned_drives() == set()

    def test_corrupt_file_reads_as_nothing_owned(self):
        """Fail closed: unreadable state must not authorise deletion."""
        ownership.mark_drive_owned("drive-1")
        (paths.get_library_state_dir() / ownership.OWNED_FILE).write_text("{ not json")
        assert ownership.get_owned_drives() == set()


class TestPurgeRefusesUnownedFolders:
    def _folder(self, name="Guitar Hero", fid="gh"):
        return {"name": name, "folder_id": fid, "files": []}

    def test_first_sync_at_an_adopted_library_purges_nothing(self, library, capsys):
        """The catastrophic case: user points at their own collection."""
        from src.sync.folder_sync import purge_all_folders
        theirs = library / "Guitar Hero"
        theirs.mkdir(parents=True)
        (theirs / "their_chart.ini").write_text("mine, not yours")

        purge_all_folders([self._folder()], library, user_settings=None)

        assert (theirs / "their_chart.ini").exists()
        assert "has not synced before" in capsys.readouterr().out

    def test_disabled_drive_we_never_created_is_not_emptied(self, library, capsys):
        from src.sync.folder_sync import purge_all_folders

        class Settings:
            def is_drive_enabled(self, drive_id):
                return False

        ownership.mark_library_adopted()  # past first sync, but own nothing
        theirs = library / "Guitar Hero"
        theirs.mkdir(parents=True)
        (theirs / "their_chart.ini").write_text("mine, not yours")

        purge_all_folders([self._folder()], library, user_settings=Settings())

        assert (theirs / "their_chart.ini").exists()
        assert "did not create this folder" in capsys.readouterr().out


class TestUpgradingUsersKeepPurge:
    """A v1.4 install has thousands of markers and no ownership file.

    Ownership is only recorded when a sync downloads something, and a fully
    synced drive returns before that point. Without deriving ownership from
    markers, upgrading would silently stop disabled-drive purge forever.
    """

    def _folder(self, name="Guitar Hero", fid="gh"):
        return {"name": name, "folder_id": fid, "files": []}

    def test_markers_alone_mean_the_library_is_ours(self):
        from src.sync.markers import save_marker
        assert ownership.is_library_adopted() is False
        save_marker("Guitar Hero/pack.7z", "abc", {"pack/song.ini": 10})
        assert ownership.is_library_adopted() is True

    def test_a_marked_drive_resolves_as_owned(self):
        from src.sync.markers import save_marker
        save_marker("Guitar Hero/pack.7z", "abc", {"pack/song.ini": 10})
        assert ownership.resolve_owned_drives([self._folder()]) == {"gh"}

    def test_an_unmarked_drive_stays_unowned(self):
        """The protection that matters: never claim a folder we did not fill."""
        from src.sync.markers import save_marker
        save_marker("Guitar Hero/pack.7z", "abc", {"pack/song.ini": 10})
        folders = [self._folder(), self._folder("Rock Band", "rb")]
        assert ownership.resolve_owned_drives(folders) == {"gh"}

    def test_backfill_persists_so_it_survives_marker_loss(self):
        from src.sync.markers import save_marker
        save_marker("Guitar Hero/pack.7z", "abc", {"pack/song.ini": 10})
        assert ownership.backfill_owned_from_markers([self._folder()]) == 1
        assert ownership.get_owned_drives() == {"gh"}
        assert ownership.backfill_owned_from_markers([self._folder()]) == 0

    def test_disabled_drive_still_purges_after_upgrade(self, library):
        """The end to end case, exactly as an existing user hits it."""
        from src.sync.folder_sync import purge_all_folders
        from src.sync.markers import save_marker

        class Disabled:
            def is_drive_enabled(self, drive_id):
                return False

        gh = library / "Guitar Hero"
        gh.mkdir(parents=True)
        chart = gh / "synced_chart.ini"
        chart.write_text("downloaded by synchotic")
        save_marker("Guitar Hero/pack.7z", "abc",
                    {"synced_chart.ini": chart.stat().st_size})

        purge_all_folders([self._folder()], library, user_settings=Disabled())

        assert not chart.exists(), "disabled drive was not purged after upgrade"
