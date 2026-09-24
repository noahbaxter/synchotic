"""`synchotic --first-run`: an empty throwaway install, so a machine that
already runs Synchotic can show what a new user sees."""
import os

import pytest

import sync as sync_entry
from src import copy
from src.core import paths
from src.core.legacy_migration import FRESH_ENV, default_library_to_adopt


@pytest.fixture
def sandbox(monkeypatch, tmp_path):
    """Run the real thing, with the environment put back afterwards. Starts
    from a shell that has a real library set, which the sandbox must drop."""
    for name in ("SYNCHOTIC_ROOT", "SYNCHOTIC_OS_DIRS", FRESH_ENV,
                 "SYNCHOTIC_LEGACY_ROOT"):
        monkeypatch.setenv(name, os.environ.get(name, ""))
    monkeypatch.setenv("SYNCHOTIC_LIBRARY", str(tmp_path))
    made = sync_entry.use_first_run_sandbox()
    yield made
    paths.set_library_path(None)


class TestTheSandbox:
    def test_it_holds_nothing_but_the_drive_manifest(self, sandbox):
        """SYNCHOTIC_ROOT moves the bundled drives.json too, and a sandbox
        with no drives is a fault in the test rig, not a new user's view."""
        assert [p.name for p in sandbox.iterdir()] == ["drives.json"]

    def test_the_drives_are_readable_from_it(self, sandbox):
        from src.config import DrivesConfig
        assert DrivesConfig.load(paths.get_drives_config_path()).drives

    def test_settings_and_logs_land_inside_it(self, sandbox):
        assert str(paths.get_data_dir()).startswith(str(sandbox))

    def test_no_library_is_set(self, sandbox):
        assert paths.library_blocked_reason() == copy.LIBRARY_UNSET

    def test_a_former_default_library_is_not_adopted(self, sandbox, tmp_path, monkeypatch):
        """Without this the charts already on disk get picked up and the
        new-user path never runs."""
        home = tmp_path / "home"
        (home / "Synchotic" / "Sync Charts" / "Some Pack").mkdir(parents=True)
        monkeypatch.setattr("pathlib.Path.home", lambda: home)
        assert default_library_to_adopt() is None

    def test_a_previous_install_is_not_imported(self, sandbox):
        """The sandbox is portable, and only OS-dirs installs adopt."""
        assert paths._using_os_dirs() is False


class TestCredentials:
    """Copied by default, so walking BYOC does not need a second Google Cloud
    project. The token stays behind, so the run still starts signed out."""

    @pytest.fixture
    def make(self, monkeypatch, tmp_path):
        real = tmp_path / "real"
        for name in ("SYNCHOTIC_ROOT", "SYNCHOTIC_OS_DIRS", FRESH_ENV,
                     "SYNCHOTIC_LIBRARY", "SYNCHOTIC_LEGACY_ROOT"):
            monkeypatch.setenv(name, os.environ.get(name, ""))
        monkeypatch.setenv("SYNCHOTIC_ROOT", str(real))
        monkeypatch.setenv("SYNCHOTIC_OS_DIRS", "0")
        data = paths.get_data_dir()
        data.mkdir(parents=True, exist_ok=True)
        (data / "credentials.json").write_text('{"installed": {}}')
        (data / "token.json").write_text("{}")

        def run(keep_creds):
            sync_entry.use_first_run_sandbox(keep_creds=keep_creds)
            return paths.get_data_dir()
        yield run
        paths.set_library_path(None)

    def test_they_are_copied_and_the_token_is_not(self, make):
        data = make(keep_creds=True)
        assert (data / "credentials.json").exists()
        assert not (data / "token.json").exists()

    def test_no_creds_leaves_them_out(self, make):
        assert not (make(keep_creds=False) / "credentials.json").exists()
