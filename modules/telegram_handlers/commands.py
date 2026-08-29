"""Telegram Command Handlers for ALFA Bot."""

import logging
from typing import TYPE_CHECKING

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, constants

if TYPE_CHECKING:
    from telegram.ext import ContextTypes
    from telegram import Update

logger = logging.getLogger(__name__)

# Imports will be resolved at runtime to avoid circular dependencies


async def start_command(update: "Update", context: "ContextTypes.DEFAULT_TYPE"):
    """Handle /start command."""
    from bot import is_authorized, safe_send_message
    
    user = update.effective_user
    chat_id = update.effective_chat.id
    if not is_authorized(user.id):
        await update.message.reply_text(
            f"⛔ *Akses Ditolak*\n\nID Anda: `{user.id}` belum terdaftar di whitelist bot.",
            parse_mode=constants.ParseMode.MARKDOWN
        )
        return

    keyboard = [
        [
            InlineKeyboardButton("📊 System Stats", callback_data="btn_stats"),
            InlineKeyboardButton("🧠 Memori", callback_data="btn_memory"),
        ],
        [
            InlineKeyboardButton("📈 Python Sandbox", callback_data="btn_python_info"),
            InlineKeyboardButton("🎙️ Toggle Voice", callback_data="btn_toggle_voice"),
        ],
        [
            InlineKeyboardButton("🧹 Reset Sesi", callback_data="btn_clear"),
            InlineKeyboardButton("📖 Bantuan & Tools", callback_data="btn_help"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    welcome_text = (
        f"🤖 **Personal Autonomous AI Agent**\n"
        f"Halo, **{user.first_name}**! Saya asisten AI otonom pribadi berbasis **Google Gemini API** yang terhubung langsung dengan mesin Linux Anda.\n\n"
        f"⚡ **Kemampuan & Tools Aktif (100% Real):**\n"
        f"• 🐍 **Python Sandbox & Data Plotter:** Eksekusi script & pembuatan grafik visual otomatis.\n"
        f"• 🖥️ **Desktop & Webcam Vision:** Screenshot layar desktop & snapshot webcam real-time.\n"
        f"• 🎙️ **Voice Notes (STT & TTS):** Kirim suara, AI membalas dengan suara natural Edge-TTS.\n"
        f"• 🌐 **Deep Web Intelligence:** DuckDuckGo search & ekstraksi konten artikel web.\n"
        f"• 🔍 **Workspace Intelligence:** Grep, find files, read/write file lokal.\n"
        f"• 🧠 **Persistent Long-Term Memory:** Memori permanen terisolasi per akun.\n"
        f"• ⏰ **Proactive Reminders:** Pengingat otomatis terjadwal.\n\n"
        f"Kirimkan pesan, pertanyaan, perintah bash, atau voice note langsung ke chat ini!"
    )
    await safe_send_message(context, chat_id, welcome_text, reply_markup=reply_markup)


async def menu_command(update: "Update", context: "ContextTypes.DEFAULT_TYPE"):
    """Handle /menu command - show interactive menu."""
    from bot import is_authorized, safe_send_message
    
    if not is_authorized(update.effective_user.id):
        return

    keyboard = [
        [InlineKeyboardButton("📊 Stats", callback_data="btn_stats")],
        [InlineKeyboardButton("🧠 Memory", callback_data="btn_memory")],
        [InlineKeyboardButton("🧹 Clear", callback_data="btn_clear")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await safe_send_message(
        context,
        update.effective_chat.id,
        "📋 **Menu Utama**\n\nPilih opsi di bawah:",
        reply_markup=reply_markup
    )


async def cekagen_command(update: "Update", context: "ContextTypes.DEFAULT_TYPE"):
    """Handle /cekagen command - check agent status."""
    from bot import is_authorized, safe_send_message, get_system_stats
    
    if not is_authorized(update.effective_user.id):
        return

    stats = get_system_stats()
    status_text = (
        f"🤖 **ALFA Agent Status**\n\n"
        f"📊 **System Resources:**\n"
        f"• CPU: {stats['cpu_percent']:.1f}%\n"
        f"• RAM: {stats['memory_used_gb']:.2f}GB / {stats['memory_total_gb']:.2f}GB ({stats['memory_percent']:.1f}%)\n"
        f"• Disk: {stats['disk_usage_percent']:.1f}%\n"
        f"• Uptime: {stats['uptime_hours']:.1f} jam\n\n"
        f"✅ Agent operational and ready."
    )
    await safe_send_message(context, update.effective_chat.id, status_text)


async def stats_command(update: "Update", context: "ContextTypes.DEFAULT_TYPE"):
    """Handle /stats command - show detailed statistics."""
    from bot import is_authorized, safe_send_message, get_system_stats
    import database
    
    if not is_authorized(update.effective_user.id):
        return

    stats = get_system_stats()
    user_id = update.effective_user.id
    
    try:
        with database.get_sync_db() as conn:
            msg_count = conn.execute(
                "SELECT COUNT(*) FROM messages WHERE user_id = ?", (user_id,)
            ).fetchone()[0]
            memory_count = conn.execute(
                "SELECT COUNT(*) FROM knowledge_memory WHERE user_id = ?", (user_id,)
            ).fetchone()[0]
    except Exception:
        msg_count = 0
        memory_count = 0

    stats_text = (
        f"📊 **System & Usage Statistics**\n\n"
        f"💻 **Hardware:**\n"
        f"• CPU Usage: {stats['cpu_percent']:.1f}%\n"
        f"• Memory: {stats['memory_used_gb']:.2f}GB / {stats['memory_total_gb']:.2f}GB\n"
        f"• Disk: {stats['disk_usage_percent']:.1f}%\n"
        f"• Network ↑{stats['network_sent_mb']:.1f}MB ↓{stats['network_recv_mb']:.1f}MB\n"
        f"• Uptime: {stats['uptime_hours']:.1f} hours\n"
        f"• Processes: {stats['process_count']}\n\n"
        f"📈 **Your Usage:**\n"
        f"• Messages: {msg_count}\n"
        f"• Memories: {memory_count}"
    )
    await safe_send_message(context, update.effective_chat.id, stats_text)


async def memory_command(update: "Update", context: "ContextTypes.DEFAULT_TYPE"):
    """Handle /memory command - show user's stored memories."""
    from bot import is_authorized, safe_send_message
    import database
    
    if not is_authorized(update.effective_user.id):
        return

    user_id = update.effective_user.id
    try:
        with database.get_sync_db() as conn:
            memories = conn.execute(
                "SELECT key_topic, content, category, created_at FROM knowledge_memory "
                "WHERE user_id = ? ORDER BY created_at DESC LIMIT 10",
                (user_id,)
            ).fetchall()
    except Exception as e:
        logger.error(f"Error fetching memories: {e}")
        memories = []

    if not memories:
        await safe_send_message(
            context,
            update.effective_chat.id,
            "🧠 **Memori Kosong**\n\nBelum ada memori yang tersimpan."
        )
        return

    memory_text = "🧠 **Memori Terbaru (10 terakhir)**\n\n"
    for topic, content, category, created_at in memories:
        preview = content[:80] + "..." if len(content) > 80 else content
        memory_text += f"• **{topic}** [{category}]\n  {preview}\n\n"

    await safe_send_message(context, update.effective_chat.id, memory_text)


async def clear_command(update: "Update", context: "ContextTypes.DEFAULT_TYPE"):
    """Handle /clear command - clear conversation history."""
    from bot import is_authorized, safe_send_message
    import database
    
    if not is_authorized(update.effective_user.id):
        return

    user_id = update.effective_user.id
    try:
        with database.get_sync_db() as conn:
            conn.execute("DELETE FROM messages WHERE user_id = ?", (user_id,))
            conn.commit()
    except Exception as e:
        logger.error(f"Error clearing messages: {e}")

    await safe_send_message(
        context,
        update.effective_chat.id,
        "🧹 **Sesi Dibersihkan**\n\nRiwayat percakapan telah direset."
    )


async def id_command(update: "Update", context: "ContextTypes.DEFAULT_TYPE"):
    """Handle /id command - show user ID."""
    user = update.effective_user
    await update.message.reply_text(
        f"🆔 **Your ID:** `{user.id}`\n"
        f"**Username:** @{user.username}\n"
        f"**Name:** {user.first_name} {user.last_name or ''}",
        parse_mode=constants.ParseMode.MARKDOWN
    )


async def voice_command(update: "Update", context: "ContextTypes.DEFAULT_TYPE"):
    """Handle /voice command - toggle voice response mode."""
    from bot import is_authorized, safe_send_message
    import database
    
    if not is_authorized(update.effective_user.id):
        return

    user_id = update.effective_user.id
    try:
        with database.get_sync_db() as conn:
            current = conn.execute(
                "SELECT voice_enabled FROM user_settings WHERE user_id = ?",
                (user_id,)
            ).fetchone()
            
            if current:
                new_state = not current[0]
                conn.execute(
                    "UPDATE user_settings SET voice_enabled = ? WHERE user_id = ?",
                    (new_state, user_id)
                )
            else:
                new_state = True
                conn.execute(
                    "INSERT INTO user_settings (user_id, voice_enabled) VALUES (?, ?)",
                    (user_id, True)
                )
            conn.commit()
    except Exception as e:
        logger.error(f"Error toggling voice setting: {e}")
        new_state = None

    if new_state is not None:
        status = "✅ ON" if new_state else "❌ OFF"
        await safe_send_message(
            context,
            update.effective_chat.id,
            f"🎙️ **Voice Mode:** {status}\n\nBalasan suara telah {'diaktifkan' if new_state else 'dinonaktifkan'}."
        )


async def cron_command(update: "Update", context: "ContextTypes.DEFAULT_TYPE"):
    """Handle /cron command - manage scheduled reminders."""
    from bot import is_authorized, safe_send_message
    
    if not is_authorized(update.effective_user.id):
        return

    # Implementation for cron management
    await safe_send_message(
        context,
        update.effective_chat.id,
        "⏰ **Cron Management**\n\nFitur manajemen reminder terjadwal.\n\n"
        "Gunakan: `/cron add <waktu> <pesan>` untuk menambah reminder"
    )


async def proactive_command(update: "Update", context: "ContextTypes.DEFAULT_TYPE"):
    """Handle /proactive command - configure proactive features."""
    from bot import is_authorized, safe_send_message
    
    if not is_authorized(update.effective_user.id):
        return

    await safe_send_message(
        context,
        update.effective_chat.id,
        "🔔 **Proactive Features**\n\n"
        "Fitur proactive agent dapat dikonfigurasi melalui dashboard web."
    )


async def wa_command(update: "Update", context: "ContextTypes.DEFAULT_TYPE"):
    """Handle /wa command - WhatsApp integration."""
    from bot import is_authorized, safe_send_message
    
    if not is_authorized(update.effective_user.id):
        return

    await safe_send_message(
        context,
        update.effective_chat.id,
        "📱 **WhatsApp Integration**\n\n"
        "Integrasi WhatsApp tersedia melalui plugin WA Sheets Bot."
    )


async def dashboard_command(update: "Update", context: "ContextTypes.DEFAULT_TYPE"):
    """Handle /dashboard command - show web dashboard info."""
    from bot import is_authorized, safe_send_message
    
    if not is_authorized(update.effective_user.id):
        return

    await safe_send_message(
        context,
        update.effective_chat.id,
        "🌐 **Web Dashboard**\n\n"
        "Akses dashboard: http://localhost:8080\n\n"
        "Dashboard menyediakan:\n"
        "• Monitoring real-time\n"
        "• Manajemen API keys\n"
        "• Konfigurasi agent\n"
        "• Token usage tracking"
    )


async def keys_command(update: "Update", context: "ContextTypes.DEFAULT_TYPE"):
    """Handle /keys command - manage API keys."""
    from bot import is_authorized, safe_send_message
    
    if not is_authorized(update.effective_user.id):
        return

    await safe_send_message(
        context,
        update.effective_chat.id,
        "🔑 **API Keys Management**\n\n"
        "Kelola API keys melalui:\n"
        "• Dashboard web: /dashboard\n"
        "• Vault commands: /vault"
    )


async def agents_command(update: "Update", context: "ContextTypes.DEFAULT_TYPE"):
    """Handle /agents command - list available agents."""
    from bot import is_authorized, safe_send_message
    
    if not is_authorized(update.effective_user.id):
        return

    await safe_send_message(
        context,
        update.effective_chat.id,
        "🤖 **Available Agents**\n\n"
        "• ALFA (Main Agent)\n"
        "• Security Auditor\n"
        "• Academic Researcher\n"
        "• Swarm Engine (Multi-Agent)"
    )


async def rapat_command(update: "Update", context: "ContextTypes.DEFAULT_TYPE"):
    """Handle /rapat command - start AI meeting."""
    from bot import is_authorized, safe_send_message
    
    if not is_authorized(update.effective_user.id):
        return

    await safe_send_message(
        context,
        update.effective_chat.id,
        "👥 **AI Meeting / Rapat**\n\n"
        "Mulai rapat AI dengan command:\n"
        "`/rapat <topik> --participants=<agent1,agent2> --rounds=2`"
    )


async def swarm_command(update: "Update", context: "ContextTypes.DEFAULT_TYPE"):
    """Handle /swarm command - start swarm collaboration."""
    from bot import is_authorized, safe_send_message
    
    if not is_authorized(update.effective_user.id):
        return

    await safe_send_message(
        context,
        update.effective_chat.id,
        "🐝 **Swarm Collaboration**\n\n"
        "Aktifkan kolaborasi multi-agent untuk tugas kompleks."
    )


async def resume_swarm_command(update: "Update", context: "ContextTypes.DEFAULT_TYPE"):
    """Handle /resume_swarm command - resume paused swarm."""
    from bot import is_authorized, safe_send_message
    
    if not is_authorized(update.effective_user.id):
        return

    await safe_send_message(
        context,
        update.effective_chat.id,
        "🐝 **Resume Swarm**\n\n"
        "Lanjutkan sesi swarm yang tertunda."
    )
