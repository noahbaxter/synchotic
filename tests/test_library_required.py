"""A library is required, so an upgrade has to keep the former default it was
already using. The unset gate itself is in test_library_path.TestScanGate."""
import pytest

from src.core import paths
from src.core.legacy_migration import default_library_to_adopt


@pytest.fixture(autouse=True)
def no_ambient_library(monkeypatch):
    monkeypatch.delenv("SYNCHOTIC_LIBRARY", raising=False)
    paths.set_library_path(None)
    yield
    paths.set_library_path(None)


class TestAnUpgradeKeepsTheLibraryItHad:
    @pytest.fixture
    def former_default(self, monkeypatch, tmp_path):
        home = tmp_path / "home"
        (home / "Synchotic" / "Sync Charts").mkdir(parents=True)
        monkeypatch.setattr("pathlib.Path.home", lambda: home)
        monkeypatch.setattr(paths, "get_app_dir", lambda: tmp_path / "app")
        return home / "Synchotic" / "Sync Charts"

    def test_a_default_holding_charts_is_adopted(self, former_default):
        (former_default / "Some Setlist").mkdir()
        assert default_library_to_adopt() == former_default

    def test_an_empty_default_is_not_adopted(self, former_default):
        assert default_library_to_adopt() is None

    def test_a_default_that_never_existed_is_not_adopted(self, monkeypatch, tmp_path):
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path / "nothing")
        monkeypatch.setattr(paths, "get_app_dir", lambda: tmp_path / "nowhere")
        assert default_library_to_adopt() is None

    def test_the_portable_layout_is_checked_too(self, monkeypatch, tmp_path):
        """A loose executable kept its charts beside itself."""
        app = tmp_path / "app"
        beside = app / "Sync Charts"
        beside.mkdir(parents=True)
        (beside / "Pack").mkdir()
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path / "home")
        monkeypatch.setattr(paths, "get_app_dir", lambda: app)
        assert default_library_to_adopt() == beside
