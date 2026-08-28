#!/usr/bin/env bash
# Build Synchotic-launcher-x86_64.AppImage, the only Linux download.
#
#   packaging/linux/build_launcher_appimage.sh
#
# The launcher used to ship as a bare ELF, which is not something a Linux
# desktop treats as an app: GNOME Files refuses to execute binaries on
# double-click at all, and a downloaded file has no icon and no name beyond
# whatever it was saved as. An AppImage is the format file managers do
# understand, and it carries the .desktop entry and icon with it instead of the
# launcher writing them into ~/.local/share after the first run that worked.
#
# Unlike the standalone AppImage this is still the launcher: it downloads the
# app payload and WezTerm at runtime, so what is packed here is tiny.
#
# uruntime rather than appimagetool's default runtime, for the reason
# build_appimage.sh spells out: a stock AppImage self-mounts through libfuse2,
# which the atomic Fedora spins (Bazzite, Kinoite) and Ubuntu 26.04 do not
# ship. uruntime falls back to extracting itself.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

PY="${PYTHON:-.venv/bin/python}"
OUT="dist/Synchotic-launcher-x86_64.AppImage"
APPDIR="build/launcher-appimage/Synchotic.AppDir"

URUNTIME_VER="${URUNTIME_VERSION:-v0.6.1}"
URUNTIME_URL="https://github.com/VHSgunzo/uruntime/releases/download/$URUNTIME_VER/uruntime-appimage-squashfs-lite-x86_64"
RUNTIME="build/uruntime-$URUNTIME_VER-x86_64"

echo "==> building launcher AppImage"
rm -rf "$APPDIR" build/launcher-appimage/pyinstaller
mkdir -p "$APPDIR/usr/bin" dist build

CERT="$("$PY" -c 'import certifi; print(certifi.where())')"
"$PY" -m PyInstaller --onedir --name synchotic-launcher --clean --noconfirm \
  --distpath build/launcher-appimage/pyinstaller \
  --workpath build/launcher-appimage/work \
  --add-data "${CERT}:certifi" \
  --add-data "packaging/macos/wezterm.lua:." \
  --add-data "packaging/linux/synchotic.png:." \
  --hidden-import certifi \
  launcher.py >/dev/null

cp -a build/launcher-appimage/pyinstaller/synchotic-launcher/. "$APPDIR/usr/bin/"

# appimagetool wants both of these at the AppDir root.
cp packaging/linux/synchotic.desktop "$APPDIR/synchotic.desktop"
cp packaging/linux/synchotic.png "$APPDIR/synchotic.png"
mkdir -p "$APPDIR/usr/share/applications" "$APPDIR/usr/share/icons/hicolor/256x256/apps"
cp packaging/linux/synchotic.desktop "$APPDIR/usr/share/applications/"
cp packaging/linux/synchotic.png "$APPDIR/usr/share/icons/hicolor/256x256/apps/"

cat > "$APPDIR/AppRun" <<'APPRUN'
#!/bin/sh
# Nothing is written beside the AppImage: it belongs in the app menu, not in a
# chart folder, and inside one sys.executable points into a squashfs mount that
# is unmounted on exit. The launcher sees $APPIMAGE, puts its payload in the
# XDG data dir and hands the app SYNCHOTIC_OS_DIRS, so config, cache and state
# land where a Linux desktop expects them.
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/bin/synchotic-launcher" "$@"
APPRUN
chmod +x "$APPDIR/AppRun"

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
