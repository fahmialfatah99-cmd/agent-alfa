"""Phase 6 coverage: dashboard Google Drive & WhatsApp routes.

Hermetic: DB SQLite sementara, HOME/REPO_ROOT ke tmp, SDK Drive/httpx di-fake,
dan semua fungsi `alfa.tools` yang menyentuh jaringan di-mock.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    db_file = tmp_path / "system_routes.db"
    monkeypatch.setenv("ALFA_DB_PATH", str(db_file))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from alfa.core.db import connection

    connection.init_db_sync()
    return db_file


@pytest.fixture
def client(isolated_db, tmp_path, monkeypatch):
    from alfa.core import config
    from alfa.dashboard import app as pkg_app
    from alfa.dashboard.ratelimit import reset_rate_limits
    from alfa.dashboard.routes import auth as auth_mod
    from alfa.dashboard.routes.system import gdrive as gdrive_routes
    from alfa.dashboard.routes.system import settings_admin
    from alfa.dashboard.routes.system import whatsapp as whatsapp_routes

    home = tmp_path / "home"
    home.mkdir()
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("DASHBOARD_AUTH_TOKEN", "")
    monkeypatch.setenv("ALFA_INSECURE_LOCAL", "true")
    monkeypatch.setattr(auth_mod, "DASHBOARD_AUTH_TOKEN", "")
    monkeypatch.setattr(config, "SECRETS_PATH", tmp_path / "no-secrets.env")
    monkeypatch.setattr(settings_admin, "REPO_ROOT", str(repo))
    monkeypatch.setattr(gdrive_routes, "REPO_ROOT", str(repo))

    monkeypatch.setattr(
        whatsapp_routes, "WA_BOT_FORMATS_FILE", str(tmp_path / "wa" / "formats.json")
    )
    monkeypatch.setattr(
        whatsapp_routes,
        "WA_BOT_MEDIA_RULES_FILE",
        str(tmp_path / "wa" / "media_rules.json"),
    )
    monkeypatch.setattr(
        whatsapp_routes,
        "WA_DRIVE_UPLOADS_FILE",
        str(tmp_path / "wa" / "drive_uploads.json"),
    )
    reset_rate_limits()
    return TestClient(pkg_app)


@pytest.fixture
def gd():
    from alfa.dashboard.routes.system import gdrive as module

    return module


@pytest.fixture
def wa():
    from alfa.dashboard.routes.system import whatsapp as module

    return module


# ---------------------------------------------------------------------------
# Google Drive: status & folder
# ---------------------------------------------------------------------------


def test_gdrive_status_with_credentials_file(client, gd, monkeypatch):
    from alfa import tools

    repo = Path(gd.REPO_ROOT)
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "gdrive_credentials.json").write_text(
        json.dumps({"client_email": "sa@x", "project_id": "proj"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        tools,
        "gdrive_status",
        lambda: {
            "connected": True,
            "auth_mode": "service_account",
            "user": {"emailAddress": "active@x"},
            "storage_quota": {"limit": 1},
            "mounted_drives": [{"name": "GDrive1"}],
            "has_local_mounts": True,
        },
    )
    out = client.get("/api/gdrive/status").json()
    assert out["status"] == "success"
    assert out["client_email"] == "active@x"
    assert out["project_id"] == "proj"
    assert out["has_local_mounts"] is True
    assert out["error"] == ""


def test_gdrive_status_disconnected_and_bad_file(client, gd, monkeypatch):
    from alfa import tools

    repo = Path(gd.REPO_ROOT)
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "gdrive_credentials.json").write_text("bukan-json", encoding="utf-8")
    monkeypatch.setattr(
        tools,
        "gdrive_status",
        lambda: {"connected": False, "message": "no creds"},
    )
    out = client.get("/api/gdrive/status").json()
    assert out["connected"] is False
    assert out["error"] == "no creds"
    assert out["client_email"] == ""
    assert out["default_folder_name"] == "alfa agent"


def test_gdrive_status_exception(client, gd, monkeypatch):
    from alfa import tools

    monkeypatch.setattr(
        tools, "gdrive_status", MagicMock(side_effect=RuntimeError("drive down"))
    )
    out = client.get("/api/gdrive/status").json()
    assert out["status"] == "error"
    assert out["connected"] is False
    assert "drive down" in out["message"]


def test_gdrive_set_folder(client, isolated_db):
    from alfa.core import database

    assert client.post("/api/gdrive/folder", json={}).status_code == 400
    out = client.post(
        "/api/gdrive/folder", json={"folder_id": " F1 ", "folder_name": " Arsip "}
    ).json()
    assert out["status"] == "success"
    assert out["folder_id"] == "F1"
    assert out["folder_name"] == "Arsip"
    with database.get_sync_db() as conn:
        rows = dict(
            conn.execute(
                "SELECT key, value FROM system_settings WHERE key LIKE 'gdrive_default_folder_%'"
            ).fetchall()
        )
    assert rows["gdrive_default_folder_id"] == "F1"
    assert rows["gdrive_default_folder_url"].endswith("/F1")


# ---------------------------------------------------------------------------
# Google Drive: credentials
# ---------------------------------------------------------------------------


def test_gdrive_save_credentials_requires_input(client):
    assert client.post("/api/gdrive/credentials").status_code == 400


def test_gdrive_save_credentials_raw_json(client, gd, monkeypatch):
    from alfa import tools
    from alfa.integrations.gdrive import secret_store

    saved = []
    monkeypatch.setattr(
        secret_store, "save_secret", lambda name, value: saved.append(name) or True
    )
    monkeypatch.setattr(
        tools, "gdrive_status", lambda: {"connected": True}
    )
    payload = json.dumps(
        {"type": "service_account", "client_email": "sa@x", "project_id": "p"}
    )
    out = client.post(
        "/api/gdrive/credentials", data={"raw_json": payload}
    ).json()
    assert out["status"] == "success"
    assert out["client_email"] == "sa@x"
    assert out["connected"] is True
    assert saved
    assert (Path(gd.REPO_ROOT) / "gdrive_credentials.json").exists()


def test_gdrive_save_credentials_file_upload(client, gd, monkeypatch):
    from alfa import tools
    from alfa.integrations.gdrive import secret_store

    monkeypatch.setattr(secret_store, "save_secret", lambda *a: False)
    monkeypatch.setattr(tools, "gdrive_status", lambda: {"connected": False})
    content = json.dumps({"client_email": "legacy@x"}).encode()
    out = client.post(
        "/api/gdrive/credentials",
        files={"file": ("key.json", content, "application/json")},
    ).json()
    assert out["status"] == "success"
    assert out["client_email"] == "legacy@x"


def test_gdrive_save_credentials_invalid_kind(client, gd):
    out = client.post(
        "/api/gdrive/credentials", data={"raw_json": json.dumps({"foo": "bar"})}
    ).json()
    assert out["status"] == "error"
    assert "Service Account" in out["message"]


def test_gdrive_save_credentials_invalid_json(client, gd):
    out = client.post("/api/gdrive/credentials", data={"raw_json": "{rusak"}).json()
    assert out["status"] == "error"


def test_gdrive_delete_credentials(client, gd, monkeypatch):
    from alfa.core import database
    from alfa.integrations.gdrive import secret_store

    cred = Path(gd.REPO_ROOT) / "gdrive_credentials.json"
    cred.write_text("{}", encoding="utf-8")
    deleted = []
    monkeypatch.setattr(
        secret_store, "delete_secret", lambda name: deleted.append(name)
    )
    with database.get_sync_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO system_settings (key, value) VALUES ('gdrive_credentials_json', 'x')"
        )
        conn.commit()
    out = client.delete("/api/gdrive/credentials").json()
    assert out["status"] == "success"
    assert not cred.exists()
    assert deleted
    with database.get_sync_db() as conn:
        row = conn.execute(
            "SELECT 1 FROM system_settings WHERE key = 'gdrive_credentials_json'"
        ).fetchone()
    assert row is None


# ---------------------------------------------------------------------------
# Google Drive: OAuth
# ---------------------------------------------------------------------------


def test_gdrive_oauth_secret_check_variants(client, gd):
    path = Path(gd.REPO_ROOT) / "gdrive_oauth_client_secret.json"
    out = client.get("/api/gdrive/oauth/secret-check").json()
    assert out["exists"] is False
    assert out["kind"] == ""

    path.write_text(json.dumps({"installed": {"client_id": "x"}}), encoding="utf-8")
    out = client.get("/api/gdrive/oauth/secret-check").json()
    assert out["exists"] is True
    assert out["kind"] == "oauth_client"

    path.write_text(
        json.dumps({"type": "service_account", "private_key": "k"}), encoding="utf-8"
    )
    out = client.get("/api/gdrive/oauth/secret-check").json()
    assert out["kind"] == "service_account"
    assert out["exists"] is False

    path.write_text("bukan-json", encoding="utf-8")
    out = client.get("/api/gdrive/oauth/secret-check").json()
    assert out["kind"] == "invalid_json"
    assert out["exists"] is False


def test_gdrive_oauth_upload_secret(client, gd, monkeypatch):
    from alfa import tools

    assert client.post("/api/gdrive/oauth/upload-secret").status_code == 400
    seen = {}
    monkeypatch.setattr(
        tools,
        "gdrive_save_oauth_client_secret",
        lambda content: seen.update(content=content) or {"status": "success"},
    )
    out = client.post(
        "/api/gdrive/oauth/upload-secret",
        files={"file": ("secret.json", b'{"installed": {}}', "application/json")},
    ).json()
    assert out["status"] == "success"
    assert seen["content"] == '{"installed": {}}'
    out = client.post(
        "/api/gdrive/oauth/upload-secret", data={"raw_json": '{"web": {}}'}
    ).json()
    assert out["status"] == "success"
    assert seen["content"] == '{"web": {}}'


def test_gdrive_oauth_auth_url(client, monkeypatch):
    from alfa import tools

    seen = {}
    monkeypatch.setattr(
        tools,
        "gdrive_oauth_get_auth_url",
        lambda redirect_uri: seen.update(uri=redirect_uri) or {"status": "success"},
    )
    out = client.get("/api/gdrive/oauth/auth-url").json()
    assert out["status"] == "success"
    assert seen["uri"].endswith("/api/gdrive/oauth/callback")


def test_gdrive_oauth_callback_error_param(client):
    res = client.get("/api/gdrive/oauth/callback", params={"error": "access_denied"})
    assert res.status_code == 200
    assert "Dibatalkan" in res.text


def test_gdrive_oauth_callback_missing_code(client):
    assert client.get("/api/gdrive/oauth/callback").status_code == 400


def test_gdrive_oauth_callback_success_and_failure(client, monkeypatch):
    from alfa import tools

    seen = {}
    monkeypatch.setattr(
        tools,
        "gdrive_oauth_exchange_code",
        lambda auth_code, redirect_uri: seen.update(
            code=auth_code, uri=redirect_uri
        )
        or {"status": "success"},
    )
    res = client.get("/api/gdrive/oauth/callback", params={"code": "abc"})
    assert "Berhasil" in res.text
    assert seen["code"] == "abc"
    assert seen["uri"].endswith("/api/gdrive/oauth/callback")

    monkeypatch.setattr(
        tools,
        "gdrive_oauth_exchange_code",
        lambda **kwargs: {"status": "error", "message": "token rusak"},
    )
    res = client.get("/api/gdrive/oauth/callback", params={"code": "abc"})
    assert "Gagal Menyimpan Token" in res.text
    assert "token rusak" in res.text


def test_gdrive_oauth_exchange_endpoint(client, monkeypatch):
    from alfa import tools

    assert client.post("/api/gdrive/oauth/exchange-code", json={}).status_code == 400
    monkeypatch.setattr(
        tools,
        "gdrive_oauth_exchange_code",
        lambda auth_code, redirect_uri: {"status": "success", "code": auth_code},
    )
    out = client.post(
        "/api/gdrive/oauth/exchange-code", json={"code": " kode "}
    ).json()
    assert out["status"] == "success"
    assert out["code"] == "kode"


def test_gdrive_oauth_start_success_and_error(gd, monkeypatch):
    from alfa import tools

    monkeypatch.setattr(
        tools, "gdrive_oauth_login", lambda: {"status": "success"}
    )
    assert asyncio.run(gd.gdrive_oauth_start())["status"] == "success"

    def boom():
        raise RuntimeError("oauth crash")  # noqa: TRY003

    monkeypatch.setattr(tools, "gdrive_oauth_login", boom)
    out = asyncio.run(gd.gdrive_oauth_start())
    assert out["status"] == "error"
    assert "oauth crash" in out["message"]


def test_gdrive_oauth_start_timeout(gd, monkeypatch):
    from alfa import tools

    monkeypatch.setattr(tools, "gdrive_oauth_login", lambda: {"status": "success"})

    async def fake_wait_for(awaitable, timeout):
        awaitable.close()
        raise asyncio.TimeoutError

    monkeypatch.setattr(gd.asyncio, "wait_for", fake_wait_for)
    out = asyncio.run(gd.gdrive_oauth_start())
    assert out["status"] == "error"
    assert "Waktu login habis" in out["message"]


def test_gdrive_oauth_logout(client, monkeypatch):
    from alfa import tools

    monkeypatch.setattr(tools, "gdrive_oauth_logout", lambda: {"status": "success"})
    assert client.post("/api/gdrive/oauth/logout").json()["status"] == "success"


# ---------------------------------------------------------------------------
# Google Drive: files, upload, folder, sync
# ---------------------------------------------------------------------------


def test_gdrive_list_files_direct(client, monkeypatch):
    from alfa import tools

    monkeypatch.setattr(
        tools,
        "gdrive_list_files",
        lambda folder_id, query, limit: {"status": "success", "files": [1]},
    )
    out = client.get("/api/gdrive/files?query=x&limit=5").json()
    assert out["files"] == [1]


def test_gdrive_list_files_falls_back_to_mount(client, monkeypatch):
    from alfa import tools

    monkeypatch.setattr(
        tools, "gdrive_list_files", lambda **k: {"status": "error", "message": "no"}
    )
    monkeypatch.setattr(
        tools,
        "gdrive_list_mounted_files",
        lambda drive_index, query, limit: {
            "status": "success",
            "total_found": 2,
            "files": [
                {"path": "/m/a", "name": "a", "is_dir": True, "size": 0},
                {"path": "/m/b.txt", "name": "b.txt", "is_dir": False, "size": 10},
            ],
        },
    )
    out = client.get("/api/gdrive/files").json()
    assert out["source"] == "local_mount"
    assert out["folder_id"] == "local_mount"
    assert out["files"][0]["mimeType"].endswith("folder")
    assert out["files"][1]["mimeType"] == "application/octet-stream"


def test_gdrive_list_files_fallback_error(client, monkeypatch):
    from alfa import tools

    monkeypatch.setattr(
        tools, "gdrive_list_files", lambda **k: {"status": "error", "message": "x"}
    )
    monkeypatch.setattr(
        tools, "gdrive_list_mounted_files", lambda **k: {"status": "error"}
    )
    out = client.get("/api/gdrive/files").json()
    assert out["status"] == "error"


def test_gdrive_upload_requires_input(client):
    assert client.post("/api/gdrive/upload").status_code == 400


def test_gdrive_upload_file_success(client, tmp_path, monkeypatch):
    from alfa import tools

    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    monkeypatch.setattr(tools, "get_pdf_output_dir", lambda name: str(upload_dir))
    seen = {}
    monkeypatch.setattr(
        tools,
        "gdrive_upload_file",
        lambda filepath, folder_id, custom_filename=None: seen.update(
            path=filepath, folder=folder_id
        )
        or {"status": "success", "file_name": "x.txt"},
    )
    out = client.post(
        "/api/gdrive/upload",
        files={"file": ("x.txt", b"halo", "text/plain")},
        data={"folder_id": "F"},
    ).json()
    assert out["status"] == "success"
    assert seen["folder"] == "F"
    assert Path(seen["path"]).read_bytes() == b"halo"


def test_gdrive_upload_file_fallback_copy(client, tmp_path, monkeypatch):
    from alfa import tools

    monkeypatch.setattr(tools, "get_pdf_output_dir", lambda name: str(tmp_path))
    monkeypatch.setattr(
        tools, "gdrive_upload_file", lambda **k: {"status": "error", "message": "api"}
    )
    monkeypatch.setattr(
        tools,
        "gdrive_copy_to_drive",
        lambda source_path, drive_index: {"status": "success", "copied": source_path},
    )
    out = client.post(
        "/api/gdrive/upload",
        files={"file": ("x.txt", b"halo", "text/plain")},
    ).json()
    assert out["status"] == "success"
    assert out["copied"].endswith("x.txt")


def test_gdrive_upload_path_branch(client, monkeypatch):
    from alfa import tools

    monkeypatch.setattr(
        tools,
        "gdrive_upload_file",
        lambda filepath, folder_id, custom_filename=None: {
            "status": "success",
            "path": filepath,
        },
    )
    out = client.post(
        "/api/gdrive/upload", data={"filepath": "/tmp/laporan.pdf"}
    ).json()
    assert out["status"] == "success"
    assert out["path"] == "/tmp/laporan.pdf"

    monkeypatch.setattr(
        tools, "gdrive_upload_file", lambda **k: {"status": "error", "message": "x"}
    )
    monkeypatch.setattr(
        tools,
        "gdrive_copy_to_drive",
        lambda **k: {"status": "error", "message": "copy"},
    )
    out = client.post("/api/gdrive/upload", data={"filepath": "/tmp/x"}).json()
    assert out["status"] == "error"


def test_gdrive_create_folder(client, monkeypatch):
    from alfa import tools

    assert client.post("/api/gdrive/create-folder", json={}).status_code == 400
    seen = {}
    monkeypatch.setattr(
        tools,
        "gdrive_create_folder",
        lambda folder_name, parent_folder_id: seen.update(
            name=folder_name, parent=parent_folder_id
        )
        or {"status": "success"},
    )
    out = client.post(
        "/api/gdrive/create-folder", json={"name": "Baru", "parent_id": "P"}
    ).json()
    assert out["status"] == "success"
    assert seen == {"name": "Baru", "parent": "P"}


def test_gdrive_sync_brain(client, monkeypatch):
    from alfa import tools

    seen = {}
    monkeypatch.setattr(
        tools,
        "gdrive_sync_to_second_brain",
        lambda folder_id, limit: seen.update(folder=folder_id, limit=limit)
        or {"status": "success"},
    )
    assert client.post("/api/gdrive/sync-brain").json()["status"] == "success"
    assert seen == {"folder": "", "limit": 10}
    seen.clear()
    client.post(
        "/api/gdrive/sync-brain", json={"folder_id": "F", "limit": 900}
    )
    assert seen == {"folder": "F", "limit": 100}
    client.post("/api/gdrive/sync-brain", json={"limit": "abc"})
    assert seen == {"folder": "", "limit": 10}


# ---------------------------------------------------------------------------
# WhatsApp: validators
# ---------------------------------------------------------------------------


def test_validate_media_rules(wa):
    assert wa._validate_media_rules("x") == ["Field 'rules' harus berupa array."]
    assert wa._validate_media_rules([{}] * 31) == ["Maksimal 30 aturan."]
    errs = wa._validate_media_rules(
        [
            "bukan-dict",
            {"name": ""},
            {"name": "A", "types": "foto", "naming": ""},
            {"name": "a", "types": ["foto"], "naming": "x"},
            {"name": "B", "types": [], "naming": "x"},
        ]
    )
    assert any("bukan objek" in e for e in errs)
    assert any("nama kosong" in e for e in errs)
    assert any("duplikat" in e for e in errs)
    assert any("jenis file" in e for e in errs)
    assert any("pola nama" in e for e in errs)
    assert wa._validate_media_rules(
        [{"name": "A", "types": ["foto"], "naming": "{sender}"}]
    ) == []


def test_validate_wa_formats(wa):
    assert wa._validate_wa_formats({}) == ["Field 'formats' harus berupa array."]
    assert wa._validate_wa_formats([{}] * 51) == ["Maksimal 50 format."]
    errs = wa._validate_wa_formats(
        [
            "bukan-dict",
            {"name": "", "tab": "", "keywords": [], "columns": []},
            {
                "name": "A",
                "tab": "Tab",
                "keywords": ["k"],
                "columns": [{"title": "", "source": ""}, {}],
            },
            {
                "name": "A",
                "tab": "Tab",
                "keywords": [""],
                "columns": [{"title": "t", "value": "v"}] * 31,
            },
            {
                "name": "B",
                "tab": "Tab",
                "keywords": ["k"],
                "columns": [{"title": "T", "source": "S"}],
            },
        ]
    )
    assert any("bukan objek" in e for e in errs)
    assert any("duplikat" in e for e in errs)
    assert any("tab" in e and "dipakai" in e for e in errs)
    assert any("keywords" in e for e in errs)
    assert any("judul kosong" in e for e in errs)
    assert any("sumber kosong" in e for e in errs)
    assert any("maksimal 30 kolom" in e for e in errs)
    assert wa._validate_wa_formats(
        [
            {
                "name": "A",
                "tab": "Tab",
                "keywords": ["k"],
                "columns": [{"title": "T", "source": "S"}],
            }
        ]
    ) == []


# ---------------------------------------------------------------------------
# WhatsApp: helper Drive & log
# ---------------------------------------------------------------------------


class _Exec:
    def __init__(self, value=None, error=None):
        self.value = value
        self.error = error

    def execute(self):
        if self.error:
            raise self.error
        return self.value


class _FakeDriveFiles:
    def __init__(self, list_results, create_results):
        self.list_results = list(list_results)
        self.create_results = list(create_results)
        self.created_bodies = []

    def list(self, **kwargs):
        return self.list_results.pop(0)

    def create(self, body=None, **kwargs):
        self.created_bodies.append(dict(body or {}))
        return self.create_results.pop(0)


class _FakeDriveService:
    def __init__(self, files):
        self._files = files

    def files(self):
        return self._files


def test_gdrive_ensure_subfolder_found(wa, monkeypatch):
    files = _FakeDriveFiles([_Exec({"files": [{"id": "FOUND"}]})], [])
    monkeypatch.setattr(wa.tools, "_get_default_gdrive_folder_id", lambda: "P")
    monkeypatch.setattr(
        wa.tools, "_get_gdrive_service", lambda: _FakeDriveService(files)
    )
    assert wa._gdrive_ensure_subfolder("X") == "FOUND"
    assert files.created_bodies == []


def test_gdrive_ensure_subfolder_parent_fails_then_fallback(wa, monkeypatch):
    files = _FakeDriveFiles(
        [_Exec(error=OSError("404")), _Exec({"files": [{"id": "FALLBACK"}]})], []
    )
    monkeypatch.setattr(wa.tools, "_get_default_gdrive_folder_id", lambda: "P")
    monkeypatch.setattr(
        wa.tools, "_get_gdrive_service", lambda: _FakeDriveService(files)
    )
    assert wa._gdrive_ensure_subfolder("X") == "FALLBACK"


def test_gdrive_ensure_subfolder_both_queries_fail_creates(wa, monkeypatch):
    files = _FakeDriveFiles(
        [_Exec(error=OSError("a")), _Exec(error=OSError("b"))],
        [_Exec({"id": "NEW"})],
    )
    monkeypatch.setattr(wa.tools, "_get_default_gdrive_folder_id", lambda: "P")
    monkeypatch.setattr(
        wa.tools, "_get_gdrive_service", lambda: _FakeDriveService(files)
    )
    assert wa._gdrive_ensure_subfolder("X") == "NEW"
    assert files.created_bodies[0]["parents"] == ["P"]


def test_gdrive_ensure_subfolder_no_parent_query_error(wa, monkeypatch):
    files = _FakeDriveFiles([_Exec(error=OSError("a"))], [_Exec({"id": "ROOT"})])
    monkeypatch.setattr(wa.tools, "_get_default_gdrive_folder_id", lambda: "")
    monkeypatch.setattr(
        wa.tools, "_get_gdrive_service", lambda: _FakeDriveService(files)
    )
    assert wa._gdrive_ensure_subfolder("X") == "ROOT"
    assert "parents" not in files.created_bodies[0]


def test_gdrive_ensure_subfolder_create_notfound_retries_root(wa, monkeypatch):
    files = _FakeDriveFiles(
        [_Exec({"files": []})],
        [_Exec(error=RuntimeError("notFound")), _Exec({"id": "ROOT2"})],
    )
    monkeypatch.setattr(wa.tools, "_get_default_gdrive_folder_id", lambda: "P")
    monkeypatch.setattr(
        wa.tools, "_get_gdrive_service", lambda: _FakeDriveService(files)
    )
    assert wa._gdrive_ensure_subfolder("X") == "ROOT2"
    assert "parents" in files.created_bodies[0]
    assert "parents" not in files.created_bodies[1]


def test_gdrive_ensure_subfolder_create_other_error(wa, monkeypatch):
    files = _FakeDriveFiles(
        [_Exec({"files": []})], [_Exec(error=RuntimeError("quota"))]
    )
    monkeypatch.setattr(wa.tools, "_get_default_gdrive_folder_id", lambda: "P")
    monkeypatch.setattr(
        wa.tools, "_get_gdrive_service", lambda: _FakeDriveService(files)
    )
    with pytest.raises(RuntimeError):
        wa._gdrive_ensure_subfolder("X")


def test_log_wa_drive_upload_caps_and_recovers(wa, tmp_path, monkeypatch):
    target = tmp_path / "wa" / "drive_uploads.json"
    monkeypatch.setattr(wa, "WA_DRIVE_UPLOADS_FILE", str(target))
    target.parent.mkdir()
    target.write_text("bukan-json", encoding="utf-8")
    wa._log_wa_drive_upload({"n": 1})
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["uploads"][0]["n"] == 1

    for i in range(3, 210):
        wa._log_wa_drive_upload({"n": i})
    data = json.loads(target.read_text(encoding="utf-8"))
    assert len(data["uploads"]) == 200


def test_log_wa_drive_upload_write_error_swallowed(wa, monkeypatch):
    monkeypatch.setattr(wa, "WA_DRIVE_UPLOADS_FILE", "/proc/tidak-bisa/drive.json")
    wa._log_wa_drive_upload({"n": 1})


# ---------------------------------------------------------------------------
# WhatsApp: QR, logout, reports
# ---------------------------------------------------------------------------


class _FakeHTTPResponse:
    def __init__(self, status_code=200, data=None):
        self.status_code = status_code
        self._data = data or {}

    def json(self):
        return self._data


def _patch_httpx(monkeypatch, get=None, post=None):
    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url):
            result = get
            if isinstance(result, BaseException):
                raise result
            return result

        async def post(self, url):
            result = post
            if isinstance(result, BaseException):
                raise result
            return result

    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)


def test_wa_qr_from_service(client, monkeypatch):
    _patch_httpx(monkeypatch, get=_FakeHTTPResponse(data={"status": "READY"}))
    assert client.get("/api/wa/qr").json()["status"] == "READY"


def test_wa_qr_from_status_file_with_qr(client, monkeypatch, tmp_path):
    _patch_httpx(monkeypatch, get=_FakeHTTPResponse(status_code=500))
    home = Path(os.environ["HOME"])
    (home / ".alfa").mkdir(parents=True)
    (home / ".alfa" / "wa_status.json").write_text(
        json.dumps({"qr": "qr-string", "status": "SCAN", "updated_at": "now"}),
        encoding="utf-8",
    )

    fake_qrcode = types.ModuleType("qrcode")

    class Img:
        def save(self, buf, format=None):
            buf.write(b"PNG")

    fake_qrcode.make = lambda value: Img()
    monkeypatch.setitem(sys.modules, "qrcode", fake_qrcode)
    out = client.get("/api/wa/qr").json()
    assert out["status"] == "SCAN"
    assert out["qr_available"] is True
    assert out["qr_data_url"].startswith("data:image/png;base64,")


def test_wa_qr_status_file_without_qrcode(client, monkeypatch):
    _patch_httpx(monkeypatch, get=_FakeHTTPResponse(status_code=500))
    home = Path(os.environ["HOME"])
    (home / ".alfa").mkdir(parents=True)
    (home / ".alfa" / "wa_status.json").write_text(
        json.dumps({"qr": "abc", "status": "SCAN"}), encoding="utf-8"
    )
    monkeypatch.setitem(sys.modules, "qrcode", None)
    out = client.get("/api/wa/qr").json()
    assert out["status"] == "DISCONNECTED"


def test_wa_qr_corrupt_status_file(client, monkeypatch):
    import httpx

    _patch_httpx(monkeypatch, get=httpx.ConnectError("down"))
    home = Path(os.environ["HOME"])
    (home / ".alfa").mkdir(parents=True)
    (home / ".alfa" / "wa_status.json").write_text("{rusak", encoding="utf-8")
    out = client.get("/api/wa/qr").json()
    assert out["status"] == "DISCONNECTED"


def test_wa_logout(client, monkeypatch):
    _patch_httpx(monkeypatch, post=_FakeHTTPResponse(data={"status": "ok"}))
    assert client.post("/api/wa/logout").json()["status"] == "ok"
    _patch_httpx(monkeypatch, post=_FakeHTTPResponse(status_code=500))
    out = client.post("/api/wa/logout").json()
    assert out["status"] == "error"
    import httpx

    _patch_httpx(monkeypatch, post=httpx.ConnectError("refused"))
    assert client.post("/api/wa/logout").json()["status"] == "error"


def test_wa_reports_from_service(client, monkeypatch):
    _patch_httpx(monkeypatch, get=_FakeHTTPResponse(data={"reports": [1]}))
    assert client.get("/api/wa/reports").json()["reports"] == [1]


def test_wa_reports_fallback_files(client, monkeypatch):
    from alfa.integrations import google_sheets

    _patch_httpx(monkeypatch, get=_FakeHTTPResponse(status_code=500))
    home = Path(os.environ["HOME"])
    botdir = home / "wa-sheets-bot"
    botdir.mkdir(parents=True)
    (botdir / "recorded_reports.json").write_text(
        json.dumps([{"id": 1}, {"id": 2}]), encoding="utf-8"
    )
    (botdir / "formats.json").write_text(
        json.dumps({"formats": [{"name": "A"}]}), encoding="utf-8"
    )
    monkeypatch.setattr(google_sheets, "get_spreadsheet_id", lambda: "SID")
    out = client.get("/api/wa/reports").json()
    assert out["spreadsheet_id"] == "SID"
    assert out["total_recorded"] == 2
    assert out["formats"] == [{"name": "A"}]


def test_wa_reports_corrupt_files(client, monkeypatch):
    import httpx

    from alfa.integrations import google_sheets

    _patch_httpx(monkeypatch, get=httpx.ConnectError("down"))
    home = Path(os.environ["HOME"])
    botdir = home / "wa-sheets-bot"
    botdir.mkdir(parents=True)
    (botdir / "recorded_reports.json").write_text("{rusak", encoding="utf-8")
    (botdir / "formats.json").write_text("[1]", encoding="utf-8")
    monkeypatch.setattr(google_sheets, "get_spreadsheet_id", lambda: "")
    out = client.get("/api/wa/reports").json()
    assert out["reports"] == []
    assert out["formats"] == []


# ---------------------------------------------------------------------------
# WhatsApp: spreadsheet, parse material
# ---------------------------------------------------------------------------


def test_wa_spreadsheet_id(client, monkeypatch):
    from alfa.integrations import google_sheets

    assert client.post("/api/wa/spreadsheet-id", json={}).json()["status"] == "error"
    monkeypatch.setattr(
        google_sheets,
        "set_spreadsheet_id",
        lambda sid: {"status": "success", "id": sid},
    )
    out = client.post(
        "/api/wa/spreadsheet-id", json={"spreadsheet_id": " S1 "}
    ).json()
    assert out["id"] == "S1"


def test_wa_parse_material(client, monkeypatch):
    from alfa.integrations import google_sheets

    assert client.post("/api/wa/parse-material", json={}).json()["status"] == "error"
    seen = {}
    monkeypatch.setattr(
        google_sheets,
        "parse_and_record_material_text",
        lambda **kwargs: seen.update(kwargs) or {"status": "success"},
    )
    out = client.post(
        "/api/wa/parse-material",
        json={
            "body": " 3 tiang ",
            "sender": "Budi",
            "group": "Grup A",
            "timestamp": "t",
            "tab_name": "Sheet1",
        },
    ).json()
    assert out["status"] == "success"
    assert seen["text"] == "3 tiang"
    assert seen["source"] == "WA: Grup A"
    assert seen["tab_name"] == "Sheet1"


# ---------------------------------------------------------------------------
# WhatsApp: media rules
# ---------------------------------------------------------------------------


def test_wa_get_media_rules(client, wa, tmp_path):
    out = client.get("/api/wa/media-rules").json()
    assert out["exists"] is False
    assert out["rules"] == []

    target = Path(wa.WA_BOT_MEDIA_RULES_FILE)
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps({"rules": [{"name": "A"}]}), encoding="utf-8")
    out = client.get("/api/wa/media-rules").json()
    assert out["exists"] is True
    assert out["rules"] == [{"name": "A"}]

    target.write_text("{rusak", encoding="utf-8")
    out = client.get("/api/wa/media-rules").json()
    assert out["status"] == "error"


def test_wa_save_media_rules_validation(client):
    out = client.post("/api/wa/media-rules", json={"rules": "x"}).json()
    assert out["status"] == "error"
    assert out["validation_errors"]


def test_wa_save_media_rules_success_and_backup(client, wa):
    rules = [
        {
            "name": " Foto ",
            "enabled": True,
            "types": ["foto", "pdf"],
            "keyword": "k",
            "folder": "",
            "naming": "{sender}-{timestamp}",
        }
    ]
    first = client.post("/api/wa/media-rules", json={"rules": rules}).json()
    assert first["status"] == "success"
    assert first["saved"] == 1
    saved = json.loads(Path(wa.WA_BOT_MEDIA_RULES_FILE).read_text(encoding="utf-8"))
    assert saved["rules"][0]["name"] == "Foto"
    assert saved["rules"][0]["folder"] == "Umum"

    second = client.post("/api/wa/media-rules", json={"rules": rules}).json()
    assert second["status"] == "success"
    assert Path(wa.WA_BOT_MEDIA_RULES_FILE + ".bak").exists()


def test_wa_save_media_rules_write_error(client, wa, monkeypatch):
    monkeypatch.setattr(
        wa.os, "replace", MagicMock(side_effect=OSError("disk penuh"))
    )
    out = client.post(
        "/api/wa/media-rules",
        json={"rules": [{"name": "A", "types": ["foto"], "naming": "x"}]},
    ).json()
    assert out["status"] == "error"


# ---------------------------------------------------------------------------
# WhatsApp: drive uploads & media upload
# ---------------------------------------------------------------------------


def test_wa_drive_uploads(client, wa):
    out = client.get("/api/wa/drive-uploads").json()
    assert out["total"] == 0

    target = Path(wa.WA_DRIVE_UPLOADS_FILE)
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps({"uploads": [{"file_name": "a"}]}), encoding="utf-8")
    out = client.get("/api/wa/drive-uploads").json()
    assert out["total"] == 1

    target.write_text("{rusak", encoding="utf-8")
    out = client.get("/api/wa/drive-uploads").json()
    assert out["status"] == "error"


def test_wa_media_upload_success(client, wa, monkeypatch, tmp_path):
    from alfa import tools

    monkeypatch.setattr(wa, "_gdrive_ensure_subfolder", lambda name: "SUB")
    monkeypatch.setattr(
        tools,
        "gdrive_upload_file",
        lambda filepath, folder_id, custom_filename=None: {
            "status": "success",
            "file_name": custom_filename,
            "web_link": "https://drive/x",
        },
    )
    monkeypatch.setattr(wa, "_log_wa_drive_upload", lambda entry: None)
    real_join = os.path.join

    def fake_join(*parts):
        if len(parts) >= 2 and str(parts[0]) == "/dev/shm" and parts[1] == "alfa_wa_media":
            return str(tmp_path / "wa_media")
        if parts and str(parts[0]) == "/dev/shm/alfa_wa_media":
            return real_join(str(tmp_path / "wa_media"), *parts[1:])
        return real_join(*parts)

    monkeypatch.setattr(wa.os.path, "join", fake_join)
    out = client.post(
        "/api/wa/media-upload",
        files={"file": ("foto.jpg", b"img", "image/jpeg")},
        data={"format_name": "Foto", "sender": "A", "group": "G"},
    ).json()
    assert out["status"] == "success"
    assert out["folder"] == "WA Media / Foto"
    assert out["file_name"] == "foto.jpg"


def test_wa_media_upload_returns_error_result(client, wa, monkeypatch, tmp_path):
    from alfa import tools

    monkeypatch.setattr(wa, "_gdrive_ensure_subfolder", lambda name: "SUB")
    monkeypatch.setattr(
        tools, "gdrive_upload_file", lambda **k: {"status": "error", "message": "x"}
    )
    real_join = os.path.join

    def fake_join(*parts):
        if len(parts) >= 2 and str(parts[0]) == "/dev/shm" and parts[1] == "alfa_wa_media":
            return str(tmp_path / "wa_media")
        if parts and str(parts[0]) == "/dev/shm/alfa_wa_media":
            return real_join(str(tmp_path / "wa_media"), *parts[1:])
        return real_join(*parts)

    monkeypatch.setattr(wa.os.path, "join", fake_join)
    out = client.post(
        "/api/wa/media-upload",
        files={"file": ("x.pdf", b"pdf", "application/pdf")},
    ).json()
    assert out["status"] == "error"


def test_wa_media_upload_exception(client, wa, monkeypatch, tmp_path):
    from alfa import tools

    monkeypatch.setattr(wa, "_gdrive_ensure_subfolder", lambda name: "SUB")
    monkeypatch.setattr(
        tools,
        "gdrive_upload_file",
        MagicMock(side_effect=RuntimeError("drive mati")),
    )
    real_join = os.path.join

    def fake_join(*parts):
        if len(parts) >= 2 and str(parts[0]) == "/dev/shm" and parts[1] == "alfa_wa_media":
            return str(tmp_path / "wa_media")
        if parts and str(parts[0]) == "/dev/shm/alfa_wa_media":
            return real_join(str(tmp_path / "wa_media"), *parts[1:])
        return real_join(*parts)

    monkeypatch.setattr(wa.os.path, "join", fake_join)
    out = client.post(
        "/api/wa/media-upload",
        files={"file": ("x.pdf", b"pdf", "application/pdf")},
    ).json()
    assert out["status"] == "error"
    assert "drive mati" in out["message"]


# ---------------------------------------------------------------------------
# WhatsApp: formats
# ---------------------------------------------------------------------------


def test_wa_formats_get(client, wa):
    out = client.get("/api/wa/formats").json()
    assert out["exists"] is False

    target = Path(wa.WA_BOT_FORMATS_FILE)
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps({"formats": [{"name": "A"}]}), encoding="utf-8")
    out = client.get("/api/wa/formats").json()
    assert out["exists"] is True
    assert out["formats"] == [{"name": "A"}]

    target.write_text("[1]", encoding="utf-8")
    assert client.get("/api/wa/formats").json()["formats"] == []

    target.write_text("{rusak", encoding="utf-8")
    assert client.get("/api/wa/formats").json()["status"] == "error"


def test_wa_formats_save_validation(client):
    out = client.post("/api/wa/formats", json={"formats": "x"}).json()
    assert out["status"] == "error"
    assert out["validation_errors"]


def test_wa_formats_save_success_and_backup(client, wa):
    payload = {
        "formats": [
            {
                "name": " Laporan ",
                "keywords": [" laporan "],
                "tab": "Sheet1",
                "columns": [{"title": " Nama ", "source": " sender "}],
            }
        ]
    }
    first = client.post("/api/wa/formats", json=payload).json()
    assert first["status"] == "success"
    assert first["saved"] == 1
    saved = json.loads(Path(wa.WA_BOT_FORMATS_FILE).read_text(encoding="utf-8"))
    assert saved["formats"][0]["columns"] == [{"title": "Nama", "source": "sender"}]

    second = client.post("/api/wa/formats", json=payload).json()
    assert second["status"] == "success"
    assert Path(wa.WA_BOT_FORMATS_FILE + ".bak").exists()


def test_wa_formats_save_write_error(client, wa, monkeypatch):
    monkeypatch.setattr(
        wa.os, "replace", MagicMock(side_effect=OSError("disk penuh"))
    )
    out = client.post(
        "/api/wa/formats",
        json={
            "formats": [
                {
                    "name": "A",
                    "keywords": ["k"],
                    "tab": "T",
                    "columns": [{"title": "t", "source": "s"}],
                }
            ]
        },
    ).json()
    assert out["status"] == "error"
