# tests/test_library_path.py
"""Library Path: where charts live, and what travels with them.

Markers describe the library, so they live inside it. That makes the library
self-contained but puts state inside a tree that purge walks, and it moves
markers for every existing user. Both are guarded here.
"""
import importlib

import pytest

from src.core import paths


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNCHOTIC_ROOT", str(tmp_path))
    monkeypatch.delenv("SYNCHOTIC_LIBRARY", raising=False)
    paths.set_library_path(None)
    yield
    paths.set_library_path(None)


class TestResolution:
    def test_defaults_beside_the_app(self, tmp_path):
        assert paths.get_library_path() == tmp_path / paths.DOWNLOAD_FOLDER_NAME

    def test_setting_overrides_default(self, tmp_path):
        (tmp_path / "elsewhere").mkdir(parents=True, exist_ok=True)
        paths.set_library_path(tmp_path / "elsewhere")
        assert paths.get_library_path() == tmp_path / "elsewhere"

    def test_env_beats_setting(self, tmp_path, monkeypatch):
        (tmp_path / "from-settings").mkdir(parents=True, exist_ok=True)
        paths.set_library_path(tmp_path / "from-settings")
        monkeypatch.setenv("SYNCHOTIC_LIBRARY", str(tmp_path / "from-env"))
        assert paths.get_library_path() == tmp_path / "from-env"

    def test_download_path_is_an_alias(self):
        assert paths.get_download_path() == paths.get_library_path()

    def test_tilde_expands(self, monkeypatch):
        monkeypatch.setenv("SYNCHOTIC_LIBRARY", "~/charts")
        assert "~" not in str(paths.get_library_path())


class TestStateTravelsWithLibrary:
    def test_markers_live_in_the_library(self, tmp_path):
        from src.sync import markers
        (tmp_path / "lib").mkdir(parents=True, exist_ok=True)
        paths.set_library_path(tmp_path / "lib")
        assert markers.get_markers_dir() == tmp_path / "lib" / paths.LIBRARY_STATE_DIR_NAME / "markers"

    def test_staging_lives_in_the_library(self, tmp_path):
        """Same filesystem as the charts, so the final move is an atomic rename."""
        (tmp_path / "lib").mkdir(parents=True, exist_ok=True)
        paths.set_library_path(tmp_path / "lib")
        assert paths.get_tmp_dir().is_relative_to(tmp_path / "lib")

    def test_state_dir_is_recognised(self, tmp_path):
        (tmp_path / "lib").mkdir(parents=True, exist_ok=True)
        paths.set_library_path(tmp_path / "lib")
        assert paths.is_library_state_path(paths.get_tmp_dir() / "_download_x.7z")
        assert not paths.is_library_state_path(tmp_path / "lib" / "Drive" / "song.ini")


class TestPurgeDoesNotEatItsOwnState:
    def test_staging_is_not_reported_as_a_partial_download(self, tmp_path):
        """find_partial_downloads rglobs the whole library for _download_*."""
        from src.sync.purge_planner import find_partial_downloads
        (tmp_path / "lib").mkdir(parents=True, exist_ok=True)
        paths.set_library_path(tmp_path / "lib")
        lib = paths.get_library_path()

        live = paths.get_tmp_dir() / "_download_inflight.7z"
        live.write_bytes(b"x" * 10)
        stray = lib / "Drive" / "_download_orphan.7z"
        stray.parent.mkdir(parents=True, exist_ok=True)
        stray.write_bytes(b"y" * 10)

        found = {p.name for p, _ in find_partial_downloads(lib)}
        assert "_download_orphan.7z" in found      # real orphan still cleaned
        assert "_download_inflight.7z" not in found  # live staging protected


class TestMigration:
    def test_existing_markers_move_into_the_library(self, tmp_path):
        """A v1.4 user must not silently lose every marker."""
        data_dir = paths.get_data_dir()
        legacy = data_dir / "markers"
        legacy.mkdir(parents=True, exist_ok=True)
        (legacy / "abc123.json").write_text('{"files": ["Set/song.ini"]}')
        (legacy / "def456.json").write_text('{"files": ["Set/notes.mid"]}')

        paths.migrate_legacy_files()

        from src.sync.markers import get_markers_dir
        moved = {p.name for p in get_markers_dir().iterdir()}
        assert moved == {"abc123.json", "def456.json"}

    def test_migration_does_not_clobber_existing_library_markers(self, tmp_path):
        from src.sync.markers import get_markers_dir
        new = get_markers_dir()
        (new / "already.json").write_text("{}")

        legacy = paths.get_data_dir() / "markers"
        legacy.mkdir(parents=True, exist_ok=True)
        (legacy / "old.json").write_text("{}")

        paths.migrate_legacy_files()
        assert (new / "already.json").exists()
        assert (legacy / "old.json").exists()  # left alone, not merged blindly


class TestUnmountedLibrary:
    """A library on a drive that is not connected must stop, not improvise.

    Modelled on a real install whose library sits on /Volumes/terramox. Running
    mkdir at an absent mountpoint creates an empty tree that reads as a library
    with no markers, so the next sync re-downloads the whole collection into a
    folder that disappears on remount.
    """

    def test_missing_configured_library_is_reported_unavailable(self, tmp_path):
        paths.set_library_path(tmp_path / "not-mounted")
        assert paths.library_is_available() is False

    def test_state_dir_refuses_to_create_it(self, tmp_path):
        import pytest
        missing = tmp_path / "not-mounted"
        paths.set_library_path(missing)
        with pytest.raises(paths.LibraryUnavailable):
            paths.get_library_state_dir()
        assert not missing.exists(), "created a library at an absent mountpoint"

    def test_the_error_names_the_path_and_suggests_the_cause(self, tmp_path):
        import pytest
        paths.set_library_path(tmp_path / "not-mounted")
        with pytest.raises(paths.LibraryUnavailable) as e:
            paths.get_library_state_dir()
        assert str(tmp_path / "not-mounted") in str(e.value)
        assert "drive" in str(e.value).lower()

    def test_a_mounted_library_works_normally(self, tmp_path):
        lib = tmp_path / "mounted"
        lib.mkdir()
        paths.set_library_path(lib)
        assert paths.library_is_available() is True
        assert paths.get_library_state_dir() == lib / paths.LIBRARY_STATE_DIR_NAME

    def test_the_default_library_is_still_created_on_demand(self, tmp_path, monkeypatch):
        """Only a library the user chose is treated as must-already-exist."""
        monkeypatch.setenv("SYNCHOTIC_ROOT", str(tmp_path))
        monkeypatch.delenv("SYNCHOTIC_LIBRARY", raising=False)
        paths.set_library_path(None)
        assert paths.library_is_available() is True
        assert paths.get_library_state_dir().is_dir()


class TestLibraryPathPersists:
    def test_round_trips_through_settings(self, tmp_path):
        from src.config.settings import UserSettings
        path = tmp_path / "settings.json"
        s = UserSettings.load(path)
        s.library_path = "/Volumes/terramox/Charts/Sync Charts"
        s.save()
        assert UserSettings.load(path).library_path == "/Volumes/terramox/Charts/Sync Charts"

    def test_absent_setting_reads_as_empty(self, tmp_path):
        from src.config.settings import UserSettings
        assert UserSettings.load(tmp_path / "none.json").library_path == ""
