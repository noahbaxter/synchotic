import json
from src.drive.auth import load_client_config
from src.core import paths


def test_embedded_default(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "get_app_dir", lambda: tmp_path)
    monkeypatch.delenv("SYNCHOTIC_OAUTH_CLIENT_ID", raising=False)
    cfg = load_client_config()
    assert cfg["installed"]["client_id"].endswith(".apps.googleusercontent.com")


def test_env_overrides(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "get_app_dir", lambda: tmp_path)
    monkeypatch.setenv("SYNCHOTIC_OAUTH_CLIENT_ID", "myid")
    monkeypatch.setenv("SYNCHOTIC_OAUTH_CLIENT_SECRET", "mysecret")
    cfg = load_client_config()
    assert cfg["installed"]["client_id"] == "myid"


def test_credentials_file_overrides_embedded(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "get_app_dir", lambda: tmp_path)
    monkeypatch.delenv("SYNCHOTIC_OAUTH_CLIENT_ID", raising=False)
    creds = tmp_path / ".dm-sync" / "credentials.json"
    creds.parent.mkdir(parents=True)
    creds.write_text(json.dumps({"installed": {"client_id": "fileid", "client_secret": "s"}}))
    cfg = load_client_config()
    assert cfg["installed"]["client_id"] == "fileid"
