"""Observability (traces) & swarm checkpoint endpoints."""

from fastapi import APIRouter

router = APIRouter()


# ==================== OBSERVABILITY & CHECKPOINTS ====================


@router.get("/api/traces")
async def get_traces_endpoint(limit: int = 50):
    """Ambil riwayat trace observability terbaru."""
    try:
        from alfa.core import tracing

        traces = tracing.get_recent_traces(n=min(200, max(1, limit)))
        return {"status": "success", "total": len(traces), "traces": traces}
    except Exception as e:
        return {"status": "error", "message": f"Error fetching traces: {e}"}


@router.get("/api/traces/{trace_id}")
async def get_trace_detail_endpoint(trace_id: str):
    """Ambil detail span dari satu trace ID tertentu."""
    try:
        from alfa.core import tracing

        spans = tracing.get_trace_by_id(trace_id)
        return {"status": "success", "trace_id": trace_id, "spans": spans}
    except Exception as e:
        return {"status": "error", "message": f"Error fetching trace detail: {e}"}


@router.get("/api/checkpoints")
async def get_checkpoints_endpoint():
    """Ambil daftar checkpoint swarm yang dapat di-resume."""
    try:
        from alfa.swarm.checkpoint import SwarmCheckpoint

        resumable = SwarmCheckpoint.list_resumable()
        return {"status": "success", "total": len(resumable), "checkpoints": resumable}
    except Exception as e:
        return {"status": "error", "message": f"Error listing checkpoints: {e}"}


@router.post("/api/checkpoints/{session_id}/resume")
async def resume_checkpoint_endpoint(session_id: str):
    """Lanjutkan sesi swarm dari checkpoint."""
    try:
        from alfa.swarm import engine as swarm_engine

        res = await swarm_engine.resume_swarm_session(session_id)
        return res
    except Exception as e:
        return {"status": "error", "message": f"Error resuming session: {e}"}
