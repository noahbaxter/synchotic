#!/usr/bin/env bash
# Run the working tree the way the installed app runs.
#
#   ./dev.sh                              the app, against the installed locations
#   ./dev.sh --portable                   against the repo's own .dm-sync instead
#   ./dev.sh -m tests.manual.preflight_check --free 100G
#
# Installed locations means the real settings, cache, logs and library: the same
# state the packaged app uses. Sync deletes to make the library match, so this is
# the real thing, not a rehearsal. Use --portable for anything experimental.
set -euo pipefail
cd "$(dirname "$0")"

VENV="$PWD/venv"
if [ ! -x "$VENV/bin/python" ]; then
    echo "No venv here. Run 'venv' in this directory first." >&2
    exit 1
fi

# Activate rather than reach into venv/bin: everything the app launches gets the
# venv's python and its console scripts, instead of whichever python the shell
# happens to have first.
export VIRTUAL_ENV="$VENV"
export PATH="$VENV/bin:$PATH"
unset PYTHONHOME
PY=python

PORTABLE=0
if [ "${1:-}" = "--portable" ]; then
    PORTABLE=1
    shift
fi

if [ "$PORTABLE" = "0" ]; then
    export SYNCHOTIC_OS_DIRS=1
fi

"$PY" - <<'BANNER'
import os
from src.core.paths import get_cache_dir, get_data_dir, get_download_path

installed = os.environ.get("SYNCHOTIC_OS_DIRS") == "1"
print()
print(f"  running the working tree against "
      f"{'the installed locations' if installed else 'the repo (.dm-sync)'}")
print(f"    data     {get_data_dir()}")
print(f"    cache    {get_cache_dir()}")
print(f"    library  {get_download_path()}")
print()
BANNER

if [ "${1:-}" = "-m" ]; then
    shift
    exec "$PY" -m "$@"
fi

exec "$PY" sync.py "$@"
