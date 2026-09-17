import json
from typing import Any

from fastapi import APIRouter, HTTPException

from alfa.core import database
from alfa.dashboard.common import safe_int

router = APIRouter()

# --- Multi-Agent Round-Table Meeting Endpoints ---


@router.post("/api/meetings/start")
async def start_agent_meeting(payload: dict[str, Any]):
    """Launch direct swarm execution (mode rapat/diskusi sudah dihapus)."""
    topic = payload.get("topic")
    if not topic:
        raise HTTPException(status_code=400, detail="topic is required")

    participants = payload.get("participants")
    rounds = payload.get("rounds", 2)
    folder = payload.get("folder", "")

    from alfa.swarm import engine as swarm_engine

    result = await swarm_engine.conduct_multi_agent_meeting(
        topic=topic,
        participant_names=participants,
        rounds=safe_int(rounds, 2, minimum=1, maximum=3),
        mode="execute",
        target_folder=str(folder or ""),
    )
    return result


@router.post("/api/meetings/cancel")
async def cancel_agent_meeting():
    """Minta pembatalan eksekusi swarm yang sedang berjalan (lintas proses)."""
    from alfa.swarm import engine as swarm_engine

    ok = swarm_engine.request_cancel_swarm()
    if ok:
        return {
            "status": "success",
            "message": "Sinyal pembatalan terkirim — swarm berhenti setelah langkah berjalan selesai.",
        }
    return {"status": "error", "message": "Tidak ada sesi swarm yang sedang berjalan."}


@router.get("/api/meetings")
async def list_meetings(limit: int = 50):
    """List recent multi-agent meetings."""
    meetings = database.list_agent_meetings_sync(limit=limit)
    return {"status": "success", "total": len(meetings), "meetings": meetings}


@router.get("/api/meetings/{meeting_id}")
async def get_meeting_details(meeting_id: int):
    """Fetch complete transcript, consensus, and action plan of a meeting."""
    details = database.get_agent_meeting_sync(meeting_id)
    if not details:
        raise HTTPException(status_code=404, detail="Meeting not found")
    return {"status": "success", "meeting": details}


@router.get("/api/meeting/history")
async def get_meeting_history(limit: int = 50):
    """Get AI agent meeting history from SQLite (real data)."""
    try:
        with database.get_sync_db() as conn:
            rows = conn.execute(
                """SELECT id, title, topic, mode, status, participants,
                          consensus, action_plan, created_at
                   FROM agent_meetings ORDER BY id DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        meetings = []
        for r in rows:
            m = dict(r)
            try:
                m["participants"] = json.loads(m.get("participants") or "[]")
            except Exception:
                pass
            meetings.append(m)
        return {"status": "success", "total": len(meetings), "meetings": meetings}
    except Exception as e:
        return {"status": "error", "message": str(e), "meetings": []}
