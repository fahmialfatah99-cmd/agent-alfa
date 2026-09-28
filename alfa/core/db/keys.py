"""
API Key Multi-Provider Vault & Brain Model configuration.
"""

import logging
from typing import Any

from alfa.core.db.connection import get_sync_db
from alfa.core.db.crypto import decrypt_key, encrypt_key, mask_key

logger = logging.getLogger("DB.Keys")


def sync_external_api_keys_sync() -> list[dict[str, Any]]:
    """Automatically discover and synchronize API keys from external sources:
    1. 9Router Gateway local SQLite (~/.9router/db/data.sqlite)
    2. CLI configuration file (~/.alfa_cli_config.json)
    3. Environment variables (.env or os.environ)
    into the SQLite Database Vault (agent_data.db).
    """
    import glob
    import json
    import os
    import sqlite3
    from pathlib import Path

    synced: list[dict[str, Any]] = []

    try:
        # Check existing keys in agent_data.db to avoid duplicates
        existing_keys: set[str] = set()
        with get_sync_db() as conn:
            rows = conn.execute("SELECT provider, api_key FROM api_keys").fetchall()
            for r in rows:
                p = (r["provider"] or "").lower().strip()
                try:
                    dec = decrypt_key(r["api_key"]).strip()
                except Exception:
                    dec = (r["api_key"] or "").strip()
                if dec:
                    existing_keys.add(f"{p}:{dec}")

        # 1. 9Router Auto-Discovery from local SQLite
        paths = glob.glob(os.path.expanduser("~/.9router/db/data.sqlite")) + glob.glob(
            os.path.expandvars(r"%APPDATA%\9router\db\data.sqlite")
        )
        for dbp in paths:
            if os.path.exists(dbp):
                try:
                    with sqlite3.connect(dbp) as rconn:
                        r_rows = rconn.execute(
                            "SELECT key, name, isActive FROM apiKeys"
                        ).fetchall()
                        for rk, rname, ris_active in r_rows:
                            if not rk:
                                continue
                            rk = rk.strip()
                            ident = f"9router:{rk}"
                            if ident not in existing_keys:
                                with get_sync_db() as conn:
                                    conn.execute(
                                        """
                                        INSERT INTO api_keys (name, provider, api_key, base_url, default_model, is_active)
                                        VALUES (?, ?, ?, ?, ?, ?)
                                        """,
                                        (
                                            f"9Router ({rname or 'Gateway'})",
                                            "9router",
                                            encrypt_key(rk),
                                            "http://127.0.0.1:20128/v1",
                                            "antigravity",
                                            1 if ris_active else 0,
                                        ),
                                    )
                                    conn.commit()
                                existing_keys.add(ident)
                                synced.append(
                                    {"provider": "9router", "name": rname, "key": rk}
                                )
                except Exception as e:
                    logger.debug(f"9router sqlite sync check error: {e}")

        # 2. CLI Configuration (~/.alfa_cli_config.json)
        cfg_paths = [
            Path.home() / ".alfa_cli_config.json",
            Path.home() / ".alfa" / "config.json",
        ]
        for cfg_p in cfg_paths:
            if cfg_p.exists():
                try:
                    cfg_data = json.loads(cfg_p.read_text(encoding="utf-8"))
                    api_keys = cfg_data.get("api_keys", {})
                    for prov, k_val in api_keys.items():
                        if not k_val:
                            continue
                        k_val = k_val.strip()
                        p_norm = prov.lower().strip()
                        if p_norm == "google":
                            p_norm = "gemini"
                        ident = f"{p_norm}:{k_val}"
                        if ident not in existing_keys:
                            base_url = None
                            def_model = "default"
                            if p_norm == "9router":
                                base_url = "http://127.0.0.1:20128/v1"
                                def_model = "antigravity"
                            elif p_norm == "nvidia":
                                base_url = "https://integrate.api.nvidia.com/v1"
                                def_model = "nvidia/llama-3.1-nemotron-70b-instruct"

                            with get_sync_db() as conn:
                                conn.execute(
                                    """
                                    INSERT INTO api_keys (name, provider, api_key, base_url, default_model, is_active)
                                    VALUES (?, ?, ?, ?, ?, ?)
                                    """,
                                    (
                                        f"{prov.upper()} Key (CLI Config)",
                                        p_norm,
                                        encrypt_key(k_val),
                                        base_url,
                                        def_model,
                                        1,
                                    ),
                                )
                                conn.commit()
                            existing_keys.add(ident)
                            synced.append(
                                {"provider": p_norm, "name": "CLI Config", "key": k_val}
                            )
                except Exception as e:
                    logger.debug(f"CLI config sync error: {e}")

        # 3. Environment Variables (NINEROUTER_API_KEY, ROUTER_API_KEY, etc.)
        env_mappings = [
            (
                "9router",
                "NINEROUTER_API_KEY",
                "http://127.0.0.1:20128/v1",
                "antigravity",
            ),
            ("9router", "ROUTER_API_KEY", "http://127.0.0.1:20128/v1", "antigravity"),
            (
                "nvidia",
                "NVIDIA_API_KEY",
                "https://integrate.api.nvidia.com/v1",
                "nvidia/llama-3.1-nemotron-70b-instruct",
            ),
        ]
        for p_norm, env_var, b_url, d_mod in env_mappings:
            e_val = os.getenv(env_var)
            if e_val:
                e_val = e_val.strip()
                ident = f"{p_norm}:{e_val}"
                if ident not in existing_keys:
                    with get_sync_db() as conn:
                        conn.execute(
                            """
                            INSERT INTO api_keys (name, provider, api_key, base_url, default_model, is_active)
                            VALUES (?, ?, ?, ?, ?, ?)
                            """,
                            (
                                f"{p_norm.upper()} ({env_var})",
                                p_norm,
                                encrypt_key(e_val),
                                b_url,
                                d_mod,
                                1,
                            ),
                        )
                        conn.commit()
                    existing_keys.add(ident)
                    synced.append({"provider": p_norm, "name": env_var, "key": e_val})

    except Exception as exc:
        logger.warning(f"Error in sync_external_api_keys_sync: {exc}")

    return synced


def list_api_keys_sync(auto_sync: bool = True) -> list[dict[str, Any]]:
    """List all configured API keys with masked key values.
    Automatically syncs external keys from 9Router, CLI config, and .env if auto_sync is True.
    """
    if auto_sync:
        try:
            sync_external_api_keys_sync()
        except Exception:
            pass

    with get_sync_db() as conn:
        cursor = conn.execute(
            "SELECT id, name, provider, api_key, base_url, default_model, is_active, created_at FROM api_keys ORDER BY id ASC"
        )
        rows = cursor.fetchall()
        results = []
        for r in rows:
            results.append(
                {
                    "id": r["id"],
                    "name": r["name"],
                    "provider": r["provider"],
                    "masked_key": mask_key(decrypt_key(r["api_key"])),
                    "base_url": r["base_url"] or "",
                    "default_model": r["default_model"],
                    "is_active": bool(r["is_active"]),
                    "created_at": str(r["created_at"]),
                }
            )
        return results


def add_api_key_sync(
    name: str,
    provider: str,
    api_key: str,
    default_model: str,
    base_url: str = "",
    set_active: bool = False,
) -> dict[str, Any]:
    """Add a new API key to the vault."""
    provider_norm = provider.strip().lower()
    with get_sync_db() as conn:
        if set_active:
            conn.execute(
                "UPDATE api_keys SET is_active = 0 WHERE provider = ?", (provider_norm,)
            )
        cursor = conn.execute(
            """
            INSERT INTO api_keys (name, provider, api_key, base_url, default_model, is_active)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                name,
                provider_norm,
                encrypt_key(api_key.strip()),
                base_url.strip() if base_url else None,
                default_model,
                1 if set_active else 0,
            ),
        )
        conn.commit()
        key_id = cursor.lastrowid
    return {"status": "success", "id": key_id, "name": name, "provider": provider_norm}


def activate_api_key_sync(
    key_id: int, custom_model: str | None = None
) -> dict[str, Any]:
    """Set an API key as active. The MOST RECENTLY activated key across any
    provider automatically becomes the MAIN BRAIN for the Telegram/Web agent."""
    with get_sync_db() as conn:
        cursor = conn.execute(
            "SELECT provider, default_model FROM api_keys WHERE id = ?", (key_id,)
        )
        row = cursor.fetchone()
        if not row:
            return {"status": "error", "message": "Key not found"}
        prov = row["provider"]
        conn.execute("UPDATE api_keys SET is_active = 0 WHERE provider = ?", (prov,))
        conn.execute("UPDATE api_keys SET is_active = 1 WHERE id = ?", (key_id,))
        conn.execute(
            "INSERT OR REPLACE INTO system_settings (key, value) VALUES ('main_brain_key_id', ?)",
            (str(key_id),),
        )
        target_model = (custom_model or "").strip() or (
            row["default_model"] or ""
        ).strip()
        conn.execute(
            "INSERT OR REPLACE INTO system_settings (key, value) VALUES ('main_brain_model', ?)",
            (target_model,),
        )
        conn.commit()
    return {
        "status": "success",
        "message": f"API key #{key_id} activated & model disetel ke '{target_model}'",
    }


def set_main_brain_model(model: str) -> None:
    """Simpan pilihan model eksplisit utk otak utama ('' = ikuti default kunci)."""
    with get_sync_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO system_settings (key, value) VALUES ('main_brain_model', ?)",
            ((model or "").strip(),),
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


def get_api_key_by_id_sync(key_id: int) -> dict[str, Any] | None:
    """Ambil record API key berdasarkan ID dengan kunci terdekripsi."""
    try:
        with get_sync_db() as conn:
            cursor = conn.execute(
                "SELECT id, name, provider, api_key, base_url, default_model, is_active, created_at FROM api_keys WHERE id = ?",
                (key_id,),
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


def get_main_brain_key_id() -> int | None:
    """Return key id marked as main brain, if still valid."""
    try:
        with get_sync_db() as conn:
            row = conn.execute("""
                SELECT k.id FROM system_settings s
                JOIN api_keys k ON k.id = CAST(s.value AS INTEGER) AND k.is_active = 1
                WHERE s.key = 'main_brain_key_id'
                LIMIT 1
                """).fetchone()
            return int(row[0]) if row else None
    except Exception:
        return None


def delete_api_key_sync(key_id: int) -> dict[str, Any]:
    """Delete an API key from the vault."""
    with get_sync_db() as conn:
        cursor = conn.execute("DELETE FROM api_keys WHERE id = ?", (key_id,))
        conn.execute(
            "UPDATE custom_agents SET api_key_id = NULL WHERE api_key_id = ?", (key_id,)
        )
        conn.commit()
        if cursor.rowcount == 0:
            return {"status": "error", "message": f"API key #{key_id} not found"}
    return {"status": "success", "message": f"API key #{key_id} deleted"}


def get_active_api_key_sync(provider: str = "gemini") -> dict[str, Any] | None:
    """Get active API key record for a given provider."""
    with get_sync_db() as conn:
        cursor = conn.execute(
            "SELECT * FROM api_keys WHERE provider = ? AND is_active = 1 LIMIT 1",
            (provider.lower(),),
        )
        row = cursor.fetchone()
        if row:
            d = dict(row)
            d["api_key"] = decrypt_key(d.get("api_key") or "")
            return d
        cursor = conn.execute(
            "SELECT * FROM api_keys WHERE provider = ? ORDER BY is_active DESC, id ASC LIMIT 1",
            (provider.lower(),),
        )
        row = cursor.fetchone()
        if row:
            d = dict(row)
            d["api_key"] = decrypt_key(d.get("api_key") or "")
            return d
    return None


def list_active_keys_sync(exclude_provider: str = "") -> list[dict[str, Any]]:
    """Daftar semua kunci aktif (didekripsi), opsional kecualikan satu provider."""
    out: list[dict[str, Any]] = []
    try:
        excl = (exclude_provider or "").lower()
        with get_sync_db() as conn:
            cursor = conn.execute(
                "SELECT * FROM api_keys WHERE is_active = 1 ORDER BY id ASC"
            )
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
                (model.strip(), int(key_id)),
            )
            conn.commit()
            return bool(cur.rowcount and cur.rowcount > 0)
    except Exception:
        return False
