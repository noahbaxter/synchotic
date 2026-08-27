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
        """Keep the library's copy, but still move everything else.

        The earlier version of this test asserted that `old.json` stayed put,
        which is what the old destination-is-empty guard did. That guard was the
        bug: one marker in the destination stranded every other marker forever.
        """
        from src.sync.markers import get_markers_dir
        new = get_markers_dir()
        (new / "already.json").write_text('{"keep": "library copy"}')

        legacy = paths.get_data_dir() / "markers"
        legacy.mkdir(parents=True, exist_ok=True)
        (legacy / "already.json").write_text('{"stale": "data dir copy"}')
        (legacy / "old.json").write_text("{}")

        paths.migrate_legacy_files()

        assert (new / "already.json").read_text() == '{"keep": "library copy"}'
        assert (new / "old.json").exists(), "unrelated marker was stranded"

    def test_an_interrupted_migration_resumes(self, tmp_path):
        """The failure that deletes charts.

        A library on another volume makes every move a cross-device copy, so a
        run over thousands of markers can die part way. If the next launch skips
        the remainder, those markers are gone for good, and purge deletes the
        charts they described because nothing claims those files any more.
        """
        from src.sync.markers import get_markers_dir
        legacy = paths.get_data_dir() / "markers"
        legacy.mkdir(parents=True, exist_ok=True)
        for i in range(5):
            (legacy / f"m{i}.json").write_text('{"files": []}')

        # Interrupted after one of five.
        new = get_markers_dir()
        (new / "m0.json").write_text('{"files": []}')
        (legacy / "m0.json").unlink()

        paths.migrate_legacy_files()

        assert {p.name for p in new.iterdir()} == {f"m{i}.json" for i in range(5)}
        assert not legacy.exists(), "legacy dir should be gone once drained"

    def test_every_marker_arrives(self, tmp_path):
        """Count in equals count out. Silent partial loss is the whole risk."""
        from src.sync.markers import get_markers_dir
        legacy = paths.get_data_dir() / "markers"
        legacy.mkdir(parents=True, exist_ok=True)
        for i in range(250):
            (legacy / f"m{i}.json").write_text('{"files": []}')

        paths.migrate_legacy_files()
        assert len(list(get_markers_dir().iterdir())) == 250

    def test_sidecars_are_drained_but_not_counted(self, tmp_path):
        """macOS writes ._ files beside every file on an SMB share.

        Measured on a real 2,720 marker library: the raw file count reported
        2,850 moved. Draining them is right, counting them as markers is not.
        """
        from src.sync.markers import get_markers_dir
        legacy = paths.get_data_dir() / "markers"
        legacy.mkdir(parents=True, exist_ok=True)
        for i in range(3):
            (legacy / f"m{i}.json").write_text('{"files": []}')
            (legacy / f"._m{i}.json").write_bytes(b"\x00\x05\x16\x07")

        notes = paths.migrate_legacy_files()

        assert any("moved 3 markers" in n for n in notes), notes
        assert not legacy.exists(), "sidecars should still be drained"
        assert len([p for p in get_markers_dir().iterdir()
                    if not p.name.startswith("._")]) == 3

    def test_a_marker_it_cannot_move_is_reported(self, tmp_path, monkeypatch):
        """Never claim success while markers are still stuck."""
        import shutil as _shutil
        legacy = paths.get_data_dir() / "markers"
        legacy.mkdir(parents=True, exist_ok=True)
        (legacy / "stuck.json").write_text("{}")

        def refuse(src, dst):
            raise OSError("device not ready")
        monkeypatch.setattr(_shutil, "move", refuse)

        notes = paths.migrate_legacy_files()
        assert any("could not be moved" in n for n in notes), notes
        assert (legacy / "stuck.json").exists(), "marker must survive to retry"

    def test_an_unavailable_library_is_skipped_not_raised(self, tmp_path):
        """Startup calls this before it can show anything. It must not throw."""
        legacy = paths.get_data_dir() / "markers"
        legacy.mkdir(parents=True, exist_ok=True)
        (legacy / "m.json").write_text("{}")

        paths.set_library_path(tmp_path / "not-mounted")
        paths.migrate_legacy_files()  # must not raise

        assert (legacy / "m.json").exists(), "markers must wait for the drive"
        assert not (tmp_path / "not-mounted").exists()


class TestSidecarsInTheMarkersDir:
    """A library on an SMB share collects ._ AppleDouble files beside markers.

    Found on a real 2,720 marker library: get_marked_drive_names raised
    UnicodeDecodeError on the first sidecar. The handlers caught JSONDecodeError
    and OSError, and UnicodeDecodeError is neither, so the ownership check and
    the purge source of truth both died on a file that is not a marker at all.
    """

    def _with_sidecars(self):
        from src.sync.markers import get_markers_dir
        d = get_markers_dir()
        (d / "real.json").write_text(
            '{"archive_path": "Guitar Hero/pack.7z", "files": {"Guitar Hero/a/song.ini": 1}}'
        )
        (d / "._real.json").write_bytes(bytes([0x00, 0x05, 0x16, 0x07, 0xb0, 0xfe]))
        return d

    def test_drive_names_ignore_sidecars(self):
        from src.sync.markers import get_marked_drive_names
        self._with_sidecars()
        assert get_marked_drive_names() == {"Guitar Hero"}

    def test_purge_source_of_truth_survives_them(self):
        """If this raises, purge planning dies. If it silently drops the real
        marker, purge deletes the charts that marker protects."""
        from src.sync.markers import get_all_marker_files
        self._with_sidecars()
        assert get_all_marker_files() == {"Guitar Hero/a/song.ini"}

    def test_ownership_still_adopts_the_library(self):
        from src.sync import ownership
        self._with_sidecars()
        assert ownership.is_library_adopted() is True


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


class TestScanGate:
    """Nothing scans without somewhere to write. library_blocked_reason is the
    one rule the menu greys rows on and every scan entry point checks."""

    class _Settings:
        def __init__(self, library_path=""):
            self.library_path = library_path

    def test_an_unmounted_library_blocks(self, tmp_path):
        paths.set_library_path(tmp_path / "not-mounted")
        assert paths.library_blocked_reason() == "Library not connected"

    def test_an_unset_library_blocks_in_os_dirs_mode(self, monkeypatch, tmp_path):
        monkeypatch.setenv(paths.OS_DIRS_ENV, "1")
        assert paths.library_blocked_reason(self._Settings("")) == "Set a library first"

    def test_a_portable_install_is_never_unset(self, tmp_path):
        """Its default sits beside the launcher, which is how pre-1.5 works."""
        assert paths.library_blocked_reason(self._Settings("")) == ""

    def test_a_mounted_library_does_not_block(self, tmp_path):
        lib = tmp_path / "mounted"
        lib.mkdir()
        paths.set_library_path(lib)
        assert paths.library_blocked_reason(self._Settings(str(lib))) == ""


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
