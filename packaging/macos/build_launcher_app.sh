#!/usr/bin/env bash
# Build Synchotic.app around the launcher, not the app itself.
#
#   packaging/macos/build_launcher_app.sh
#
# The launcher is the auto-updating install: a small stub that downloads
# app-macos.zip beside itself and runs it. It has always shipped on macOS as a
# bare Mach-O binary, and that shape cannot work. launcher.py's host_paths()
# looks for wezterm-gui next to sys.executable and wezterm.lua in
# ../Resources, which are bundle paths, so a loose binary never finds a
# terminal host and a double-click lands in whatever Terminal.app gives it.
# There is no ensure_wezterm_macos() to fall back on either; Windows and Linux
# download WezTerm at runtime, macOS was meant to carry it.
#
# get_launcher_dir() already walks up to the .app and returns the folder
# containing it, so the downloaded payload lands beside the bundle rather than
# inside it, where it would break the signature and vanish on every update.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
source packaging/macos/sign.sh
APP="dist/Synchotic.app"
PY="${PYTHON:-.venv/bin/python}"
CERT="$("$PY" -c 'import certifi; print(certifi.where())')"
WEZ_VER="20240203-110809-5046fc22"
WEZ_URL="https://github.com/wezterm/wezterm/releases/download/$WEZ_VER/WezTerm-macos-$WEZ_VER.zip"
WEZ_CACHE="build/wezterm-$WEZ_VER"

# onedir, matching the app bundle. PyInstaller deprecated onefile inside a .app
# ("clashes with macOS's security", an error from v7 on) and it is the wrong
# shape here anyway: onefile unpacks to a temp dir at every launch, which the
# hardened runtime a notarized build needs is entitled to refuse.
# sys.executable stays Contents/MacOS/Synchotic either way, which is what
# host_paths() and get_launcher_dir() read.
rm -rf build/synchotic-launcher "$APP"
"$PY" -m PyInstaller --windowed --onedir --name Synchotic --clean --noconfirm \
  --workpath build/synchotic-launcher \
  --add-data "${CERT}:certifi" \
  --hidden-import certifi \
  --icon=packaging/macos/Synchotic.icns \
  --osx-bundle-identifier dev.noahbaxter.synchotic.launcher \
  launcher.py >/dev/null

MACOS="$APP/Contents/MacOS"

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

# No shim here, unlike the app bundle. The launcher is its own entry point: a
# Finder launch has no controlling terminal, so maybe_relaunch_in_host() sees
# the wezterm-gui now sitting beside it and re-execs into a window itself.
sign_bundle "$APP"

echo "built $APP"
