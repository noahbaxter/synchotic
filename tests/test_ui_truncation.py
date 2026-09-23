"""Tests for UI text truncation and terminal width handling.

The pinned active-downloads block these used to cover is gone; the sync screen
draws those rows now, and tests/ui pins their widths against real chart names.
"""

from unittest.mock import patch

from src.ui.primitives.terminal import truncate_text, get_available_width


class TestTruncateText:
    def test_no_truncation_needed(self):
        assert truncate_text("short", 10) == "short"

    def test_exact_length(self):
        assert truncate_text("12345", 5) == "12345"

    def test_truncates_with_suffix(self):
        assert truncate_text("hello world", 8) == "hello..."

    def test_custom_suffix(self):
        assert truncate_text("hello world", 8, "~") == "hello w~"

    def test_very_short_max_len(self):
        assert truncate_text("hello", 2) == "he"

    def test_max_len_equals_suffix(self):
        assert truncate_text("hello", 3) == "hel"


class TestGetAvailableWidth:
    # src.ui.primitives.terminal is a re-export shim now, so patching it does not
    # reach the module-local lookup inside get_available_width. Patch the source.
    @patch('chotic_ui.primitives.terminal.get_terminal_width', return_value=80)
    def test_with_reserved(self, mock_width):
        assert get_available_width(reserved=20) == 60

    @patch('chotic_ui.primitives.terminal.get_terminal_width', return_value=80)
    def test_respects_min_width(self, mock_width):
        assert get_available_width(reserved=70, min_width=20) == 20

    @patch('chotic_ui.primitives.terminal.get_terminal_width', return_value=30)
    def test_narrow_terminal(self, mock_width):
        assert get_available_width(reserved=20, min_width=15) == 15
