"""Files the OS writes back the moment you delete them.

macOS creates a ._name sidecar beside every file on SMB and exFAT, which is
exactly what Library Path points people at. Purging them achieves nothing: the
filesystem recreates them on the next write, so every sync reports work it did
not really do, and the count drifts toward the confirm threshold on a big
library. Measured on a real SMB run: 5 real files, 5 sidecars, all 5 queued.
"""
import pytest

from src.config.settings import DEFAULT_PURGE_IGNORE, UserSettings
from src.sync.purge_planner import find_extra_files


def _extras(tmp_path, names, ignore=None):
    folder = tmp_path / "Drive"
    folder.mkdir(parents=True, exist_ok=True)
    local = {}
    for n in names:
        p = folder / n
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x")
        local[n] = 1
    got = find_extra_files("Drive", folder, set(), set(), local, ignore_patterns=ignore)
    return {p.name for p, _ in got}


class TestOsLitterIsLeftAlone:
    def test_appledouble_sidecars_are_not_purged(self, tmp_path):
        assert _extras(tmp_path, ["._song.ini", "song.ini"]) == {"song.ini"}

    def test_the_usual_suspects(self, tmp_path):
        names = [".DS_Store", "Thumbs.db", "desktop.ini", "real.chart"]
        assert _extras(tmp_path, names) == {"real.chart"}

    def test_a_real_chart_named_like_nothing_special_still_purges(self, tmp_path):
        assert _extras(tmp_path, ["notes.mid"]) == {"notes.mid"}

    def test_sidecars_in_subfolders_too(self, tmp_path):
        got = _extras(tmp_path, ["Set/Chart/._notes.mid", "Set/Chart/notes.mid"])
        assert got == {"notes.mid"}


class TestItIsConfigurable:
    def test_a_custom_list_replaces_the_default(self, tmp_path):
        got = _extras(tmp_path, ["._x.ini", "keep.log"], ignore=["*.log"])
        assert got == {"._x.ini"}

    def test_an_empty_list_purges_everything(self, tmp_path):
        got = _extras(tmp_path, ["._x.ini", "y.ini"], ignore=[])
        assert got == {"._x.ini", "y.ini"}

    def test_garbage_in_settings_falls_back_instead_of_crashing(self, tmp_path):
        """A hand-edited settings.json must not crash a purge."""
        assert _extras(tmp_path, ["._x.ini", "y.ini"], ignore="not-a-list") == {"y.ini"}

    def test_it_round_trips_through_settings(self, tmp_path):
        s = UserSettings(tmp_path / "s.json")
        s.purge_ignore = ["*.tmp"]
        s.save()
        assert UserSettings.load(tmp_path / "s.json").purge_ignore == ["*.tmp"]

    def test_it_defaults_when_absent(self, tmp_path):
        loaded = UserSettings.load(tmp_path / "none.json")
        assert loaded.purge_ignore == list(DEFAULT_PURGE_IGNORE)
