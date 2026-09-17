import asyncio
import json
import logging
import os
import shutil
import sqlite3
import subprocess
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import aiosqlite
import psutil
from dotenv import dotenv_values
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response

from alfa import tools
from alfa.core import database
from alfa.dashboard.common import REPO_ROOT, get_primary_user_id, logger, safe_int

router = APIRouter()

# ==================== SETTINGS & ANTIGRAVITY ====================

_models_cache: Dict[int, tuple] = {}


@router.get("/api/settings")
async def get_system_settings():
    """Retrieve current system configuration (.env and database settings)."""
    env_path = os.path.join(REPO_ROOT, ".env")
    env_vals = dotenv_values(env_path) if os.path.exists(env_path) else {}

    bot_token = env_vals.get("TELEGRAM_BOT_TOKEN", "")
    masked_bot_token = (
        (bot_token[:6] + "..." + bot_token[-4:])
        if len(bot_token) > 10
        else ("***" if bot_token else "")
    )

    gemini_key = env_vals.get("GEMINI_API_KEY", "")
    masked_gemini_key = (
        (gemini_key[:6] + "..." + gemini_key[-4:])
        if len(gemini_key) > 10
        else ("***" if gemini_key else "")
    )

    with database.get_sync_db() as conn:
        c = conn.cursor()
        c.execute("SELECT key, value FROM system_settings")
        db_settings = {row[0]: row[1] for row in c.fetchall()}

    alfa_prompt_path = os.path.expanduser("~/.alfa/system_prompt.txt")
    prompt_source = "env"
    active_instruction = env_vals.get("SYSTEM_INSTRUCTION", "")
    if os.path.exists(alfa_prompt_path):
        try:
            with open(alfa_prompt_path, "r", encoding="utf-8") as f:
                active_instruction = f.read().strip()
            prompt_source = "file"
        except Exception:
            pass

    try:
        from alfa.core import brain as _mb

        brain = _mb.get_main_brain()
        main_brain_info = {
            "provider": brain["provider"],
            "model": brain["model"],
            "key_id": brain["key_id"],
            "label": brain["label"],
        }
    except Exception:
        main_brain_info = {"provider": "?", "model": "", "key_id": None, "label": ""}

    vault_keys = database.list_api_keys_sync()

    return {
        "status": "success",
        "main_brain": main_brain_info,
        "vault_keys": [
            {
                "id": k["id"],
                "name": k["name"],
                "provider": k["provider"],
                "model": k["default_model"],
                "masked_key": k["masked_key"],
                "is_active": bool(k.get("is_active")),
            }
            for k in vault_keys
        ],
        "env": {
            "has_bot_token": bool(
                bot_token and bot_token != "your_telegram_bot_token_here"
            ),
            "masked_bot_token": masked_bot_token,
            "has_gemini_key": bool(
                gemini_key and gemini_key != "your_gemini_api_key_here"
            ),
            "masked_gemini_key": masked_gemini_key,
            "gemini_model": env_vals.get("GEMINI_MODEL", "gemini-3.6-flash"),
            "allowed_user_ids": env_vals.get("ALLOWED_USER_IDS", ""),
            "system_instruction": active_instruction,
            "system_instruction_source": prompt_source,
            "system_instruction_path": alfa_prompt_path,
        },
        "db_settings": db_settings,
    }


@router.get("/api/models-for-key")
async def models_for_key(key_id: int):
    """Fetch live model list dari provider kunci terpilih (60s cache)."""
    import httpx

    key_id = safe_int(key_id, 0)
    cached = _models_cache.get(key_id)
    if cached and (time.time() - cached[0]) < 60:
        return {"status": "success", "provider": cached[1], "models": cached[2]}

    row = None
    with database.get_sync_db() as conn:
        r = conn.execute(
            "SELECT provider, api_key, base_url FROM api_keys WHERE id = ?", (key_id,)
        )
        row = r.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Key tidak ditemukan")

    provider = (row["provider"] or "").lower()
    api_key = database.decrypt_key(row["api_key"] or "")
    base_url = (row["base_url"] or "").strip()
    models: List[str] = []
    try:
        if provider == "gemini":
            try:
                async with httpx.AsyncClient(timeout=15) as cli:
                    res = await cli.get(
                        "https://generativelanguage.googleapis.com/v1beta/models",
                        params={"key": api_key, "pageSize": 1000},
                    )
                if res.status_code == 200:
                    for m in res.json().get("models", []):
                        methods = m.get("supportedGenerationMethods") or []
                        if "generateContent" not in methods:
                            continue
                        mid = (m.get("name") or "").replace("models/", "")
                        if mid:
                            models.append(mid)
            except Exception:
                pass
            if not models:
                models = [
                    "gemini-3.7-flash",
                    "gemini-3.6-flash",
                    "gemini-3.6-flash-lite",
                    "gemini-3.1-pro-preview",
                    "gemini-3.1-flash-lite",
                    "gemini-3-flash-preview",
                    "gemini-flash-latest",
                    "gemini-pro-latest",
                ]
        else:
            base = base_url or {
                "openrouter": "https://openrouter.ai/api/v1",
                "nvidia": "https://integrate.api.nvidia.com/v1",
                "deepseek": "https://api.deepseek.com/v1",
                "openai": "https://api.openai.com/v1",
                "groq": "https://api.groq.com/openai/v1",
            }.get(provider, "")
            if base:
                async with httpx.AsyncClient(timeout=30) as cli:
                    res = await cli.get(
                        f"{base.rstrip('/')}/models",
                        headers={"Authorization": f"Bearer {api_key}"},
                    )
                if res.status_code == 200:
                    for m in res.json().get("data", []):
                        mid = m.get("id")
                        if mid:
                            models.append(mid)
        models = sorted(set(models))
        _models_cache.clear()
        _models_cache[key_id] = (time.time(), provider, models)
        return {"status": "success", "provider": provider, "models": models}
    except Exception as e:
        return {
            "status": "error",
            "message": str(e),
            "provider": provider,
            "models": [],
        }


async def antigravity_set_main_brain_impl(key_id: int, model: str):
    with database.get_sync_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO system_settings (key, value) VALUES ('main_brain_key_id', ?)",
            (str(key_id),),
        )
        conn.execute(
            "INSERT OR REPLACE INTO system_settings (key, value) VALUES ('main_brain_model', ?)",
            (model,),
        )
        conn.commit()
    from alfa.core import brain as _mb

    brain = _mb.get_main_brain()
    return {
        "main_brain": {
            "provider": brain["provider"],
            "model": brain["model"],
            "key_id": brain["key_id"],
            "label": brain["label"],
        }
    }


@router.post("/api/antigravity/apply")
async def antigravity_apply_model(payload: Dict[str, Any]):
    """Terapkan model Antigravity sebagai KUNCI CADANGAN (+ opsional semua agen)."""
    model = str(payload.get("model", "")).strip()
    apply_all = bool(payload.get("apply_all_agents", True))
    as_main_brain = bool(payload.get("as_main_brain", False))

    target_key = None
    for k in database.list_api_keys_sync():
        if "8890" in (k.get("base_url") or ""):
            target_key = k
            break
    if not target_key:
        r = database.add_api_key_sync(
            name="Antigravity Multi-Account",
            provider="custom",
            api_key="antigravity",
            default_model=model or "gemini-3.6-flash",
            base_url="http://127.0.0.1:8890/v1",
            set_active=False,
        )
        key_id = r.get("id")
    else:
        key_id = target_key["id"]
        database.update_api_key_model(key_id, model or "gemini-3.6-flash")

    updated = []
    if apply_all:
        for a in database.list_custom_agents_sync():
            if a.get("is_enabled", 1):
                database.update_custom_agent_sync(
                    a["id"],
                    {
                        "provider": "custom",
                        "model": model or "gemini-3.6-flash",
                        "api_key_id": key_id,
                    },
                )
                updated.append(a["name"])

    brain_note = ""
    main_brain_info = None

    if as_main_brain:
        brain_res = await antigravity_set_main_brain_impl(
            key_id, model or "gemini-3.6-flash"
        )
        main_brain_info = brain_res.get("main_brain")
        brain_note = " Otak utama dialihkan ke Antigravity."
    else:
        brain_note = (
            " Mode cadangan: otak utama tidak berubah "
            "(aktifkan via kartu Otak Utama bila diperlukan)."
        )

    return {
        "status": "success",
        "key_id": key_id,
        "model": model,
        "agents_updated": updated,
        "agents_count": len(updated),
        "as_main_brain": as_main_brain,
        "main_brain": main_brain_info,
        "message": (
            f"Kunci cadangan '{model}' siap ({len(updated)} agen swarm ikut memakai)."
            f"{brain_note}"
        ),
    }


@router.post("/api/main-brain/test")
async def test_main_brain_combo(payload: Dict[str, Any]):
    """Tes koneksi kombinasi kunci + model sebelum diterapkan."""
    import httpx as _hx

    try:
        key_id = int(payload.get("key_id", 0))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="key_id wajib angka")
    model = str(payload.get("model", "")).strip()
    row = None
    with database.get_sync_db() as conn:
        r = conn.execute(
            "SELECT provider, api_key, base_url FROM api_keys WHERE id=?", (key_id,)
        ).fetchone()
        row = dict(r) if r else None
    if not row:
        return {"status": "error", "message": "Key tidak ditemukan"}
    row["api_key"] = database.decrypt_key(row.get("api_key") or "")

    provider = (row["provider"] or "").lower()
    t0 = time.time()
    try:
        if provider == "gemini":
            from google import genai as _genai
            from google.genai import types as _types

            client = _genai.Client(api_key=row["api_key"])
            resp = await client.aio.models.generate_content(
                model=model or "gemini-3.6-flash",
                contents="Balas satu kata: SIAP",
                config=_types.GenerateContentConfig(max_output_tokens=100),
            )
            text = (resp.text or "").strip()
            ok = bool(text)
            snippet = text[:80]
        else:
            base = (row["base_url"] or "").rstrip("/")
            async with _hx.AsyncClient(timeout=_hx.Timeout(60.0, connect=10.0)) as cli:
                r2 = await cli.post(
                    f"{base}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {row['api_key']}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": model or "all",
                        "messages": [
                            {"role": "user", "content": "Balas satu kata: SIAP"}
                        ],
                        "max_tokens": 50,
                        "stream": False,
                    },
                )
            ok = r2.status_code == 200
            if ok:
                try:
                    snippet = (
                        r2.json()
                        .get("choices", [{}])[0]
                        .get("message", {})
                        .get("content", "")
                        or ""
                    )[:80]
                except Exception:
                    snippet = r2.text[:80]
            else:
                snippet = f"HTTP {r2.status_code}: {r2.text[:120]}"
        ms = round((time.time() - t0) * 1000)
        return {
            "status": "success" if ok else "error",
            "latency_ms": ms,
            "snippet": snippet,
            "message": ("Koneksi OK" if ok else f"Gagal: {snippet}"),
        }
    except Exception as e:
        return {"status": "error", "message": f"Error: {str(e)[:200]}"}


@router.post("/api/settings/main-brain")
async def set_main_brain_endpoint(payload: Dict[str, Any]):
    """Set the agent's MAIN BRAIN by activating a specific vault key."""
    key_id = payload.get("key_id")
    model_override = str(payload.get("model", "") or "").strip()
    try:
        key_id = int(key_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="key_id wajib berupa angka.")
    res = database.activate_api_key_sync(key_id)
    database.set_main_brain_model(model_override)
    if res.get("status") == "success":
        key_row = None
        with database.get_sync_db() as conn:
            kr = conn.execute(
                "SELECT provider, default_model FROM api_keys WHERE id = ?", (key_id,)
            ).fetchone()
            key_row = dict(kr) if kr else None
        if key_row:
            for a in database.list_custom_agents_sync():
                if a["name"] == "Alpha Lead":
                    database.update_custom_agent_sync(
                        a["id"],
                        {
                            "provider": key_row["provider"],
                            "model": model_override or key_row["default_model"],
                            "api_key_id": key_id,
                        },
                    )
                    res["synced_agents"] = ["Alpha Lead"]
                    res["message"] += " Alpha Lead ikut tersinkron."
                    break

        from alfa.core import brain as _mb

        brain = _mb.get_main_brain()
        res["main_brain"] = {
            "provider": brain["provider"],
            "model": brain["model"],
            "key_id": brain["key_id"],
            "label": brain["label"],
        }
        res["message"] += f" Model: {brain['model']}"
    return res


@router.post("/api/settings")
async def update_system_settings(payload: Dict[str, Any]):
    """Update system configuration (.env and database settings)."""
    env_path = os.path.join(REPO_ROOT, ".env")

    def _get(field: str) -> Optional[str]:
        if field in payload and isinstance(payload[field], str):
            return payload[field].strip()
        return None

    bot_token = _get("telegram_bot_token")
    gemini_key = _get("gemini_api_key")
    gemini_model = _get("gemini_model")
    allowed_ids = _get("allowed_user_ids")
    system_instruction = _get("system_instruction")

    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    else:
        lines = []

    new_lines = []
    keys_seen = set()

    for line in lines:
        if line.startswith("TELEGRAM_BOT_TOKEN="):
            keys_seen.add("TELEGRAM_BOT_TOKEN")
            if (
                bot_token is not None
                and bot_token
                and not bot_token.startswith("***")
                and "..." not in bot_token
            ):
                new_lines.append(f"TELEGRAM_BOT_TOKEN={bot_token}\n")
            else:
                new_lines.append(line)
        elif line.startswith("GEMINI_API_KEY="):
            keys_seen.add("GEMINI_API_KEY")
            if (
                gemini_key is not None
                and gemini_key
                and not gemini_key.startswith("***")
                and "..." not in gemini_key
            ):
                new_lines.append(f"GEMINI_API_KEY={gemini_key}\n")
            else:
                new_lines.append(line)
        elif line.startswith("GEMINI_MODEL="):
            keys_seen.add("GEMINI_MODEL")
            if gemini_model is not None and gemini_model:
                new_lines.append(f"GEMINI_MODEL={gemini_model}\n")
            else:
                new_lines.append(line)
        elif line.startswith("ALLOWED_USER_IDS="):
            keys_seen.add("ALLOWED_USER_IDS")
            if allowed_ids is not None:
                new_lines.append(f"ALLOWED_USER_IDS={allowed_ids}\n")
            else:
                new_lines.append(line)
        elif line.startswith("SYSTEM_INSTRUCTION="):
            keys_seen.add("SYSTEM_INSTRUCTION")
            if system_instruction is not None and system_instruction:
                escaped_instr = (
                    system_instruction.replace("\\", "\\\\")
                    .replace('"', '\\"')
                    .replace("\n", "\\n")
                )
                new_lines.append(f'SYSTEM_INSTRUCTION="{escaped_instr}"\n')
            else:
                new_lines.append(line)
        else:
            new_lines.append(line)

    pending = []
    if (
        "TELEGRAM_BOT_TOKEN" not in keys_seen
        and bot_token
        and not bot_token.startswith("***")
        and "..." not in bot_token
    ):
        pending.append(f"TELEGRAM_BOT_TOKEN={bot_token}\n")
    if (
        "GEMINI_API_KEY" not in keys_seen
        and gemini_key
        and not gemini_key.startswith("***")
        and "..." not in gemini_key
    ):
        pending.append(f"GEMINI_API_KEY={gemini_key}\n")
    if "GEMINI_MODEL" not in keys_seen and gemini_model:
        pending.append(f"GEMINI_MODEL={gemini_model}\n")
    if "ALLOWED_USER_IDS" not in keys_seen and allowed_ids is not None:
        pending.append(f"ALLOWED_USER_IDS={allowed_ids}\n")
    if "SYSTEM_INSTRUCTION" not in keys_seen and system_instruction:
        escaped_instr = (
            system_instruction.replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("\n", "\\n")
        )
        pending.append(f'SYSTEM_INSTRUCTION="{escaped_instr}"\n')

    if pending or new_lines != lines:
        with open(env_path, "w", encoding="utf-8") as f:
            f.writelines(new_lines + pending)

    if system_instruction is not None:
        alfa_dir = os.path.expanduser("~/.alfa")
        alfa_prompt_path = os.path.join(alfa_dir, "system_prompt.txt")
        try:
            os.makedirs(alfa_dir, exist_ok=True)
            if os.path.exists(alfa_prompt_path):
                shutil.copyfile(alfa_prompt_path, alfa_prompt_path + ".bak")
            with open(alfa_prompt_path, "w", encoding="utf-8") as f:
                f.write(system_instruction + "\n")
        except Exception as prompt_err:
            return {
                "status": "error",
                "message": f"Gagal menulis {alfa_prompt_path}: {prompt_err}",
            }

    db_updates = payload.get("db_settings", {})
    if db_updates:
        with database.get_sync_db() as conn:
            c = conn.cursor()
            c.execute(
                "CREATE TABLE IF NOT EXISTS system_settings (key TEXT PRIMARY KEY, value TEXT)"
            )
            for k, v in db_updates.items():
                c.execute(
                    "INSERT OR REPLACE INTO system_settings (key, value) VALUES (?, ?)",
                    (str(k), str(v)),
                )
            conn.commit()

    return {
        "status": "success",
        "message": "Konfigurasi tersimpan. Kepribadian agent langsung aktif (Telegram & Web) tanpa restart.",
    }
