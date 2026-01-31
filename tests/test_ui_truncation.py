"""Tests for UI text truncation and terminal width handling."""

import re
import pytest
from unittest.mock import patch

from src.ui.primitives.terminal import truncate_text, get_terminal_width, get_available_width
from src.ui.widgets.active_downloads import ActiveDownloadsDisplay, ActiveDownload


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
    @patch('src.ui.primitives.terminal.get_terminal_width', return_value=80)
    def test_with_reserved(self, mock_width):
        assert get_available_width(reserved=20) == 60

    @patch('src.ui.primitives.terminal.get_terminal_width', return_value=80)
    def test_respects_min_width(self, mock_width):
        assert get_available_width(reserved=70, min_width=20) == 20

    @patch('src.ui.primitives.terminal.get_terminal_width', return_value=30)
    def test_narrow_terminal(self, mock_width):
        assert get_available_width(reserved=20, min_width=15) == 15


class TestActiveDownloadsRender:
    @patch('src.ui.widgets.active_downloads.get_terminal_width')
    def test_lines_fit_terminal_width(self, mock_width):
        """Rendered lines should not exceed terminal width."""
        mock_width.return_value = 60

        display = ActiveDownloadsDisplay(is_tty=False)
        display.set_aggregate_totals(10, 1024 * 1024 * 100, "Very Long Drive Name That Should Be Truncated")
        display.register("f1", "extremely_long_filename_that_needs_truncation.7z", "Artist/Album", 1024 * 1024 * 50)

        lines = display.render()
        for line in lines:
            clean = re.sub(r'\x1b\[[0-9;]*m', '', line)
            assert len(clean) <= 60, f"Line too long ({len(clean)}): {clean}"

    @patch('src.ui.widgets.active_downloads.get_terminal_width')
    def test_narrow_terminal(self, mock_width):
        """Should handle very narrow terminals gracefully."""
        mock_width.return_value = 40

        display = ActiveDownloadsDisplay(is_tty=False)
        display.set_aggregate_totals(5, 1024 * 1024 * 50, "Drive")
        display.register("f1", "file.7z", "Path", 1024 * 1024)

        lines = display.render()
        assert len(lines) > 0

    def test_empty_state(self):
        """Empty display should return empty list."""
        display = ActiveDownloadsDisplay(is_tty=False)
        assert display.render() == []
