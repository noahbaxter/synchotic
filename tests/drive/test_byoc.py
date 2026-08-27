import json
from src.drive.auth import has_custom_client_config, load_client_config
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


class TestHasCustomClientConfig:
    """Whether BYOC is actually usable, as opposed to silently falling back.

    load_client_config always returns a config, so it cannot answer this. Without
    a separate check the app offers BYOC, signs in with the embedded blocked
    client, and disables the rclone tier that would have saved the download.
    """

    def test_no_credentials_anywhere(self, monkeypatch, tmp_path):
        monkeypatch.setattr(paths, "get_app_dir", lambda: tmp_path)
        monkeypatch.delenv("SYNCHOTIC_OAUTH_CLIENT_ID", raising=False)
        monkeypatch.delenv("SYNCHOTIC_OAUTH_CLIENT_SECRET", raising=False)
        assert has_custom_client_config() is False

    def test_env_pair_counts(self, monkeypatch, tmp_path):
        monkeypatch.setattr(paths, "get_app_dir", lambda: tmp_path)
        monkeypatch.setenv("SYNCHOTIC_OAUTH_CLIENT_ID", "myid")
        monkeypatch.setenv("SYNCHOTIC_OAUTH_CLIENT_SECRET", "mysecret")
        assert has_custom_client_config() is True

    def test_half_an_env_pair_does_not(self, monkeypatch, tmp_path):
        """load_client_config ignores a lone id, so this must not claim success."""
        monkeypatch.setattr(paths, "get_app_dir", lambda: tmp_path)
        monkeypatch.setenv("SYNCHOTIC_OAUTH_CLIENT_ID", "myid")
        monkeypatch.delenv("SYNCHOTIC_OAUTH_CLIENT_SECRET", raising=False)
        assert has_custom_client_config() is False

    def test_credentials_file_counts(self, monkeypatch, tmp_path):
        monkeypatch.setattr(paths, "get_app_dir", lambda: tmp_path)
        monkeypatch.delenv("SYNCHOTIC_OAUTH_CLIENT_ID", raising=False)
        creds = tmp_path / ".dm-sync" / "credentials.json"
        creds.parent.mkdir(parents=True)
        creds.write_text(json.dumps({"installed": {"client_id": "f", "client_secret": "s"}}))
        assert has_custom_client_config() is True

    def test_credentials_file_missing_secret(self, monkeypatch, tmp_path):
        monkeypatch.setattr(paths, "get_app_dir", lambda: tmp_path)
        monkeypatch.delenv("SYNCHOTIC_OAUTH_CLIENT_ID", raising=False)
        creds = tmp_path / ".dm-sync" / "credentials.json"
        creds.parent.mkdir(parents=True)
        creds.write_text(json.dumps({"installed": {"client_id": "f"}}))
        assert has_custom_client_config() is False

    def test_corrupt_credentials_file(self, monkeypatch, tmp_path):
        monkeypatch.setattr(paths, "get_app_dir", lambda: tmp_path)
        monkeypatch.delenv("SYNCHOTIC_OAUTH_CLIENT_ID", raising=False)
        creds = tmp_path / ".dm-sync" / "credentials.json"
        creds.parent.mkdir(parents=True)
        creds.write_text("{ not json")
        assert has_custom_client_config() is False
