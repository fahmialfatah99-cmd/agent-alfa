"""Main-brain resolution (vault/env/offline -> provider credentials)."""

import logging
import os
from typing import Any

from alfa.core.brain.config import PROJECT_DIR

logger = logging.getLogger("MainBrain")


def get_main_brain(
    override_key_id: int | None = None, override_model: str | None = None
) -> dict[str, Any]:
    """
    Return dict: {provider, api_key, model, base_url, key_id, label}
    Prioritas: ALFA_OFFLINE_MODE -> override_key_id -> pointer main_brain_key_id -> kunci aktif di vault -> .env
    """
    # Cek mode offline / Ollama lokal otonom
    if os.getenv("ALFA_OFFLINE_MODE", "").lower() in ("true", "1", "on"):
        return {
            "provider": "ollama",
            "api_key": "ollama",
            "model": override_model or os.getenv("OLLAMA_MODEL", "hermes3:latest"),
            "base_url": os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
            "key_id": None,
            "label": "ollama-local",
        }

    from alfa.core import database

    kid = override_key_id or database.get_main_brain_key_id()
    if kid:
        try:
            with database.get_sync_db() as conn:
                row = conn.execute(
                    "SELECT id, provider, api_key, default_model, base_url "
                    "FROM api_keys WHERE id = ?",
                    (kid,),
                ).fetchone()
            if row:
                model = override_model or row["default_model"]
                if not override_model:
                    override = database.get_main_brain_model()
                    if override:
                        model = override
                return {
                    "provider": row["provider"].lower(),
                    "api_key": database.decrypt_key(row["api_key"]),
                    "model": model,
                    "base_url": row["base_url"] or "",
                    "key_id": row["id"],
                    "label": f"brain#{row['id']}",
                }
        except Exception as e:
            logger.warning(f"main brain pointer unreadable: {e}")

    # Fallback: kunci gemini aktif di vault, lalu .env
    try:
        gk = database.get_active_api_key_sync("gemini")
    except Exception:
        gk = None
    if gk and (gk.get("api_key") or "").strip():
        return {
            "provider": "gemini",
            "api_key": gk["api_key"].strip(),
            "model": override_model or gk.get("default_model") or "",
            "base_url": "",
            "key_id": gk.get("id"),
            "label": f"brain#{gk.get('id')}",
        }

    from dotenv import load_dotenv

    load_dotenv(os.path.join(PROJECT_DIR, ".env"))
    env_key = os.getenv("GEMINI_API_KEY", "").strip()
    return {
        "provider": "gemini" if env_key else "none",
        "api_key": env_key,
        "model": override_model or os.getenv("GEMINI_MODEL", ""),
        "base_url": "",
        "key_id": None,
        "label": "gemini-env",
    }


get_brain = get_main_brain
