"""Tests for download cancellation behavior."""

import asyncio
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.sync.downloader import FileDownloader, DownloadTask

# EscMonitor can't access stdin during pytest (it's captured), which is fine
# since we use cancel_check for programmatic cancellation in tests
pytestmark = pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")


class TestCancelCheck:
    """Tests for programmatic cancellation via cancel_check callback."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def mock_tasks(self, temp_dir):
        """Create mock download tasks."""
        return [
            DownloadTask(
                file_id=f"id_{i}",
                local_path=temp_dir / f"file_{i}.txt",
                size=1000,
                md5=f"md5_{i}",
                rel_path=f"Drive/folder/file_{i}.txt",
                is_archive=False,
            )
            for i in range(10)
        ]

    def test_cancel_check_stops_downloads(self, mock_tasks):
        """cancel_check=True should stop downloads promptly."""
        downloader = FileDownloader(max_workers=4)
        cancel_count = [0]

        def cancel_after_calls():
            cancel_count[0] += 1
            # Cancel after a few checks (simulates ESC pressed mid-download)
            return cancel_count[0] >= 3

        # Mock the async download to simulate slow downloads
        async def slow_download(*args, **kwargs):
            await asyncio.sleep(0.5)  # Simulate download time
            return MagicMock(
                success=True,
                file_path=args[1].local_path,
                message="OK",
                bytes_downloaded=1000,
            )

        with patch.object(downloader, '_download_file_async', side_effect=slow_download):
            downloaded, skipped, errors, rate_limited, cancelled, bytes_dl = downloader.download_many(
                mock_tasks,
                show_progress=False,
                cancel_check=cancel_after_calls,
            )

        # Should have cancelled before completing all downloads
        assert cancelled, "download_many should report cancelled=True"
        assert downloaded < len(mock_tasks), f"Should not complete all {len(mock_tasks)} downloads"

    def test_cancel_check_not_called_when_fast(self, mock_tasks):
        """Fast downloads should complete without cancellation."""
        downloader = FileDownloader(max_workers=4)

        # Cancel check always returns False
        def never_cancel():
            return False

        # Mock fast downloads
        async def fast_download(*args, **kwargs):
            return MagicMock(
                success=True,
                file_path=args[1].local_path,
                message="OK",
                bytes_downloaded=1000,
            )

        with patch.object(downloader, '_download_file_async', side_effect=fast_download):
            downloaded, skipped, errors, rate_limited, cancelled, bytes_dl = downloader.download_many(
                mock_tasks,
                show_progress=False,
                cancel_check=never_cancel,
            )

        assert not cancelled, "Should not be cancelled"
        assert downloaded == len(mock_tasks), "Should complete all downloads"

class TestCancelResponsiveness:
    """Test that cancellation is reasonably responsive."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_cancel_within_reasonable_time(self, temp_dir):
        """Cancellation should happen within ~500ms of cancel_check returning True."""
        tasks = [
            DownloadTask(
                file_id=f"id_{i}",
                local_path=temp_dir / f"file_{i}.txt",
                size=1000000,  # 1MB each
                md5=f"md5_{i}",
                rel_path=f"Drive/folder/file_{i}.txt",
                is_archive=False,
            )
            for i in range(20)
        ]

        downloader = FileDownloader(max_workers=8)
        cancel_time = [None]
        return_time = [None]

        def cancel_after_delay():
            if cancel_time[0] is None:
                # First call - start timer, don't cancel yet
                cancel_time[0] = time.time() + 0.2  # Cancel in 200ms
                return False
            if time.time() >= cancel_time[0]:
                if return_time[0] is None:
                    return_time[0] = time.time()
                return True
            return False

        async def slow_download(*args, **kwargs):
            # Each download takes 2 seconds
            await asyncio.sleep(2.0)
            return MagicMock(success=True, file_path=args[1].local_path, message="OK", bytes_downloaded=1000)

        with patch.object(downloader, '_download_file_async', side_effect=slow_download):
            start = time.time()
            downloaded, skipped, errors, rate_limited, cancelled, bytes_dl = downloader.download_many(
                tasks,
                show_progress=False,
                cancel_check=cancel_after_delay,
            )
            elapsed = time.time() - start

        assert cancelled, "Should be cancelled"
        # Should cancel within 500ms of the cancel_check returning True
        # (100ms poll interval + some overhead)
        assert elapsed < 1.0, f"Cancellation took too long: {elapsed:.2f}s"
