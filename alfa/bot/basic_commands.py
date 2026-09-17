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
    constants,
)
from telegram.ext import ContextTypes

from alfa import tools
from alfa.bot.config import is_authorized
from alfa.bot.helpers import safe_send_message
from alfa.core import database
from alfa.tools import get_system_stats

logger = logging.getLogger("TelegramAIAgent")


def _get_bot_module():
    return sys.modules.get("alfa.bot.telegram_bot")


def _is_authorized(user_id: int) -> bool:
    mod = _get_bot_module()
    if mod and hasattr(mod, "is_authorized"):
        return mod.is_authorized(user_id)
    return is_authorized(user_id)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command."""
    user = update.effective_user
    chat_id = update.effective_chat.id
    if not _is_authorized(user.id):
        await update.message.reply_text(
            f"⛔ *Akses Ditolak*\n\nID Anda: `{user.id}` belum terdaftar di whitelist bot.",
            parse_mode=constants.ParseMode.MARKDOWN,
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
        ],
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


async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /menu command."""
    user = update.effective_user
    chat_id = update.effective_chat.id
    if not _is_authorized(user.id):
        return

    settings = await database.get_user_settings(user.id)
    voice_status = "ON 🔊" if settings.get("voice_reply") else "OFF 🔇"

    keyboard = [
        [
            InlineKeyboardButton("📊 System Stats", callback_data="btn_stats"),
            InlineKeyboardButton("🧠 Lihat Memori", callback_data="btn_memory"),
        ],
        [
            InlineKeyboardButton(
                f"🎙️ Suara: {voice_status}", callback_data="btn_toggle_voice"
            ),
            InlineKeyboardButton("📈 Python & Plot", callback_data="btn_python_info"),
        ],
        [
            InlineKeyboardButton("🧹 Reset Konteks", callback_data="btn_clear"),
            InlineKeyboardButton("❓ Daftar Perintah", callback_data="btn_help"),
        ],
    ]
    await safe_send_message(
        context,
        chat_id,
        "🎛️ **Menu Kontrol Autonomous Agent:**",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def cekagen_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/cekagen — audit kesehatan konfigurasi otak utama & agen swarm."""
    user_id = update.effective_user.id
    if not _is_authorized(user_id):
        return

    import sqlite3 as _sq

    conn = _sq.connect(database.DB_PATH)
    conn.row_factory = _sq.Row
    try:
        brain_key = conn.execute(
            "SELECT value FROM system_settings WHERE key='main_brain_key_id'"
        ).fetchone()
        brain_model = conn.execute(
            "SELECT value FROM system_settings WHERE key='main_brain_model'"
        ).fetchone()
        bk = int(brain_key[0]) if brain_key else None
        bm = (brain_model[0] or "").strip() if brain_model else ""
        krow = (
            conn.execute(
                "SELECT name,provider,default_model,is_active FROM api_keys WHERE id=?",
                (bk,),
            ).fetchone()
            if bk
            else None
        )

        lines = ["🩺 **AUDIT KONFIGURASI AGENT**\n"]
        if krow:
            ok_model = bm == (krow["default_model"] or "").strip()
            lines.append(
                f"*Otak Utama:* key#{bk} `{krow['name']}` ({krow['provider']})\n"
                f"  Model override: `{bm}` {'✅' if ok_model else '⚠️ beda dari default kunci (`' + krow['default_model'] + '`)'}\n"
                f"  Status kunci: {'🟢 aktif' if krow['is_active'] else '🔴 NONAKTIF'}"
            )
        else:
            lines.append("*Otak Utama:* ❌ pointer kosong/tidak valid!")

        lines.append("\n*Agen Swarm:*")
        problems = 0
        for a in conn.execute(
            "SELECT name,provider,model,api_key_id,is_enabled FROM custom_agents ORDER BY id"
        ):
            kid = a["api_key_id"]
            k2 = (
                conn.execute(
                    "SELECT provider,default_model,is_active FROM api_keys WHERE id=?",
                    (kid,),
                ).fetchone()
                if kid
                else None
            )
            issues = []
            if not k2:
                issues.append("kunci hilang")
            else:
                if k2["provider"] != a["provider"]:
                    issues.append(f"kunci {k2['provider']} ≠ agen {a['provider']}")
                if not k2["is_active"]:
                    issues.append("kunci nonaktif/kuota bisa habis terpisah")
                if (a["model"] or "").strip() and a["model"].strip() != (
                    k2["default_model"] or ""
                ).strip():
                    if a["provider"] == k2["provider"]:
                        issues.append(f"model '{a['model']}' ≠ default kunci")
            flag = "✅" if not issues else "❌"
            problems += len(issues)
            status = " | ".join(issues) if issues else "sehat"
            on = "" if a["is_enabled"] else " (off)"
            lines.append(
                f"  {flag} {a['name']}: {a['provider']}/{a['model']} → key#{kid} — {status}{on}"
            )

        lines.append(
            f"\n{'🎉 Semua konfigurasi konsisten.' if problems == 0 else f'⚠️ {problems} masalah ditemukan.'}\n"
            "Perbaiki lewat Dashboard › API Key Vault / Agen Swarm."
        )
        await safe_send_message(context, update.effective_chat.id, "\n".join(lines))
    finally:
        conn.close()


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /stats command."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if not _is_authorized(user_id):
        return

    stats = get_system_stats()
    text = (
        f"📊 **Status Server / Laptop Real-Time:**\n\n"
        f"• **CPU:** `{stats.get('cpu')}`\n"
        f"• **RAM:** `{stats.get('ram')}`\n"
        f"• **Swap:** `{stats.get('swap')}`\n"
        f"• **Disk:** `{stats.get('disk')}`\n"
        f"• **Power/Baterai:** `{stats.get('battery')}`\n"
        f"• **IP Addr:** `{stats.get('ip_addresses')}`\n"
        f"• **Uptime:** `{stats.get('uptime')}`\n\n"
        f"🔥 **Top RAM:**\n"
        + "\n".join([f"  - {p}" for p in stats.get("top_ram_processes", [])])
        + "\n\n"
        "⚡ **Top CPU:**\n"
        + "\n".join([f"  - {p}" for p in stats.get("top_cpu_processes", [])])
    )
    await safe_send_message(context, chat_id, text)


async def memory_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /memory command."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if not _is_authorized(user_id):
        return

    memories = await database.get_all_memories(user_id)
    if not memories:
        await safe_send_message(
            context,
            chat_id,
            '🧠 **Memori Jangka Panjang Kosong.**\n\nAnda bisa menyuruh bot mengingat sesuatu, contoh:\n_"Ingat bahwa port database staging adalah 5433"_',
        )
        return

    text = f"🧠 **Memori Tersimpan ({len(memories)} item):**\n\n"
    for m in memories:
        text += (
            f"• *[{m['category'].upper()}]* `{m['key_topic']}`:\n  {m['content']}\n\n"
        )

    await safe_send_message(context, chat_id, text)


async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /clear command."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if not _is_authorized(user_id):
        return

    await database.clear_user_chat_history(user_id)
    await safe_send_message(
        context,
        chat_id,
        "🧹 **Riwayat percakapan berhasil direset.** Memori jangka panjang tetap aman tersimpan!",
    )


async def id_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /id command."""
    user = update.effective_user
    chat_id = update.effective_chat.id
    text = (
        f"👤 **Nama:** {user.full_name}\n"
        f"🆔 **Telegram ID:** `{user.id}`\n"
        f"💬 **Chat ID:** `{chat_id}`"
    )
    await safe_send_message(context, chat_id, text)


async def voice_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /voice toggle command."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if not _is_authorized(user_id):
        return

    is_on = await database.toggle_voice_setting(user_id)
    status_str = (
        "AKTIF 🔊 (Bot akan membalas dengan Voice Note & Teks)"
        if is_on
        else "NONAKTIF 🔇 (Bot membalas teks saja)"
    )
    await safe_send_message(context, chat_id, f"🎙️ **Mode Suara:** {status_str}")


async def cron_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List scheduled recurring tasks."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if not _is_authorized(user_id):
        await safe_send_message(context, chat_id, "⛔ Akses ditolak.")
        return

    jobs = database.list_cron_jobs_sync(user_id)
    if not jobs:
        await safe_send_message(
            context,
            chat_id,
            "⏰ Belum ada tugas berulang (cron/watchdog) yang aktif.\n\nContoh membuat: *'Jadwalkan pantau server tiap 30 menit'*.",
        )
        return

    text = f"⏰ **Daftar Tugas Berulang & Watchdog ({len(jobs)} tugas):**\n\n"
    for j in jobs:
        status_icon = "🟢 Aktif" if j["is_active"] else "🔴 Nonaktif"
        text += f"• **#{j['id']} {j['title']}** ({status_icon})\n"
        text += f"  - Interval: Setiap {j['interval_minutes']} menit\n"
        text += f"  - Instruksi: `{j['prompt_instruction']}`\n"
        text += f"  - Jadwal Berikutnya: `{j['next_run']}`\n\n"

    await safe_send_message(context, chat_id, text)


async def proactive_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /proactive command to view or toggle ambient proactive intelligence."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if not _is_authorized(user_id):
        return

    config = tools.proactive_ambient_agent_config("status")
    p_cfg = config.get("proactive_config", {})
    status_str = "🟢 AKTIF" if p_cfg.get("enabled", True) else "🔴 NONAKTIF"

    text = (
        f"🤖 **Status Inisiatif Proaktif Otonom:**\n\n"
        f"• **Status:** {status_str}\n"
        f"• **Jeda Inisiatif:** Minimal setiap `{p_cfg.get('min_hours_between_pings', 3)}` jam\n"
        f"• **Jam Tenang (Quiet Hours):** `{p_cfg.get('quiet_hours_start', 23)}:00` s/d `{p_cfg.get('quiet_hours_end', 7)}:00`\n"
        f"• **Waktu Terakhir:** `{p_cfg.get('last_ping_time', 'Belum pernah')}`\n\n"
        f"💡 _Saat aktif, bot akan berinisiatif mandiri menyapa, menanyakan progres tugas, atau mengingatkan sesuatu berdasarkan waktu & kondisi laptop._"
    )
    await safe_send_message(context, chat_id, text)
