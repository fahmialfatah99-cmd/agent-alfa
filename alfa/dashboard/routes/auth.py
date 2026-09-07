"""Authentication, session management, and user authorization for ALFA Dashboard."""

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from alfa.dashboard.common import (
    DASHBOARD_AUTH_TOKEN,
    SESSION_DURATION_HOURS,
    SESSION_SECRET,
    logger,
)

auth_router = APIRouter(tags=["auth"])


def _hash_password(password: str, salt: str = None) -> tuple:
    """Hash password dengan salt menggunakan PBKDF2-HMAC-SHA256."""
    if salt is None:
        salt = secrets.token_hex(16)
    pwd_hash = hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt.encode('utf-8'),
        100000  # iterations
    ).hex()
    return pwd_hash, salt


def _verify_password(password: str, pwd_hash: str, salt: str) -> bool:
    """Verifikasi password terhadap hash yang tersimpan."""
    computed_hash, _ = _hash_password(password, salt)
    return secrets.compare_digest(computed_hash, pwd_hash)


def _create_session_token(user_id: int, username: str) -> str:
    """Buat session token HMAC untuk user."""
    expiry = datetime.now() + timedelta(hours=SESSION_DURATION_HOURS)
    payload = f"{user_id}|||{username}|||{expiry.isoformat()}"
    signature = hmac.new(
        SESSION_SECRET.encode('utf-8'),
        payload.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    return f"{payload}|||{signature}"


def _verify_session_token(token: str) -> Optional[Dict[str, Any]]:
    """Verifikasi dan decode session token."""
    try:
        parts = token.split('|||')
        if len(parts) != 4:
            return None
        user_id = int(parts[0])
        username = parts[1]
        expiry_str = parts[2]
        signature = parts[3]

        expiry = datetime.fromisoformat(expiry_str)
        if datetime.now() > expiry:
            return None  # Session expired

        payload = f"{user_id}|||{username}|||{expiry_str}"
        expected_sig = hmac.new(
            SESSION_SECRET.encode('utf-8'),
            payload.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        if not secrets.compare_digest(signature, expected_sig):
            return None

        return {"user_id": user_id, "username": username, "expiry": expiry}
    except Exception:
        return None


_auth_db_initialized = False


def init_auth_db():
    """Inisialisasi tabel users dan sessions di database."""
    global _auth_db_initialized
    if _auth_db_initialized:
        return
    from alfa.core import database as db
    conn = db.get_connection_pool().acquire()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS dashboard_users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                telegram_user_id INTEGER,
                is_admin INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_login TIMESTAMP,
                is_active INTEGER DEFAULT 1
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS dashboard_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                token_hash TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP NOT NULL,
                is_valid INTEGER DEFAULT 1,
                FOREIGN KEY (user_id) REFERENCES dashboard_users(id) ON DELETE CASCADE
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_users_username ON dashboard_users(username)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_sessions_token ON dashboard_sessions(token_hash)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_sessions_expiry ON dashboard_sessions(expires_at)
        """)
        conn.commit()
        _auth_db_initialized = True
        logger.info("Auth database tables initialized successfully")
    finally:
        db.get_connection_pool().release(conn)


def create_user(username: str, password: str, telegram_user_id: int = None, is_admin: bool = False) -> Dict[str, Any]:
    """Buat user baru di database."""
    import sqlite3
    from alfa.core import database as db

    if len(username) < 3:
        raise ValueError("Username minimal 3 karakter")
    if len(password) < 6:
        raise ValueError("Password minimal 6 karakter")

    pwd_hash, salt = _hash_password(password)

    conn = db.get_connection_pool().acquire()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO dashboard_users (username, password_hash, salt, telegram_user_id, is_admin)
            VALUES (?, ?, ?, ?, ?)
        """, (username, pwd_hash, salt, telegram_user_id, 1 if is_admin else 0))
        conn.commit()
        user_id = cursor.lastrowid
        logger.info(f"User '{username}' created with ID {user_id}")
        return {"user_id": user_id, "username": username, "is_admin": is_admin}
    except sqlite3.IntegrityError:
        raise ValueError(f"Username '{username}' sudah terdaftar")
    finally:
        db.get_connection_pool().release(conn)


def authenticate_user(username: str, password: str) -> Optional[Dict[str, Any]]:
    """Autentikasi user dan return info user jika berhasil."""
    from alfa.core import database as db

    conn = db.get_connection_pool().acquire()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, username, password_hash, salt, is_admin, is_active, last_login
            FROM dashboard_users
            WHERE username = ? AND is_active = 1
        """, (username,))
        row = cursor.fetchone()

        if not row:
            return None

        user_id, uname, stored_hash, salt, is_admin, is_active, last_login = row

        if _verify_password(password, stored_hash, salt):
            cursor.execute("""
                UPDATE dashboard_users SET last_login = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (user_id,))
            conn.commit()

            return {
                "user_id": user_id,
                "username": uname,
                "is_admin": bool(is_admin)
            }
        return None
    finally:
        db.get_connection_pool().release(conn)


def store_session(user_id: int, token: str) -> None:
    """Simpan session token di database."""
    from alfa.core import database as db

    token_hash = hashlib.sha256(token.encode('utf-8')).hexdigest()
    expires_at = datetime.now() + timedelta(hours=SESSION_DURATION_HOURS)

    conn = db.get_connection_pool().acquire()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE dashboard_sessions SET is_valid = 0
            WHERE user_id = ? AND is_valid = 1
        """, (user_id,))
        cursor.execute("""
            INSERT INTO dashboard_sessions (user_id, token_hash, expires_at)
            VALUES (?, ?, ?)
        """, (user_id, token_hash, expires_at))
        conn.commit()
    finally:
        db.get_connection_pool().release(conn)


def validate_session(token: str) -> Optional[Dict[str, Any]]:
    """Validasi session token dari database."""
    from alfa.core import database as db

    session_data = _verify_session_token(token)
    if not session_data:
        return None

    token_hash = hashlib.sha256(token.encode('utf-8')).hexdigest()

    conn = db.get_connection_pool().acquire()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT s.user_id, u.username, u.is_admin, s.expires_at
            FROM dashboard_sessions s
            JOIN dashboard_users u ON s.user_id = u.id
            WHERE s.token_hash = ? AND s.is_valid = 1 AND s.expires_at > CURRENT_TIMESTAMP
        """, (token_hash,))
        row = cursor.fetchone()

        if row:
            return {
                "user_id": row[0],
                "username": row[1],
                "is_admin": bool(row[2]),
                "expiry": datetime.fromisoformat(row[3])
            }
        return None
    finally:
        db.get_connection_pool().release(conn)


def invalidate_session(token: str) -> bool:
    """Invalidate/logout session token."""
    from alfa.core import database as db

    token_hash = hashlib.sha256(token.encode('utf-8')).hexdigest()

    conn = db.get_connection_pool().acquire()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE dashboard_sessions SET is_valid = 0
            WHERE token_hash = ?
        """, (token_hash,))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        db.get_connection_pool().release(conn)


def get_all_users() -> List[Dict[str, Any]]:
    """Dapatkan daftar semua users (hanya admin)."""
    from alfa.core import database as db

    conn = db.get_connection_pool().acquire()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, username, telegram_user_id, is_admin, created_at, last_login, is_active
            FROM dashboard_users
            ORDER BY created_at DESC
        """)
        rows = cursor.fetchall()
        return [
            {
                "id": row[0],
                "username": row[1],
                "telegram_user_id": row[2],
                "is_admin": bool(row[3]),
                "created_at": row[4],
                "last_login": row[5],
                "is_active": bool(row[6])
            }
            for row in rows
        ]
    finally:
        db.get_connection_pool().release(conn)


def delete_user(user_id: int) -> bool:
    """Hapus user dari database."""
    from alfa.core import database as db

    conn = db.get_connection_pool().acquire()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            DELETE FROM dashboard_users WHERE id = ?
        """, (user_id,))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        db.get_connection_pool().release(conn)


class DashboardAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Skip auth untuk OPTIONS, static files, dan endpoint publik
        if request.method == "OPTIONS":
            return await call_next(request)

        path = request.url.path
        if path == "/static" or path.startswith("/static/"):
            return await call_next(request)

        public_paths = ["/", "/health", "/api/auth/login", "/api/auth/register", "/docs", "/redoc", "/openapi.json"]
        if path == "/" or any(path.startswith(pp) for pp in public_paths if pp != "/"):
            return await call_next(request)

        # Cek session token dari cookie atau header
        session_token = request.cookies.get("session_token") or request.headers.get("X-Session-Token", "")
        auth_header = request.headers.get("Authorization", "")
        if not session_token and auth_header.startswith("Bearer "):
            candidate = auth_header[7:]
            if candidate != DASHBOARD_AUTH_TOKEN:
                session_token = candidate

        if session_token:
            user = validate_session(session_token)
            if user:
                request.state.user = user
                return await call_next(request)

        # Fallback ke DASHBOARD_AUTH_TOKEN legacy mode
        if DASHBOARD_AUTH_TOKEN:
            auth_header = request.headers.get("Authorization", "")
            authorized = False
            if auth_header == f"Bearer {DASHBOARD_AUTH_TOKEN}":
                authorized = True
            elif auth_header.startswith("Basic "):
                try:
                    decoded = base64.b64decode(auth_header[6:]).decode("utf-8")
                    _, _, pwd = decoded.partition(":")
                    authorized = secrets.compare_digest(pwd, DASHBOARD_AUTH_TOKEN)
                except Exception:
                    authorized = False

            if authorized:
                request.state.user = {"user_id": 0, "username": "admin_legacy", "is_admin": True}
                return await call_next(request)

        # Block akses ke API endpoints tanpa auth
        if DASHBOARD_AUTH_TOKEN and path.startswith("/api/"):
            return Response(
                content='{"detail":"Unauthorized: login required"}',
                status_code=401,
                media_type="application/json",
                headers={"WWW-Authenticate": 'Bearer realm="ALFA Dashboard Session"'}
            )

        return await call_next(request)


# ─────────────────────────────────────────────────────────────────────────────
# AUTHENTICATION ENDPOINTS - Login, Register, Logout, User Management
# ─────────────────────────────────────────────────────────────────────────────

@auth_router.post("/api/auth/register")
async def register_user(payload: Dict[str, Any]):
    """Register user baru untuk akses dashboard."""
    username = payload.get("username", "").strip()
    password = payload.get("password", "")
    telegram_user_id = payload.get("telegram_user_id")

    if not username or not password:
        raise HTTPException(status_code=400, detail="Username dan password wajib diisi")

    try:
        from alfa.core import database as db
        conn = db.get_connection_pool().acquire()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM dashboard_users")
            count = cursor.fetchone()[0]
            is_admin = (count == 0)
        finally:
            db.get_connection_pool().release(conn)

        result = create_user(username, password, telegram_user_id, is_admin)
        return {"status": "success", "message": "User berhasil didaftarkan", "user": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Registration error: {e}")
        raise HTTPException(status_code=500, detail="Gagal mendaftar user")


@auth_router.post("/api/auth/login")
async def login_user(payload: Dict[str, Any]):
    """Login user dan buat session token."""
    username = payload.get("username", "").strip()
    password = payload.get("password", "")

    if not username or not password:
        raise HTTPException(status_code=400, detail="Username dan password wajib diisi")

    user = authenticate_user(username, password)
    if not user:
        raise HTTPException(status_code=401, detail="Username atau password salah")

    session_token = _create_session_token(user["user_id"], user["username"])
    store_session(user["user_id"], session_token)

    response = Response(
        content=json.dumps({
            "status": "success",
            "message": "Login berhasil",
            "token": session_token,
            "user": user
        }),
        media_type="application/json"
    )

    response.set_cookie(
        key="session_token",
        value=session_token,
        max_age=SESSION_DURATION_HOURS * 3600,
        httponly=True,
        secure=False,
        samesite="lax"
    )

    return response


@auth_router.post("/api/auth/logout")
async def logout_user(request: Request):
    """Logout user dan invalidate session."""
    session_token = request.cookies.get("session_token") or request.headers.get("X-Session-Token", "")

    if session_token:
        invalidate_session(session_token)

    response = Response(
        content=json.dumps({"status": "success", "message": "Logout berhasil"}),
        media_type="application/json"
    )
    response.delete_cookie(key="session_token")
    return response


@auth_router.get("/api/auth/me")
async def get_current_user(request: Request):
    """Dapatkan info user yang sedang login."""
    user = getattr(request.state, "user", None)

    if not user:
        session_token = request.cookies.get("session_token")
        if session_token:
            user = validate_session(session_token)
            if user:
                request.state.user = user

    if not user:
        raise HTTPException(status_code=401, detail="Tidak ada sesi aktif. Silakan login.")

    return {"status": "success", "user": user}


@auth_router.get("/api/auth/users")
async def list_users(request: Request):
    """Daftar semua users (hanya untuk admin)."""
    user = getattr(request.state, "user", None)

    if not user or not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Akses ditolak. Hanya admin yang bisa melihat daftar user.")

    users = get_all_users()
    return {"status": "success", "users": users}


@auth_router.delete("/api/auth/users/{user_id}")
async def remove_user(request: Request, user_id: int):
    """Hapus user (hanya untuk admin)."""
    user = getattr(request.state, "user", None)

    if not user or not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Akses ditolak. Hanya admin yang bisa menghapus user.")

    if delete_user(user_id):
        return {"status": "success", "message": f"User {user_id} berhasil dihapus"}
    raise HTTPException(status_code=404, detail=f"User {user_id} tidak ditemukan")
