#!/usr/bin/env bash
# Build Synchotic-x86_64.AppImage, the Linux counterpart of Synchotic.app.
#
#   packaging/linux/build_appimage.sh
#
# Same shape as the .app: a PyInstaller onedir build of the TUI, a bundled
# WezTerm to give it a window, and a shim that wires the two together. Nothing
# is fetched on first run, unlike the launcher path.
#
# The runtime is uruntime rather than appimagetool's default, and that is the
# whole reason this is not a one-liner. A stock AppImage self-mounts through
# libfuse2, which the atomic Fedora spins (Bazzite, Kinoite) and Ubuntu 26.04
# no longer ship, so it would fail to start on the machines this is aimed at.
# uruntime tries FUSE and extracts itself when that is unavailable. It is the
# same reasoning that made launcher.py extract WezTerm's AppImage instead of
# running it.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

PY="${PYTHON:-.venv/bin/python}"
VERSION="$(cat VERSION)"
OUT="dist/Synchotic-${VERSION}-x86_64.AppImage"
APPDIR="build/appimage/Synchotic.AppDir"

WEZ_VER="20240203-110809-5046fc22"
WEZ_URL="https://github.com/wezterm/wezterm/releases/download/$WEZ_VER/WezTerm-$WEZ_VER-Ubuntu20.04.AppImage"
WEZ_CACHE="build/wezterm-linux-$WEZ_VER"

# Pinned: an AppImage that cannot start on the target distro is worse than one
# that is a release behind. Override to test a different runtime.
URUNTIME_VER="${URUNTIME_VERSION:-v0.6.1}"
URUNTIME_URL="https://github.com/VHSgunzo/uruntime/releases/download/$URUNTIME_VER/uruntime-appimage-squashfs-lite-x86_64"
RUNTIME="build/uruntime-$URUNTIME_VER-x86_64"

# libs/bin/unrar is whatever the last build put there, and the checked-in copy is
# a macOS binary. CI swaps it per platform via .github/actions/setup-unrar; a
# local build has to have done the same, or the AppImage ships an unrar that
# cannot run and only fails when someone opens a .rar.
UNRAR="libs/bin/unrar"
if [ ! -f "$UNRAR" ] || ! file -b "$UNRAR" | grep -q ELF; then
  echo "error: $UNRAR is not a Linux binary." >&2
  echo "  Build it first (same recipe as .github/actions/setup-unrar):" >&2
  echo "    curl -LO https://www.rarlab.com/rar/unrarsrc-7.2.2.tar.gz" >&2
  echo "    tar -xzf unrarsrc-7.2.2.tar.gz && (cd unrar && make)" >&2
  echo "    mkdir -p libs/bin && cp unrar/unrar libs/bin/unrar" >&2
  exit 1
fi

echo "==> building Synchotic $VERSION"
rm -rf "$APPDIR" build/synchotic-linux
mkdir -p "$APPDIR/usr/bin" "$APPDIR/usr/share/synchotic" dist build

CERT="$("$PY" -c 'import certifi; print(certifi.where())')"
"$PY" -m PyInstaller --onedir --name synchotic-tui --clean --noconfirm \
  --distpath build/appimage/pyinstaller \
  --workpath build/synchotic-linux \
  --paths vendor/chotic-ui --collect-submodules chotic_ui \
  --add-data "drives.json:." \
  --add-data "src/drive/byoc_setup_instructions.txt:src/drive" \
  --add-data "VERSION:." \
  --add-data "${CERT}:certifi" \
  --add-binary "libs/bin/unrar:." \
  --hidden-import certifi \
  --hidden-import rarfile \
  sync.py >/dev/null

cp -a build/appimage/pyinstaller/synchotic-tui/. "$APPDIR/usr/bin/"

# --- WezTerm ---
# Extracted rather than run, for the same FUSE reason as above.
if [ ! -d "$WEZ_CACHE/squashfs-root" ]; then
  echo "==> fetching WezTerm $WEZ_VER"
  mkdir -p "$WEZ_CACHE"
  curl -fsSL -o "$WEZ_CACHE/wezterm.AppImage" "$WEZ_URL"
  chmod +x "$WEZ_CACHE/wezterm.AppImage"
  ( cd "$WEZ_CACHE" && ./wezterm.AppImage --appimage-extract >/dev/null )
fi

WEZ_ROOT="$WEZ_CACHE/squashfs-root"
cp "$WEZ_ROOT/usr/bin/wezterm-gui" "$APPDIR/usr/bin/wezterm-gui"
# WezTerm's AppImage carries its own libraries. They are kept apart from the
# TUI's, which ships its own libssl through PyInstaller: one flat lib directory
# would let whichever loads first shadow the other.
if [ -d "$WEZ_ROOT/usr/lib" ]; then
  mkdir -p "$APPDIR/usr/lib/wezterm"
  cp -a "$WEZ_ROOT/usr/lib/." "$APPDIR/usr/lib/wezterm/"
fi

# The launcher builds already ship this file on every platform; it is config,
# not Mac-specific, and duplicating it here would only let the copies drift.
cp packaging/macos/wezterm.lua "$APPDIR/usr/share/synchotic/wezterm.lua"
cp packaging/macos/WezTerm-LICENSE.txt "$APPDIR/usr/share/synchotic/" 2>/dev/null || true

# --- desktop integration ---
# appimagetool wants both of these at the AppDir root.
cp packaging/linux/synchotic.desktop "$APPDIR/synchotic.desktop"
cp packaging/linux/synchotic.png "$APPDIR/synchotic.png"
mkdir -p "$APPDIR/usr/share/applications" "$APPDIR/usr/share/icons/hicolor/256x256/apps"
cp packaging/linux/synchotic.desktop "$APPDIR/usr/share/applications/"
cp packaging/linux/synchotic.png "$APPDIR/usr/share/icons/hicolor/256x256/apps/"

cat > "$APPDIR/AppRun" <<'APPRUN'
#!/bin/sh
# A frozen build writes its data next to the executable, which inside a mounted
# AppImage is a read-only squashfs. Point it somewhere durable that survives
# replacing the file.
HERE="$(dirname "$(readlink -f "$0")")"
export SYNCHOTIC_ROOT="${SYNCHOTIC_ROOT:-$HOME/Synchotic}"
mkdir -p "$SYNCHOTIC_ROOT"

# WezTerm has no size persistence of its own; the config reads this back.
XDG_DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
export SYNCHOTIC_WINDOW_FILE="$XDG_DATA/Synchotic/window.txt"
mkdir -p "$XDG_DATA/Synchotic"

TUI="$HERE/usr/bin/synchotic-tui"

# Started from a terminal: this is a TUI, so just be one. Only a launch with no
# controlling terminal (desktop file, file manager) needs a window built for it.
if [ -t 0 ] && [ -t 1 ]; then
  exec "$TUI" "$@"
fi

# LD_LIBRARY_PATH is set for WezTerm alone. Exporting it would hand the same
# path to the TUI that WezTerm spawns, shadowing the libssl PyInstaller bundled
# for it, which is the failure launcher.py documents in host_environment().
exec env LD_LIBRARY_PATH="$HERE/usr/lib/wezterm${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" \
  "$HERE/usr/bin/wezterm-gui" \
  --config-file "$HERE/usr/share/synchotic/wezterm.lua" \
  start --always-new-process --cwd "$SYNCHOTIC_ROOT" --class synchotic \
  -- "$TUI" "$@"
APPRUN
chmod +x "$APPDIR/AppRun"

# --- pack ---
if [ ! -f "$RUNTIME" ]; then
  echo "==> fetching uruntime $URUNTIME_VER"
  curl -fsSL -o "$RUNTIME" "$URUNTIME_URL"
  chmod +x "$RUNTIME"
fi

APPIMAGETOOL="${APPIMAGETOOL:-build/appimagetool-x86_64.AppImage}"
if [ ! -f "$APPIMAGETOOL" ]; then
  echo "==> fetching appimagetool"
  curl -fsSL -o "$APPIMAGETOOL" \
    "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage"
  chmod +x "$APPIMAGETOOL"
fi

# appimagetool is itself an AppImage, so it needs the same FUSE it cannot count
# on. Tell it to unpack itself instead.
APPIMAGE_EXTRACT_AND_RUN=1 "$APPIMAGETOOL" \
  --runtime-file "$RUNTIME" \
  "$APPDIR" "$OUT"

chmod +x "$OUT"
echo "==> $OUT"
