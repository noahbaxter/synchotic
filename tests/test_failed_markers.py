"""
Failed marker tests — permanent extraction failure tracking.

Tests the failed marker system that prevents infinite re-download loops
for archives whose extracted files exceed OS path length limits.
"""

import tempfile
from pathlib import Path

import pytest

from src.sync.markers import (
    save_failed_marker,
    load_failed_marker,
    is_permanently_failed,
    get_all_failed_markers,
    delete_failed_markers_for_archive,
    save_marker,
    load_marker,
    get_markers_dir,
)
from src.sync.downloader import _is_path_length_error


@pytest.fixture
def markers_dir(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        d = Path(tmpdir) / "markers"
        d.mkdir()
        monkeypatch.setattr("src.sync.markers.get_markers_dir", lambda: d)
        yield d


class TestFailedMarkerRoundTrip:
    """save → load → is_permanently_failed all agree."""

    def test_save_and_load(self, markers_dir):
        archive = "Drive/Setlist/pack.7z"
        md5 = "abc12345"
        error = "[Errno 36] File name too long"

        path = save_failed_marker(archive, md5, error)
        assert path.exists()

        loaded = load_failed_marker(archive, md5)
        assert loaded is not None
        assert loaded["archive_path"] == archive
        assert loaded["md5"] == md5
        assert loaded["error"] == error
        assert "failed_at" in loaded

    def test_is_permanently_failed(self, markers_dir):
        archive = "Drive/Setlist/pack.7z"
        md5 = "abc12345"

        assert not is_permanently_failed(archive, md5)
        save_failed_marker(archive, md5, "path too long")
        assert is_permanently_failed(archive, md5)

    def test_load_nonexistent_returns_none(self, markers_dir):
        assert load_failed_marker("no/such/archive.7z", "md5") is None


class TestFailedMarkerTTL:
    """Failed markers expire after TTL so environment changes trigger retry."""

    def test_expired_marker_not_failed(self, markers_dir):
        archive = "Drive/Setlist/pack.7z"
        md5 = "abc12345"

        path = save_failed_marker(archive, md5, "path too long")
        assert is_permanently_failed(archive, md5)

        # Backdate the file mtime by 8 days
        import os, time
        old_time = time.time() - (8 * 86400)
        os.utime(path, (old_time, old_time))

        assert not is_permanently_failed(archive, md5)
        # Expired marker should be deleted
        assert not path.exists()

    def test_fresh_marker_still_active(self, markers_dir):
        archive = "Drive/Setlist/pack.7z"
        md5 = "abc12345"

        path = save_failed_marker(archive, md5, "path too long")

        # Backdate by 6 days (within 7-day TTL)
        import os, time
        old_time = time.time() - (6 * 86400)
        os.utime(path, (old_time, old_time))

        assert is_permanently_failed(archive, md5)


class TestFailedMarkerMD5Specificity:
    """Failed marker for MD5 A doesn't block MD5 B (archive updated on Drive)."""

    def test_different_md5_not_failed(self, markers_dir):
        archive = "Drive/Setlist/pack.7z"
        save_failed_marker(archive, "old_md5", "path too long")

        assert is_permanently_failed(archive, "old_md5")
        assert not is_permanently_failed(archive, "new_md5")


class TestFailedMarkersIndependentFromSuccess:
    """Failed markers don't interfere with success markers."""

    def test_both_coexist(self, markers_dir):
        archive = "Drive/Setlist/pack.7z"

        # Save a success marker
        save_marker(archive, "good_md5", {"Setlist/Chart/song.ini": 100})
        # Save a failed marker for a different MD5
        save_failed_marker(archive, "bad_md5", "path too long")

        # Success marker still works
        assert load_marker(archive, "good_md5") is not None
        # Failed marker still works
        assert is_permanently_failed(archive, "bad_md5")
        # They don't cross-contaminate
        assert not is_permanently_failed(archive, "good_md5")


class TestGetAllFailedMarkers:

    def test_returns_all(self, markers_dir):
        save_failed_marker("Drive/A/pack1.7z", "md5_1", "error 1")
        save_failed_marker("Drive/B/pack2.7z", "md5_2", "error 2")
        save_failed_marker("Drive/C/pack3.7z", "md5_3", "error 3")

        all_failed = get_all_failed_markers()
        assert len(all_failed) == 3
        paths = {m["archive_path"] for m in all_failed}
        assert paths == {"Drive/A/pack1.7z", "Drive/B/pack2.7z", "Drive/C/pack3.7z"}

    def test_empty_when_none(self, markers_dir):
        assert get_all_failed_markers() == []


class TestDeleteFailedMarkers:

    def test_deletes_all_md5_variants(self, markers_dir):
        archive = "Drive/Setlist/pack.7z"
        save_failed_marker(archive, "md5_v1", "error 1")
        save_failed_marker(archive, "md5_v2", "error 2")

        deleted = delete_failed_markers_for_archive(archive)
        assert deleted == 2
        assert not is_permanently_failed(archive, "md5_v1")
        assert not is_permanently_failed(archive, "md5_v2")

    def test_doesnt_delete_other_archives(self, markers_dir):
        save_failed_marker("Drive/A/pack.7z", "md5_a", "error")
        save_failed_marker("Drive/B/pack.7z", "md5_b", "error")

        delete_failed_markers_for_archive("Drive/A/pack.7z")
        assert not is_permanently_failed("Drive/A/pack.7z", "md5_a")
        assert is_permanently_failed("Drive/B/pack.7z", "md5_b")


class TestIsPathLengthError:
    """_is_path_length_error detects platform-specific errors."""

    def test_windows_error(self):
        assert _is_path_length_error("[WinError 206] The filename or extension is too long")

    def test_linux_error(self):
        assert _is_path_length_error("[Errno 36] File name too long: '/very/long/path'")

    def test_macos_error(self):
        assert _is_path_length_error("[Errno 63] File name too long: '/very/long/path'")

    def test_unrelated_error_not_matched(self):
        assert not _is_path_length_error("Permission denied")
        assert not _is_path_length_error("[Errno 13] Permission denied")
        assert not _is_path_length_error("FileNotFoundError: No such file")
        assert not _is_path_length_error("")
