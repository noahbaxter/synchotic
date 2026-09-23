"""Only the `synchotic` console script switches to the OS dirs. `python sync.py`
and the frozen builds run sync.py as __main__, and a loose Windows executable
must keep the portable .dm-sync beside it."""
import pytest

import sync as sync_entry


@pytest.fixture
def no_main(monkeypatch):
    # setenv first so the original value (or its absence) is what gets
    # restored: cli() writes os.environ directly, behind monkeypatch's back.
    monkeypatch.setenv("SYNCHOTIC_OS_DIRS", "")
    monkeypatch.delenv("SYNCHOTIC_OS_DIRS")
    monkeypatch.setattr(sync_entry, "main", lambda: None)


def test_running_the_file_keeps_the_layout_it_was_given(no_main):
    import os
    sync_entry.run()
    assert "SYNCHOTIC_OS_DIRS" not in os.environ


def test_the_console_script_uses_the_os_dirs(no_main):
    import os
    sync_entry.cli()
    assert os.environ["SYNCHOTIC_OS_DIRS"] == "1"


def test_the_console_script_can_be_told_not_to(no_main, monkeypatch):
    import os
    monkeypatch.setenv("SYNCHOTIC_OS_DIRS", "0")
    sync_entry.cli()
    assert os.environ["SYNCHOTIC_OS_DIRS"] == "0"
