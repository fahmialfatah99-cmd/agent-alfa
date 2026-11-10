"""Productivity, WhatsApp bridge, Android, and SQLite query tools for ALFA.

Pecah dari modul monolitik ``integrations.py``. **Import path publik tidak
berubah** — simbol tetap di-import dari ``alfa.tools.system.integrations``.

Sub-modul:
- ``_api``          : HTTP client internal bot WhatsApp.
- ``productivity``  : reminder, password aman, sesi fokus.
- ``whatsapp``      : jembatan API bot WA (chat, pesan, arsip, format, status).
- ``bot_control``   : kontrol proses bot WA + daftar upload Drive.
- ``android``       : kontrol perangkat Android via scrcpy.
- ``database_query``: query SQL read-only ke SQLite lokal.
"""

from alfa.core import database
from alfa.core.runtime_ctx import get_current_chat_id, get_current_user_id
from alfa.tools.system.integrations._api import WA_BOT_URL, _wa_api
from alfa.tools.system.integrations.android import scrcpy_android_control
from alfa.tools.system.integrations.bot_control import (
    list_wa_drive_uploads,
    manage_wa_sheets_bot,
)
from alfa.tools.system.integrations.database_query import query_database
from alfa.tools.system.integrations.productivity import (
    generate_secure_password,
    schedule_reminder,
    start_focus_session,
)
from alfa.tools.system.integrations.whatsapp import (
    wa_add_format,
    wa_clear_history,
    wa_delete_format,
    wa_get_chats,
    wa_get_history_archive,
    wa_get_incoming,
    wa_get_me,
    wa_get_messages,
    wa_get_records,
    wa_list_formats,
    wa_mark_read,
    wa_post_status,
    wa_search_messages,
    wa_send_message,
    wa_toggle_format,
)

__all__ = [
    "WA_BOT_URL",
    "_wa_api",
    "database",
    "generate_secure_password",
    "get_current_chat_id",
    "get_current_user_id",
    "list_wa_drive_uploads",
    "manage_wa_sheets_bot",
    "query_database",
    "schedule_reminder",
    "scrcpy_android_control",
    "start_focus_session",
    "wa_add_format",
    "wa_clear_history",
    "wa_delete_format",
    "wa_get_chats",
    "wa_get_history_archive",
    "wa_get_incoming",
    "wa_get_me",
    "wa_get_messages",
    "wa_get_records",
    "wa_list_formats",
    "wa_mark_read",
    "wa_post_status",
    "wa_search_messages",
    "wa_send_message",
    "wa_toggle_format",
]
