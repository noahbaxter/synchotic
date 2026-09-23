"""Real charts for the sync screen tests.

Every row here came out of the scan cache of an actual library: 506 charts
sampled across 156 scanned drives. That matters twice over.

It is authentic. Names run to 108 characters, setlists to 43, sizes from a
one-byte file to a 3.6 GB pack, and over half of it is archive filenames rather
than anything resembling "Artist - Title". Hand-written rows made the screen
look better than it is.

It is also only what the app knows *before* a download: path, name and size,
which is all a Drive scan returns. Nothing in here was read out of a song.ini,
because at render time the chart is not on disk yet. Loose files are grouped
into their chart folder the way FolderProgress groups them, so one entry is one
chart, same as a row.

Regenerate with tests/manual/build_chart_fixture.py after a scan.
"""
import json
import os
import random
from dataclasses import dataclass
from pathlib import Path

DATA = Path(__file__).with_name("real_charts.json")


@dataclass(frozen=True)
class Chart:
    key: str
    name: str
    context: str
    size: int
    archive: bool


def _master() -> list[Chart]:
    rows = json.loads(DATA.read_text(encoding="utf-8"))
    return [
        Chart(key=f"file{i:04d}", name=row["name"], context=row["context"],
              size=row["size"], archive=row["archive"])
        for i, row in enumerate(rows)
    ]


MASTER = _master()


def new_seed() -> int:
    """A fresh seed per run, from the OS rather than the clock."""
    return int.from_bytes(os.urandom(4), "big")


def sample(count: int, seed: int) -> list[Chart]:
    """`count` charts drawn from the master list under `seed`.

    Report the seed on failure. Reproduce with sample(count, that_seed).
    """
    return random.Random(seed).sample(MASTER, min(count, len(MASTER)))
