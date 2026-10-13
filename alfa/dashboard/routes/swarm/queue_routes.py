"""Antrean misi swarm durable: daftar, pantau, batalkan via dashboard."""

from typing import Any

from fastapi import APIRouter, HTTPException

from alfa.dashboard.common import safe_int
from alfa.swarm import queue as swarm_queue

router = APIRouter()


@router.post("/api/swarm/queue/enqueue")
async def enqueue_mission(payload: dict[str, Any]):
    """Daftarkan misi swarm durable (dieksekusi worker terpisah)."""
    topic = (payload.get("topic") or "").strip()
    if not topic:
        raise HTTPException(status_code=400, detail="topic is required")
    try:
        mission = swarm_queue.enqueue(
            topic=topic,
            mode=str(payload.get("mode") or "execute"),
            participants=payload.get("participants"),
            target_folder=str(payload.get("folder") or ""),
            delay_s=float(payload.get("delay_s") or 0),
            max_attempts=safe_int(payload.get("max_attempts", 0), 0),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"status": "success", "mission": mission}


@router.get("/api/swarm/queue")
async def list_queue(status: str = "", limit: int = 50):
    """Daftar misi antrean, opsional filter status."""
    missions = swarm_queue.list_missions(
        status=status or None, limit=safe_int(limit, 50, minimum=1, maximum=200)
    )
    return {"status": "success", "total": len(missions), "missions": missions}


@router.get("/api/swarm/queue/{mission_id}")
async def get_queued_mission(mission_id: int):
    """Detail satu misi antrean."""
    mission = swarm_queue.get_mission(mission_id)
    if not mission:
        raise HTTPException(status_code=404, detail="mission not found")
    return {"status": "success", "mission": mission}


@router.post("/api/swarm/queue/{mission_id}/cancel")
async def cancel_queued_mission(mission_id: int):
    """Batalkan misi queued/running."""
    if swarm_queue.cancel_mission(mission_id):
        return {"status": "success", "message": f"Misi #{mission_id} dibatalkan."}
    raise HTTPException(
        status_code=404, detail="mission not found atau sudah final"
    )
