#!/usr/bin/env bash
# Build Synchotic.app.
#
#   packaging/macos/build_app.sh
#
# PyInstaller has to lay the bundle out itself: its bootloader detects
# .app/Contents/MacOS and then looks for Contents/Frameworks, so a onedir build
# copied into a hand-made bundle fails with "Failed to load Python shared
# library". Hence --windowed rather than wrapping the onedir output.
#
# --windowed also means a Finder launch has no controlling terminal, and this is
# a TUI. CFBundleExecutable is therefore a shim that hands the real binary to a
# bundled WezTerm, so the app owns its window size and colors instead of
# borrowing whatever Terminal.app happens to be configured with.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
APP="dist/Synchotic.app"
PY="${PYTHON:-.venv/bin/python}"
CERT="$("$PY" -c 'import certifi; print(certifi.where())')"
WEZ_VER="20240203-110809-5046fc22"
WEZ_URL="https://github.com/wezterm/wezterm/releases/download/$WEZ_VER/WezTerm-macos-$WEZ_VER.zip"
WEZ_CACHE="build/wezterm-$WEZ_VER"

rm -rf build/synchotic "$APP"
"$PY" -m PyInstaller --windowed --onedir --name Synchotic --clean --noconfirm \
  --workpath build/synchotic \
  --paths vendor/chotic-ui --collect-submodules chotic_ui \
  --add-data="drives.json:." \
  --add-data="src/drive/byoc_setup_instructions.txt:src/drive" \
  --add-data="VERSION:." \
  --add-data="${CERT}:certifi" \
  --icon=packaging/macos/Synchotic.icns \
  --osx-bundle-identifier dev.noahbaxter.synchotic \
  sync.py >/dev/null

MACOS="$APP/Contents/MacOS"
mv "$MACOS/Synchotic" "$MACOS/synchotic-tui"

# wezterm-gui is self-contained; the wezterm CLI and mux server are only needed
# for multiplexing, which this app never does. Skipping them keeps ~125MB out
# of the bundle.
if [ ! -d "$WEZ_CACHE" ]; then
  echo "fetching WezTerm $WEZ_VER"
  mkdir -p "$WEZ_CACHE"
  curl -fsSL -o "$WEZ_CACHE/wezterm.zip" "$WEZ_URL"
  ( cd "$WEZ_CACHE" && unzip -q wezterm.zip )
fi
cp "$WEZ_CACHE/WezTerm-macos-$WEZ_VER/WezTerm.app/Contents/MacOS/wezterm-gui" "$MACOS/"
cp packaging/macos/wezterm.lua packaging/macos/WezTerm-LICENSE.txt "$APP/Contents/Resources/"

# TCC files a permission grant against the app's bundle identity. wezterm-gui is
# the process that actually touches the library, and without these it checks in
# as an anonymous binary, so the grant never attaches to Synchotic and the
# network volume prompt returns on every launch no matter how often it is
# accepted. The usage string is what that prompt reads.
PLIST="$APP/Contents/Info.plist"
plutil -replace LSAllowOtherExecutablesToCheckIn -bool true "$PLIST"
plutil -replace NSNetworkVolumesUsageDescription -string \
  "Synchotic reads and writes your chart library, which can live on a network volume." "$PLIST"

# A frozen build puts its data next to the executable, which inside a bundle in
# /Applications means writing settings, markers and the chart library into the
# app itself. Point it somewhere durable that survives replacing the app.
cat > "$MACOS/Synchotic" <<'SHIM'
#!/bin/bash
DIR="$(cd "$(dirname "$0")" && pwd)"
export SYNCHOTIC_ROOT="$HOME/Synchotic"
mkdir -p "$SYNCHOTIC_ROOT"
exec "$DIR/wezterm-gui" \
  --config-file "$DIR/../Resources/wezterm.lua" \
  start --always-new-process --cwd "$SYNCHOTIC_ROOT" \
  -- "$DIR/synchotic-tui"
SHIM
chmod +x "$MACOS/Synchotic"

# PyInstaller signed the bundle before the shim and WezTerm existed, so re-sign
# the whole thing.
codesign --force --deep --sign - "$APP"

echo "built $APP"
