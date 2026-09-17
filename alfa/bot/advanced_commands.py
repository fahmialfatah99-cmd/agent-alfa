"""Telegram bot command handlers."""

import json
import logging
import os
import sys

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
    WebAppInfo,
)
from telegram.ext import ContextTypes

from alfa import tools
from alfa.bot.config import is_authorized
from alfa.bot.helpers import safe_send_message
from alfa.core import database

logger = logging.getLogger("TelegramAIAgent")


def _get_bot_module():
    return sys.modules.get("alfa.bot.telegram_bot")


def _is_authorized(user_id: int) -> bool:
    mod = _get_bot_module()
    if mod and hasattr(mod, "is_authorized"):
        return mod.is_authorized(user_id)
    return is_authorized(user_id)


async def wa_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /wa or /washeets command to control WhatsApp Google Sheets Bot."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if not _is_authorized(user_id):
        return

    res = tools.manage_wa_sheets_bot("status")
    is_running = res.get("is_running", False)
    status_icon = "🟢 RUNNING (Aktif)" if is_running else "🔴 STOPPED (Mati)"

    wa_auth_status = "UNKNOWN"
    qr_str = ""
    status_file = os.path.expanduser("~/.alfa/wa_status.json")
    if os.path.exists(status_file):
        try:
            with open(status_file) as f:
                wa_data = json.load(f)
            wa_auth_status = wa_data.get("status", "UNKNOWN")
            qr_str = wa_data.get("qr", "")
        except Exception:
            pass

    keyboard = [
        [
            InlineKeyboardButton("🔄 Restart WA Bot", callback_data="btn_wa_restart"),
            InlineKeyboardButton("📊 Cek Status", callback_data="btn_wa_status"),
        ],
        [
            InlineKeyboardButton("▶️ Start WA Bot", callback_data="btn_wa_start"),
            InlineKeyboardButton("⏹️ Stop WA Bot", callback_data="btn_wa_stop"),
        ],
        [
            InlineKeyboardButton("🌐 Buka Web Dashboard", url="http://localhost:8080"),
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    auth_desc = (
        "✅ Terhubung (Logged In)"
        if wa_auth_status == "READY"
        else f"⚠️ {wa_auth_status} (Perlu Scan QR)"
    )

    text = (
        f"📱 **Manajer WhatsApp Google Sheets Bot:**\n\n"
        f"• **Status Layanan:** {status_icon}\n"
        f"• **Status Akun WA:** `{auth_desc}`\n"
        f"• **Auto-Start Saat Boot/Internet:** `{'Aktif 🟢' if res.get('enabled_on_boot') else 'Nonaktif 🔴'}`\n"
        f"• **Service Name:** `wa-sheets-bot.service`\n\n"
        f"💡 _Bot WhatsApp ini otomatis aktif saat laptop online dan diawasi 24/7 oleh Ecosystem Watchdog._"
    )

    if wa_auth_status == "QR_READY" and qr_str:
        try:
            import io

            import qrcode

            img = qrcode.make(qr_str)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            buf.seek(0)
            await context.bot.send_photo(
                chat_id=chat_id,
                photo=buf,
                caption=f"📲 **SCAN QR CODE WHATSAPP SEKARANG**\n\n{text}",
                reply_markup=reply_markup,
                parse_mode="Markdown",
            )
            return
        except Exception as e:
            logger.error(f"Failed to generate QR photo: {e}")

    await safe_send_message(context, chat_id, text, reply_markup=reply_markup)


async def dashboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /dashboard, /web, or /app command."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if not _is_authorized(user_id):
        return

    res = tools.open_web_dashboard(port=8080)
    tma_url = os.getenv(
        "ALFA_WEBAPP_URL", res.get("network_url") or "http://127.0.0.1:8080"
    )

    keyboard = []
    if tma_url and tma_url.startswith("https://"):
        keyboard.append(
            [
                InlineKeyboardButton(
                    "📱 Buka ALFA Mini App", web_app=WebAppInfo(url=tma_url)
                )
            ]
        )
    else:
        keyboard.append(
            [
                InlineKeyboardButton(
                    "🌐 Buka Web Dashboard",
                    url=res.get("local_url") or "http://127.0.0.1:8080",
                )
            ]
        )

    reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None

    text = (
        f"🛸 **ALFA SOVEREIGN COMMAND CENTER:**\n\n"
        f"• **Akses Lokal (Laptop):** `{res.get('local_url')}`\n"
        f"• **Akses Jaringan (HP / WiFi):** `{res.get('network_url')}`\n\n"
        f"⚡ **Pusat Kontrol Terintegrasi:**\n"
        f"1. 📊 Telemetri Hardware & CPU/RAM Real-time\n"
        f"2. ⚡ 130+ Tools Interaktif & Browser Otomatis\n"
        f"3. 🧠 Second Brain & Vector Memory\n"
        f"4. 🛡️ 24/7 System Guardian & Background Watchdogs\n"
        f"5. 💬 Web AI Interactive Console\n"
        f"6. 🤖 Ruang Rapat AI (Swarm Multi-Agent Engine)\n"
        f"7. 🔑 Multi-Provider Vault & API Keys Manager"
    )
    await safe_send_message(context, chat_id, text, reply_markup=reply_markup)


async def keys_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /keys command to manage API keys vault."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if not _is_authorized(user_id):
        return

    keys = database.list_api_keys_sync()
    if not keys:
        text = "🔑 **API Key Vault Kosong.** Tambahkan via Web Dashboard (http://localhost:8080) atau gunakan perintah tool."
    else:
        text = "🔑 **Multi-Provider API Key Vault:**\n\n"
        for k in keys:
            act = "🟢 *[ACTIVE]*" if k["is_active"] else "⚪"
            text += f"{act} **{k['name']}** (`{k['provider'].upper()}`)\n"
            text += f"   • Key: `{k['masked_key']}` | Model: `{k['default_model']}`\n\n"
        text += "💡 _Kelola, uji koneksi, & tambah key baru dengan mudah via Web Dashboard di tab API Key Vault._"
    await safe_send_message(context, chat_id, text)


async def agents_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /agents or /swarm command to view autonomous AI workforce."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if not _is_authorized(user_id):
        return

    agents = database.list_custom_agents_sync()
    if not agents:
        text = "🤖 **Belum ada AI Agent terdaftar.**"
    else:
        text = "🤖 **ALFA Autonomous AI Agent Workforce:**\n\n"
        for a in agents:
            status = "🟢 Aktif" if a.get("is_enabled", 1) else "🔴 Nonaktif"
            text += f"{a.get('avatar_emoji', '🤖')} **{a['name']}** ({status})\n"
            text += f"   • Role: *{a['role']}*\n"
            text += f"   • Model: `{a['provider']}/{a['model']}`\n\n"
        text += "💡 _Mulai rapat antar agent dengan perintah `/rapat <topik>` atau via Web Dashboard!_"
    await safe_send_message(context, chat_id, text)


async def rapat_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /rapat or /meeting command to conduct an autonomous round-table meeting (Plan Mode)."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if not _is_authorized(user_id):
        return

    topic = " ".join(context.args).strip() if context.args else ""
    if not topic:
        text = (
            "🏛️ **Panduan Ruang Rapat AI (Mode 1: Plan):**\n\n"
            "Format: `/rapat <topik / masalah yang ingin dibahas>`\n\n"
            "**Contoh:**\n"
            "• `/rapat Desain arsitektur database baru untuk auto-sync WhatsApp ke cloud`\n"
            "• `/rapat Strategi meningkatkan performa agent bot dan penghematan token API`\n\n"
            "💡 _Para agent akan berdebat, berdiskusi, dan merumuskan Action Plan!_\n"
            "⚡ _Untuk menyuruh agent langsung bekerja & mengeksekusi tugas nyata, gunakan `/swarm <perintah>`!_"
        )
        await safe_send_message(context, chat_id, text)
        return

    await safe_send_message(
        context,
        chat_id,
        f"🏛️ **Membuka Rapat Perencanaan AI...**\n\n"
        f"📋 **Agenda:** _{topic}_\n"
        f"👥 Memanggil para agent spesialis untuk memulai diskusi round-table. Mohon tunggu...",
    )

    try:
        from alfa.swarm import engine as swarm_engine

        result = await swarm_engine.conduct_multi_agent_meeting(
            topic=topic, rounds=2, mode="plan"
        )

        transcript = result.get("dialogue_transcript", [])
        dialogue_text = "🗣️ **Transkrip Diskusi Antar Agent:**\n\n"
        for d in transcript[:6]:
            dialogue_text += f"{d.get('avatar_emoji', '🤖')} **{d['agent_name']}** ({d['role']}):\n{d['message'][:350]}...\n\n"

        await safe_send_message(context, chat_id, dialogue_text)

        final_text = (
            f"🎯 **KONSENSUS & KEPUTUSAN RAPAT:**\n\n"
            f"{result.get('consensus', '')}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📋 **ACTION PLAN / LANGKAH KERJA:**\n\n"
            f"{result.get('action_plan', '')}\n\n"
            f"🌐 _Transkrip lengkap tersimpan di Web Dashboard (ID: #{result.get('meeting_id')})_"
        )
        await safe_send_message(context, chat_id, final_text)

    except Exception as e:
        logger.error(f"Error during Telegram /rapat meeting: {e}")
        await safe_send_message(
            context, chat_id, f"❌ Terjadi kesalahan saat rapat agent: {str(e)}"
        )


async def swarm_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /swarm or /eksekusi command to trigger live collaborative tool execution (Execute Mode)."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if not _is_authorized(user_id):
        return

    topic = " ".join(context.args).strip() if context.args else ""
    if not topic:
        text = (
            "⚡ **Panduan Swarm Eksekusi Langsung (Mode 2: Bekerja Nyata):**\n\n"
            "Format: `/swarm <perintah / tugas nyata yang ingin dikerjakan bersama>`\n\n"
            "**Contoh:**\n"
            "• `/swarm Scrape 20 mouse gaming terlaris di Shopee & Tokopedia dan buatkan CSV-nya`\n"
            "• `/swarm Buatkan script Python monitoring RAM/CPU dan jalankan di sandbox`\n"
            "• `/swarm Audit port lokal dan status keamanan server`\n\n"
            "💡 _Seluruh tim agen AI akan langsung membagi tugas, menjalankan tools live, dan mengirimkan file hasil ke Telegram kamu!_"
        )
        await safe_send_message(context, chat_id, text)
        return

    await safe_send_message(
        context,
        chat_id,
        f"⚡ **Membangunkan AI Swarm & Mengeksekusi Tugas Nyata...**\n\n"
        f"📌 **Tugas:** _{topic}_\n"
        f"🛠️ Alpha Lead, Researcher Prime, Code Crafter, dan Cyber Sentry sedang mengeksekusi tools. Mohon tunggu...",
    )

    try:
        from alfa.swarm import engine as swarm_engine

        result = await swarm_engine.conduct_multi_agent_meeting(
            topic=topic, rounds=1, mode="execute"
        )

        steps = result.get("execution_results", [])
        steps_text = "⚡ **Laporan Eksekusi Tiap Agen:**\n\n"
        for s in steps:
            steps_text += (
                f"{s.get('avatar_emoji', '🤖')} **{s['agent_name']}** ({s['role']})\n"
            )
            steps_text += f"   • Tool: `{s['tool_used']}` ({s['duration_ms']}ms)\n"
            steps_text += f"   • Output: _{s['execution_summary'][:200]}_\n\n"

        await safe_send_message(context, chat_id, steps_text)

        final_text = (
            f"🏆 **LAPORAN HASIL EKSEKUSI NYATA:**\n\n"
            f"{result.get('consensus', '')}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🌐 _ID Sesi: #{result.get('meeting_id')} • Tersimpan di Web Dashboard & Dokumen_"
        )
        await safe_send_message(context, chat_id, final_text)

        for s in steps:
            fpath = s.get("deliverable_file")
            if fpath and os.path.exists(fpath):
                try:
                    with open(fpath, "rb") as f_doc:
                        await context.bot.send_document(
                            chat_id=chat_id,
                            document=f_doc,
                            filename=os.path.basename(fpath),
                            caption=f"📁 **File Deliverable Hasil Swarm ({s['agent_name']}):**\n`{os.path.basename(fpath)}`",
                        )
                except Exception as file_err:
                    logger.warning(
                        f"Failed to send deliverable file to Telegram: {file_err}"
                    )

    except Exception as e:
        logger.error(f"Error during Telegram /swarm execution: {e}")
        await safe_send_message(
            context, chat_id, f"❌ Terjadi kesalahan saat eksekusi swarm: {str(e)}"
        )


async def resume_swarm_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /resume_swarm or /resume to resume an interrupted/cancelled swarm session."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if not _is_authorized(user_id):
        return

    from alfa.swarm.checkpoint import SwarmCheckpoint

    resumable = SwarmCheckpoint.list_resumable()

    session_id = (context.args[0].strip()) if context.args else ""
    if not session_id:
        if not resumable:
            await safe_send_message(
                context,
                chat_id,
                "ℹ️ Tidak ada sesi swarm yang tertunda atau bisa dilanjutkan saat ini.",
            )
            return

        text = "🔄 **Daftar Sesi Swarm yang Bisa Dilanjutkan (Checkpoints):**\n\n"
        for r in resumable[:5]:
            text += (
                f"• `{r['session_id']}` [{r['status'].upper()}]\n"
                f"  📌 Topik: _{r['topic']}_\n"
                f"  📊 Progres: {r['steps_done']}/{r['steps_total']} langkah\n"
                f"  🕒 Update: `{r['updated_at'][:19]}`\n\n"
            )
        text += "Gunakan `/resume <session_id>` untuk melanjutkan sesi."
        await safe_send_message(context, chat_id, text)
        return

    await safe_send_message(
        context,
        chat_id,
        f"🔄 **Melanjutkan sesi swarm `{session_id}` dari checkpoint...**",
    )
    try:
        from alfa.swarm import engine as swarm_engine

        result = await swarm_engine.resume_swarm_session(session_id)
        if result.get("status") == "error":
            await safe_send_message(
                context,
                chat_id,
                f"❌ Gagal resume: {result.get('message', 'Unknown error')}",
            )
            return

        steps = result.get("execution_results", [])
        steps_text = "⚡ **Hasil Lanjutan Sesi Swarm:**\n\n"
        for s in steps:
            steps_text += (
                f"{s.get('avatar_emoji', '🤖')} **{s['agent_name']}** ({s['role']})\n"
            )
            steps_text += f"   • Tool: `{s['tool_used']}`\n"
            steps_text += f"   • Output: _{s['execution_summary'][:200]}_\n\n"
        await safe_send_message(context, chat_id, steps_text)

        final_text = (
            f"🏆 **LAPORAN HASIL LANJUTAN EKSEKUSI:**\n\n"
            f"{result.get('consensus', '')}"
        )
        await safe_send_message(context, chat_id, final_text)
    except Exception as e:
        logger.error(f"Error during /resume_swarm: {e}")
        await safe_send_message(
            context, chat_id, f"❌ Terjadi kesalahan saat resume: {str(e)}"
        )
