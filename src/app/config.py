"""Shared app-level config that both sync.py and its mixins need."""

import os
import sys
from pathlib import Path


def _checkout_key() -> str:
    """GOOGLE_API_KEY from the checkout's .env. CI bakes the key into release
    builds; a run from source otherwise scans with none, and Google refuses a
    keyless scan outright, so rclone and no-sign-in modes list nothing."""
    if getattr(sys, "frozen", False):
        return ""
    try:
        lines = (Path(__file__).resolve().parents[2] / ".env").read_text().splitlines()
    except OSError:
        return ""
    for line in lines:
        name, _, value = line.partition("=")
        if name.strip() == "GOOGLE_API_KEY":
            return value.strip().strip("\"'")
    return ""


API_KEY = os.environ.get("GOOGLE_API_KEY", "") or _checkout_key()
