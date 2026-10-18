"""Penyimpanan kredensial Google Drive (OAuth & SA) via αlfa Secure Vault.

Semua nilai kredensial dienkripsi AES-256-GCM melalui ``alfa.security.vault``;
bukan lagi plaintext di tabel `system_settings` (bisa tervalidasi ke response
HTTP ada di masa lalu). Lapisan kompatibilitas lama tetap ada untuk membaca
sisa plaintext lama, lalu memigrasikannya otomatis.

Nama secret di vault:
- ``GDRIVE_OAUTH_TOKEN_JSON``  — token_data OAuth
- ``GDRIVE_CREDENTIALS_JSON`` — service-account JSON
"""

import json as _json
import logging
import sqlite3

from alfa.core import database

logger = logging.getLogger("GDriveSecretStore")

OAUTH_SECRET_NAME = "GDRIVE_OAUTH_TOKEN_JSON"
CRED_SECRET_NAME = "GDRIVE_CREDENTIALS_JSON"


def _vault():
    from alfa.security.vault import AlfaSecureVault

    return AlfaSecureVault()


def save_secret(name: str, value: str) -> bool:
    """Simpan/replace secret terenkripsi di vault. False bila vault gagal."""
    if not value:
        return False
    try:
        category = "oauth" if name == OAUTH_SECRET_NAME else "api_key"
        _vault().store_secret(
            name, value, category=category, notes="Google Drive (auto-managed)"
        )
        return True
    except (sqlite3.Error, OSError, ValueError, TypeError, RuntimeError) as vault_err:
        logger.warning(f"Vault save gagal untuk {name}: {vault_err}")
        return False


def load_secret(name: str) -> str | None:
    """Baca secret dari vault; None/jika tak ada atau dekripsi gagal."""
    try:
        info = _vault().get_secret(name)
        if info and info.get("value"):
            return str(info["value"])
    except (sqlite3.Error, OSError, ValueError, TypeError, RuntimeError) as vault_err:
        logger.warning(f"Vault read gagal untuk {name}: {vault_err}")
    return None


def delete_secret(name: str) -> bool:
    """Hapus secret dari vault (logout/rotasi)."""
    try:
        vault = _vault()
        info = vault.get_secret(name)
        if not info:
            return False
        secret_id = info.get("id")
        from alfa.security.vault import _vault_db_path

        conn = sqlite3.connect(_vault_db_path())
        try:
            conn.execute("DELETE FROM vault_secrets WHERE id = ?", (secret_id,))
            conn.commit()
        finally:
            conn.close()
        return True
    except (sqlite3.Error, OSError, ValueError, TypeError, RuntimeError) as vault_err:
        logger.warning(f"Vault delete gagal untuk {name}: {vault_err}")
        return False

def _legacy_plaintext_read(key: str) -> str | None:
    """Baca sisa nilai plaintext (migrasi kompatibilitas) dari system_settings."""
    try:
        with database.get_sync_db() as conn:
            row = conn.execute(
                "SELECT value FROM system_settings WHERE key = ?", (key,)
            ).fetchone()
            return str(row[0]) if row and row[0] else None
    except (sqlite3.Error, OSError):
        return None


def migrate_legacy_plaintext() -> dict[str, bool | str]:
    """Pindahkan plaintext system_settings → vault (idempoten, sekali jalan).

    Dipanggil dari lifespan dashboard; juga aman dipanggil ulang kapan saja.
    Rows plaintext dihapus hanya setelah tersimpan terenkripsi di vault.
    """
    report: dict[str, bool | str] = {}
    for key, name in (
        ("gdrive_oauth_token_json", OAUTH_SECRET_NAME),
        ("gdrive_credentials_json", CRED_SECRET_NAME),
    ):
        plaintext = _legacy_plaintext_read(key)
        if not plaintext:
            report[key] = "kosong"
            continue
        if load_secret(name):
            # Sudah ada di vault; hapus plaintext legacy dengan aman
            ok_db = True
        else:
            ok_db = save_secret(name, plaintext)
            if not ok_db:
                report[key] = False
                continue
        try:
            with database.get_sync_db() as conn:
                conn.execute("DELETE FROM system_settings WHERE key = ?", (key,))
                conn.commit()
            report[key] = True
        except (sqlite3.Error, OSError) as e:
            logger.warning(f"Migrasi {key}: hapus plaintext gagal: {e}")
            report[key] = False
    return report


def load_oauth_token(scopes: list | None = None) -> dict | None:
    """Muat token_data OAuth: vault dulu, fallback plaintext legacy.

    JSON valid (walau kosong `{}`) dianggap ada — caller menilai isinya.
    """
    raw = load_secret(OAUTH_SECRET_NAME)
    if not raw:
        raw = _legacy_plaintext_read("gdrive_oauth_token_json")
    if not raw:
        return None
    try:
        info = _json.loads(raw)
        if isinstance(info, dict) and scopes:
            info.setdefault("scopes", scopes)
        return info if isinstance(info, dict) else None
    except (TypeError, _json.JSONDecodeError) as e:
        logger.warning(f"gdrive oauth token tidak valid: {e}")
        return None


def load_service_account_json() -> dict | None:
    """Muat SA JSON: vault dulu, fallback plaintext legacy."""
    raw = load_secret(CRED_SECRET_NAME)
    if not raw:
        raw = _legacy_plaintext_read("gdrive_credentials_json")
    if not raw:
        return None
    try:
        parsed = _json.loads(raw)
        return parsed if isinstance(parsed, dict) else None
    except (TypeError, _json.JSONDecodeError) as e:
        logger.warning(f"gdrive SA json tidak valid: {e}")
        return None
