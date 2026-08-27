"""What the scanner reaches for next.

Nothing can be downloaded from a setlist until it has been scanned, and a
single scan thread feeds the downloader. Order therefore decides how long the
downloader sits idle: cheap setlists first give it work sooner, and spreading
across drives stops one large drive holding up work that was ready elsewhere.

Ordering is a hint built from remembered counts. It must never change which
setlists get scanned, only when.
"""
import pytest

from src.sync.background_scanner import BackgroundScanner, SetlistInfo


@pytest.fixture
def scanner(monkeypatch):
    """A scanner with a stubbed stats cache, so tests pick the counts."""
    def build(setlists, remembered=None, enabled=()):
        remembered = remembered or {}

        class FakeCounts:
            def remembered_chart_count(self, drive_id, name):
                return remembered.get((drive_id, name))

        monkeypatch.setattr("src.sync.cache.get_persistent_stats_cache",
                            lambda: FakeCounts())

        import threading

        s = BackgroundScanner.__new__(BackgroundScanner)
        s._lock = threading.RLock()
        s._all_setlists = {
            sid: SetlistInfo(setlist_id=sid, name=name, drive_id=drive,
                             drive_name=drive, drive={})
            for sid, name, drive in setlists
        }
        s._order_cache = None
        s._enabled_setlist_ids = set(enabled)
        s._scanned_setlist_ids = set()
        s._failed_setlist_ids = set()
        return s
    return build


class TestCheapestFirst:
    def test_a_drive_is_scanned_smallest_setlist_first(self, scanner):
        s = scanner(
            [("a", "big", "d1"), ("b", "small", "d1"), ("c", "mid", "d1")],
            remembered={("d1", "big"): 900, ("d1", "small"): 3, ("d1", "mid"): 40},
        )
        assert s._scan_order() == ["b", "c", "a"]

    def test_a_setlist_never_scanned_goes_last(self, scanner):
        """An unknown setlist could be anything. Everything we can actually
        cost should go first rather than gambling the downloader's wait on it."""
        s = scanner(
            [("unknown", "new", "d1"), ("known", "old", "d1")],
            remembered={("d1", "old"): 500},
        )
        assert s._scan_order() == ["known", "unknown"]


class TestAcrossDrives:
    def test_drives_are_interleaved_not_drained(self, scanner):
        """Depth-first leaves every other drive at zero until the first one
        finishes. Round-robin gets each drive producing work early."""
        s = scanner(
            [("a1", "s1", "d1"), ("a2", "s2", "d1"), ("a3", "s3", "d1"),
             ("b1", "s1", "d2"), ("c1", "s1", "d3")],
            remembered={("d1", "s1"): 1, ("d1", "s2"): 2, ("d1", "s3"): 3,
                        ("d2", "s1"): 1, ("d3", "s1"): 1},
        )
        order = s._scan_order()
        assert order[:3] == ["a1", "b1", "c1"], "drained one drive before the others"
        assert order[3:] == ["a2", "a3"]

    def test_every_setlist_is_still_scheduled_exactly_once(self, scanner):
        """Ordering is a hint. Dropping or duplicating one would change what
        gets scanned, which is the one thing it must not do."""
        setlists = [(f"s{i}", f"name{i}", f"d{i % 3}") for i in range(20)]
        s = scanner(setlists, remembered={})
        order = s._scan_order()
        assert sorted(order) == sorted(sid for sid, _, _ in setlists)
        assert len(order) == len(set(order))


class TestPicking:
    def test_enabled_setlists_come_before_disabled_ones(self, scanner):
        """Priority beats cost: a disabled setlist is not downloadable, so
        scanning it first would leave the downloader idle regardless."""
        s = scanner(
            [("cheap_off", "a", "d1"), ("dear_on", "b", "d1")],
            remembered={("d1", "a"): 1, ("d1", "b"): 999},
            enabled=["dear_on"],
        )
        assert s._get_next_setlist_to_scan().setlist_id == "dear_on"

    def test_already_scanned_ones_are_skipped(self, scanner):
        s = scanner(
            [("a", "a", "d1"), ("b", "b", "d1")],
            remembered={("d1", "a"): 1, ("d1", "b"): 2},
        )
        s._scanned_setlist_ids.add("a")
        assert s._get_next_setlist_to_scan().setlist_id == "b"

    def test_nothing_left_returns_none(self, scanner):
        s = scanner([("a", "a", "d1")], remembered={("d1", "a"): 1})
        s._scanned_setlist_ids.add("a")
        assert s._get_next_setlist_to_scan() is None
