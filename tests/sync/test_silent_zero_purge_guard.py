"""A scan that reached nothing must never look like a drive with nothing on it.

The purge planner treats a folder as "not scanned" only while its files entry
is None; an empty list means "the remote really is empty" and everything on
disk is extra. So any path that turns a dead scan into [] hands the planner a
deletion order for the whole library.

Two such paths existed together: list_folder swallowed 403 into [], and the
scanner created drive["files"] = [] at discovery time, before a single file
had been fetched. Both are pinned here.
"""

import tempfile
from pathlib import Path

import pytest
import requests

from src.sync.purge_planner import plan_purge


class _Settings:
    purge_ignore = None
    delete_videos = True

    def is_drive_enabled(self, folder_id):
        return True

    def get_disabled_subfolders(self, folder_id):
        return set()

    def is_subfolder_enabled(self, *a):
        return True

    def sync_subfolder_names(self, *a):
        return False

    def save(self):
        pass


class _Auth:
    def get_token(self):
        return "oauth-token"


@pytest.fixture
def library():
    """A managed library with charts already on disk and no markers."""
    base = Path(tempfile.mkdtemp())
    setlist = base / "MyDrive" / "Setlist A"
    setlist.mkdir(parents=True)
    for name in ("chart1.sng", "chart2.sng", "notes.txt"):
        (setlist / name).write_bytes(b"x" * 1000)
    return base


@pytest.fixture
def dead_drive(monkeypatch):
    """Every Drive HTTP call answers 403, the shape of a credential-less scan."""
    import src.drive.client as client_module

    class Forbidden:
        status_code = 403
        text = "insufficientPermissions"
        headers = {"Content-Type": "application/json"}

        def raise_for_status(self):
            raise requests.exceptions.HTTPError(response=self)

        def json(self):
            return {}

    monkeypatch.setattr(client_module.requests, "request",
                        lambda method, url, **kw: Forbidden())
    monkeypatch.setattr(client_module.requests, "post",
                        lambda url, **kw: Forbidden())
    monkeypatch.setattr(client_module.time, "sleep", lambda *_: None)


def _scan(folder, download_path):
    """Run discovery and every setlist scan on the calling thread.

    Driving the worker directly rather than through start() keeps the test off
    a background thread, so a failure points at the scan instead of a timeout.
    """
    from src.drive.scanner import FolderScanner
    from src.sync.background_scanner import BackgroundScanner

    scanner = BackgroundScanner([folder], _Auth(), api_key="",
                                user_settings=_Settings(),
                                download_path=download_path, force_rescan=True)
    scanner.discover()
    folder_scanner = FolderScanner(scanner._client)
    while True:
        setlist = scanner._get_next_setlist_to_scan()
        if setlist is None:
            return scanner
        scanner._scan_setlist(setlist, folder_scanner)


def test_a_drive_whose_every_scan_died_is_never_reported_as_empty(library, dead_drive):
    folder = {"folder_id": "driveroot", "name": "MyDrive", "files": None}

    _scan(folder, library)

    assert folder["files"] is None, (
        "an empty list here reads as 'the remote is empty' and purge deletes to match"
    )


def test_a_dead_scan_raises_the_failure_flag(library, dead_drive):
    folder = {"folder_id": "driveroot", "name": "MyDrive", "files": None}

    scanner = _scan(folder, library)

    assert scanner.has_scan_failures()
    assert "403" in scanner.get_failure_reason()


def test_a_dead_scan_purges_nothing(library, dead_drive):
    """The end of the chain, and the only assertion that matters to a user."""
    folder = {"folder_id": "driveroot", "name": "MyDrive", "files": None}

    scanner = _scan(folder, library)
    failed = None
    if scanner.has_scan_failures():
        failed = {"driveroot": scanner.get_failed_setlist_names("driveroot")}

    files, stats = plan_purge([folder], library, _Settings(), failed,
                              precomputed_markers=set())

    assert files == []
    assert stats.total_files == 0


def test_a_setlist_that_failed_to_scan_is_not_offered_for_download(library, dead_drive):
    """Nothing listed it, so there is nothing to download from it.

    The scan loop reads drive["files"] for whatever this returns. That entry is
    None until a scan succeeds, so handing back a failed setlist walks the
    downloader into iterating None.
    """
    folder = {"folder_id": "driveroot", "name": "MyDrive", "files": None}

    scanner = _scan(folder, library)

    assert scanner.get_failed_setlist_names("driveroot")
    assert scanner.get_scanned_enabled_setlists() == []


def test_a_setlist_that_failed_its_retry_is_still_not_offered_for_download(library, dead_drive):
    """The retry pass marks a re-failed setlist scanned so is_done() can finish.

    That flag says "stop waiting for it", not "its files are ready", and it must
    not put the setlist back in front of the downloader.
    """
    from src.drive.scanner import FolderScanner
    from src.sync.background_scanner import BackgroundScanner

    folder = {"folder_id": "driveroot", "name": "MyDrive", "files": None}
    scanner = BackgroundScanner([folder], _Auth(), api_key="",
                                user_settings=_Settings(),
                                download_path=library, force_rescan=True)
    scanner.discover()
    scanner._scan_worker()  # runs the scan pass and the retry pass

    assert scanner.is_done(), "the retry pass must not leave the scan hanging"
    assert scanner.get_scanned_enabled_setlists() == []
    assert folder["files"] is None


def test_discovery_alone_does_not_create_an_empty_file_list(library, dead_drive):
    """Registering a setlist used to set files = [] before anything was fetched.

    That alone defeated the planner's "not scanned, skipping entirely" guard,
    with or without the 403 swallow above it.
    """
    from src.sync.background_scanner import BackgroundScanner

    folder = {"folder_id": "driveroot", "name": "MyDrive", "files": None}
    scanner = BackgroundScanner([folder], _Auth(), api_key="",
                                user_settings=_Settings(),
                                download_path=library, force_rescan=True)

    scanner.discover()

    assert folder["files"] is None
