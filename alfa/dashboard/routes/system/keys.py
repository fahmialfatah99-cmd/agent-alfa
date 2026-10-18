"""API key vault endpoints for ALFA Dashboard."""

import time
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from alfa.core import database
from alfa.dashboard.common import safe_int
from alfa.dashboard.routes.auth import require_admin

router = APIRouter()

# ==================== API KEYS ====================


@router.get("/api/keys")
async def get_api_keys(request: Request):
    """List API keys ter-enrolled (hanya admin; key dimasking)."""
    require_admin(request)
    keys = database.list_api_keys_sync()
    return {"status": "success", "total": len(keys), "keys": keys}


@router.get("/api/keys/usage")
async def get_api_keys_usage(request: Request, hours: int = 24):
    """Realtime token-usage summary per API key/provider (hanya admin)."""
    require_admin(request)
    hours = safe_int(hours, 24, minimum=1, maximum=720)
    keys = database.list_api_keys_sync()
    key_names = {k["id"]: k["name"] for k in keys}
    summary = database.get_api_usage_summary_sync(hours=hours)
    for row in summary.get("per_key", []):
        row["key_name"] = (
            key_names.get(row.get("key_id")) or row.get("key_label") or "(env)"
        )
    return {"status": "success", **summary}


@router.post("/api/keys")
async def add_api_key_endpoint(payload: dict[str, Any], request: Request):
    """Add a new API key to the vault."""
    require_admin(request)
    name = payload.get("name")
    provider = payload.get("provider", "gemini")
    api_key = payload.get("api_key")
    default_model = payload.get("default_model", "gemini-3.5-flash")
    base_url = payload.get("base_url", "")
    set_active = payload.get("set_active", True)

    if not api_key:
        raise HTTPException(status_code=400, detail="api_key is required")

    res = database.add_api_key_sync(
        name=name or f"{provider.capitalize()} Key",
        provider=provider,
        api_key=api_key,
        default_model=default_model,
        base_url=base_url,
        set_active=set_active,
    )
    return res


@router.post("/api/keys/{key_id}/activate")
async def activate_api_key_endpoint(key_id: int, request: Request):
    """Set an API key as active."""
    require_admin(request)
    res = database.activate_api_key_sync(key_id)
    return res


@router.delete("/api/keys/{key_id}")
async def delete_api_key_endpoint(key_id: int, request: Request):
    """Delete an API key."""
    require_admin(request)
    res = database.delete_api_key_sync(key_id)
    return res


@router.post("/api/keys/{key_id}/test")
async def test_api_key_endpoint(request: Request, key_id: int):
    """Live ping koneksi API key memakai kuota server (hanya admin)."""
    require_admin(request)
    with database.get_sync_db() as conn:
        row = conn.execute("SELECT * FROM api_keys WHERE id = ?", (key_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="API Key tidak ditemukan")
        key_data = dict(row)

    from alfa.swarm import engine as swarm_engine

    dummy_agent = {
        "name": f"Tester-{key_data['provider']}",
        "provider": key_data["provider"],
        "model": key_data["default_model"],
        "api_key_id": key_id,
    }
    start_t = time.time()
    resp = await swarm_engine.generate_agent_response(
        agent=dummy_agent,
        prompt="Katakan 'Koneksi Berhasil' dalam 3 kata.",
        system_instruction="Kamu adalah modul health checker. Jawab dengan sangat singkat.",
    )
    duration_ms = round((time.time() - start_t) * 1000, 1)
    is_error = not resp or "[Error:" in resp or "Gagal memanggil" in resp

    return {
        "status": "error" if is_error else "success",
        "key_id": key_id,
        "provider": key_data["provider"],
        "model": key_data["default_model"],
        "duration_ms": duration_ms,
        "response": resp,
    }
