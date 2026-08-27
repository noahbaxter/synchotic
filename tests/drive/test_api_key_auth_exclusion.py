"""The API key and an OAuth token must never go out on the same request.

Google 400s that combination when the two are from different Cloud projects,
which is every BYOC user against a release build.
"""

from src.drive.client import DriveClient, DriveClientConfig

CONFIG = DriveClientConfig(api_key="test-key")


def test_key_sent_when_anonymous():
    client = DriveClient(CONFIG)
    assert client._get_params(q="x")["key"] == "test-key"


def test_key_dropped_when_authenticated():
    client = DriveClient(CONFIG, auth_token="tok")
    params = client._get_params(q="x")
    assert "key" not in params
    assert params["q"] == "x"


def test_authenticated_request_never_carries_both():
    client = DriveClient(CONFIG, auth_token="tok")
    assert "Authorization" in client._get_headers()
    assert "key" not in client._get_params()


def test_batch_body_omits_key_when_authenticated(monkeypatch):
    """The batch path built its query string separately and missed the fix once."""
    sent = {}

    class FakeResponse:
        status_code = 200
        text = ""
        headers = {"Content-Type": "multipart/mixed; boundary=b"}

        def raise_for_status(self):
            pass

    def fake_post(url, headers=None, data=None, timeout=None):
        sent["body"] = data
        sent["headers"] = headers
        return FakeResponse()

    monkeypatch.setattr("src.drive.client.requests.post", fake_post)

    client = DriveClient(CONFIG, auth_token="tok")
    client.list_folders_batch(["folder1"])

    assert "key=test-key" not in sent["body"]
    assert sent["headers"]["Authorization"] == "Bearer tok"
