"""Galeri situs hasil kerja agent untuk dashboard web."""
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from alfa.dashboard.routes.auth import require_admin

router = APIRouter()


@router.get("/api/sites")
async def api_sites() -> dict[str, Any]:
    try:
        from alfa.tools import serve_site

        rows = serve_site(action="status").get("sites", []) or []
        return {"status": "success", "total": len(rows), "sites": rows}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/api/sites/{slug}/{action}", dependencies=[Depends(require_admin)])
async def api_site_action(slug: str, action: str) -> dict[str, Any]:
    if action not in ("start", "stop"):
        raise HTTPException(status_code=400, detail="aksi harus start|stop")
    try:
        from alfa.tools import serve_site

        res = serve_site(action=action, slug=slug)
        if res.get("status") == "error":
            raise HTTPException(status_code=404, detail=res.get("message", "?"))
        return res
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/api/budget/today")
async def api_budget_today() -> dict[str, Any]:
    try:
        from alfa.core.rate_limiter import get_budget_report

        return get_budget_report()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/api/budget/reset")
async def api_budget_reset() -> dict[str, Any]:
    try:
        from alfa.core.rate_limiter import reset_user_usage_today

        deleted = reset_user_usage_today()
        return {"status": "ok", "deleted": deleted}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

