"""Two archives that unpack to the same chart folder.

A charter can upload the same chart twice, once loose and once inside a folder,
or under names differing only in case or punctuation. Both unpack to the same
place and overwrite each other, so only one can be on disk. The loser's marker
can then never verify again.

Treated naively that reads as "chart missing": it downloads every sync, undoes
the other copy, and reports unsynced the whole time. Whichever copy is actually
on disk should win instead.
"""
import pytest

from src.sync.markers import save_marker, _invalidate_claims
from src.sync.sync_checker import is_archive_synced


@pytest.fixture(autouse=True)
def markers_dir(tmp_path, monkeypatch):
    d = tmp_path / ".synchotic" / "markers"
    d.mkdir(parents=True)
    monkeypatch.setattr("src.sync.markers.get_markers_dir", lambda: d)
    _invalidate_claims()
    yield d
    _invalidate_claims()


@pytest.fixture
def library(tmp_path):
    """A drive folder with one chart already extracted into it."""
    base = tmp_path / "Misc"
    chart = base / "Josh" / "Pup - Hallways"
    chart.mkdir(parents=True)
    (chart / "song.ini").write_text("x" * 1114)
    (chart / "notes.mid").write_bytes(b"y" * 34849)
    return base


LOOSE = "Misc/Josh/Pup - Hallways.rar"
NESTED = "Misc/Josh/Pup - Hallways/Pup - Hallways.rar"
ON_DISK = {"Josh/Pup - Hallways/song.ini": 1114,
           "Josh/Pup - Hallways/notes.mid": 34849}
STALE = {"Josh/Pup - Hallways/song.ini": 1051,
         "Josh/Pup - Hallways/notes.mid": 34825}


class TestTheLoserIsNotMissing:
    def test_the_copy_on_disk_satisfies_the_other_archive(self, library):
        """The nested archive is what got extracted. The loose one must not be
        reported as missing just because its own sizes no longer match."""
        save_marker(NESTED, "md5nested", ON_DISK)
        save_marker(LOOSE, "md5loose", STALE)

        synced, size = is_archive_synced(
            folder_name="Misc", checksum_path="Josh",
            archive_name="Pup - Hallways.rar", manifest_md5="md5loose",
            local_base=library,
        )
        assert synced is True, "loser reported missing, so it re-downloads every sync"
        assert size == sum(ON_DISK.values())

    def test_it_works_whichever_one_won(self, library):
        """Nothing privileges one shape over the other. Whoever is on disk wins."""
        save_marker(LOOSE, "md5loose", ON_DISK)
        save_marker(NESTED, "md5nested", STALE)

        synced, _ = is_archive_synced(
            folder_name="Misc", checksum_path="Josh/Pup - Hallways",
            archive_name="Pup - Hallways.rar", manifest_md5="md5nested",
            local_base=library,
        )
        assert synced is True


class TestItStillDownloadsWhatItShould:
    def test_a_genuinely_missing_chart_is_still_missing(self, library):
        """No twin on disk means the chart really is absent."""
        save_marker("Misc/Josh/Other Song.rar", "md5other",
                    {"Josh/Other Song/song.ini": 500})

        synced, size = is_archive_synced(
            folder_name="Misc", checksum_path="Josh",
            archive_name="Other Song.rar", manifest_md5="md5other",
            local_base=library,
        )
        assert synced is False
        assert size == 0

    def test_an_archive_with_no_marker_is_not_rescued(self, library):
        """A chart never downloaded has no marker, so there is nothing to
        compare and it must not be quietly considered done."""
        save_marker(NESTED, "md5nested", ON_DISK)

        synced, _ = is_archive_synced(
            folder_name="Misc", checksum_path="Josh",
            archive_name="Never Fetched.rar", manifest_md5="md5never",
            local_base=library,
        )
        assert synced is False

    def test_a_twin_that_is_also_gone_does_not_count(self, library):
        """Both copies missing from disk is a real gap, not a conflict."""
        save_marker("Misc/Josh/Gone.rar", "md5a", {"Josh/Gone/song.ini": 10})
        save_marker("Misc/Josh/Gone/Gone.rar", "md5b", {"Josh/Gone/song.ini": 20})

        synced, _ = is_archive_synced(
            folder_name="Misc", checksum_path="Josh",
            archive_name="Gone.rar", manifest_md5="md5a",
            local_base=library,
        )
        assert synced is False
