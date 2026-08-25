# tests/test_gate_harness.py
"""The release gates measure the app, so a broken gate is worse than no gate.

Markers and staging moved inside the library. The harness has to skip that state
and find markers in either home, or a dev-versus-branch comparison reports
differences that are really just bookkeeping, and passes vacuously on markers.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import _harness  # noqa: E402


def _library(root: Path, state_dir: str) -> Path:
    """A library holding one chart plus a full set of app state."""
    lib = root / "Sync Charts"
    (lib / "Guitar Hero").mkdir(parents=True)
    (lib / "Guitar Hero" / "song.chart").write_text("notes")
    state = lib / state_dir
    (state / "markers").mkdir(parents=True)
    (state / "markers" / "abc.json").write_text('{"archive_path": "Guitar Hero/p.7z"}')
    (state / "owned_drives.json").write_text('{"drives": ["fid"]}')
    (state / "tmp").mkdir()
    (state / "tmp" / "_download_live.7z").write_text("in flight")
    return lib


class TestSnapshotTreeSkipsState:
    def test_library_state_is_not_a_chart(self, tmp_path):
        lib = _library(tmp_path, _harness.LIBRARY_STATE_DIR_NAME)
        assert set(_harness.snapshot_tree(lib)) == {"Guitar Hero/song.chart"}

    def test_machine_state_is_not_a_chart(self, tmp_path):
        lib = _library(tmp_path, _harness.DATA_DIR_NAME)
        assert set(_harness.snapshot_tree(lib)) == {"Guitar Hero/song.chart"}

    def test_in_flight_staging_is_never_compared(self, tmp_path):
        """Staging is transient. Comparing it makes parity fail at random."""
        lib = _library(tmp_path, _harness.LIBRARY_STATE_DIR_NAME)
        assert not any("_download_" in k for k in _harness.snapshot_tree(lib))


class TestSnapshotMarkersFindsBothHomes:
    def test_markers_in_the_data_dir(self, tmp_path):
        data = tmp_path / ".dm-sync"
        (data / "markers").mkdir(parents=True)
        (data / "markers" / "abc.json").write_text("{}")
        assert set(_harness.snapshot_markers(data, tmp_path / "Sync Charts")) == {"abc.json"}

    def test_markers_in_the_library(self, tmp_path):
        lib = _library(tmp_path, _harness.LIBRARY_STATE_DIR_NAME)
        assert set(_harness.snapshot_markers(tmp_path / ".dm-sync", lib)) == {"abc.json"}


class TestDevAndBranchCompareEqual:
    """The property the parity gate actually depends on.

    Same charts and same markers must produce identical snapshots whichever
    layout they are stored in, or the gate cannot tell a real download
    difference from the state relocation.
    """

    def test_identical_content_in_either_layout_matches(self, tmp_path):
        # dev: markers sit in the machine data dir, the library holds only charts
        dev = tmp_path / "dev"
        dev_lib = dev / "Sync Charts"
        (dev_lib / "Guitar Hero").mkdir(parents=True)
        (dev_lib / "Guitar Hero" / "song.chart").write_text("notes")
        dev_data = dev / _harness.DATA_DIR_NAME
        (dev_data / "markers").mkdir(parents=True)
        (dev_data / "markers" / "abc.json").write_text('{"archive_path": "Guitar Hero/p.7z"}')

        # branch: same chart, same marker, state relocated into the library
        branch = tmp_path / "branch"
        branch_lib = _library(branch, _harness.LIBRARY_STATE_DIR_NAME)
        branch_data = branch / _harness.DATA_DIR_NAME
        branch_data.mkdir(parents=True)

        assert _harness.snapshot_tree(dev_lib) == _harness.snapshot_tree(branch_lib)
        assert (_harness.snapshot_markers(dev_data, dev_lib)
                == _harness.snapshot_markers(branch_data, branch_lib))
