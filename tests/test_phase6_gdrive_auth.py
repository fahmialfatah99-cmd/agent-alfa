"""Phase 6 coverage: Google Drive auth — OAuth, service account, status.

Hermetic: PROJECT_DIR/HOME diarahkan ke tmp_path, SDK Google di-fake, DB sementara.
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

from alfa.integrations.gdrive import auth as ga


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    db_file = tmp_path / "gdrive.db"
    monkeypatch.setenv("ALFA_DB_PATH", str(db_file))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from alfa.core.db import connection

    connection.init_db_sync()
    return db_file


@pytest.fixture
def project(tmp_path, monkeypatch):
    proj = tmp_path / "proj"
    proj.mkdir()
    monkeypatch.setattr(ga, "PROJECT_DIR", str(proj))
    monkeypatch.setattr(ga, "REPO_ROOT", str(proj))
    return proj


class _FakeCreds:
    def __init__(self, **kwargs):
        self.expired = kwargs.get("expired", False)
        self.refresh_token = kwargs.get("refresh_token", "rt")
        self.refreshed = False
        self.token = kwargs.get("token", "tok")
        self.token_uri = kwargs.get("token_uri", "https://oauth2")
        self.client_id = kwargs.get("client_id", "cid")
        self.client_secret = kwargs.get("client_secret", "csec")
        self.scopes = kwargs.get("scopes", ["scope"])

    def refresh(self, request):
        self.refreshed = True


def _install_google(monkeypatch, creds, build_result="SERVICE"):
    """Install fake google SDK modules; return dict of call recorders."""
    calls = {}

    google_mod = types.ModuleType("google")
    google_mod.__path__ = []
    oauth2 = types.ModuleType("google.oauth2")
    oauth2.__path__ = []
    service_account = types.ModuleType("google.oauth2.service_account")

    class SACreds:
        @staticmethod
        def from_service_account_file(path, scopes=None):
            calls["sa_file"] = (path, scopes)
            return creds

        @staticmethod
        def from_service_account_info(info, scopes=None):
            calls["sa_info"] = (info, scopes)
            return creds

    service_account.Credentials = SACreds

    creds_mod = types.ModuleType("google.oauth2.credentials")

    class UserCreds:
        @staticmethod
        def from_authorized_user_file(path, scopes=None):
            calls["user_file"] = (path, scopes)
            if isinstance(creds, BaseException):
                raise creds
            return creds

        @staticmethod
        def from_authorized_user_info(info, scopes=None):
            calls["user_info"] = (info, scopes)
            return creds

        def __init__(self, token=None, scopes=None):
            calls["direct"] = (token, scopes)
            self.token = token
            self.scopes = scopes

    creds_mod.Credentials = UserCreds

    auth_mod = types.ModuleType("google.auth")
    auth_mod.__path__ = []
    transport = types.ModuleType("google.auth.transport")
    transport.__path__ = []
    requests_mod = types.ModuleType("google.auth.transport.requests")

    class Request:
        pass

    requests_mod.Request = Request
    auth_mod.transport = transport
    transport.requests = requests_mod

    api_mod = types.ModuleType("googleapiclient")
    api_mod.__path__ = []
    discovery = types.ModuleType("googleapiclient.discovery")

    def build(service, version, credentials=None):
        calls["build"] = (service, version, credentials)
        return build_result

    discovery.build = build
    api_mod.discovery = discovery

    monkeypatch.setitem(sys.modules, "google", google_mod)
    monkeypatch.setitem(sys.modules, "google.oauth2", oauth2)
    monkeypatch.setitem(sys.modules, "google.oauth2.service_account", service_account)
    monkeypatch.setitem(sys.modules, "google.oauth2.credentials", creds_mod)
    monkeypatch.setitem(sys.modules, "google.auth", auth_mod)
    monkeypatch.setitem(sys.modules, "google.auth.transport", transport)
    monkeypatch.setitem(sys.modules, "google.auth.transport.requests", requests_mod)
    monkeypatch.setitem(sys.modules, "googleapiclient", api_mod)
    monkeypatch.setitem(sys.modules, "googleapiclient.discovery", discovery)
    return calls


def test_default_folder_from_db(isolated_db):
    from alfa.core import database

    with database.get_sync_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO system_settings (key, value) VALUES ('gdrive_default_folder_id', ' db-folder ')",
        )
        conn.commit()
    assert ga._get_default_gdrive_folder_id() == "db-folder"


def test_default_folder_from_env(isolated_db, monkeypatch):
    from alfa.core import database

    with database.get_sync_db() as conn:
        conn.execute("DELETE FROM system_settings WHERE key = 'gdrive_default_folder_id'")
        conn.commit()
    monkeypatch.setenv("GDRIVE_DEFAULT_FOLDER_ID", "env-folder")
    assert ga._get_default_gdrive_folder_id() == "env-folder"


def test_get_service_no_credentials(project, monkeypatch):
    creds = _FakeCreds()
    _install_google(monkeypatch, creds)
    monkeypatch.delenv("GDRIVE_SERVICE_ACCOUNT_JSON", raising=False)
    from alfa.integrations.gdrive import secret_store

    monkeypatch.setattr(secret_store, "load_oauth_token", lambda scopes=None: None)
    monkeypatch.setattr(secret_store, "load_service_account_json", lambda: None)
    monkeypatch.setattr(ga.os.path, "expanduser", lambda p: str(project / "nope"))
    with pytest.raises(ValueError) as err:
        ga._get_gdrive_service()
    assert "belum dikonfigurasi" in str(err.value)


def test_get_service_service_account_file(project, monkeypatch):
    creds = _FakeCreds()
    calls = _install_google(monkeypatch, creds)
    cred_file = project / "gdrive_credentials.json"
    cred_file.write_text("{}", encoding="utf-8")
    assert ga._get_gdrive_service() == "SERVICE"
    assert calls["sa_file"][0] == str(cred_file)
    assert calls["build"][0] == "drive"


def test_get_service_env_json(project, monkeypatch):
    creds = _FakeCreds()
    calls = _install_google(monkeypatch, creds)
    monkeypatch.setenv("GDRIVE_SERVICE_ACCOUNT_JSON", '{"type": "service_account"}')
    assert ga._get_gdrive_service() == "SERVICE"
    assert calls["sa_info"][0] == {"type": "service_account"}


def test_get_service_env_json_invalid(project, monkeypatch):
    creds = _FakeCreds()
    _install_google(monkeypatch, creds)
    monkeypatch.setenv("GDRIVE_SERVICE_ACCOUNT_JSON", "bukan-json")
    monkeypatch.setattr(ga.os.path, "expanduser", lambda p: str(project / "nope"))
    with pytest.raises(ValueError):
        ga._get_gdrive_service()


def test_get_service_oauth_file_and_refresh(project, monkeypatch):
    oauth_file = project / "gdrive_oauth_token.json"
    oauth_file.write_text('{"scopes": ["scope"]}', encoding="utf-8")
    creds = _FakeCreds(expired=True, refresh_token="rt")
    calls = _install_google(monkeypatch, creds)
    assert ga._get_gdrive_service() == "SERVICE"
    assert creds.refreshed is True
    assert calls["user_file"][0] == str(oauth_file)


def test_get_service_oauth_file_unreadable_scopes(project, monkeypatch):
    oauth_file = project / "gdrive_oauth_token.json"
    oauth_file.write_text("bukan-json", encoding="utf-8")
    creds = _FakeCreds()
    _install_google(monkeypatch, creds)
    assert ga._get_gdrive_service() == "SERVICE"


def test_get_service_oauth_invalid_grant(project, monkeypatch):
    oauth_file = project / "gdrive_oauth_token.json"
    oauth_file.write_text('{"scopes": []}', encoding="utf-8")
    _install_google(monkeypatch, ValueError("invalid_grant"))
    monkeypatch.setattr(ga.os.path, "expanduser", lambda p: str(project / "nope"))
    with pytest.raises(ValueError) as err:
        ga._get_gdrive_service()
    assert "kedaluwarsa" in str(err.value)


def test_get_service_secret_store_oauth(project, isolated_db, monkeypatch):
    creds = _FakeCreds()
    calls = _install_google(monkeypatch, creds)
    from alfa.integrations.gdrive import secret_store

    monkeypatch.setattr(secret_store, "load_oauth_token", lambda scopes=None: {"refresh_token": "x"})
    monkeypatch.setattr(ga.os.path, "expanduser", lambda p: str(project / "nope"))
    assert ga._get_gdrive_service() == "SERVICE"
    assert calls["user_info"][0] == {"refresh_token": "x"}


def test_get_service_secret_store_service_account(project, isolated_db, monkeypatch):
    creds = _FakeCreds()
    calls = _install_google(monkeypatch, creds)
    from alfa.integrations.gdrive import secret_store

    monkeypatch.setattr(secret_store, "load_oauth_token", lambda scopes=None: None)
    monkeypatch.setattr(secret_store, "load_service_account_json", lambda: {"type": "service_account"})
    monkeypatch.setattr(ga.os.path, "expanduser", lambda p: str(project / "nope"))
    assert ga._get_gdrive_service() == "SERVICE"
    assert calls["sa_info"][0] == {"type": "service_account"}


def test_get_service_wa_service_account(project, isolated_db, monkeypatch):
    creds = _FakeCreds()
    calls = _install_google(monkeypatch, creds)
    from alfa.integrations.gdrive import secret_store

    monkeypatch.setattr(secret_store, "load_oauth_token", lambda scopes=None: None)
    monkeypatch.setattr(secret_store, "load_service_account_json", lambda: None)
    wa = project / "wa-sheets-bot"
    wa.mkdir()
    (wa / "service-account.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        ga.os.path,
        "expanduser",
        lambda p: str(wa / "service-account.json") if "~" in p else str(project / p),
    )
    assert ga._get_gdrive_service() == "SERVICE"
    assert calls["sa_file"][0].endswith("service-account.json")


def test_get_service_rclone_token(project, isolated_db, monkeypatch):
    creds = _FakeCreds()
    calls = _install_google(monkeypatch, creds)
    from alfa.integrations.gdrive import secret_store

    monkeypatch.setattr(secret_store, "load_oauth_token", lambda scopes=None: None)
    monkeypatch.setattr(secret_store, "load_service_account_json", lambda: None)
    rclone = project / "rclone.conf"
    rclone.write_text(
        "[gdrive1]\ntoken = " + json.dumps({"access_token": "at"}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        ga.os.path,
        "expanduser",
        lambda p: str(rclone) if "rclone" in p else str(project / "nope"),
    )
    assert ga._get_gdrive_service() == "SERVICE"
    assert calls["direct"][0] == "at"


def test_detect_auth_mode(project, isolated_db, monkeypatch):
    from alfa.integrations.gdrive import secret_store

    monkeypatch.setattr(secret_store, "load_oauth_token", lambda scopes=None: None)
    monkeypatch.delenv("GDRIVE_SERVICE_ACCOUNT_JSON", raising=False)
    assert ga._detect_gdrive_auth_mode() == "none"
    (project / "gdrive_oauth_token.json").write_text("{}", encoding="utf-8")
    assert ga._detect_gdrive_auth_mode() == "oauth"
    (project / "gdrive_oauth_token.json").unlink()
    monkeypatch.setattr(secret_store, "load_oauth_token", lambda scopes=None: {"x": 1})
    assert ga._detect_gdrive_auth_mode() == "oauth"
    monkeypatch.setattr(secret_store, "load_oauth_token", lambda scopes=None: None)
    (project / "gdrive_credentials.json").write_text("{}", encoding="utf-8")
    assert ga._detect_gdrive_auth_mode() == "service_account"
    (project / "gdrive_credentials.json").unlink()
    monkeypatch.setenv("GDRIVE_SERVICE_ACCOUNT_JSON", "{}")
    assert ga._detect_gdrive_auth_mode() == "service_account"


def _fake_flow_module(monkeypatch, run_result=None, auth_result=None, fetch_error=None):
    flow_mod = types.ModuleType("google_auth_oauthlib.flow")
    records = {}

    class Flow:
        def __init__(self):
            self.credentials = run_result

        @classmethod
        def from_client_secrets_file(cls, path, scopes=None, redirect_uri=None):
            records["secret_path"] = path
            records["scopes"] = scopes
            records["redirect_uri"] = redirect_uri
            return cls()

        def run_local_server(self, **kwargs):
            records["local"] = kwargs
            if isinstance(run_result, BaseException):
                raise run_result
            return run_result

        def authorization_url(self, **kwargs):
            records["auth_kwargs"] = kwargs
            return ("https://auth.example/u", "state-1")

        def fetch_token(self, code=None):
            records["code"] = code
            if fetch_error:
                raise fetch_error
            self.credentials = auth_result

    flow_mod.Flow = Flow
    flow_mod.InstalledAppFlow = Flow
    monkeypatch.setitem(sys.modules, "google_auth_oauthlib", types.ModuleType("google_auth_oauthlib"))
    monkeypatch.setitem(sys.modules, "google_auth_oauthlib.flow", flow_mod)
    return records


def test_oauth_login_missing_secret(project):
    out = ga.gdrive_oauth_login()
    assert out["status"] == "error"
    assert out["needs_client_secret"] is True


def test_oauth_login_service_account_file(project):
    (project / "gdrive_oauth_client_secret.json").write_text(
        json.dumps({"type": "service_account", "private_key": "x"}), encoding="utf-8"
    )
    out = ga.gdrive_oauth_login()
    assert out["status"] == "error"
    assert out.get("wrong_type") == "service_account"


def test_oauth_login_unreadable_probe(project):
    (project / "gdrive_oauth_client_secret.json").write_text("bukan-json", encoding="utf-8")
    out = ga.gdrive_oauth_login()
    assert out["status"] == "error"


def test_oauth_login_success(project, isolated_db, monkeypatch):
    (project / "gdrive_oauth_client_secret.json").write_text(
        json.dumps({"installed": {"client_id": "cid"}}), encoding="utf-8"
    )
    creds = _FakeCreds()
    _fake_flow_module(monkeypatch, run_result=creds)
    from alfa.integrations.gdrive import secret_store

    saved = []
    monkeypatch.setattr(secret_store, "save_secret", lambda name, value: saved.append(name) or True)
    out = ga.gdrive_oauth_login()
    assert out["status"] == "success"
    assert (project / "gdrive_oauth_token.json").exists()
    assert saved


def test_oauth_login_failure(project, isolated_db, monkeypatch):
    (project / "gdrive_oauth_client_secret.json").write_text(
        json.dumps({"installed": {"client_id": "cid"}}), encoding="utf-8"
    )
    _fake_flow_module(monkeypatch, run_result=RuntimeError("dibatalkan"))
    out = ga.gdrive_oauth_login()
    assert out["status"] == "error"
    assert "dibatalkan" in out["message"]


def test_save_client_secret_invalid_type(project):
    out = ga.gdrive_save_oauth_client_secret(123)
    assert out["status"] == "error"


def test_save_client_secret_service_account(project):
    out = ga.gdrive_save_oauth_client_secret({"type": "service_account"})
    assert out["status"] == "error"
    assert "Service Account" in out["message"]


def test_save_client_secret_missing_keys(project):
    out = ga.gdrive_save_oauth_client_secret({"foo": "bar"})
    assert out["status"] == "error"


def test_save_client_secret_success(project, isolated_db):
    out = ga.gdrive_save_oauth_client_secret({"installed": {"client_id": "cid"}})
    assert out["status"] == "success"
    assert Path(out["file"]).exists()
    from alfa.core import database

    with database.get_sync_db() as conn:
        row = conn.execute(
            "SELECT value FROM system_settings WHERE key = 'gdrive_oauth_client_secret_json'"
        ).fetchone()
    assert row and "cid" in row[0]


def test_save_client_secret_invalid_json_string(project):
    out = ga.gdrive_save_oauth_client_secret("{bukan json")
    assert out["status"] == "error"


def test_auth_url_missing_secret(project, isolated_db):
    out = ga.gdrive_oauth_get_auth_url()
    assert out["status"] == "error"
    assert out["needs_client_secret"] is True


def test_auth_url_from_db_secret(project, isolated_db, monkeypatch):
    from alfa.core import database

    with database.get_sync_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO system_settings (key, value) VALUES ('gdrive_oauth_client_secret_json', ?)",
            (json.dumps({"installed": {"client_id": "cid"}}),),
        )
        conn.commit()
    _fake_flow_module(monkeypatch)
    out = ga.gdrive_oauth_get_auth_url("http://localhost/cb")
    assert out["status"] == "success"
    assert out["auth_url"] == "https://auth.example/u"
    assert out["state"] == "state-1"


def test_auth_url_flow_error(project, monkeypatch):
    (project / "gdrive_oauth_client_secret.json").write_text(
        json.dumps({"installed": {}}), encoding="utf-8"
    )

    flow_mod = types.ModuleType("google_auth_oauthlib.flow")
    flow_mod.Flow = SimpleNamespace(
        from_client_secrets_file=lambda *a, **k: (_ for _ in ()).throw(ValueError("bad"))
    )
    monkeypatch.setitem(sys.modules, "google_auth_oauthlib", types.ModuleType("google_auth_oauthlib"))
    monkeypatch.setitem(sys.modules, "google_auth_oauthlib.flow", flow_mod)
    out = ga.gdrive_oauth_get_auth_url()
    assert out["status"] == "error"


def test_exchange_code_missing_secret(project):
    out = ga.gdrive_oauth_exchange_code("code")
    assert out["status"] == "error"


def test_exchange_code_success(project, isolated_db, monkeypatch):
    (project / "gdrive_oauth_client_secret.json").write_text(
        json.dumps({"installed": {}}), encoding="utf-8"
    )
    creds = _FakeCreds()
    _fake_flow_module(monkeypatch, auth_result=creds)
    from alfa.integrations.gdrive import secret_store

    monkeypatch.setattr(secret_store, "save_secret", lambda *a, **k: True)
    out = ga.gdrive_oauth_exchange_code(" code ")
    assert out["status"] == "success"
    assert (project / "gdrive_oauth_token.json").exists()


def test_exchange_code_failure(project, monkeypatch):
    (project / "gdrive_oauth_client_secret.json").write_text(
        json.dumps({"installed": {}}), encoding="utf-8"
    )
    _fake_flow_module(monkeypatch, fetch_error=RuntimeError("invalid"))
    out = ga.gdrive_oauth_exchange_code("code")
    assert out["status"] == "error"


def test_oauth_logout_removes_file(project, isolated_db, monkeypatch):
    from alfa.integrations.gdrive import secret_store

    deleted = []
    monkeypatch.setattr(secret_store, "delete_secret", lambda name: deleted.append(name))
    token = project / "gdrive_oauth_token.json"
    token.write_text("{}", encoding="utf-8")
    out = ga.gdrive_oauth_logout()
    assert out["status"] == "success"
    assert out["removed"] is True
    assert not token.exists()
    assert deleted


def test_oauth_logout_without_file(project, isolated_db, monkeypatch):
    from alfa.integrations.gdrive import secret_store

    monkeypatch.setattr(secret_store, "delete_secret", lambda name: None)
    out = ga.gdrive_oauth_logout()
    assert out["status"] == "success"
    assert out["removed"] is False


def test_detect_mounted_drives(tmp_path, monkeypatch):
    for idx in (1, 2):
        d = tmp_path / f"GDrive{idx}"
        d.mkdir()
        (d / "file").write_text("x", encoding="utf-8")
    monkeypatch.setattr(
        ga.os.path,
        "expanduser",
        lambda p: str(tmp_path / p.split("~/")[-1]),
    )
    mounts = ga._detect_mounted_gdrives()
    assert [m["name"] for m in mounts] == ["GDrive1", "GDrive2"]
    assert mounts[0]["items_count"] == 1


def test_gdrive_status_success(isolated_db, monkeypatch):
    from alfa.core import database

    with database.get_sync_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO system_settings (key, value) VALUES ('gdrive_default_folder_name', 'Folder Uji')"
        )
        conn.commit()

    about = SimpleNamespace(
        get=lambda **k: SimpleNamespace(
            execute=lambda: {"user": {"email": "x"}, "storageQuota": {"limit": 1}}
        )
    )
    monkeypatch.setattr(ga, "_get_gdrive_service", lambda: SimpleNamespace(about=lambda: about))
    monkeypatch.setattr(ga, "_detect_gdrive_auth_mode", lambda: "oauth")
    monkeypatch.setattr(ga, "_detect_mounted_gdrives", lambda: [{"name": "GDrive1"}])
    out = ga.gdrive_status()
    assert out["status"] == "success"
    assert out["connected"] is True
    assert out["default_folder_name"] == "Folder Uji"
    assert out["has_local_mounts"] is True


def test_gdrive_status_error(isolated_db, monkeypatch):
    monkeypatch.setattr(
        ga, "_get_gdrive_service", lambda: (_ for _ in ()).throw(ValueError("no creds"))
    )
    monkeypatch.setattr(ga, "_detect_mounted_gdrives", lambda: [])
    out = ga.gdrive_status()
    assert out["status"] == "error"
    assert out["connected"] is False
    assert "no creds" in out["message"]
