#!/usr/bin/env python3
"""Render the Synchotic ASCII logo to PNG with sunset gradient."""

from PIL import Image, ImageDraw, ImageFont, ImageFilter
import sys
import os
import random
import math

# Sunset gradient from colors.py
GRADIENT_COLORS = [
    (80, 20, 120),    # Deep purple
    (110, 25, 130),   # Purple
    (150, 25, 120),   # Plum
    (185, 30, 95),    # Magenta-red
    (215, 35, 65),    # Crimson
    (235, 40, 45),    # Red
    (245, 55, 35),    # Scarlet
    (250, 80, 30),    # Red-orange
    (252, 115, 30),   # Dark orange
    (254, 150, 35),   # Orange
    (255, 185, 50),   # Amber
    (255, 215, 75),   # Warm gold
]

TEXTURE_DENSITY = 0.90  # 0.0 = none, 1.0 = every interior space
TEXTURE_DENSITY = 1
TEXTURE_OPACITY = (150, 200)  # (min, max) alpha range, 0-255
DARK_BG = False  # False = transparent, True = layered dark background

LOGO = r"""
                  *************
             *****             *****
          ****                     ****
        ***                           ***
      ***                               ***
     **    ███████╗██╗   ██╗███╗   ██╗    **
    **     ██╔════╝╚██╗ ██╔╝████╗  ██║     **
   **      ███████╗ ╚████╔╝ ██╔██╗ ██║      **
  **       ╚════██║  ╚██╔╝  ██║╚██╗██║       **
  **       ███████║   ██║   ██║ ╚████║       **
 **        ╚══════╝   ╚═╝   ╚═╝  ╚═══╝       **
 **                                           **
 **          ██████╗██╗  ██╗ ██████╗          **
 **         ██╔════╝██║  ██║██╔═══██╗         **
 **         ██║     ███████║██║   ██║         **
 **         ██║     ██╔══██║██║   ██║         **
 **         ╚██████╗██║  ██║╚██████╔╝         **
 **          ╚═════╝╚═╝  ╚═╝ ╚═════╝          **
 **                                           **
  **          ████████╗██╗ ██████╗           **
  **          ╚══██╔══╝██║██╔════╝           **
   **            ██║   ██║██║               **
    **           ██║   ██║██║              **
     **          ██║   ██║╚██████╗        **
      ***        ╚═╝   ╚═╝ ╚═════╝      ***
        ***                           ***
          ****                     ****
             *****             *****
                  *************
""".strip('\n')


def lerp_color(c1, c2, t):
    return (
        int(c1[0] + (c2[0] - c1[0]) * t),
        int(c1[1] + (c2[1] - c1[1]) * t),
        int(c1[2] + (c2[2] - c1[2]) * t),
    )


def get_gradient_color(pos):
    pos = max(0.0, min(1.0, pos))
    scaled = pos * (len(GRADIENT_COLORS) - 1)
    idx = int(scaled)
    if idx >= len(GRADIENT_COLORS) - 1:
        return GRADIENT_COLORS[-1]
    return lerp_color(GRADIENT_COLORS[idx], GRADIENT_COLORS[idx + 1], scaled - idx)


def render(output_path="synchotic_logo.png", scale=2):
    # Find a monospace font
    font_candidates = [
        ("/System/Library/Fonts/Menlo.ttc", 0),
        "/System/Library/Fonts/SFMono-Regular.otf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/usr/share/fonts/TTF/DejaVuSansMono.ttf",
    ]

    font_size = 14 * scale
    font = None
    for entry in font_candidates:
        if isinstance(entry, tuple):
            path, index = entry
        else:
            path, index = entry, 0
        if os.path.exists(path):
            try:
                font = ImageFont.truetype(path, font_size, index=index)
                break
            except Exception:
                continue

    if font is None:
        font = ImageFont.load_default()
        print("Warning: no monospace font found, using default")

    lines = LOGO.split('\n')
    total_rows = len(lines)

    # Measure character size
    bbox = font.getbbox("█")
    char_w = bbox[2] - bbox[0]
    char_h = int((bbox[3] - bbox[1]) * 1.15)

    max_cols = max(len(line) for line in lines)
    padding = 40 * scale

    img_w = max_cols * char_w + padding * 2
    img_h = total_rows * char_h + padding * 2

    if DARK_BG:
        # Base layer: dark background
        img = Image.new("RGBA", (img_w, img_h), (30, 31, 42, 255))
        draw = ImageDraw.Draw(img)

        # Radial vignette: draw concentric ellipses from light center to dark edge
        cx, cy = img_w // 2, img_h // 2
        bg_center = (60, 62, 84)
        bg_edge = (30, 31, 42)
        steps = 80
        for i in range(steps, 0, -1):
            t = i / steps
            c = lerp_color(bg_edge, bg_center, 1.0 - t)
            rx = int(cx * t * 1.2)
            ry = int(cy * t * 1.2)
            draw.ellipse(
                (cx - rx, cy - ry, cx + rx, cy + ry),
                fill=(c[0], c[1], c[2], 255),
            )

        # Subtle noise layer for texture
        noise = Image.new("RGBA", (img_w, img_h), (0, 0, 0, 0))
        noise_draw = ImageDraw.Draw(noise)
        random.seed(123)
        for _ in range(img_w * img_h // 40):
            nx = random.randint(0, img_w - 1)
            ny = random.randint(0, img_h - 1)
            v = random.randint(20, 45)
            noise_draw.point((nx, ny), fill=(v, v, v, 25))
        noise = noise.filter(ImageFilter.GaussianBlur(radius=1))
        img = Image.alpha_composite(img, noise)
        draw = ImageDraw.Draw(img)
    else:
        img = Image.new("RGBA", (img_w, img_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

    # Build a set of all non-space character positions (the "filled" area)
    filled = set()
    for row, line in enumerate(lines):
        for col, char in enumerate(line):
            if char != ' ':
                filled.add((row, col))

    # Find interior spaces: spaces that are horizontally between filled chars on the same row
    # and vertically between filled chars in the same column
    interior = set()
    for row, line in enumerate(lines):
        for col, char in enumerate(line):
            if char != ' ':
                continue
            # Check if bounded horizontally
            has_left = any((row, c) in filled for c in range(0, col))
            has_right = any((row, c) in filled for c in range(col + 1, max_cols))
            # Check if bounded vertically
            has_above = any((r, col) in filled for r in range(0, row))
            has_below = any((r, col) in filled for r in range(row + 1, total_rows))
            if has_left and has_right and has_above and has_below:
                interior.add((row, col))

    # Scatter texture particles in interior spaces
    random.seed(69)
    texture_chars = ['.', '·', ':', '∙', ',', '\'']
    # texture_chars = ['.', '·', ':', '∙', ',', '\'']

    for row, line in enumerate(lines):
        for col, char in enumerate(line):
            x = padding + col * char_w
            y = padding + row * char_h

            if char != ' ':
                # Regular filled character
                pos = (row / total_rows) * 0.4 + (col / max_cols) * 0.6
                r, g, b = get_gradient_color(pos)
                draw.text((x, y), char, fill=(r, g, b, 255), font=font)
            elif (row, col) in interior and random.random() < TEXTURE_DENSITY:
                # Sparse texture particle
                pos = (row / total_rows) * 0.4 + (col / max_cols) * 0.6
                r, g, b = get_gradient_color(pos)
                alpha = random.randint(*TEXTURE_OPACITY)
                tc = random.choice(texture_chars)
                draw.text((x, y), tc, fill=(r, g, b, alpha), font=font)

    img.save(output_path)
    print(f"Saved {output_path} ({img_w}x{img_h})")


if __name__ == "__main__":
    # --bg renders the backed variant the app icons are cut from; without it the
    # background is transparent, which is what the docs want.
    args = [a for a in sys.argv[1:] if a != "--bg"]
    DARK_BG = "--bg" in sys.argv
    out = args[0] if args else "synchotic_logo.png"
    sc = int(args[1]) if len(args) > 1 else 2
    render(out, sc)
