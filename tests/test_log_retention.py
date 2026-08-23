"""Daily logs are append-only and nothing used to remove them.

Measured on a real install: 37 MB across 6 days, one sync day alone at 21 MB.
Left alone that grows for the life of the install.
"""
from datetime import date

from src.core.logging import LOG_RETENTION_DAYS, prune_old_logs


def _logs(tmp_path, *names):
    d = tmp_path / "logs"
    d.mkdir(exist_ok=True)
    for n in names:
        (d / n).write_text("x")
    return d


TODAY = date(2026, 8, 23)


def test_recent_logs_are_kept(tmp_path):
    d = _logs(tmp_path, "2026-08-23.log", "2026-08-22.log", "2026-08-11.log")
    assert prune_old_logs(d, today=TODAY) == 0
    assert len(list(d.iterdir())) == 3


def test_old_logs_are_deleted(tmp_path):
    d = _logs(tmp_path, "2026-08-23.log", "2026-02-04.log", "2026-02-03.log")
    assert prune_old_logs(d, today=TODAY) == 2
    assert [p.name for p in d.iterdir()] == ["2026-08-23.log"]


def test_todays_log_is_never_deleted(tmp_path):
    """It is about to be opened for append."""
    d = _logs(tmp_path, "2026-08-23.log")
    prune_old_logs(d, keep_days=0, today=TODAY)
    assert (d / "2026-08-23.log").exists()


def test_boundary_day_is_kept(tmp_path):
    """keep_days=14 keeps the 13-day-old file and drops the 14-day-old one."""
    d = _logs(tmp_path, "2026-08-10.log", "2026-08-09.log")  # 13 and 14 days old
    prune_old_logs(d, keep_days=14, today=TODAY)
    assert (d / "2026-08-10.log").exists()
    assert not (d / "2026-08-09.log").exists()


def test_foreign_files_are_never_touched(tmp_path):
    """Only files this module creates are ours to delete."""
    d = _logs(tmp_path, "2026-01-01.log", "notes.txt", "important.log",
              "2026-01-01.log.bak", "crash-2026-01-01.log")
    prune_old_logs(d, today=TODAY)
    survivors = sorted(p.name for p in d.iterdir())
    assert survivors == ["2026-01-01.log.bak", "crash-2026-01-01.log",
                         "important.log", "notes.txt"]


def test_impossible_date_is_left_alone(tmp_path):
    d = _logs(tmp_path, "2026-13-45.log")
    assert prune_old_logs(d, today=TODAY) == 0
    assert (d / "2026-13-45.log").exists()


def test_missing_directory_is_not_an_error(tmp_path):
    assert prune_old_logs(tmp_path / "nope", today=TODAY) == 0


def test_default_retention_is_two_weeks():
    assert LOG_RETENTION_DAYS == 14
