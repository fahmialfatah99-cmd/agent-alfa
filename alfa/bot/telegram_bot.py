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
import sys
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from alfa.core import database
from alfa.core import brain as main_brain
from alfa.core import permissions as permission_gate
import plugins
import token_usage
from alfa import tools
from alfa.tools import (
    AVAILABLE_TOOLS,
    SANDBOX_DIR,
    current_chat_id_var,
    current_user_id_var,
    get_system_stats,
)
import tts_engine

# Re-export all symbols from submodules for complete backward compatibility
from alfa.bot.config import *  # noqa: F401, F403
from alfa.bot.config import (
    ALLOWED_USER_IDS,
    ALFA_PROMPT_PATH,
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

from alfa.bot.streamer import TelegramStreamer  # noqa: F401

from alfa.bot.turn_executor import run_agent_turn  # noqa: F401

from alfa.bot.handlers import *  # noqa: F401, F403
from alfa.bot.handlers import (
    check_and_send_media_artifacts,
    handle_callback_query,
    handle_document_message,
    handle_photo_message,
    handle_text_message,
    handle_voice_message,
)

from alfa.bot.commands import *  # noqa: F401, F403
from alfa.bot.commands import (
    agents_command,
    cekagen_command,
    clear_command,
    cron_command,
    dashboard_command,
    id_command,
    keys_command,
    memory_command,
    menu_command,
    proactive_command,
    rapat_command,
    resume_swarm_command,
    start_command,
    stats_command,
    swarm_command,
    voice_command,
    wa_command,
)

from alfa.bot.proactive import *  # noqa: F401, F403
from alfa.bot.proactive import (
    proactive_ambient_agent_loop,
    proactive_cron_watchdog_loop,
    proactive_ecosystem_watchdog_loop,
    proactive_focus_session_loop,
    proactive_reminder_loop,
    proactive_system_guardian_loop,
)

logger = logging.getLogger("TelegramAIAgent")


async def post_init(application: Application):
    """Post initialization hook."""
    await database.init_db()

    # Connect Subagent swarm to Telegram app instance
    import subagents
    subagents.set_telegram_app(application)

    # Start background dispatchers
    asyncio.create_task(proactive_reminder_loop(application))
    asyncio.create_task(proactive_cron_watchdog_loop(application))
    asyncio.create_task(proactive_system_guardian_loop(application))
    asyncio.create_task(proactive_focus_session_loop(application))
    asyncio.create_task(proactive_ambient_agent_loop(application))
    asyncio.create_task(proactive_ecosystem_watchdog_loop(application))


def main():
    """Main application launcher."""
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
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("cekagen", cekagen_command))
    application.add_handler(CommandHandler("memory", memory_command))
    application.add_handler(CommandHandler("cron", cron_command))
    application.add_handler(CommandHandler("tasks", cron_command))
    application.add_handler(CommandHandler("proactive", proactive_command))
    application.add_handler(CommandHandler("keys", keys_command))
    application.add_handler(CommandHandler("vault", keys_command))
    application.add_handler(CommandHandler("agents", agents_command))
    application.add_handler(CommandHandler("swarm", swarm_command))
    application.add_handler(CommandHandler("eksekusi", swarm_command))
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
    application.add_handler(CallbackQueryHandler(
        permission_gate.handle_permission_callback, pattern=r"^perm(\|.*|_done)$"))
    application.add_handler(CallbackQueryHandler(handle_callback_query))

    # Multimodal message handlers
    application.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_voice_message))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo_message))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document_message))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))

    logger.info("Bot Telegram Otonom siap melayani! Menunggu interaksi...")
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
