"""A batch sub-response we could not read is a failure, not an empty folder.

list_folders_batch pre-seeds every folder with [] and fills in what it parses.
Anything it cannot parse therefore keeps the []: a 200 with a mangled body, a
missing boundary, a truncated part. Each one reaches the purge planner as "this
folder is empty on the remote", which is a deletion order for the local copy.

Every case here answers HTTP 200. The 403 path is covered by the auth contract.
"""

import pytest
import requests

from src.drive.client import DriveClient, DriveClientConfig

BOUNDARY = "batchboundary"


def _multipart(body_by_folder: dict) -> str:
    parts = []
    for folder_id, body in body_by_folder.items():
        parts.append(
            f"--{BOUNDARY}\r\n"
            f"Content-Type: application/http\r\n"
            f"Content-ID: <response-{folder_id}>\r\n"
            f"\r\n"
            f"HTTP/1.1 200 OK\r\n"
            f"Content-Type: application/json\r\n"
            f"\r\n"
            f"{body}\r\n"
        )
    return "".join(parts) + f"--{BOUNDARY}--\r\n"


@pytest.fixture
def batch(monkeypatch):
    """Serve one canned batch response, then 403 any individual retry."""
    state = {"text": "", "content_type": f"multipart/mixed; boundary={BOUNDARY}",
             "individual_calls": []}

    class Batch:
        status_code = 200

        @property
        def headers(self):
            return {"Content-Type": state["content_type"]}

        @property
        def text(self):
            return state["text"]

        def raise_for_status(self):
            pass

    class Forbidden:
        status_code = 403
        text = "insufficientPermissions"

        def raise_for_status(self):
            raise requests.exceptions.HTTPError(response=self)

    import src.drive.client as client_module

    monkeypatch.setattr(client_module.requests, "post", lambda url, **kw: Batch())

    def individual(method, url, **kw):
        state["individual_calls"].append(url)
        return Forbidden()

    monkeypatch.setattr(client_module.requests, "request", individual)
    monkeypatch.setattr(client_module.time, "sleep", lambda *_: None)
    return state


def _client():
    return DriveClient(DriveClientConfig(api_key="k"), auth_token="tok")


def test_a_good_batch_still_returns_its_files(batch):
    """Guards against fixing the holes by breaking the happy path."""
    batch["text"] = _multipart({"folder1": '{"files": [{"id": "a"}]}'})

    assert _client().list_folders_batch(["folder1"]) == {"folder1": [{"id": "a"}]}
    assert batch["individual_calls"] == []


def test_a_folder_missing_from_the_response_is_not_an_empty_folder(batch):
    """Two folders asked for, one answered. The other is unknown, not empty."""
    batch["text"] = _multipart({"folder1": '{"files": [{"id": "a"}]}'})

    with pytest.raises(requests.exceptions.HTTPError):
        _client().list_folders_batch(["folder1", "folder2"])


def test_an_unparseable_body_is_not_an_empty_folder(batch):
    batch["text"] = _multipart({"folder1": "{not json at all"})

    with pytest.raises(requests.exceptions.HTTPError):
        _client().list_folders_batch(["folder1"])


def test_a_part_with_no_json_body_is_not_an_empty_folder(batch):
    batch["text"] = (
        f"--{BOUNDARY}\r\n"
        f"Content-Type: application/http\r\n"
        f"Content-ID: <response-folder1>\r\n"
        f"\r\n"
        f"HTTP/1.1 200 OK\r\n"
        f"\r\n"
        f"--{BOUNDARY}--\r\n"
    )

    with pytest.raises(requests.exceptions.HTTPError):
        _client().list_folders_batch(["folder1"])


def test_a_response_with_no_boundary_is_not_a_batch_of_empty_folders(batch):
    """No boundary means nothing was read at all, for every folder in the batch."""
    batch["content_type"] = "text/html"
    batch["text"] = "<html>proxy error</html>"

    with pytest.raises(requests.exceptions.HTTPError):
        _client().list_folders_batch(["folder1", "folder2"])
