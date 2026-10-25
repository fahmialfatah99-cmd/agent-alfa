"""Telegram bot command handlers."""

import logging
import sys

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    Update,
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
        return bool(mod.is_authorized(user_id))
    return is_authorized(user_id)


def get_persistent_reply_keyboard() -> ReplyKeyboardMarkup:
    """Keyboard navigasi cepat yang tetap aktif di bagian bawah chat Telegram pengguna."""
    return ReplyKeyboardMarkup(
        [
            ["📦 Rekap Material Lahat", "📋 Daily Briefing"],
            ["🎛️ Menu Utama", "📱 WhatsApp Hub", "🖥️ Status Server"],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


def _main_menu_markup() -> InlineKeyboardMarkup:
    """Grid menu utama terstruktur, elegan, dan ergonomis untuk Telegram."""
    return InlineKeyboardMarkup(
        [
            # 1. Mode Kerja & AI
            [
                InlineKeyboardButton("🧍 Mode Single", callback_data="btn_mode_single"),
                InlineKeyboardButton("⚡ Mode Swarm", callback_data="btn_mode_swarm"),
            ],
            # 2. Operasional Lapangan (FTTH / Material)
            [
                InlineKeyboardButton("📦 Rekap Material Lahat", callback_data="btn_rekap_lahat"),
                InlineKeyboardButton("📋 Daily Briefing", callback_data="btn_daily_briefing"),
            ],
            # 3. Komunikasi & Cloud Data
            [
                InlineKeyboardButton("📱 WhatsApp Hub", callback_data="btn_wa"),
                InlineKeyboardButton("☁️ Google Cloud Hub", callback_data="btn_cloud"),
            ],
            # 4. Aplikasi Desktop & Rapat
            [
                InlineKeyboardButton("🎨 ArtCraft Suite", callback_data="btn_artcraft"),
                InlineKeyboardButton("🏛️ Rapat Plan AI", callback_data="btn_meeting_info"),
            ],
            # 5. Monitoring & Dashboard
            [
                InlineKeyboardButton("🖥️ Status Server & RAM", callback_data="btn_stats"),
                InlineKeyboardButton("🌐 Web Dashboard", callback_data="btn_dashboard"),
            ],
            # 6. Otomasi & Workforce
            [
                InlineKeyboardButton("🤖 Agen & Persona", callback_data="btn_agents"),
                InlineKeyboardButton("🛠️ Tools (140+)", callback_data="btn_tools"),
            ],
            # 7. Pengaturan & Bantuan
            [
                InlineKeyboardButton("🎙️ Suara AI", callback_data="btn_toggle_voice"),
                InlineKeyboardButton("🧠 Memori", callback_data="btn_memory"),
                InlineKeyboardButton("❓ Bantuan", callback_data="btn_help"),
            ],
        ]
    )


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command."""
    user = update.effective_user
    chat_id = update.effective_chat.id if update.effective_chat else 0
    user_id = user.id if user else 0
    if not _is_authorized(user_id):
        if update.message:
            await update.message.reply_text(
                f"⛔ *Akses Ditolak*\n\nID Anda: `{user_id}` belum terdaftar di whitelist bot.",
                parse_mode=constants.ParseMode.MARKDOWN,
            )
        return

    reply_markup = _main_menu_markup()

    # Onboarding pengguna baru: tur singkat bila belum pernah chat.
    try:
        _hist = await database.get_recent_chat_history(user_id, limit=1)
    except Exception:
        _hist = [{}]
    tour = ""
    if not _hist:
        tour = (
            "\n\n🎉 **Selamat datang, pengguna baru! Tur 30 detik:**\n"
            "1. Ketik apa saja — saya agen AI dengan akses mesin + 160 tools.\n"
            "2. `/menu` — semua tombol fitur.\n"
            "3. `/sheets` & `/drive` — pantau file Google Sheets & Drive.\n"
            "4. `/swarm <tugas>` — kerjakan tugas berat multi-agen.\n"
            "5. `/cekagen` — cek kesehatan konfigurasi bila ada yang aneh.\n"
            "6. `/sites` — galeri hasil kerja (website/proyek).\n"
        )

    first_name = user.first_name if user else ""
    try:
        await context.bot.send_message(
            chat_id=chat_id,
            text="⚡ *ALFA OS Sovereign Agent siap melayani Anda.*",
            parse_mode=constants.ParseMode.MARKDOWN,
            reply_markup=get_persistent_reply_keyboard(),
        )
    except Exception as e:
        logger.debug("Gagal mengirim persistent keyboard: %s", e)

    welcome_text = (
        f"🤖 **Personal Autonomous AI Agent**\n"
        f"Halo, **{first_name}**! Saya asisten AI otonom pribadi berbasis **multi-provider (9Router/Gemini)** yang terhubung langsung dengan mesin Linux Anda.\n\n"
        f"🧭 **Mode Eksekusi:** `/mode single` (1 agen cepat) atau `/mode swarm` (tim multi-agen). "
        f"Panggil swarm kapan saja via `/swarm <tugas>`.\n\n"
        f"⚡ **Kemampuan & Tools Aktif (100% Real):**\n"
        f"• 🐍 **Python Sandbox & Data Plotter:** Eksekusi script & pembuatan grafik visual otomatis.\n"
        f"• 📊 **Google Sheets & Drive:** `/sheets` & `/drive` untuk melihat file & isi data terhubung.\n"
        f"• 🖥️ **Desktop & Webcam Vision:** Screenshot layar desktop & snapshot webcam real-time.\n"
        f"• 🎙️ **Voice Notes (STT & TTS):** Kirim suara, AI membalas dengan suara natural Edge-TTS.\n"
        f"• 🌐 **Deep Web Intelligence:** DuckDuckGo search & ekstraksi konten artikel web.\n"
        f"• 🔍 **Workspace Intelligence:** Grep, find files, read/write file lokal.\n"
        f"• 🤖 **Swarm Multi-Agent:** `/rapat` (plan) & `/swarm` (eksekusi nyata).\n"
        f"• 🔁 **Pipeline DAG & Tugas Latar:** `/pipeline`, `/tugas`.\n"
        f"• 🧠 **Persistent Long-Term Memory:** Memori permanen terisolasi per akun.\n"
        f"• ⏰ **Proactive Reminders:** Pengingat otomatis terjadwal.\n\n"
        f"Ketik `/menu` untuk panel lengkap atau `/help` untuk semua perintah!"
        f"{tour}"
    )
    await safe_send_message(context, chat_id, welcome_text, reply_markup=reply_markup)


async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /menu command."""
    user = update.effective_user
    chat_id = update.effective_chat.id if update.effective_chat else 0
    if not _is_authorized(user.id if user else 0):
        return

    try:
        await context.bot.send_message(
            chat_id=chat_id,
            text="🎛️ *Panel Navigasi Cepat Terpasang*",
            parse_mode=constants.ParseMode.MARKDOWN,
            reply_markup=get_persistent_reply_keyboard(),
        )
    except Exception as e:
        logger.debug("Gagal kirim persistent keyboard on menu: %s", e)

    keyboard = _main_menu_markup().inline_keyboard
    await safe_send_message(
        context,
        chat_id,
        "🎛️ **Menu Kontrol Autonomous Agent (ALFA OS):**\nSilakan pilih modul kerja yang Anda butuhkan:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def cekagen_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/cekagen — audit kesehatan konfigurasi otak utama & agen swarm."""
    user_id = update.effective_user.id if update.effective_user else 0
    chat_id = update.effective_chat.id if update.effective_chat else 0
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
        await safe_send_message(context, chat_id, "\n".join(lines))
    finally:
        conn.close()


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /stats command."""
    user_id = update.effective_user.id if update.effective_user else 0
    chat_id = update.effective_chat.id if update.effective_chat else 0
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
    user_id = update.effective_user.id if update.effective_user else 0
    chat_id = update.effective_chat.id if update.effective_chat else 0
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
    user_id = update.effective_user.id if update.effective_user else 0
    chat_id = update.effective_chat.id if update.effective_chat else 0
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
    chat_id = update.effective_chat.id if update.effective_chat else 0
    text = (
        f"👤 **Nama:** {user.full_name if user else ''}\n"
        f"🆔 **Telegram ID:** `{user.id if user else 0}`\n"
        f"💬 **Chat ID:** `{chat_id}`"
    )
    await safe_send_message(context, chat_id, text)


async def voice_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /voice toggle command."""
    user_id = update.effective_user.id if update.effective_user else 0
    chat_id = update.effective_chat.id if update.effective_chat else 0
    if not _is_authorized(user_id):
        return

    is_on = await database.toggle_voice_setting(user_id)
    status_str = (
        "AKTIF 🔊 (Bot akan membalas dengan Voice Note & Teks)"
        if is_on
        else "NONAKTIF 🔇 (Bot membalas teks saja)"
    )
    await safe_send_message(context, chat_id, f"🎙️ **Mode Suara:** {status_str}")


async def budget_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/budget [set <token_harian> <call_harian>] — lihat & atur kuota token harian."""
    user_id = update.effective_user.id if update.effective_user else 0
    chat_id = update.effective_chat.id if update.effective_chat else 0
    if not _is_authorized(user_id):
        return

    from alfa.core import rate_limiter

    args = list(context.args) if context.args else []
    if args and args[0].lower() in ("reset", "clear"):
        deleted = rate_limiter.reset_user_usage_today(user_id)
        usage = rate_limiter.get_user_usage_today(user_id)
        msg = (
            "🔄 **Kuota harian berhasil di-reset!**\n\n"
            f"• Token terpakai hari ini: **0** / {usage['budget_limit']:,} token\n"
            f"• Panggilan terpakai: **0** / {usage['call_limit']:,} panggilan\n"
            f"• Catatan pemakaian dihapus: {deleted} entri\n\n"
            "Sekarang Anda bisa kembali menggunakan AI secara normal tanpa batasan kuota."
        )
        await safe_send_message(context, chat_id, msg)
        return

    if len(args) >= 3 and args[0].lower() == "set":
        try:
            tok = max(1000, int(args[1]))
            cal = max(10, int(args[2]))
        except ValueError:
            await safe_send_message(
                context, chat_id, "Usage: `/budget set <token_harian> <call_harian>`\nContoh: `/budget set 500000 200`"
            )
            return
        rate_limiter.set_user_budget(user_id, tok, cal)
        await safe_send_message(
            context, chat_id, f"✅ Kuota harian diset: **{tok:,}** token, **{cal}** panggilan."
        )
        return

    rep = rate_limiter.get_budget_report(user_id)
    if rep.get("status") != "ok":
        await safe_send_message(context, chat_id, "❓ Data kuota belum tersedia.")
        return
    pct = rep["pct"] * 100
    bar_n = int(min(10, rep["pct"] * 10))
    bar = "█" * bar_n + "░" * (10 - bar_n)
    icon = "🔴" if rep["exceeded"] else ("🟡" if rep["warn"] else "🟢")
    lines = [
        f"{icon} **Kuota Token Harian:**",
        f"`[{bar}]` {pct:.0f}%",
        f"• Terpakai: **{rep['total_tokens']:,}** / {rep['budget_limit']:,} token",
        f"• Sisa: **{rep['remaining']:,}** • Panggilan: {rep['total_calls']}/{rep['call_limit']}",
        "• Reset otomatis: tengah malam WIB",
    ]
    for k in (rep.get("by_key") or [])[:5]:
        label = k.get("key_label") or k.get("provider") or "?"
        lines.append(f"  - {label}: {(k.get('total_tokens') or 0):,} ({k.get('calls', 0)}×)")
    if rep["exceeded"]:
        lines.append("\n🔴 Di atas batas — ketik `/budget reset` atau naikkan batas kuota.")
    elif rep["warn"]:
        lines.append("\n🟡 Di atas 80% — hemat: utamakan chat single, tunda misi swarm besar.")
    lines.append("\n• Reset sekarang: `/budget reset`\n• Ubah batas: `/budget set <token> <call>`")

    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Reset Kuota Sekarang", callback_data="budget:reset")]
    ])
    await safe_send_message(context, chat_id, "\n".join(lines), reply_markup=kb)


async def cron_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List scheduled recurring tasks."""
    user_id = update.effective_user.id if update.effective_user else 0
    chat_id = update.effective_chat.id if update.effective_chat else 0
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
        kind_badge = "⚡ swarm" if (j.get("kind") or "single") == "swarm" else "🧍 single"
        text += f"• **#{j['id']} {j['title']}** ({status_icon} • {kind_badge})\n"
        text += f"  - Interval: Setiap {j['interval_minutes']} menit\n"
        text += f"  - Instruksi: `{j['prompt_instruction']}`\n"
        text += f"  - Jadwal Berikutnya: `{j['next_run']}`\n\n"

    await safe_send_message(context, chat_id, text)


async def proactive_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /proactive command to view or toggle ambient proactive intelligence."""
    user_id = update.effective_user.id if update.effective_user else 0
    chat_id = update.effective_chat.id if update.effective_chat else 0
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
