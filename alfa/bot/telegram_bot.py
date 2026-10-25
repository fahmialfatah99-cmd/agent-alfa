#!/usr/bin/env python3
"""
Ultra-Advanced Telegram AI Agent Bot (Surpassing Hermes Agent & OpenClaw)
Powered by Google Gemini API & Autonomous Real Tool Execution.

This module acts as the unified facade and application launcher, re-exporting
all components from specialized submodules:
- config: Configuration, system prompts, Gemini client resolution
- helpers: Text splitting, formatting, safe message delivery
- streamer: TelegramStreamer progressive streaming response engine
- turn_executor: Autonomous multi-step agent turn engine
- handlers: Message, voice, document, photo, and callback query handlers
- commands: Bot slash-commands
- proactive: 24/7 proactive reminder, cron, guardian, and ambient loops
"""

import asyncio
import logging
import os
import sys

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import plugins
from alfa import tools
from alfa.bot.commands import *  # noqa: F401, F403
from alfa.bot.commands import (
    agents_command,
    budget_command,
    cancel_command,
    cekagen_command,
    clear_command,
    cloud_command,
    cron_command,
    dashboard_command,
    drive_command,
    id_command,
    keys_command,
    memory_command,
    menu_command,
    mode_command,
    persona_command,
    pipeline_command,
    proactive_command,
    ram_command,
    rapat_command,
    resume_swarm_command,
    setsheet_command,
    sheets_command,
    single_command,
    sites_command,
    skills_command,
    start_command,
    stats_command,
    status_command,
    swarm_command,
    tools_command,
    tugas_command,
    voice_command,
    wa_command,
    wacari_command,
    wachat_command,
    waformat_command,
    wakirim_command,
    wamasuk_command,
    wareport_command,
    waringkas_command,
)

# Re-export all symbols from submodules for complete backward compatibility
from alfa.bot.config import *  # noqa: F401, F403
from alfa.bot.config import (
    ALFA_PROMPT_PATH,
    ALLOWED_USER_IDS,
    ANTIGRAVITY_WORKFLOW_BLOCK,
    AUDIT_CORRECTION_TEXT,
    BASE_SYSTEM_PROMPT,
    CAPABILITIES_BLOCK,
    CODING_DELIVERY_BLOCK,
    ENFORCEMENT_BLOCK,
    ENV_SYSTEM_INSTRUCTION,
    GEMINI_API_KEY,
    GEMINI_MODEL,
    MEETING_FABRICATION_MARKERS,
    MEETING_INTENT_KEYWORDS,
    OWNER_NAME,
    REPO_ROOT,
    SUPERPOWERS_SKILLS_BLOCK,
    TELEGRAM_BOT_TOKEN,
    TOOL_FIRST_EXECUTION_BLOCK,
    UI_UX_PRO_MAX_BLOCK,
    _gemini_client_cache,
    _main_brain_gemini_model,
    gemini_client,
    is_authorized,
    resolve_main_gemini,
)
from alfa.bot.handlers import *  # noqa: F401, F403
from alfa.bot.handlers import (
    check_and_send_media_artifacts,
    handle_callback_query,
    handle_document_message,
    handle_photo_message,
    handle_text_message,
    handle_voice_message,
)
from alfa.bot.helpers import *  # noqa: F401, F403
from alfa.bot.helpers import (
    ARTIFACT_DIRS,
    ARTIFACT_NOUNS,
    COMPLETION_VERBS,
    _artifact_signature,
    _meetings_count,
    safe_send_message,
    send_typing_loop,
    should_reply_with_text_instead_of_voice,
    split_message,
)
from alfa.bot.proactive import *  # noqa: F401, F403
from alfa.bot.proactive import (
    proactive_ambient_agent_loop,
    proactive_cron_watchdog_loop,
    proactive_ecosystem_watchdog_loop,
    proactive_focus_session_loop,
    proactive_reminder_loop,
    proactive_sites_watch_loop,
    proactive_system_guardian_loop,
    proactive_wa_digest_loop,
)
from alfa.bot.streamer import TelegramStreamer  # noqa: F401
from alfa.bot.turn_executor import run_agent_turn  # noqa: F401
from alfa.core import brain as main_brain
from alfa.core import database
from alfa.core import permissions as permission_gate
from alfa.core import token_usage as token_usage
from alfa.media import tts_engine as tts_engine
from alfa.tools import (
    AVAILABLE_TOOLS,
    SANDBOX_DIR,
    current_chat_id_var,
    current_user_id_var,
    get_system_stats,
)
from alfa.tools.system.guardian import guardian_wa_watchdog_loop

logger = logging.getLogger("TelegramAIAgent")


_proactive_tasks: list[asyncio.Task] = []


async def post_init(application: Application):
    """Post initialization hook."""
    await database.init_db()

    # Connect Subagent swarm to Telegram app instance
    from alfa.swarm import subagents as subagents

    subagents.set_telegram_app(application)

    # Daftarkan daftar slash command agar muncul di autocomplete Telegram
    try:
        from telegram import BotCommand

        await application.bot.set_my_commands(
            [
                BotCommand("start", "Mulai & sambutan"),
                BotCommand("menu", "Panel kontrol lengkap"),
                BotCommand("help", "Semua perintah"),
                BotCommand("mode", "Alih mode single|swarm"),
                BotCommand("single", "Single agent (pindah/eksekusi)"),
                BotCommand("swarm", "Misi swarm multi-agen"),
                BotCommand("rapat", "Rapat plan antar-agen"),
                BotCommand("resume", "Lanjutkan sesi swarm"),
                BotCommand("cancel", "Hentikan misi swarm"),
                BotCommand("status", "Status mode & sistem"),
                BotCommand("agents", "Daftar agen swarm"),
                BotCommand("persona", "Ganti persona single-mode"),
                BotCommand("tools", "Daftar tools aktif"),
                BotCommand("pipeline", "Workflow pipeline"),
                BotCommand("tugas", "Tugas latar & checkpoint"),
                BotCommand("keys", "API key vault"),
                BotCommand("cekagen", "Audit konfigurasi agen"),
                BotCommand("cron", "Tugas berulang"),
                BotCommand("budget", "Kuota token harian"),
                BotCommand("proactive", "Inisiatif ambient"),
                BotCommand("stats", "Statistik server"),
                BotCommand("memory", "Memori jangka panjang"),
                BotCommand("dashboard", "Command center web"),
                BotCommand("sites", "Galeri & hidupkan situs"),
                BotCommand("wa", "Bot WhatsApp Sheets"),
                BotCommand("meeting", "Rapat plan (alias)"),
                BotCommand("eksekusi", "Swarm execute (alias)"),
                BotCommand("tasks", "Tugas berulang (alias)"),
                BotCommand("vault", "API vault (alias)"),
                BotCommand("stop", "Hentikan swarm (alias)"),
                BotCommand("web", "Dashboard (alias)"),
                BotCommand("app", "Dashboard (alias)"),
                BotCommand("washeets", "Bot WA Sheets (alias)"),
                BotCommand("sheets", "Lihat file & tab Google Sheets"),
                BotCommand("drive", "Lihat file Google Drive & mount"),
                BotCommand("cloud", "Hub Google Sheets & Drive"),
                BotCommand("setsheet", "Setel Google Sheets material"),
                BotCommand("batal", "Batalkan misi (alias)"),
                BotCommand("resume_swarm", "Lanjut swarm (alias)"),
                BotCommand("reset", "Reset konteks (alias)"),
                BotCommand("wachat", "Baca chat WhatsApp"),
                BotCommand("wamasuk", "Pesan WA masuk terbaru"),
                BotCommand("wakirim", "Kirim pesan WhatsApp"),
                BotCommand("waringkas", "Digest cerdas WA"),
                BotCommand("wacari", "Cari pesan WhatsApp"),
                BotCommand("waformat", "Atur format pencatatan WA"),
                BotCommand("wareport", "Baca laporan WA terekam"),
                BotCommand("voice", "Toggle balasan suara"),
                BotCommand("ram", "Pantau & optimasi RAM bot/WA"),
                BotCommand("bersihkan", "Bersihkan memori & cache"),
                BotCommand("clear", "Reset riwayat chat"),
                BotCommand("id", "ID Telegram & chat"),
            ]
        )
    except Exception as cmd_err:
        logger.warning(f"set_my_commands gagal: {cmd_err}")

    # Clean up any stale media/charts in sandbox on startup
    if os.path.exists(SANDBOX_DIR):
        for fname in os.listdir(SANDBOX_DIR):
            fpath = os.path.join(SANDBOX_DIR, fname)
            if os.path.isfile(fpath):
                ext = os.path.splitext(fname)[1].lower()
                if (
                    ext in [".png", ".jpg", ".jpeg", ".webp"]
                    or fname.startswith("generated_plot")
                    or fname == "dataset_analysis_chart.png"
                ):
                    try:
                        os.remove(fpath)
                    except OSError:
                        pass

    # Start background dispatchers
    global _proactive_tasks
    _proactive_tasks = [
        asyncio.create_task(proactive_reminder_loop(application)),
        asyncio.create_task(proactive_sites_watch_loop(application)),
        asyncio.create_task(proactive_cron_watchdog_loop(application)),
        asyncio.create_task(proactive_wa_digest_loop(application)),
        asyncio.create_task(proactive_system_guardian_loop(application)),
        asyncio.create_task(proactive_focus_session_loop(application)),
        asyncio.create_task(proactive_ambient_agent_loop(application)),
        asyncio.create_task(proactive_ecosystem_watchdog_loop(application)),
        asyncio.create_task(guardian_wa_watchdog_loop(application)),
    ]


async def post_shutdown(application: Application):
    """Graceful shutdown hook to cancel background tasks cleanly."""
    global _proactive_tasks
    for task in _proactive_tasks:
        if not task.done():
            task.cancel()
    if _proactive_tasks:
        await asyncio.gather(*_proactive_tasks, return_exceptions=True)
    _proactive_tasks.clear()


def main():
    """Main application launcher."""
    from alfa.core.security_boot_guard import check_runtime_security

    check_runtime_security("telegram-bot")

    if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "your_telegram_bot_token_here":
        logger.critical("TELEGRAM_BOT_TOKEN belum disetel di .env!")
        sys.exit(1)

    if not GEMINI_API_KEY or GEMINI_API_KEY == "your_gemini_api_key_here":
        logger.warning("GEMINI_API_KEY belum diisi di .env.")

    logger.info("Menginisialisasi Ultra-Advanced Telegram AI Agent Bot...")
    application = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .concurrent_updates(True)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    # Command handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("menu", menu_command))
    application.add_handler(CommandHandler("dashboard", dashboard_command))
    application.add_handler(CommandHandler("web", dashboard_command))
    application.add_handler(CommandHandler("app", dashboard_command))
    application.add_handler(CommandHandler("wa", wa_command))
    application.add_handler(CommandHandler("washeets", wa_command))
    application.add_handler(CommandHandler("setsheet", setsheet_command))
    application.add_handler(CommandHandler("sheets", sheets_command))
    application.add_handler(CommandHandler("sheet", sheets_command))
    application.add_handler(CommandHandler("drive", drive_command))
    application.add_handler(CommandHandler("gdrive", drive_command))
    application.add_handler(CommandHandler("cloud", cloud_command))
    application.add_handler(CommandHandler("wachat", wachat_command))
    application.add_handler(CommandHandler("wamasuk", wamasuk_command))
    application.add_handler(CommandHandler("wakirim", wakirim_command))
    application.add_handler(CommandHandler("wacari", wacari_command))
    application.add_handler(CommandHandler("waformat", waformat_command))
    application.add_handler(CommandHandler("wareport", wareport_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("ram", ram_command))
    application.add_handler(CommandHandler("bersihkan", ram_command))
    application.add_handler(CommandHandler("cekagen", cekagen_command))
    application.add_handler(CommandHandler("memory", memory_command))
    application.add_handler(CommandHandler("skills", skills_command))
    application.add_handler(CommandHandler("learn", skills_command))
    application.add_handler(CommandHandler("cron", cron_command))
    application.add_handler(CommandHandler("tasks", cron_command))
    application.add_handler(CommandHandler("budget", budget_command))
    application.add_handler(CommandHandler("waringkas", waringkas_command))
    application.add_handler(CommandHandler("proactive", proactive_command))
    application.add_handler(CommandHandler("keys", keys_command))
    application.add_handler(CommandHandler("vault", keys_command))
    application.add_handler(CommandHandler("agents", agents_command))
    application.add_handler(CommandHandler("persona", persona_command))
    application.add_handler(CommandHandler("tools", tools_command))
    application.add_handler(CommandHandler("swarm", swarm_command))
    application.add_handler(CommandHandler("sites", sites_command))
    application.add_handler(CommandHandler("eksekusi", swarm_command))
    application.add_handler(CommandHandler("mode", mode_command))
    application.add_handler(CommandHandler("single", single_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("cancel", cancel_command))
    application.add_handler(CommandHandler("stop", cancel_command))
    application.add_handler(CommandHandler("batal", cancel_command))
    application.add_handler(CommandHandler("pipeline", pipeline_command))
    application.add_handler(CommandHandler("tugas", tugas_command))
    application.add_handler(CommandHandler("resume_swarm", resume_swarm_command))
    application.add_handler(CommandHandler("resume", resume_swarm_command))
    application.add_handler(CommandHandler("rapat", rapat_command))
    application.add_handler(CommandHandler("meeting", rapat_command))
    application.add_handler(CommandHandler("clear", clear_command))
    application.add_handler(CommandHandler("reset", clear_command))
    application.add_handler(CommandHandler("id", id_command))
    application.add_handler(CommandHandler("voice", voice_command))
    application.add_handler(CommandHandler("help", start_command))

    # Callback Query (Buttons)
    application.add_handler(
        CallbackQueryHandler(
            permission_gate.handle_permission_callback, pattern=r"^perm(\|.*|_done)$"
        )
    )
    application.add_handler(CallbackQueryHandler(handle_callback_query))

    # Multimodal message handlers
    application.add_handler(
        MessageHandler(filters.VOICE | filters.AUDIO, handle_voice_message)
    )
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo_message))
    application.add_handler(
        MessageHandler(filters.Document.ALL, handle_document_message)
    )
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message)
    )

    async def _on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        logger.error("Exception while handling an update:", exc_info=context.error)
        if hasattr(update, "effective_chat") and getattr(update, "effective_chat", None):
            try:
                await safe_send_message(
                    context,
                    update.effective_chat.id,
                    f"⚠️ Terjadi kendala saat memproses permintaan:\n`{context.error}`",
                )
            except (TelegramError, OSError):
                pass

    application.add_error_handler(_on_error)

    logger.info("Bot Telegram Otonom siap melayani! Menunggu interaksi...")
    application.run_polling(drop_pending_updates=True)


# ── Sambungkan notification port agar lapisan tools tak perlu impor alfa.bot ─
async def _notify_safe_send(app, chat_id, text, reply_markup=None):
    """Adapter port→helper bot; impor lazy supaya siklus modul tetap putus."""

    return await safe_send_message(app, chat_id, text, reply_markup)


def _notify_swarm_templates() -> dict:
    from alfa.bot.mode_commands import SWARM_TEMPLATES

    return SWARM_TEMPLATES


try:
    from alfa.core import notification as _notification_port

    _notification_port.register_send_message(_notify_safe_send)
    _notification_port.register_swarm_templates(_notify_swarm_templates)
except Exception:  # pragma: no cover — port opsional saat sandingan berubah
    pass


if __name__ == "__main__":
    main()

