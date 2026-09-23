"""Telling a previous Synchotic library from someone's own songs folder."""
from types import SimpleNamespace

from src.sync.library_probe import DEPTH, previous_selection, probe_library

DRIVES = ["Rock Band", "Misc", "Guitar Hero: Smash Hits"]


def _chart(folder, marker="song.ini"):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / marker).write_text("x")


class TestAPreviousSynchoticLibrary:
    def test_drive_names_at_the_top_are_the_giveaway(self, tmp_path):
        _chart(tmp_path / "Rock Band" / "RB3" / "Song A")
        (tmp_path / "Misc").mkdir()
        # Only the top level says whose library this is.
        (tmp_path / "screenshots" / "Guitar Hero - Smash Hits").mkdir(parents=True)

        assert probe_library(tmp_path, DRIVES).drive_matches == ("Misc", "Rock Band")

    def test_a_sanitized_folder_name_still_matches(self, tmp_path):
        """The folder on disk is the sanitized name, so that is what to compare."""
        (tmp_path / "Guitar Hero - Smash Hits").mkdir()

        assert probe_library(tmp_path, DRIVES).drive_matches == (
            "Guitar Hero - Smash Hits",)


class TestSomeoneElsesCharts:
    def test_chart_folders_with_no_drive_names(self, tmp_path):
        _chart(tmp_path / "a", marker="song.ini")
        _chart(tmp_path / "b", marker="notes.chart")
        _chart(tmp_path / "c", marker="notes.mid")

        look = probe_library(tmp_path, DRIVES)

        assert (look.chart_folders, look.drive_matches) == (3, ())

    def test_one_walk_answers_every_question(self, tmp_path):
        _chart(tmp_path / "Rock Band" / "RB3" / "Song")
        (tmp_path / "loose.txt").write_text("x")

        look = probe_library(tmp_path, DRIVES)

        assert look.drive_matches == ("Rock Band",)
        assert look.chart_folders == 1
        assert (look.files, look.folders) == (2, 3)

    def test_a_path_that_is_not_a_folder_looks_like_nothing(self, tmp_path):
        assert probe_library(tmp_path / "nope", DRIVES) == probe_library(tmp_path, DRIVES)


class TestItStaysCheap:
    def test_it_does_not_walk_past_three_levels(self, tmp_path):
        deep = tmp_path.joinpath(*[f"L{i}" for i in range(DEPTH + 3)])
        _chart(deep)

        assert probe_library(tmp_path, DRIVES).chart_folders == 0

    def test_it_stops_after_enough_entries(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.sync.library_probe.MAX_ENTRIES", 5)
        for i in range(20):
            (tmp_path / f"f{i}").mkdir()

        assert probe_library(tmp_path, DRIVES).capped is True

    def test_it_gives_up_when_the_disk_is_too_slow(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.sync.library_probe.TIME_BUDGET", -1)
        (tmp_path / "Rock Band").mkdir()

        assert probe_library(tmp_path, DRIVES).capped is True

    def test_finder_litter_and_skipped_folders_are_not_counted(self, tmp_path):
        (tmp_path / "Pack").mkdir()
        (tmp_path / "._Pack").write_text("")
        (tmp_path / "song.ogg").write_text("x")
        (tmp_path / "._song.ogg").write_text("")
        (tmp_path / ".synchotic" / "markers").mkdir(parents=True)

        look = probe_library(tmp_path, DRIVES, skip=(".synchotic",))

        assert (look.files, look.folders) == (1, 1)


class TestPreviousSelection:
    def test_it_reads_back_which_setlists_were_on(self, tmp_path):
        drives = [SimpleNamespace(name="Rock Band", folder_id="rb"),
                  SimpleNamespace(name="Misc", folder_id="misc")]
        (tmp_path / "Rock Band" / "RB3").mkdir(parents=True)
        (tmp_path / "Rock Band" / "RB1").mkdir()
        (tmp_path / "Rock Band" / "._RB1").write_text("")
        (tmp_path / "My Stuff" / "Songs").mkdir(parents=True)

        assert previous_selection(tmp_path, drives) == {"rb": ["RB1", "RB3"]}
