"""
Real-time logging, live feed streaming, QA evaluation, and intent detection for ALFA Swarm.
"""

import itertools
import json
import logging
import os
import re
from datetime import datetime
from typing import Any

from alfa.swarm.workspace_hygiene import (
    LIVE_FEED_FILE,
    LIVE_LOG,
    _get_swarm_output_dir,
)

logger = logging.getLogger(__name__)

# Checkpoint system
try:
    from alfa.swarm.checkpoint import SwarmCheckpoint as _SwarmCheckpoint

    _CHECKPOINT_AVAILABLE = True
except ImportError:
    _CHECKPOINT_AVAILABLE = False
    _SwarmCheckpoint = None


def _load_last_seq() -> int:
    try:
        output_dir = _get_swarm_output_dir()
        feed_file = os.path.join(output_dir, "live_meeting_feed.jsonl")
        if not os.path.exists(feed_file):
            feed_file = LIVE_FEED_FILE
        with open(feed_file, encoding="utf-8") as f:
            lines = f.read().strip().splitlines()
        if lines:
            return int(json.loads(lines[-1]).get("i", 0))
    except Exception:
        pass
    return 0


_live_seq = itertools.count(_load_last_seq() + 1)


def _append_feed_file(entry: dict[str, Any]) -> None:
    """Append satu baris JSONL; rotasi sederhana bila >300KB."""
    try:
        output_dir = _get_swarm_output_dir()
        feed_file = os.path.join(output_dir, "live_meeting_feed.jsonl")
        if os.path.exists(feed_file) and os.path.getsize(feed_file) > 300_000:
            with open(feed_file, encoding="utf-8") as f:
                lines = f.readlines()[-150:]
            tmp = feed_file + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.writelines(lines)
            os.replace(tmp, feed_file)
        with open(feed_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


def log_live(tag: str, text: str) -> None:
    """Append one realtime line for the dashboard live terminal. Fail-safe."""
    try:
        entry = {
            "i": next(_live_seq),
            "ts": datetime.now().strftime("%H:%M:%S"),
            "tag": tag.upper(),
            "text": str(text)[:400],
        }
        LIVE_LOG.append(entry)
        _append_feed_file(entry)
    except Exception:
        pass


def log_tool_live(text: str) -> None:
    """Jembatan aktivitas tool dari jalur MainBrain -> live feed UI.
    Hanya menulis saat ada rapat berjalan; aman dipanggil lintas modul."""
    from alfa.swarm import workspace_hygiene

    if not workspace_hygiene.MEETING_RUNNING:
        return
    log_live("TOOL", text)


def _build_error_context(failed_steps: list) -> str:
    """Format daftar kegagalan agen menjadi blok konteks untuk agen berikutnya."""
    if not failed_steps:
        return ""
    lines = ["⚠️ KEGAGALAN AGEN SEBELUMNYA (jangan ulangi — selesaikan yang belum):"]
    for fs in failed_steps[-3:]:
        lines.append(
            f"  • {fs.get('agent_name','?')} [{fs.get('tool_used','?')}]: "
            f"{(fs.get('feedback') or fs.get('execution_summary',''))[:120]}"
        )
    return "\n".join(lines)


def _record_step_error(session_id: str, step_result: dict, feedback: str) -> None:
    """Catat kegagalan satu step ke checkpoint jika tersedia."""
    if _CHECKPOINT_AVAILABLE and session_id:
        try:
            _SwarmCheckpoint.add_error(
                session_id=session_id,
                step_name=step_result.get("task_assigned", "")[:80],
                agent_name=step_result.get("agent_name", "?"),
                error=feedback or step_result.get("execution_summary", ""),
            )
        except Exception:
            pass


def qa_verdict_passed(text: str) -> bool:
    """True bila teks laporan QA memuat verdict LULUS (QA_VERDICT: PASS)."""
    return bool(re.search(r"QA_VERDICT\s*:\s*PASS", text or "", re.IGNORECASE))


def detect_task_intent(topic: str) -> dict[str, Any]:
    """Analyze the user's topic/command to determine tool strategy, categories, and limits."""
    low = (topic or "").lower()

    count_match = re.search(r"\b(\d{1,3})\b", low)
    limit = int(count_match.group(1)) if count_match else 20
    limit = min(50, max(5, limit))

    is_scrape = any(
        k in low
        for k in [
            "scrape",
            "scraping",
            "ambil data",
            "sedot",
            "cari data",
            "carikan produk",
            "lowongan",
            "kontak",
            "supplier",
            "harga",
        ]
    )
    is_code = any(
        k in low
        for k in [
            "script",
            "skrip",
            "python",
            "koding",
            "coding",
            "program",
            "buatkan script",
            "bikin script",
            "aplikasi",
            "fungsi",
            "function",
        ]
    )
    is_audit = any(
        k in low
        for k in [
            "audit",
            "security",
            "keamanan",
            "vram",
            "ram",
            "cpu",
            "port",
            "firewall",
            "celah",
        ]
    )

    category = "general_web"
    if any(
        k in low
        for k in [
            "shopee",
            "tokopedia",
            "tiktok",
            "lazada",
            "blibli",
            "marketplace",
            "produk",
            "jual",
            "harga",
            "beli",
            "mouse",
            "baju",
            "sepatu",
            "laptop",
            "hp",
        ]
    ):
        category = "all_marketplace"
    elif any(
        k in low
        for k in [
            "loker",
            "lowongan",
            "kerja",
            "job",
            "karir",
            "jobstreet",
            "glints",
            "linkedin",
        ]
    ):
        category = "jobs_career"
    elif any(
        k in low
        for k in [
            "kontak",
            "supplier",
            "wa",
            "whatsapp",
            "distributor",
            "email",
            "pabrik",
        ]
    ):
        category = "leads_contacts"
    elif any(k in low for k in ["berita", "news", "detik", "kompas", "cnn", "media"]):
        category = "news_media"

    cleaned = topic or ""
    fillers = [
        r"(?i)\b(tolong|coba|scrape|scraping|carikan|ambilkan|ambil|cari|eksekusi|buatkan|bikin|analisa|analisis|rekap|buatkan skrip|skrip|script|rekap csv|csv-nya|file csv|terlaris|terpopuler|murah|bagus|dan buatkan.*|analisa rentang.*)\b",
        r"(?i)\b(di shopee|di tokopedia|di lazada|di tiktok|shopee & tokopedia|shopee dan tokopedia|di marketplace|di google)\b",
        r"\b\d+\b",
        r"[^\w\s-]",
    ]
    for p in fillers:
        cleaned = re.sub(p, " ", cleaned)
    cleaned = " ".join(cleaned.split()).strip()
    if len(cleaned) < 3:
        cleaned = (topic or "")[:40]

    return {
        "is_scrape": is_scrape,
        "is_code": is_code,
        "is_audit": is_audit,
        "category": category,
        "limit": limit,
        "clean_query": cleaned,
    }
