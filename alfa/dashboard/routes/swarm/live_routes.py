import asyncio
import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException

from alfa.core import database
from alfa.dashboard.common import logger, safe_int

router = APIRouter()

# --- Swarm Arena State Parsing & Real-Time Visualization ---

PERSONA_ID_MAP = {
    "commander": (
        "alpha lead",
        "commander",
        "leader",
        "planner",
        "strategic planner",
        "lead",
    ),
    "researcher": ("researcher prime", "researcher", "analis", "analyst", "riset"),
    "critic": ("system auditor", "critic", "auditor", "sentinel", "sentinel qa", "qa"),
    "executor": ("code crafter", "executor", "crafter", "coder", "developer"),
}


def _resolve_persona_id(name: Optional[str]) -> Optional[str]:
    """Map human or role string to one of the 4 canonical persona IDs."""
    if not name:
        return None
    name_clean = name.strip().lower()
    for pid, aliases in PERSONA_ID_MAP.items():
        if pid == name_clean or any(a in name_clean for a in aliases):
            return pid
    return None


def _extract_speaker_from_entry(e: Dict[str, Any]) -> Optional[str]:
    """Extract persona/speaker name from a live feed entry."""
    if not isinstance(e, dict):
        return None
    if e.get("agent_name"):
        return str(e["agent_name"]).strip()
    if e.get("speaker"):
        return str(e["speaker"]).strip()

    text = str(e.get("text", "")).strip()
    tag = str(e.get("tag", "")).upper()

    # 💬 Alpha Lead: ...
    m = re.search(r"💬\s*([^:]+):", text)
    if m:
        return m.group(1).strip()

    # ⚙️ Code Crafter mulai eksekusi: ...
    m = re.search(r"⚙️\s*([A-Za-z0-9_\s]+?)\s+mulai\s+eksekusi", text)
    if m:
        return m.group(1).strip()

    # 📁 Code Crafter menghasilkan berkas: ...
    m = re.search(r"📁\s*([A-Za-z0-9_\s]+?)\s+menghasilkan\s+berkas", text)
    if m:
        return m.group(1).strip()

    # ✅ PASS — Code Crafter (...) / ❌ FAIL — Code Crafter (...)
    m = re.search(
        r"[✅❌]\s*(?:PASS|FAIL)\s*—\s*([A-Za-z0-9_\s]+?)(?:\s*\(|\s*:|$)", text
    )
    if m:
        return m.group(1).strip()

    if tag == "QA" or "sentinel qa" in text.lower():
        return "System Auditor"

    if tag == "PLAN":
        return "Alpha Lead"

    return None


def detect_active_speaker(entries: List[Dict[str, Any]]) -> Optional[str]:
    """Detect the current speaking or executing agent from recent events."""
    if not entries:
        return None
    for e in reversed(entries[-30:]):
        sp = _extract_speaker_from_entry(e)
        if sp:
            return sp
    return None


def parse_swarm_stage(entries: List[Dict[str, Any]], running: bool = False) -> str:
    """Determine the current stage of the Swarm session: idle, plan, debate, vote, consensus, execute."""
    if not running:
        return "idle"
    if not entries:
        return "plan"

    last_entry = entries[-1]
    last_tag = str(last_entry.get("tag", "")).upper()
    if last_tag in ("DONE", "CANCEL"):
        return "idle"

    for e in reversed(entries[-25:]):
        tag = str(e.get("tag", "")).upper()
        text = str(e.get("text", "")).lower()

        # Tag-based matching has highest precedence
        if tag in ("EXEC", "TOOL", "FILE", "VERIFY", "QA"):
            return "execute"
        if tag == "VOTE":
            return "vote"
        if tag == "CONSENSUS":
            return "consensus"
        if tag == "DIALOG":
            return "debate"
        if tag == "PLAN":
            return "plan"

        # Fallback to semantic text keyword matching
        if any(
            w in text
            for w in (
                "eksekusi",
                "execute",
                "running tool",
                "single-shot write",
                "forced-exec",
            )
        ):
            return "execute"
        if any(w in text for w in ("voting", "vote", "memilih", "polling")):
            return "vote"
        if any(w in text for w in ("konsensus", "kesepakatan", "consensus")):
            return "consensus"
        if any(
            w in text for w in ("diskusi", "debat", "deliberasi", "dialog", "tanggapan")
        ):
            return "debate"
        if any(w in text for w in ("rencana", "planning", "dekomposisi", "roadmap")):
            return "plan"

    return "plan"


def compute_agent_states(
    entries: List[Dict[str, Any]], running: bool = False
) -> Dict[str, str]:
    """Compute status for each persona (commander, researcher, critic, executor): speaking, waiting, idle."""
    base_states = {
        "commander": "idle",
        "researcher": "idle",
        "critic": "idle",
        "executor": "idle",
    }
    if not running:
        return base_states

    states = {k: "waiting" for k in base_states}
    speaker = detect_active_speaker(entries)
    active_pid = _resolve_persona_id(speaker)

    if active_pid and active_pid in states:
        states[active_pid] = "speaking"

    return states


def compute_consensus_percent(stage: str, entries: List[Dict[str, Any]]) -> int:
    """Compute consensus agreement percentage (0 to 100) based on stage and progress."""
    if stage == "idle":
        if entries and str(entries[-1].get("tag", "")).upper() == "DONE":
            return 100
        return 0
    if stage == "plan":
        return 20
    if stage == "debate":
        return 45
    if stage == "vote":
        return 70
    if stage == "consensus":
        return 90
    if stage == "execute":
        if any(str(e.get("tag", "")).upper() == "DONE" for e in entries[-5:]):
            return 100
        return 95
    return 0


def parse_arena_state(
    entries: List[Dict[str, Any]], running: bool = False
) -> Dict[str, Any]:
    """Compile structured arena state for visualization."""
    stage = parse_swarm_stage(entries, running=running)
    active_speaker = detect_active_speaker(entries) if running else None
    agent_states = compute_agent_states(entries, running=running)
    consensus_percent = compute_consensus_percent(stage, entries)
    return {
        "running": running,
        "active_speaker": active_speaker,
        "stage": stage,
        "consensus_percent": consensus_percent,
        "agent_states": agent_states,
    }


@router.get("/api/swarm/live")
async def swarm_live_feed(since: int = 0):
    """Realtime terminal and Arena visualizer feed of what the swarm agents are doing right now."""
    from alfa.swarm import engine as _se

    since = safe_int(since, 0, minimum=0)
    entries = []
    all_recent_entries = []
    is_running = bool(getattr(_se, "MEETING_RUNNING", False))
    try:
        if os.path.exists(_se.LIVE_FEED_FILE):
            with open(_se.LIVE_FEED_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        e = json.loads(line)
                        all_recent_entries.append(e)
                        if e.get("i", 0) > since:
                            entries.append(e)
                    except Exception:
                        continue
            all_recent_entries = all_recent_entries[-50:]
            entries = entries[-150:]
    except Exception as e:
        return {
            "status": "error",
            "message": str(e),
            "entries": [],
            "running": False,
            "active_speaker": None,
            "stage": "idle",
            "consensus_percent": 0,
            "agent_states": {
                "commander": "idle",
                "researcher": "idle",
                "critic": "idle",
                "executor": "idle",
            },
        }

    arena_source = all_recent_entries if all_recent_entries else entries
    arena = parse_arena_state(arena_source, running=is_running)

    return {
        "status": "success",
        "entries": entries,
        "running": is_running,
        "active_speaker": arena["active_speaker"],
        "stage": arena["stage"],
        "consensus_percent": arena["consensus_percent"],
        "agent_states": arena["agent_states"],
    }


@router.get("/api/swarm/folders")
async def swarm_list_folders():
    """Daftar folder proyek yang bisa dipilih sebagai target edit agen."""
    candidates = []

    def _add(root: str, label_prefix: str):
        try:
            if not os.path.isdir(root):
                return
            for d in sorted(os.listdir(root)):
                p = os.path.join(root, d)
                if os.path.isdir(p) and not d.startswith("."):
                    candidates.append({"path": p, "label": f"{label_prefix}/{d}"})
        except Exception:
            pass

    _add("/dev/shm/alfa_sandbox", "sandbox")
    _add(
        os.path.expanduser("~/Dokumen/ALFA_SWARM_OUTPUTS/websites"), "outputs/websites"
    )
    _add(
        os.path.expanduser("~/Dokumen/ALFA_SWARM_OUTPUTS/projects"), "outputs/projects"
    )
    _add(os.path.expanduser("~/alfa_projects"), "alfa_projects")
    return {"folders": candidates}
