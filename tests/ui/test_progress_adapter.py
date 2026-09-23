"""FolderProgress: downloader events land on the right row, and none of them
leaves a bar running forever."""
import re
from pathlib import Path

import pytest

from src import copy
from src.ui.widgets.progress import FolderProgress


def _progress(total=10):
    progress = FolderProgress(total_files=total, total_folders=0)
    progress.set_aggregate_totals(total, 1_000_000, "Drummer's Monthly")
    return progress


class TestLiveRows:
    def test_a_registered_transfer_shows_as_a_bar(self):
        progress = _progress()
        progress.register_active_download("id1", "Rush - YYZ.7z", "DM 2024-06", 1_000)
        progress.update_active_download("id1", 400)

        entry = progress.screen.entries.ordered()[0]
        assert (entry.state, entry.fraction) == ("active", 0.4)

    def test_a_finished_transfer_leaves_no_bar_running(self):
        """Every path out of a download calls unregister; none may leave a row."""
        progress = _progress()
        progress.register_active_download("id1", "Rush - YYZ.7z", "DM 2024-06", 1_000)
        progress.unregister_active_download("id1")

        assert progress.screen.entries.ordered() == []


class TestAnArchiveKeepsItsRowUntilItSettles:
    """Downloaded is not done. The row stays put through extraction and turns
    into the ✓ or ! itself, rather than vanishing and coming back as a new one."""

    def _extracting(self):
        progress = _progress()
        progress.register_active_download("id1", "Pack/_download_Rush - YYZ.7z", "DM 2024-06", 1_000)
        progress.update_active_download("id1", 1_000)
        progress.mark_extracting("id1")
        return progress

    def test_it_is_still_listed_while_extracting(self):
        progress = self._extracting()

        (entry,) = progress.screen.entries.ordered()
        assert (entry.state, entry.extracting) == ("active", True)

    def test_success_resolves_the_same_row(self):
        progress = self._extracting()
        progress.archive_completed(Path("/songs/DM/Pack/x.7z"), "Rush - YYZ.7z", "DM 2024-06",
                                   file_id="id1")

        (entry,) = progress.screen.entries.ordered()
        assert (entry.name, entry.state, entry.position) == ("Rush - YYZ.7z", "done", 1)

    def test_failure_resolves_the_same_row(self):
        progress = self._extracting()
        progress.print_error("DM 2024-06", "extract: Pack - corrupt archive", file_id="id1")

        (entry,) = progress.screen.entries.ordered()
        assert entry.state == "failed"


class TestResolutions:
    def test_an_extracted_archive_becomes_a_numbered_row(self):
        progress = _progress()
        progress.archive_completed(Path("/songs/DM/Pack/x.7z"), "Pack 12.7z", "DM 2024-06")

        entry = progress.screen.entries.ordered()[0]
        assert (entry.name, entry.state, entry.position) == ("Pack 12.7z", "done", 1)

    def test_a_failure_carries_a_reason_a_person_can_act_on(self):
        progress = _progress()
        progress.print_error("DM 2024-06",
                             "NEEDS AUTH (authenticated download set up automatically): x.7z")

        entry = progress.screen.entries.ordered()[0]
        assert entry.state == "failed"
        assert entry.reason == copy.FAIL_NEEDS_SIGN_IN

    def test_the_reason_survives_into_the_summary(self):
        progress = _progress()
        progress.print_error("DM 2024-06", "ERR (timeout): x.7z")

        assert progress.errors[0].reason == copy.FAIL_TIMED_OUT


class TestTheRateIsCurrent:
    """How fast it is going now, not how fast it has averaged since the run
    began: that sinks through every minute spent checking setlists."""

    def _progress(self):
        progress = _progress()
        now = [100.0]
        progress.screen.clock = lambda: now[0]
        return progress, now

    def test_a_long_quiet_spell_does_not_drag_the_rate_down(self):
        progress, now = self._progress()
        for i in range(5):
            now[0] += 1
            progress.add_downloaded_bytes(1_000_000, file_id=f"early{i}")

        now[0] += 600  # ten minutes of checking setlists, nothing downloading
        progress.add_downloaded_bytes(1_000_000, file_id="late")
        now[0] += 1
        progress.add_downloaded_bytes(1_000_000, file_id="later")

        assert progress.screen.speed == pytest.approx(1_000_000, rel=0.01)

    def test_a_large_file_is_not_counted_twice_when_it_lands(self):
        """It streams its progress, then reports its whole size on landing."""
        progress, now = self._progress()
        progress.register_active_download("big", "big.7z", "", 4_000_000)
        for mb in range(1, 5):
            now[0] += 1
            progress.update_active_download("big", mb * 1_000_000)
        progress.unregister_active_download("big")
        now[0] += 1
        progress.add_downloaded_bytes(4_000_000, file_id="big")

        # 1 MB/s is the truth; counting the landing again would claim ~1.75.
        assert progress.screen.speed <= 1_000_000

    def test_the_moment_of_the_last_transfer_is_recorded(self):
        progress, now = self._progress()
        now[0] = 123.0
        progress.add_downloaded_bytes(10, file_id="x")

        assert progress.screen.last_transfer_at == 123.0


class TestTheTwoCountersNeverDisagree:
    """One panel, one count. The scanner walks every setlist there is, the run
    only downloads the enabled ones, and showing both left the bar on 77/80
    beside a caption reading 78/177."""

    def test_the_background_scan_carries_no_count_of_its_own(self):
        class Stats:
            current_folder = "BirdmanExe Drive/SoundHaven"
            folders_done = 77
            folders_total = 177

        progress = _progress()
        progress.set_scan_stats_getter(Stats)

        note = progress._status_note()
        assert "BirdmanExe Drive/SoundHaven" in note
        # A slash is fine, setlist names have them. A count is not.
        assert not re.search(r"\d+\s*/\s*\d+", note), f"caption still counts: {note}"

    def test_a_finished_scan_says_nothing(self):
        class Stats:
            current_folder = ""
            folders_done = 177
            folders_total = 177

        progress = _progress()
        progress.set_scan_stats_getter(Stats)

        assert progress._status_note() == ""


class TestPhaseChanges:
    def test_download_rate_does_not_follow_the_run_into_the_purge(self):
        """140 KB/s on a job that deletes files."""
        progress = _progress()
        progress.screen.speed = 140_000

        progress.set_phase("PURGE")

        assert progress.screen.speed == 0.0

    def test_staying_in_the_same_phase_leaves_the_rate_alone(self):
        progress = _progress()
        progress.set_phase("DOWNLOAD")
        progress.screen.speed = 140_000

        progress.set_phase("DOWNLOAD")

        assert progress.screen.speed == 140_000


class TestSuspending:
    """A widget that draws its own screen needs the terminal to itself."""

    def test_a_dialog_is_not_painted_over(self, monkeypatch):
        from src.ui.widgets import progress as progress_mod

        created = []

        class FakeLoop:
            def __init__(self, painter):
                self.stopped = False

            def start(self):
                return self

            def stop(self):
                self.stopped = True

        def factory(painter):
            loop = FakeLoop(painter)
            created.append(loop)
            return loop

        monkeypatch.setattr(progress_mod, "PaintLoop", factory)
        progress = FolderProgress(total_files=1, total_folders=0)
        progress.painter.is_tty = True
        progress.start()
        assert len(created) == 1 and not created[0].stopped

        with progress.suspended():
            assert created[0].stopped, "the panel kept repainting over the dialog"
            assert len(created) == 1, "a new painter started while the dialog was up"

        assert len(created) == 2, "the panel never came back after the dialog"


def test_a_units_progress_never_moves_backwards():
    """Checking can reach 90% before downloading starts over near 0%."""
    progress = FolderProgress(total_files=0, total_folders=0)
    progress.set_run_total(4, "setlists")
    progress.set_current_fraction(0.9)
    progress.set_current_fraction(0.3)
    assert progress.screen.run_partial == 0.9
