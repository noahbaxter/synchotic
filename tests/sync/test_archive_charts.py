"""An archive is one file on Drive, so its chart count arrives as 1.

Telling someone a 94-chart pack contains one chart is worse than an estimate,
but an estimate that overrides a correct count is worse still. These pin both
directions.
"""
import pytest

from src.sync.archive_charts import (
    effective_chart_count, known_archive_charts, _ARCHIVE_CHART_COUNTS,
)


class TestTheTableFillsTheGap:
    def test_a_known_archive_reports_its_real_size(self):
        assert effective_chart_count("(2006) Guitar Hero II", 1, 0) == 100

    def test_drive_and_disk_spellings_both_match(self):
        """Drive writes "Hero: Metallica"; the extracted folder is "Hero - Metallica"."""
        assert known_archive_charts("(2009) Guitar Hero: Metallica") == 49
        assert known_archive_charts("(2009) Guitar Hero - Metallica") == 49

    def test_an_unknown_setlist_is_left_alone(self):
        assert effective_chart_count("Some Charter's Pack", 173, 0) == 173
        assert known_archive_charts("Some Charter's Pack") == 0


class TestTheTableNeverMakesThingsWorse:
    def test_disk_beats_the_table_once_extracted(self):
        """What is actually on disk outranks any estimate."""
        assert effective_chart_count("(2006) Guitar Hero II", 1, 97) == 97

    def test_a_correct_remote_count_is_never_overridden(self):
        """Guitar Hero Live ships as loose charts and Drive counts it right, so
        it must not appear in the table."""
        assert known_archive_charts("(2015) Guitar Hero Live") == 0
        assert effective_chart_count("(2015) Guitar Hero Live", 42, 0) == 42

    def test_the_table_only_ever_corrects_an_undercount(self):
        for name, count in _ARCHIVE_CHART_COUNTS.items():
            assert effective_chart_count(name, count + 5, 0) == count + 5, name

    def test_every_entry_is_a_plausible_pack(self):
        for name, count in _ARCHIVE_CHART_COUNTS.items():
            assert 1 < count < 500, (name, count)


class TestForcingACount:
    """The escape hatch: any setlist whose count is wrong can be pinned without
    editing code or waiting for a release."""

    def _write(self, tmp_path, payload):
        import json
        p = tmp_path / "archive_charts.json"
        p.write_text(json.dumps(payload), encoding="utf-8")
        return p

    def test_a_forced_count_beats_the_built_in_table(self, tmp_path):
        from src.sync.archive_charts import load_forced_counts
        forced = load_forced_counts(self._write(tmp_path, {"(2006) Guitar Hero II": 7}))
        assert effective_chart_count("(2006) Guitar Hero II", 1, 0, forced=forced) == 7

    def test_a_forced_count_beats_the_disk(self, tmp_path):
        """It is an instruction, not a hint, so it outranks even a real scan."""
        from src.sync.archive_charts import load_forced_counts
        forced = load_forced_counts(self._write(tmp_path, {"Anything": 5}))
        assert effective_chart_count("Anything", 1, 900, forced=forced) == 5

    def test_it_works_for_an_archive_with_no_built_in_entry(self, tmp_path):
        from src.sync.archive_charts import load_forced_counts
        forced = load_forced_counts(self._write(tmp_path, {"Some Future Pack": 61}))
        assert effective_chart_count("Some Future Pack", 1, 0, forced=forced) == 61

    def test_a_key_can_be_scoped_to_one_drive(self, tmp_path):
        from src.sync.archive_charts import load_forced_counts
        forced = load_forced_counts(
            self._write(tmp_path, {"Guitar Hero/Shared Name": 12}))
        assert effective_chart_count("Shared Name", 1, 0,
                                     drive_name="Guitar Hero", forced=forced) == 12
        assert effective_chart_count("Shared Name", 1, 0,
                                     drive_name="Other Drive", forced=forced) == 1

    def test_punctuation_and_case_do_not_matter(self, tmp_path):
        from src.sync.archive_charts import load_forced_counts
        forced = load_forced_counts(
            self._write(tmp_path, {"(2009) guitar hero - metallica": 3}))
        assert effective_chart_count("(2009) Guitar Hero: Metallica", 1, 0,
                                     forced=forced) == 3


class TestABrokenOverrideFileIsNotFatal:
    def test_a_missing_file_is_the_normal_case(self, tmp_path):
        from src.sync.archive_charts import load_forced_counts
        assert load_forced_counts(tmp_path / "nope.json") == {}

    def test_malformed_json_is_ignored(self, tmp_path):
        from src.sync.archive_charts import load_forced_counts
        p = tmp_path / "archive_charts.json"
        p.write_text("{ not json,", encoding="utf-8")
        assert load_forced_counts(p) == {}

    def test_a_non_object_is_ignored(self, tmp_path):
        from src.sync.archive_charts import load_forced_counts
        p = tmp_path / "archive_charts.json"
        p.write_text("[1, 2, 3]", encoding="utf-8")
        assert load_forced_counts(p) == {}

    @pytest.mark.parametrize("bad", ["ten", -1, True, None, 1.5])
    def test_a_value_that_is_not_a_count_is_dropped(self, tmp_path, bad):
        import json
        from src.sync.archive_charts import load_forced_counts
        p = tmp_path / "archive_charts.json"
        p.write_text(json.dumps({"Pack": bad, "Good": 9}), encoding="utf-8")
        assert load_forced_counts(p) == {"good": 9}
