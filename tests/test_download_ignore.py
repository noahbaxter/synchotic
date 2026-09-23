"""download_ignore stops a fetch, through one matcher shared by the download
planner, status and extraction. Purge is covered end to end in
integration/test_download_ignore_loop.py."""
import pytest

from src.core.files import matches_ignore
from src.sync.download_planner import plan_downloads
from src.sync.extractor import delete_ignored_files
from src.sync.status import get_setlist_sync_status
from src.sync.cache import clear_cache


@pytest.fixture
def tmp(tmp_path):
    clear_cache()
    yield tmp_path
    clear_cache()


class TestTheMatcher:
    def test_matches_on_the_file_name_not_the_path(self):
        assert matches_ignore("Setlist/Chart/song.mp4", ["*.mp4"])
        assert matches_ignore("Setlist/Chart/Thumbs.db", ["Thumbs.db"])
        assert not matches_ignore("mp4/song.ini", ["*.mp4"])

    def test_case_insensitive(self):
        assert matches_ignore("SONG.MP4", ["*.mp4"])
        assert matches_ignore("song.mp4", ["*.MP4"])

    def test_an_empty_list_ignores_nothing(self):
        assert not matches_ignore("song.mp4", [])
        assert not matches_ignore("song.mp4", None)


class TestACustomPatternIsHonoured:
    """The whole point of the list: "*.iso" has to actually do something."""

    def test_the_planner_skips_it(self, tmp):
        files = [{"id": "1", "path": "Set/disc.iso", "size": 100, "md5": "a"}]
        tasks, skipped, _ = plan_downloads(files, tmp, download_ignore=["*.iso"])
        assert tasks == []
        assert skipped == 1

    def test_the_planner_still_fetches_a_video(self, tmp):
        """download_ignore is a list, not a video flag with extra steps."""
        files = [{"id": "1", "path": "Set/song.mp4", "size": 100, "md5": "a"}]
        tasks, _, _ = plan_downloads(files, tmp, download_ignore=["*.iso"])
        assert len(tasks) == 1

    def test_status_does_not_count_it(self, tmp):
        """A chart is synced when everything we would fetch is there."""
        folder_name, setlist = "Drive", "Set"
        chart = tmp / folder_name / setlist / "Chart"
        chart.mkdir(parents=True)
        (chart / "song.ini").write_bytes(b"x" * 10)
        (chart / "notes.mid").write_bytes(b"x" * 20)

        folder = {"name": folder_name, "files": [
            {"path": f"{setlist}/Chart/song.ini", "size": 10, "md5": "a"},
            {"path": f"{setlist}/Chart/notes.mid", "size": 20, "md5": "b"},
            {"path": f"{setlist}/Chart/disc.iso", "size": 999, "md5": "c"},
        ]}

        ignored = get_setlist_sync_status(folder, setlist, tmp, download_ignore=["*.iso"])
        assert ignored.synced_charts == 1
        assert ignored.total_size == 30, "the .iso we never fetch is not missing size"

        counted = get_setlist_sync_status(folder, setlist, tmp, download_ignore=[])
        assert counted.synced_charts == 0, "not ignored means it has to be on disk"

    def test_extraction_strips_it(self, tmp):
        (tmp / "disc.iso").write_bytes(b"x")
        (tmp / "song.mp4").write_bytes(b"x")
        (tmp / "notes.mid").write_bytes(b"x")
        assert delete_ignored_files(tmp, ["*.iso"]) == 1
        assert sorted(p.name for p in tmp.iterdir()) == ["notes.mid", "song.mp4"]

    def test_extraction_strips_nothing_when_the_list_is_empty(self, tmp):
        (tmp / "song.mp4").write_bytes(b"x")
        assert delete_ignored_files(tmp, []) == 0
        assert (tmp / "song.mp4").exists()


def test_the_app_hands_the_list_to_the_syncer(tmp):
    """The settings list has to reach the downloader, or a custom pattern
    does nothing."""
    from types import SimpleNamespace
    from sync import SyncApp
    from src.config.settings import UserSettings

    app = object.__new__(SyncApp)
    app.client = None
    app.auth = SimpleNamespace(get_token_getter=lambda: None)
    app.user_settings = UserSettings.load(tmp / "settings.json")
    app.user_settings.download_ignore = ["*.iso"]

    app._refresh_sync_token()
    assert app.sync.download_ignore == ["*.iso"]
    assert app.sync.downloader.download_ignore == ["*.iso"]
