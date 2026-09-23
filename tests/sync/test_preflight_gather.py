"""The numbers preflight needs, from the stats cache. A drive never scanned
counts as unmeasured, so the total is a floor."""
from src.sync.preflight import GB, concerns_for, gather


class FakeSettings:
    def __init__(self, enabled=(), setlists_off=()):
        self._enabled = set(enabled)
        self._off = set(setlists_off)

    def is_drive_enabled(self, folder_id):
        return folder_id in self._enabled

    def is_subfolder_enabled(self, folder_id, name):
        return (folder_id, name) not in self._off


class FakeCache:
    """Stands in for PersistentStatsCache, holding one drive's setlists."""

    def __init__(self, stats):
        self._stats = stats

    def get_setlist(self, folder_id, name):
        return self._stats.get((folder_id, name))


class Stats:
    def __init__(self, total_size=0, synced_size=0, disk_size=0, disk_files=0,
                 disk_charts=0, total_charts=0, synced_charts=0):
        self.total_size = total_size
        self.synced_size = synced_size
        self.disk_size = disk_size
        self.disk_files = disk_files
        self.disk_charts = disk_charts
        self.total_charts = total_charts
        self.synced_charts = synced_charts


def _folder(folder_id, name, setlists):
    return {"folder_id": folder_id, "name": name, "setlists": setlists}


class TestWhatIsStillToDownload:
    def test_only_what_is_missing_counts(self):
        """Half a drive already on disk is not half a drive to download again."""
        cache = FakeCache({("d1", "Pack"): Stats(total_size=10 * GB, synced_size=6 * GB)})
        needed, unmeasured, charts, purge_bytes = gather(
            [_folder("d1", "Drive", ["Pack"])], FakeSettings(enabled=["d1"]), cache)

        assert needed == 4 * GB
        assert unmeasured == 0

    def test_drives_that_are_off_are_not_counted(self):
        cache = FakeCache({("d1", "Pack"): Stats(total_size=10 * GB)})
        needed, _, _, _ = gather([_folder("d1", "Drive", ["Pack"])],
                                 FakeSettings(enabled=[]), cache)

        assert needed == 0

    def test_a_drive_nobody_has_scanned_is_counted_as_unmeasured(self):
        cache = FakeCache({})
        needed, unmeasured, _, _ = gather([_folder("d1", "Drive", ["Pack"])],
                                          FakeSettings(enabled=["d1"]), cache)

        assert (needed, unmeasured) == (0, 1)

    def test_a_drive_with_some_setlists_measured_is_still_measured(self):
        """Part of a drive counts. The floor grows; the drive is not unknown."""
        cache = FakeCache({("d1", "A"): Stats(total_size=2 * GB)})
        needed, unmeasured, _, _ = gather([_folder("d1", "Drive", ["A", "B"])],
                                          FakeSettings(enabled=["d1"]), cache)

        assert (needed, unmeasured) == (2 * GB, 0)

    def test_a_drive_that_is_off_is_not_unmeasured(self):
        """Nothing will download from it, so it cannot make the sync not fit."""
        _, unmeasured, _, _ = gather([_folder("d1", "Drive", ["Pack"])],
                                     FakeSettings(enabled=[]), FakeCache({}))

        assert unmeasured == 0


class TestTheWholeCheck:
    """concerns_for is what sync calls, so the wiring is worth its own test."""

    def _usage(self, free):
        class Usage:
            def __init__(self, free):
                self.free = free
        return lambda path: Usage(free)

    def test_a_library_with_room_raises_nothing(self):
        cache = FakeCache({("d1", "Pack"): Stats(total_size=4 * GB)})
        concerns, free = concerns_for([_folder("d1", "Drive", ["Pack"])],
                                      FakeSettings(enabled=["d1"]), cache,
                                      "/Songs", disk_usage=self._usage(500 * GB))

        assert concerns == []
        assert free == 500 * GB

    def test_a_library_without_room_raises_one(self):
        cache = FakeCache({("d1", "Pack"): Stats(total_size=40 * GB)})
        concerns, _ = concerns_for([_folder("d1", "Drive", ["Pack"])],
                                   FakeSettings(enabled=["d1"]), cache,
                                   "/Songs", disk_usage=self._usage(18 * GB))

        assert [c.kind for c in concerns] == ["space"]

    def test_a_disk_it_cannot_measure_does_not_block_the_sync(self):
        def explode(path):
            raise OSError("no such volume")

        concerns, free = concerns_for([], FakeSettings(), FakeCache({}),
                                      "/Songs", disk_usage=explode)

        assert (concerns, free) == ([], 0)


class TestWhatWouldBeDeleted:
    def test_a_setlist_turned_off_with_files_on_disk_is_purgeable(self):
        cache = FakeCache({
            ("d1", "Keep"): Stats(total_size=1 * GB),
            ("d1", "Drop"): Stats(disk_size=3 * GB, disk_files=40, disk_charts=12),
        })
        _, _, charts, purge_bytes = gather(
            [_folder("d1", "Drive", ["Keep", "Drop"])],
            FakeSettings(enabled=["d1"], setlists_off=[("d1", "Drop")]), cache)

        assert (charts, purge_bytes) == (12, 3 * GB)

    def test_a_drive_turned_off_puts_all_of_its_disk_content_up_for_purge(self):
        cache = FakeCache({("d1", "Pack"): Stats(disk_size=5 * GB, disk_files=60,
                                                 disk_charts=20)})
        _, _, charts, purge_bytes = gather([_folder("d1", "Drive", ["Pack"])],
                                           FakeSettings(enabled=[]), cache)

        assert (charts, purge_bytes) == (20, 5 * GB)
