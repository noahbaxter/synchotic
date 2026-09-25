"""Choosing where charts live. The library is self-contained, so pointing at a
different folder just looks somewhere else."""
from pathlib import Path

import pytest

from src.config.settings import UserSettings
from src.core import paths
from src.ui.screens.library import show_library_screen


def _library():
    """The library as a plain path, without Windows' extended-length prefix."""
    return Path(paths.plain_path(paths.get_library_path()))


@pytest.fixture(autouse=True)
def never_open_a_real_dialog(monkeypatch):
    """A missed patch here once opened a real Finder dialog. Fail instead."""
    def forbidden(*a, **k):
        raise AssertionError("the real folder picker was called from a test")
    monkeypatch.setattr("src.core.folder_picker._run", forbidden)


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNCHOTIC_ROOT", str(tmp_path))
    monkeypatch.delenv("SYNCHOTIC_LIBRARY", raising=False)
    paths.set_library_path(None)
    yield
    paths.set_library_path(None)


def _answers(monkeypatch, confirms):
    """Every confirm dialog and boxed question takes the next answer."""
    answers = list(confirms)

    def answer(*a, **k):
        return answers.pop(0) if answers else True

    monkeypatch.setattr("chotic_ui.widgets.confirm.ConfirmDialog.run", answer)
    monkeypatch.setattr("src.ui.screens.library.ask", answer)


@pytest.fixture
def drive(monkeypatch):
    """Type a path into the path row once; a second visit backs out."""
    def run(typed, confirms=(True,), settings=None):
        monkeypatch.setattr("src.core.folder_picker.picker_available", lambda: False)
        visits = []

        def type_into_the_path_row(self, initial_index=0):
            from chotic_ui.widgets.menu import MenuResult

            visits.append(1)
            if len(visits) > 1:
                return None
            row = self.items[-1]
            row.text = typed
            return MenuResult(row, "enter")

        monkeypatch.setattr("chotic_ui.widgets.menu.Menu.run", type_into_the_path_row)
        _answers(monkeypatch, confirms)
        return show_library_screen(settings), settings
    return run


def _settings(tmp_path):
    return UserSettings(tmp_path / "settings.json")


class TestChoosingAFolder:
    def test_an_existing_folder_is_saved_and_applied(self, tmp_path, drive):
        target = tmp_path / "elsewhere"; target.mkdir()
        changed, s = drive(str(target), settings=_settings(tmp_path))

        assert changed is True
        assert UserSettings.load(tmp_path / "settings.json").library_path == str(target)
        assert _library() == target
        # Path helpers read module state, so a stale value would keep writing
        # into the old library until restart.
        from src.sync import markers
        assert Path(paths.plain_path(markers.get_markers_dir())).is_relative_to(target)

    def test_tilde_is_expanded(self, tmp_path, drive, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        (tmp_path / "charts").mkdir()
        changed, s = drive("~/charts", settings=_settings(tmp_path))
        assert changed is True
        assert "~" not in s.library_path

    def test_quotes_from_a_dragged_path_are_stripped(self, tmp_path, drive):
        target = tmp_path / "with space"; target.mkdir()
        changed, s = drive(f'"{target}"', settings=_settings(tmp_path))
        assert changed is True
        assert s.library_path == str(target)

    def test_a_missing_folder_can_be_created(self, tmp_path, drive):
        target = tmp_path / "new" / "charts"
        changed, s = drive(str(target), confirms=(True, True), settings=_settings(tmp_path))
        assert changed is True and target.is_dir()


class TestBackingOut:
    def test_empty_input_changes_nothing(self, tmp_path, drive):
        changed, s = drive("   ", settings=_settings(tmp_path))
        assert changed is False and s.library_path == ""

    def test_declining_the_folder_changes_nothing(self, tmp_path, drive):
        target = tmp_path / "theirs"; target.mkdir()
        changed, s = drive(str(target), confirms=(False,), settings=_settings(tmp_path))
        assert changed is False and s.library_path == ""

    def test_a_file_is_refused(self, tmp_path, drive):
        f = tmp_path / "notafolder.txt"; f.write_text("x")
        changed, s = drive(str(f), settings=_settings(tmp_path))
        assert changed is False and s.library_path == ""

    def test_declining_to_create_changes_nothing(self, tmp_path, drive):
        changed, s = drive(str(tmp_path / "nope"), confirms=(False,),
                           settings=_settings(tmp_path))
        assert changed is False
        assert not (tmp_path / "nope").exists()


class TestBrowsing:
    """The native dialog is a way into the same screen, not a bypass of it."""

    @pytest.fixture
    def browse(self, monkeypatch):
        def run(returns, confirms=(True,), settings=None):
            picked = iter(returns)
            opened = []

            def fake_picker(*a, **k):
                opened.append(True)
                return next(picked, "")

            def fake_menu_run(self, initial_index=0):
                # Row one opens the dialog; once the results run out, back out.
                from chotic_ui.widgets.menu import MenuResult

                if len(opened) >= len(returns):
                    return None
                return MenuResult(self.items[0], "enter")

            monkeypatch.setattr("chotic_ui.widgets.menu.Menu.run", fake_menu_run)
            monkeypatch.setattr("src.core.folder_picker.picker_available", lambda: True)
            monkeypatch.setattr("src.core.folder_picker.pick_folder", fake_picker)
            _answers(monkeypatch, confirms)
            return show_library_screen(settings)
        return run

    def test_a_chosen_folder_is_saved(self, tmp_path, browse):
        target = tmp_path / "picked"; target.mkdir()
        s = _settings(tmp_path)
        assert browse([target], settings=s) is True
        assert s.library_path == str(target)

    def test_cancelling_reopens_the_screen_instead_of_leaving(self, tmp_path, browse):
        """Choosing on the second go is what proves it looped back."""
        target = tmp_path / "picked"; target.mkdir()
        s = _settings(tmp_path)
        assert browse([None, target], settings=s) is True
        assert s.library_path == str(target)

    def test_a_browsed_folder_is_still_confirmed(self, tmp_path, browse):
        target = tmp_path / "empty"; target.mkdir()
        s = _settings(tmp_path)
        assert browse([target], confirms=(False,), settings=s) is False
        assert not s.library_path


class TestInsideSetup:
    def test_setup_heads_the_box_and_puts_the_question_last(self):
        from src import copy
        from src.ui.widgets.sync_display import setup_frame

        title, body = setup_frame("Where?", "Why it matters.", (1, 3), "Chart Library")

        assert title == copy.SETUP_TITLE
        assert body == "Chart Library - 1/3\n\nWhy it matters.\n\nWhere?"

    def test_outside_setup_the_question_is_the_title(self):
        from src.ui.widgets.sync_display import setup_frame

        assert setup_frame("Where?", "Why.") == ("Where?", "Why.")


class TestStatsDoNotOutliveTheOldLibrary:
    """Nothing recomputes a setlist that is already cached, so stats measured
    in the old library would go on describing it."""

    @pytest.fixture(autouse=True)
    def fresh_cache(self, monkeypatch):
        from src.sync import cache as cache_mod
        monkeypatch.setattr(cache_mod, "_persistent_stats_cache", None)
        return cache_mod

    def test_disk_stats_are_dropped(self, tmp_path, drive, fresh_cache):
        old = tmp_path / "old"; old.mkdir()
        new = tmp_path / "new"; new.mkdir()
        paths.set_library_path(old)
        fresh_cache.get_persistent_stats_cache().set_setlist(
            "drive1", "Setlist", fresh_cache.CachedSetlistStats(
                total_charts=10, total_size=100, synced_charts=10, synced_size=100,
                disk_files=40, disk_size=100, disk_charts=10))

        changed, _ = drive(str(new), settings=_settings(tmp_path))

        assert changed is True
        assert fresh_cache.get_persistent_stats_cache().get_setlist("drive1", "Setlist") is None

    def test_the_drive_scan_cache_is_kept(self, tmp_path, drive, fresh_cache):
        """It describes Drive, not disk; dropping it costs a full re-scan."""
        target = tmp_path / "elsewhere"; target.mkdir()
        scan = fresh_cache.get_scan_cache()
        scan.set("setlist1", [{"path": "a.7z", "id": "x", "size": 1}])

        drive(str(target), settings=_settings(tmp_path))

        assert scan.get("setlist1") is not None


def test_a_picked_library_moves_on_without_a_pause(monkeypatch):
    """The next screen follows at once. A pause here showed a frozen frame and
    echoed keys pressed during it."""
    from sync import SyncApp

    app = object.__new__(SyncApp)
    app.user_settings = object()
    app.folder_stats_cache = type("Stats", (), {"invalidate_all": lambda s: None})()
    monkeypatch.setattr("src.ui.screens.show_library_screen", lambda *a, **k: True)
    monkeypatch.setattr(SyncApp, "_turn_on_library_drives", lambda self: {})

    def paused(*a, **k):
        raise AssertionError("paused after picking a library")
    monkeypatch.setattr("src.app.auth.wait_with_skip", paused)

    assert app.handle_library() is True
