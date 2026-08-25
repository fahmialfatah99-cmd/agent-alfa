"""
Swarm Checkpoint & Resume System for ALFA Agent.

Menyimpan state eksekusi swarm ke JSON agar bisa di-resume setelah cancel/crash.
File checkpoint disimpan di: storage/checkpoints/
"""
import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

CHECKPOINT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "storage", "checkpoints")
os.makedirs(CHECKPOINT_DIR, exist_ok=True)


class SwarmCheckpoint:
    """
    Manages save/load of swarm session state.
    """
    
    @staticmethod
    def _path(session_id: str) -> str:
        return os.path.join(CHECKPOINT_DIR, f"{session_id}.json")
    
    @staticmethod
    def save(
        session_id: str,
        topic: str,
        mode: str,
        participants: List[Dict[str, Any]],
        steps: List[Dict[str, Any]],
        steps_done: int,
        deliverables: Optional[List[str]] = None,
        error_log: Optional[List[Dict[str, Any]]] = None,
        status: str = "running",
        resume_count: int = 0,
    ) -> str:
        """Save or update a checkpoint. Returns the checkpoint file path."""
        path = SwarmCheckpoint._path(session_id)
        existing = {}
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    existing = json.load(f)
            except Exception:
                pass
        
        state = {
            "session_id": session_id,
            "created_at": existing.get("created_at") or datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "topic": topic,
            "mode": mode,
            "status": status,
            "participants": participants,
            "steps_total": len(steps),
            "steps_done": steps_done,
            "steps": steps,
            "deliverables": deliverables or [],
            "error_log": error_log or [],
            "resume_count": resume_count,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2, default=str)
        return path
    
    @staticmethod
    def load(session_id: str) -> Optional[Dict[str, Any]]:
        """Load a checkpoint. Returns None if not found."""
        path = SwarmCheckpoint._path(session_id)
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None
    
    @staticmethod
    def list_resumable() -> List[Dict[str, Any]]:
        """
        List all checkpoints that can be resumed (status = paused/cancelled/running).
        Returns list sorted by updated_at desc.
        """
        result = []
        try:
            for fname in os.listdir(CHECKPOINT_DIR):
                if not fname.endswith(".json"):
                    continue
                fpath = os.path.join(CHECKPOINT_DIR, fname)
                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        state = json.load(f)
                    if state.get("status") in ("paused", "cancelled", "running"):
                        result.append({
                            "session_id": state["session_id"],
                            "topic": state.get("topic", "")[:80],
                            "mode": state.get("mode", ""),
                            "status": state["status"],
                            "steps_done": state.get("steps_done", 0),
                            "steps_total": state.get("steps_total", 0),
                            "updated_at": state.get("updated_at", ""),
                            "resume_count": state.get("resume_count", 0),
                        })
                except Exception:
                    pass
        except Exception:
            pass
        return sorted(result, key=lambda x: x.get("updated_at", ""), reverse=True)
    
    @staticmethod
    def mark_completed(session_id: str, deliverables: Optional[List[str]] = None):
        """Mark a checkpoint as completed."""
        state = SwarmCheckpoint.load(session_id)
        if not state:
            return
        state["status"] = "completed"
        state["updated_at"] = datetime.now(timezone.utc).isoformat()
        if deliverables:
            state["deliverables"] = deliverables
        with open(SwarmCheckpoint._path(session_id), "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2, default=str)
    
    @staticmethod
    def mark_cancelled(session_id: str):
        """Mark a checkpoint as cancelled (can be resumed)."""
        state = SwarmCheckpoint.load(session_id)
        if not state:
            return
        state["status"] = "cancelled"
        state["updated_at"] = datetime.now(timezone.utc).isoformat()
        with open(SwarmCheckpoint._path(session_id), "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2, default=str)
    
    @staticmethod
    def clear(session_id: str) -> bool:
        """Delete a checkpoint file. Returns True if deleted."""
        path = SwarmCheckpoint._path(session_id)
        if os.path.exists(path):
            os.remove(path)
            return True
        return False
    
    @staticmethod
    def add_error(session_id: str, step_name: str, agent_name: str, error: str):
        """Append an error entry to checkpoint's error_log."""
        state = SwarmCheckpoint.load(session_id)
        if not state:
            return
        state.setdefault("error_log", []).append({
            "step": step_name,
            "agent": agent_name,
            "error": error[:300],
            "ts": datetime.now(timezone.utc).isoformat(),
        })
        state["updated_at"] = datetime.now(timezone.utc).isoformat()
        with open(SwarmCheckpoint._path(session_id), "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2, default=str)
