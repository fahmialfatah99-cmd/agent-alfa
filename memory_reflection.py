"""
MEMORY REFLECTION LAYER — langkah menuju memori hierarkis ala MemGPT.

Setiap N giliran percakapan, agent "merefleksikan" dialog terakhir secara
otomatis: mengekstrak fakta tahan-lama (preferensi, proyek, aturan) lalu
menyimpannya ke memori jangka panjang TANPA diminta user.

Layer:
  - Recall  : riwayat chat (sudah ada, SQLite)
  - Archival: knowledge memory hasil refleksi otomatis (ini modulnya)

Env:
    ALFA_MEMORY_REFLECT=on|off   (default on)
    ALFA_MEMORY_REFLECT_EVERY=6  interval giliran antar-refleksi per user
"""

import asyncio
import json
import logging
import os
from typing import Any, Dict, List

logger = logging.getLogger("MemoryReflection")

_ENABLED = os.getenv("ALFA_MEMORY_REFLECT", "on").strip().lower() != "off"
try:
    EVERY = max(2, int(os.getenv("ALFA_MEMORY_REFLECT_EVERY", "6")))
except ValueError:
    EVERY = 6

_reflection_counters: Dict[int, int] = {}

_REFLECTION_PROMPT = """Analisis percakapan berikut dan ekstrak HANYA fakta tahan-lama
yang layak diingat jangka panjang tentang pengguna/proyeknya (preferensi, nama proyek,
stack teknologi, aturan kerja, informasi identitas). Abaikan smalltalk dan pertanyaan sekali-pakai.

Balas HANYA JSON array (bisa kosong []), format tiap item:
{"key_topic": "<judul pendek snake_case>", "content": "<fakta lengkap>", "category": "preference|project|general"}

PERCAKAPAN:
"""


def should_reflect(user_id: int) -> bool:
    """Dipanggil setelah tiap balasan sukses; True saat giliran refleksi tiba."""
    if not _ENABLED:
        return False
    _reflection_counters[user_id] = _reflection_counters.get(user_id, 0) + 1
    return _reflection_counters[user_id] % EVERY == 0


async def reflect_recent_conversation(user_id: int, history: List[Dict[str, str]]) -> int:
    """
    Jalankan refleksi via otak utama, simpan fakta hasil ekstraksi.
    Return jumlah fakta tersimpan. Fire-and-forget friendly (tak pernah raise).
    """
    try:
        if not history:
            return 0

        import database
        convo_text = "\n".join(
            f"{('USER' if m.get('role') in ('user',) else 'AGENT')}: {str(m.get('content', ''))[:500]}"
            for m in history[-10:]
        )[:8000]

        import main_brain as mb
        brain = mb.get_main_brain()
        if not brain.get("api_key"):
            return 0

        raw = await mb.run_openai_agentic_turn(
            provider=brain["provider"],
            base_url=brain["base_url"],
            api_key=brain["api_key"],
            model=brain["model"] or "gemini-3.6-flash",
            system_instruction=(
                "Kamu adalah mesin ekstraksi memori. Balas HANYA JSON array valid, "
                "tanpa penjelasan, tanpa markdown fence."
            ),
            user_text=_REFLECTION_PROMPT + convo_text,
            context="memory_reflection",
        )
        if not raw:
            return 0

        # Bersihkan kemungkinan markdown fence / prolog
        txt = raw.strip()
        if txt.startswith("```"):
            txt = txt.split("```")[1]
            if txt.startswith("json"):
                txt = txt[4:]
        start, end = txt.find("["), txt.rfind("]")
        if start == -1 or end == -1 or end <= start:
            return 0
        facts = json.loads(txt[start:end + 1])
        if not isinstance(facts, list):
            return 0

        saved = 0
        for fact in facts[:5]:  # batasi 5 fakta/refleksi
            try:
                await database.save_memory_fact(
                    user_id=user_id,
                    key_topic=str(fact.get("key_topic", ""))[:80] or f"refleksi_{user_id}",
                    content=str(fact.get("content", ""))[:1000],
                    category=str(fact.get("category", "general"))[:30],
                )
                saved += 1
            except Exception:
                continue
        if saved:
            logger.info(f"[Reflect] {saved} fakta baru tersimpan utk user {user_id}")
        return saved
    except Exception as e:
        logger.debug(f"[Reflect] dilewati: {e}")
        return 0


def maybe_schedule_reflection(user_id: int, history: List[Dict[str, str]]) -> None:
    """Hook ringan dipanggil dari handler pesan; menjadwalkan refleksi bila waktunya."""
    try:
        if should_reflect(user_id):
            asyncio.get_running_loop().create_task(
                reflect_recent_conversation(user_id, history))
    except Exception:
        pass
