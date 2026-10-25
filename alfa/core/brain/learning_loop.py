"""
Hermes-Style Self-Improving Learning Loop for ALFA OS.

Enables the agent to:
1. Record execution trajectories (prompts, tool calls, results, user corrections).
2. Synthesize persistent skills, heuristic rules, and lessons learned from past feedback.
3. Dynamically retrieve learned rules during future turns to prevent repeating mistakes.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime
from typing import Any

from alfa.core.db.connection import get_sync_db
from alfa.tools.registry import register_tool

logger = logging.getLogger("LearningLoop")


def init_learning_tables() -> None:
    """Ensure SQLite tables for trajectories and learned skills are initialized."""
    with get_sync_db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_trajectories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                turn_id TEXT,
                user_prompt TEXT,
                plan_summary TEXT,
                tool_calls_json TEXT,
                result_summary TEXT,
                success INTEGER DEFAULT 1,
                feedback TEXT,
                category TEXT DEFAULT 'general',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS alfa_learned_skills (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                skill_id TEXT UNIQUE,
                topic TEXT,
                trigger_pattern TEXT,
                learned_rule TEXT,
                source_turn_id TEXT,
                confidence REAL DEFAULT 1.0,
                active INTEGER DEFAULT 1,
                hit_count INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_trajectories_turn ON agent_trajectories(turn_id);"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_learned_skills_topic ON alfa_learned_skills(topic);"
        )
        conn.commit()


def record_trajectory(
    user_prompt: str,
    tool_calls: list[dict[str, Any]] | None = None,
    result_summary: str = "",
    success: bool = True,
    feedback: str = "",
    category: str = "general",
    turn_id: str = "",
) -> int:
    """Record an agent execution trajectory for self-improvement and offline analysis."""
    init_learning_tables()
    t_id = turn_id or f"turn_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{hashlib.sha256(user_prompt.encode()).hexdigest()[:8]}"
    tc_json = json.dumps(tool_calls or [])

    with get_sync_db() as conn:
        cur = conn.execute(
            """
            INSERT INTO agent_trajectories
            (turn_id, user_prompt, plan_summary, tool_calls_json, result_summary, success, feedback, category)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                t_id,
                user_prompt,
                "",
                tc_json,
                result_summary[:2000],
                1 if success else 0,
                feedback[:1000],
                category,
            ),
        )
        conn.commit()
        return cur.lastrowid or 0


def synthesize_skill_from_experience(
    topic: str,
    learned_rule: str,
    trigger_pattern: str = "",
    source_turn_id: str = "",
    confidence: float = 1.0,
) -> dict[str, Any]:
    """
    Synthesize an experience or user correction into a persistent rule/skill.
    Similar to Hermes Agent's learning loop, ensures the agent retains knowledge across sessions.
    """
    init_learning_tables()
    topic_clean = topic.strip().upper()
    rule_clean = learned_rule.strip()
    trig_clean = trigger_pattern.strip().lower()

    raw_hash = hashlib.sha256(f"{topic_clean}:{rule_clean}".encode()).hexdigest()[:12]
    skill_id = f"skill_{topic_clean}_{raw_hash}"

    with get_sync_db() as conn:
        conn.execute(
            """
            INSERT INTO alfa_learned_skills
            (skill_id, topic, trigger_pattern, learned_rule, source_turn_id, confidence, active, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 1, CURRENT_TIMESTAMP)
            ON CONFLICT(skill_id) DO UPDATE SET
                trigger_pattern = excluded.trigger_pattern,
                learned_rule = excluded.learned_rule,
                confidence = excluded.confidence,
                active = 1,
                updated_at = CURRENT_TIMESTAMP
            """,
            (skill_id, topic_clean, trig_clean, rule_clean, source_turn_id, confidence),
        )
        conn.commit()

    logger.info("Skill berhasil disintesis: [%s] %s", skill_id, topic_clean)
    return {
        "status": "success",
        "skill_id": skill_id,
        "topic": topic_clean,
        "learned_rule": rule_clean,
        "trigger_pattern": trig_clean,
        "confidence": confidence,
    }


def retrieve_relevant_skills(query: str, limit: int = 4) -> list[dict[str, Any]]:
    """Retrieve active learned skills matching the query text."""
    init_learning_tables()
    q_norm = query.lower().strip()
    words = re.findall(r"\w+", q_norm)
    if not words:
        words = [q_norm]

    matched_skills = []
    with get_sync_db() as conn:
        rows = conn.execute(
            """
            SELECT id, skill_id, topic, trigger_pattern, learned_rule, confidence, hit_count
            FROM alfa_learned_skills
            WHERE active = 1
            ORDER BY hit_count DESC, id DESC
            """
        ).fetchall()

        for r in rows:
            topic_str = (r["topic"] or "").lower()
            trig_str = (r["trigger_pattern"] or "").lower()
            rule_str = (r["learned_rule"] or "").lower()

            score = 0
            for w in words:
                if len(w) < 3:
                    continue
                if w in trig_str:
                    score += 3
                if w in topic_str:
                    score += 2
                if w in rule_str:
                    score += 1

            if score > 0:
                matched_skills.append((score, dict(r)))

    matched_skills.sort(key=lambda x: x[0], reverse=True)
    results = [item[1] for item in matched_skills[:limit]]

    # Increment hit count
    if results:
        with get_sync_db() as conn:
            for item in results:
                conn.execute(
                    "UPDATE alfa_learned_skills SET hit_count = hit_count + 1 WHERE id = ?",
                    (item["id"],),
                )
            conn.commit()

    return results


def format_learned_skills_prompt(query: str) -> str:
    """Format matching skills into a clear prompt block for LLM inference."""
    skills = retrieve_relevant_skills(query, limit=3)
    if not skills:
        return ""

    lines = ["\n[ATURAN PENGALAMAN & SELF-IMPROVEMENT (HERMES LEARNING LOOP)]:"]
    for idx, s in enumerate(skills, 1):
        lines.append(f"{idx}. Topik: {s['topic']}")
        lines.append(f"   Aturan: {s['learned_rule']}")
    lines.append("Patuhi aturan di atas secara konsisten untuk mencegah pengulangan kesalahan masa lalu.\n")
    return "\n".join(lines)


def seed_initial_critical_skills() -> int:
    """Seed foundational knowledge learned from previous operations."""
    init_learning_tables()
    seeds = [
        (
            "CLUSTER_LAHAT_MATERIAL",
            "rekap material lahat tiang 160 mandor mugi aqe",
            "Total pengambilan tiang bersih (Net) Cluster Lahat adalah tepat 160 batang. Terdiri dari Mandor Mugi (61 batang net = 68 bruto - 7 retur) dan Mandor Aqe Setiawan (99 batang net). Item: T72=63 btg, T73=94 btg, T74=1 btg, T94=2 btg.",
        ),
        (
            "EXCEL_DYNAMIC_FORMULA",
            "excel rumus sum sumifs formula dinamis circular",
            "Formula Excel WAJIB 100% dinamis menggunakan openpyxl: gunakan =SUM(G6:G...), =SUMIFS(), =C...-D... DILARANG membuat circular reference (referensi baris ke dirinya sendiri) atau offset baris.",
        ),
        (
            "MASTER_LEDGER_CUMULATIVE",
            "master file excel kumulatif append terusan harian",
            "Gunakan pola Master Ledger Kumulatif: perbarui berkas master cluster in-place (sambung baris baru ke bawah), JANGAN membuat berkas harian terpisah-pisah per tanggal.",
        ),
        (
            "WA_SESSION_INTEGRITY",
            "wa restart stop session whatsapp logout qr",
            "Layanan wa-sheets-bot.service DILARANG KERAS di-restart atau di-stop secara sembarangan agar sesi login QR WhatsApp tidak logout.",
        ),
    ]

    added = 0
    for topic, trig, rule in seeds:
        res = synthesize_skill_from_experience(topic=topic, trigger_pattern=trig, learned_rule=rule)
        if res.get("status") == "success":
            added += 1
    return added


# --- Registered Agent Tools ---

@register_tool(category="agent")
def record_agent_experience(
    topic: str,
    lesson_learned: str,
    trigger_pattern: str = "",
) -> dict[str, Any]:
    """
    SINTESIS PENGALAMAN & ATURAN BARU (HERMES-STYLE SELF-IMPROVING LOOP):
    Merekam koreksi, instruksi operasional penting, atau pelajaran dari tugas sebelumnya
    menjadi aturan pengetahuan persisten. Agen akan otomatis mengingat dan menerapkan aturan ini
    pada perintah serupa di masa depan tanpa perlu diajari ulang.

    Args:
        topic: Topik atau kategori pengetahuan (misal: 'CLUSTER_CURUP_MATERIAL', 'RUMUS_BOQ').
        lesson_learned: Isi aturan atau instruksi yang harus dipatuhi secara permanen.
        trigger_pattern: Kata kunci pemicu yang memanggil aturan ini (misal: 'curup material tiang').

    Returns:
        Dict berisi status, skill_id, dan detail aturan yang tersimpan.
    """
    try:
        if not topic or not lesson_learned:
            return {"status": "error", "message": "Parameter 'topic' dan 'lesson_learned' wajib diisi."}

        res = synthesize_skill_from_experience(
            topic=topic,
            learned_rule=lesson_learned,
            trigger_pattern=trigger_pattern or topic,
        )
        return {
            "status": "success",
            "skill_id": res["skill_id"],
            "topic": res["topic"],
            "message": f"Aturan baru untuk topik '{res['topic']}' berhasil disimpan ke sistem pembelajaran mandiri ALFA OS.",
        }
    except Exception as e:
        logger.exception("Gagal merekam pengalaman agen: %s", e)
        return {"status": "error", "message": f"Record experience error: {str(e)}"}


@register_tool(category="agent")
def query_learned_skills(query: str = "") -> dict[str, Any]:
    """
    CARI ATURAN & SKILL HASIL PEMBELAJARAN MANDIRI (SELF-IMPROVING REPOSITORY):
    Melihat daftar aturan, heuristic rules, dan pelajaran yang telah dipelajari ALFA OS
    dari interaksi dan koreksi sebelumnya.

    Args:
        query: Kata kunci pencarian (kosongkan untuk menampilkan semua aturan aktif).

    Returns:
        Dict berisi daftar aturan, topik, trigger, dan tingkat kepatuhan.
    """
    try:
        init_learning_tables()
        with get_sync_db() as conn:
            if query.strip():
                skills = retrieve_relevant_skills(query, limit=10)
            else:
                rows = conn.execute(
                    """
                    SELECT skill_id, topic, trigger_pattern, learned_rule, confidence, hit_count, updated_at
                    FROM alfa_learned_skills
                    WHERE active = 1
                    ORDER BY hit_count DESC, id DESC
                    """
                ).fetchall()
                skills = [dict(r) for r in rows]

        return {
            "status": "success",
            "count": len(skills),
            "query": query,
            "skills": skills,
            "message": f"Ditemukan {len(skills)} aturan hasil pembelajaran mandiri.",
        }
    except Exception as e:
        logger.exception("Gagal mencari learned skills: %s", e)
        return {"status": "error", "message": f"Query learned skills error: {str(e)}"}
