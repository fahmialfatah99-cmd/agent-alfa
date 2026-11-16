"""P1 Skill Compiler — ubah trajectory sukses menjadi workflow reusable.

Modul ini melengkapi ``learning_loop`` (yang menyimpan aturan/refleksi) dengan
mengompilasi **urutan tool** dari giliran yang sukses menjadi skill workflow
terstruktur:

- Sumber: tabel ``agent_trajectories`` (turn sukses dengan >= 2 tool call).
- Penyimpanan: tabel aditif ``alfa_compiled_skills`` (terpisah dari
  ``alfa_learned_skills`` agar zero-regression).
- Mode ``ALFA_SKILL_COMPILER``:
  - ``off``    : tidak membaca/menulis.
  - ``shadow`` : mengompilasi dan menyimpan sebagai **inactive** (default).
  - ``on``     : mengompilasi, mengaktifkan, dan menyuntikkan ke prompt.

Semua operasi fail-soft: kegagalan kompilasi tidak boleh mengganggu giliran.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

from alfa.core.config import env_bool, env_int, env_str
from alfa.core.db.connection import get_sync_db

logger = logging.getLogger("SkillCompiler")

_DB_ERR = (
    sqlite3.Error,
    OSError,
    ValueError,
    TypeError,
    KeyError,
    AttributeError,
    RuntimeError,
    UnicodeError,
    json.JSONDecodeError,
)

#: Kata umum yang tidak layak menjadi trigger workflow.
_STOPWORDS = frozenset(
    {
        "yang", "untuk", "dengan", "dari", "ini", "itu", "dan", "atau", "di",
        "ke", "pada", "adalah", "akan", "bisa", "tolong", "mohon", "bantu",
        "buat", "buatkan", "lakukan", "jalankan", "kerjakan", "saya", "aku",
        "kamu", "anda", "file", "data", "semua", "serta", "agar", "supaya",
        "the", "and", "for", "with", "from", "this", "that", "please", "can",
        "you", "to", "of", "in", "on", "a", "an", "is", "are",
    }
)

_MAX_PROMPT_STEPS = 8
_MAX_SOURCE_TURNS = 6
_DEFAULT_MIN_SUPPORT = 2
_DEFAULT_LOOKBACK_DAYS = 90
_DEFAULT_SCAN_LIMIT = 500


def compiler_mode() -> str:
    """Mode aktif: ``off`` | ``shadow`` | ``on``."""
    raw = env_str("ALFA_SKILL_COMPILER", "shadow").strip().lower()
    if raw in {"1", "true", "yes"}:
        return "on"
    if raw in {"0", "false", "no"}:
        return "off"
    if raw in {"off", "shadow", "on"}:
        return raw
    return "shadow"


def _mode_active() -> bool:
    return compiler_mode() in {"shadow", "on"}


def _ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS alfa_compiled_skills (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            skill_id TEXT UNIQUE,
            name TEXT,
            trigger_pattern TEXT,
            category TEXT DEFAULT 'general',
            steps_json TEXT DEFAULT '[]',
            tool_sequence_json TEXT DEFAULT '[]',
            source_turns TEXT DEFAULT '',
            support_count INTEGER DEFAULT 1,
            hit_count INTEGER DEFAULT 0,
            confidence REAL DEFAULT 1.0,
            active INTEGER DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_compiled_skills_active "
        "ON alfa_compiled_skills(active, updated_at DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_compiled_skills_trigger "
        "ON alfa_compiled_skills(trigger_pattern)"
    )


def init_skill_compiler_tables() -> None:
    """Pastikan tabel kompilasi ada (dipanggil juga oleh tes/CLI)."""
    try:
        with get_sync_db() as conn:
            _ensure_table(conn)
            conn.commit()
    except _DB_ERR as exc:
        logger.debug("init skill compiler dilewati: %s", exc)


def _normalize_tool_calls(raw: Any) -> list[str]:
    """Ambil nama tool dari berbagai bentuk payload trajectory."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            return []
    if not isinstance(raw, list):
        return []
    tools: list[str] = []
    for item in raw:
        name = ""
        if isinstance(item, str):
            name = item
        elif isinstance(item, dict):
            name = str(item.get("tool") or item.get("name") or "")
        name = name.strip()
        if not name:
            continue
        if tools and tools[-1] == name:
            continue
        tools.append(name)
    return tools


def _trigger_from_prompts(prompts: list[str], category: str = "") -> str:
    """Buat trigger ringkas dari kata bermakna pada prompt sumber."""
    tokens: dict[str, int] = {}
    for prompt in prompts:
        for word in re.findall(r"[a-zA-Z_][a-zA-Z0-9_]{2,}", str(prompt or "").lower()):
            if word in _STOPWORDS:
                continue
            tokens[word] = tokens.get(word, 0) + 1
    ranked = sorted(tokens.items(), key=lambda item: (-item[1], item[0]))
    trigger = " ".join(word for word, _ in ranked[:8])
    if not trigger and category and category != "general":
        trigger = category.lower()
    return trigger or "workflow"


def _skill_name(tools: list[str] | tuple[str, ...]) -> str:
    pretty = " → ".join(tools[:_MAX_PROMPT_STEPS])
    return f"Workflow: {pretty}"


def list_compiled_skills_sync(
    *, active_only: bool = False, limit: int = 20
) -> list[dict[str, Any]]:
    """Daftar skill hasil kompilasi (fail-soft)."""
    limit = max(1, min(int(limit), 200))
    try:
        with get_sync_db() as conn:
            _ensure_table(conn)
            conn.row_factory = sqlite3.Row
            sql = "SELECT * FROM alfa_compiled_skills"
            if active_only:
                sql += " WHERE active = 1"
            sql += " ORDER BY support_count DESC, updated_at DESC LIMIT ?"
            rows = conn.execute(sql, (limit,)).fetchall()
        return [dict(row) for row in rows]
    except _DB_ERR as exc:
        logger.debug("List compiled skills gagal: %s", exc)
        return []


def compile_skills_sync(
    *,
    min_support: int | None = None,
    lookback_days: int | None = None,
    scan_limit: int | None = None,
) -> dict[str, Any]:
    """Kompilasi trajectory sukses menjadi skill workflow.

    Idempoten: grup urutan tool yang sama akan memperbarui baris yang ada
    (``support_count``/``confidence``), bukan menduplikasi.
    """
    mode = compiler_mode()
    summary: dict[str, Any] = {
        "status": "ok",
        "mode": mode,
        "scanned": 0,
        "eligible": 0,
        "groups": 0,
        "compiled": 0,
        "activated": 0,
        "min_support": 0,
    }
    if mode == "off":
        summary["status"] = "disabled"
        return summary

    min_support = (
        env_int("ALFA_SKILL_COMPILER_MIN_SUPPORT", _DEFAULT_MIN_SUPPORT, minimum=1)
        if min_support is None
        else max(1, int(min_support))
    )
    lookback_days = (
        env_int(
            "ALFA_SKILL_COMPILER_LOOKBACK_DAYS",
            _DEFAULT_LOOKBACK_DAYS,
            minimum=1,
        )
        if lookback_days is None
        else max(1, int(lookback_days))
    )
    scan_limit = (
        env_int("ALFA_SKILL_COMPILER_SCAN_LIMIT", _DEFAULT_SCAN_LIMIT, minimum=1)
        if scan_limit is None
        else max(1, int(scan_limit))
    )
    summary["min_support"] = min_support
    summary["lookback_days"] = lookback_days

    cutoff = (
        datetime.now(timezone.utc) - timedelta(days=lookback_days)
    ).strftime("%Y-%m-%d %H:%M:%S")

    try:
        from alfa.core.brain.learning_loop import init_learning_tables

        init_learning_tables()
    except (ImportError, sqlite3.Error, OSError, ValueError, TypeError) as exc:
        logger.debug("init learning tables untuk compiler dilewati: %s", exc)

    try:
        with get_sync_db() as conn:
            _ensure_table(conn)
            conn.row_factory = sqlite3.Row
            try:
                rows = conn.execute(
                    """
                    SELECT turn_id, user_prompt, tool_calls_json, category
                    FROM agent_trajectories
                    WHERE success = 1 AND created_at >= ?
                    ORDER BY id DESC LIMIT ?
                    """,
                    (cutoff, scan_limit),
                ).fetchall()
            except sqlite3.Error:
                # Tabel trajectory belum ada (bot belum pernah belajar).
                rows = []

            summary["scanned"] = len(rows)
            groups: dict[tuple[str, ...], dict[str, Any]] = {}
            for row in rows:
                tools = _normalize_tool_calls(row["tool_calls_json"])
                if len(tools) < 2:
                    continue
                if len(tools) > _MAX_PROMPT_STEPS:
                    continue
                key = tuple(tools)
                group = groups.setdefault(
                    key,
                    {
                        "prompts": [],
                        "turn_ids": [],
                        "category": str(row["category"] or "general"),
                        "count": 0,
                    },
                )
                group["count"] += 1
                prompt = str(row["user_prompt"] or "").strip()
                if prompt and len(group["prompts"]) < 20:
                    group["prompts"].append(prompt)
                if row["turn_id"] and len(group["turn_ids"]) < _MAX_SOURCE_TURNS:
                    group["turn_ids"].append(str(row["turn_id"]))
            summary["eligible"] = len(groups)

            active_value = 1 if mode == "on" else 0
            for sequence, data in groups.items():
                trajectory_count = max(1, int(data.get("count") or 1))
                if trajectory_count < min_support:
                    continue
                category = data["category"] or "general"
                trigger = _trigger_from_prompts(data["prompts"], category)
                skill_id = "wf_" + hashlib.sha256(
                    json.dumps(sequence, separators=(",", ":")).encode()
                ).hexdigest()[:12]
                steps = [
                    {"step": idx + 1, "tool": tool}
                    for idx, tool in enumerate(sequence)
                ]
                confidence = min(
                    1.0, 0.5 + (trajectory_count / max(2, min_support + 2))
                )
                conn.execute(
                    """
                    INSERT INTO alfa_compiled_skills
                        (skill_id, name, trigger_pattern, category, steps_json,
                         tool_sequence_json, source_turns, support_count,
                         confidence, active, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(skill_id) DO UPDATE SET
                        name = excluded.name,
                        trigger_pattern = excluded.trigger_pattern,
                        category = excluded.category,
                        steps_json = excluded.steps_json,
                        tool_sequence_json = excluded.tool_sequence_json,
                        source_turns = excluded.source_turns,
                        support_count = excluded.support_count,
                        confidence = excluded.confidence,
                        active = CASE
                            WHEN ? = 1 THEN 1
                            ELSE alfa_compiled_skills.active
                        END,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (
                        skill_id,
                        _skill_name(sequence),
                        trigger,
                        category,
                        json.dumps(steps, ensure_ascii=False),
                        json.dumps(sequence, ensure_ascii=False),
                        ",".join(data["turn_ids"]),
                        trajectory_count,
                        confidence,
                        active_value,
                        active_value,
                    ),
                )
                summary["compiled"] += 1
                if active_value:
                    summary["activated"] += 1
            summary["groups"] = summary["compiled"]
            conn.commit()
    except _DB_ERR as exc:
        logger.debug("Compile skills gagal: %s", exc)
        summary["status"] = "error"
        summary["error"] = str(exc)
    return summary


def _query_tokens(query: str) -> list[str]:
    return [
        word
        for word in re.findall(r"[a-zA-Z_][a-zA-Z0-9_]{2,}", str(query or "").lower())
        if word not in _STOPWORDS
    ]


def retrieve_compiled_skills(query: str, limit: int = 2) -> list[dict[str, Any]]:
    """Ambil workflow aktif yang relevan dengan query (mode ``on`` saja)."""
    if compiler_mode() != "on" or not str(query or "").strip():
        return []
    words = _query_tokens(query)
    if not words:
        return []
    limit = max(1, min(int(limit), 5))
    try:
        with get_sync_db() as conn:
            _ensure_table(conn)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM alfa_compiled_skills WHERE active = 1 "
                "ORDER BY support_count DESC, hit_count DESC LIMIT 100"
            ).fetchall()
            matches: list[tuple[int, sqlite3.Row]] = []
            for row in rows:
                haystack = (
                    f"{row['trigger_pattern'] or ''} {row['name'] or ''} "
                    f"{row['category'] or ''}"
                ).lower()
                score = sum(2 if word in haystack else 0 for word in words)
                if score > 0:
                    matches.append((score, row))
            matches.sort(key=lambda item: (-item[0], -int(item[1]["support_count"] or 0)))
            selected = [dict(row) for _, row in matches[:limit]]
            if selected:
                for item in selected:
                    conn.execute(
                        "UPDATE alfa_compiled_skills SET hit_count = hit_count + 1 "
                        "WHERE id = ?",
                        (item["id"],),
                    )
                conn.commit()
            return selected
    except _DB_ERR as exc:
        logger.debug("Retrieve compiled skills gagal: %s", exc)
        return []


def format_compiled_skills_prompt(query: str) -> str:
    """Format workflow aktif menjadi blok prompt singkat untuk model."""
    if not env_bool("ALFA_SKILL_COMPILER_PROMPT", True):
        return ""
    skills = retrieve_compiled_skills(query, limit=2)
    if not skills:
        return ""
    lines = ["\n[WORKFLOW TERKOMPILASI DARI PENGALAMAN SUKSES]:"]
    for idx, skill in enumerate(skills, 1):
        try:
            steps = json.loads(str(skill.get("steps_json") or "[]"))
        except (TypeError, ValueError, json.JSONDecodeError):
            steps = []
        step_text = " → ".join(
            str(step.get("tool") or "")
            for step in steps
            if isinstance(step, dict) and step.get("tool")
        )
        lines.append(
            f"{idx}. {skill.get('name') or 'Workflow'} "
            f"(support {skill.get('support_count', 1)}×)"
        )
        if step_text:
            lines.append(f"   Urutan: {step_text}")
    lines.append(
        "Gunakan urutan ini sebagai panduan bila relevan; tetap verifikasi "
        "argumen dan kondisi terbaru sebelum eksekusi.\n"
    )
    return "\n".join(lines)


def format_compiled_skills_status() -> str:
    """Ringkasan singkat untuk perintah /skills."""
    mode = compiler_mode()
    skills = list_compiled_skills_sync(active_only=False, limit=100)
    active = sum(1 for skill in skills if int(skill.get("active") or 0) == 1)
    return (
        f"• Skill Compiler: `{mode}` — {len(skills)} workflow "
        f"({active} aktif)"
    )


__all__ = [
    "compile_skills_sync",
    "compiler_mode",
    "format_compiled_skills_prompt",
    "format_compiled_skills_status",
    "init_skill_compiler_tables",
    "list_compiled_skills_sync",
    "retrieve_compiled_skills",
]
