"""
Purge safety tests — Don't Delete User Data.

Tests the purge planner in scenarios that historically caused data loss.
The 185GB incident was caused by purge misclassifying extracted archives as "extras".
"""

from src.core.formatting import normalize_path_key, sanitize_path
from src.sync.purge_planner import plan_purge, find_extra_files, find_partial_downloads
from src.sync.markers import get_all_marker_files, rebuild_markers_from_disk
from src.sync.cache import clear_cache
from tests.conftest import (
    SyncEnv,
    make_synced_archive,
    make_unsynced_archive,
    make_synced_loose_file,
)


class MockSettings:
    delete_videos = True

    def __init__(self, disabled_drives=None, disabled_subfolders=None):
        self._disabled_drives = disabled_drives or set()
        self._disabled_subfolders = disabled_subfolders or {}

    def is_drive_enabled(self, folder_id):
        return folder_id not in self._disabled_drives

    def is_subfolder_enabled(self, folder_id, subfolder):
        disabled = self._disabled_subfolders.get(folder_id, set())
        return subfolder not in disabled

    def get_disabled_subfolders(self, folder_id):
        return self._disabled_subfolders.get(folder_id, set())


class TestScanFailureProtection:
    """Scan failure for a setlist should protect its files from purge."""

    def test_failed_setlist_files_not_purged(self, sync_env):
        folder_name = "TestDrive"
        folder_id = "drive1"

        # Files on disk for two setlists
        sync_env.make_files(folder_name, {
            "RockClassics/Chart1/song.ini": 100,
            "RockClassics/Chart1/notes.mid": 200,
            "PopHits/Chart2/song.ini": 100,
        })

        # Create markers for both
        sync_env.make_marker(
            f"{folder_name}/RockClassics/rock.7z", "md5_rock",
            {"RockClassics/Chart1/song.ini": 100, "RockClassics/Chart1/notes.mid": 200},
        )
        sync_env.make_marker(
            f"{folder_name}/PopHits/pop.7z", "md5_pop",
            {"PopHits/Chart2/song.ini": 100},
        )

        manifest_files = [
            sync_env.make_manifest_entry("PopHits/pop.7z", md5="md5_pop"),
            # RockClassics NOT in manifest (scan failed)
        ]
        folders = [sync_env.make_folder_dict(folder_name, folder_id=folder_id, files=manifest_files)]

        # RockClassics scan failed
        failed_setlists = {folder_id: {"RockClassics"}}
        settings = MockSettings()

        purge_files, stats = plan_purge(
            folders, sync_env.base_path,
            user_settings=settings,
            failed_setlists=failed_setlists,
        )

        purged_paths = {str(p) for p, _ in purge_files}
        rock_path = str(sync_env.base_path / folder_name / "RockClassics")

        # No RockClassics files should be in purge list
        for path_str in purged_paths:
            assert not path_str.startswith(rock_path), (
                f"Failed setlist file should be protected: {path_str}"
            )


class TestMissingMarkersRebuildPreventsPurge:
    """Files on disk with no markers — rebuild prevents mass purge."""

    def test_rebuild_then_purge_returns_zero(self, sync_env):
        folder_name = "TestDrive"
        folder_id = "drive1"

        # Extracted files on disk (no markers)
        sync_env.make_files(folder_name, {
            "Setlist/Chart1/song.ini": 100,
            "Setlist/Chart1/notes.mid": 200,
            "Setlist/Chart2/song.ini": 100,
            "Setlist/Chart2/notes.mid": 200,
        })

        manifest_files = [
            sync_env.make_manifest_entry("Setlist/pack1.7z", md5="md5_1"),
            sync_env.make_manifest_entry("Setlist/pack2.7z", md5="md5_2"),
        ]
        folders = [sync_env.make_folder_dict(folder_name, folder_id=folder_id, files=manifest_files)]

        # Rebuild markers from disk
        clear_cache()
        created, _ = rebuild_markers_from_disk(folders, sync_env.base_path)
        assert created == 2

        # Now purge should find nothing to delete
        clear_cache()
        settings = MockSettings()
        purge_files, stats = plan_purge(
            folders, sync_env.base_path, user_settings=settings,
        )

        assert stats.extra_file_count == 0, (
            f"After rebuild, no extras should exist. Got {stats.extra_file_count}"
        )


class TestDisabledSetlistPurgeIsScoped:
    """Disabling setlist A only purges A's files, not B or C."""

    def test_only_disabled_setlist_purged(self, sync_env):
        folder_name = "TestDrive"
        folder_id = "drive1"

        # Files for three setlists
        for setlist in ["SetlistA", "SetlistB", "SetlistC"]:
            sync_env.make_files(folder_name, {
                f"{setlist}/Chart/song.ini": 100,
                f"{setlist}/Chart/notes.mid": 200,
            })
            sync_env.make_marker(
                f"{folder_name}/{setlist}/pack.7z", f"md5_{setlist}",
                {f"{setlist}/Chart/song.ini": 100, f"{setlist}/Chart/notes.mid": 200},
            )

        manifest_files = [
            sync_env.make_manifest_entry(f"{s}/pack.7z", md5=f"md5_{s}")
            for s in ["SetlistA", "SetlistB", "SetlistC"]
        ]
        folders = [sync_env.make_folder_dict(folder_name, folder_id=folder_id, files=manifest_files)]

        # Disable only SetlistA
        settings = MockSettings(disabled_subfolders={folder_id: {"SetlistA"}})
        clear_cache()
        purge_files, stats = plan_purge(
            folders, sync_env.base_path, user_settings=settings,
        )

        purged_paths = {str(p) for p, _ in purge_files}
        setlist_a_path = str(sync_env.base_path / folder_name / "SetlistA")
        setlist_b_path = str(sync_env.base_path / folder_name / "SetlistB")
        setlist_c_path = str(sync_env.base_path / folder_name / "SetlistC")

        # SetlistA files should be purged
        has_a = any(p.startswith(setlist_a_path) for p in purged_paths)
        assert has_a, "Disabled setlist A should have files in purge list"

        # SetlistB and C should NOT be purged
        has_b = any(p.startswith(setlist_b_path) for p in purged_paths)
        has_c = any(p.startswith(setlist_c_path) for p in purged_paths)
        assert not has_b, "Enabled setlist B should NOT be purged"
        assert not has_c, "Enabled setlist C should NOT be purged"


class TestDisabledDrivePurgeIsScoped:
    """Disabling drive X only purges X's files, drive Y untouched."""

    def test_only_disabled_drive_purged(self, sync_env):
        # Drive X (disabled)
        sync_env.make_files("DriveX", {"Setlist/Chart/song.ini": 100})
        sync_env.make_marker(
            "DriveX/Setlist/pack.7z", "md5_x",
            {"Setlist/Chart/song.ini": 100},
        )

        # Drive Y (enabled)
        sync_env.make_files("DriveY", {"Setlist/Chart/song.ini": 100})
        sync_env.make_marker(
            "DriveY/Setlist/pack.7z", "md5_y",
            {"Setlist/Chart/song.ini": 100},
        )

        folders = [
            sync_env.make_folder_dict("DriveX", folder_id="x_id", files=[
                sync_env.make_manifest_entry("Setlist/pack.7z", md5="md5_x"),
            ]),
            sync_env.make_folder_dict("DriveY", folder_id="y_id", files=[
                sync_env.make_manifest_entry("Setlist/pack.7z", md5="md5_y"),
            ]),
        ]

        settings = MockSettings(disabled_drives={"x_id"})
        clear_cache()
        purge_files, stats = plan_purge(
            folders, sync_env.base_path, user_settings=settings,
        )

        purged_paths = {str(p) for p, _ in purge_files}
        drive_x_path = str(sync_env.base_path / "DriveX")
        drive_y_path = str(sync_env.base_path / "DriveY")

        has_x = any(p.startswith(drive_x_path) for p in purged_paths)
        has_y = any(p.startswith(drive_y_path) for p in purged_paths)

        assert has_x, "Disabled drive X should have files in purge list"
        assert not has_y, "Enabled drive Y should NOT be purged"


class TestExtraFilesDetection:
    """Files on disk not in manifest or markers — flagged as extras."""

    def test_unknown_files_flagged(self, sync_env):
        folder_name = "TestDrive"

        # Create known file (in manifest)
        sync_env.make_files(folder_name, {
            "Setlist/Chart/song.ini": 100,
            "Setlist/random_junk.txt": 50,  # Not in manifest or markers
        })
        sync_env.make_marker(
            f"{folder_name}/Setlist/pack.7z", "md5_known",
            {"Setlist/Chart/song.ini": 100},
        )

        marker_files = {normalize_path_key(p) for p in get_all_marker_files()}
        manifest_paths = {normalize_path_key(f"{folder_name}/Setlist/pack.7z")}

        clear_cache()
        extras = find_extra_files(
            folder_name,
            sync_env.base_path / folder_name,
            marker_files,
            manifest_paths,
        )

        extra_names = {p.name for p, _ in extras}
        assert "random_junk.txt" in extra_names


class TestManifestFilesNotFlaggedAsExtras:
    """Loose files that ARE in manifest should not be purged."""

    def test_manifest_loose_files_protected(self, sync_env):
        folder_name = "TestDrive"

        # Create loose file that's in manifest
        sync_env.make_files(folder_name, {
            "Setlist/Chart/song.ini": 100,
            "Setlist/Chart/notes.mid": 200,
        })

        marker_files = set()  # No markers (loose files, not archives)
        manifest_paths = {
            normalize_path_key(f"{folder_name}/{sanitize_path('Setlist/Chart/song.ini')}"),
            normalize_path_key(f"{folder_name}/{sanitize_path('Setlist/Chart/notes.mid')}"),
        }

        clear_cache()
        extras = find_extra_files(
            folder_name,
            sync_env.base_path / folder_name,
            marker_files,
            manifest_paths,
        )

        assert len(extras) == 0, f"Manifest files should not be extras: {extras}"


class TestMarkerTrackedFilesNotFlaggedAsExtras:
    """Extracted archive contents tracked by markers — not purged."""

    def test_marker_files_protected(self, sync_env):
        folder_name = "TestDrive"

        # Create files and marker
        chart_files = {
            "Setlist/Chart/song.ini": 100,
            "Setlist/Chart/notes.mid": 200,
            "Setlist/Chart/album.png": 300,
        }
        sync_env.make_files(folder_name, chart_files)
        sync_env.make_marker(
            f"{folder_name}/Setlist/pack.7z", "md5_pack", chart_files,
        )

        marker_files = {normalize_path_key(p) for p in get_all_marker_files()}
        manifest_paths = {normalize_path_key(f"{folder_name}/Setlist/pack.7z")}

        clear_cache()
        extras = find_extra_files(
            folder_name,
            sync_env.base_path / folder_name,
            marker_files,
            manifest_paths,
        )

        assert len(extras) == 0, f"Marker-tracked files should not be extras: {extras}"


class TestPartialDownloadsPurged:
    """_download_*.7z files should be included in purge."""

    def test_partial_downloads_detected(self, sync_env):
        folder_name = "TestDrive"

        sync_env.make_files(folder_name, {
            "Setlist/_download_pack.7z": 5000,
            "Setlist/Chart/song.ini": 100,
        })

        clear_cache()
        partials = find_partial_downloads(sync_env.base_path / folder_name)

        assert len(partials) == 1
        assert partials[0][0].name == "_download_pack.7z"


class TestPurgeWithAllSetlistsFailed:
    """All setlists fail to scan — nothing purged."""

    def test_all_failed_zero_purge(self, sync_env):
        folder_name = "TestDrive"
        folder_id = "drive1"

        # Files on disk
        sync_env.make_files(folder_name, {
            "SetlistA/Chart/song.ini": 100,
            "SetlistB/Chart/song.ini": 100,
        })

        # Empty manifest (all scans failed)
        manifest_files = []
        folders = [sync_env.make_folder_dict(folder_name, folder_id=folder_id, files=manifest_files)]

        # ALL setlists failed
        failed_setlists = {folder_id: {"SetlistA", "SetlistB"}}
        settings = MockSettings()

        clear_cache()
        purge_files, stats = plan_purge(
            folders, sync_env.base_path,
            user_settings=settings,
            failed_setlists=failed_setlists,
        )

        assert stats.total_files == 0, (
            f"With all setlists failed, nothing should be purged. Got {stats.total_files}"
        )
