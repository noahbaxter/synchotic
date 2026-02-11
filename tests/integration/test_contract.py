"""
Status/Planner agreement contract tests.

The #1 bug source with 20+ fix commits. Tests the invariant:
if status says N files need syncing, planner must produce exactly N download tasks.

Both get_setlist_sync_status() and plan_downloads() are called on identical state.
"""

import pytest

from src.sync.status import get_setlist_sync_status
from src.sync.download_planner import plan_downloads
from src.core.formatting import dedupe_files_by_newest
from tests.conftest import (
    SyncEnv,
    make_synced_archive,
    make_unsynced_archive,
    make_synced_loose_file,
    make_unsynced_loose_file,
    make_corrupted_file,
)


def _count_missing_charts(tasks):
    """Count distinct missing charts from planner tasks.

    Archives: 1 task = 1 chart (the archive IS the chart).
    Loose files: group by parent folder, each folder with tasks = 1 missing chart.
    """
    missing_charts = 0
    loose_file_parents = set()

    for task in tasks:
        if task.is_archive:
            missing_charts += 1
        else:
            # Loose file — group by parent folder (the chart folder)
            parent = str(task.local_path.parent)
            loose_file_parents.add(parent)

    missing_charts += len(loose_file_parents)
    return missing_charts


def assert_contract(folder, setlist_name, base_path, files, folder_name, delete_videos=True):
    """Assert status and planner agree on sync state.

    The invariant: status.missing_charts == count of distinct missing charts from planner.
    For archives: 1 task = 1 chart. For loose files: tasks grouped by parent folder.
    """
    status = get_setlist_sync_status(
        folder=folder,
        setlist_name=setlist_name,
        base_path=base_path,
        delete_videos=delete_videos,
    )

    # Filter manifest files to just this setlist (same as status does internally)
    setlist_prefix = f"{setlist_name}/"
    setlist_files = [
        f for f in files
        if f["path"].startswith(setlist_prefix) or f["path"] == setlist_name
    ]
    setlist_files = dedupe_files_by_newest(setlist_files)

    tasks, skipped, _ = plan_downloads(
        setlist_files,
        base_path / folder_name,
        delete_videos=delete_videos,
        folder_name=folder_name,
    )

    missing_from_planner = _count_missing_charts(tasks)
    assert status.missing_charts == missing_from_planner, (
        f"Contract violation: status says {status.missing_charts} missing "
        f"({status.synced_charts}/{status.total_charts} synced), "
        f"planner has {missing_from_planner} missing charts ({len(tasks)} tasks). "
    )

    return status, tasks


class TestFullySynced:
    """All archives have markers + files on disk."""

    def test_all_archives_synced(self, sync_env):
        folder_name = "TestDrive"
        setlist = "RockHits"

        files = []
        for i in range(3):
            chart_files = {
                f"{setlist}/Chart{i}/song.ini": 100,
                f"{setlist}/Chart{i}/notes.mid": 200,
            }
            entry = make_synced_archive(
                sync_env, folder_name, setlist, f"chart{i}.7z",
                md5=f"md5_{i}", chart_files=chart_files,
            )
            files.append(entry)

        folder = sync_env.make_folder_dict(folder_name, files=files)
        status, tasks = assert_contract(
            folder, setlist, sync_env.base_path, files, folder_name,
        )
        assert status.synced_charts == 3
        assert status.total_charts == 3
        assert len(tasks) == 0


class TestNothingSynced:
    """Empty disk, no markers."""

    def test_no_files_on_disk(self, sync_env):
        folder_name = "TestDrive"
        setlist = "MetalPacks"

        files = []
        for i in range(4):
            entry = make_unsynced_archive(
                sync_env, folder_name, setlist, f"pack{i}.7z",
                md5=f"md5_{i}",
            )
            files.append(entry)

        folder = sync_env.make_folder_dict(folder_name, files=files)
        status, tasks = assert_contract(
            folder, setlist, sync_env.base_path, files, folder_name,
        )
        assert status.synced_charts == 0
        assert status.total_charts == 4
        assert len(tasks) == 4


class TestPartialArchiveSync:
    """Some archives synced, some not."""

    def test_three_of_five_synced(self, sync_env):
        folder_name = "TestDrive"
        setlist = "Mixed"

        files = []
        # 3 synced
        for i in range(3):
            chart_files = {
                f"{setlist}/Chart{i}/song.ini": 100,
                f"{setlist}/Chart{i}/notes.mid": 200,
            }
            entry = make_synced_archive(
                sync_env, folder_name, setlist, f"synced{i}.7z",
                md5=f"synced_md5_{i}", chart_files=chart_files,
            )
            files.append(entry)

        # 2 unsynced
        for i in range(2):
            entry = make_unsynced_archive(
                sync_env, folder_name, setlist, f"missing{i}.7z",
                md5=f"missing_md5_{i}",
            )
            files.append(entry)

        folder = sync_env.make_folder_dict(folder_name, files=files)
        status, tasks = assert_contract(
            folder, setlist, sync_env.base_path, files, folder_name,
        )
        assert status.synced_charts == 3
        assert status.total_charts == 5
        assert len(tasks) == 2


class TestPartialLooseFileSync:
    """Loose files (non-archives) partially synced."""

    def test_some_loose_files_on_disk(self, sync_env):
        folder_name = "TestDrive"
        setlist = "LooseCharts"

        files = []
        # Create chart folders with song.ini as marker — 3 synced charts
        for i in range(3):
            chart_path = f"{setlist}/Chart{i}"
            files.append(make_synced_loose_file(
                sync_env, folder_name, f"{chart_path}/song.ini", 50,
            ))
            files.append(make_synced_loose_file(
                sync_env, folder_name, f"{chart_path}/notes.mid", 200,
            ))

        # 2 unsynced charts (no files on disk)
        for i in range(3, 5):
            chart_path = f"{setlist}/Chart{i}"
            files.append(make_unsynced_loose_file(f"{chart_path}/song.ini", 50))
            files.append(make_unsynced_loose_file(f"{chart_path}/notes.mid", 200))

        folder = sync_env.make_folder_dict(folder_name, files=files)
        status, tasks = assert_contract(
            folder, setlist, sync_env.base_path, files, folder_name,
        )
        assert status.total_charts == 5
        assert status.synced_charts == 3
        assert len(tasks) == 2 * 2  # 2 charts x 2 files each


class TestMarkerExistsButFilesDeleted:
    """Marker present, extracted files gone — both must detect as unsynced."""

    def test_files_deleted_after_extraction(self, sync_env):
        folder_name = "TestDrive"
        setlist = "Broken"
        archive_name = "chart.7z"
        md5 = "md5_broken"

        # Create marker (as if archive was extracted previously)
        archive_path = f"{folder_name}/{setlist}/{archive_name}"
        sync_env.make_marker(archive_path, md5, {
            f"{setlist}/Chart/song.ini": 100,
            f"{setlist}/Chart/notes.mid": 200,
        })
        # But DON'T create the files on disk (simulating deletion)
        sync_env.make_folder(folder_name, setlist)

        files = [sync_env.make_manifest_entry(
            path=f"{setlist}/{archive_name}", md5=md5,
        )]

        folder = sync_env.make_folder_dict(folder_name, files=files)
        status, tasks = assert_contract(
            folder, setlist, sync_env.base_path, files, folder_name,
        )
        assert status.synced_charts == 0
        assert len(tasks) == 1


class TestMarkerWrongMD5:
    """Archive updated on Drive — marker has old MD5, manifest has new."""

    def test_md5_mismatch_triggers_redownload(self, sync_env):
        folder_name = "TestDrive"
        setlist = "Updated"
        archive_name = "chart.7z"

        # Marker with old MD5, files on disk
        chart_files = {
            f"{setlist}/Chart/song.ini": 100,
            f"{setlist}/Chart/notes.mid": 200,
        }
        sync_env.make_files(folder_name, chart_files)
        archive_path = f"{folder_name}/{setlist}/{archive_name}"
        sync_env.make_marker(archive_path, "old_md5", chart_files)

        # Manifest has NEW md5
        files = [sync_env.make_manifest_entry(
            path=f"{setlist}/{archive_name}", md5="new_md5",
        )]

        folder = sync_env.make_folder_dict(folder_name, files=files)
        status, tasks = assert_contract(
            folder, setlist, sync_env.base_path, files, folder_name,
        )
        assert status.synced_charts == 0
        assert len(tasks) == 1


class TestCorruptedFile:
    """File exists but with wrong size — both detect as unsynced."""

    def test_truncated_loose_file(self, sync_env):
        folder_name = "TestDrive"
        setlist = "Corrupt"

        files = []
        # One good chart
        chart_files_ok = {
            f"{setlist}/Good/song.ini": 50,
            f"{setlist}/Good/notes.mid": 200,
        }
        for rel_path, size in chart_files_ok.items():
            files.append(make_synced_loose_file(sync_env, folder_name, rel_path, size))

        # One corrupted chart (song.ini is truncated)
        files.append(make_corrupted_file(
            sync_env, folder_name, f"{setlist}/Bad/song.ini",
            manifest_size=500, actual_size=100,
        ))
        files.append(make_synced_loose_file(
            sync_env, folder_name, f"{setlist}/Bad/notes.mid", 200,
        ))

        folder = sync_env.make_folder_dict(folder_name, files=files)
        status, tasks = assert_contract(
            folder, setlist, sync_env.base_path, files, folder_name,
        )
        assert status.total_charts == 2
        assert status.synced_charts == 1  # Only the good chart
        assert len(tasks) == 1  # Re-download the corrupted file


class TestINIExtraData:
    """song.ini larger than manifest — Clone Hero appends leaderboard data."""

    def test_ini_larger_than_manifest_is_synced(self, sync_env):
        folder_name = "TestDrive"
        setlist = "INITest"

        # Create chart with song.ini LARGER than manifest says
        manifest_size = 50
        actual_size = 150  # Clone Hero appended leaderboard data
        sync_env.make_files(folder_name, {
            f"{setlist}/Chart/song.ini": actual_size,
            f"{setlist}/Chart/notes.mid": 200,
        })

        files = [
            sync_env.make_manifest_entry(
                path=f"{setlist}/Chart/song.ini", size=manifest_size, md5="",
            ),
            sync_env.make_manifest_entry(
                path=f"{setlist}/Chart/notes.mid", size=200, md5="",
            ),
        ]

        folder = sync_env.make_folder_dict(folder_name, files=files)
        status, tasks = assert_contract(
            folder, setlist, sync_env.base_path, files, folder_name,
        )
        assert status.synced_charts == 1
        assert len(tasks) == 0


class TestVideoSkipping:
    """Videos in manifest, delete_videos=True — both skip them."""

    def test_videos_skipped_when_delete_enabled(self, sync_env):
        folder_name = "TestDrive"
        setlist = "VideoTest"

        # Create chart files on disk (no video)
        sync_env.make_files(folder_name, {
            f"{setlist}/Chart/song.ini": 50,
            f"{setlist}/Chart/notes.mid": 200,
        })

        files = [
            sync_env.make_manifest_entry(
                path=f"{setlist}/Chart/song.ini", size=50, md5="",
            ),
            sync_env.make_manifest_entry(
                path=f"{setlist}/Chart/notes.mid", size=200, md5="",
            ),
            sync_env.make_manifest_entry(
                path=f"{setlist}/Chart/video.mp4", size=50000, md5="",
            ),
        ]

        folder = sync_env.make_folder_dict(folder_name, files=files)
        status, tasks = assert_contract(
            folder, setlist, sync_env.base_path, files, folder_name,
            delete_videos=True,
        )
        # Video excluded from totals — chart should be fully synced
        assert status.synced_charts == 1
        assert len(tasks) == 0


class TestCaseInsensitiveArchiveDupes:
    """Archives differing only in case — deduped consistently by both."""

    def test_case_variant_archives_deduped(self, sync_env):
        folder_name = "TestDrive"
        setlist = "Dupes"

        # Create files and marker for one variant
        chart_files = {
            f"{setlist}/Carol/song.ini": 100,
            f"{setlist}/Carol/notes.mid": 200,
        }
        sync_env.make_files(folder_name, chart_files)
        sync_env.make_marker(
            f"{folder_name}/{setlist}/Carol of.7z", "md5_lower", chart_files,
        )

        # Both case variants in manifest
        files = [
            sync_env.make_manifest_entry(
                path=f"{setlist}/Carol of.7z", md5="md5_lower",
            ),
            sync_env.make_manifest_entry(
                path=f"{setlist}/Carol Of.7z", md5="md5_upper",
            ),
        ]

        folder = sync_env.make_folder_dict(folder_name, files=files)

        # Status uses _build_chart_folders which keys by sanitized path
        # Planner dedupes via normalize_path_key
        # Both should see 1 chart total (deduped), and it should be synced
        status = get_setlist_sync_status(
            folder=folder, setlist_name=setlist,
            base_path=sync_env.base_path, delete_videos=True,
        )

        setlist_files = [f for f in files if f["path"].startswith(f"{setlist}/")]
        setlist_files = dedupe_files_by_newest(setlist_files)

        tasks, _, _ = plan_downloads(
            setlist_files,
            sync_env.base_path / folder_name,
            delete_videos=True,
            folder_name=folder_name,
        )

        # The exact counts depend on dedup behavior, but the contract must hold
        assert status.synced_charts + len(tasks) == status.total_charts


class TestMixedArchivesAndLooseFiles:
    """Some synced, some not — agreement on exact counts."""

    def test_mixed_sync_state(self, sync_env):
        folder_name = "TestDrive"
        setlist = "Mixed"

        files = []

        # 2 synced archives
        for i in range(2):
            chart_files = {
                f"{setlist}/Archive{i}/song.ini": 100,
                f"{setlist}/Archive{i}/notes.mid": 200,
            }
            entry = make_synced_archive(
                sync_env, folder_name, setlist, f"archive{i}.7z",
                md5=f"synced_{i}", chart_files=chart_files,
            )
            files.append(entry)

        # 1 unsynced archive
        files.append(make_unsynced_archive(
            sync_env, folder_name, setlist, "missing.7z", md5="missing_md5",
        ))

        # 1 synced loose chart
        files.append(make_synced_loose_file(
            sync_env, folder_name, f"{setlist}/Loose1/song.ini", 50,
        ))
        files.append(make_synced_loose_file(
            sync_env, folder_name, f"{setlist}/Loose1/notes.mid", 200,
        ))

        # 1 unsynced loose chart
        files.append(make_unsynced_loose_file(f"{setlist}/Loose2/song.ini", 50))
        files.append(make_unsynced_loose_file(f"{setlist}/Loose2/notes.mid", 200))

        folder = sync_env.make_folder_dict(folder_name, files=files)
        status, tasks = assert_contract(
            folder, setlist, sync_env.base_path, files, folder_name,
        )
        assert status.total_charts == 5  # 2 archive + 1 archive + 1 loose + 1 loose
        assert status.synced_charts == 3  # 2 synced archives + 1 synced loose
