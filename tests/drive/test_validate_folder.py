"""Adding a custom drive says why a folder cannot be used, in Google's words."""
import pytest
import requests

from src import copy
from src.drive.client import DriveClient, DriveClientConfig


class _Response:
    def __init__(self, body, status=200):
        self._body, self.status_code = body, status

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


@pytest.fixture
def client():
    return DriveClient(DriveClientConfig(api_key="key"))


def _answer(client, monkeypatch, result):
    def request(*a, **k):
        if isinstance(result, Exception):
            raise result
        return result
    monkeypatch.setattr(client, "_request_with_retry", request)


def _http_error(body, status):
    return requests.exceptions.HTTPError(response=_Response(body, status))


def test_a_folder_gives_its_name(client, monkeypatch):
    _answer(client, monkeypatch, _Response(
        {"name": "Charts", "mimeType": "application/vnd.google-apps.folder"}))
    assert client.validate_folder("id") == ("Charts", None)


def test_googles_reason_is_passed_on(client, monkeypatch):
    _answer(client, monkeypatch, _http_error(
        {"error": {"message": "File not found: id."}}, 404))
    assert client.validate_folder("id") == (None, "File not found: id.")


def test_an_error_without_a_message_still_says_something(client, monkeypatch):
    _answer(client, monkeypatch, _http_error(ValueError("not json"), 502))
    assert client.validate_folder("id") == (None, "HTTP 502")


def test_being_offline_is_a_reason_not_a_crash(client, monkeypatch):
    _answer(client, monkeypatch, requests.exceptions.ConnectionError())
    assert client.validate_folder("id") == (None, "ConnectionError")


def test_running_out_of_retries_is_a_reason_not_a_crash(client, monkeypatch):
    _answer(client, monkeypatch, RuntimeError("Request failed after 3 attempts"))
    assert client.validate_folder("id") == (None, "Request failed after 3 attempts")


def test_a_file_is_not_a_folder(client, monkeypatch):
    _answer(client, monkeypatch, _Response({"name": "song.zip", "mimeType": "application/zip"}))
    assert client.validate_folder("id") == (None, copy.URL_IS_FILE)


def test_the_screen_prints_the_reason(monkeypatch, capsys):
    from src.ui.screens import add_folder

    class Client:
        def validate_folder(self, folder_id):
            return None, "File not found: id."

    for name in ("clear_screen", "print_header", "wait_with_skip"):
        monkeypatch.setattr(add_folder, name, lambda *a, **k: None)
    monkeypatch.setattr(add_folder, "input_with_esc", lambda prompt: "1ABC123def456_-xyz")

    from src.ui.components import strip_ansi
    assert add_folder.show_add_custom_folder(Client()) == (None, None)
    assert f"{copy.FAILURE}: File not found: id." in strip_ansi(capsys.readouterr().out)
