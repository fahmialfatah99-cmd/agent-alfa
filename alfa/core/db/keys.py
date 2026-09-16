# -*- coding: utf-8 -*-
"""
API Key Multi-Provider Vault & Brain Model configuration.
"""

import logging
from typing import Any, Dict, List, Optional

from alfa.core.db.connection import get_sync_db
from alfa.core.db.crypto import decrypt_key, encrypt_key, mask_key

logger = logging.getLogger("DB.Keys")


def list_api_keys_sync() -> List[Dict[str, Any]]:
    """List all configured API keys with masked key values."""
    with get_sync_db() as conn:
        cursor = conn.execute("SELECT id, name, provider, api_key, base_url, default_model, is_active, created_at FROM api_keys ORDER BY id ASC")
        rows = cursor.fetchall()
        results = []
        for r in rows:
            results.append({
                "id": r["id"],
                "name": r["name"],
                "provider": r["provider"],
                "masked_key": mask_key(decrypt_key(r["api_key"])),
                "base_url": r["base_url"] or "",
                "default_model": r["default_model"],
                "is_active": bool(r["is_active"]),
                "created_at": str(r["created_at"])
            })
        return results


def add_api_key_sync(name: str, provider: str, api_key: str, default_model: str, base_url: str = "", set_active: bool = False) -> Dict[str, Any]:
    """Add a new API key to the vault."""
    provider_norm = provider.strip().lower()
    with get_sync_db() as conn:
        if set_active:
            conn.execute("UPDATE api_keys SET is_active = 0 WHERE provider = ?", (provider_norm,))
        cursor = conn.execute(
            """
            INSERT INTO api_keys (name, provider, api_key, base_url, default_model, is_active)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (name, provider_norm, encrypt_key(api_key.strip()), base_url.strip() if base_url else None, default_model, 1 if set_active else 0)
        )
        conn.commit()
        key_id = cursor.lastrowid
    return {"status": "success", "id": key_id, "name": name, "provider": provider_norm}


def activate_api_key_sync(key_id: int, custom_model: Optional[str] = None) -> Dict[str, Any]:
    """Set an API key as active. The MOST RECENTLY activated key across any
    provider automatically becomes the MAIN BRAIN for the Telegram/Web agent."""
    with get_sync_db() as conn:
        cursor = conn.execute("SELECT provider, default_model FROM api_keys WHERE id = ?", (key_id,))
        row = cursor.fetchone()
        if not row:
            return {"status": "error", "message": "Key not found"}
        prov = row["provider"]
        conn.execute("UPDATE api_keys SET is_active = 0 WHERE provider = ?", (prov,))
        conn.execute("UPDATE api_keys SET is_active = 1 WHERE id = ?", (key_id,))
        conn.execute(
            "INSERT OR REPLACE INTO system_settings (key, value) VALUES ('main_brain_key_id', ?)",
            (str(key_id),)
        )
        target_model = (custom_model or "").strip() or (row["default_model"] or "").strip()
        conn.execute(
            "INSERT OR REPLACE INTO system_settings (key, value) VALUES ('main_brain_model', ?)",
            (target_model,)
        )
        conn.commit()
    return {"status": "success", "message": f"API key #{key_id} activated & model disetel ke '{target_model}'"}


def set_main_brain_model(model: str) -> None:
    """Simpan pilihan model eksplisit utk otak utama ('' = ikuti default kunci)."""
    with get_sync_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO system_settings (key, value) VALUES ('main_brain_model', ?)",
            ((model or "").strip(),)
        )
        conn.commit()


def get_main_brain_model() -> str:
    """Model override otak utama ('' bila tidak disetel)."""
    try:
        with get_sync_db() as conn:
            row = conn.execute(
                "SELECT value FROM system_settings WHERE key = 'main_brain_model'"
            ).fetchone()
            return (row[0] or "").strip() if row else ""
    except Exception:
        return ""


def get_api_key_by_id_sync(key_id: int) -> Optional[Dict[str, Any]]:
    """Ambil record API key berdasarkan ID dengan kunci terdekripsi."""
    try:
        with get_sync_db() as conn:
            cursor = conn.execute(
                "SELECT id, name, provider, api_key, base_url, default_model, is_active, created_at FROM api_keys WHERE id = ?",
                (key_id,)
            )
            row = cursor.fetchone()
            if not row:
                return None
            res = dict(row)
            res["api_key"] = decrypt_key(res["api_key"])
            return res
    except Exception as e:
        logger.error(f"Error fetching API key #{key_id}: {e}")
        return None


def get_main_brain_key_id() -> Optional[int]:
    """Return key id marked as main brain, if still valid."""
    try:
        with get_sync_db() as conn:
            row = conn.execute(
                """
                SELECT k.id FROM system_settings s
                JOIN api_keys k ON k.id = CAST(s.value AS INTEGER) AND k.is_active = 1
                WHERE s.key = 'main_brain_key_id'
                LIMIT 1
                """
            ).fetchone()
            return int(row[0]) if row else None
    except Exception:
        return None


def delete_api_key_sync(key_id: int) -> Dict[str, Any]:
    """Delete an API key from the vault."""
    with get_sync_db() as conn:
        cursor = conn.execute("DELETE FROM api_keys WHERE id = ?", (key_id,))
        conn.execute("UPDATE custom_agents SET api_key_id = NULL WHERE api_key_id = ?", (key_id,))
        conn.commit()
        if cursor.rowcount == 0:
            return {"status": "error", "message": f"API key #{key_id} not found"}
    return {"status": "success", "message": f"API key #{key_id} deleted"}


def get_active_api_key_sync(provider: str = "gemini") -> Optional[Dict[str, Any]]:
    """Get active API key record for a given provider."""
    with get_sync_db() as conn:
        cursor = conn.execute("SELECT * FROM api_keys WHERE provider = ? AND is_active = 1 LIMIT 1", (provider.lower(),))
        row = cursor.fetchone()
        if row:
            d = dict(row)
            d["api_key"] = decrypt_key(d.get("api_key") or "")
            return d
        cursor = conn.execute(
            "SELECT * FROM api_keys WHERE provider = ? ORDER BY is_active DESC, id ASC LIMIT 1",
            (provider.lower(),)
        )
        row = cursor.fetchone()
        if row:
            d = dict(row)
            d["api_key"] = decrypt_key(d.get("api_key") or "")
            return d
    return None


def list_active_keys_sync(exclude_provider: str = "") -> List[Dict[str, Any]]:
    """Daftar semua kunci aktif (didekripsi), opsional kecualikan satu provider."""
    out: List[Dict[str, Any]] = []
    try:
        excl = (exclude_provider or "").lower()
        with get_sync_db() as conn:
            cursor = conn.execute(
                "SELECT * FROM api_keys WHERE is_active = 1 ORDER BY id ASC")
            for row in cursor.fetchall():
                d = dict(row)
                if excl and (d.get("provider") or "").lower() == excl:
                    continue
                try:
                    d["api_key"] = decrypt_key(d.get("api_key") or "")
                except Exception:
                    continue
                out.append(d)
    except Exception as e:
        logger.warning(f"list_active_keys_sync gagal: {e}")
    return out


def update_api_key_model(key_id: int, model: str) -> bool:
    """Update default_model sebuah kunci vault."""
    try:
        with get_sync_db() as conn:
            cur = conn.execute(
                "UPDATE api_keys SET default_model = ? WHERE id = ?",
                (model.strip(), int(key_id)))
            conn.commit()
            return cur.rowcount > 0
    except Exception:
        return False
