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


@router.get("/api/evals/runs")
async def get_eval_runs_endpoint(limit: int = 20):
    """Daftar ringkasan hasil eval (offline/live) dari storage/eval_runs/."""
    import glob
    import json
    import os

    try:
        from alfa.dashboard.common import REPO_ROOT

        runs = []
        for path in sorted(
            glob.glob(os.path.join(REPO_ROOT, "storage", "eval_runs", "*.json")),
            reverse=True,
        )[: max(1, min(100, limit))]:
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                runs.append(
                    {
                        "file": os.path.basename(path),
                        "timestamp": data.get("timestamp"),
                        "live": data.get("live"),
                        "total": data.get("total"),
                        "passed": data.get("passed"),
                        "failed": data.get("failed"),
                    }
                )
            except Exception:
                continue
        return {"status": "success", "total": len(runs), "runs": runs}
    except Exception as e:
        return {"status": "error", "message": f"Error listing eval runs: {e}"}


@router.get("/api/evals/runs/{filename}")
async def get_eval_run_detail_endpoint(filename: str):
    """Detail satu hasil eval (nama file dibatasi pola aman)."""
    import json
    import os
    import re

    try:
        from alfa.dashboard.common import REPO_ROOT

        if not re.fullmatch(r"[A-Za-z0-9_.\-]+\.json", filename or ""):
            return {"status": "error", "message": "Nama file tidak valid."}
        path = os.path.join(REPO_ROOT, "storage", "eval_runs", filename)
        with open(path, encoding="utf-8") as f:
            return {"status": "success", "run": json.load(f)}
    except FileNotFoundError:
        return {"status": "error", "message": "Hasil eval tidak ditemukan."}
    except Exception as e:
        return {"status": "error", "message": f"Error reading eval run: {e}"}


@router.post("/api/checkpoints/{session_id}/resume")
async def resume_checkpoint_endpoint(session_id: str):
    """Lanjutkan sesi swarm dari checkpoint."""
    try:
        from alfa.swarm import engine as swarm_engine

        res = await swarm_engine.resume_swarm_session(session_id)
        return res
    except Exception as e:
        return {"status": "error", "message": f"Error resuming session: {e}"}
