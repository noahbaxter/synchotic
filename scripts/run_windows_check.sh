#!/usr/bin/env bash
# Run scripts/windows_check.py on a Windows host over ssh.
#
#   scripts/run_windows_check.sh winprox                    every case, real Drive
#   scripts/run_windows_check.sh winprox --exe              also build the app and launch it once
#   scripts/run_windows_check.sh winprox -- --anonymous     arguments for windows_check.py
#   scripts/run_windows_check.sh winprox -- --library-dir LONG
#   scripts/run_windows_check.sh winprox --upgrade-from v1.5.6
#       that release syncs a library first, then this worktree takes it over
#
# Syncs this worktree to %USERPROFILE%\synchotic-validate\src on the host, keeps
# a venv and UnRAR.exe beside it, and copies this Mac's sign-in (token.json,
# credentials.json) so the check runs signed in as BYOC. .env is not copied;
# GOOGLE_API_KEY is passed for the one command, as run_gates_remote.sh does.
# The check deletes its test install afterwards, downloads included.
set -euo pipefail

HOST="${1:?usage: run_windows_check.sh <ssh-host> [--exe] [-- windows_check args...]}"
shift
EXE=0
FROM=""
while [ $# -gt 0 ]; do
  case "$1" in
    --exe) EXE=1; shift ;;
    --upgrade-from) FROM="${2:?--upgrade-from needs a git ref}"; shift 2 ;;
    --) shift; break ;;
    *) break ;;
  esac
done
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AUTH="$HOME/Library/Application Support/Synchotic"

KEY="${GOOGLE_API_KEY:-}"
if [ -z "$KEY" ]; then
  for f in "$REPO/.env" "$(git -C "$REPO" rev-parse --path-format=absolute --git-common-dir)/../.env"; do
    [ -f "$f" ] && KEY="$(grep -E '^GOOGLE_API_KEY=' "$f" | head -1 | cut -d= -f2-)" && break
  done
fi
[ -n "$KEY" ] || { echo "no GOOGLE_API_KEY in env or .env"; exit 2; }
for f in token.json credentials.json; do
  [ -f "$AUTH/$f" ] || { echo "no $f in $AUTH (sign in with BYOC on this Mac first)"; exit 2; }
done

PROFILE="$(ssh "$HOST" 'echo %USERPROFILE%' | tr -d '\r')"
DEST="$PROFILE\\synchotic-validate"
FWD="${DEST//\\//}"   # the same path with forward slashes, for scp and tar

echo "==> syncing $REPO -> $HOST:$DEST\\src"
# Parenthesised: cmd's `if` swallows the rest of the line, mkdir included.
ssh "$HOST" "(if exist \"$DEST\\src\" rmdir /s /q \"$DEST\\src\") & mkdir \"$DEST\\src\" \"$DEST\\auth\" 2>nul & echo ok" >/dev/null
COPYFILE_DISABLE=1 tar czf - -C "$REPO" \
  --exclude .git --exclude .venv --exclude venv --exclude .env --exclude dist --exclude build \
  --exclude .dm-sync --exclude "Sync Charts" --exclude __pycache__ --exclude .pytest_cache \
  --exclude .overlap_cache.json --exclude libs . \
  | ssh "$HOST" "tar xzf - -C \"$FWD/src\""
scp -q "$AUTH/token.json" "$AUTH/credentials.json" "$HOST:$FWD/auth/"

PS="powershell -NoProfile -ExecutionPolicy Bypass -File"
echo "==> preparing venv and UnRAR on $HOST$([ "$EXE" = 1 ] && echo ', building the app')"
ssh "$HOST" "$PS \"$DEST\\src\\scripts\\windows_prepare.ps1\" -Base \"$DEST\" $([ "$EXE" = 1 ] && echo -Build)"

if [ "$EXE" = 1 ]; then
  echo "==> launching it once"
  ssh "$HOST" "$PS \"$DEST\\src\\scripts\\windows_exe_smoke.ps1\" -Base \"$DEST\""
fi

CHECK="cd /d \"$DEST\" && set GOOGLE_API_KEY=$KEY&& set PYTHONIOENCODING=utf-8&& venv\\Scripts\\python -u src\\scripts\\windows_check.py --root \"$DEST\\root\" --auth \"$DEST\\auth\""

if [ -n "$FROM" ]; then
  echo "==> staging $FROM as old-src"
  ssh "$HOST" "(if exist \"$DEST\\old-src\" rmdir /s /q \"$DEST\\old-src\") & mkdir \"$DEST\\old-src\"" >/dev/null
  git -C "$REPO" archive "$FROM" | ssh "$HOST" "tar xf - -C \"$FWD/old-src\""
  ssh "$HOST" "robocopy \"$DEST\\src\\vendor\" \"$DEST\\old-src\\vendor\" /E /NFL /NDL /NJH /NJS >nul & mkdir \"$DEST\\old-src\\libs\\bin\" 2>nul & copy /y \"$DEST\\unrar_cli\\UnRAR.exe\" \"$DEST\\old-src\\libs\\bin\\\" >nul"
  echo "==> $FROM syncs a library"
  ssh "$HOST" "$CHECK --src \"$DEST\\old-src\" --only setup --keep $*"
  echo "==> this worktree takes it over"
  ssh "$HOST" "$CHECK --src \"$DEST\\src\" --reuse $*"
  ssh "$HOST" "rmdir /s /q \"$DEST\\old-src\""
  exit 0
fi

echo "==> running windows_check on $HOST"
ssh "$HOST" "$CHECK --src \"$DEST\\src\" $*"
