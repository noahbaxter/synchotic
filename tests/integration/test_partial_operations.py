"""
Error recovery tests — state consistency after partial/interrupted operations.

Tests that the system recovers correctly when operations are incomplete:
marker rebuild, partial syncs, missing markers, MD5 changes.
"""

from src.sync.markers import rebuild_markers_from_disk, load_marker
from src.sync.sync_checker import is_archive_synced
from src.sync.status import get_setlist_sync_status
from src.sync.download_planner import plan_downloads
from src.sync.purge_planner import plan_purge
from src.sync.cache import clear_cache
from src.core.formatting import dedupe_files_by_newest
from tests.conftest import (
    make_synced_archive,
    make_unsynced_archive,
)


class MockSettings:
    delete_videos = True

    def is_drive_enabled(self, folder_id):
        return True

    def get_disabled_subfolders(self, folder_id):
        return set()


class TestMarkerRebuildBeforeSync:
    """Pre-existing files without markers — rebuild creates markers, planner skips them."""

    def test_rebuild_makes_planner_skip(self, sync_env):
        folder_name = "TestDrive"
        setlist = "Rebuild"

        # Files on disk but no markers
        sync_env.make_files(folder_name, {
            f"{setlist}/Chart1/song.ini": 100,
            f"{setlist}/Chart1/notes.mid": 200,
            f"{setlist}/Chart2/song.ini": 100,
            f"{setlist}/Chart2/notes.mid": 200,
        })

        manifest_files = [
            sync_env.make_manifest_entry(f"{setlist}/pack1.7z", md5="md5_1"),
            sync_env.make_manifest_entry(f"{setlist}/pack2.7z", md5="md5_2"),
        ]
        folders = [sync_env.make_folder_dict(folder_name, files=manifest_files)]

        # Before rebuild — planner wants to download both
        tasks_before, _, _ = plan_downloads(
            manifest_files,
            sync_env.base_path / folder_name,
            folder_name=folder_name,
        )
        assert len(tasks_before) == 2

        # Rebuild markers
        created, _ = rebuild_markers_from_disk(folders, sync_env.base_path)
        assert created == 2

        # After rebuild — planner skips both
        tasks_after, skipped, _ = plan_downloads(
            manifest_files,
            sync_env.base_path / folder_name,
            folder_name=folder_name,
        )
        assert len(tasks_after) == 0
        assert skipped == 2


class TestPartialSyncStateConsistency:
    """Sync 3 of 5 archives — status, planner, and purge all agree."""

    def test_three_of_five_consistent(self, sync_env):
        folder_name = "TestDrive"
        folder_id = "drive1"
        setlist = "Partial"

        files = []
        # 3 synced
        for i in range(3):
            chart_files = {
                f"{setlist}/Chart{i}/song.ini": 100,
                f"{setlist}/Chart{i}/notes.mid": 200,
            }
            entry = make_synced_archive(
                sync_env, folder_name, setlist, f"synced{i}.7z",
                md5=f"synced_{i}", chart_files=chart_files,
            )
            files.append(entry)

        # 2 unsynced
        for i in range(2):
            entry = make_unsynced_archive(
                sync_env, folder_name, setlist, f"missing{i}.7z",
                md5=f"missing_{i}",
            )
            files.append(entry)

        folder = sync_env.make_folder_dict(folder_name, folder_id=folder_id, files=files)

        # Status: 3/5 synced
        status = get_setlist_sync_status(
            folder, setlist, sync_env.base_path,
        )
        assert status.total_charts == 5
        assert status.synced_charts == 3

        # Planner: 2 tasks
        setlist_files = dedupe_files_by_newest(
            [f for f in files if f["path"].startswith(f"{setlist}/")]
        )
        tasks, _, _ = plan_downloads(
            setlist_files,
            sync_env.base_path / folder_name,
            folder_name=folder_name,
        )
        assert len(tasks) == 2

        # Purge: doesn't touch the 3 synced
        clear_cache()
        settings = MockSettings()
        purge_files, stats = plan_purge(
            [folder], sync_env.base_path, user_settings=settings,
        )

        purged_paths = {str(p) for p, _ in purge_files}
        for i in range(3):
            chart_path = str(sync_env.base_path / folder_name / setlist / f"Chart{i}")
            for path_str in purged_paths:
                assert not path_str.startswith(chart_path), (
                    f"Synced chart {i} should not be purged"
                )


class TestMissingMarkerHandling:
    """sync_checker handles missing marker gracefully."""

    def test_no_marker_returns_not_synced(self, sync_env):
        folder_name = "TestDrive"

        # No marker, no files
        synced, size = is_archive_synced(
            folder_name=folder_name,
            checksum_path="Setlist",
            archive_name="pack.7z",
            manifest_md5="any_md5",
            local_base=sync_env.base_path / folder_name,
        )

        assert synced is False
        assert size == 0

    def test_no_marker_with_files_returns_not_synced(self, sync_env):
        folder_name = "TestDrive"

        # Files exist but no marker
        sync_env.make_files(folder_name, {
            "Setlist/Chart/song.ini": 100,
            "Setlist/Chart/notes.mid": 200,
        })

        synced, size = is_archive_synced(
            folder_name=folder_name,
            checksum_path="Setlist",
            archive_name="pack.7z",
            manifest_md5="any_md5",
            local_base=sync_env.base_path / folder_name,
        )

        assert synced is False


class TestArchiveMD5ChangeTrigger:
    """Marker for old MD5, manifest has new MD5 — triggers re-download."""

    def test_md5_change_detected(self, sync_env):
        folder_name = "TestDrive"
        setlist = "Update"

        # Create files and marker with old MD5
        chart_files = {
            f"{setlist}/Chart/song.ini": 100,
            f"{setlist}/Chart/notes.mid": 200,
        }
        sync_env.make_files(folder_name, chart_files)
        sync_env.make_marker(
            f"{folder_name}/{setlist}/pack.7z", "old_md5", chart_files,
        )

        # is_archive_synced with new MD5 should return False
        synced, _ = is_archive_synced(
            folder_name=folder_name,
            checksum_path=setlist,
            archive_name="pack.7z",
            manifest_md5="new_md5",
            local_base=sync_env.base_path / folder_name,
        )
        assert synced is False

        # Planner should include it
        manifest_files = [
            sync_env.make_manifest_entry(f"{setlist}/pack.7z", md5="new_md5"),
        ]
        tasks, _, _ = plan_downloads(
            manifest_files,
            sync_env.base_path / folder_name,
            folder_name=folder_name,
        )
        assert len(tasks) == 1
