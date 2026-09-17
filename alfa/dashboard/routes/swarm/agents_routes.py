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

# --- Autonomous AI Workforce & Custom Agent Endpoints ---


@router.get("/api/agents")
async def get_custom_agents():
    """List all custom agents in the workforce."""
    agents = database.list_custom_agents_sync()
    return {"status": "success", "total": len(agents), "agents": agents}


@router.post("/api/agents")
async def create_custom_agent(payload: Dict[str, Any]):
    """Create a new specialized AI agent."""
    name = payload.get("name")
    role = payload.get("role")
    persona = payload.get("persona", "")
    system_instruction = payload.get("system_instruction", "")
    provider = payload.get("provider", "gemini")
    model = payload.get("model", "gemini-3.6-flash")
    api_key_id = payload.get("api_key_id")
    avatar_emoji = payload.get("avatar_emoji", "🤖")
    color_theme = payload.get("color_theme", "cyan")

    if not name or not role:
        raise HTTPException(status_code=400, detail="name and role are required")

    res = database.add_custom_agent_sync(
        name=name,
        role=role,
        persona=persona or f"Spesialis {role}",
        system_instruction=system_instruction or f"Kamu adalah {name}, {role}.",
        provider=provider,
        model=model,
        api_key_id=api_key_id,
        avatar_emoji=avatar_emoji,
        color_theme=color_theme,
    )
    return res


@router.put("/api/agents/{agent_id}")
async def update_custom_agent_endpoint(agent_id: int, payload: Dict[str, Any]):
    """Update custom agent configuration."""
    res = database.update_custom_agent_sync(agent_id, payload)
    return res


@router.delete("/api/agents/{agent_id}")
async def delete_custom_agent_endpoint(agent_id: int):
    """Delete a custom agent."""
    res = database.delete_custom_agent_sync(agent_id)
    return res


@router.post("/api/agents/{agent_id}/chat")
async def chat_with_custom_agent(agent_id: int, payload: Dict[str, Any]):
    """Send a test message directly to a specific custom agent."""
    prompt = payload.get("message")
    if not prompt:
        raise HTTPException(status_code=400, detail="message is required")

    with database.get_sync_db() as conn:
        row = conn.execute(
            "SELECT * FROM custom_agents WHERE id = ?", (agent_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Agent tidak ditemukan")
        agent_data = dict(row)

    from alfa.swarm import engine as swarm_engine

    start_t = time.time()
    resp = await swarm_engine.generate_agent_response(
        agent=agent_data,
        prompt=prompt,
        system_instruction=agent_data.get("system_instruction")
        or f"Kamu adalah {agent_data['name']}, {agent_data['role']}.",
    )
    duration_ms = round((time.time() - start_t) * 1000, 1)

    return {
        "status": "success",
        "agent_name": agent_data["name"],
        "model": agent_data["model"],
        "provider": agent_data["provider"],
        "duration_ms": duration_ms,
        "reply": resp,
    }


# --- Live Agent Activity & Real-Time Autonomous Execution ---


@router.get("/api/agent-activity")
async def get_agent_activity():
    """Fetch live real-time agent activities, subagent background tasks, and agent telemetry."""
    activities = database.list_agent_activities_sync(limit=30)
    subagent_tasks = database.list_subagent_tasks_sync(limit=10)
    agents = database.list_custom_agents_sync()

    agent_states = []
    for a in agents:
        last_act = next(
            (
                act
                for act in activities
                if act.get("agent_id") == a["id"] or act.get("agent_name") == a["name"]
            ),
            None,
        )
        agent_states.append(
            {
                "id": a["id"],
                "name": a["name"],
                "role": a["role"],
                "avatar_emoji": a.get("avatar_emoji", "🤖"),
                "color_theme": a.get("color_theme", "cyan"),
                "provider": a["provider"],
                "model": a["model"],
                "status": "active" if a.get("is_enabled", 1) else "disabled",
                "current_state": (
                    "🟢 STANDBY"
                    if not last_act
                    else f"⚙️ {last_act.get('action_type', 'ACTIVE').upper()}"
                ),
                "last_action": (
                    last_act.get("description", "Menunggu instruksi tugas")
                    if last_act
                    else "Siap eksekusi tugas otonom"
                ),
                "last_tool": last_act.get("tool_name") if last_act else None,
                "last_updated": (
                    last_act.get("created_at") if last_act else a.get("created_at")
                ),
            }
        )

    return {
        "status": "success",
        "total_activities": len(activities),
        "activities": activities,
        "subagent_tasks": subagent_tasks,
        "agent_states": agent_states,
    }


@router.post("/api/agents/{agent_id}/execute")
async def execute_agent_task(agent_id: int, payload: Dict[str, Any]):
    """Directly dispatch an autonomous task to a specialized agent with real tool execution."""
    instruction = payload.get("instruction")
    if not instruction:
        raise HTTPException(status_code=400, detail="instruction is required")

    with database.get_sync_db() as conn:
        row = conn.execute(
            "SELECT * FROM custom_agents WHERE id = ?", (agent_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Agent tidak ditemukan")
        agent_data = dict(row)

    from alfa import tools
    from alfa.swarm import engine as swarm_engine

    start_t = time.time()

    tool_router_prompt = (
        f"USER REQUEST:\n{instruction}\n\n"
        f"Kamu adalah {agent_data['name']} ({agent_data['role']}). Kamu memiliki akses langsung ke Linux Host.\n"
        f"PILIH SALAH SATU TOOL YANG TEPAT UNTUK MENGEKSEKUSI TUGAS DI ATAS:\n"
        f"- BASH: format `TOOL: BASH | <perintah bash>` (misal `TOOL: BASH | git status`, `TOOL: BASH | free -m`, `TOOL: BASH | ps aux --sort=-%mem | head -n 10`)\n"
        f"- SYSTEM_STATS: format `TOOL: SYSTEM_STATS | none`\n"
        f"- READ_FILE: format `TOOL: READ_FILE | <path>`\n"
        f"- WRITE_FILE: format `TOOL: WRITE_FILE | <path> | <isi konten>`\n"
        f"- WEB_SEARCH: format `TOOL: WEB_SEARCH | <query>`\n"
        f"- DIRECT_ANSWER: Jika tidak butuh tool, jawab langsung.\n\n"
        f"Format jawaban baris pertama harus TOOL: <NAMA_TOOL> | <PARAM> jika memanggil tool!"
    )

    decision = await swarm_engine.generate_agent_response(
        agent=agent_data,
        prompt=tool_router_prompt,
        system_instruction="Kamu adalah engine otonom yang mengeksekusi tool sistem.",
    )

    tool_called = None
    tool_input = None
    tool_output_str = ""
    action_type = "tool_call"

    if "TOOL: BASH |" in decision:
        cmd = decision.split("TOOL: BASH |", 1)[1].strip().split("\n")[0]
        tool_called = "execute_bash_command"
        tool_input = cmd
        action_type = "bash_exec"
        res = tools.execute_bash_command(cmd)
        tool_output_str = (
            res.get("stdout")
            or res.get("output")
            or res.get("message")
            or res.get("stderr")
            or "Done (exit code 0)"
        )
    elif "TOOL: SYSTEM_STATS" in decision:
        tool_called = "get_system_stats"
        tool_input = "metrics"
        action_type = "audit"
        res = tools.get_system_stats()
        tool_output_str = json.dumps(res, indent=2, default=str)
    elif "TOOL: READ_FILE |" in decision:
        fpath = decision.split("TOOL: READ_FILE |", 1)[1].strip().split("\n")[0]
        tool_called = "read_local_file"
        tool_input = fpath
        action_type = "file_op"
        res = tools.read_local_file(fpath)
        tool_output_str = res.get("content") or res.get("message", "")
    elif "TOOL: WEB_SEARCH |" in decision:
        q = decision.split("TOOL: WEB_SEARCH |", 1)[1].strip().split("\n")[0]
        tool_called = "web_search"
        tool_input = q
        action_type = "web_search"
        res = tools.web_search(q)
        tool_output_str = json.dumps(res, indent=2, default=str)
    else:
        if any(
            kw in instruction.lower()
            for kw in [
                "git",
                "ps",
                "top",
                "ram",
                "cpu",
                "disk",
                "ls",
                "systemctl",
                "curl",
                "free",
            ]
        ):
            tool_called = "execute_bash_command"
            tool_input = instruction
            action_type = "bash_exec"
            res = tools.execute_bash_command(instruction)
            tool_output_str = (
                res.get("stdout")
                or res.get("output")
                or res.get("message")
                or res.get("stderr")
                or "Done (exit code 0)"
            )

    synth_prompt = (
        f"TUGAS AWAL: {instruction}\n\n"
        f"HASIL EKSEKUSI TOOL ({tool_called or 'Direct Reasoning'}):\n"
        f"Input: {tool_input}\n"
        f"Output:\n{tool_output_str[:3000]}\n\n"
        f"Berikan laporan ringkas, santai, gaul, dan to-the-point mengenai hasil eksekusi di atas!"
    )

    final_report = await swarm_engine.generate_agent_response(
        agent=agent_data,
        prompt=synth_prompt,
        system_instruction=agent_data.get("system_instruction")
        or "Kamu adalah engineer spesialis AI.",
    )

    duration_ms = round((time.time() - start_t) * 1000, 1)

    database.log_agent_activity_sync(
        agent_id=agent_data["id"],
        agent_name=agent_data["name"],
        action_type=action_type,
        description=f"Eksekusi tugas: {instruction[:80]}",
        tool_name=tool_called,
        tool_input=tool_input,
        tool_output=tool_output_str[:1500] if tool_output_str else None,
        status="success",
        duration_ms=duration_ms,
    )

    return {
        "status": "success",
        "agent_name": agent_data["name"],
        "role": agent_data["role"],
        "model": agent_data["model"],
        "provider": agent_data["provider"],
        "action_type": action_type,
        "tool_called": tool_called,
        "tool_input": tool_input,
        "tool_output": tool_output_str,
        "agent_report": final_report,
        "duration_ms": duration_ms,
    }
