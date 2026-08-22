#!/usr/bin/env bash
# Run the gate suite on a remote host over ssh.
#
#   scripts/run_gates_remote.sh bazzite
#   scripts/run_gates_remote.sh bazzite --quick
#
# Syncs this worktree to ~/synchotic-gates on the host, builds a venv there, and
# runs scripts/run_gates.py. .env is deliberately NOT copied; GOOGLE_API_KEY is
# passed through for the single command instead of being left on the box.
set -euo pipefail

HOST="${1:?usage: run_gates_remote.sh <ssh-host> [run_gates args...]}"
shift || true
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="synchotic-gates"

KEY="${GOOGLE_API_KEY:-}"
if [ -z "$KEY" ]; then
  for f in "$REPO/.env" "$(git -C "$REPO" rev-parse --path-format=absolute --git-common-dir)/../.env"; do
    [ -f "$f" ] && KEY="$(grep -E '^GOOGLE_API_KEY=' "$f" | head -1 | cut -d= -f2-)" && break
  done
fi
[ -n "$KEY" ] || { echo "no GOOGLE_API_KEY in env or .env"; exit 2; }

echo "==> syncing $REPO -> $HOST:~/$DEST"
rsync -az --delete \
  --exclude '.git/' --exclude '.venv/' --exclude '.env' \
  --exclude '__pycache__/' --exclude '.pytest_cache/' \
  --exclude 'Sync Charts/' --exclude '.dm-sync/' --exclude 'build/' --exclude 'dist/' \
  "$REPO/" "$HOST:$DEST/"

echo "==> preparing venv on $HOST"
ssh "$HOST" "cd $DEST && { [ -d .venv ] || python3 -m venv .venv; } && \
  .venv/bin/pip install -q --upgrade pip && .venv/bin/pip install -q -r requirements.txt" 

echo "==> running gates on $HOST"
ssh "$HOST" "cd $DEST && GOOGLE_API_KEY='$KEY' .venv/bin/python scripts/run_gates.py $*"
