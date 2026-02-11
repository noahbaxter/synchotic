"""
Path normalization boundary tests.

Tests NFC normalization and path handling across module boundaries.
NFD/NFC mismatches between macOS filesystem, Drive API, markers, and cache
have caused recurring bugs.
"""

import unicodedata

from src.sync.markers import save_marker, load_marker
from src.sync.sync_checker import is_archive_synced
from src.sync.status import get_setlist_sync_status
from src.sync.download_planner import plan_downloads
from src.sync.cache import clear_cache
from src.core.formatting import normalize_path_key, sanitize_drive_name
from tests.conftest import SyncEnv


# NFD and NFC forms of "Pokémon" — é is a common test case
POKEMON_NFC = unicodedata.normalize("NFC", "Pokémon")
POKEMON_NFD = unicodedata.normalize("NFD", "Pokémon")


class TestNFDMarkerLookup:
    """Marker saved with NFC path, looked up with NFD equivalent — should match."""

    def test_nfd_lookup_finds_nfc_marker(self, sync_env):
        folder_name = "TestDrive"
        setlist_nfc = POKEMON_NFC
        archive_name = "chart.7z"

        # Create files and marker using NFC
        chart_files = {f"{setlist_nfc}/Chart/song.ini": 100}
        sync_env.make_files(folder_name, chart_files)
        archive_path_nfc = f"{folder_name}/{setlist_nfc}/{archive_name}"
        sync_env.make_marker(archive_path_nfc, "md5_test", chart_files)

        # Lookup using NFD (as macOS filesystem would return)
        setlist_nfd = POKEMON_NFD
        synced, _ = is_archive_synced(
            folder_name=folder_name,
            checksum_path=setlist_nfd,
            archive_name=archive_name,
            manifest_md5="md5_test",
            local_base=sync_env.base_path / folder_name,
        )

        assert synced, (
            "NFD lookup should find NFC marker — normalize_path_key should handle this"
        )


class TestNFDCacheKey:
    """Cache key from macOS filesystem (NFD) matches NFC-normalized key."""

    def test_nfd_nfc_keys_match(self):
        nfc_key = normalize_path_key(f"TestDrive/{POKEMON_NFC}/chart.7z")
        nfd_key = normalize_path_key(f"TestDrive/{POKEMON_NFD}/chart.7z")

        assert nfc_key == nfd_key, (
            f"NFC key ({nfc_key!r}) should match NFD key ({nfd_key!r}) "
            "after normalize_path_key"
        )


class TestForwardSlashConsistency:
    """Manifest paths with forward slashes, disk paths with OS separator — match in lookups."""

    def test_marker_with_forward_slashes(self, sync_env):
        folder_name = "TestDrive"
        setlist = "Setlist"

        # Create files
        chart_files = {f"{setlist}/Deep/Chart/song.ini": 100}
        sync_env.make_files(folder_name, chart_files)

        # Marker uses forward slashes (as saved by the system)
        archive_path = f"{folder_name}/{setlist}/Deep/pack.7z"
        sync_env.make_marker(archive_path, "md5_test", chart_files)

        # Lookup also uses forward slashes (checksum_path comes from manifest)
        synced, _ = is_archive_synced(
            folder_name=folder_name,
            checksum_path=f"{setlist}/Deep",
            archive_name="pack.7z",
            manifest_md5="md5_test",
            local_base=sync_env.base_path / folder_name,
        )

        assert synced

    def test_plan_downloads_forward_slashes(self, sync_env):
        folder_name = "TestDrive"
        setlist = "Setlist"

        chart_files = {f"{setlist}/Sub/Chart/song.ini": 100}
        sync_env.make_files(folder_name, chart_files)
        sync_env.make_marker(
            f"{folder_name}/{setlist}/Sub/pack.7z", "md5_test", chart_files,
        )

        manifest_files = [
            sync_env.make_manifest_entry(f"{setlist}/Sub/pack.7z", md5="md5_test"),
        ]

        tasks, skipped, _ = plan_downloads(
            manifest_files,
            sync_env.base_path / folder_name,
            folder_name=folder_name,
        )

        assert len(tasks) == 0
        assert skipped == 1


class TestColonSanitizationConsistency:
    """'Guitar Hero: Metallica' sanitized identically by status, planner, and purge."""

    def test_colon_in_setlist_name(self, sync_env):
        folder_name = "TestDrive"
        # Raw name with colon (from Drive API)
        raw_setlist = "Guitar Hero: Metallica"
        # sanitize_drive_name replaces ":" with " -"
        sanitized_setlist = sanitize_drive_name(raw_setlist)

        # Create files using sanitized name (as they'd appear on disk)
        chart_files = {
            f"{sanitized_setlist}/Chart/song.ini": 100,
            f"{sanitized_setlist}/Chart/notes.mid": 200,
        }
        sync_env.make_files(folder_name, chart_files)
        sync_env.make_marker(
            f"{folder_name}/{sanitized_setlist}/pack.7z", "md5_gh",
            chart_files,
        )

        # Manifest uses sanitized paths (scanner sanitizes before storing)
        manifest_files = [
            sync_env.make_manifest_entry(
                f"{sanitized_setlist}/pack.7z", md5="md5_gh",
            ),
        ]

        folder = sync_env.make_folder_dict(folder_name, files=manifest_files)

        # Status should find it synced
        status = get_setlist_sync_status(
            folder, sanitized_setlist, sync_env.base_path,
        )
        assert status.total_charts == 1
        assert status.synced_charts == 1

        # Planner should skip it
        tasks, skipped, _ = plan_downloads(
            manifest_files,
            sync_env.base_path / folder_name,
            folder_name=folder_name,
        )
        assert len(tasks) == 0
        assert skipped == 1
