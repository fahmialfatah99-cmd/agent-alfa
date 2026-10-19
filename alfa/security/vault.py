"""
╔══════════════════════════════════════════════════════════════════════════════╗
║                   ALFA SECURE VAULT ENGINE (AES-256-GCM)                     ║
║   Enterprise Military-Grade Authenticated Encryption Secret Store            ║
║   Copyright (c) 2026 Fahmi Alfatah. All Rights Reserved.                     ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import base64
import hashlib
import logging
import os
import sqlite3
from datetime import datetime
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

logger = logging.getLogger("alfa.vault")

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DB_PATH = os.getenv("ALFA_DB_PATH", os.path.join(REPO_ROOT, "agent_data.db"))
KEY_FILE = os.path.expanduser("~/.alfa_vault_master.key")

# Jalur patokan yang dibekukan saat import — pembanding untuk mendeteksi
# monkeypatch ATTR DB_PATH (pola isolasi test lama) vs ubah ENV runtime (baru).
_ENV_DB_PATH_AT_IMPORT = DB_PATH


def _vault_db_path() -> str:
    """Resolusi path DB **dinamis** untuk setiap koneksi.

    Nilai statis ``DB_PATH`` dipatok saat import — bila ``ALFA_DB_PATH`` diubah
    setelahnya koneksi tetap menunjuk DB lama dan baris vault bocor antar-test
    (sumber race GDrive auth-mode). Preseden resolusi:

    1. ATTR ``DB_PATH`` yang di-patch eksplisit (≠ patokan) — pola isolasi lama;
    2. ENV ``ALFA_DB_PATH``/``DATABASE_URL`` saat koneksi — pola test baru;
    3. resolver ``alfa.core.db.paths`` (sumber kebenaran tunggal);
    4. ATTR ``DB_PATH`` apa adanya.
    """
    if globals().get("DB_PATH") != _ENV_DB_PATH_AT_IMPORT:
        # DB_PATH di-override eksplisit (monkeypatch attr) → hormati.
        return str(globals().get("DB_PATH"))
    try:
        from alfa.core.db.paths import resolve_db_path

        resolved = resolve_db_path(fallback=DB_PATH)
        if resolved:
            return str(resolved)
    except Exception:  # noqa: BLE001 — resolver opsional, fallback statis aman
        pass
    return DB_PATH


def _get_or_create_master_key() -> bytes:
    """
    Retrieve or generate 256-bit (32-byte) AES-GCM Master Key.
    Prioritizes .env VAULT_MASTER_KEY, then ~/.alfa_vault_master.key.
    """
    env_key = os.getenv("VAULT_MASTER_KEY", "").strip()
    if env_key:
        if len(env_key) == 64:  # 64 hex chars = 32 bytes
            return bytes.fromhex(env_key)
        # Derive 32 bytes via SHA-256
        return hashlib.sha256(env_key.encode("utf-8")).digest()

    if os.path.exists(KEY_FILE):
        try:
            with open(KEY_FILE, "rb") as f:
                key = f.read().strip()
                if len(key) == 32:
                    return key
                elif len(key) == 64:
                    return bytes.fromhex(key.decode("utf-8"))
        except Exception as e:
            logger.warning(f"Failed to read vault master key file: {e}")

        # The existing key file is unreadable/corrupt. Back it up instead of
        # overwriting it: generating a fresh key here would permanently lock
        # every secret already encrypted with the old key.
        backup_path = KEY_FILE + ".corrupt." + datetime.now().strftime("%Y%m%d%H%M%S")
        try:
            os.replace(KEY_FILE, backup_path)
            logger.error(
                f"Vault master key file invalid - moved to '{backup_path}'. "
                "Secrets encrypted with the previous key can no longer be decrypted. "
                "Restore the backup file to recover them."
            )
        except Exception as backup_err:
            logger.error(
                f"Could not back up corrupt vault master key file: {backup_err}"
            )
            raise RuntimeError(
                "Vault master key file is corrupt and could not be backed up; "
                "refusing to generate a new key (existing secrets would be lost)."
            ) from backup_err

    # Generate new random 256-bit key
    new_key: bytes = AESGCM.generate_key(bit_length=256)
    try:
        # Open with restrictive permissions from the start to avoid a
        # world-readable window before chmod runs.
        fd = os.open(KEY_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(new_key.hex().encode("utf-8"))
        os.chmod(KEY_FILE, 0o600)
    except Exception as e:
        logger.error(f"Could not persist vault master key: {e}")

    return new_key


def _init_vault_db():
    """Ensure vault_secrets table exists in SQLite database."""
    conn = sqlite3.connect(_vault_db_path())
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS vault_secrets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            category TEXT NOT NULL DEFAULT 'api_key',
            ciphertext TEXT NOT NULL,
            nonce TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            notes TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS vault_secret_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            secret_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            ciphertext TEXT NOT NULL,
            nonce TEXT NOT NULL,
            archived_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


# Initialize table on import
_init_vault_db()


class AlfaSecureVault:
    """
    High-Performance AES-256-GCM Secret Store.
    Encrypts sensitive data with 96-bit unique nonces per entry and authenticated tags.
    """

    def __init__(self):
        self.master_key = _get_or_create_master_key()
        self.aesgcm = AESGCM(self.master_key)

    def encrypt_val(self, plaintext: str) -> dict[str, str]:
        """Encrypt string data using AES-256-GCM with a fresh 12-byte nonce."""
        nonce = os.urandom(12)
        data_bytes = plaintext.encode("utf-8")
        ciphertext = self.aesgcm.encrypt(nonce, data_bytes, None)
        return {
            "ciphertext": base64.b64encode(ciphertext).decode("utf-8"),
            "nonce": base64.b64encode(nonce).decode("utf-8"),
        }

    def decrypt_val(self, ciphertext_b64: str, nonce_b64: str) -> str:
        """Decrypt ciphertext and verify authenticity tag."""
        ciphertext = base64.b64decode(ciphertext_b64)
        nonce = base64.b64decode(nonce_b64)
        decrypted_bytes: bytes = self.aesgcm.decrypt(nonce, ciphertext, None)
        return decrypted_bytes.decode("utf-8")

    def store_secret(
        self, name: str, value: str, category: str = "api_key", notes: str = ""
    ) -> dict[str, Any]:
        """Store or update an encrypted secret in the vault."""
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("Secret name cannot be empty")

        enc = self.encrypt_val(value)
        now = datetime.now().isoformat()

        conn = sqlite3.connect(_vault_db_path())
        cursor = conn.cursor()

        # Arsipkan nilai lama sebelum ditimpa (versioning untuk audit/rollback).
        old = cursor.execute(
            "SELECT id, ciphertext, nonce FROM vault_secrets WHERE name = ?",
            (clean_name,),
        ).fetchone()

        # Upsert secret
        cursor.execute(
            """
            INSERT INTO vault_secrets (name, category, ciphertext, nonce, created_at, updated_at, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                category = excluded.category,
                ciphertext = excluded.ciphertext,
                nonce = excluded.nonce,
                updated_at = excluded.updated_at,
                notes = excluded.notes
        """,
            (clean_name, category, enc["ciphertext"], enc["nonce"], now, now, notes),
        )

        if old:
            cursor.execute(
                """INSERT INTO vault_secret_versions
                   (secret_id, name, ciphertext, nonce, archived_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (old[0], clean_name, old[1], old[2], now),
            )

        conn.commit()
        conn.close()

        logger.info(
            f"Secret '{clean_name}' successfully encrypted with AES-256-GCM into vault."
        )
        return {
            "status": "success",
            "name": clean_name,
            "category": category,
            "algorithm": "AES-256-GCM",
            "message": f"Secret '{clean_name}' aman tersimpan dalam αlfa Secure Vault.",
        }

    def get_secret(self, name_or_id: str) -> dict[str, Any] | None:
        """Retrieve and decrypt secret value."""
        conn = sqlite3.connect(_vault_db_path())
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        name_str = str(name_or_id).strip()
        if name_str.isdigit():
            # Try by id first, then fall back to literal numeric names
            cursor.execute("SELECT * FROM vault_secrets WHERE id = ?", (int(name_str),))
            row = cursor.fetchone()
            if not row:
                cursor.execute(
                    "SELECT * FROM vault_secrets WHERE name = ?", (name_str,)
                )
                row = cursor.fetchone()
        else:
            cursor.execute("SELECT * FROM vault_secrets WHERE name = ?", (name_str,))
            row = cursor.fetchone()

        if not row:
            conn.close()
            return None

        row_data = dict(row)
        conn.close()

        try:
            decrypted_val = self.decrypt_val(row_data["ciphertext"], row_data["nonce"])
        except Exception as decrypt_err:
            logger.error(
                f"Failed to decrypt secret '{row_data['name']}': {decrypt_err}"
            )
            raise ValueError(
                f"Gagal mendekripsi secret '{row_data['name']}'. "
                "Master key kemungkinan berubah sejak secret ini disimpan."
            ) from decrypt_err
        return {
            "id": row_data["id"],
            "name": row_data["name"],
            "category": row_data["category"],
            "value": decrypted_val,
            "created_at": row_data["created_at"],
            "updated_at": row_data["updated_at"],
            "notes": row_data["notes"],
        }

    def list_secrets(self, category: str | None = None) -> list[dict[str, Any]]:
        """List metadata for secrets without exposing decrypted values."""
        conn = sqlite3.connect(_vault_db_path())
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        if category and category != "all":
            cursor.execute(
                "SELECT id, name, category, created_at, updated_at, notes FROM vault_secrets WHERE category = ? ORDER BY updated_at DESC",
                (category,),
            )
        else:
            cursor.execute(
                "SELECT id, name, category, created_at, updated_at, notes FROM vault_secrets ORDER BY updated_at DESC"
            )

        rows = cursor.fetchall()
        conn.close()

        items = []
        for r in rows:
            items.append(
                {
                    "id": r["id"],
                    "name": r["name"],
                    "category": r["category"],
                    "created_at": r["created_at"],
                    "updated_at": r["updated_at"],
                    "notes": r["notes"] or "",
                    "masked_value": "••••••••••••••••",
                }
            )
        return items

    def list_secret_versions(
        self, name_or_id: str, limit: int = 20
    ) -> list[dict[str, Any]]:
        """Riwayat nilai lama sebuah secret (metadata + ciphertext, tanpa decrypt)."""
        conn = sqlite3.connect(_vault_db_path())
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        name_str = str(name_or_id).strip()
        try:
            if name_str.isdigit():
                rows = cursor.execute(
                    "SELECT id, secret_id, name, archived_at FROM vault_secret_versions "
                    "WHERE secret_id = ? OR name = ? ORDER BY id DESC LIMIT ?",
                    (int(name_str), name_str, max(1, limit)),
                ).fetchall()
            else:
                rows = cursor.execute(
                    "SELECT id, secret_id, name, archived_at FROM vault_secret_versions "
                    "WHERE name = ? ORDER BY id DESC LIMIT ?",
                    (name_str, max(1, limit)),
                ).fetchall()
        except sqlite3.OperationalError:
            rows = []
        conn.close()
        return [dict(r) for r in rows]

    def delete_secret(self, secret_id: int) -> bool:
        """Permanently delete a secret from vault."""
        conn = sqlite3.connect(_vault_db_path())
        cursor = conn.cursor()
        cursor.execute("DELETE FROM vault_secrets WHERE id = ?", (secret_id,))
        deleted = cursor.rowcount > 0
        conn.commit()
        conn.close()
        return deleted

    def rotate_master_key(self) -> dict[str, Any]:
        """Rotasi master key: dekripsi semua secret dengan key lama, enkripsi
        ulang dengan key baru, lalu simpan key baru.

        Aman: bila SATU SAJA secret gagal didekripsi, tidak ada yang diubah
        (abort sebelum tulis). Bila master key berasal dari env
        VAULT_MASTER_KEY, rotasi file ditolak — operator harus update env
        manual (kembalikan error eksplisit, bukan diam-diam merusak).
        """
        if os.getenv("VAULT_MASTER_KEY", "").strip():
            raise RuntimeError(
                "Rotasi ditolak: master key berasal dari env VAULT_MASTER_KEY. "
                "Set key baru di env/secret manager, lalu restart."
            )

        conn = sqlite3.connect(_vault_db_path())
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        try:
            rows = cursor.execute(
                "SELECT id, name, ciphertext, nonce FROM vault_secrets"
            ).fetchall()
        except sqlite3.OperationalError:
            rows = []

        plaintexts: list[tuple[int, str]] = []
        failed: list[str] = []
        for r in rows:
            try:
                plaintexts.append(
                    (r["id"], self.decrypt_val(r["ciphertext"], r["nonce"]))
                )
            except Exception:
                failed.append(r["name"])
        if failed:
            conn.close()
            raise RuntimeError(
                f"Rotasi dibatalkan — {len(failed)} secret tak bisa didekripsi "
                f"dengan key saat ini: {', '.join(failed[:5])}"
            )

        new_key = AESGCM.generate_key(bit_length=256)
        new_aes = AESGCM(new_key)
        re_enc: list[tuple[str, str, str, int]] = []
        for rid, plain in plaintexts:
            nonce = os.urandom(12)
            ct = new_aes.encrypt(nonce, plain.encode("utf-8"), None)
            re_enc.append(
                (
                    base64.b64encode(ct).decode("utf-8"),
                    base64.b64encode(nonce).decode("utf-8"),
                    datetime.now().isoformat(),
                    rid,
                )
            )

        backup_path = KEY_FILE + ".rotated." + datetime.now().strftime("%Y%m%d%H%M%S")
        try:
            if os.path.exists(KEY_FILE):
                os.replace(KEY_FILE, backup_path)
            else:
                backup_path = ""
            fd = os.open(KEY_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(new_key.hex().encode("utf-8"))
            os.chmod(KEY_FILE, 0o600)
        except Exception as key_err:
            conn.close()
            raise RuntimeError(
                f"Rotasi dibatalkan — gagal menulis key baru: {key_err}"
            ) from key_err

        try:
            cursor.executemany(
                "UPDATE vault_secrets SET ciphertext = ?, nonce = ?, updated_at = ? WHERE id = ?",
                re_enc,
            )
            conn.commit()
        except Exception as db_err:
            conn.rollback()
            raise RuntimeError(
                f"Rotasi gagal di DB (key file sudah terganti — restore {backup_path}): {db_err}"
            ) from db_err
        finally:
            conn.close()

        self.master_key = new_key
        self.aesgcm = new_aes
        logger.info(
            f"Vault master key dirotasi: {len(plaintexts)} secret dienkripsi ulang."
        )
        return {
            "status": "success",
            "rotated": len(plaintexts),
            "backup": backup_path,
            "algorithm": "AES-256-GCM",
        }


# Global Singleton
vault = AlfaSecureVault()
