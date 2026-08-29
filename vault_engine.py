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
from typing import Any, Dict, List, Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

logger = logging.getLogger("alfa.vault")

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent_data.db")
KEY_FILE = os.path.expanduser("~/.alfa_vault_master.key")


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
            logger.error(f"Could not back up corrupt vault master key file: {backup_err}")
            raise RuntimeError(
                "Vault master key file is corrupt and could not be backed up; "
                "refusing to generate a new key (existing secrets would be lost)."
            )

    # Generate new random 256-bit key
    new_key = AESGCM.generate_key(bit_length=256)
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
    conn = sqlite3.connect(DB_PATH)
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

    def encrypt_val(self, plaintext: str) -> Dict[str, str]:
        """Encrypt string data using AES-256-GCM with a fresh 12-byte nonce."""
        nonce = os.urandom(12)
        data_bytes = plaintext.encode("utf-8")
        ciphertext = self.aesgcm.encrypt(nonce, data_bytes, None)
        return {
            "ciphertext": base64.b64encode(ciphertext).decode("utf-8"),
            "nonce": base64.b64encode(nonce).decode("utf-8")
        }

    def decrypt_val(self, ciphertext_b64: str, nonce_b64: str) -> str:
        """Decrypt ciphertext and verify authenticity tag."""
        ciphertext = base64.b64decode(ciphertext_b64)
        nonce = base64.b64decode(nonce_b64)
        decrypted_bytes = self.aesgcm.decrypt(nonce, ciphertext, None)
        return decrypted_bytes.decode("utf-8")

    def store_secret(self, name: str, value: str, category: str = "api_key", notes: str = "") -> Dict[str, Any]:
        """Store or update an encrypted secret in the vault."""
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("Secret name cannot be empty")

        enc = self.encrypt_val(value)
        now = datetime.now().isoformat()

        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        # Upsert secret
        cursor.execute("""
            INSERT INTO vault_secrets (name, category, ciphertext, nonce, created_at, updated_at, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                category = excluded.category,
                ciphertext = excluded.ciphertext,
                nonce = excluded.nonce,
                updated_at = excluded.updated_at,
                notes = excluded.notes
        """, (clean_name, category, enc["ciphertext"], enc["nonce"], now, now, notes))

        conn.commit()
        conn.close()

        logger.info(f"Secret '{clean_name}' successfully encrypted with AES-256-GCM into vault.")
        return {
            "status": "success",
            "name": clean_name,
            "category": category,
            "algorithm": "AES-256-GCM",
            "message": f"Secret '{clean_name}' aman tersimpan dalam αlfa Secure Vault."
        }

    def get_secret(self, name_or_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve and decrypt secret value."""
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        name_str = str(name_or_id).strip()
        if name_str.isdigit():
            # Try by id first, then fall back to literal numeric names
            cursor.execute("SELECT * FROM vault_secrets WHERE id = ?", (int(name_str),))
            row = cursor.fetchone()
            if not row:
                cursor.execute("SELECT * FROM vault_secrets WHERE name = ?", (name_str,))
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
            logger.error(f"Failed to decrypt secret '{row_data['name']}': {decrypt_err}")
            raise ValueError(
                f"Gagal mendekripsi secret '{row_data['name']}'. "
                "Master key kemungkinan berubah sejak secret ini disimpan."
            )
        return {
            "id": row_data["id"],
            "name": row_data["name"],
            "category": row_data["category"],
            "value": decrypted_val,
            "created_at": row_data["created_at"],
            "updated_at": row_data["updated_at"],
            "notes": row_data["notes"]
        }

    def list_secrets(self, category: Optional[str] = None) -> List[Dict[str, Any]]:
        """List metadata for secrets without exposing decrypted values."""
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        if category and category != "all":
            cursor.execute("SELECT id, name, category, created_at, updated_at, notes FROM vault_secrets WHERE category = ? ORDER BY updated_at DESC", (category,))
        else:
            cursor.execute("SELECT id, name, category, created_at, updated_at, notes FROM vault_secrets ORDER BY updated_at DESC")

        rows = cursor.fetchall()
        conn.close()

        items = []
        for r in rows:
            items.append({
                "id": r["id"],
                "name": r["name"],
                "category": r["category"],
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
                "notes": r["notes"] or "",
                "masked_value": "••••••••••••••••"
            })
        return items

    def delete_secret(self, secret_id: int) -> bool:
        """Permanently delete a secret from vault."""
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM vault_secrets WHERE id = ?", (secret_id,))
        deleted = cursor.rowcount > 0
        conn.commit()
        conn.close()
        return deleted


# Global Singleton
vault = AlfaSecureVault()
