"""Shared app-level config that both sync.py and its mixins need."""

import os


API_KEY = os.environ.get("GOOGLE_API_KEY", "")
