"""Space and deletion checks before a sync. An ordinary sync says nothing."""
from src.sync.preflight import GB, Concern, preflight


def _checks(**kwargs):
    args = dict(needed_bytes=1 * GB, free_bytes=500 * GB, unmeasured_drives=0,
                purge_charts=0, purge_bytes=0)
    args.update(kwargs)
    return preflight(**args)


class TestQuietRuns:
    def test_a_sync_that_fits_asks_nothing(self):
        assert _checks() == []

    def test_a_handful_of_deletions_asks_nothing(self):
        """Turning off one setlist should not need a confirmation."""
        assert _checks(purge_charts=4, purge_bytes=200_000_000) == []

    def test_unmeasured_drives_alone_are_not_a_concern(self):
        """Scanning is always in progress. Prompting on it would prompt always."""
        assert _checks(unmeasured_drives=3) == []


class TestSpace:
    def test_more_to_download_than_the_disk_holds(self):
        concerns = _checks(needed_bytes=40 * GB, free_bytes=18 * GB)
        assert [c.kind for c in concerns] == ["space"]
        assert "18" in concerns[0].detail and "40" in concerns[0].detail

    def test_a_sync_that_fits_but_leaves_nothing_behind(self):
        # 75 GB unpacks to about 94, so it lands with roughly 6 GB to spare.
        concerns = _checks(needed_bytes=75 * GB, free_bytes=100 * GB)
        assert [c.kind for c in concerns] == ["headroom"]

    def test_out_of_space_and_low_on_space_say_different_things(self):
        """75 GB into 100 free fits; calling it "not enough" reads as a bug."""
        (out,) = _checks(needed_bytes=40 * GB, free_bytes=18 * GB)
        (low,) = _checks(needed_bytes=75 * GB, free_bytes=100 * GB)
        assert out.headline != low.headline

    def test_archives_need_room_to_unpack_as_well_as_land(self):
        """A 7z occupies its own size and its contents at once, mid-unpack."""
        assert _checks(needed_bytes=90 * GB, free_bytes=100 * GB) != []

    def test_an_unmeasured_drive_makes_a_close_call_a_concern(self):
        """The number is a floor, so close to the line means over it."""
        concerns = _checks(needed_bytes=14 * GB, free_bytes=20 * GB, unmeasured_drives=2)
        assert concerns
        assert "at least" in concerns[0].detail

    def test_a_measured_sync_of_the_same_size_stays_quiet(self):
        assert _checks(needed_bytes=14 * GB, free_bytes=60 * GB) == []


class TestPurge:
    def test_a_large_deletion_is_worth_stopping_for(self):
        concerns = _checks(purge_charts=1204, purge_bytes=86 * GB)
        assert [c.kind for c in concerns] == ["purge"]
        assert "1204" in concerns[0].headline or "1,204" in concerns[0].headline


class TestSeveralAtOnce:
    def test_every_concern_is_reported_with_space_first(self):
        concerns = _checks(needed_bytes=40 * GB, free_bytes=18 * GB,
                           purge_charts=900, purge_bytes=30 * GB)
        assert [c.kind for c in concerns] == ["space", "purge"]

    def test_a_concern_carries_a_headline_and_a_detail(self):
        for concern in _checks(needed_bytes=40 * GB, free_bytes=1 * GB,
                               purge_charts=900, purge_bytes=30 * GB):
            assert isinstance(concern, Concern)
            assert concern.headline and concern.detail
