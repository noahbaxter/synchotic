#!/usr/bin/env python3
"""Derive the platform icon files from the master logo PNG.

Run after render_logo.py. Produces:
  packaging/macos/Synchotic.icns   (iconutil, macOS-only step)
  packaging/windows/synchotic.ico  (multi-resolution)
  packaging/linux/synchotic.png    (256x256)

Needs Pillow, which is a build-time tool and deliberately not in
requirements.txt: it is not imported by anything that ships.
"""

import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
MASTER = HERE / "synchotic_logo.png"


def main():
    master = Image.open(MASTER).convert("RGBA")

    linux = ROOT / "packaging" / "linux" / "synchotic.png"
    linux.parent.mkdir(parents=True, exist_ok=True)
    master.resize((256, 256), Image.LANCZOS).save(linux)

    win = ROOT / "packaging" / "windows" / "synchotic.ico"
    win.parent.mkdir(parents=True, exist_ok=True)
    master.save(win, sizes=[(16, 16), (24, 24), (32, 32), (48, 48),
                            (64, 64), (128, 128), (256, 256)])

    # macOS: feed a fully OPAQUE square (no alpha channel) and let macOS apply its
    # own squircle mask. An icns *with* an alpha channel makes macOS treat it as a
    # custom icon and composite it onto its generic light plate; an opaque one is
    # used directly and masked to the rounded-rect, filling the whole tile.
    icns = ROOT / "packaging" / "macos" / "Synchotic.icns"
    icns.parent.mkdir(parents=True, exist_ok=True)
    if sys.platform == "darwin":
        mac_master = master.convert("RGB")
        specs = [(16, "16x16"), (32, "16x16@2x"), (32, "32x32"), (64, "32x32@2x"),
                 (128, "128x128"), (256, "128x128@2x"), (256, "256x256"),
                 (512, "256x256@2x"), (512, "512x512"), (1024, "512x512@2x")]
        with tempfile.TemporaryDirectory() as tmp:
            iconset = Path(tmp) / "Synchotic.iconset"
            iconset.mkdir()
            for px, name in specs:
                mac_master.resize((px, px), Image.LANCZOS).save(iconset / f"icon_{name}.png")
            subprocess.run(["iconutil", "-c", "icns", "-o", str(icns), str(iconset)],
                           check=True)
    else:
        print("Skipping .icns (iconutil is macOS-only)")

    print(f"Wrote:\n  {linux}\n  {win}\n  {icns if sys.platform == 'darwin' else '(skipped icns)'}")


if __name__ == "__main__":
    main()
