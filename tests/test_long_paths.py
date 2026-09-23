"""The library root carries the Windows extended-length prefix, lifting the
260-character path and 248-character directory limits for everything derived
from it. These are the string half, so they run anywhere; the rest is the
checklist in docs/windows-long-paths.md."""
from pathlib import PureWindowsPath

import pytest

from src.core.paths import _extend, is_library_state_path, plain_path


class TestExtending:
    def test_a_drive_path_gets_the_prefix(self):
        assert _extend(r"C:\CH Songs\Sync Charts") == r"\\?\C:\CH Songs\Sync Charts"

    def test_a_unc_share_gets_the_unc_form(self):
        r"""\\?\\NAS\charts is not a path Windows will open."""
        assert _extend(r"\\NAS\charts\Sync") == r"\\?\UNC\NAS\charts\Sync"

    def test_it_is_idempotent(self):
        once = _extend(r"C:\Sync")
        assert _extend(once) == once

    def test_a_relative_path_is_left_alone(self):
        """The prefix only works on a full path."""
        assert _extend(r"Sync Charts\Misc") == r"Sync Charts\Misc"

    def test_a_posix_path_is_left_alone(self):
        assert _extend("/Users/noah/Sync Charts") == "/Users/noah/Sync Charts"


class TestPlainPath:
    @pytest.mark.parametrize("written", [r"C:\CH Songs\Sync", r"\\NAS\charts\Sync"])
    def test_it_round_trips(self, written):
        assert plain_path(_extend(written)) == written

    def test_an_unprefixed_path_is_unchanged(self):
        assert plain_path(r"C:\Sync") == r"C:\Sync"


def test_a_marker_key_is_the_same_either_way():
    """Markers store library-relative paths, so the prefix never reaches them."""
    rel = r"Misc\Set\Chart\song.ini"
    plain = PureWindowsPath(r"C:\CH Songs\Sync Charts")
    extended = PureWindowsPath(_extend(str(plain)))
    assert (extended / rel).relative_to(extended).as_posix() == \
           (plain / rel).relative_to(plain).as_posix() == "Misc/Set/Chart/song.ini"


class TestTheGuardKnowsBothLimits:
    @pytest.fixture
    def on_windows(self, monkeypatch):
        from src.sync import download_planner as dp
        monkeypatch.setattr(dp.os, "name", "nt")
        monkeypatch.setattr(dp, "is_long_paths_enabled", lambda: False)
        return dp

    def test_a_file_under_the_limit_in_a_folder_over_it_is_refused(self, on_windows):
        """259 characters, under MAX_PATH, but the parent is 250 and a
        directory stops at 248."""
        parent = (r"C:\CH Songs\songs\Sync Charts\Misc\Drumb n' Geet Charts"
                  r"\SirMonkfish's FB Charts\The Word Alive - Empire EP"
                  r"\The Word Alive - The Only Rule Is That There Are No Rules [SirMonkfish]"
                  r"\The Word Alive - The Only Rule Is That There Are No Rules [SirMonkfish]")
        assert len(parent) == 250
        path = PureWindowsPath(parent + r"\song.ini")
        assert len(str(path)) == 259 < 260
        assert on_windows.exceeds_windows_path_limit(path)

    def test_a_short_path_is_fine(self, on_windows):
        assert not on_windows.exceeds_windows_path_limit(
            PureWindowsPath(r"C:\Sync Charts\Misc\Set\Chart\song.ini"))

    def test_the_prefix_lifts_it(self, on_windows):
        deep = PureWindowsPath(_extend(r"C:\Sync Charts" + r"\A Very Long Chart Folder Name" * 10))
        assert len(str(deep)) > 300
        assert not on_windows.exceeds_windows_path_limit(deep)


class TestLibraryStateIsFoundEitherWay:
    """is_library_state_path decides whether purge may walk a path. A prefix
    mismatch there would delete live staging."""

    @pytest.fixture
    def library(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SYNCHOTIC_LIBRARY", str(tmp_path / "lib"))
        return tmp_path / "lib"

    def test_state_is_recognised(self, library):
        assert is_library_state_path(library / ".synchotic" / "tmp" / "_download_a.7z")

    def test_a_chart_is_not_state(self, library):
        assert not is_library_state_path(library / "Misc" / "Set" / "song.ini")
