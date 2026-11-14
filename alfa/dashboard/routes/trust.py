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
