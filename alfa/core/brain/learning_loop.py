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

logger = logging.getLogger("LearningLoop")


def register_tool(category: str = "agent"):
    """Deferred tool registration to prevent circular import between tools and brain."""
    def decorator(fn):
        try:
            from alfa.tools.registry import register_tool as _rt
            return _rt(category=category)(fn)
        except Exception:
            return fn
    return decorator


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
                success_count INTEGER DEFAULT 0,
                failure_count INTEGER DEFAULT 0,
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

        # Non-destructive SQLite column additions for existing installations
        for col, col_def in (
            ("success_count", "INTEGER DEFAULT 0"),
            ("failure_count", "INTEGER DEFAULT 0"),
        ):
            try:
                conn.execute(f"ALTER TABLE alfa_learned_skills ADD COLUMN {col} {col_def};")
            except Exception:
                pass

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


# --- Autonomous User Correction Detection (Auto-Reflexion & Reinforcement) ---

_CORRECTION_TRIGGER_REGEX = re.compile(
    r"\b(salah|bukan|kacau|ngawur|keliru|tidak tepat|jangan|harusnya|seharusnya|yang benar|koreksi|perbaiki|salah hitung|tidak sesuai)\b",
    re.IGNORECASE,
)

_POSITIVE_TRIGGER_REGEX = re.compile(
    r"\b(mantap|sip|keren|bagus|top|benar|sesuai|jos|good job|terima kasih|makasih|tepat sekali|sempurna|juara)\b",
    re.IGNORECASE,
)


def is_user_correction_signal(text: str) -> bool:
    """Detect if user input contains negative feedback or explicit correction."""
    if not text or len(text.strip()) < 4:
        return False
    return bool(_CORRECTION_TRIGGER_REGEX.search(text))


def is_positive_reinforcement_signal(text: str) -> bool:
    """Detect if user input contains positive feedback or praise for completed turn."""
    if not text or len(text.strip()) < 3:
        return False
    return bool(_POSITIVE_TRIGGER_REGEX.search(text))


def extract_correction_topic(text: str) -> str:
    """Identify the domain topic of the correction."""
    t = text.lower()
    if any(k in t for k in ("tiang", "material", "lahat", "curup", "bengkulu", "retur", "mandor", "kabel", "ftth")):
        return "TELECOM_FIELD_LOGISTICS"
    if any(k in t for k in ("excel", "rumus", "formula", "sheet", "sum", "sumifs", "gridcraft")):
        return "EXCEL_SPREADSHEET_LOGIC"
    if any(k in t for k in ("file", "master", "simpan", "tulis", "folder", "kumulatif")):
        return "FILE_STORAGE_POLICY"
    if any(k in t for k in ("wa", "whatsapp", "pesan", "chat", "bot")):
        return "WHATSAPP_INTEGRATION"
    return "USER_HEURISTIC_RULE"


def smart_extract_user_rule(user_text: str) -> tuple[str, str, str]:
    """
    Ekstraksi cerdas (Reflexion Parser) dari koreksi pengguna:
    Mengekstrak (topic, learned_rule, trigger_pattern) secara terstruktur.
    """
    clean_text = user_text.strip()
    topic = extract_correction_topic(clean_text)

    # 1. Deteksi klausa inti kebenaran (truth clause)
    match_truth = re.search(
        r"(?:harusnya|seharusnya|yang benar|yang betul|koreksi\s*:?|aturan\s*:?|wajib|tetap)\s+([^.!?\n]+)",
        clean_text,
        re.IGNORECASE,
    )
    if match_truth:
        core_statement = match_truth.group(1).strip()
        learned_rule = f"ATURAN HASIL KOREKSI PENGGUNA: {core_statement}."
    else:
        # Hilangkan kata koreksi awal jika ada
        stripped = re.sub(
            r"^(?:bukan|salah|ngawur|keliru|koreksi|tidak tepat)[,:\s]+",
            "",
            clean_text,
            flags=re.IGNORECASE,
        ).strip()
        learned_rule = f"ATURAN KOREKSI: {stripped if stripped else clean_text}."

    # 2. Sintesis kata kunci pemicu (high-value domain trigger tokens)
    stop_words = {
        "yang", "dan", "atau", "dari", "pada", "untuk", "dengan", "akan",
        "bukan", "salah", "kacau", "ngawur", "keliru", "tolong", "bisa", "sudah",
        "tapi", "oleh", "dalam", "yaitu", "yakni", "kami", "kamu", "saya"
    }
    raw_words = re.findall(r"\b[a-zA-Z0-9_-]{3,}\b", clean_text.lower())
    filtered_tokens = [w for w in raw_words if w not in stop_words]
    # Ambil hingga 6 token unik
    unique_tokens = list(dict.fromkeys(filtered_tokens))[:6]
    trigger_pattern = " ".join(unique_tokens) if unique_tokens else topic.lower()

    return topic, learned_rule, trigger_pattern


def reinforce_skill(
    skill_id_or_topic: str,
    success: bool = True,
    weight_delta: float = 0.05,
) -> bool:
    """
    ACTIVE HEBBIAN REINFORCEMENT:
    Adjusts skill confidence and telemetry counters based on operational outcome.
    If success=True: confidence increases up to 1.0, success_count increments.
    If success=False: confidence decreases down to 0.1, failure_count increments.
    """
    init_learning_tables()
    with get_sync_db() as conn:
        row = conn.execute(
            """
            SELECT id, skill_id, confidence, success_count, failure_count
            FROM alfa_learned_skills
            WHERE skill_id = ? OR topic = ?
            LIMIT 1
            """,
            (skill_id_or_topic, skill_id_or_topic.upper()),
        ).fetchone()

        if not row:
            return False

        sid = row["id"]
        cur_conf = row["confidence"] or 1.0
        cur_succ = row["success_count"] or 0
        cur_fail = row["failure_count"] or 0

        if success:
            new_conf = min(1.0, round(cur_conf + weight_delta, 3))
            new_succ = cur_succ + 1
            new_fail = cur_fail
        else:
            new_conf = max(0.1, round(cur_conf - (weight_delta * 2), 3))
            new_succ = cur_succ
            new_fail = cur_fail + 1

        conn.execute(
            """
            UPDATE alfa_learned_skills
            SET confidence = ?,
                success_count = ?,
                failure_count = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (new_conf, new_succ, new_fail, sid),
        )
        conn.commit()
        logger.info(
            "Reinforced skill %s: success=%s, conf=%.3f->%.3f (succ=%d, fail=%d)",
            skill_id_or_topic,
            success,
            cur_conf,
            new_conf,
            new_succ,
            new_fail,
        )
        return True


def detect_and_process_user_correction(user_text: str, user_id: int = 0) -> dict[str, Any] | None:
    """
    AUTONOMOUS SELF-IMPROVING REFLEXION:
    Automatically detects when the user corrects the agent, extracts the invariant rule,
    and stores it into alfa_learned_skills so the agent never repeats the same mistake.
    """
    if not is_user_correction_signal(user_text):
        return None

    init_learning_tables()
    topic, learned_rule, trigger_pattern = smart_extract_user_rule(user_text)

    res = synthesize_skill_from_experience(
        topic=topic,
        learned_rule=learned_rule,
        trigger_pattern=trigger_pattern,
        confidence=1.0,
    )

    # Catat koreksi sebagai failure reinforcement pada topik terkait jika sebelumnya ada
    reinforce_skill(topic, success=False)

    logger.info("Autonomous learning loop captured correction: [%s] %s", topic, learned_rule[:60])
    return res


def audit_against_learned_skills(user_prompt: str, reply_text: str) -> tuple[bool, str, str]:
    """
    PRE-FLIGHT COMPLIANCE AUDIT (IN-FLIGHT SELF-CORRECTION):
    Validates drafted agent replies against known critical rules to ensure compliance.
    Returns (is_valid, violation_message, corrected_reply).
    """
    skills = retrieve_relevant_skills(user_prompt, limit=5)
    if not skills:
        return True, "", reply_text

    rep_low = reply_text.lower()
    p_low = user_prompt.lower()

    # Rule 1: Cluster Lahat 160 Tiang
    if "lahat" in p_low and any(k in p_low for k in ("tiang", "material", "rekap", "pengambilan")):
        # If reply mentions poles count other than 160 as net
        if re.search(r"\b(?:total|net|bersih)[^0-9\n]{1,20}(?!160\b)[0-9]{2,4}\s*(?:batang|btg)", rep_low):
            corrected = re.sub(
                r"\b(?:total|net|bersih)[^0-9\n]{1,20}[0-9]{2,4}\s*(?:batang|btg)",
                "total bersih 160 batang",
                reply_text,
                flags=re.IGNORECASE,
            )
            return False, "Koreksi otomatis: Total tiang bersih Lahat adalah 160 batang sesuai aturan CLUSTER_LAHAT_MATERIAL.", corrected

    # Rule 2: Master Ledger Cumulative
    if any(k in rep_low for k in ("membuat file baru", "laporan baru dibuat", "file excel terpisah")):
        if "master" in rep_low or "lahat" in p_low:
            note = "\n\n💡 _Catatan Otomasi: Menggunakan Master Ledger Kumulatif (data diteruskan in-place pada satu berkas master)._"
            return False, "Koreksi otomatis: Menerapkan Master Ledger Kumulatif in-place.", reply_text + note

    # Rule 3: Level 5+ Neuro-Symbolic AST Mathematical & Invariant Proof Gate
    try:
        from alfa.core.apex.neuro_symbolic import verify_and_prove_response

        ns_res = verify_and_prove_response(user_prompt, reply_text)
        if not ns_res.get("is_valid", True):
            v_msg = "; ".join(ns_res.get("violations", []))
            return False, f"Neuro-Symbolic Prover: {v_msg}", ns_res.get("corrected_reply", reply_text)
    except Exception as e:
        logger.debug("Neuro-symbolic gate bypass: %s", e)

    return True, "", reply_text


def get_learning_loop_metrics() -> dict[str, Any]:
    """Retrieve telemetry metrics for the Self-Improving Learning Loop."""
    init_learning_tables()
    with get_sync_db() as conn:
        total_skills = conn.execute("SELECT COUNT(*) FROM alfa_learned_skills WHERE active = 1").fetchone()[0]
        total_trajectories = conn.execute("SELECT COUNT(*) FROM agent_trajectories").fetchone()[0]
        stats_row = conn.execute(
            """
            SELECT
                COALESCE(AVG(confidence), 1.0) AS avg_conf,
                COALESCE(SUM(hit_count), 0) AS total_hits,
                COALESCE(SUM(success_count), 0) AS total_success,
                COALESCE(SUM(failure_count), 0) AS total_failures
            FROM alfa_learned_skills
            WHERE active = 1
            """
        ).fetchone()

        top_skills_rows = conn.execute(
            """
            SELECT topic, learned_rule, hit_count, confidence, success_count, failure_count
            FROM alfa_learned_skills
            WHERE active = 1
            ORDER BY hit_count DESC, id DESC
            LIMIT 5
            """
        ).fetchall()
        top_skills = [dict(r) for r in top_skills_rows]

    return {
        "status": "success",
        "total_active_skills": total_skills,
        "total_trajectories": total_trajectories,
        "avg_confidence": round(float(stats_row["avg_conf"]), 2) if stats_row else 1.0,
        "total_hits": int(stats_row["total_hits"]) if stats_row else 0,
        "total_success": int(stats_row["total_success"]) if stats_row else 0,
        "total_failures": int(stats_row["total_failures"]) if stats_row else 0,
        "top_skills": top_skills,
        "learning_engine": "Hermes-Reflexion-Supreme-v2",
    }


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
