"""
Shared color definitions for terminal output.
"""


# -- Theme definitions --
# Each theme: (accent_colors_dict, gradient_list)

_THEME_ORDER = ["gemini", "flame", "ocean", "synthwave", "forest", "frost", "sunset", "mono"]

_THEME_ACCENTS = {
    "gemini": {
        "PURPLE": (138, 43, 226),
        "INDIGO": (99, 102, 241),
        "PINK": (244, 114, 182),
        "PINK_DIM": (150, 70, 110),
        "HOTKEY": (167, 139, 250),
    },
    "flame": {
        "PURPLE": (200, 45, 10),
        "INDIGO": (240, 90, 15),
        "PINK": (252, 130, 20),
        "PINK_DIM": (140, 60, 15),
        "HOTKEY": (255, 175, 45),
    },
    "ocean": {
        "PURPLE": (20, 60, 155),
        "INDIGO": (30, 150, 215),
        "PINK": (80, 220, 235),
        "PINK_DIM": (20, 90, 120),
        "HOTKEY": (110, 230, 235),
    },
    "synthwave": {
        "PURPLE": (130, 20, 170),
        "INDIGO": (210, 30, 160),
        "PINK": (245, 75, 110),
        "PINK_DIM": (90, 20, 100),
        "HOTKEY": (200, 150, 210),
    },
    "forest": {
        "PURPLE": (20, 110, 35),
        "INDIGO": (40, 178, 60),
        "PINK": (100, 222, 115),
        "PINK_DIM": (20, 80, 30),
        "HOTKEY": (130, 232, 140),
    },
    "frost": {
        "PURPLE": (90, 125, 180),
        "INDIGO": (150, 195, 228),
        "PINK": (208, 232, 248),
        "PINK_DIM": (60, 80, 120),
        "HOTKEY": (190, 222, 244),
    },
    "sunset": {
        "PURPLE": (150, 25, 120),
        "INDIGO": (235, 40, 45),
        "PINK": (250, 80, 30),
        "PINK_DIM": (90, 25, 80),
        "HOTKEY": (255, 185, 50),
    },
    "mono": {
        "PURPLE": (130, 135, 140),
        "INDIGO": (165, 170, 175),
        "PINK": (210, 214, 218),
        "PINK_DIM": (80, 85, 90),
        "HOTKEY": (225, 228, 231),
    },
}

_THEME_GRADIENTS = {
    "gemini": [
        (138, 43, 226),   # Blue-violet
        (123, 44, 191),   # Purple
        (108, 45, 156),   # Deep purple
        (93, 63, 211),    # Slate blue
        (79, 70, 229),    # Indigo
        (99, 102, 241),   # Light indigo
        (129, 140, 248),  # Periwinkle
        (167, 139, 250),  # Light purple
        (196, 118, 232),  # Orchid
        (232, 121, 197),  # Pink
        (244, 114, 182),  # Hot pink
        (251, 113, 133),  # Rose
    ],
    "flame": [
        (120, 10, 5),     # Deep maroon
        (155, 20, 8),     # Dark crimson
        (190, 30, 8),     # Crimson
        (215, 45, 8),     # Blood red
        (230, 60, 10),    # Red
        (240, 80, 12),    # Red-orange
        (248, 105, 15),   # Dark orange
        (252, 130, 20),   # Orange
        (254, 155, 30),   # Warm orange
        (255, 175, 45),   # Amber
        (255, 195, 65),   # Golden amber
        (255, 210, 90),   # Warm gold
    ],
    "ocean": [
        (10, 20, 80),     # Deep navy
        (15, 40, 120),    # Dark blue
        (20, 60, 155),    # Blue
        (20, 85, 180),    # Medium blue
        (25, 115, 200),   # Steel blue
        (30, 150, 215),   # Sky blue
        (40, 180, 225),   # Light blue
        (55, 205, 230),   # Cyan
        (80, 220, 235),   # Light cyan
        (110, 230, 235),  # Seafoam
        (150, 240, 238),  # Pale seafoam
        (190, 248, 242),  # Mint
    ],
    "synthwave": [
        (60, 10, 120),    # Deep purple
        (90, 15, 150),    # Purple
        (130, 20, 170),   # Violet
        (170, 25, 175),   # Magenta
        (210, 30, 160),   # Hot magenta
        (235, 50, 130),   # Pink
        (245, 75, 110),   # Salmon
        (250, 100, 120),  # Rose
        (240, 130, 160),  # Light rose
        (200, 150, 210),  # Lavender
        (140, 170, 240),  # Periwinkle
        (90, 200, 250),   # Electric blue
    ],
    "forest": [
        (10, 60, 20),     # Dark forest
        (15, 85, 30),     # Forest green
        (20, 110, 35),    # Green
        (25, 135, 40),    # Medium green
        (30, 158, 50),    # Kelly green
        (40, 178, 60),    # Bright green
        (55, 195, 75),    # Light green
        (75, 210, 95),    # Lime green
        (100, 222, 115),  # Spring green
        (130, 232, 140),  # Mint green
        (165, 242, 170),  # Pale green
        (200, 250, 200),  # Honeydew
    ],
    "frost": [
        (60, 80, 120),    # Steel
        (75, 100, 150),   # Slate blue
        (90, 125, 180),   # Medium slate
        (110, 150, 200),  # Light slate
        (130, 175, 215),  # Sky
        (150, 195, 228),  # Pale blue
        (170, 210, 238),  # Ice blue
        (190, 222, 244),  # Light ice
        (208, 232, 248),  # Frost
        (222, 240, 252),  # Near white blue
        (235, 246, 254),  # Faint blue
        (245, 250, 255),  # Ghost white
    ],
    "sunset": [
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
    ],
    "mono": [
        (70, 75, 80),     # Dark gray
        (90, 95, 100),    # Gray
        (110, 115, 120),  # Medium gray
        (130, 135, 140),  # Silver-gray
        (148, 153, 158),  # Silver
        (165, 170, 175),  # Light silver
        (180, 185, 190),  # Pale silver
        (195, 200, 205),  # Light gray
        (210, 214, 218),  # Near white
        (225, 228, 231),  # Faint gray
        (238, 240, 242),  # Ghost gray
        (248, 249, 250),  # Almost white
    ],
}


# -- Active theme state --

THEME_SWITCHER_ENABLED = False

_active_theme_idx = _THEME_ORDER.index("sunset")

GRADIENT_COLORS = list(_THEME_GRADIENTS[_THEME_ORDER[_active_theme_idx]])


def _esc(r, g, b):
    return f"\x1b[38;2;{r};{g};{b}m"


class Colors:
    RESET = "\x1b[0m"
    BOLD = "\x1b[1m"
    DIM = "\x1b[2m"
    ITALIC = "\x1b[3m"
    DIM_HOVER = "\x1b[38;2;140;150;160m"
    MUTED = "\x1b[38;2;148;163;184m"
    MUTED_DIM = "\x1b[38;2;90;100;110m"
    STALE = "\x1b[38;2;100;110;125m"
    RED = "\x1b[38;2;239;68;68m"
    GREEN = "\x1b[38;2;34;197;94m"
    CYAN = "\x1b[38;2;34;211;238m"
    CYAN_DIM = "\x1b[38;2;20;110;130m"
    # Theme-dependent (set by _apply_theme)
    PURPLE = ""
    INDIGO = ""
    PINK = ""
    PINK_DIM = ""
    HOTKEY = ""


def _apply_theme():
    """Apply the current theme to Colors class and GRADIENT_COLORS list."""
    name = _THEME_ORDER[_active_theme_idx]
    accents = _THEME_ACCENTS[name]
    for attr, (r, g, b) in accents.items():
        setattr(Colors, attr, _esc(r, g, b))
    GRADIENT_COLORS.clear()
    GRADIENT_COLORS.extend(_THEME_GRADIENTS[name])


_apply_theme()


def get_theme_name() -> str:
    return _THEME_ORDER[_active_theme_idx]


def cycle_theme() -> str:
    """Advance to next theme. Returns the new theme name."""
    global _active_theme_idx
    _active_theme_idx = (_active_theme_idx + 1) % len(_THEME_ORDER)
    _apply_theme()
    return get_theme_name()


def rgb(r: int, g: int, b: int) -> str:
    return f"\x1b[38;2;{r};{g};{b}m"


def lerp_color(c1: tuple, c2: tuple, t: float) -> tuple:
    return (
        int(c1[0] + (c2[0] - c1[0]) * t),
        int(c1[1] + (c2[1] - c1[1]) * t),
        int(c1[2] + (c2[2] - c1[2]) * t),
    )


def get_gradient_color(pos: float) -> tuple:
    """Get interpolated color at position 0.0-1.0."""
    pos = max(0.0, min(1.0, pos))
    scaled = pos * (len(GRADIENT_COLORS) - 1)
    idx = int(scaled)
    if idx >= len(GRADIENT_COLORS) - 1:
        return GRADIENT_COLORS[-1]
    return lerp_color(GRADIENT_COLORS[idx], GRADIENT_COLORS[idx + 1], scaled - idx)
