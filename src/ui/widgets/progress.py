"""The seam between the downloader and the sync screen: transfer events become
rows on one list of charts (see sync_screen).

Folder bookkeeping lives here too: a chart made of loose files is finished
when the last of its files is.
"""

from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from ... import copy
from ...core.constants import CHART_MARKERS
from ...core.formatting import extract_path_context
from ...core.progress import ProgressTracker
from .sync_paint import PaintLoop, ScreenPainter
from .sync_screen import SyncScreen
from . import sync_display as display


# How far back the transfer rate looks: "how fast now", not a run average that
# sinks while the run checks setlists and downloads nothing.
RATE_WINDOW_SECONDS = 5.0


@dataclass
class DownloadError:
    """Records a download error for summary."""
    path_context: str
    filename: str
    reason: str


class FolderProgress(ProgressTracker):
    """Tracks chart completion and drives the sync screen."""

    def __init__(self, total_files: int, total_folders: int):
        super().__init__()
        self.total_files = total_files
        self.total_folders = total_folders
        self.total_charts = 0
        self.completed_files = 0
        self.completed_charts = 0

        self.total_bytes = 0
        self.downloaded_bytes = 0

        # Every byte that has arrived, counted once: a large file reports as it
        # streams and then its whole size again when it lands.
        self._received = 0
        self._streamed: dict[str, int] = {}
        self._rate_samples: deque = deque()

        self.folder_progress = {}
        self.errors: list[DownloadError] = []

        self.screen = SyncScreen()
        from ..components.header import header_height, header_text
        self.painter = ScreenPainter(self.screen, banner_text=header_text,
                                     banner_rows=header_height)
        self._loop = None
        self._scan_stats_getter = None
        # What is blocking the run right now, shown ahead of the scan note.
        self._activity_text = ""
        self.screen.status_getter = self._status_note
        # Progress within the unit in flight; see set_current_fraction.
        self._current_fraction = 0.0
        self._unit_baseline_bytes = 0
        self._unit_total_bytes = 0

    # -- setup ------------------------------------------------------------

    def set_aggregate_totals(self, total_files: int, total_bytes: int, drive_name: str = ""):
        """Add this folder's totals to the run's: one screen serves every folder."""
        self.total_files += total_files
        self.total_bytes += total_bytes
        if drive_name:
            self.screen.title = drive_name
        self.screen.set_totals(files=self.total_charts or self.total_files,
                               total_bytes=self.total_bytes)
        self._start_painting()

    def start(self):
        """Take the terminal now, before any totals are known."""
        self._start_painting()

    def set_title(self, text: str) -> None:
        """The current drive/file context, shown next to the phase in the header."""
        self.screen.title = text

    def set_phase(self, text: str) -> None:
        """The stage word in the header: DOWNLOAD, VERIFY, PURGE... A new
        phase zeroes the rate, or a purge would claim to run at 140 KB/s."""
        phase = text.upper()
        if phase != self.screen.phase:
            self.screen.speed = 0.0
        self.screen.phase = phase

    def set_run_total(self, total: int, unit: str = "") -> None:
        """How many units (setlists, drives) make up the current phase. The bar
        tracks these instead of bytes, and `unit` names them so the counter is
        not read as a count of the charts below."""
        self.screen.run_total = total
        self.screen.run_done = 0
        self.screen.run_unit = unit
        self._reset_unit()

    def advance_run(self, n: int = 1) -> None:
        """One more unit of the current phase resolved, whatever it was."""
        self.screen.run_done += n
        self._reset_unit()

    def _reset_unit(self) -> None:
        self._current_fraction = 0.0
        self._unit_total_bytes = 0
        self.screen.run_partial = 0.0

    def set_current_fraction(self, fraction: float) -> None:
        """How far into the current unit we are, 0 to 1. Only ever moves up:
        the signal changes mid-unit (files checked, then bytes downloaded),
        and the bar must not jump backwards."""
        self._current_fraction = max(self._current_fraction, min(1.0, fraction))
        self.screen.run_partial = self._current_fraction

    def begin_unit(self, total_bytes: int) -> None:
        """A download batch is starting, so its bytes count toward this unit."""
        self._unit_baseline_bytes = self.downloaded_bytes
        self._unit_total_bytes = total_bytes

    def set_stage(self, text: str) -> None:
        """What is happening right now, on the divider ahead of the scan note.
        "" falls back to the scan note."""
        self._activity_text = text

    def note(self, name: str, context: str = "") -> None:
        """A resolved row that is not a chart (a marker rebuild, a purge
        result), so the whole run stays on the panel. Not counted as a chart."""
        with self.lock:
            if self._closed:
                return
            self.screen.entries.note(name, name=name, context=context)
        self._start_painting()

    def set_scan_stats_getter(self, getter):
        """Scan progress, shown while nothing more specific is happening."""
        self._scan_stats_getter = getter

    def _status_note(self) -> str:
        return self._activity_text or self._scan_note()

    def _scan_note(self) -> str:
        """The background scan, labelled as such: it is on a different setlist
        than the rows below."""
        if not self._scan_stats_getter:
            return ""
        try:
            stats = self._scan_stats_getter()
        except Exception:
            return ""
        if not stats or not stats.current_folder:
            return ""
        # No count: the scanner walks switched-off drives too, so its total
        # would disagree with the run's own.
        return copy.STAGE_SCANNING_AHEAD.format(name=stats.current_folder)

    def _start_painting(self):
        """Take over the terminal, but only when there is one to take over."""
        if self._loop or not self.painter.is_tty:
            return
        self._loop = PaintLoop(self.painter).start()

    @contextmanager
    def suspended(self):
        """Hand the terminal to something that draws its own screen, such as
        a confirm dialog, which the paint loop would otherwise paint over."""
        loop, self._loop = self._loop, None
        if loop:
            loop.stop()
        try:
            yield
        finally:
            if loop:
                self._start_painting()

    def register_folders(self, tasks):
        """Register all folders and their expected file counts."""
        folder_files = {}
        for task in tasks:
            folder = str(task.local_path.parent)
            if folder not in folder_files:
                folder_files[folder] = {"files": [], "archives": [], "rel_paths": []}
            filename = task.local_path.name.lower()
            folder_files[folder]["files"].append(filename)
            folder_files[folder]["rel_paths"].append(task.rel_path)
            if task.is_archive:
                display_name = task.local_path.name
                if display_name.startswith("_download_"):
                    display_name = display_name[10:]
                folder_files[folder]["archives"].append(display_name)

        for folder, data in folder_files.items():
            filenames = data["files"]
            archives = data["archives"]
            rel_paths = data["rel_paths"]

            archive_count = len(archives)
            has_markers = bool(set(filenames) & CHART_MARKERS)
            is_chart = has_markers and archive_count == 0

            self.folder_progress[folder] = {
                "expected": len(filenames),
                "completed": 0,
                "is_chart": is_chart,
                "path_context": extract_path_context(rel_paths[0] if rel_paths else None),
            }

            if archive_count > 0:
                self.total_charts += archive_count
            elif is_chart:
                self.total_charts += 1

        self.total_folders = len(folder_files)
        self.screen.set_totals(files=self.total_charts, total_bytes=self.total_bytes)

    # -- live transfers ---------------------------------------------------

    def register_active_download(self, file_id: str, display_name: str,
                                 path_context: str, total_bytes: int):
        with self.lock:
            self.screen.entries.start(file_id, display_name, path_context, total_bytes)

    def update_active_download(self, file_id: str, downloaded_bytes: int):
        with self.lock:
            self.screen.entries.progress(file_id, downloaded_bytes)
            already = self._streamed.get(file_id, 0)
            if downloaded_bytes > already:
                self._received += downloaded_bytes - already
                self._streamed[file_id] = downloaded_bytes
                self._sample_rate()

    def mark_extracting(self, file_id: str):
        with self.lock:
            self.screen.entries.extracting(file_id)

    def unregister_active_download(self, file_id: str):
        """Forget a live row that will not resolve as a chart of its own (a
        loose file, a transfer handed to another tier)."""
        with self.lock:
            self.screen.entries.drop(file_id)

    def add_downloaded_bytes(self, bytes_count: int, file_id: str | None = None):
        """A file finished. `file_id` lets the rate credit what that file
        already streamed, so a large file is not counted twice as it lands."""
        with self.lock:
            self.downloaded_bytes += bytes_count
            self.screen.downloaded_bytes = self.downloaded_bytes
            streamed = self._streamed.pop(file_id, 0) if file_id else 0
            self._received += max(0, bytes_count - streamed)
            self._sample_rate()
        if self._unit_total_bytes:
            done = self.downloaded_bytes - self._unit_baseline_bytes
            self.set_current_fraction(done / self._unit_total_bytes)

    def _sample_rate(self):
        """The transfer rate over the last few seconds. Call under the lock."""
        now = self.screen.clock()
        samples = self._rate_samples
        samples.append((now, self._received))
        # After a quiet spell only this sample is left, so the rate starts
        # over rather than averaging across the silence.
        while now - samples[0][0] > RATE_WINDOW_SECONDS:
            samples.popleft()

        started, received_then = samples[0]
        if now > started:
            self.screen.speed = (self._received - received_then) / (now - started)
        else:
            self.screen.speed = 0.0
        self.screen.last_transfer_at = now

    # -- resolutions ------------------------------------------------------

    def write(self, msg: str):
        """A line that is not about one chart. Only piped output shows these."""
        with self.lock:
            if self._closed:
                return
            if not self.painter.is_tty:
                print(msg)

    def print_error(self, path_context: str, message: str, file_id: str = ""):
        """`file_id` resolves the transfer's live row in place, if it had one."""
        with self.lock:
            if self._closed:
                return
            reason = display.describe_failure(message)
            filename = message.split(":", 1)[1].strip() if ":" in message else message
            self.errors.append(DownloadError(path_context, filename, reason))
            self.screen.entries.fail(file_id or filename, reason,
                                     name=filename, context=path_context)

    def archive_completed(self, local_path: Path, archive_name: str, path_context: str = "",
                          file_id: str = ""):
        with self.lock:
            if self._closed:
                return
            folder = str(local_path.parent)
            if folder in self.folder_progress and not path_context:
                path_context = self.folder_progress[folder].get("path_context", "")
            self.completed_charts += 1
            self.screen.entries.finish(file_id or archive_name,
                                       name=archive_name, context=path_context)

    def file_completed(self, local_path: Path) -> tuple[str, bool, str] | None:
        with self.lock:
            if self._closed:
                return None
            self.completed_files += 1
            folder = str(local_path.parent)

            if folder in self.folder_progress:
                self.folder_progress[folder]["completed"] += 1
                prog = self.folder_progress[folder]
                if prog["completed"] >= prog["expected"] and prog["is_chart"]:
                    self.completed_charts += 1
                    return (local_path.parent.name, True, prog.get("path_context", ""))
            return None

    def print_folder_complete(self, folder_name: str, is_chart: bool, path_context: str = ""):
        with self.lock:
            if self._closed or not is_chart:
                return
            self.screen.entries.finish(folder_name, name=folder_name, context=path_context)

    # -- teardown ---------------------------------------------------------

    def close(self):
        with self.lock:
            if self._closed:
                return
            self._closed = True
        if self._loop:
            self._loop.stop()
            self._loop = None
        else:
            self.painter.paint()
            self.painter.close()

    def print_error_summary(self):
        """Group what failed by reason, under the frame it just left behind."""
        if not self.errors:
            return

        by_reason: dict[str, list[DownloadError]] = {}
        for err in self.errors:
            by_reason.setdefault(err.reason, []).append(err)
        display.failure_summary(by_reason)
