"""Locate and load the repo .env.

.env is gitignored, so it only exists in the main worktree. Scripts run from a
linked worktree have to reach across to find it.
"""

import os
import subprocess
from pathlib import Path


def env_candidates(repo: Path) -> list[Path]:
    paths = [repo / ".env"]
    try:
        common = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--path-format=absolute",
             "--git-common-dir"],
            capture_output=True, text=True, timeout=10, check=True,
        ).stdout.strip()
        if common:
            paths.append(Path(common).parent / ".env")
    except Exception:
        pass
    return paths


def load_env(repo: Path) -> Path | None:
    """Read the first .env found into os.environ. Existing vars win."""
    for path in env_candidates(repo):
        if not path.exists():
            continue
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            os.environ.setdefault(key.strip(), val.strip())
        return path
    return None
