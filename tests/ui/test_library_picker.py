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
def never_open_a_real_dialog(monkeypatch):
    """A missed patch here used to reach osascript and open a Finder dialog on
    the machine running the suite. Fail loudly instead."""
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


@pytest.fixture
def drive(monkeypatch):
    """Drive the screen: typed path, and answers for any confirm dialogs."""
    def run(typed, confirms=(True,), settings=None):
        answers = list(confirms)
        monkeypatch.setattr("src.ui.screens.library.clear_screen", lambda: None)
        monkeypatch.setattr("src.ui.screens.library.print_header", lambda *a, **k: None)
        monkeypatch.setattr("src.core.folder_picker.picker_available", lambda: False)
        monkeypatch.setattr("src.ui.primitives.input_with_browse",
                            lambda p="", browse_key="b": typed)
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


class TestBrowsing:
    """The native dialog is a way into the same prompt, not a bypass of it.
    Everything after a path is chosen has to behave identically to typing it."""

    @pytest.fixture
    def browse(self, monkeypatch):
        def run(returns, confirms=(True,), settings=None):
            from src.ui.primitives.path_input import Browse
            answers = list(confirms)
            picked = iter(returns)
            # Browse fires once per prompt, then the line reads as empty, so a
            # loop that fails to consume a result ends the screen instead of
            # spinning. A test must never be able to reopen a dialog forever.
            pressed = []

            def fake_input(p="", browse_key="b"):
                if len(pressed) < len(returns):
                    pressed.append(True)
                    raise Browse()
                return ""

            monkeypatch.setattr("src.ui.screens.library.clear_screen", lambda: None)
            monkeypatch.setattr("src.ui.screens.library.print_header",
                                lambda *a, **k: None)
            # These are imported inside show_library_screen, so the source
            # module is the only patch point that takes.
            monkeypatch.setattr("src.core.folder_picker.picker_available",
                                lambda: True)
            monkeypatch.setattr("src.core.folder_picker.pick_folder",
                                lambda *a, **k: next(picked))
            monkeypatch.setattr("src.ui.primitives.input_with_browse", fake_input)
            monkeypatch.setattr("chotic_ui.widgets.confirm.ConfirmDialog.run",
                                lambda self: answers.pop(0) if answers else True)
            return show_library_screen(settings)
        return run

    def test_a_chosen_folder_is_saved(self, tmp_path, browse):
        target = tmp_path / "picked"; target.mkdir()
        (target / ".synchotic" / "markers").mkdir(parents=True)
        s = _settings(tmp_path)
        assert browse([target], settings=s) is True
        assert s.library_path == str(target)
        assert paths.get_library_path() == target

    def test_cancelling_reopens_the_prompt_instead_of_leaving(self, tmp_path, browse):
        """Cancel must not read as a chosen path and must not drop out of the
        screen. Choosing on the second go is what proves it looped back."""
        target = tmp_path / "picked"; target.mkdir()
        (target / ".synchotic" / "markers").mkdir(parents=True)
        s = _settings(tmp_path)
        assert browse([None, target], settings=s) is True
        assert s.library_path == str(target)

    def test_a_browsed_folder_with_no_markers_still_warns(self, tmp_path, browse):
        """The dialog cannot vouch for a folder. An empty one re-downloads
        everything, so it hits the same confirm a typed path does."""
        target = tmp_path / "empty"; target.mkdir()
        s = _settings(tmp_path)
        assert browse([target], confirms=(False,), settings=s) is False
        assert not s.library_path


class TestBrowseHotkey:
    """Whether the key is bound depends on there being a dialog to open."""

    def _type(self, monkeypatch, keys, browse_key):
        from src.ui.primitives import path_input
        it = iter(keys)
        monkeypatch.setattr(path_input, "getch", lambda: next(it))
        return path_input.input_with_browse("", browse_key=browse_key)

    def test_unbound_without_a_picker(self, monkeypatch):
        """With no dialog available 'b' stays a plain character, or a relative
        path starting with it would be untypeable."""
        assert self._type(monkeypatch, ["b", "i", "n", "\r"], "") == "bin"

    def test_fires_only_while_the_line_is_empty(self, monkeypatch):
        assert self._type(monkeypatch, ["/", "b", "\r"], "b") == "/b"

    def test_fires_on_an_empty_line(self, monkeypatch):
        from src.ui.primitives.path_input import Browse
        with pytest.raises(Browse):
            self._type(monkeypatch, ["b"], "b")


class TestImportingAPreviousInstall:
    """Pointing the library at a pre-1.5 folder brings that install's settings
    across. The app holds one settings object for its whole run and save()
    writes it whole, so an import the object never sees is thrown away by the
    next keypress: drives, download mode and sign-in prompt all back to nothing.
    """

    @pytest.fixture(autouse=True)
    def os_dirs(self, tmp_path, monkeypatch):
        """Only a bundle imports: portable installs already read the folder."""
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setattr(paths.Path, "home", staticmethod(lambda: home))
        monkeypatch.setenv(paths.OS_DIRS_ENV, "1")
        monkeypatch.delenv("SYNCHOTIC_ROOT", raising=False)
        return home

    @pytest.fixture
    def previous(self, tmp_path):
        import json
        library = tmp_path / "OldInstall" / "Sync Charts"
        library.mkdir(parents=True)
        state = tmp_path / "OldInstall" / paths.DATA_DIR_NAME
        state.mkdir()
        (state / "settings.json").write_text(json.dumps({
            "drive_toggles": {"driveA": True, "driveB": False},
            "download_mode": "byoc",
        }))
        (state / "markers").mkdir()
        return library

    def _import(self, drive, library):
        live = UserSettings.load(paths.get_settings_path())
        changed, live = drive(str(library), settings=live)
        assert changed is True
        return live

    def test_the_running_app_sees_it(self, drive, previous):
        live = self._import(drive, previous)
        assert live.drive_toggles == {"driveA": True, "driveB": False}
        assert live.download_mode == "byoc"

    def test_it_survives_the_next_save(self, drive, previous):
        live = self._import(drive, previous)
        live.set_drive_enabled("driveC", True)
        live.save()
        saved = UserSettings.load(paths.get_settings_path())
        assert saved.drive_toggles == {"driveA": True, "driveB": False, "driveC": True}
        assert saved.download_mode == "byoc"

    def test_the_picked_folder_still_wins(self, drive, previous):
        """The import must not drag the old library_path back over the pick."""
        live = self._import(drive, previous)
        assert live.library_path == str(previous)
        assert paths.get_library_path() == previous
