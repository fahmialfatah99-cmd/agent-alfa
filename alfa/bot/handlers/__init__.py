"""Handler pesan & callback untuk ALFA Telegram Bot.

Pecah dari modul monolitik `handlers.py` (2.839 baris) menjadi sub-modul
per tanggung jawab. **Import path publik tidak berubah** — semua simbol tetap
di-import dari `alfa.bot.handlers`.

Sub-modul:
- `_state`    : state mutable & konstanta bersama.
- `_compat`   : akses dinamis ke simbol paket (patch/mock tetap berlaku).
- `common`    : sapaan, otorisasi, agent turn, nudge.
- `artifacts` : deteksi intent media & pengiriman artefak.
- `documents` : cache dokumen, aksi dokumen, batch dokumen/foto.
- `forwards`  : pesan ter-forward & aksi batch forward.
- `menus`     : router callback query & dispatch menu.
- `messages`  : pesan teks, voice note, fast-path pesan masuk WhatsApp.
"""

import asyncio
import io
import json
import logging
import os
import sys
import time
from typing import Any

from telegram import Update, constants
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from alfa import tools
from alfa.bot.config import (
    GEMINI_MODEL,
    _main_brain_gemini_model,
    is_authorized,
    resolve_main_gemini,
)
from alfa.bot.handlers._state import (
    _ARTIFACT_INTENT_KEYWORDS,
    _DOC_BATCH_LOCK,
    _DOC_BATCHES,
    _FORWARD_BATCH_LOCK,
    _FORWARD_BATCHES,
    _GREETING_EXACT,
    _HANDLER_ERR,
    _PHOTO_BATCH_LOCK,
    _PHOTO_BATCHES,
    _PROCESSED_ARTIFACT_TURNS,
    _RECENT_DOCS,
    _RECENT_DOCS_CACHE_PATH,
    _RECENT_FORWARD_BATCHES,
    _WA_INCOMING_TRIGGERS,
    ACTIVE_CHAT_TASKS,
)
from alfa.bot.handlers.artifacts import (
    _check_and_send_media_artifacts,
    _safe_unlink,
    check_and_send_media_artifacts,
    has_artifact_intent,
    is_artifact_producing_tool,
)
from alfa.bot.handlers.common import (
    _get_bot_module,
    _is_authorized,
    _long_turn_nudge,
    _run_agent_turn,
    greeting_reply,
)
from alfa.bot.handlers.documents import (
    _execute_document_batch,
    _get_or_recover_recent_doc,
    _parse_summary_into_table,
    _save_recent_docs_cache,
    handle_doc_action_callback,
    handle_document_message,
)
from alfa.bot.handlers.forwards import (
    _execute_forward_batch,
    get_forward_info,
    handle_forward_action_callback,
)
from alfa.bot.handlers.media import _execute_photo_batch, handle_photo_message
from alfa.bot.handlers.menus import _dispatch_menu_callback, handle_callback_query
from alfa.bot.handlers.messages import (
    handle_text_message,
    handle_voice_message,
    try_handle_fast_wa,
)
from alfa.bot.helpers import (
    safe_send_message,
    send_typing_loop,
    should_reply_with_text_instead_of_voice,
)
from alfa.bot.streamer import TelegramStreamer
from alfa.bot.turn_executor import run_agent_turn
from alfa.core import database
from alfa.media import tts_engine
from alfa.tools import SANDBOX_DIR, get_system_stats

logger = logging.getLogger("TelegramAIAgent")

#: API publik paket — dipakai `from alfa.bot.handlers import *` (bot Telegram)
#: dan menjaga patch/mock pada `alfa.bot.handlers.<nama>` tetap bermakna.
__all__ = [
    "ACTIVE_CHAT_TASKS",
    "Any",
    "ContextTypes",
    "GEMINI_MODEL",
    "SANDBOX_DIR",
    "TelegramError",
    "TelegramStreamer",
    "Update",
    "_main_brain_gemini_model",
    "asyncio",
    "io",
    "json",
    "logging",
    "os",
    "sys",
    "time",
    "_ARTIFACT_INTENT_KEYWORDS",
    "_DOC_BATCHES",
    "_DOC_BATCH_LOCK",
    "_FORWARD_BATCHES",
    "_FORWARD_BATCH_LOCK",
    "_GREETING_EXACT",
    "_HANDLER_ERR",
    "_PHOTO_BATCHES",
    "_PHOTO_BATCH_LOCK",
    "_PROCESSED_ARTIFACT_TURNS",
    "_RECENT_DOCS",
    "_RECENT_DOCS_CACHE_PATH",
    "_RECENT_FORWARD_BATCHES",
    "_WA_INCOMING_TRIGGERS",
    "_check_and_send_media_artifacts",
    "_dispatch_menu_callback",
    "_execute_document_batch",
    "_execute_forward_batch",
    "_execute_photo_batch",
    "_get_bot_module",
    "_get_or_recover_recent_doc",
    "_is_authorized",
    "_long_turn_nudge",
    "_parse_summary_into_table",
    "_run_agent_turn",
    "_safe_unlink",
    "_save_recent_docs_cache",
    "check_and_send_media_artifacts",
    "constants",
    "database",
    "get_forward_info",
    "get_system_stats",
    "greeting_reply",
    "handle_callback_query",
    "handle_doc_action_callback",
    "handle_document_message",
    "handle_forward_action_callback",
    "handle_photo_message",
    "handle_text_message",
    "handle_voice_message",
    "has_artifact_intent",
    "is_artifact_producing_tool",
    "is_authorized",
    "resolve_main_gemini",
    "run_agent_turn",
    "safe_send_message",
    "send_typing_loop",
    "should_reply_with_text_instead_of_voice",
    "tools",
    "try_handle_fast_wa",
    "tts_engine",
]
