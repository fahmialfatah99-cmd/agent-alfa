"""Coverage batch 8: Google Drive auth (mode detection, secret save, logout, status).

Hermetic: PROJECT_DIR redirected to tmp, database calls and the Drive API
service are mocked, so no real credential or network access happens.
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture
def ga(tmp_path, monkeypatch):
    """Import module with PROJECT_DIR redirected into tmp + isolated sqlite."""
    import alfa.integrations.gdrive.auth as gauth
    from alfa.core.db import connection as db_conn

    db_file = tmp_path / "gdrive_test.db"
    monkeypatch.setenv("ALFA_DB_PATH", str(db_file))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    db_conn.init_db_sync()
    monkeypatch.setattr(gauth, "PROJECT_DIR", str(tmp_path))
    return gauth


def _set_setting(key: str, value: str) -> None:
    """Insert/replace a system_settings row for the current test DB."""
    from alfa.core.db.connection import get_sync_db

    with get_sync_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO system_settings (key, value) VALUES (?, ?)",
            (key, value),
        )
        conn.commit()


def _del_setting(key: str) -> None:
    from alfa.core.db.connection import get_sync_db

    with get_sync_db() as conn:
        conn.execute("DELETE FROM system_settings WHERE key = ?", (key,))
        conn.commit()


# ── default folder id ────────────────────────────────────────────────────────


class TestDefaultFolder:
    def test_from_db(self, ga):
        _set_setting("gdrive_default_folder_id", "  FOLDER_FROM_DB  ")
        assert ga._get_default_gdrive_folder_id() == "FOLDER_FROM_DB"

    def test_falls_back_to_env(self, ga, monkeypatch):
        _del_setting("gdrive_default_folder_id")
        monkeypatch.setenv("GDRIVE_DEFAULT_FOLDER_ID", "ENV_FOLDER")
        assert ga._get_default_gdrive_folder_id() == "ENV_FOLDER"

    def test_blank_db_row_falls_through(self, ga, monkeypatch):
        _set_setting("gdrive_default_folder_id", "   ")
        monkeypatch.setenv("GDRIVE_DEFAULT_FOLDER_ID", "ENV_FOLDER")
        assert ga._get_default_gdrive_folder_id() == "ENV_FOLDER"

    def test_builtin_default_when_nothing_set(self, ga, monkeypatch):
        _del_setting("gdrive_default_folder_id")
        monkeypatch.delenv("GDRIVE_DEFAULT_FOLDER_ID", raising=False)
        out = ga._get_default_gdrive_folder_id()
        assert isinstance(out, str) and out


# ── auth mode detection ──────────────────────────────────────────────────────


class TestAuthModeDetection:
    def test_none_when_nothing_configured(self, ga, monkeypatch):
        monkeypatch.delenv("GDRIVE_SERVICE_ACCOUNT_JSON", raising=False)
        _del_setting("gdrive_oauth_token_json")
        assert ga._detect_gdrive_auth_mode() == "none"

    def test_oauth_from_token_file(self, ga, monkeypatch):
        monkeypatch.delenv("GDRIVE_SERVICE_ACCOUNT_JSON", raising=False)
        (Path(ga.PROJECT_DIR) / "gdrive_oauth_token.json").write_text(
            "{}", encoding="utf-8"
        )
        assert ga._detect_gdrive_auth_mode() == "oauth"

    def test_oauth_from_db(self, ga, monkeypatch):
        monkeypatch.delenv("GDRIVE_SERVICE_ACCOUNT_JSON", raising=False)
        _set_setting("gdrive_oauth_token_json", "{}")
        assert ga._detect_gdrive_auth_mode() == "oauth"

    def test_service_account_file_wins_after_oauth_absent(self, ga, monkeypatch):
        monkeypatch.delenv("GDRIVE_SERVICE_ACCOUNT_JSON", raising=False)
        _del_setting("gdrive_oauth_token_json")
        (Path(ga.PROJECT_DIR) / "gdrive_credentials.json").write_text(
            "{}", encoding="utf-8"
        )
        assert ga._detect_gdrive_auth_mode() == "service_account"

    def test_service_account_from_env(self, ga, monkeypatch):
        monkeypatch.setenv("GDRIVE_SERVICE_ACCOUNT_JSON", "{}")
        _del_setting("gdrive_oauth_token_json")
        assert ga._detect_gdrive_auth_mode() == "service_account"

    def test_oauth_takes_precedence_over_sa(self, ga, monkeypatch):
        monkeypatch.setenv("GDRIVE_SERVICE_ACCOUNT_JSON", "{}")
        (Path(ga.PROJECT_DIR) / "gdrive_oauth_token.json").write_text(
            "{}", encoding="utf-8"
        )
        assert ga._detect_gdrive_auth_mode() == "oauth"


# ── client secret saving ─────────────────────────────────────────────────────


class TestSaveClientSecret:
    def test_rejects_wrong_shape(self, ga):
        out = ga.gdrive_save_oauth_client_secret(12345)
        assert out["status"] == "error"
        assert "tidak valid" in out["message"]

    def test_rejects_service_account_payload(self, ga):
        out = ga.gdrive_save_oauth_client_secret({"type": "service_account"})
        assert out["status"] == "error"

    def test_saves_installed_app(self, ga):
        payload = {"installed": {"client_id": "cid", "client_secret": "cs"}}
        out = ga.gdrive_save_oauth_client_secret(json.dumps(payload))
        assert out["status"] == "success"
        saved = Path(ga.PROJECT_DIR) / "gdrive_oauth_client_secret.json"
        assert saved.exists()
        assert json.loads(saved.read_text())["installed"]["client_id"] == "cid"

    def test_saves_web_app(self, ga):
        payload = {"web": {"client_id": "wcid"}}
        out = ga.gdrive_save_oauth_client_secret(payload)
        assert out["status"] == "success"
        saved = Path(ga.PROJECT_DIR) / "gdrive_oauth_client_secret.json"
        assert json.loads(saved.read_text())["web"]["client_id"] == "wcid"

    def test_rejects_malformed_json_string(self, ga):
        out = ga.gdrive_save_oauth_client_secret("{bukan json")
        assert out["status"] == "error"


# ── logout ───────────────────────────────────────────────────────────────────


class TestLogout:
    def test_logout_removes_token_file(self, ga):
        tf = Path(ga.PROJECT_DIR) / "gdrive_oauth_token.json"
        tf.write_text("{}", encoding="utf-8")
        out = ga.gdrive_oauth_logout()
        assert out["status"] == "success"
        assert out["removed"] is True
        assert not tf.exists()

    def test_logout_clears_db_row(self, ga):
        _set_setting("gdrive_oauth_token_json", "{}")
        ga.gdrive_oauth_logout()
        from alfa.core.db.connection import get_sync_db

        with get_sync_db() as conn:
            row = conn.execute(
                "SELECT value FROM system_settings WHERE key = 'gdrive_oauth_token_json'"
            ).fetchone()
        assert row is None

    def test_logout_without_token(self, ga):
        out = ga.gdrive_oauth_logout()
        assert out["status"] == "success"
        assert out["removed"] is False


# ── status ───────────────────────────────────────────────────────────────────


def _fake_service(about_payload, fail=False):
    svc = MagicMock()
    about = MagicMock()
    if fail:
        about.get.return_value.execute.side_effect = RuntimeError("quota API gagal")
    else:
        about.get.return_value.execute.return_value = about_payload
    svc.about.return_value = about
    return svc


class TestStatus:
    def test_status_success(self, ga, monkeypatch):
        payload = {
            "user": {"emailAddress": "u@x.io"},
            "storageQuota": {"limit": "1", "usage": "2"},
        }
        monkeypatch.setattr(ga, "_get_gdrive_service", lambda: _fake_service(payload))
        out = ga.gdrive_status()
        assert out["status"] == "success"
        assert out["connected"] is True
        assert out["user"]["emailAddress"] == "u@x.io"
        assert out["auth_mode"] in ("oauth", "service_account", "none")
        assert out["default_folder_url"].startswith("https://drive.google.com/")

    def test_status_uses_folder_name_from_db(self, ga, monkeypatch):
        monkeypatch.setattr(ga, "_get_gdrive_service", lambda: _fake_service({}))
        _set_setting("gdrive_default_folder_name", "Folder Kustom")
        out = ga.gdrive_status()
        assert out["default_folder_name"] == "Folder Kustom"

    def test_status_reports_error(self, ga, monkeypatch):
        monkeypatch.setattr(
            ga, "_get_gdrive_service", lambda: _fake_service({}, fail=True)
        )
        out = ga.gdrive_status()
        assert out["status"] == "error"
        assert out["connected"] is False
        assert "quota API gagal" in out["message"]
