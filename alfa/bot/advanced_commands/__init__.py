"""Perintah lanjutan bot Telegram ALFA.

Pecah dari modul monolitik `advanced_commands.py` (1.464 baris) menjadi
sub-modul per tanggung jawab. **Import path publik tidak berubah** — semua
simbol tetap di-import dari `alfa.bot.advanced_commands`.

Sub-modul:
- `_common` : akses modul bot, otorisasi user, konstanta error.
- `_compat` : akses dinamis agar patch/mock pada paket tetap berlaku.
- `wa`      : perintah WhatsApp.
- `sites`   : perintah & callback /sites.
- `commands`: perintah umum bot.
"""

from alfa.bot.advanced_commands._common import (
    _ADV_ERR,
    _get_bot_module,
    _is_authorized,
)
from alfa.bot.advanced_commands.commands import (
    agents_command,
    apex_command,
    dashboard_command,
    keys_command,
    ram_command,
    rapat_command,
    resume_swarm_command,
    setsheet_command,
    skills_command,
    swarm_command,
)
from alfa.bot.advanced_commands.sites import (
    handle_sites_callback,
    sites_command,
)
from alfa.bot.advanced_commands.wa import (
    _WA_TYPE_ICON,
    _wa_esc,
    _wa_not_ready,
    _wa_sender,
    _wa_time,
    _wa_time_iso,
    wa_command,
    wacari_command,
    wachat_command,
    waformat_command,
    wakirim_command,
    wamasuk_command,
    wareport_command,
    waringkas_command,
)
from alfa.bot.config import is_authorized
from alfa.bot.helpers import safe_send_message

__all__ = [
    "_ADV_ERR",
    "_WA_TYPE_ICON",
    "_wa_esc",
    "_wa_not_ready",
    "_wa_sender",
    "_wa_time",
    "_wa_time_iso",
    "_get_bot_module",
    "_is_authorized",
    "agents_command",
    "apex_command",
    "dashboard_command",
    "handle_sites_callback",
    "is_authorized",
    "keys_command",
    "rapat_command",
    "ram_command",
    "resume_swarm_command",
    "safe_send_message",
    "setsheet_command",
    "sites_command",
    "skills_command",
    "swarm_command",
    "wa_command",
    "wacari_command",
    "waformat_command",
    "wachat_command",
    "wamasuk_command",
    "wareport_command",
    "waringkas_command",
    "wakirim_command",
]
