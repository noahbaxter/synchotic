"""
Google Drive API client for DM Chart Sync.

Handles all HTTP interactions with the Google Drive API.
"""

import time
import re
import json
import requests
from typing import Optional
from dataclasses import dataclass
from urllib.parse import urlencode


@dataclass
class DriveClientConfig:
    """Configuration for DriveClient."""
    api_key: str
    timeout: int = 60
    max_retries: int = 3
    max_qps: float = 100  # queries per second limit (0 = unlimited)


class DriveClient:
    """
    Google Drive API client.

    Handles listing folders, getting file metadata, and API authentication.
    Does NOT handle downloads (see FileDownloader for that).
    """

    API_BASE = "https://www.googleapis.com/drive/v3"
    API_FILES = f"{API_BASE}/files"
    API_CHANGES = f"{API_BASE}/changes"

    def __init__(self, config: DriveClientConfig, auth_token: Optional[str] = None):
        """
        Initialize the Drive client.

        Args:
            config: Client configuration
            auth_token: Optional OAuth token (for Changes API)
        """
        self.config = config
        self.auth_token = auth_token
        self._api_calls = 0
        self._last_request_time = 0.0
        self._min_request_interval = 1.0 / config.max_qps if config.max_qps > 0 else 0

    @property
    def api_calls(self) -> int:
        """Total API calls made by this client."""
        return self._api_calls

    def reset_api_calls(self):
        """Reset the API call counter."""
        self._api_calls = 0

    def _get_headers(self) -> dict:
        """Get request headers."""
        if self.auth_token:
            return {"Authorization": f"Bearer {self.auth_token}"}
        return {}

    def _get_params(self, **kwargs) -> dict:
        """Build request params with API key."""
        params = {"key": self.config.api_key, **kwargs}
        return params

    def _wait_for_rate_limit(self):
        """Wait if necessary to respect rate limit."""
        if self._min_request_interval <= 0:
            return
        elapsed = time.time() - self._last_request_time
        if elapsed < self._min_request_interval:
            time.sleep(self._min_request_interval - elapsed)
        self._last_request_time = time.time()

    def _request_with_retry(self, method: str, url: str, **kwargs) -> requests.Response:
        """Make a request with retry logic."""
        timeout = kwargs.pop("timeout", self.config.timeout)

        for attempt in range(self.config.max_retries):
            try:
                self._wait_for_rate_limit()
                response = requests.request(method, url, timeout=timeout, **kwargs)
                self._api_calls += 1
                response.raise_for_status()
                return response
            except requests.exceptions.Timeout:
                if attempt < self.config.max_retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                raise
            except requests.exceptions.HTTPError:
                if attempt < self.config.max_retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                raise

        raise RuntimeError(f"Request failed after {self.config.max_retries} attempts")

    def list_folder(self, folder_id: str) -> list:
        """
        List all files and folders in a Google Drive folder.

        Handles pagination and includes shortcut details for linked folders.

        Args:
            folder_id: Google Drive folder ID

        Returns:
            List of file/folder metadata dicts
        """
        all_items = []
        page_token = None

        while True:
            params = self._get_params(
                q=f"'{folder_id}' in parents and trashed = false",
                fields="nextPageToken, files(id, name, mimeType, size, md5Checksum, modifiedTime, shortcutDetails)",
                pageSize=1000,
                supportsAllDrives="true",
                includeItemsFromAllDrives="true",
            )

            if page_token:
                params["pageToken"] = page_token

            try:
                response = self._request_with_retry(
                    "GET", self.API_FILES,
                    params=params,
                    headers=self._get_headers()
                )
                data = response.json()
            except requests.exceptions.HTTPError as e:
                if hasattr(e, 'response') and e.response.status_code == 403:
                    return []  # Access denied
                raise

            all_items.extend(data.get("files", []))
            page_token = data.get("nextPageToken")

            if not page_token:
                break

        return all_items

    def get_file_metadata(self, file_id: str, fields: str = "id,name,parents") -> Optional[dict]:
        """
        Get metadata for a single file.

        Args:
            file_id: Google Drive file ID
            fields: Comma-separated list of fields to return

        Returns:
            File metadata dict or None if not found
        """
        params = self._get_params(
            fields=fields,
            supportsAllDrives="true",
        )

        try:
            response = self._request_with_retry(
                "GET", f"{self.API_FILES}/{file_id}",
                params=params,
                headers=self._get_headers()
            )
            return response.json()
        except requests.exceptions.HTTPError:
            return None

    def get_changes_start_token(self) -> str:
        """
        Get the starting page token for the Changes API.

        Requires OAuth authentication.

        Returns:
            Start page token string
        """
        if not self.auth_token:
            raise RuntimeError("OAuth token required for Changes API")

        params = {"supportsAllDrives": "true"}
        response = self._request_with_retry(
            "GET", f"{self.API_CHANGES}/startPageToken",
            params=params,
            headers=self._get_headers()
        )
        self._api_calls += 1
        return response.json().get("startPageToken")

    def get_changes(self, page_token: str) -> tuple:
        """
        Get changes since the given page token.

        Requires OAuth authentication.

        Args:
            page_token: Page token from previous call or getStartPageToken

        Returns:
            Tuple of (changes_list, new_page_token)
        """
        if not self.auth_token:
            raise RuntimeError("OAuth token required for Changes API")

        all_changes = []
        current_token = page_token

        while True:
            params = {
                "pageToken": current_token,
                "pageSize": 1000,
                "fields": "nextPageToken, newStartPageToken, changes(fileId, removed, file(id, name, mimeType, size, md5Checksum, modifiedTime, parents, trashed))",
                "supportsAllDrives": "true",
                "includeItemsFromAllDrives": "true",
            }

            response = self._request_with_retry(
                "GET", self.API_CHANGES,
                params=params,
                headers=self._get_headers()
            )
            data = response.json()

            all_changes.extend(data.get("changes", []))

            if "newStartPageToken" in data:
                return all_changes, data["newStartPageToken"]

            current_token = data.get("nextPageToken")
            if not current_token:
                break

        return all_changes, current_token

    def list_folders_batch(self, folder_ids: list[str], batch_size: int = 100) -> dict[str, list]:
        """
        List contents of multiple folders in batched API calls.

        Uses Google's batch API to combine up to 100 requests per HTTP call,
        dramatically reducing network overhead for large folder scans.

        Args:
            folder_ids: List of Google Drive folder IDs to list
            batch_size: Max requests per batch (Google limit is 100)

        Returns:
            Dict mapping folder_id -> list of file/folder metadata
        """
        BATCH_URL = "https://www.googleapis.com/batch/drive/v3"
        results = {fid: [] for fid in folder_ids}

        # Process in batches of batch_size
        for i in range(0, len(folder_ids), batch_size):
            batch_ids = folder_ids[i:i + batch_size]

            # Rate limit: wait for enough "tokens" for this batch
            # Each request in the batch counts toward quota
            for _ in range(len(batch_ids)):
                self._wait_for_rate_limit()

            boundary = f"batch_{int(time.time() * 1000)}_{i}"

            # Build multipart batch request body
            parts = []
            for folder_id in batch_ids:
                query_params = urlencode({
                    "q": f"'{folder_id}' in parents and trashed = false",
                    "fields": "nextPageToken, files(id, name, mimeType, size, md5Checksum, modifiedTime, shortcutDetails)",
                    "pageSize": 1000,
                    "supportsAllDrives": "true",
                    "includeItemsFromAllDrives": "true",
                    "key": self.config.api_key,
                })

                part = (
                    f"--{boundary}\r\n"
                    f"Content-Type: application/http\r\n"
                    f"Content-ID: <{folder_id}>\r\n"
                    f"\r\n"
                    f"GET /drive/v3/files?{query_params}\r\n"
                )
                parts.append(part)

            body = "".join(parts) + f"--{boundary}--\r\n"

            headers = {
                "Content-Type": f"multipart/mixed; boundary={boundary}",
            }
            if self.auth_token:
                headers["Authorization"] = f"Bearer {self.auth_token}"

            try:
                response = requests.post(
                    BATCH_URL,
                    headers=headers,
                    data=body,
                    timeout=self.config.timeout
                )
                self._api_calls += len(batch_ids)  # Count each batched call
                response.raise_for_status()

                # Parse multipart response, track folders needing follow-up
                needs_pagination = []
                failed_ids = []
                self._parse_batch_response(response, results, needs_pagination, failed_ids)

                # Retry failed sub-requests individually (e.g. intermittent 403 on shared folders)
                for folder_id in failed_ids:
                    results[folder_id] = self.list_folder(folder_id)

                # Handle pagination for folders with >1000 items
                for folder_id, page_token in needs_pagination:
                    results[folder_id] = self.list_folder(folder_id)

            except requests.exceptions.HTTPError:
                # On batch failure, fall back to individual calls for this batch
                for folder_id in batch_ids:
                    results[folder_id] = self.list_folder(folder_id)

        return results

    def _parse_batch_response(self, response: requests.Response, results: dict,
                              needs_pagination: list = None, failed_ids: list = None):
        """Parse a multipart/mixed batch response and populate results dict."""
        content_type = response.headers.get("Content-Type", "")
        boundary_match = re.search(r'boundary=([^\s;]+)', content_type)
        if not boundary_match:
            return

        boundary = boundary_match.group(1)
        parts = response.text.split(f"--{boundary}")

        for part in parts:
            if not part.strip() or part.strip() == "--":
                continue

            # Extract Content-ID (folder_id)
            id_match = re.search(r'Content-ID:\s*<?\s*response-([^>\s]+)', part)
            if not id_match:
                continue

            folder_id = id_match.group(1)
            if folder_id not in results:
                continue

            # Check HTTP status in this part — retry failures individually
            status_match = re.search(r'HTTP/[\d.]+ (\d+)', part)
            if status_match and int(status_match.group(1)) >= 400:
                if failed_ids is not None:
                    failed_ids.append(folder_id)
                continue

            # Find JSON body (after blank line following headers)
            json_match = re.search(r'\r?\n\r?\n({.*})', part, re.DOTALL)
            if not json_match:
                continue

            try:
                data = json.loads(json_match.group(1))
                files = data.get("files", [])
                results[folder_id] = files

                # Track folders that need pagination follow-up
                if data.get("nextPageToken") and needs_pagination is not None:
                    needs_pagination.append((folder_id, data["nextPageToken"]))
            except json.JSONDecodeError:
                pass

    def validate_folder(self, folder_id: str) -> tuple[bool, Optional[str]]:
        """
        Check if a folder is accessible and get its name.

        Args:
            folder_id: Google Drive folder ID

        Returns:
            Tuple of (is_valid, folder_name)
            - (True, "Folder Name") if accessible
            - (False, None) if not accessible or not a folder
        """
        metadata = self.get_file_metadata(
            folder_id, fields="id,name,mimeType"
        )

        if not metadata:
            return False, None

        # Check it's actually a folder
        if metadata.get("mimeType") != "application/vnd.google-apps.folder":
            return False, None

        return True, metadata.get("name")
