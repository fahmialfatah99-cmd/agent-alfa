"""Trust & Evidence observability router untuk dashboard ALFA.

Read-only: ringkasan evidence ledger, daftar bukti eksekusi tool, dan
statistik context governor. Tidak ada endpoint mutasi di sini.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from alfa.core.brain.context_governor import governor_stats
from alfa.core.db.evidence import (
    evidence_summary_sync,
    ledger_mode,
    list_evidence_sync,
    turn_evidence_sync,
)

logger = logging.getLogger("Dashboard.Trust")

trust_router = APIRouter(prefix="/api/v1/trust", tags=["Trust"])


@trust_router.get("/summary")
async def trust_summary(
    hours: int = Query(default=24, ge=1, le=24 * 30),
    top_tools: int = Query(default=10, ge=1, le=50),
) -> dict[str, Any]:
    """Ringkasan evidence + context governor untuk panel Trust Center."""
    evidence = evidence_summary_sync(hours=hours, top_tools=top_tools)
    return {
        "status": "ok",
        "evidence": evidence,
        "evidence_mode": ledger_mode(),
        "context_governor": governor_stats(),
    }


@trust_router.get("/evidence")
async def list_evidence(
    limit: int = Query(default=50, ge=1, le=200),
    turn_id: str = Query(default="", max_length=128),
    path: str = Query(default="", max_length=1000),
) -> dict[str, Any]:
    """Daftar bukti terbaru (filter opsional ``turn_id``/``path``)."""
    try:
        rows = list_evidence_sync(limit=limit, turn_id=turn_id, path=path)
    except Exception as exc:  # pragma: no cover — panel tak mungkin crash app
        logger.warning("list evidence gagal: %s", exc)
        raise HTTPException(status_code=500, detail="evidence read failed") from exc
    return {"status": "ok", "count": len(rows), "evidence": rows}


@trust_router.get("/evidence/{turn_id}")
async def get_turn_evidence(turn_id: str) -> dict[str, Any]:
    """Semua bukti untuk satu ``turn_id``."""
    rows = turn_evidence_sync(turn_id)
    return {"status": "ok", "turn_id": turn_id, "count": len(rows), "evidence": rows}


@trust_router.get("/context")
async def context_governor_status() -> dict[str, Any]:
    """Statistik kompaksi konteks terakhir + batas aktif."""
    return {"status": "ok", "context_governor": governor_stats()}


@trust_router.get("/capabilities")
async def capability_grants(
    chat_id: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    """Daftar capability grant (read-only) + mode keamanan aktif."""
    from alfa.core.perm.capabilities import (
        capability_mode,
        capability_required,
        list_capabilities_sync,
    )

    grants = list_capabilities_sync(chat_id=chat_id, limit=limit)
    valid = [item for item in grants if item.get("valid")]
    return {
        "status": "ok",
        "mode": capability_mode(),
        "required": capability_required(),
        "count": len(grants),
        "valid_count": len(valid),
        "capabilities": grants,
    }


@trust_router.get("/tasks")
async def durable_task_status(
    limit: int = Query(default=25, ge=1, le=200),
) -> dict[str, Any]:
    """Ringkasan durable task runtime (read-only)."""
    from alfa.core.db.durable_tasks import (
        durable_mode,
        list_tasks_sync,
        task_count_sync,
    )

    rows = list_tasks_sync(limit=limit)
    return {
        "status": "ok",
        "mode": durable_mode(),
        "count": task_count_sync(),
        "tasks": rows,
    }


@trust_router.get("/skills")
async def compiled_skill_status(
    active_only: bool = Query(default=False),
    limit: int = Query(default=25, ge=1, le=200),
) -> dict[str, Any]:
    """Ringkasan skill compiler (read-only)."""
    from alfa.core.brain.skill_compiler import (
        compiler_mode,
        list_compiled_skills_sync,
    )

    rows = list_compiled_skills_sync(active_only=active_only, limit=limit)
    return {
        "status": "ok",
        "mode": compiler_mode(),
        "count": len(rows),
        "skills": rows,
    }
