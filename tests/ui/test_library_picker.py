"""Choosing where charts live.

Changing this setting migrates nothing: the library is self-contained, so
pointing at a different folder just looks somewhere else. A folder Synchotic
has never synced reads as empty and the next sync re-downloads into it, which
has to be said before the user watches it happen.
"""
import pytest

from src.config.settings import UserSettings
from src.core import paths
from src.ui.screens.library import show_library_screen


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNCHOTIC_ROOT", str(tmp_path))
    monkeypatch.delenv("SYNCHOTIC_LIBRARY", raising=False)
    paths.set_library_path(None)
    yield
    paths.set_library_path(None)


@pytest.fixture
def drive(monkeypatch):
    """Drive the screen: typed path, and answers for any confirm dialogs."""
    def run(typed, confirms=(True,), settings=None):
        answers = list(confirms)
        monkeypatch.setattr("src.ui.screens.library.clear_screen", lambda: None)
        monkeypatch.setattr("src.ui.screens.library.print_header", lambda *a, **k: None)
        monkeypatch.setattr("src.ui.primitives.input_with_esc", lambda p="": typed,
                            raising=False)
        monkeypatch.setattr("chotic_ui.primitives.keyboard_input.input_with_esc",
                            lambda p="": typed, raising=False)
        monkeypatch.setattr("chotic_ui.widgets.confirm.ConfirmDialog.run",
                            lambda self: answers.pop(0) if answers else True)
        monkeypatch.setattr("src.ui.widgets.confirm.ConfirmDialog.run",
                            lambda self: answers.pop(0) if answers else True,
                            raising=False)
        return show_library_screen(settings), settings
    return run


def _settings(tmp_path):
    return UserSettings(tmp_path / "settings.json")


class TestChoosingAFolder:
    def test_an_existing_folder_is_accepted_and_saved(self, tmp_path, drive):
        target = tmp_path / "elsewhere"; target.mkdir()
        s = _settings(tmp_path)
        changed, s = drive(str(target), settings=s)
        assert changed is True
        assert s.library_path == str(target)
        assert paths.get_library_path() == target

    def test_it_persists_for_the_next_launch(self, tmp_path, drive):
        target = tmp_path / "elsewhere"; target.mkdir()
        drive(str(target), settings=_settings(tmp_path))
        assert UserSettings.load(tmp_path / "settings.json").library_path == str(target)

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


class TestItAppliesImmediately:
    def test_markers_resolve_to_the_new_library_in_the_same_session(self, tmp_path, drive):
        """Path helpers read module state, so a stale value would keep writing
        into the old library until restart."""
        target = tmp_path / "elsewhere"; target.mkdir()
        drive(str(target), settings=_settings(tmp_path))
        from src.sync import markers
        assert markers.get_markers_dir().is_relative_to(target)


class TestBackingOut:
    def test_empty_input_changes_nothing(self, tmp_path, drive):
        s = _settings(tmp_path)
        changed, s = drive("   ", settings=s)
        assert changed is False and s.library_path == ""

    def test_declining_the_new_library_warning_changes_nothing(self, tmp_path, drive):
        target = tmp_path / "theirs"; target.mkdir()
        s = _settings(tmp_path)
        changed, s = drive(str(target), confirms=(False,), settings=s)
        assert changed is False and s.library_path == ""

    def test_a_file_is_refused(self, tmp_path, drive):
        f = tmp_path / "notafolder.txt"; f.write_text("x")
        s = _settings(tmp_path)
        changed, s = drive(str(f), settings=s)
        assert changed is False and s.library_path == ""

    def test_declining_to_create_changes_nothing(self, tmp_path, drive):
        s = _settings(tmp_path)
        changed, s = drive(str(tmp_path / "nope"), confirms=(False,), settings=s)
        assert changed is False
        assert not (tmp_path / "nope").exists()


class TestCreatingIt:
    def test_a_missing_folder_can_be_created(self, tmp_path, drive):
        target = tmp_path / "new" / "charts"
        s = _settings(tmp_path)
        changed, s = drive(str(target), confirms=(True, True), settings=s)
        assert changed is True and target.is_dir()


class TestAlreadySyncedFolder:
    def test_a_library_with_markers_asks_nothing(self, tmp_path, drive):
        """No warning is due: this folder is already ours."""
        target = tmp_path / "existing"
        (target / paths.LIBRARY_STATE_DIR_NAME / "markers").mkdir(parents=True)
        s = _settings(tmp_path)
        changed, s = drive(str(target), confirms=(), settings=s)
        assert changed is True and s.library_path == str(target)
