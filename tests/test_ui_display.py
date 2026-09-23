"""UI display state tests.

These used to assert the shape of two printed lines, a completion and an error,
because that was all the download output was. It is one framed list now, so what
is worth pinning here is what the downloader's events do to it: a chart resolves
onto the list, and a failure keeps a reason that survives into the summary.

Run with: pytest tests/test_ui_display.py -v
"""

import io
from contextlib import redirect_stdout
from pathlib import Path

from src import copy
from src.core.formatting import count
from src.ui.widgets.progress import FolderProgress


def _progress(total_files=10):
    return FolderProgress(total_files=total_files, total_folders=1)


class TestChartsResolving:
    def test_an_extracted_archive_lands_on_the_list(self):
        progress = _progress()
        progress.archive_completed(Path("/songs/DM/Pack/x.7z"), "Pack 12.7z", "TestSetlist")

        entry = progress.screen.entries.ordered()[0]
        assert (entry.name, entry.context, entry.state) == ("Pack 12.7z", "TestSetlist", "done")

    def test_a_chart_of_loose_files_resolves_once_its_last_file_lands(self):
        """One row per chart, not one per album.png inside it."""
        progress = _progress()
        progress.folder_progress["/songs/DM/Chart"] = {
            "expected": 2, "completed": 0, "is_chart": True, "path_context": "TestSetlist",
        }

        assert progress.file_completed(Path("/songs/DM/Chart/notes.chart")) is None
        done = progress.file_completed(Path("/songs/DM/Chart/song.ini"))

        assert done == ("Chart", True, "TestSetlist")


class TestErrors:
    def test_a_failure_keeps_a_reason_and_a_filename(self):
        progress = _progress()
        progress.print_error("Setlist", "ERR (timeout): filename.ogg")

        assert len(progress.errors) == 1
        assert progress.errors[0].reason == copy.FAIL_TIMED_OUT
        assert progress.errors[0].filename == "filename.ogg"

    def test_a_message_with_no_filename_is_still_recorded(self):
        progress = _progress()
        progress.print_error("Setlist", "simple error message")

        assert progress.errors[0].filename == "simple error message"
        assert progress.errors[0].reason == "failed"


class TestErrorSummary:
    """The summary prints under the frame, once the sync has finished."""

    def _summary(self, progress):
        captured = io.StringIO()
        with redirect_stdout(captured):
            progress.print_error_summary()
        return captured.getvalue()

    def test_failures_are_grouped_by_reason(self):
        progress = _progress()
        for i in range(3):
            progress.print_error("Setlist", f"ERR (timeout): file{i}.ogg")
        for i in range(2):
            progress.print_error("Setlist", f"NEEDS AUTH (set up automatically): pack{i}.7z")

        output = self._summary(progress)
        assert copy.DID_NOT_DOWNLOAD.format(charts=count(5, "chart")) in output
        assert f"3 {copy.FAIL_TIMED_OUT}" in output
        assert f"2 {copy.FAIL_NEEDS_SIGN_IN}" in output

    def test_a_long_list_is_cut_short(self):
        progress = _progress(total_files=100)
        for i in range(50):
            progress.print_error("Setlist", f"ERR (timeout): file{i}.ogg")

        assert copy.AND_MORE.format(n=47) in self._summary(progress)

    def test_sign_in_failures_say_what_to_do_about_them(self):
        """A reason you can act on, pointing at the row that fixes it."""
        progress = _progress()
        progress.print_error("Setlist", "NEEDS AUTH (set up automatically): pack.7z")

        assert copy.ADVICE_NEEDS_SIGN_IN in self._summary(progress)

    def test_nothing_is_printed_when_nothing_failed(self):
        assert self._summary(_progress()) == ""
