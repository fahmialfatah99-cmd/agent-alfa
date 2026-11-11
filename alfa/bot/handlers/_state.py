"""State mutable & konstanta bersama antar handler Telegram.

Dipisah dari logika agar semua sub-modul memakai objek yang sama
(mis. `ACTIVE_CHAT_TASKS` juga dipakai `alfa.bot.mode_commands`).
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from typing import Any

from telegram.error import TelegramError

_HANDLER_ERR = (
    TelegramError,
    OSError,
    ValueError,
    RuntimeError,
    TypeError,
    KeyError,
    AttributeError,
    ImportError,
)

#: Registry task yang sedang berjalan per chat_id (bisa di-cancel via /cancel).
ACTIVE_CHAT_TASKS: dict[int, asyncio.Task] = {}

#: Sapaan ringan yang dijawab langsung tanpa agent turn.
_GREETING_EXACT = {
    "halo", "hallo", "hello", "hi", "hai", "hei", "hey", "hola",
    "pagi", "siang", "sore", "malam",
    "selamat pagi", "selamat siang", "selamat sore", "selamat malam",
    "assalamualaikum", "assalamu'alaikum", "salam",
    "tes", "test", "testing", "ping", "p",
    "apa kabar", "gimana kabar", "bagaimana kabar",
    "ok", "oke", "okey", "okay", "siap", "sip", "mantap",
    "makasih", "terima kasih", "thanks", "thank you", "trims",
    "baik", "noted", "hehe", "haha", "wkwk", "👍",
}

#: Cache dokumen terakhir per chat.
_RECENT_DOCS: dict[int, dict[str, Any]] = {}

#: Folder cache unggahan dokumen. Dipisah per-user (bukan /tmp global) agar
#: tidak bisa ditambi/sybil oleh proses lain di mesin yang sama.
UPLOAD_CACHE_DIR = os.path.join(
    tempfile.gettempdir(), f"alfa_uploads_{os.getuid() if hasattr(os, 'getuid') else 'user'}"
)


def ensure_upload_cache_dir() -> str:
    """Buat folder cache unggahan dengan izin 0700 (anti symlink/sybil)."""
    os.makedirs(UPLOAD_CACHE_DIR, mode=0o700, exist_ok=True)
    try:
        os.chmod(UPLOAD_CACHE_DIR, 0o700)
    except OSError:
        pass
    return UPLOAD_CACHE_DIR


_RECENT_DOCS_CACHE_PATH = os.path.join(UPLOAD_CACHE_DIR, "recent_docs_cache.json")

#: Batch forward yang sedang berjalan.
_FORWARD_BATCHES: dict[int, dict[str, Any]] = {}
_FORWARD_BATCH_LOCK = asyncio.Lock()
_RECENT_FORWARD_BATCHES: dict[int, dict[str, Any]] = {}

#: Keyword yang mengindeksi intent pengiriman media.
_ARTIFACT_INTENT_KEYWORDS = (
    "screenshot",
    "tangkapan layar",
    "capture",
    "excel",
    "rekap",
    "pdf",
    "grafik",
    "chart",
    "file",
    "berkas",
    "dokumen",
)

#: Turn yang artefaknya sudah dikirim (anti duplikasi).
_PROCESSED_ARTIFACT_TURNS: dict[str, float] = {}

#: Trigger cepat pesan masuk WhatsApp.
_WA_INCOMING_TRIGGERS = (
    "pengambilan",
    "material",
    "retur",
    "kembali",
    "tiang",
    "kabel",
)

#: Batch foto & dokumen yang sedang berjalan.
_PHOTO_BATCHES: dict[int, dict[str, Any]] = {}
_PHOTO_BATCH_LOCK = asyncio.Lock()
_DOC_BATCHES: dict[int, dict[str, Any]] = {}
_DOC_BATCH_LOCK = asyncio.Lock()
