"""Callback Query Handler for Inline Buttons."""

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from telegram.ext import ContextTypes
    from telegram import Update

logger = logging.getLogger(__name__)


async def handle_callback_query(update: "Update", context: "ContextTypes.DEFAULT_TYPE"):
    """Handle inline button callback queries."""
    from bot import (
        is_authorized,
        safe_send_message,
        get_system_stats,
    )
    import database
    
    query = update.callback_query
    user_id = query.from_user.id
    
    if not is_authorized(user_id):
        await query.answer("⛔ Akses ditolak", show_alert=True)
        return
    
    await query.answer()  # Acknowledge callback
    
    chat_id = query.message.chat_id
    data = query.data
    
    if data == "btn_stats":
        stats = get_system_stats()
        stats_text = (
            f"📊 **System Stats**\n\n"
            f"CPU: {stats['cpu_percent']:.1f}%\n"
            f"RAM: {stats['memory_used_gb']:.2f}GB / {stats['memory_total_gb']:.2f}GB\n"
            f"Disk: {stats['disk_usage_percent']:.1f}%\n"
            f"Uptime: {stats['uptime_hours']:.1f}h"
        )
        await safe_send_message(context, chat_id, stats_text)
        
    elif data == "btn_memory":
        try:
            with database.get_sync_db() as conn:
                count = conn.execute(
                    "SELECT COUNT(*) FROM knowledge_memory WHERE user_id = ?",
                    (user_id,)
                ).fetchone()[0]
            await safe_send_message(
                context, 
                chat_id, 
                f"🧠 **Memori Anda**\n\nTotal: {count} memori tersimpan."
            )
        except Exception as e:
            logger.error(f"Error fetching memory count: {e}")
            await safe_send_message(context, chat_id, "🧠 Memori: Error mengambil data")
            
    elif data == "btn_clear":
        try:
            with database.get_sync_db() as conn:
                conn.execute("DELETE FROM messages WHERE user_id = ?", (user_id,))
                conn.commit()
            await safe_send_message(
                context, 
                chat_id, 
                "🧹 **Sesi dibersihkan**\n\nRiwayat percakapan telah direset."
            )
        except Exception as e:
            logger.error(f"Error clearing messages: {e}")
            await safe_send_message(context, chat_id, "❌ Error membersihkan sesi")
            
    elif data == "btn_toggle_voice":
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
                
            status = "✅ ON" if new_state else "❌ OFF"
            await safe_send_message(
                context,
                chat_id,
                f"🎙️ **Voice Mode:** {status}"
            )
        except Exception as e:
            logger.error(f"Error toggling voice: {e}")
            await safe_send_message(context, chat_id, "❌ Error mengubah voice mode")
            
    elif data == "btn_python_info":
        await safe_send_message(
            context,
            chat_id,
            "🐍 **Python Sandbox Info**\n\n"
            "Ketik kode Python langsung:\n"
            "```python\nprint('Hello World')\n```"
        )
        
    elif data == "btn_help":
        await safe_send_message(
            context,
            chat_id,
            "📖 **Bantuan & Tools**\n\n"
            "**Commands:**\n"
            "/start - Menu utama\n"
            "/stats - Statistik sistem\n"
            "/memory - Lihat memori\n"
            "/clear - Reset sesi\n"
            "/voice - Toggle voice mode\n\n"
            "**Tools:** Bash, Python, Web Search, File Operations, dll."
        )
