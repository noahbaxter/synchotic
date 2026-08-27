"""Synchotic's palette.

chotic-ui owns the colour values; this picks the one Synchotic wears.

nova-rose is magenta throughout -- pink keys, hot-magenta cursor, deep-rose
frame -- under the magenta-to-gold wordmark ramp the whole family shares. It is
a single hue beside its neutral, which is what the earlier attempts got wrong:
a plum frame, an orange cursor and an amber key all arguing at once.

The frame is the darkest value in the set on purpose. BORDER paints every box
edge, and at full saturation the furniture outshouts the cursor it exists to sit
behind -- which is exactly how 1.4's near-pure-red frame read.

Five sibling palettes ship in chotic-ui (nova, nova-gold, nova-ink, nova-coal,
nova-crimson) and are deliberately not offered in the app: a themed identity is
worth more than a preference nobody asked for. SYNCHOTIC_THEME still overrides
the default for one run, e.g. SYNCHOTIC_THEME=nova-ink ./sync.py, which is
enough to compare them.
"""

DEFAULT_THEME = "nova-rose"
