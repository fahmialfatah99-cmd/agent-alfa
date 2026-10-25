"""Pipeline Stage 1: Context, Compaction, and System Prompt Assembly."""

from __future__ import annotations

import logging
import os
import sqlite3
from typing import Any

from alfa.bot.config import (
    ALFA_PROMPT_PATH,
    ANTIGRAVITY_WORKFLOW_BLOCK,
    BASE_SYSTEM_PROMPT,
    CAPABILITIES_BLOCK,
    CODING_DELIVERY_BLOCK,
    ENFORCEMENT_BLOCK,
    GEMINI_MODEL,
    HONESTY_BLOCK,
    OWNER_NAME,
    SUPERPOWERS_SKILLS_BLOCK,
    TOOL_FIRST_EXECUTION_BLOCK,
    UI_UX_PRO_MAX_BLOCK,
)

logger = logging.getLogger("ContextBuilder")

# SQL recall arsip material (bandit B608-safe: konstanta polos, interpolasi
# hanya daftar '?' placeholders via .replace — nilai user selalu parameterized).
_MATERIAL_RECALL_SQL = """
                SELECT id, role, content FROM chat_history
                WHERE user_id = ?
                  AND id NOT IN ({EX_IDS})
                  AND (
                      content LIKE '%mandor%' OR content LIKE '%cluster%' OR content LIKE '%kabel%'
                      OR content LIKE '%pole%' OR content LIKE '%tiang%' OR content LIKE '%pengambilan%'
                      OR content LIKE '%dead end%' OR content LIKE '%clamp%' OR content LIKE '%habib%'
                      OR content LIKE '%kasambe%' OR content LIKE '%jany%'
                  )
                ORDER BY id DESC LIMIT 10
                """

_COMPACT_KEEP = 12
_COMPACT_WINDOW = 40
_COMPACT_MIN_NEW = 8
_COMPACT_MODEL = "gemini-3.5-flash"

_TURN_EXEC_ERR: tuple[type[BaseException], ...] = (
    OSError,
    ValueError,
    RuntimeError,
    TypeError,
    KeyError,
    AttributeError,
    ImportError,
    TimeoutError,
    ConnectionError,
    sqlite3.Error,
)


def format_compaction(summary: str) -> str:
    """Format compacted history summary as a structured block."""
    if not (summary or "").strip():
        return ""
    return (
        "\n\n======================================================\n"
        "🗜️ [RINGKASAN PERCAKAPAN LAMA — COMPACTED]\n"
        "Konteks lawas yang sudah diringkas otomatis (detail 12 pesan terakhir tetap utuh di atas):\n"
        + summary.strip()
        + "\n======================================================\n"
    )


async def summarize_chunk(
    prev_summary: str, fresh: list[dict], gemini_client: Any = None
) -> str:
    """Ringkas satu potongan riwayat via model murah sekali-jalan (tanpa tools)."""
    if gemini_client is None:
        return ""
    try:
        from google.genai import types

        convo = "\n".join(
            f"{m.get('role', '?')}: {str(m.get('content', ''))[:600]}"
            for m in fresh[-30:]
        )
        base = (
            f"Ringkasan sebelumnya:\n{prev_summary}\n\n"
            if (prev_summary or "").strip()
            else ""
        )
        candidate_models = [
            "gemini-flash-lite-latest",
            "gemini-3.5-flash-lite",
            _COMPACT_MODEL,
        ]
        resp = None
        used_model = _COMPACT_MODEL
        for cand in candidate_models:
            try:
                resp = await gemini_client.aio.models.generate_content(
                    model=cand,
                    contents=(
                        base
                        + "Percakapan lanjutan:\n"
                        + convo
                        + "\n\nRingkas gabungan jadi MAKS 20 baris: fakta penting, "
                        "keputusan, janji/tugas terbuka, catatan material lapangan (nama mandor, cluster, jumlah kabel/tiang/aksesoris), preferensi user. Bahasa Indonesia, fakta saja."
                    ),
                    config=types.GenerateContentConfig(
                        system_instruction="Kamu peringkas memori percakapan. Fakta saja, tanpa basa-basi."
                    ),
                )
                if resp and (getattr(resp, "text", "") or "").strip():
                    used_model = cand
                    break
            except Exception:
                continue

        if resp is None:
            return ""

        try:
            from alfa.core import token_usage as _tu

            _tu.from_gemini_response(
                resp,
                model=f"{used_model}:compact",
                context="telegram_chat:compact",
            )
        except (ImportError, AttributeError, TypeError, ValueError):
            pass
        return (getattr(resp, "text", "") or "").strip()
    except _TURN_EXEC_ERR as e:
        logger.debug(f"[compact] ringkas gagal: {e}")
        return ""


async def maybe_compact_history(
    db: Any, user_id: int, gemini_client: Any = None
) -> str:
    """Rolling summary riwayat lama. Return blok prompt ('' bila tak perlu). Fail-open."""
    if not user_id:
        return ""
    try:
        get_conn = getattr(db, "get_sync_db", None)
        if get_conn is None:
            from alfa.core import database as _ddb

            get_conn = _ddb.get_sync_db
        with get_conn() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS chat_compactions ("
                " user_id INTEGER PRIMARY KEY, summary TEXT DEFAULT '',"
                " up_to_id INTEGER DEFAULT 0,"
                " updated_at DATETIME DEFAULT CURRENT_TIMESTAMP)"
            )
            try:
                row = conn.execute(
                    "SELECT summary, up_to_id FROM chat_compactions WHERE user_id = ?",
                    (user_id,),
                ).fetchone()
                prev = str(row[0] or "") if row else ""
                up_to = int(row[1] or 0) if row else 0
            except (sqlite3.Error, TypeError, ValueError, IndexError):
                prev, up_to = "", 0
            msgs = conn.execute(
                "SELECT id, role, content FROM chat_history WHERE user_id = ? "
                "ORDER BY id DESC LIMIT ?",
                (user_id, _COMPACT_WINDOW),
            ).fetchall()
            msgs = [
                {"id": m[0], "role": m[1], "content": m[2]}
                for m in reversed(msgs)
            ]
            if len(msgs) <= _COMPACT_KEEP + 4:
                return format_compaction(prev)
            kept_ids = {m["id"] for m in msgs[-_COMPACT_KEEP:]}
            fresh = [
                m for m in msgs if m["id"] > up_to and m["id"] not in kept_ids
            ]
            if len(fresh) >= _COMPACT_MIN_NEW:
                new_summary = await summarize_chunk(
                    prev, fresh, gemini_client=gemini_client
                )
                if new_summary:
                    new_up_to = max(m["id"] for m in fresh)
                    conn.execute(
                        "INSERT INTO chat_compactions (user_id, summary, up_to_id, updated_at) "
                        "VALUES (?, ?, ?, CURRENT_TIMESTAMP) "
                        "ON CONFLICT(user_id) DO UPDATE SET summary = excluded.summary, "
                        "up_to_id = excluded.up_to_id, updated_at = CURRENT_TIMESTAMP",
                        (user_id, new_summary, new_up_to),
                    )
                    try:
                        conn.commit()
                    except sqlite3.Error:
                        pass
                    prev = new_summary
            return format_compaction(prev)
    except _TURN_EXEC_ERR as e:
        logger.debug(f"[compact] dilewati: {e}")
        return ""


def build_memory_block(
    user_id: int,
    user_prompt: str,
    user_memories: list,
    kg_triples: list,
    compaction_block: str,
    db: Any = None,
    exclude_history_ids: set[int] | None = None,
) -> str:
    """Rakit blok ingatan jangka panjang + Auto-RAG + ringkasan kompaksi + Session Material Recall.

    Mendukung penarikan catatan material lawas dalam sesi ini agar rekapitulasi tidak memotong mandor.
    """
    memory_context_parts = []
    if user_memories:
        memory_context_parts.append("📌 FAKTA & CATATAN PRIBADI TERSIMPAN:")
        for m in user_memories:
            memory_context_parts.append(
                f"- [{m['category']}] {m['key_topic']}: {m['content']}"
            )

    if kg_triples:
        memory_context_parts.append("🕸️ RELASI KNOWLEDGE GRAPH:")
        for k in kg_triples[:15]:
            tag_str = f" ({k['tags']})" if k.get("tags") else ""
            memory_context_parts.append(
                f"- {k['entity']} -> [{k['relation']}] -> {k['target_value']}{tag_str}"
            )

    # AUTO-RAG: potongan dokumen Drive yang relevan dgn pertanyaan
    p_check = (user_prompt or "").lower().strip()
    should_search_rag = (
        len(p_check) > 15
        and not any(
            p_check == g or p_check.startswith(g + " ")
            for g in [
                "halo",
                "hai",
                "pagi",
                "siang",
                "malam",
                "apa kabar",
                "siapa kamu",
                "tes",
                "ping",
            ]
        )
        and any(
            k in p_check
            for k in [
                "dokumen",
                "drive",
                "file",
                "catatan",
                "ingat",
                "materi",
                "referensi",
                "data",
                "info",
                "tentang",
                "jelaskan",
                "bagaimana",
                "apa itu",
                "siapa",
            ]
        )
    )

    if should_search_rag:
        try:
            from alfa.memory import vector as vector_memory

            brain_hits = vector_memory.semantic_search(
                user_id=user_id, query=user_prompt or "", top_k=4
            )
            relevant = [
                h
                for h in brain_hits
                if (h.get("similarity_score") or 0) >= 0.25
            ]
            if relevant:
                memory_context_parts.append(
                    "📄 PENGETAHUAN DARI DOKUMEN DRIVE (Second Brain):"
                )
                for h in relevant:
                    memory_context_parts.append(
                        f"- [{h.get('doc_title', '?')}] {str(h.get('chunk_text', ''))[:350]}"
                    )
        except (
            ImportError,
            OSError,
            sqlite3.Error,
            ValueError,
            TypeError,
            KeyError,
        ) as rag_err:
            logger.debug(f"Auto-RAG skipped: {rag_err}")

    # MATERIAL SESSION RECALL: Jika prompt terkait material/mandor/rekap, tarik arsip material sesi terdahulu
    p_check_mat = (user_prompt or "").lower()
    mat_keywords = [
        "mandor", "material", "rekap", "rangkuman", "surat jalan",
        "habib", "jany", "kasambe", "yanto", "apied", "delima", "swadayan",
        "tiang", "pole", "kabel", "pengambilan", "retur", "pengembalian",
        "dead end", "clamp", "stopping", "suspension",
    ]
    if db and any(kw in p_check_mat for kw in mat_keywords):
        try:
            get_conn = getattr(db, "get_sync_db", None)
            if get_conn is None:
                from alfa.core import database as _ddb
                get_conn = _ddb.get_sync_db
            with get_conn() as conn:
                ex_ids = list(exclude_history_ids or [])
                placeholders = ",".join("?" for _ in ex_ids) if ex_ids else "0"
                query = _MATERIAL_RECALL_SQL.replace("{EX_IDS}", placeholders)
                params = [user_id] + ex_ids
                mat_rows = conn.execute(query, params).fetchall()
                if mat_rows:
                    mat_lines = []
                    for r in reversed(mat_rows):
                        r_id = r[0] if isinstance(r, (tuple, list)) else r["id"]
                        r_role = r[1] if isinstance(r, (tuple, list)) else r["role"]
                        r_content = r[2] if isinstance(r, (tuple, list)) else r["content"]
                        mat_lines.append(f"- [ID {r_id} | {r_role}]: {str(r_content)[:350]}")
                    memory_context_parts.append(
                        "📦 [ARSIP MATERIAL & SURAT JALAN SESI SEBELUMNYA HARI INI]:\n"
                        "Gunakan catatan material terdahulu ini jika pengguna meminta rekapitulasi menyeluruh atau "
                        "menyinggung mandor yang pernah dicatat sebelumnya (agar TIDAK ADA mandor atau rincian material yang terlewat):\n"
                        + "\n".join(mat_lines)
                    )
        except Exception as mat_err:
            logger.debug(f"[material_recall] gagal: {mat_err}")

    # 3. KNOWLEDGE GRAPH RECALL (GRAPHRAG PRE-FETCH):
    # Menyuntikkan subgraf 1-hop & relasi relasional ke konteks prompt jika ada entitas cocok
    try:
        from alfa.memory import graph_rag

        graph_facts = graph_rag.get_pre_turn_graph_context(
            user_id=user_id, prompt=user_prompt
        )
        if graph_facts:
            memory_context_parts.append(graph_facts)
    except Exception as graph_err:  # noqa: BLE001
        logger.debug(f"[graph_rag_recall] gagal: {graph_err}")

    memory_block = ""
    if memory_context_parts:
        memory_block = (
            "\n\n======================================================\n"
            "🧠 [INGATAN JANGKA PANJANG & SECOND BRAIN AKTIF]\n"
            f"Berikut adalah seluruh ingatan jangka panjang dan fakta yang tersimpan tentang {OWNER_NAME}. "
            "Pahami dan gunakan fakta ini secara alami dalam percakapan tanpa perlu bertanya ulang:\n"
            + "\n".join(memory_context_parts)
            + "\n======================================================\n"
        )

    if compaction_block:
        memory_block += compaction_block
    return memory_block


async def build_system_instruction(
    db: Any,
    user_id: int,
    brain: dict,
    override_model: str | None,
    memory_block: str,
    user_prompt: str = "",
) -> tuple[str, str, str]:
    """Muat settings pengguna & file prompt; rakit instruksi sistem final.

    Return ``(full_system_instruction, preferred_model, current_active_model)``.
    """
    user_settings = await db.get_user_settings(user_id)

    # Reload latest prompt from file if available
    active_base_prompt = BASE_SYSTEM_PROMPT
    if os.path.exists(ALFA_PROMPT_PATH):
        try:
            with open(ALFA_PROMPT_PATH, encoding="utf-8") as f:
                active_base_prompt = f.read().strip()
        except OSError:
            pass

    brain_model_override = (
        db.get_main_brain_model()
        if hasattr(db, "get_main_brain_model")
        else None
    )
    preferred_model = (
        override_model or user_settings.get("model_name") or GEMINI_MODEL
    )
    current_active_model = (
        override_model
        or brain.get("model")
        or brain_model_override
        or preferred_model
    )
    current_active_provider = brain.get("provider", "gemini").upper()
    current_key_label = brain.get("label", "")

    active_identity_block = (
        f"\n\n### 🤖 INFORMASI ENGINE & MODEL AKTIF SAAT INI (GROUND TRUTH)\n"
        f"- MODEL AI AKTIF SAAT INI: `{current_active_model}`\n"
        f"- PROVIDER / GATEWAY: `{current_active_provider}`\n"
        f"- KUNCI/AKUN VAULT: `{current_key_label}`\n"
        f"- Jika pengguna bertanya kamu pakai model apa, model apa yang sedang aktif, atau identitas enginemu, "
        f"jawab dengan jujur dan jelas bahwa saat ini kamu ditenagai oleh model `{current_active_model}` ({current_active_provider})!\n"
    )

    base_instruction = (
        user_settings.get("system_prompt_override") or active_base_prompt
    )
    from alfa.tools.system.constants import is_unrestricted

    unrestricted_block = (
        (
            "\n\n### ⚡ HAK AKSES HOST LINUX PENUH (UNRESTRICTED MODE)\n"
            "- Kamu beroperasi dengan AKSES HOST LINUX LANGSUNG PENUH di mesin pengguna (bukan di dalam container atau sandbox Docker terisolasi).\n"
            "- Eksekusi bash (`execute_bash_command`) dan script Python (`execute_python_sandbox`) berjalan langsung di mesin Linux pengguna.\n"
            "- Tidak ada blocklist perintah dan tidak ada permission gate yang membatasi tindakanmu.\n"
            "- Kamu memiliki wewenang penuh dari Fahmi untuk mengeksekusi perintah sistem, menginstal paket sistem/pip, memodifikasi file di sistem, dan menggunakan `sudo` kapan pun dibutuhkan tanpa ragu.\n"
        )
        if is_unrestricted()
        else ""
    )

    learned_skills_prompt = ""
    if user_prompt:
        try:
            from alfa.core.brain.learning_loop import format_learned_skills_prompt

            learned_skills_prompt = format_learned_skills_prompt(user_prompt)
        except Exception as e:
            logger.debug("Learning loop prompt format bypass: %s", e)

    full_system_instruction = (
        base_instruction
        + active_identity_block
        + memory_block
        + (f"\n\n{learned_skills_prompt}" if learned_skills_prompt else "")
        + ENFORCEMENT_BLOCK
        + HONESTY_BLOCK
        + CODING_DELIVERY_BLOCK
        + CAPABILITIES_BLOCK
        + ANTIGRAVITY_WORKFLOW_BLOCK
        + TOOL_FIRST_EXECUTION_BLOCK
        + SUPERPOWERS_SKILLS_BLOCK
        + UI_UX_PRO_MAX_BLOCK
        + unrestricted_block
    )
    return full_system_instruction, preferred_model, current_active_model
