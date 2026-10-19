"""Antigravity OAuth suite endpoints."""
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from alfa.dashboard.routes.auth import require_admin

router = APIRouter()


# ==================== ANTIGRAVITY OAUTH SUITE ====================


@router.post("/api/antigravity/login/start", dependencies=[Depends(require_admin)])
async def antigravity_login_start(payload: dict[str, Any]):
    """Mulai sesi login Google utk akun Antigravity baru."""
    from alfa.integrations import antigravity_login as agy_oauth

    name = payload.get("name", "").strip().lower()
    if not name:
        raise HTTPException(status_code=400, detail="nama wajib diisi")
    res = agy_oauth.start_login(name)
    return res


@router.get("/api/antigravity/login/status")
async def antigravity_login_status(name: str = ""):
    from alfa.integrations import antigravity_login as agy_oauth

    return agy_oauth.login_status(name)


@router.get("/api/antigravity/accounts")
async def antigravity_accounts():
    from alfa.integrations import antigravity_login as agy_oauth

    return {"status": "success", "accounts": agy_oauth.list_accounts()}


@router.post("/api/antigravity/logout", dependencies=[Depends(require_admin)])
async def antigravity_logout_endpoint(payload: dict[str, Any]):
    from alfa.integrations import antigravity_login as agy_oauth

    return agy_oauth.remove_account(payload.get("name", ""))
