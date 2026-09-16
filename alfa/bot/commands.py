"""Telegram bot command handlers.

Facade aggregating basic and advanced bot commands.
"""

from alfa.bot.basic_commands import (
    _get_bot_module,
    _is_authorized,
    cekagen_command,
    clear_command,
    cron_command,
    id_command,
    memory_command,
    menu_command,
    proactive_command,
    start_command,
    stats_command,
    voice_command,
)
from alfa.bot.advanced_commands import (
    agents_command,
    dashboard_command,
    keys_command,
    rapat_command,
    resume_swarm_command,
    swarm_command,
    wa_command,
)

__all__ = [
    "_get_bot_module",
    "_is_authorized",
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
]
