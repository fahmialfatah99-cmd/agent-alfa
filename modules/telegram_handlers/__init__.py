"""Telegram Handlers Module - Command and message handlers for ALFA bot."""

from .commands import (
    start_command,
    menu_command,
    cekagen_command,
    stats_command,
    memory_command,
    clear_command,
    id_command,
    voice_command,
    cron_command,
    proactive_command,
    wa_command,
    dashboard_command,
    keys_command,
    agents_command,
    rapat_command,
    swarm_command,
    resume_swarm_command,
)
from .message_handler import handle_text_message
from .media_handlers import (
    handle_voice_message,
    handle_photo_message,
    handle_document_message,
)
from .callback_handler import handle_callback_query
from .proactive_loops import (
    proactive_reminder_loop,
    proactive_cron_watchdog_loop,
    proactive_system_guardian_loop,
    proactive_focus_session_loop,
    proactive_ambient_agent_loop,
    proactive_ecosystem_watchdog_loop,
)

__all__ = [
    # Commands
    "start_command",
    "menu_command",
    "cekagen_command",
    "stats_command",
    "memory_command",
    "clear_command",
    "id_command",
    "voice_command",
    "cron_command",
    "proactive_command",
    "wa_command",
    "dashboard_command",
    "keys_command",
    "agents_command",
    "rapat_command",
    "swarm_command",
    "resume_swarm_command",
    # Message handlers
    "handle_text_message",
    # Media handlers
    "handle_voice_message",
    "handle_photo_message",
    "handle_document_message",
    # Callback
    "handle_callback_query",
    # Proactive loops
    "proactive_reminder_loop",
    "proactive_cron_watchdog_loop",
    "proactive_system_guardian_loop",
    "proactive_focus_session_loop",
    "proactive_ambient_agent_loop",
    "proactive_ecosystem_watchdog_loop",
]
