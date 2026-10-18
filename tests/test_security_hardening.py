"""Regression tests: hardening temuan kritis audit keamanan 2026-10-18.

Mengunci perilaku berikut agar tidak regresi:
1. Boot guard menolak kombinasi env berbahaya (unrestricted + bind publik,
   unrestricted + host-exec tanpa pengakuan).
2. WebSocket: lokal-only saat token kosong, cek Origin (anti cross-site hijack),
   wajib token saat auth aktif.
3. /api/auth/register: ditutup (invite-token / admin-only) setelah bootstrap.
4. /api/settings: admin-gated + redaksi nilai rahasia (gdrive token, dsb.).
5. Sandbox Docker: --network none default (anti eksfiltrasi).
"""

import contextlib
import json
import sqlite3
import sys
from pathlib import Path

import pytest

# ── 1. BOOT GUARD ─────────────────────────────────────────────────────────────


class TestBootGuard:
    def _check(self):
        from alfa.core.security_boot_guard import check_runtime_security

        return check_runtime_security("test")

    def test_unrestricted_plus_public_bind_fatal(self, monkeypatch):
        monkeypatch.setenv("ALFA_UNRESTRICTED", "true")
        monkeypatch.setenv("DASHBOARD_HOST", "0.0.0.0")
        with pytest.raises(RuntimeError) as ei:
            self._check()
        assert "DASHBOARD_HOST" in str(ei.value)

    def test_unrestricted_ipv6_public_bind_fatal(self, monkeypatch):
        monkeypatch.setenv("ALFA_UNRESTRICTED", "true")
        monkeypatch.setenv("DASHBOARD_HOST", "::")
        with pytest.raises(RuntimeError):
            self._check()

    def test_unrestricted_plus_host_exec_wajib_ack(self, monkeypatch):
        monkeypatch.setenv("ALFA_UNRESTRICTED", "true")
        monkeypatch.setenv("ALFA_ALLOW_HOST_EXEC", "true")
        monkeypatch.setenv("DASHBOARD_HOST", "127.0.0.1")
        monkeypatch.delenv("ALFA_UNRESTRICTED_ACK", raising=False)
        with pytest.raises(RuntimeError) as ei:
            self._check()
        assert "ALFA_UNRESTRICTED_ACK" in str(ei.value)

    def test_unrestricted_plus_host_exec_dengan_ack_lolos(self, monkeypatch):
        monkeypatch.setenv("ALFA_UNRESTRICTED", "true")
        monkeypatch.setenv("ALFA_ALLOW_HOST_EXEC", "true")
        monkeypatch.setenv("DASHBOARD_HOST", "127.0.0.1")
        monkeypatch.setenv("ALFA_UNRESTRICTED_ACK", "yes")
        self._check()  # tidak raise

    def test_konfigurasi_aman_lolos(self, monkeypatch):
        monkeypatch.setenv("ALFA_UNRESTRICTED", "false")
        monkeypatch.setenv("ALFA_ALLOW_HOST_EXEC", "false")
        monkeypatch.setenv("DASHBOARD_HOST", "0.0.0.0")  # boleh — unrestricted off
        self._check()

    def test_is_public_bind(self):
        from alfa.core.security_boot_guard import is_public_bind

        assert is_public_bind("0.0.0.0")
        assert is_public_bind("::")
        assert is_public_bind("")
        assert not is_public_bind("127.0.0.1")
        assert not is_public_bind("192.168.1.5")


# ── 2. WEBSOCKET AUTH ─────────────────────────────────────────────────────────


class _FakeWS:
    def __init__(self, ip="8.8.8.8", headers=None, query=None, cookies=None):
        from types import SimpleNamespace

        self.client = SimpleNamespace(host=ip) if ip else None
        self.headers = headers or {}
        self.query_params = query or {}
        self.cookies = cookies or {}


class TestWsAuthorization:
    def _auth(self):
        from alfa.dashboard import websocket as ws_mod

        return ws_mod._is_ws_authorized

    def test_tanpa_token_ip_eksternal_ditolak(self, monkeypatch):
        from alfa.dashboard import websocket as ws_mod

        monkeypatch.setattr(ws_mod, "DASHBOARD_AUTH_TOKEN", "")
        ws = _FakeWS(ip="192.168.1.50")
        assert self._auth()(ws) is False

    def test_tanpa_token_loopback_diloloskan(self, monkeypatch):
        from alfa.dashboard import websocket as ws_mod

        monkeypatch.setattr(ws_mod, "DASHBOARD_AUTH_TOKEN", "")
        assert self._auth()(_FakeWS(ip="127.0.0.1")) is True
        assert self._auth()(_FakeWS(ip="::1")) is True
        assert self._auth()(_FakeWS(ip="::ffff:127.0.0.1")) is True

    def test_localhost_loopback_variants(self):
        from alfa.dashboard.websocket import _is_loopback_ip

        assert _is_loopback_ip("127.0.0.1")
        assert _is_loopback_ip("::1")
        assert _is_loopback_ip("::ffff:127.0.0.1")
        assert not _is_loopback_ip("192.168.1.50")
        assert not _is_loopback_ip("")
        assert not _is_loopback_ip("::2")

    def test_origin_luar_ditolak_tanpa_token(self, monkeypatch):
        from alfa.dashboard import websocket as ws_mod

        monkeypatch.setattr(ws_mod, "DASHBOARD_AUTH_TOKEN", "")
        ws = _FakeWS(
            ip="127.0.0.1", headers={"origin": "https://evil.example.com"}
        )
        assert self._auth()(ws) is False

    def test_origin_sama_host_null_diloloskan(self, monkeypatch):
        from alfa.dashboard import websocket as ws_mod

        monkeypatch.setattr(ws_mod, "DASHBOARD_AUTH_TOKEN", "")
        assert self._auth()(
            _FakeWS(ip="127.0.0.1", headers={"origin": "http://localhost:8080",
                                             "host": "localhost:8080"})
        ) is True
        # Tidak ada header Origin (non-browser client) → lolos
        assert self._auth()(_FakeWS(ip="127.0.0.1")) is True

    def test_mode_token_salah_ditolak(self, monkeypatch):
        from alfa.dashboard import websocket as ws_mod

        monkeypatch.setattr(ws_mod, "DASHBOARD_AUTH_TOKEN", "secret-token")
        ws = _FakeWS(ip="127.0.0.1", query={"token": "salah"})
        assert self._auth()(ws) is False

    def test_mode_token_konsisten_diloloskan(self, monkeypatch):
        from alfa.dashboard import websocket as ws_mod

        monkeypatch.setattr(ws_mod, "DASHBOARD_AUTH_TOKEN", "secret-token")
        ws = _FakeWS(ip="10.0.0.5", query={"token": "secret-token"})
        assert self._auth()(ws) is True


# ── 3. REGISTRASI DITUTUP (INVITE TOKEN) ──────────────────────────────────────


class TestRegisterPolicy:
    def _policy(self):
        from alfa.dashboard.routes.auth import _register_policy

        return _register_policy

    def test_user_pertama_bootstrap_admin(self):
        is_admin, denial = self._policy()(0, False, None)
        assert is_admin is True and denial == ""

    def test_non_admin_tanpa_invite_ditolak(self):
        is_admin, denial = self._policy()(3, False, {"is_admin": False})
        assert is_admin is False and "invite" in denial.lower()

    def test_invite_valid_lolos_non_admin(self):
        is_admin, denial = self._policy()(3, True, None)
        assert is_admin is False and denial == ""

    def test_admin_sesi_lolos_tanpa_invite(self):
        is_admin, denial = self._policy()(3, False, {"is_admin": True})
        assert is_admin is False and denial == ""


class _SqliteCtx:
    """Contextmanager fake pengganti database.get_sync_db utk test."""

    def __init__(self, db_file: Path):
        self.db_file = str(db_file)

    @contextlib.contextmanager
    def __call__(self):  # noqa: C901
        conn = sqlite3.connect(self.db_file)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()


class TestInviteToken:
    @pytest.fixture
    def fake_db(self, tmp_path, monkeypatch):
        import alfa.core.database as db_mod

        ctx = _SqliteCtx(tmp_path / "test_invite.db")
        monkeypatch.setattr(db_mod, "get_sync_db", ctx)
        # Reset flag ensure table agar dibuat ulang pada DB fake
        Path(ctx.db_file).touch()
        return ctx

    def test_create_consume_roundtrip(self, fake_db):
        from alfa.dashboard.routes import auth as auth_mod

        info = auth_mod.create_invite_token("admin", 3600)
        token = info["invite_token"]
        assert token and info["ttl_seconds"] == 3600
        assert auth_mod.consume_invite_token(token) is True
        # Sekali pakai: konsumsi kedua ditolak
        assert auth_mod.consume_invite_token(token) is False
        # Token acak ditolak
        assert auth_mod.consume_invite_token("tidak-ada") is False

    def test_register_ditutup_setelah_bootstrap(self, fake_db, monkeypatch):
        """Setelah ada user, register anonim tanpa invite ditolak; dengan
        invite diterima sebagai non-admin. DB hermetik (tidak sentuh DB real)."""
        from fastapi.testclient import TestClient

        from alfa.dashboard import app as pkg_app
        from alfa.dashboard.routes import auth as auth_mod

        monkeypatch.setattr(auth_mod, "DASHBOARD_AUTH_TOKEN", "")  # local-admin mode

        # Fake pool: DB dengan 2 user eksisting
        class _FakeCursor:
            def execute(self, *_a, **_k):
                pass

            def fetchone(self):
                return (2,)

        class _FakeConn:
            def cursor(self):
                return _FakeCursor()

        class _FakePool:
            def acquire(self):
                return _FakeConn()

            def release(self, _conn):
                return None

        import alfa.core.database as db_mod

        monkeypatch.setattr(db_mod, "get_connection_pool", lambda: _FakePool())
        # create_user dibongkar-pasang agar tidak menulis DB
        created: dict = {}

        def _fake_create(username, password, telegram_id=None, is_admin=False):
            created["username"] = username
            created["is_admin"] = is_admin
            return {
                "user_id": 999,
                "username": username,
                "is_admin": is_admin,
            }

        monkeypatch.setattr(auth_mod, "create_user", _fake_create)

        client = TestClient(pkg_app)

        # 1) Tanpa invite → 403
        res = client.post(
            "/api/auth/register",
            json={"username": "penyusup", "password": "password123"},
        )
        assert res.status_code == 403, res.text
        assert "penyusup" not in created

        # 2) Admin (local) membuat invite → token valid
        res_inv = client.post("/api/auth/invite", json={"ttl_seconds": 3600})
        assert res_inv.status_code == 200, res_inv.text
        token = res_inv.json()["invite_token"]

        # 3) Dengan invite → diterima, non-admin
        res_ok = client.post(
            "/api/auth/register",
            json={
                "username": "user_invite",
                "password": "password123",
                "invite_token": token,
            },
        )
        assert res_ok.status_code == 200, res_ok.text
        assert created["is_admin"] is False
        # 4) Token terpakai: konsumsi ulang ditolak
        assert auth_mod.consume_invite_token(token) is False


# ── 4. REDAKSI SECRETS / SETTINGS ─────────────────────────────────────────────


class TestSettingsRedaction:
    def test_keys_rahasia_diruliska(self):
        from alfa.dashboard.routes.system.settings_admin import redact_db_settings

        raw = {
            "gdrive_oauth_token_json": '{"refresh_token": "SECRET-XYZ"}',
            "gdrive_credentials_json": '{"client_secret": "TOP-SECRET"}',
            "telegram_bot_token": "123:ABC",
            "system_instruction": "Kamu adalah ALFA",
            "site_huggingface": "aktif",
            "main_brain_model": "gemini-3.6-flash",
        }
        out = redact_db_settings(raw)
        blob = json.dumps(out)
        assert "SECRET-XYZ" not in blob
        assert "TOP-SECRET" not in blob
        assert "123:ABC" not in blob
        assert "Telegram Bot Token" not in blob
        # status set tercatat
        assert out.get("gdrive_oauth_token_json_set") == "1"
        assert out.get("telegram_bot_token_set") == "1"
        # data biasa tetap utuh
        assert out["system_instruction"] == "Kamu adalah ALFA"
        assert out["main_brain_model"] == "gemini-3.6-flash"

    def test_json_secret_terdeteksi_via_isi(self):
        from alfa.dashboard.routes.system.settings_admin import (
            _SECRET_VALUE_HINTS,
            redact_db_settings,
        )

        assert _SECRET_VALUE_HINTS
        out = redact_db_settings({"custom_blob_json": '{"private_key": "-----BEGIN"}'})
        assert "-----BEGIN" not in json.dumps(out)
        assert out.get("custom_blob_json_set") == "1"


# ── 5. SANDBOX DOCKER NETWORK ─────────────────────────────────────────────────
class TestSandboxNetwork:
    def test_default_none(self):
        from alfa.tools.system.constants import _sandbox_network

        assert _sandbox_network() == "none"

    def test_override_env(self, monkeypatch):
        from alfa.tools.system.constants import _sandbox_network

        monkeypatch.setenv("ALFA_SANDBOX_NETWORK", "bridge")
        assert _sandbox_network() == "bridge"

    def test_common_args_mengandung_network_none(self):
        from alfa.tools.system.execution import _docker_common_args

        args = _docker_common_args("123")
        i = args.index("--network")
        assert args[i + 1] == "none"
        assert "no-new-privileges" in args
        assert "--cap-drop" in args

    def test_common_args_hormati_override(self, monkeypatch):
        from alfa.tools.system import execution as exec_mod

        monkeypatch.setenv("ALFA_SANDBOX_NETWORK", "bridge")
        args = exec_mod._docker_common_args("1")
        i = args.index("--network")
        assert args[i + 1] == "bridge"


# ── 6. RATE LIMIT ─────────────────────────────────────────────────────────────


class TestRateLimit:
    def _reset(self):
        from alfa.dashboard.routes.auth import _rate_buckets

        _rate_buckets.clear()

    def test_limit_tercapai(self):
        from alfa.dashboard.routes.auth import _rate_limit

        self._reset()
        for _ in range(5):
            ok, _ = _rate_limit("u1", 5, 60)
            assert ok
        ok, retry = _rate_limit("u1", 5, 60)
        assert not ok and retry > 0

    def test_bucket_terpisah(self):
        from alfa.dashboard.routes.auth import _rate_limit

        self._reset()
        for _ in range(5):
            _rate_limit("a", 5, 60)
        ok, _ = _rate_limit("b", 5, 60)
        assert ok

    def test_reset_setelah_window(self, monkeypatch):
        from alfa.dashboard.routes import auth as auth_mod

        self._reset()
        import time

        base = time.monotonic()
        monkeypatch.setattr(time, "monotonic", lambda: base)
        for _ in range(2):
            auth_mod._rate_limit("w", 2, 10)
        ok, _ = auth_mod._rate_limit("w", 2, 10)
        assert not ok
        monkeypatch.setattr(time, "monotonic", lambda: base + 11)
        ok, _ = auth_mod._rate_limit("w", 2, 10)
        assert ok


# ── 7. ENDPOINT /api/settings GUARD ────────────────────────────────────────────


class TestSettingsEndpointAdminGated:
    @pytest.fixture
    def client_with_admin_session(self, monkeypatch, tmp_path):
        from fastapi.testclient import TestClient

        import alfa.core.database as db_mod
        from alfa.dashboard import app as pkg_app
        from alfa.dashboard.routes import auth as auth_mod
        from alfa.dashboard.routes.system import settings_admin as sa

        monkeypatch.setattr(auth_mod, "DASHBOARD_AUTH_TOKEN", "tok")

        def _validate(token):
            if token == "sess-admin":
                return {
                    "user_id": 1,
                    "username": "boss",
                    "is_admin": True,
                }
            if token == "sess-member":
                return {
                    "user_id": 2,
                    "username": "member",
                    "is_admin": False,
                }
            return None

        monkeypatch.setattr(auth_mod, "validate_session", _validate)

        # Fake DB berisi rahasia simulasi + repo tanpa .env
        fake_db = _SqliteCtx(tmp_path / "fake_settings.db")
        conn = sqlite3.connect(fake_db.db_file, uri=False)
        conn.row_factory = sqlite3.Row
        conn.execute(
            "CREATE TABLE IF NOT EXISTS system_settings "
            "(key TEXT PRIMARY KEY, value TEXT)"
        )
        conn.execute(
            "INSERT INTO system_settings VALUES "
            "('gdrive_oauth_token_json', '{\"refresh_token\": \"RT-XYZ\"}')"
        )
        conn.execute(
            "INSERT INTO system_settings VALUES "
            "('gdrive_credentials_json', '{\"client_secret\": \"CS-XYZ\"}')"
        )
        conn.commit()
        conn.close()

        monkeypatch.setattr(db_mod, "get_sync_db", fake_db)
        monkeypatch.setattr(sa.database, "get_sync_db", fake_db)
        monkeypatch.setattr(sa.database, "list_api_keys_sync", lambda: [])
        monkeypatch.setattr(sa, "REPO_ROOT", str(tmp_path))  # tanpa .env real
        monkeypatch.setenv("DASHBOARD_AUTH_TOKEN", "tok")

        client = TestClient(pkg_app)
        return client

    def test_member_non_admin_ditolak(self, client_with_admin_session):
        res = client_with_admin_session.get(
            "/api/settings", cookies={"session_token": "sess-member"}
        )
        assert res.status_code == 403

    def test_anonim_ditolak(self, client_with_admin_session):
        res = client_with_admin_session.get("/api/settings")
        assert res.status_code in (401, 403)

    def test_admin_mendapat_redaksi(self, client_with_admin_session):
        res = client_with_admin_session.get(
            "/api/settings", cookies={"session_token": "sess-admin"}
        )
        assert res.status_code == 200
        blob = json.dumps(res.json())
        assert "RT-XYZ" not in blob
        assert "CS-XYZ" not in blob
        assert "gdrive_oauth_token_json_set" in blob


# ── 8. SSRF GUARD (`alfa/security/net_guard.py`) ──────────────────────────────


class TestNetGuard:
    def _check(self, url):
        from alfa.security.net_guard import is_public_http_url

        return is_public_http_url(url)

    def test_url_publik_lolos(self, monkeypatch):
        monkeypatch.setenv("ALFA_ALLOW_PRIVATE_FETCH", "false")
        ok, _ = self._check("https://example.com/file.pdf")
        assert ok

    def test_skema_non_http_ditolak(self):
        for url in ("file:///etc/passwd", "gopher://evil", "ftp://x.com/a", "@/local"):
            ok, reason = self._check(url)
            assert not ok, url

    def test_ip_literal_forbidden(self):
        for url in (
            "http://127.0.0.1:8080/api/settings",
            "http://10.0.0.5/x",
            "http://192.168.1.3/y",
            "http://169.254.169.254/latest/meta-data",
            "http://[::1]:8080/z",
        ):
            ok, reason = self._check(url)
            assert not ok, url

    def test_hostname_dip_kata_internal(self):
        ok, _ = self._check("http://localhost/x")
        assert not ok
        ok, _ = self._check("http://metadata.google.internal/computeMetadata")
        assert not ok

    def test_dns_ke_ip_private_ditolak(self, monkeypatch):
        from alfa.security import net_guard as ng

        monkeypatch.setenv("ALFA_ALLOW_PRIVATE_FETCH", "false")

        def fake_getaddrinfo(host, port=None, proto=None, **_k):
            return [(2, 1, 6, "", ("10.0.0.99", 0))]

        monkeypatch.setattr(ng.socket, "getaddrinfo", fake_getaddrinfo)
        ok, reason = self._check("https://internal-corpan.example.com/data")
        assert not ok and "10.0.0.99" in reason

    def test_bypass_eksplisit_operator(self, monkeypatch):
        monkeypatch.setenv("ALFA_ALLOW_PRIVATE_FETCH", "true")
        ok, _ = self._check("http://192.168.1.3/internal")
        assert ok
        monkeypatch.setenv("ALFA_ALLOW_PRIVATE_FETCH", "false")
        ok, _ = self._check("http://192.168.1.3/internal")
        assert not ok

    def test_assert_raise_unsafe(self):
        from alfa.security.net_guard import UnsafeUrlError, assert_public_http_url

        with pytest.raises(UnsafeUrlError):
            assert_public_http_url("http://169.254.169.254/x")
        assert_public_http_url("https://example.com/x")


class TestDownloadToolGuards:
    def test_filename_traversal_dilucuti(self, tmp_path, monkeypatch):
        from alfa.tools.system import network as net_mod

        monkeypatch.setattr(net_mod, "SANDBOX_DIR", str(tmp_path / "sbx"))
        dest = net_mod.download_file_from_url(
            "http://127.0.0.1:9999/x", "/home/x/.bashrc"
        )
        blob = str(dest)
        assert ".bashrc" not in blob or "bashrc" == dest.get("file", "")
        # SSRF guard menolak lebih dahulu — hasil error, bukan file
        assert dest.get("status") == "error" or "SSRF" in blob or "ditolak" in blob
        assert not (tmp_path / "sbx" / ".bashrc").exists()

    def test_filename_benign_logits_ke_sandbox(self, tmp_path, monkeypatch):
        from alfa.tools.system import network as net_mod

        sandbox = tmp_path / "sbx"
        sandbox.mkdir()
        monkeypatch.setattr(net_mod, "SANDBOX_DIR", str(sandbox))
        # URL agar httpx tidak benar-benar dipanggil → mock client.get
        import httpx as _httpx

        class _FakeResp:
            status_code = 200
            content = b"hello"

            def raise_for_status(self):
                return None

        class _FakeClient:
            def __init__(self, *a, **k):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return None

            def get(self, *a, **k):
                return _FakeResp()

        monkeypatch.setattr(_httpx, "Client", _FakeClient)
        result = net_mod.download_file_from_url(
            "https://example.com/laporan.csv", "hasil.csv"
        )
        assert result.get("status") in ("success", "error")
        if result.get("status") == "success":
            assert (sandbox / "hasil.csv").exists()

    def test_fetch_web_page_content_blokir_internal(self):
        from alfa.tools.web import search as search_mod

        res = search_mod.fetch_web_page_content("http://127.0.0.1:8080/api/settings")
        assert res.get("status") == "error" or "SSRF" in str(res.get("message", ""))


# ── 9. IDENTITAS ANTI-SPOOF (X-User-Id) ───────────────────────────────────────


class TestIdentityPolicy:
    def _get_uid(self, request):
        from alfa.dashboard.common import get_primary_user_id

        return get_primary_user_id(request)

    def _fake_request(self, header_uid=None, query_uid=None):
        from types import SimpleNamespace

        headers = {"X-User-Id": header_uid} if header_uid else {}
        query = SimpleNamespace(get=lambda k: query_uid if k == "user_id" else None)
        return SimpleNamespace(headers=headers, query_params=query)

    def test_token_mode_header_dipercaya_no_longer(self, monkeypatch):
        monkeypatch.setattr(
            "alfa.dashboard.common.DASHBOARD_AUTH_TOKEN", "tok"
        )
        monkeypatch.setenv("ALLOWED_USER_IDS", "111222333")
        req = self._fake_request(header_uid="999888777")
        assert self._get_uid(req) == 111222333

    def test_lokal_mode_header_masih_dipercaya(self, monkeypatch):
        monkeypatch.setenv("ALLOWED_USER_IDS", "111222333")
        monkeypatch.setattr(
            "alfa.dashboard.common.DASHBOARD_AUTH_TOKEN", ""
        )
        req = self._fake_request(header_uid="999888777")
        assert self._get_uid(req) == 999888777

    def test_tanpa_request_fallback_whitelist(self, monkeypatch):
        monkeypatch.setenv("ALLOWED_USER_IDS", "111222333")
        assert self._get_uid(None) == 111222333


# ── 10. RBAC SWEEP MEKANIS — endpoint sensitif selalu ditolak tanpa admin ─────


_SENSITIVE_ENDPOINTS = [
    ("GET", "/api/settings"),
    ("GET", "/api/models-for-key?key_id=1"),
    ("GET", "/api/keys"),
    ("GET", "/api/keys/usage"),
    ("GET", "/api/stats"),
    ("GET", "/api/system/home-dir"),
    ("GET", "/api/services"),
    ("GET", "/api/services/logs"),
    ("GET", "/api/vault/list"),
    ("GET", "/api/workspace/tree?path=documents"),
    ("GET", "/api/workspace/file?path=x"),
    ("GET", "/api/artifacts/download?path=x"),
    ("GET", "/api/security/permission-audit"),
    ("GET", "/api/security/trust-scores"),
    ("GET", "/api/chat/export"),
    ("GET", "/api/scraper/batches"),
    ("GET", "/api/brain/export"),
    ("POST", "/api/tools/execute"),
    ("POST", "/api/plugins/execute"),
    ("POST", "/api/chat/model"),
    ("POST", "/api/chat/execute-code"),
    ("POST", "/api/memory/add"),
    ("POST", "/api/memory/delete"),
    ("POST", "/api/brain/vector/ingest"),
    ("POST", "/api/brain/vector/delete"),
    ("POST", "/api/pipelines/p/run"),
    ("POST", "/api/pipelines/p"),
    ("POST", "/api/pipelines/p/enable"),
    ("POST", "/api/scraper/universal"),
    ("POST", "/api/scraper/custom-batch"),
    ("POST", "/api/scraper/modern-lab"),
    ("POST", "/api/vault/passkey/toggle"),
    ("POST", "/api/security/audit"),
    ("DELETE", "/api/chat/history"),
]


class TestRbacSweep:
    """Semua endpoint sensitif → 401 (anonim, token mode) & 403 (member non-admin)."""

    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch):
        from fastapi.testclient import TestClient

        from alfa.dashboard import app as pkg_app
        from alfa.dashboard.routes import auth as auth_mod

        monkeypatch.setattr(auth_mod, "DASHBOARD_AUTH_TOKEN", "sweeptoken")

        def _validate(token):
            if token == "sess-admin":
                return {"user_id": 1, "username": "boss", "is_admin": True}
            if token == "sess-member":
                return {"user_id": 2, "username": "member", "is_admin": False}
            return None

        monkeypatch.setattr(auth_mod, "validate_session", _validate)
        monkeypatch.setenv("DASHBOARD_AUTH_TOKEN", "sweeptoken")
        self.client = TestClient(pkg_app)
        self.monkeypatch = monkeypatch

    @pytest.mark.parametrize("method,path", _SENSITIVE_ENDPOINTS)
    def test_anonim_ditolak(self, method, path):
        if method == "GET":
            res = self.client.get(path)
        elif method == "POST":
            res = self.client.post(path, json={})
        else:
            res = self.client.delete(path)
        assert res.status_code == 401, (method, path, res.status_code)

    @pytest.mark.parametrize("method,path", _SENSITIVE_ENDPOINTS)
    def test_member_nonadmin_ditolak(self, method, path):
        cookies = {"session_token": "sess-member"}
        if method == "GET":
            res = self.client.get(path, cookies=cookies)
        elif method == "POST":
            res = self.client.post(path, json={}, cookies=cookies)
        else:
            res = self.client.delete(path, cookies=cookies)
        assert res.status_code == 403, (method, path, res.status_code)


# ── 11. GDRIVE SECRETS → VAULT ────────────────────────────────────────────────


class TestGdriveSecretStore:
    @pytest.fixture
    def vault_env(self, tmp_path, monkeypatch):
        """DB sementara + master key file sementara."""
        import alfa.core.database as db_mod

        db_file = tmp_path / "gdrive_test.db"
        monkeypatch.setenv("ALFA_DB_PATH", str(db_file))
        monkeypatch.setenv("ENCRYPTION_KEY", "x" * 32)
        monkeypatch.setattr(db_mod, "DB_PATH", str(db_file))

        from alfa.security import vault as _shadow_pkg  # noqa: F401 (shadowed attr)

        # alfa/security/__init__.py menimpa attr 'vault' dgn INSTANCE — ambil
        # modul asli lewat sys.modules agar global DB_PATH bisa di-patch.
        vault_mod = sys.modules["alfa.security.vault"]
        monkeypatch.setattr(vault_mod, "DB_PATH", str(db_file))
        monkeypatch.setattr(
            vault_mod, "_get_or_create_master_key", lambda: b"A" * 32
        )
        vault_mod._init_vault_db()  # tabel vault di DB sementara

        ctx = _SqliteCtx(db_file)
        monkeypatch.setattr(db_mod, "get_sync_db", ctx)
        with sqlite3.connect(str(db_file)) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS system_settings "
                "(key TEXT PRIMARY KEY, value TEXT)"
            )
        return db_file

    def test_save_load_roundtrip_vault(self, vault_env):
        from alfa.integrations.gdrive import secret_store

        token = '{"refresh_token": "RT-RAHASIA"}'
        assert secret_store.save_secret(secret_store.OAUTH_SECRET_NAME, token) is True
        loaded = secret_store.load_secret(secret_store.OAUTH_SECRET_NAME)
        assert loaded == token

    def test_plaintext_legacy_tidak_masuk_setting_response(self, vault_env):
        from alfa.integrations.gdrive import secret_store

        with sqlite3.connect(str(vault_env)) as conn:
            conn.execute(
                "INSERT INTO system_settings VALUES "
                "('gdrive_oauth_token_json', '{\"refresh_token\":\"PLAINTXT\"}')"
            )
        report = secret_store.migrate_legacy_plaintext()
        assert report["gdrive_oauth_token_json"] is True
        # plaintext sudah dihapus dari system_settings
        with sqlite3.connect(str(vault_env)) as conn:
            row = conn.execute(
                "SELECT value FROM system_settings WHERE key='gdrive_oauth_token_json'"
            ).fetchone()
        assert row is None
        # dan kini hidup terenkripsi di vault
        assert "PLAINTXT" in (secret_store.load_secret(secret_store.OAUTH_SECRET_NAME) or "")

    def test_load_oauth_token_fallback_legacy(self, vault_env):
        from alfa.integrations.gdrive import secret_store

        with sqlite3.connect(str(vault_env)) as conn:
            conn.execute(
                "INSERT INTO system_settings VALUES "
                "('gdrive_oauth_token_json', '{\"refresh_token\":\"LEG-1\"}')"
            )
        info = secret_store.load_oauth_token()
        assert info and info["refresh_token"] == "LEG-1"
