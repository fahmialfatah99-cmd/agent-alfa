"""
Workforce Agents & Round-Table Meetings Database Functions.
"""

import json
import logging
from typing import Any

from alfa.core.db.connection import get_sync_db

logger = logging.getLogger("DB.Agents")


def list_custom_agents_sync() -> list[dict[str, Any]]:
    """List all registered custom agents."""
    with get_sync_db() as conn:
        cursor = conn.execute("""
            SELECT a.id, a.name, a.role, a.persona, a.system_instruction, a.provider, a.model, 
                   a.api_key_id, a.avatar_emoji, a.color_theme, a.is_enabled, a.created_at,
                   COALESCE(a.enable_tools, 0) as enable_tools,
                   k.name as key_name
            FROM custom_agents a
            LEFT JOIN api_keys k ON a.api_key_id = k.id
            ORDER BY a.id ASC
            """)
        rows = cursor.fetchall()
        return [dict(r) for r in rows]


def add_custom_agent_sync(
    name: str,
    role: str,
    persona: str,
    system_instruction: str,
    provider: str = "gemini",
    model: str = "gemini-3.6-flash",
    api_key_id: int | None = None,
    avatar_emoji: str = "🤖",
    color_theme: str = "cyan",
) -> dict[str, Any]:
    """Create a new specialized AI agent in the workforce."""
    with get_sync_db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO custom_agents (name, role, persona, system_instruction, provider, model, api_key_id, avatar_emoji, color_theme, is_enabled)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (
                name,
                role,
                persona,
                system_instruction,
                provider,
                model,
                api_key_id,
                avatar_emoji,
                color_theme,
            ),
        )
        conn.commit()
        agent_id = cursor.lastrowid
    return {"status": "success", "id": agent_id, "name": name, "role": role}


def update_custom_agent_sync(agent_id: int, updates: dict[str, Any]) -> dict[str, Any]:
    """Update custom agent configuration."""
    ALLOWED_COLUMNS = frozenset(
        [
            "name",
            "role",
            "persona",
            "system_instruction",
            "provider",
            "model",
            "api_key_id",
            "avatar_emoji",
            "color_theme",
            "is_enabled",
            "enable_tools",
        ]
    )

    fields = []
    values = []
    for k, v in updates.items():
        if k not in ALLOWED_COLUMNS:
            logger.warning(
                f"update_custom_agent: kolom '{k}' ditolak (tidak ada di whitelist)"
            )
            continue
        if not all(c.isalnum() or c == "_" for c in k):
            logger.warning(
                f"update_custom_agent: kolom '{k}' ditolak (karakter tidak valid)"
            )
            continue
        fields.append(f'"{k}" = ?')
        values.append(v)
    if not fields:
        return {"status": "error", "message": "No valid fields to update"}
    values.append(agent_id)
    with get_sync_db() as conn:
        cursor = conn.execute(
            f"UPDATE custom_agents SET {', '.join(fields)} WHERE id = ?", tuple(values)
        )
        conn.commit()
        if cursor.rowcount == 0:
            return {"status": "error", "message": f"Agent #{agent_id} not found"}
    return {"status": "success", "message": f"Agent #{agent_id} updated"}


def delete_custom_agent_sync(agent_id: int) -> dict[str, Any]:
    """Delete a custom agent."""
    with get_sync_db() as conn:
        cursor = conn.execute("DELETE FROM custom_agents WHERE id = ?", (agent_id,))
        conn.commit()
        if cursor.rowcount == 0:
            return {"status": "error", "message": f"Agent #{agent_id} not found"}
    return {"status": "success", "message": f"Agent #{agent_id} deleted"}


def get_custom_agent_sync(name_or_id: Any) -> dict[str, Any] | None:
    """Retrieve custom agent by name or id."""
    with get_sync_db() as conn:
        if isinstance(name_or_id, int) or (
            isinstance(name_or_id, str) and name_or_id.isdigit()
        ):
            cursor = conn.execute(
                "SELECT * FROM custom_agents WHERE id = ?", (int(name_or_id),)
            )
        else:
            cursor = conn.execute(
                "SELECT * FROM custom_agents WHERE LOWER(name) = LOWER(?)",
                (str(name_or_id).strip(),),
            )
        row = cursor.fetchone()
        if row:
            return dict(row)
    return None


def create_agent_meeting_sync(
    title: str,
    topic: str,
    participants: list[str],
    dialogue_transcript: list[dict[str, Any]],
    consensus: str,
    action_plan: str,
    mode: str = "plan",
    execution_results: Any = "",
    status: str = "completed",
) -> dict[str, Any]:
    """Save a completed or active multi-agent meeting with mode and live execution results."""
    exec_str = (
        execution_results
        if isinstance(execution_results, str)
        else json.dumps(execution_results, ensure_ascii=False)
    )
    with get_sync_db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO agent_meetings (title, topic, participants, dialogue_transcript, consensus, action_plan, mode, execution_results, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                title,
                topic,
                json.dumps(participants, ensure_ascii=False),
                json.dumps(dialogue_transcript, ensure_ascii=False),
                consensus,
                action_plan,
                mode,
                exec_str,
                status,
            ),
        )
        conn.commit()
        meeting_id = cursor.lastrowid
    return {"status": "success", "id": meeting_id, "title": title}


def list_agent_meetings_sync(limit: int = 50) -> list[dict[str, Any]]:
    """List recent meetings with mode information."""
    with get_sync_db() as conn:
        cursor = conn.execute(
            "SELECT id, title, topic, participants, consensus, action_plan, mode, execution_results, status, created_at FROM agent_meetings ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        rows = cursor.fetchall()
        results = []
        for r in rows:
            parts = []
            try:
                parts = json.loads(r["participants"])
            except Exception:
                pass

            exec_res = []
            if r["execution_results"]:
                try:
                    exec_res = json.loads(r["execution_results"])
                except Exception:
                    exec_res = r["execution_results"]

            results.append(
                {
                    "id": r["id"],
                    "title": r["title"],
                    "topic": r["topic"],
                    "participants": parts,
                    "consensus": r["consensus"] or "",
                    "action_plan": r["action_plan"] or "",
                    "mode": r["mode"] or "plan",
                    "execution_results": exec_res,
                    "status": r["status"],
                    "created_at": str(r["created_at"]),
                }
            )
        return results


def get_agent_meeting_sync(meeting_id: int) -> dict[str, Any] | None:
    """Get full details of a specific meeting including full dialogue transcript and execution results."""
    with get_sync_db() as conn:
        cursor = conn.execute(
            "SELECT * FROM agent_meetings WHERE id = ?", (meeting_id,)
        )
        row = cursor.fetchone()
        if row:
            d = dict(row)
            try:
                d["participants"] = json.loads(d["participants"])
            except Exception:
                pass
            try:
                d["dialogue_transcript"] = json.loads(d["dialogue_transcript"])
            except Exception:
                pass
            if d.get("execution_results"):
                try:
                    d["execution_results"] = json.loads(d["execution_results"])
                except Exception:
                    pass
            return d
    return None
