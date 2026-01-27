"""
UI display state tests.

Tests that UI widgets render correctly and handle state properly.
Run with: pytest tests/test_ui_display.py -v
"""

from src.ui.widgets.progress import FolderProgress


class TestProgressFormatting:
    """Test progress tracker formatting."""

    def test_completion_line_format(self):
        progress = FolderProgress(total_files=10, total_folders=1)
        progress.total_charts = 100
        progress.completed_charts = 50

        line = progress._format_completion_line("TestSetlist", "Chart Name Here")
        assert "50.0%" in line
        assert "(50/100)" in line or "( 50/100)" in line
        assert "[TestSetlist]" in line
        assert "Chart Name Here" in line

    def test_error_line_format(self):
        progress = FolderProgress(total_files=10, total_folders=1)

        line = progress._format_error_line("TestSetlist", "ERR: something failed")
        assert "ERR:" in line
        assert "[TestSetlist]" in line

    def test_error_parsing(self):
        progress = FolderProgress(total_files=10, total_folders=1)
        progress._is_tty = False  # Disable TTY operations

        # Test with colon separator
        progress.print_error("Setlist", "ERR (timeout): filename.ogg")
        assert len(progress.errors) == 1
        assert progress.errors[0].reason == "ERR (timeout)"
        assert progress.errors[0].filename == "filename.ogg"

        # Test without colon
        progress.errors.clear()
        progress.print_error("Setlist", "simple error message")
        assert progress.errors[0].reason == "error"
        assert progress.errors[0].filename == "simple error message"


class TestErrorSummary:
    """Test error summary formatting."""

    def test_few_errors_all_shown(self):
        progress = FolderProgress(total_files=10, total_folders=1)
        progress._is_tty = False

        # Add a few errors
        for i in range(5):
            progress._record_error("Setlist", f"file{i}.ogg", "timeout")

        # Capture output
        import io
        import sys
        captured = io.StringIO()
        sys.stdout = captured
        try:
            progress.print_error_summary()
        finally:
            sys.stdout = sys.__stdout__

        output = captured.getvalue()
        assert "Download errors:" in output
        assert "[Setlist]" in output
        assert "5 failed" in output

    def test_many_errors_truncated(self):
        progress = FolderProgress(total_files=100, total_folders=1)
        progress._is_tty = False

        # Add many errors
        for i in range(50):
            progress._record_error("Setlist", f"file{i}.ogg", "timeout")

        import io
        import sys
        captured = io.StringIO()
        sys.stdout = captured
        try:
            progress.print_error_summary()
        finally:
            sys.stdout = sys.__stdout__

        output = captured.getvalue()
        assert "... and" in output  # Should have truncation
