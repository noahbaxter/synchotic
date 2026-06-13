# tests/integration/test_tier4_safety.py
"""Locks the tier-4 trust invariant: a file delivered by rclone must produce the
same disk+marker state as tiers 1-3, so the triangle never purges it.

These tests pass on the CURRENT codebase (no rclone code yet) because they assert
properties of the TARGET state that the rclone tier must reproduce. If a later task
makes the triangle disagree about such a state, these go red.

Uses the canonical `sync_env` fixture from tests/conftest.py (monkeypatches
get_markers_dir + a fresh SyncCache), exactly like test_contract.py and
test_purge_safety.py, so wiring matches the proven pattern."""

from src.sync.status import get_setlist_sync_status
from src.sync.download_planner import plan_downloads
from src.sync.purge_planner import plan_purge
from src.sync.cache import clear_cache
from src.core.formatting import dedupe_files_by_newest
from tests.conftest import make_synced_archive


class MockSettings:
    delete_videos = True
    def is_drive_enabled(self, folder_id): return True
    def is_subfolder_enabled(self, folder_id, subfolder): return True
    def get_disabled_subfolders(self, folder_id): return set()


def test_tier4_delivered_archive_is_synced_and_purge_safe(sync_env):
    """The state a correct rclone delivery produces: status=synced, 0 download
    tasks, 0 purge deletions. This is the target Tasks 6-9 must reproduce."""
    entry = make_synced_archive(
        sync_env, "Drive", "SetA", "pack.7z", md5="m1",
        chart_files={"SetA/Chart1/song.ini": 100, "SetA/Chart1/notes.chart": 200},
    )
    files = [entry]
    folder = sync_env.make_folder_dict("Drive", folder_id="fid_drive", files=files)

    status = get_setlist_sync_status(
        folder=folder, setlist_name="SetA", base_path=sync_env.base_path, delete_videos=True
    )
    assert status.missing_charts == 0, "tier-4 delivered archive must read as synced"

    setlist_files = dedupe_files_by_newest(
        [f for f in files if f["path"].startswith("SetA/")]
    )
    tasks, _, _ = plan_downloads(setlist_files, sync_env.base_path / "Drive", True, folder_name="Drive")
    assert tasks == [], "no re-download for a tier-4 delivered file"

    clear_cache()
    purge_files, stats = plan_purge(
        [folder], sync_env.base_path, user_settings=MockSettings()
    )
    chart_dir = str(sync_env.base_path / "Drive" / "SetA" / "Chart1")
    for path, _size in purge_files:
        assert not str(path).startswith(chart_dir), f"purge must NOT delete tier-4 file {path}"


def test_partial_download_does_not_endanger_synced_neighbor(sync_env):
    """A leftover _download_ partial (cancelled rclone job) must never cause purge
    to delete a fully-synced chart next to it."""
    good = make_synced_archive(
        sync_env, "Drive", "SetA", "good.7z", md5="g1",
        chart_files={"SetA/Good/song.ini": 100},
    )
    # Simulate an interrupted delivery: a _download_ temp file with no marker.
    partial = sync_env.base_path / "Drive" / "SetA" / "_download_partial.7z"
    partial.parent.mkdir(parents=True, exist_ok=True)
    partial.write_bytes(b"\x00" * 50)
    folder = sync_env.make_folder_dict("Drive", folder_id="fid_drive", files=[good])

    clear_cache()
    purge_files, _ = plan_purge([folder], sync_env.base_path, user_settings=MockSettings())
    purged = {str(p) for p, _ in purge_files}
    good_file = str(sync_env.base_path / "Drive" / "SetA" / "Good" / "song.ini")
    assert good_file not in purged, "synced neighbor must survive a partial"


def test_download_many_return_arity_is_pinned():
    """Pin download_many's return contract so the tuple change in Task 8 is a
    deliberate, reviewed event and no caller silently mis-unpacks.

    NOTE: update the expected arity from 6 to 7 ONLY in Task 8, together with the
    folder_sync caller. Until then this asserts the current 6-tuple."""
    from src.sync.downloader import FileDownloader
    dl = FileDownloader(auth_token=None)
    result = dl.download_many([], show_progress=False)
    assert isinstance(result, tuple)
    assert len(result) == 7  # Changed to 7 in Task 8: blocked_tasks appended (with folder_sync.py:125)
