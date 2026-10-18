"""Basisdata kredential & challenge WebAuthn (passkey) dashboard.

Storage MySQL/SQLite via pool `alfa.core.database`, schema:

- dashboard_webauthn_credentials: kredential publik per user (passkey)
- dashboard_webauthn_challenges: satu-pakai, T berbatas waktu; dikonsumsi
  verify endpoint agar tidak dipakai ulang (anti-replay)

Semua byte di simpan base64url (aman untuk kolom TEXT dan JSON).
"""

from __future__ import annotations

import hashlib
import logging
import os
import secrets
from typing import Any

logger = logging.getLogger("alfa.webauthn_store")


def get_authenticator_config() -> tuple[str, str]:
    """RP ID + origin untuk WebAuthn dari env.

    Mengembalikan (rp_id, origin). Spesifikasi WebAuthn melarang rp_id berupa
    alamat IP: panggilan endpoint menolak konfigurasi itu (honest config check).
    Default ``localhost`` → aman sejak server dev/jaringan-lokal.
    """
    rp_id = os.getenv("ALFA_WEBAUTHN_RP_ID", "localhost").strip()
    origin = os.getenv("ALFA_WEBAUTHN_ORIGIN", "").strip()
    if not origin:
        origin = f"http://{rp_id}:8000"
    return rp_id, origin


def user_handle(user_id: int) -> bytes:
    """User handle 16-byte deterministik untuk Relay WebAuthn."""
    return hashlib.sha256(f"alfa-user:{user_id}".encode()).digest()


def _ensure_tables() -> None:
    from alfa.core import database as db

    conn = db.get_connection_pool().acquire()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS dashboard_webauthn_credentials (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                credential_id TEXT UNIQUE NOT NULL,
                public_key TEXT NOT NULL,
                sign_count INTEGER NOT NULL DEFAULT 0,
                aaguid TEXT DEFAULT '',
                fmt TEXT DEFAULT 'none',
                device_type TEXT DEFAULT 'singleDevice',
                transports TEXT DEFAULT '',
                label TEXT DEFAULT 'passkey',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_used TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES dashboard_users(id)
                    ON DELETE CASCADE
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_webauthn_cred_user
                ON dashboard_webauthn_credentials(user_id)
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS dashboard_webauthn_challenges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL,
                challenge TEXT UNIQUE NOT NULL,
                user_id INTEGER,
                expires_at TIMESTAMP NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_webauthn_challenge_expiry
                ON dashboard_webauthn_challenges(expires_at)
        """)
        conn.commit()
    finally:
        db.get_connection_pool().release(conn)


# ── challenges ────────────────────────────────────────────────────────────────

CHALLENGE_TTL_SECONDS = 300


def store_challenge(kind: str, challenge: str, user_id: int | None) -> bool:
    """Simpan challenge untuk verifikasi nanti; sekaligus buang yang kadaluarsa."""
    _ensure_tables()
    from datetime import datetime, timedelta, timezone

    from alfa.core import database as db

    if kind not in ("reg", "login"):
        msg = f"kind challenge tak dikenal: {kind}"
        raise ValueError(msg)
    expires_at = (
        datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(
            seconds=CHALLENGE_TTL_SECONDS
        )
    )
    conn = db.get_connection_pool().acquire()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            DELETE FROM dashboard_webauthn_challenges WHERE expires_at < CURRENT_TIMESTAMP
        """)
        cursor.execute("""
            INSERT INTO dashboard_webauthn_challenges (kind, challenge, user_id, expires_at)
            VALUES (?, ?, ?, ?)
        """, (kind, challenge, user_id, expires_at.isoformat(sep=" ")))
        conn.commit()
        return True
    finally:
        db.get_connection_pool().release(conn)


def consume_challenge(kind: str, challenge: str) -> dict[str, Any] | None:
    """Ambil-dan-hapus challenge sekali-pakai. None bila tak ada/tak lagi valid."""
    _ensure_tables()
    from alfa.core import database as db

    conn = db.get_connection_pool().acquire()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, user_id FROM dashboard_webauthn_challenges
             WHERE kind = ? AND challenge = ?
               AND expires_at >= CURRENT_TIMESTAMP
        """, (kind, challenge))
        row = cursor.fetchone()
        if not row:
            return None
        cursor.execute(
            "DELETE FROM dashboard_webauthn_challenges WHERE id = ?", (row[0],)
        )
        conn.commit()
        return {"user_id": row[1]}
    finally:
        db.get_connection_pool().release(conn)


def new_challenge() -> str:
    """T dipselolis mana pun: 32 byte random dirilis dalam format base64url."""
    import base64

    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")


# ── kredensial ────────────────────────────────────────────────────────────────

def upsert_credential(
    user_id: int,
    credential_id: str,
    public_key: str,
    sign_count: int,
    aaguid: str = "",
    fmt: str = "none",
    device_type: str = "singleDevice",
    transports: str = "",
) -> int:
    """Simpan kredential publik passkey (atau perbarui bila id sudah ada)."""
    _ensure_tables()
    from alfa.core import database as db

    conn = db.get_connection_pool().acquire()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO dashboard_webauthn_credentials
                (user_id, credential_id, public_key, sign_count, aaguid, fmt,
                 device_type, transports)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(credential_id) DO UPDATE SET
                public_key = excluded.public_key,
                sign_count = excluded.sign_count,
                aaguid = excluded.aaguid,
                fmt = excluded.fmt,
                device_type = excluded.device_type,
                transports = excluded.transports
        """, (
            user_id, credential_id, public_key, int(sign_count), aaguid, fmt,
            device_type, transports,
        ))
        conn.commit()
        cursor.execute("""
            SELECT id FROM dashboard_webauthn_credentials WHERE credential_id = ?
        """, (credential_id,))
        row = cursor.fetchone()
        return int(row[0])
    finally:
        db.get_connection_pool().release(conn)


def get_credential(credential_id: str) -> dict[str, Any] | None:
    _ensure_tables()
    from alfa.core import database as db

    conn = db.get_connection_pool().acquire()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, user_id, public_key, sign_count, aaguid, fmt, device_type
              FROM dashboard_webauthn_credentials WHERE credential_id = ?
        """, (credential_id,))
        row = cursor.fetchone()
        if not row:
            return None
        return {
            "id": int(row[0]),
            "user_id": int(row[1]),
            "public_key": row[2],
            "sign_count": int(row[3]),
            "aaguid": row[4],
            "fmt": row[5],
            "device_type": row[6],
        }
    finally:
        db.get_connection_pool().release(conn)


def list_credentials(user_id: int) -> list[dict[str, Any]]:
    _ensure_tables()
    from alfa.core import database as db

    conn = db.get_connection_pool().acquire()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT credential_id, transports, label, created_at, last_used, aaguid
              FROM dashboard_webauthn_credentials WHERE user_id = ?
             ORDER BY created_at
        """, (user_id,))
        return [
            {
                "credential_id": row[0],
                "transports": row[1],
                "label": row[2],
                "created_at": row[3],
                "last_used": row[4],
                "aaguid": row[5],
            }
            for row in cursor.fetchall()
        ]
    finally:
        db.get_connection_pool().release(conn)


def update_sign_count(credential_id: str, new_count: int) -> None:
    from alfa.core import database as db

    conn = db.get_connection_pool().acquire()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE dashboard_webauthn_credentials
               SET sign_count = ?, last_used = CURRENT_TIMESTAMP
             WHERE credential_id = ?
        """, (int(new_count), credential_id))
        conn.commit()
    finally:
        db.get_connection_pool().release(conn)


def delete_credential(credential_id: str, user_id: int, is_admin: bool) -> bool:
    """Hapus kredential — user hanya boleh milik sendiri; admin milik siapa pun."""
    _ensure_tables()
    from alfa.core import database as db

    conn = db.get_connection_pool().acquire()
    try:
        cursor = conn.cursor()
        if is_admin:
            cursor.execute(
                "DELETE FROM dashboard_webauthn_credentials WHERE credential_id = ?",
                (credential_id,),
            )
        else:
            cursor.execute(
                "DELETE FROM dashboard_webauthn_credentials "
                "WHERE credential_id = ? AND user_id = ?",
                (credential_id, user_id),
            )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        db.get_connection_pool().release(conn)
