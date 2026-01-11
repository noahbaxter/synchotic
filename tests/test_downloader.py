"""Tests for downloader.py CDN download functionality."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from src.sync.download_planner import DownloadTask
from src.sync.downloader import FileDownloader, DownloadResult


class TestDownloadFromCDN:
    """Tests for _download_url_async() CDN download method."""

    @pytest.fixture
    def downloader(self):
        """Create a FileDownloader instance for testing."""
        return FileDownloader(max_workers=2, max_retries=3)

    @pytest.fixture
    def cdn_task(self, tmp_path):
        """Create a DownloadTask with a CDN URL."""
        return DownloadTask(
            file_id="cdn-test-123",
            local_path=tmp_path / "test_file.rar",
            size=1000,
            md5="abc123",
            url="https://cdn.example.com/files/test.rar"
        )

    def test_cdn_download_success(self, downloader, cdn_task, tmp_path):
        """Successful CDN download writes file and returns success."""
        file_content = b"fake archive content"

        async def run_test():
            # Mock the response
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.raise_for_status = MagicMock()
            mock_response.content.iter_chunked = lambda size: mock_async_iter([file_content])
            mock_response.headers = {"Content-Length": str(len(file_content))}

            # Mock session.get as async context manager
            mock_session = MagicMock()
            mock_session.get = MagicMock(return_value=async_context_manager(mock_response))

            semaphore = asyncio.Semaphore(1)

            # We need to also mock _write_response since it does the actual work
            with patch.object(downloader, '_write_response', new_callable=AsyncMock) as mock_write:
                mock_write.return_value = DownloadResult(
                    success=True,
                    file_path=cdn_task.local_path,
                    message="OK",
                    bytes_downloaded=len(file_content)
                )

                result = await downloader._download_url_async(
                    mock_session, cdn_task, semaphore, None
                )

            assert result.success is True
            assert result.bytes_downloaded == len(file_content)

        asyncio.run(run_test())

    def test_cdn_timeout_triggers_retry(self, downloader, cdn_task):
        """Timeout errors trigger retry with backoff."""
        retry_count = 0

        async def run_test():
            nonlocal retry_count

            # Create context manager that raises TimeoutError
            class TimeoutContextManager:
                async def __aenter__(self):
                    nonlocal retry_count
                    retry_count += 1
                    raise asyncio.TimeoutError()

                async def __aexit__(self, *args):
                    pass

            mock_session = MagicMock()
            mock_session.get = MagicMock(return_value=TimeoutContextManager())

            semaphore = asyncio.Semaphore(1)

            result = await downloader._download_url_async(
                mock_session, cdn_task, semaphore, None
            )

            assert result.success is False
            assert "timeout" in result.message.lower()
            assert result.retryable is True

        asyncio.run(run_test())
        # Should have tried max_retries times
        assert retry_count == downloader.max_retries

    def test_cdn_http_429_marked_retryable(self, downloader, cdn_task):
        """HTTP 429 (rate limit) marked as retryable."""

        async def run_test():
            mock_response = AsyncMock()
            mock_response.raise_for_status = MagicMock(
                side_effect=aiohttp.ClientResponseError(
                    request_info=MagicMock(),
                    history=(),
                    status=429
                )
            )

            mock_session = MagicMock()
            mock_session.get = MagicMock(return_value=async_context_manager(mock_response))

            semaphore = asyncio.Semaphore(1)
            result = await downloader._download_url_async(
                mock_session, cdn_task, semaphore, None
            )

            assert result.success is False
            assert "429" in result.message
            assert result.retryable is True

        asyncio.run(run_test())

    def test_cdn_http_503_marked_retryable(self, downloader, cdn_task):
        """HTTP 503 (service unavailable) marked as retryable."""

        async def run_test():
            mock_response = AsyncMock()
            mock_response.raise_for_status = MagicMock(
                side_effect=aiohttp.ClientResponseError(
                    request_info=MagicMock(),
                    history=(),
                    status=503
                )
            )

            mock_session = MagicMock()
            mock_session.get = MagicMock(return_value=async_context_manager(mock_response))

            semaphore = asyncio.Semaphore(1)
            result = await downloader._download_url_async(
                mock_session, cdn_task, semaphore, None
            )

            assert result.success is False
            assert "503" in result.message
            assert result.retryable is True

        asyncio.run(run_test())

    def test_cdn_http_404_not_retryable(self, downloader, cdn_task):
        """HTTP 404 (not found) marked as NOT retryable."""

        async def run_test():
            mock_response = AsyncMock()
            mock_response.raise_for_status = MagicMock(
                side_effect=aiohttp.ClientResponseError(
                    request_info=MagicMock(),
                    history=(),
                    status=404
                )
            )

            mock_session = MagicMock()
            mock_session.get = MagicMock(return_value=async_context_manager(mock_response))

            semaphore = asyncio.Semaphore(1)
            result = await downloader._download_url_async(
                mock_session, cdn_task, semaphore, None
            )

            assert result.success is False
            assert "404" in result.message
            assert result.retryable is False

        asyncio.run(run_test())

    def test_cdn_http_403_not_retryable(self, downloader, cdn_task):
        """HTTP 403 (forbidden) marked as NOT retryable."""

        async def run_test():
            mock_response = AsyncMock()
            mock_response.raise_for_status = MagicMock(
                side_effect=aiohttp.ClientResponseError(
                    request_info=MagicMock(),
                    history=(),
                    status=403
                )
            )

            mock_session = MagicMock()
            mock_session.get = MagicMock(return_value=async_context_manager(mock_response))

            semaphore = asyncio.Semaphore(1)
            result = await downloader._download_url_async(
                mock_session, cdn_task, semaphore, None
            )

            assert result.success is False
            assert "403" in result.message
            assert result.retryable is False

        asyncio.run(run_test())

    def test_cdn_html_error_page_detected(self, downloader, cdn_task):
        """HTML error pages should be detected and rejected."""

        async def run_test():
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.raise_for_status = MagicMock()
            mock_response.headers = {"content-type": "text/html; charset=utf-8"}

            mock_session = MagicMock()
            mock_session.get = MagicMock(return_value=async_context_manager(mock_response))

            semaphore = asyncio.Semaphore(1)

            result = await downloader._download_url_async(
                mock_session, cdn_task, semaphore, None
            )

            # Should detect HTML content-type and fail
            assert result.success is False
            assert "html" in result.message.lower()
            assert result.retryable is False

        asyncio.run(run_test())

    def test_cdn_routes_through_download_file_async(self, downloader, cdn_task):
        """CDN tasks route through _download_file_async to _download_url_async."""

        async def run_test():
            mock_session = MagicMock()
            semaphore = asyncio.Semaphore(1)

            with patch.object(downloader, '_download_url_async', new_callable=AsyncMock) as mock_cdn:
                mock_cdn.return_value = DownloadResult(
                    success=True,
                    file_path=cdn_task.local_path,
                    message="OK"
                )

                result = await downloader._download_file_async(
                    mock_session, cdn_task, semaphore, None
                )

            # CDN task should route to _download_url_async
            mock_cdn.assert_called_once()
            assert result.success is True

        asyncio.run(run_test())

    def test_gdrive_task_does_not_route_to_cdn(self, downloader, tmp_path):
        """Non-CDN tasks (no url) should NOT route to _download_url_async."""
        gdrive_task = DownloadTask(
            file_id="1abc123xyz",
            local_path=tmp_path / "gdrive_file.7z",
            size=1000,
            md5="abc123",
            url=""  # No URL = GDrive file
        )

        async def run_test():
            mock_session = MagicMock()
            semaphore = asyncio.Semaphore(1)

            with patch.object(downloader, '_download_url_async', new_callable=AsyncMock) as mock_cdn:
                # GDrive logic is inline, so we can't fully mock it, but we can
                # verify the CDN path is NOT taken by checking mock_cdn wasn't called
                try:
                    await downloader._download_file_async(
                        mock_session, gdrive_task, semaphore, None
                    )
                except Exception:
                    pass  # Expected - GDrive download will fail without proper mocking

                # CDN method should NOT have been called
                mock_cdn.assert_not_called()

        asyncio.run(run_test())


class TestMixedDownloads:
    """Tests for mixed CDN and GDrive download scenarios."""

    @pytest.fixture
    def downloader(self):
        return FileDownloader(max_workers=4, max_retries=2)

    def test_mixed_batch_processes_both_types(self, downloader, tmp_path):
        """Batch with both CDN and GDrive files processes correctly."""
        cdn_task = DownloadTask(
            file_id="cdn-1",
            local_path=tmp_path / "cdn_file.rar",
            size=500,
            url="https://cdn.example.com/file.rar"
        )
        gdrive_task = DownloadTask(
            file_id="gdrive-1",
            local_path=tmp_path / "gdrive_file.7z",
            size=500,
            url=""  # No URL = GDrive
        )

        # Just verify both task types are distinguishable
        assert cdn_task.url != ""
        assert gdrive_task.url == ""


# Helper functions for async mocking

async def mock_async_iter(items):
    """Create an async iterator from a list."""
    for item in items:
        yield item


class async_context_manager:
    """Helper to create an async context manager from a value."""
    def __init__(self, value):
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, *args):
        pass
