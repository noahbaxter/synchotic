"""Picking a folder that already has things in it.

Once a drive syncs into a folder here, anything inside it that Synchotic did
not download is deleted, so pointing it at a hand-made songs folder is the
pick that has to be hard.
"""
import io
from contextlib import redirect_stdout

import pytest

from src import copy
from src.config.settings import UserSettings
from src.ui.primitives import strip_ansi
from src.ui.screens.library import show_library_screen
from src.ui.widgets.sync_display import library_contents, library_summary


def _summary(**kw):
    args = dict(chart_folders=0, files=0, folders=0, more=False)
    args.update(kw)
    return library_summary("/songs", **args)


class TestWhatItSaysIsInThere:
    def test_a_known_library_names_its_drives_by_group(self):
        _, body, risky = _summary(has_markers=True,
                                  contents=(("Drums", "BirdmanExe Drive", 30),
                                            ("Drums", "Misc", 1),
                                            ("Games", "Rock Band", 2)))

        body = strip_ansi(body)
        assert copy.KNOWN_LIBRARY in body
        order = [body.index(s) for s in
                 ("DRUMS", "BirdmanExe Drive: 30 setlists", "Misc: 1 setlist\n",
                  "GAMES", "Rock Band: 2 setlists")]
        assert order == sorted(order)
        assert risky is False

    def test_a_heading_does_not_look_like_a_drive(self):
        heading, drive = library_contents((("Drums", "Misc", 4),)).split("\n")

        assert "\x1b[" in heading  # dimmed
        assert "\x1b[" not in drive

    def test_a_drive_with_no_group_still_lands_somewhere(self):
        assert strip_ansi(library_contents((("", "Some Drive", 3),))).startswith("OTHER\n")

    def test_a_count_that_stopped_early_says_at_least(self):
        _, body, risky = _summary(chart_folders=12, files=89, folders=20, more=True)

        assert "12+ chart folders, 89+ files, 20+ folders" in strip_ansi(body)
        assert risky is True

    def test_an_empty_folder_is_not_a_risk(self):
        _, body, risky = _summary()

        assert copy.FOLDER_IS_NEW in body
        assert risky is False


class TestThePrompt:
    @pytest.fixture
    def pick(self, monkeypatch, tmp_path):
        """Type `target` into the path row, answer every question `answer`.
        Returns (changed, what the questions showed, their options, settings)."""
        def run(target, answer):
            asked, offered, visits = [], [], []

            monkeypatch.setattr("src.core.folder_picker.picker_available",
                                lambda: False)

            def type_the_path(self, initial_index=0):
                from chotic_ui.widgets.menu import MenuResult

                # A "no" returns to the picker; backing out of that second
                # visit ends the screen.
                visits.append(1)
                if len(visits) > 1:
                    return None
                row = self.items[-1]
                row.text = str(target)
                return MenuResult(row, "enter")

            monkeypatch.setattr("chotic_ui.widgets.menu.Menu.run", type_the_path)

            def fake_ask(title, body, options, **kw):
                asked.append(strip_ansi(f"{title}\n{body}"))
                offered.append([value for _, value in options])
                return answer

            monkeypatch.setattr("src.ui.screens.library.ask", fake_ask)
            monkeypatch.setattr("chotic_ui.widgets.confirm.ConfirmDialog.run",
                                lambda self: answer)

            settings = UserSettings(tmp_path / "settings.json")
            with redirect_stdout(io.StringIO()):
                changed = show_library_screen(settings)
            return changed, "\n".join(asked), offered, settings

        return run

    def test_somebody_elses_charts_get_the_loud_one(self, pick, tmp_path):
        target = tmp_path / "Songs"
        (target / "My Own Chart").mkdir(parents=True)
        (target / "My Own Chart" / "notes.chart").write_text("x")

        changed, seen, offered, _ = pick(target, answer=True)

        assert copy.CONFIRM_RISKY_Q in seen
        assert "WILL BE DELETED" in seen
        assert "1 chart folder," in seen
        assert offered == [[False, True]], "the cursor must start on No"
        assert changed is True

    def test_a_previous_library_is_recognised(self, pick, tmp_path):
        target = tmp_path / "Old Library"
        (target / "Rock Band" / "RB3" / "Song").mkdir(parents=True)
        (target / "Rock Band" / "RB3" / "Song" / "song.ini").write_text("x")

        changed, seen, offered, _ = pick(target, answer=True)

        assert copy.KNOWN_LIBRARY in seen
        assert "Rock Band" in seen
        assert "DELETED" not in seen
        assert offered == [[True, False]]
        assert changed is True

    def test_an_old_install_beside_the_folder_does_not_make_it_ours(
            self, pick, tmp_path):
        """v1.4 left .dm-sync next to its own Sync Charts folder. A songs
        folder picked beside it is not the library those markers describe."""
        (tmp_path / ".dm-sync" / "markers").mkdir(parents=True)
        (tmp_path / ".dm-sync" / "markers" / "a.json").write_text("{}")
        target = tmp_path / "Custom"
        (target / "My Own Chart").mkdir(parents=True)
        (target / "My Own Chart" / "notes.chart").write_text("x")
        (target / "My Own Chart" / "song.ogg").write_text("x")

        _, seen, _, _ = pick(target, answer=True)

        assert copy.KNOWN_LIBRARY not in seen
        assert "all 2 unmanaged files in this folder" in seen

    def test_an_empty_folder_gets_the_quieter_message(self, pick, tmp_path):
        target = tmp_path / "Fresh"
        target.mkdir()

        _, seen, _, _ = pick(target, answer=True)

        assert copy.FOLDER_IS_NEW in seen
        assert "DELETED" not in seen

    def test_saying_no_leaves_the_library_alone(self, pick, tmp_path):
        target = tmp_path / "Songs"
        (target / "Keep Me").mkdir(parents=True)

        changed, _, _, settings = pick(target, answer=False)

        assert changed is False
        assert settings.library_path == ""
