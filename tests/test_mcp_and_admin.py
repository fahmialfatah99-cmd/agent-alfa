"""MCP client & dashboard admin — jalur integrasi yang belum teruji.

* `alfa/mcp/client.py` — penemuan OAuth, connect/disconnect, pemanggilan tool
  remote, dengan validasi skema URL (anti SSRF).
* `alfa/dashboard/routes/system/settings_admin.py` — endpoint pengaturan
  sistem, redaksi secret, dan pemilihan main brain.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# ── MCP client ───────────────────────────────────────────────────────────────


class TestMcpUrlValidation:
    def test_skema_bukan_http_ditolak(self):
        from alfa.mcp import client

        for bad in ("file:///etc/passwd", "ftp://x/y", "javascript:alert(1)", ""):
            with pytest.raises(ValueError):
                client._validate_http_url(bad)

    def test_http_https_diterima(self):
        from alfa.mcp import client

        client._validate_http_url("http://127.0.0.1:9000/mcp")
        client._validate_http_url("https://example.com/mcp")


class TestMcpStore:
    def test_load_save_roundtrip(self, tmp_path, monkeypatch):
        from alfa.mcp import client

        store_file = tmp_path / "mcp.json"
        monkeypatch.setattr(client, "STORE_FILE", str(store_file))
        monkeypatch.setattr(client, "STATE_DIR", str(tmp_path))
        client._save({"a": {"token": "t"}})
        assert store_file.exists()
        loaded = client._load()
        assert loaded["a"]["token"] == "t"

    def test_load_file_tidak_ada_kosong(self, tmp_path, monkeypatch):
        from alfa.mcp import client

        monkeypatch.setattr(client, "STORE_FILE", str(tmp_path / "nope.json"))
        monkeypatch.setattr(client, "STATE_DIR", str(tmp_path))
        assert client._load() == {}

    def test_load_file_rusak_tidak_crash(self, tmp_path, monkeypatch):
        from alfa.mcp import client

        bad = tmp_path / "mcp.json"
        bad.write_text("{bukan json", encoding="utf-8")
        monkeypatch.setattr(client, "STORE_FILE", str(bad))
        monkeypatch.setattr(client, "STATE_DIR", str(tmp_path))
        assert client._load() == {}


class TestMcpConnect:
    def test_start_connect_server_tak_dikenal(self, tmp_path, monkeypatch):
        from alfa.mcp import client

        monkeypatch.setattr(client, "STORE_FILE", str(tmp_path / "mcp.json"))
        monkeypatch.setattr(client, "STATE_DIR", str(tmp_path))
        res = client.start_connect("srv-tidak-ada", "http://localhost:9999/cb")
        assert res.get("status") == "error"
        assert "tak dikenal" in res.get("message", "")

    def test_start_connect_menyimpan_state(self, tmp_path, monkeypatch):
        from alfa.mcp import client

        monkeypatch.setattr(client, "STORE_FILE", str(tmp_path / "mcp.json"))
        monkeypatch.setattr(client, "STATE_DIR", str(tmp_path))
        monkeypatch.setattr(
            client, "SERVERS", {"srv1": {"url": "https://mcp.example/mcp", "scopes": ["mcp:full"]}}
        )
        monkeypatch.setattr(
            client,
            "_discover_oauth",
            lambda base: {
                "authorization_endpoint": "https://auth.example/authorize",
                "registration_endpoint": "https://auth.example/register",
                "token_endpoint": "https://auth.example/token",
            },
        )
        monkeypatch.setattr(
            client,
            "_http",
            lambda method, url, body=None, headers=None, timeout=25: {
                "client_id": "cid",
                "client_secret": "sec",
            },
        )
        res = client.start_connect("srv1", "http://localhost:9999/callback")
        assert res.get("status") == "success", res
        assert res["auth_url"].startswith("https://auth.example/authorize?")
        store = client._load()
        assert "srv1" in store
        assert store["srv1"]["client_id"] == "cid"
        assert store["srv1"]["connected"] is False

    def test_finish_connect_state_cocok_berhasil(self, tmp_path, monkeypatch):
        from alfa.mcp import client

        monkeypatch.setattr(client, "STORE_FILE", str(tmp_path / "mcp.json"))
        monkeypatch.setattr(client, "STATE_DIR", str(tmp_path))
        client._save(
            {
                "srv1": {
                    "url": "https://mcp.example/mcp",
                    "state": "st",
                    "client_id": "cid",
                    "code_verifier": "v",
                    "redirect_uri": "http://localhost:9999/cb",
                    "token_endpoint": "https://auth.example/token",
                }
            }
        )
        monkeypatch.setattr(
            client,
            "_post_form",
            lambda url, body, headers=None: {
                "access_token": "tok",
                "refresh_token": "ref",
                "expires_in": 3600,
            },
        )
        res = client.finish_connect("kode", "srv1:st")
        assert res.get("status") == "success", res
        assert client._load()["srv1"]["connected"] is True

    def test_finish_connect_state_salah_ditolak(self, tmp_path, monkeypatch):
        from alfa.mcp import client

        monkeypatch.setattr(client, "STORE_FILE", str(tmp_path / "mcp.json"))
        monkeypatch.setattr(client, "STATE_DIR", str(tmp_path))
        client._save(
            {
                "srv1": {
                    "url": "https://mcp.example/mcp",
                    "state": "st",
                    "client_id": "cid",
                    "code_verifier": "v",
                    "redirect_uri": "http://localhost:9999/cb",
                    "token_endpoint": "https://auth.example/token",
                }
            }
        )
        res = client.finish_connect("kode", "srv1:state_lain")
        assert res.get("status") == "error"


class TestMcpCallTool:
    def test_call_tool_tanpa_server_dikenal(self, tmp_path, monkeypatch):
        from alfa.mcp import client

        monkeypatch.setattr(client, "STORE_FILE", str(tmp_path / "mcp.json"))
        monkeypatch.setattr(client, "STATE_DIR", str(tmp_path))
        res = client.call_tool_sync("tidak-ada", "apa_saja", {})
        assert res.get("status") == "error"

    def test_list_tools_tanpa_server_dikenal(self, tmp_path, monkeypatch):
        from alfa.mcp import client

        monkeypatch.setattr(client, "STORE_FILE", str(tmp_path / "mcp.json"))
        monkeypatch.setattr(client, "STATE_DIR", str(tmp_path))
        res = client.list_tools_sync("tidak-ada")
        assert res.get("status") == "error"

    def test_call_tool_menggunakan_token_tersimpan(self, tmp_path, monkeypatch):
        from alfa.mcp import client

        monkeypatch.setattr(client, "STORE_FILE", str(tmp_path / "mcp.json"))
        monkeypatch.setattr(client, "STATE_DIR", str(tmp_path))
        client._save(
            {
                "srv1": {
                    "url": "http://127.0.0.1:9100/mcp",
                    "access_token": "tok",
                    "connected": True,
                    "tools": [{"name": "ping"}],
                }
            }
        )
        captured = {}

        async def _fake_call(url, token, tool, args, timeout=60.0):
            captured.update({"url": url, "token": token, "tool": tool, "args": args})
            return {"status": "success", "result": "pong"}

        monkeypatch.setattr(client, "_call_remote", _fake_call)
        res = client.call_tool_sync("srv1", "ping", {"x": 1})
        assert res.get("status") == "success"
        assert captured["token"] == "tok"
        assert captured["tool"] == "ping"
        assert captured["args"] == {"x": 1}

    def test_list_tools_menggunakan_token_tersimpan(self, tmp_path, monkeypatch):
        from alfa.mcp import client

        monkeypatch.setattr(client, "STORE_FILE", str(tmp_path / "mcp.json"))
        monkeypatch.setattr(client, "STATE_DIR", str(tmp_path))
        client._save(
            {
                "srv1": {
                    "url": "http://127.0.0.1:9100/mcp",
                    "access_token": "tok",
                    "connected": True,
                }
            }
        )
        captured = {}

        async def _fake_list(url, token, timeout=30.0):
            captured.update({"url": url, "token": token})
            return [{"name": "ping"}]

        monkeypatch.setattr(client, "_list_remote", _fake_list)
        res = client.list_tools_sync("srv1")
        assert res.get("status") == "success"
        assert captured["token"] == "tok"


# ── Dashboard admin ──────────────────────────────────────────────────────────


class TestSettingsAdmin:
    def test_redact_db_settings_menyembunyikan_secret(self):
        from alfa.dashboard.routes.system.settings_admin import redact_db_settings

        out = redact_db_settings(
            {
                "gemini_api_key": "sk-secret",
                "credentials_json": '{"client_secret": "abc"}',
                "db_url": "postgres://user:pass@host/db",
                "plain": "oke",
            }
        )
        # Key rahasia → hanya status "set", nilainya tidak dikirim.
        assert out.get("gemini_api_key_set") == "1"
        assert "sk-secret" not in json.dumps(out)
        assert "client_secret" not in json.dumps(out)
        # Key biasa → nilainya tetap.
        assert out.get("plain") == "oke"

    def test_endpoint_pengaturan_memerlukan_admin(self, monkeypatch):
        from fastapi.testclient import TestClient

        from alfa.dashboard import app as pkg_app
        from alfa.dashboard.routes import auth as auth_mod

        monkeypatch.setattr(auth_mod, "DASHBOARD_AUTH_TOKEN", "tok")
        monkeypatch.setenv("DASHBOARD_AUTH_TOKEN", "tok")
        monkeypatch.setenv("ALFA_INSECURE_LOCAL", "false")
        client = TestClient(pkg_app)
        res = client.get("/api/settings")
        assert res.status_code in (401, 403), res.status_code

    def test_endpoint_pengaturan_terbuka_untuk_admin(self, monkeypatch):
        from fastapi.testclient import TestClient

        from alfa.dashboard import app as pkg_app
        from alfa.dashboard.routes import auth as auth_mod

        monkeypatch.setattr(auth_mod, "DASHBOARD_AUTH_TOKEN", "")
        monkeypatch.setenv("DASHBOARD_AUTH_TOKEN", "")
        monkeypatch.setenv("ALFA_INSECURE_LOCAL", "true")
        client = TestClient(pkg_app)
        res = client.get("/api/settings")
        assert res.status_code == 200, res.text
        assert isinstance(res.json(), dict)
