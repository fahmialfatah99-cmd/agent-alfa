"""
Database Cryptography & API Key Encryption at-rest (AES-256-GCM).
"""

import base64
import logging
import os
import sqlite3

logger = logging.getLogger("DB.Crypto")

_ENC_PREFIX = "enc1:"


def _get_aesgcm():
    """Kembalikan objek AESGCM dari vault; None bila vault tak tersedia."""
    try:
        from alfa.security.vault import vault

        return vault.aesgcm
    except Exception:
        return None


def encrypt_key(plain: str) -> str:
    """Enkripsi string kunci menjadi 'enc1:<nonce_b64>:<ct_b64>'. Idempoten."""
    if not plain or plain.startswith(_ENC_PREFIX):
        return plain
    aes = _get_aesgcm()
    if aes is None:
        return plain  # degradasi anggun bila kripto tak tersedia
    nonce = os.urandom(12)
    ct = aes.encrypt(nonce, plain.encode("utf-8"), None)
    return (
        _ENC_PREFIX
        + base64.b64encode(nonce).decode("ascii")
        + ":"
        + base64.b64encode(ct).decode("ascii")
    )


def decrypt_key(stored: str) -> str:
    """Dekripsi nilai kolom api_key. Nilai plaintext lama lolos apa adanya."""
    if not stored or not stored.startswith(_ENC_PREFIX):
        return stored or ""
    try:
        _, nonce_b64, ct_b64 = stored.split(":", 2)
        aes = _get_aesgcm()
        if aes is None:
            return ""
        return aes.decrypt(
            base64.b64decode(nonce_b64), base64.b64decode(ct_b64), None
        ).decode("utf-8")
    except Exception:
        return ""


def mask_key(k: str) -> str:
    """Mask sensitive key string for safe UI presentation."""
    if not k or len(k) <= 8:
        return "••••••••"
    return k[:4] + "••••••••" + k[-4:]


def migrate_encrypt_api_keys() -> dict[str, int]:
    """Enkripsi satu kali seluruh api_key yang masih plaintext. Idempoten."""
    from alfa.core.db.connection import _get_db_path

    db_path = _get_db_path()
    changed, total = 0, 0
    conn = sqlite3.connect(db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("SELECT id, api_key FROM api_keys").fetchall()
        total = len(rows)
        for r in rows:
            val = r["api_key"] or ""
            if val and not val.startswith(_ENC_PREFIX):
                aes = _get_aesgcm()
                if aes is None:
                    break
                nonce = os.urandom(12)
                ct = aes.encrypt(nonce, val.encode("utf-8"), None)
                stored = (
                    _ENC_PREFIX
                    + base64.b64encode(nonce).decode("ascii")
                    + ":"
                    + base64.b64encode(ct).decode("ascii")
                )
                conn.execute(
                    "UPDATE api_keys SET api_key = ? WHERE id = ?", (stored, r["id"])
                )
                changed += 1
        conn.commit()
    finally:
        conn.close()
    return {"total": total, "encrypted": changed}
