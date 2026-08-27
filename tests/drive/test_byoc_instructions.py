"""Getting a user from "pick BYOC" to a working credentials.json.

The data directory resolves three different ways (launcher, frozen exe, dev
checkout), so telling someone to "find .dm-sync" is not an answer. Write the
steps into that folder and open it.
"""
import json

import pytest

from src.core import paths
from src.core.files import open_folder
from src.drive.auth import (BYOC_INSTRUCTIONS_FILE, has_custom_client_config,
                            write_byoc_instructions)


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "get_app_dir", lambda: tmp_path)
    monkeypatch.delenv("SYNCHOTIC_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("SYNCHOTIC_OAUTH_CLIENT_SECRET", raising=False)


class TestInstructionsFile:
    def test_lands_next_to_where_credentials_go(self, tmp_path):
        path = write_byoc_instructions()
        assert path.name == BYOC_INSTRUCTIONS_FILE
        assert path.parent == paths.get_data_dir()

    def test_carries_no_absolute_paths(self):
        """The file sits in the folder it describes, so "this folder" says it.

        A spelled-out path also wraps badly and leaks the user's name when they
        paste the file somewhere to ask for help.
        """
        text = write_byoc_instructions().read_text()
        assert str(paths.get_data_dir()) not in text
        assert "/Users/" not in text and "C:\\" not in text

    def test_points_at_the_folder_it_lives_in(self):
        text = write_byoc_instructions().read_text()
        install = text[text.index("INSTALL IT"):text.index("ENABLE IT")]
        assert "this folder" in install
        assert "next to these instructions" in install

    def test_warns_about_the_testing_status_trap(self):
        """Publishing status Testing expires the token weekly, the usual mistake."""
        text = write_byoc_instructions().read_text().lower()
        assert "in production" in text
        assert "7 days" in text

    def test_stays_readable_for_non_developers(self):
        """These go to Clone Hero players, not developers.

        Environment variables are the standout offender: there is no way to
        explain setting one that a normal person can follow, and the file
        route already works.
        """
        text = write_byoc_instructions().read_text()
        for jargon in ("SYNCHOTIC_OAUTH_CLIENT_ID", "environment variable",
                       "env var", "terminal", "command line", "OAuth client ID JSON"):
            assert jargon.lower() not in text.lower(), f"jargon leaked in: {jargon}"

    def test_names_the_exact_filename_to_use(self):
        """Renaming the download is the step people skip."""
        assert "credentials.json" in write_byoc_instructions().read_text()

    def test_rewrites_cleanly_when_run_twice(self):
        first = write_byoc_instructions().read_text()
        assert write_byoc_instructions().read_text() == first

    def test_creates_the_folder_if_absent(self, tmp_path):
        assert not (tmp_path / ".dm-sync").exists()
        write_byoc_instructions()
        assert (tmp_path / ".dm-sync").is_dir()

    def test_instructions_alone_do_not_count_as_configured(self):
        """Writing help must not make has_custom_client_config lie."""
        write_byoc_instructions()
        assert has_custom_client_config() is False

    def test_real_credentials_still_register(self):
        write_byoc_instructions()
        (paths.get_data_dir() / "credentials.json").write_text(
            json.dumps({"installed": {"client_id": "i", "client_secret": "s"}}))
        assert has_custom_client_config() is True


class TestOpenFolder:
    def test_refuses_a_path_that_is_not_a_directory(self, tmp_path):
        f = tmp_path / "a.txt"
        f.write_text("x")
        assert open_folder(f) is False
        assert open_folder(tmp_path / "missing") is False

    def test_headless_linux_does_not_try(self, monkeypatch, tmp_path):
        """No display means nothing to open, and Popen would just fail."""
        monkeypatch.setattr("sys.platform", "linux")
        monkeypatch.delenv("DISPLAY", raising=False)
        monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
        called = []
        monkeypatch.setattr("subprocess.Popen", lambda *a, **k: called.append(a))
        assert open_folder(tmp_path) is False
        assert called == []

    def test_a_broken_file_manager_is_not_fatal(self, monkeypatch, tmp_path):
        def boom(*a, **k):
            raise FileNotFoundError("no xdg-open")
        monkeypatch.setattr("subprocess.Popen", boom)
        monkeypatch.setenv("DISPLAY", ":0")
        assert open_folder(tmp_path) is False
