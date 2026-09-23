"""Rebuild tests/ui/real_charts.json from this machine's scan cache.

    ./venv/bin/python -m tests.manual.build_chart_fixture

Takes only what a Drive scan returns before anything is downloaded: path, name
and size. Loose files are grouped into their chart folder, so one row is one
chart. Up to four charts per scanned drive, so no single library dominates.
"""
import json
import random
from collections import defaultdict
from pathlib import Path

from src.core.paths import get_cache_dir

ARCHIVES = (".zip", ".rar", ".7z")
PER_DRIVE = 4
OUT = Path(__file__).resolve().parents[1] / "ui" / "real_charts.json"


def charts_in(entries: list) -> list[dict]:
    charts = []
    loose = defaultdict(list)
    for entry in entries:
        path, size = entry.get("path", ""), entry.get("size", 0)
        if not path or not size:
            continue
        parts = path.split("/")
        context = parts[0] if len(parts) >= 2 else ""
        if Path(path).suffix.lower() in ARCHIVES:
            charts.append({"name": parts[-1], "context": context,
                           "size": size, "archive": True})
        else:
            loose["/".join(parts[:-1])].append((context, size))

    for folder, files in loose.items():
        if folder:
            charts.append({"name": folder.split("/")[-1], "context": files[0][0],
                           "size": sum(size for _, size in files), "archive": False})
    return charts


def main():
    cache = get_cache_dir() / "scan_cache"
    rng = random.Random(20260910)
    picked, seen = [], set()

    for path in sorted(cache.glob("*.json")):
        try:
            entries = json.loads(path.read_text(encoding="utf-8")).get("files") or []
        except (OSError, ValueError):
            continue
        drive = charts_in(entries)
        for chart in rng.sample(drive, min(PER_DRIVE, len(drive))):
            key = (chart["name"], chart["context"], chart["size"])
            if key not in seen:
                seen.add(key)
                picked.append(chart)

    picked.sort(key=lambda c: (c["context"], c["name"]))
    # One chart per line: a few hundred lines to diff instead of a few thousand.
    rows = ",\n".join(json.dumps(row, ensure_ascii=False) for row in picked)
    OUT.write_text(f"[\n{rows}\n]\n", encoding="utf-8")
    print(f"{len(picked)} charts -> {OUT}")


if __name__ == "__main__":
    main()
