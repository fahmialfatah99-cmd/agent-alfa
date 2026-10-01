"""Swarm session resume flow (checkpoint -> re-execution)."""

from typing import Any

from alfa.swarm.live_logger import _CHECKPOINT_AVAILABLE, _SwarmCheckpoint, log_live


async def resume_swarm_session(session_id: str) -> dict[str, Any]:
    """
    Melanjutkan sesi swarm yang sebelumnya dibatalkan atau tertunda berdasarkan checkpoint.
    """
    if not _CHECKPOINT_AVAILABLE:
        return {"status": "error", "message": "Checkpoint system tidak tersedia."}

    ckpt = _SwarmCheckpoint.load(session_id)
    if not ckpt:
        return {
            "status": "error",
            "message": f"Checkpoint untuk session '{session_id}' tidak ditemukan.",
        }

    topic = ckpt.get("topic", "")
    mode = ckpt.get("mode", "execute")
    participant_names = [
        a["name"]
        for a in ckpt.get("participants", [])
        if isinstance(a, dict) and "name" in a
    ]

    log_live("RESUME", f"🔄 Melanjutkan sesi {session_id} (Topik: {topic[:60]})...")

    from alfa.swarm.engine import conduct_multi_agent_meeting

    return await conduct_multi_agent_meeting(
        topic=topic,
        participant_names=participant_names or None,
        mode=mode,
        session_id=session_id,
    )
