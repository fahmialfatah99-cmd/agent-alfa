"""Run-trace observability router untuk dashboard ALFA.

Read-only: daftar jejak run multi-agen (laporan ringkas) dari tabel
``run_traces``. Tidak ada mutation endpoint di sini.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from alfa.core.db.run_trace import get_run_sync, list_runs_sync

logger = logging.getLogger("Dashboard.Trace")

trace_router = APIRouter(prefix="/api/v1/trace", tags=["Tracing"])


@trace_router.get("/runs")
async def list_trace_runs(
    limit: int = Query(default=25, ge=1, le=200),
    kind: str = Query(default="", max_length=64),
) -> dict[str, Any]:
    """Jejak run terakhir (terbaru dulu) utk panel dashboard."""
    try:
        runs = list_runs_sync(limit=limit, kind=kind)
    except Exception as exc:  # pragma: no cover — panel tak mungkin crash app
        logger.warning("list trace gagal: %s", exc)
        raise HTTPException(status_code=500, detail="trace read failed") from exc
    return {"status": "ok", "count": len(runs), "runs": runs}


@trace_router.get("/runs/{run_id}")
async def get_trace_run(run_id: str) -> dict[str, Any]:
    """Satu jejak run lengkap berdasarkan ``run_id``."""
    run_row: dict[str, Any] | None = get_run_sync(run_id)
    if run_row is None:
        raise HTTPException(status_code=404, detail="run tidak ditemukan")
    return {"status": "ok", "run": run_row}
