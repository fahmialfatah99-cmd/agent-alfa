"""Phase 6 coverage: autentikasi dashboard (hash/sesi, rate-limit, invite, magic-link, middleware, endpoint).

Hermetic: SQLite diarahkan ke ``tmp_path`` (tabel auth dibuat sendiri), dua
aplikasi FastAPI mini (endpoint tanpa middleware + middleware autentikasi),
dan token dibuat dalam tes. Tidak menyentuh DB produksi atau mengirim apa pun.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import hmac
import json
import os
import sqlite3
from datetime import datetime, timedelta

import pytest
from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient
from starlette.middleware.base import BaseHTTPMiddleware


def _raw_db() -> sqlite3.Connection:
    """Koneksi SQLite langsung ke DB tes (dibaca dari env ALFA_DB_PATH)."""
    return sqlite3.connect(os.environ["ALFA_DB_PATH"])


def _update(sql: str, params: tuple = ()) -> None:
    """Jalankan UPDATE/INSERT langsung ke DB tes lalu tutup koneksi."""
    with contextlib.closing(_raw_db()) as conn:
        conn.execute(sql, params)
        conn.commit()


def _user_header(name: str, is_admin: bool, user_id: int = 1) -> dict[str, str]:
    """Header uji untuk menyuntikkan ``request.state.user`` tanpa middleware auth."""
    payload = {"user_id": user_id, "username": name, "is_admin": is_admin}
    return {"X-Test-User": json.dumps(payload)}


@pytest.fixture
def auth_mod(tmp_path, monkeypatch):
    from alfa.dashboard.routes import auth as mod

    db_file = tmp_path / "auth.db"
    monkeypatch.setenv("ALFA_DB_PATH", str(db_file))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    # Mode lokal tanpa auth dimatikan: endpoint /api/* harus benar-benar
    # menuntut sesi/token sehingga jalur 401 ikut terukur.
    monkeypatch.delenv("ALFA_INSECURE_LOCAL", raising=False)
    monkeypatch.delenv("ALFA_DASHBOARD_SESSION_RETENTION_DAYS", raising=False)
    monkeypatch.setattr(mod, "_auth_db_initialized", False)
    monkeypatch.setattr(mod, "DASHBOARD_AUTH_TOKEN", "")
    mod.init_auth_db()
    mod._rate_buckets.clear()
    yield mod
    mod._rate_buckets.clear()


class _StateInjector(BaseHTTPMiddleware):
    """Suntikkan ``request.state.user`` dari header X-Test-User (JSON) untuk tes."""

    async def dispatch(self, request, call_next):
        raw = request.headers.get("X-Test-User")
        if raw:
            request.state.user = json.loads(raw)
        return await call_next(request)


@pytest.fixture
def api_client(auth_mod):
    """Aplikasi endpoint auth TANPA middleware (pengujian cabang per endpoint)."""
    app = FastAPI()
    app.add_middleware(_StateInjector)
    app.include_router(auth_mod.auth_router)
    return TestClient(app)


@pytest.fixture
def mw_client(auth_mod):
    """Aplikasi dengan ``DashboardAuthMiddleware`` (pengujian jalur middleware)."""
    app = FastAPI()
    app.add_middleware(auth_mod.DashboardAuthMiddleware)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/page")
    async def page():
        return {"page": True}

    @app.get("/api/demo")
    async def demo(request: Request):
        return {"user": getattr(request.state, "user", None)}

    app.include_router(auth_mod.auth_router)
    return TestClient(app)


# ---------------------------------------------------------------------------
# Hash password & session token
# ---------------------------------------------------------------------------


def test_hash_and_verify_password(auth_mod):
    pwd_hash, salt = auth_mod._hash_password("rahasia123")
    assert len(pwd_hash) == 64
    assert len(salt) == 32
    assert auth_mod._verify_password("rahasia123", pwd_hash, salt) is True
    assert auth_mod._verify_password("salah-satu", pwd_hash, salt) is False

    # Salt eksplisit membuat hash deterministik.
    h1, s1 = auth_mod._hash_password("x", salt="tetap")
    h2, s2 = auth_mod._hash_password("x", salt="tetap")
    assert h1 == h2
    assert s1 == s2 == "tetap"


def _signed_token(user_id: int, username: str, expiry: datetime) -> str:
    """Buat token sesi dengan tanda tangan benar tapi isi bebas (untuk uji)."""
    from alfa.dashboard.common import SESSION_SECRET

    payload = f"{user_id}|||{username}|||{expiry.isoformat()}"
    signature = hmac.new(
        SESSION_SECRET.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return f"{payload}|||{signature}"


def test_verify_session_token_branches(auth_mod):
    token = auth_mod._create_session_token(7, "budi")
    data = auth_mod._verify_session_token(token)
    assert data is not None
    assert data["user_id"] == 7
    assert data["username"] == "budi"

    # Kedaluwarsa -> None.
    expired = _signed_token(1, "uji", datetime.now() - timedelta(hours=1))
    assert auth_mod._verify_session_token(expired) is None

    # Signature dimanipulasi -> None.
    tampered = token[:-1] + ("0" if token[-1] != "0" else "1")
    assert auth_mod._verify_session_token(tampered) is None

    # Bagian bukan angka -> ValueError -> None.
    assert (
        auth_mod._verify_session_token("abc|||uji|||2030-01-01T00:00:00|||xx")
        is None
    )
    # Jumlah bagian salah -> None.
    assert auth_mod._verify_session_token("hanya|||dua") is None


# ---------------------------------------------------------------------------
# create_user / authenticate_user / validate_session
# ---------------------------------------------------------------------------


def test_create_user_validation_and_duplicate(auth_mod):
    with pytest.raises(ValueError, match="minimal 3"):
        auth_mod.create_user("ab", "password123")
    with pytest.raises(ValueError, match="minimal 6"):
        auth_mod.create_user("abc", "abcde")

    created = auth_mod.create_user("adminuji", "katasandi123", is_admin=True)
    assert created["is_admin"] is True
    assert created["user_id"] > 0

    with pytest.raises(ValueError, match="sudah terdaftar"):
        auth_mod.create_user("adminuji", "katasandi123")


def test_authenticate_user_paths(auth_mod):
    # User tidak ada -> None.
    assert auth_mod.authenticate_user("tidak-ada", "katasandi") is None

    auth_mod.create_user("pemilik", "katasandi123")
    got = auth_mod.authenticate_user("pemilik", "katasandi123")
    assert got is not None
    assert got["username"] == "pemilik"
    assert got["is_admin"] is False

    # Password salah -> None.
    assert auth_mod.authenticate_user("pemilik", "salah") is None

    # User dinonaktifkan -> tidak ditemukan -> None.
    _update(
        "UPDATE dashboard_users SET is_active = 0 WHERE id = ?",
        (got["user_id"],),
    )
    assert auth_mod.authenticate_user("pemilik", "katasandi123") is None


def test_validate_session_rejects_inactive_user(auth_mod):
    created = auth_mod.create_user("aktif", "katasandi123")
    token = auth_mod._create_session_token(created["user_id"], "aktif")
    auth_mod.store_session(created["user_id"], token)
    assert auth_mod.validate_session(token) is not None

    _update(
        "UPDATE dashboard_users SET is_active = 0 WHERE id = ?",
        (created["user_id"],),
    )
    assert auth_mod.validate_session(token) is None


# ---------------------------------------------------------------------------
# Retensi sesi & flatten default-deny
# ---------------------------------------------------------------------------


def test_session_retention_days_fallback_and_clamp(auth_mod, monkeypatch):
    monkeypatch.setenv("ALFA_DASHBOARD_SESSION_RETENTION_DAYS", "bukan-angka")
    assert auth_mod._session_retention_days() == 30

    monkeypatch.setenv("ALFA_DASHBOARD_SESSION_RETENTION_DAYS", "99999")
    assert auth_mod._session_retention_days() == 3650

    monkeypatch.setenv("ALFA_DASHBOARD_SESSION_RETENTION_DAYS", "-5")
    assert auth_mod._session_retention_days() == 0
    # 0 hari = pruning nonaktif.
    assert auth_mod.prune_dashboard_sessions_sync(retention_days=0) == 0


def test_flatten_with_default_deny(auth_mod):
    from fastapi import APIRouter

    parent = APIRouter()
    sub = APIRouter()

    @sub.get("/tersembunyi")
    async def tersembunyi():
        return {"ok": True}

    auth_mod.flatten_with_default_deny(parent, [sub])
    assert len(parent.routes) == 1

    # Fungsional: route hasil flatten wajib admin (default-deny).
    app = FastAPI()
    app.add_middleware(_StateInjector)
    app.include_router(parent)
    client = TestClient(app)
    assert client.get("/tersembunyi").status_code == 401
    assert (
        client.get("/tersembunyi", headers=_user_header("a", True)).json()
        == {"ok": True}
    )

    # Dependency eksplisit menggantikan default admin.
    panggilan: list[int] = []

    def wajib():
        panggilan.append(1)

    parent2 = APIRouter()
    auth_mod.flatten_with_default_deny(parent2, [sub], dependency=Depends(wajib))
    app2 = FastAPI()
    app2.include_router(parent2)
    assert TestClient(app2).get("/tersembunyi").status_code == 200
    assert panggilan == [1]


# ---------------------------------------------------------------------------
# Endpoint: register
# ---------------------------------------------------------------------------


def test_register_validation_and_rate_limit(auth_mod, api_client):
    # Field wajib kosong -> 400.
    res = api_client.post("/api/auth/register", json={})
    assert res.status_code == 400
    assert "wajib diisi" in res.json()["detail"]

    # Bootstrap: user pertama menjadi admin.
    res = api_client.post(
        "/api/auth/register",
        json={"username": "bos", "password": "katasandi123"},
    )
    assert res.status_code == 200
    assert res.json()["user"]["is_admin"] is True

    # Invite tidak valid -> 403.
    res = api_client.post(
        "/api/auth/register",
        json={
            "username": "kedua",
            "password": "katasandi123",
            "invite_token": "ngawur",
        },
    )
    assert res.status_code == 403
    assert "Invite token" in res.json()["detail"]

    # Invite valid tetapi username duplikat -> ValueError -> 400.
    invite = auth_mod.create_invite_token("uji")["invite_token"]
    res = api_client.post(
        "/api/auth/register",
        json={
            "username": "bos",
            "password": "katasandi123",
            "invite_token": invite,
        },
    )
    assert res.status_code == 400
    assert "sudah terdaftar" in res.json()["detail"]


def test_register_rate_limit_429(auth_mod, api_client):
    for _ in range(10):
        res = api_client.post("/api/auth/register", json={})
        assert res.status_code == 400
    res = api_client.post("/api/auth/register", json={})
    assert res.status_code == 429
    assert res.headers.get("Retry-After")


def test_register_unexpected_error_500(auth_mod, api_client, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("kegagalan buatan")  # noqa: TRY003

    monkeypatch.setattr(auth_mod, "create_user", boom)
    res = api_client.post(
        "/api/auth/register",
        json={"username": "aman", "password": "katasandi123"},
    )
    assert res.status_code == 500
    assert res.json()["detail"] == "Gagal mendaftar user"


# ---------------------------------------------------------------------------
# Endpoint: invite
# ---------------------------------------------------------------------------


def test_invite_endpoint_ttl_clamp_and_fallback(auth_mod, api_client):
    # Tanpa sesi admin -> 401.
    res = api_client.post("/api/auth/invite", json={})
    assert res.status_code == 401

    hdr = _user_header("adminuji", True)

    # ttl terlalu kecil -> dinaikkan ke 60.
    res = api_client.post("/api/auth/invite", json={"ttl_seconds": 5}, headers=hdr)
    assert res.status_code == 200
    assert res.json()["ttl_seconds"] == 60

    # ttl bukan angka -> jatuh ke default 3600 (cabang except).
    res = api_client.post(
        "/api/auth/invite", json={"ttl_seconds": "abc"}, headers=hdr
    )
    assert res.status_code == 200
    assert res.json()["ttl_seconds"] == 3600

    # ttl melebihi batas -> dipangkas ke 86400.
    res = api_client.post(
        "/api/auth/invite", json={"ttl_seconds": 10**9}, headers=hdr
    )
    assert res.status_code == 200
    assert res.json()["ttl_seconds"] == 86400

    # Tanpa body (payload None) -> default 3600.
    res = api_client.post(
        "/api/auth/invite",
        content=b"null",
        headers={"Content-Type": "application/json", **hdr},
    )
    assert res.status_code == 200
    assert res.json()["ttl_seconds"] == 3600

    # Token hasil invite bisa dipakai untuk registrasi.
    token = res.json()["invite_token"]
    assert auth_mod.consume_invite_token(token) is True
    # Sekali pakai: konsumsi ulang ditolak.
    assert auth_mod.consume_invite_token(token) is False


# ---------------------------------------------------------------------------
# Endpoint: login / logout / me / users / delete
# ---------------------------------------------------------------------------


def test_login_validation_and_success(auth_mod, api_client):
    # Field kosong -> 400.
    res = api_client.post("/api/auth/login", json={})
    assert res.status_code == 400
    assert "wajib diisi" in res.json()["detail"]

    auth_mod.create_user("penulis", "katasandi123")

    # Password salah -> 401.
    res = api_client.post(
        "/api/auth/login", json={"username": "penulis", "password": "salah"}
    )
    assert res.status_code == 401
    assert "salah" in res.json()["detail"]

    # Login sukses -> token + cookie sesi.
    res = api_client.post(
        "/api/auth/login",
        json={"username": "penulis", "password": "katasandi123"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "success"
    assert body["user"]["username"] == "penulis"
    assert "|||" in body["token"]
    assert "session_token" in res.cookies


def test_login_rate_limit_429(auth_mod, api_client):
    auth_mod.create_user("korban", "katasandi123")
    for _ in range(10):
        res = api_client.post(
            "/api/auth/login",
            json={"username": "korban", "password": "salah"},
        )
        assert res.status_code == 401
    res = api_client.post(
        "/api/auth/login", json={"username": "korban", "password": "salah"}
    )
    assert res.status_code == 429
    assert res.headers.get("Retry-After")


def test_logout_invalidates_session(auth_mod, api_client):
    # Tanpa sesi -> tetap sukses (tidak ada yang di-invalidate).
    res = api_client.post("/api/auth/logout")
    assert res.status_code == 200
    assert res.json()["status"] == "success"

    auth_mod.create_user("keluar", "katasandi123")
    login = api_client.post(
        "/api/auth/login",
        json={"username": "keluar", "password": "katasandi123"},
    )
    token = login.json()["token"]
    assert auth_mod.validate_session(token) is not None

    res = api_client.post(
        "/api/auth/logout", headers={"X-Session-Token": token}
    )
    assert res.status_code == 200
    assert auth_mod.validate_session(token) is None


def test_me_endpoint_branches(auth_mod, api_client):
    # Tanpa sesi -> 401.
    res = api_client.get("/api/auth/me")
    assert res.status_code == 401
    assert "login" in res.json()["detail"].lower()

    # Lewat cookie valid -> sukses dan sesi divalidasi ulang.
    auth_mod.create_user("peninjau", "katasandi123")
    api_client.post(
        "/api/auth/login",
        json={"username": "peninjau", "password": "katasandi123"},
    )
    res = api_client.get("/api/auth/me")
    assert res.status_code == 200
    assert res.json()["user"]["username"] == "peninjau"

    # Lewat state.user yang sudah diisi (middleware) -> langsung sukses.
    res = api_client.get(
        "/api/auth/me", headers=_user_header("disuntik", True)
    )
    assert res.status_code == 200
    assert res.json()["user"]["username"] == "disuntik"


def test_list_users_and_delete_user(auth_mod, api_client):
    admin_hdr = _user_header("adminuji", True, user_id=1)
    user_hdr = _user_header("biasa", False, user_id=2)

    # Tanpa user -> 403.
    assert api_client.get("/api/auth/users").status_code == 403
    # Non-admin -> 403.
    assert api_client.get("/api/auth/users", headers=user_hdr).status_code == 403

    created = auth_mod.create_user("daftar", "katasandi123")
    res = api_client.get("/api/auth/users", headers=admin_hdr)
    assert res.status_code == 200
    assert any(u["username"] == "daftar" for u in res.json()["users"])

    # Hapus user: tanpa sesi & non-admin -> 403.
    target = f"/api/auth/users/{created['user_id']}"
    assert api_client.delete(target).status_code == 403
    assert api_client.delete(target, headers=user_hdr).status_code == 403

    # Admin tapi user tidak ada -> 404.
    res = api_client.delete("/api/auth/users/999999", headers=admin_hdr)
    assert res.status_code == 404
    assert "tidak ditemukan" in res.json()["detail"]

    # Admin + user ada -> sukses.
    res = api_client.delete(target, headers=admin_hdr)
    assert res.status_code == 200
    assert res.json()["status"] == "success"
    assert auth_mod.get_all_users() == []


# ---------------------------------------------------------------------------
# Endpoint: magic-link Telegram /t/{token}
# ---------------------------------------------------------------------------


def test_telegram_magic_link_flow(auth_mod, api_client):
    # Token tidak dikenal -> 410.
    res = api_client.get("/t/tidak-ada", follow_redirects=False)
    assert res.status_code == 410
    assert "kedaluwarsa" in res.text

    created = auth_mod.create_user("tele", "katasandi123")
    token = auth_mod.create_telegram_link(created["user_id"])

    # Token sah -> redirect 302 + cookie sesi yang valid.
    res = api_client.get(f"/t/{token}", follow_redirects=False)
    assert res.status_code == 302
    session_cookie = res.cookies.get("session_token")
    assert session_cookie
    assert auth_mod.validate_session(session_cookie) is not None

    # Sekali pakai -> 410.
    res = api_client.get(f"/t/{token}", follow_redirects=False)
    assert res.status_code == 410

    # Kedaluwarsa -> 410.
    expired_token = auth_mod.create_telegram_link(created["user_id"])
    _update(
        "UPDATE telegram_login_links SET expires_at = ? WHERE token = ?",
        ("2000-01-01 00:00:00", expired_token),
    )
    res = api_client.get(f"/t/{expired_token}", follow_redirects=False)
    assert res.status_code == 410


# ---------------------------------------------------------------------------
# Middleware: publik / blokir / sesi / token legacy / Basic
# ---------------------------------------------------------------------------


def test_middleware_public_paths_and_fail_closed(auth_mod, mw_client):
    # OPTIONS dilewat tanpa auth.
    res = mw_client.options("/api/demo")
    assert res.status_code in (404, 405)

    # Path publik lolos.
    assert mw_client.get("/health").status_code == 200

    # API tanpa sesi -> 401 fail-closed + header WWW-Authenticate.
    res = mw_client.get("/api/demo")
    assert res.status_code == 401
    assert "WWW-Authenticate" in res.headers
    assert res.json()["detail"] == "Unauthorized: login required"

    # Halaman non-API non-publik tetap lolos middleware.
    assert mw_client.get("/page").status_code == 200


def test_middleware_session_cookie_sets_user(auth_mod, mw_client):
    auth_mod.create_user("masuk", "katasandi123")
    res = mw_client.post(
        "/api/auth/login",
        json={"username": "masuk", "password": "katasandi123"},
    )
    assert res.status_code == 200

    res = mw_client.get("/api/demo")
    assert res.status_code == 200
    assert res.json()["user"]["username"] == "masuk"


def test_middleware_bearer_candidate_rejected(auth_mod, mw_client):
    # Bearer yang bukan sesi valid maupun token legacy -> 401.
    res = mw_client.get(
        "/api/demo", headers={"Authorization": "Bearer bukan-sesi"}
    )
    assert res.status_code == 401


def test_middleware_legacy_token_and_basic(auth_mod, mw_client, monkeypatch):
    monkeypatch.setattr(auth_mod, "DASHBOARD_AUTH_TOKEN", "token-legacy-uji")

    # Bearer cocok -> identitas admin_legacy.
    res = mw_client.get(
        "/api/demo", headers={"Authorization": "Bearer token-legacy-uji"}
    )
    assert res.status_code == 200
    assert res.json()["user"]["username"] == "admin_legacy"

    # Basic valid -> identitas admin_legacy.
    basic = base64.b64encode(b"admin:token-legacy-uji").decode("ascii")
    res = mw_client.get("/api/demo", headers={"Authorization": f"Basic {basic}"})
    assert res.status_code == 200
    assert res.json()["user"]["username"] == "admin_legacy"

    # Basic dengan password salah -> ditolak.
    bad = base64.b64encode(b"admin:salah").decode("ascii")
    res = mw_client.get("/api/demo", headers={"Authorization": f"Basic {bad}"})
    assert res.status_code == 401

    # Basic rusak (b64decode gagal) -> aman -> tetap 401.
    res = mw_client.get("/api/demo", headers={"Authorization": "Basic abc"})
    assert res.status_code == 401
