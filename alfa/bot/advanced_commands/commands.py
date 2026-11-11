"""Perintah umum bot (/setsheet, /dashboard, /keys, /rapat, /swarm, ...)."""
from __future__ import annotations

import asyncio
import logging
import os

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
    WebAppInfo,
)
from telegram.ext import ContextTypes

from alfa import tools
from alfa.bot.advanced_commands._common import _ADV_ERR
from alfa.bot.advanced_commands._compat import is_authorized, safe_send_message
from alfa.core import database

logger = logging.getLogger("TelegramAIAgent")

async def setsheet_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /setsheet [URL or ID] command to configure Google Spreadsheet for material logging."""
    user_id = update.effective_user.id if update.effective_user else 0
    chat_id = update.effective_chat.id if update.effective_chat else 0
    if not is_authorized(user_id):
        await safe_send_message(context, chat_id, "⛔ Akses ditolak.")
        return

    args = context.args if context and context.args else []
    from alfa.integrations import google_sheets

    sa_email = "ais-gemini-key-557267392dac418@30020894332.iam.gserviceaccount.com"

    if not args:
        curr_id = google_sheets.get_spreadsheet_id()
        tab_name = google_sheets.DEFAULT_TAB_NAME

        status_text = "Belum Terhubung 🔴"
        title_text = "-"
        if curr_id:
            check_res = google_sheets.ensure_material_sheet_tab(spreadsheet_id=curr_id)
            if check_res.get("status") == "success":
                status_text = "Terhubung 🟢"
                title_text = check_res.get("title", "-")
            else:
                status_text = f"Peringatan Akses ⚠️ ({check_res.get('message', '')[:100]})"

        msg = (
            f"📊 **Konfigurasi Google Sheets Pencatatan Material**\n\n"
            f"• **Status Koneksi:** {status_text}\n"
            f"• **Judul Spreadsheet:** `{title_text}`\n"
            f"• **Spreadsheet ID Saat Ini:**\n`{curr_id or 'Belum disetel'}`\n"
            f"• **Tab Target:** `{tab_name}`\n"
            f"• **Local GDrive Backup:** `~/GDrive1/PENCATATAN_MATERIAL/Rekap_Pengambilan_Material.xlsx`\n\n"
            f"🔧 **Panduan Menyambungkan Google Sheets Baru:**\n"
            f"1️⃣ Buat spreadsheet baru di Google Sheets (atau buka yang ingin digunakan).\n"
            f"2️⃣ Klik tombol **Bagikan (Share)** di pojok kanan atas.\n"
            f"3️⃣ Tambahkan email Service Account sebagai **Editor**:\n"
            f"`{sa_email}`\n"
            f"4️⃣ Kirim perintah berikut ke bot:\n"
            f"`/setsheet <Link_URL_atau_ID_Spreadsheet>`\n\n"
            f"_Contoh:_\n"
            f"`/setsheet https://docs.google.com/spreadsheets/d/1d9Mr1IZszP1Cq34VN1_OTHtWokxDdV4prywsgVxN0RQ/edit`"
        )
        await safe_send_message(context, chat_id, msg)
        return

    raw_input = " ".join(args).strip()
    await safe_send_message(context, chat_id, "⏳ Memverifikasi dan mengonfigurasi Google Sheets baru...")

    res = google_sheets.set_spreadsheet_id(raw_input)
    if res.get("status") == "success":
        reply = (
            f"🎉 **Google Sheets Baru Berhasil Dikonfigurasi!**\n\n"
            f"• **Judul:** `{res.get('spreadsheet_title', '-')}`\n"
            f"• **ID:** `{res.get('spreadsheet_id')}`\n"
            f"• **Tab Otomatis:** `{res.get('tab_name')}` (Kolom standar sudah siap)\n"
            f"• **Sinkronisasi Telegram:** Aktif 🟢\n"
            f"• **Sinkronisasi WhatsApp:** Aktif 🟢 (Service di-reload)\n"
            f"• **Backup GDrive Lokal:** Aktif 🟢\n\n"
            f"💡 _Mulai sekarang, seluruh dokumen/foto/pesan pengambilan material yang masuk ke Telegram maupun WhatsApp akan otomatis dirapikan oleh AI dan dicatat ke spreadsheet ini._"
        )
    else:
        reply = (
            f"⚠️ **Pengaturan Spreadsheet Gagal / Ada Masalah:**\n\n"
            f"{res.get('message')}\n\n"
            f"📌 **Pastikan:**\n"
            f"Email Service Account sudah ditambahkan sebagai **Editor**:\n"
            f"`{sa_email}`"
        )

    await safe_send_message(context, chat_id, reply)

async def dashboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /dashboard, /web, or /app command."""
    user_id = update.effective_user.id if update.effective_user else 0
    chat_id = update.effective_chat.id if update.effective_chat else 0
    if not is_authorized(user_id):
        return

    res = tools.open_web_dashboard(port=8080)
    tma_url = os.getenv(
        "ALFA_WEBAPP_URL", res.get("network_url") or "http://127.0.0.1:8080"
    )

    keyboard = []
    magic_ok = False
    try:
        from alfa.dashboard.routes.auth import create_telegram_link

        # CATATAN: tombol URL localhost DITOLAK API Telegram (400 utk SELURUH pesan).
        # Semua tombol pakai base LAN — laptop satu WiFi membukanya normal.
        lan_base = (res.get("network_url") or "").rstrip("/")
        if lan_base:
            tok_hp = create_telegram_link(user_id)
            tok_laptop = create_telegram_link(user_id)
            keyboard.append(
                [InlineKeyboardButton("📱 Buka di HP (WiFi, auto-login)", url=f"{lan_base}/t/{tok_hp}")]
            )
            keyboard.append(
                [InlineKeyboardButton("💻 Buka di Laptop (auto-login)", url=f"{lan_base}/t/{tok_laptop}")]
            )
            magic_ok = bool(keyboard)
    except _ADV_ERR as link_err:
        logger.debug(f"[dashboard] magic link gagal: {link_err}")
    if tma_url and tma_url.startswith("https://"):
        keyboard.append(
            [
                InlineKeyboardButton(
                    "📱 Buka ALFA Mini App", web_app=WebAppInfo(url=tma_url)
                )
            ]
        )
    else:
        web_url = res.get("network_url") or res.get("local_url") or ""
        if web_url and not web_url.startswith("http://localhost") and not magic_ok:
            keyboard.append(
                [InlineKeyboardButton("🌐 Buka Web Dashboard", url=web_url)]
            )

    reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None

    text = (
        "🛸 **ALFA SOVEREIGN COMMAND CENTER:**\n\n"
        + (
            "Ketuk tombol di bawah untuk masuk otomatis (tanpa login).\n"
            "Berlaku 10 menit, sekali pakai.\n"
            if magic_ok
            else (
                f"• **Akses Lokal (Laptop):** `{res.get('local_url')}`\n"
                f"• **Akses Jaringan (HP / WiFi):** `{res.get('network_url')}`\n"
            )
        )
        + "\n⚡ **Pusat Kontrol Terintegrasi:**\n"
        "1. 📊 Telemetri Hardware & CPU/RAM Real-time\n"
        "2. ⚡ 130+ Tools Interaktif & Browser Otomatis\n"
        "3. 🧠 Second Brain & Vector Memory\n"
        "4. 🛡️ 24/7 System Guardian & Background Watchdogs\n"
        "5. 💬 Web AI Interactive Console\n"
        "6. 🤖 Ruang Rapat AI (Swarm Multi-Agent Engine)\n"
        "7. 🔑 Multi-Provider Vault & API Keys Manager"
    )
    await safe_send_message(context, chat_id, text, reply_markup=reply_markup)

async def keys_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /keys command to manage API keys vault."""
    user_id = update.effective_user.id if update.effective_user else 0
    chat_id = update.effective_chat.id if update.effective_chat else 0
    if not is_authorized(user_id):
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
    user_id = update.effective_user.id if update.effective_user else 0
    chat_id = update.effective_chat.id if update.effective_chat else 0
    if not is_authorized(user_id):
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
    user_id = update.effective_user.id if update.effective_user else 0
    chat_id = update.effective_chat.id if update.effective_chat else 0
    if not is_authorized(user_id):
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

    from alfa.bot.progress import SwarmProgressReporter

    reporter = SwarmProgressReporter(context, chat_id, topic, header="🏛️ **Rapat**")
    await reporter.start()

    try:
        from alfa.swarm import engine as swarm_engine

        result = await swarm_engine.conduct_multi_agent_meeting(
            topic=topic, rounds=2, mode="plan"
        )
    except _ADV_ERR as e:
        await reporter.stop("❌ Rapat gagal.")
        logger.error(f"Error during Telegram /rapat meeting: {e}")
        await safe_send_message(
            context, chat_id, f"❌ Terjadi kesalahan saat rapat agent: {str(e)}"
        )
        return

    await reporter.stop("✅ Diskusi selesai — transkrip di bawah ⬇️")

    try:
        from alfa.swarm.deliberation import export_meeting_report_files

        try:
            export_meeting_report_files({**result, "topic": topic})
        except Exception as exc:
            logger.debug("Kegagalan tak terduga di rapat_command: %s", exc)

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
        meeting_kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "⚡ Eksekusi Action Plan Ini",
                        callback_data="btn_swarm_exec_last",
                    )
                ],
                [
                    InlineKeyboardButton(
                        "📄 Export Dokumen Laporan Rapat",
                        callback_data="btn_swarm_export_last",
                    )
                ],
            ]
        )
        await safe_send_message(
            context, chat_id, final_text, reply_markup=meeting_kb
        )

    except _ADV_ERR as e:
        logger.error(f"Error during Telegram /rapat meeting: {e}")
        await safe_send_message(
            context, chat_id, f"❌ Terjadi kesalahan saat rapat agent: {str(e)}"
        )

async def swarm_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /swarm — subcommands (model|status|cancel) atau eksekusi langsung (Execute Mode)."""
    user_id = update.effective_user.id if update.effective_user else 0
    chat_id = update.effective_chat.id if update.effective_chat else 0
    if not is_authorized(user_id):
        return

    raw = " ".join(context.args).strip() if context.args else ""
    first = (raw.split(maxsplit=1)[0].lower() if raw else "")
    rest = (raw.split(maxsplit=1)[1] if " " in raw else "")

    if first in ("model", "set-model"):
        # Reuse CLI helper logic via direct DB update path
        import shlex

        from alfa.core import database as _db
        from alfa.core.cli.direct_ai import PROVIDERS_CATALOG, normalize_provider

        try:
            parts = shlex.split(rest)
        except ValueError:
            parts = rest.strip().split()
        agents = _db.list_custom_agents_sync()
        if not parts:
            await safe_send_message(
                context,
                chat_id,
                "Usage: `/swarm model <id|nama> <provider> [model]`\n"
                "Contoh: `/swarm model 2 9router antigravity`",
            )
            return
        target_agent = parts[0]
        matched = None
        if target_agent.isdigit():
            matched = next((a for a in agents if a.get("id") == int(target_agent)), None)
        if not matched:
            tl = target_agent.lower()
            matched = next((a for a in agents if tl in a.get("name", "").lower()), None)
        if not matched:
            await safe_send_message(context, chat_id, f"❌ Agen '{target_agent}' tidak ditemukan. `/agents`")
            return
        if len(parts) < 2:
            await safe_send_message(
                context, chat_id,
                f"Agen: **{matched.get('name')}** — `{matched.get('provider')}/{matched.get('model')}`\n"
                f"Ubah: `/swarm model \"{matched.get('name')}\" <provider> [model]`",
            )
            return
        provider = normalize_provider(parts[1])
        cat = PROVIDERS_CATALOG.get(provider, {})
        model = parts[2] if len(parts) > 2 else (cat.get("default_model") or "default")
        res = _db.update_custom_agent_sync(matched["id"], {"provider": provider, "model": model})
        if res.get("status") == "success":
            await safe_send_message(context, chat_id, f"✅ **{matched.get('name')}** → `{provider}/{model}`")
        else:
            await safe_send_message(context, chat_id, f"❌ Gagal: `{res.get('message')}`")
        return

    if first in ("status", "info"):
        from alfa.bot.mode_commands import status_command as _status

        await _status(update, context)
        return

    if first in ("cancel", "stop", "batal"):
        from alfa.bot.mode_commands import cancel_command as _cancel

        await _cancel(update, context)
        return

    if first in ("single", "solo"):
        from alfa.bot.mode_commands import set_telegram_mode_sync

        set_telegram_mode_sync("single")
        await safe_send_message(context, chat_id, "🧍 **Mode SINGLE aktif.**")
        return

    if first in ("swarm", "on", "multi"):
        from alfa.bot.mode_commands import set_telegram_mode_sync

        set_telegram_mode_sync("swarm")
        await safe_send_message(context, chat_id, "⚡ **Mode SWARM aktif.** Chat teks dieksekusi tim.")
        return

    if first in ("template", "templates", "templat"):
        from alfa.bot.mode_commands import SWARM_TEMPLATES

        if not rest:
            rows = [f"• `{n}` — {t[:90]}…" for n, t in SWARM_TEMPLATES.items()]
            await safe_send_message(
                context,
                chat_id,
                "📦 **Templat Misi Swarm:**\n\n" + "\n".join(rows)
                + "\n\nJalankan: `/swarm template <nama>`\nJadwalkan: *'Jadwalkan misi swarm <nama> tiap <N> menit/jam'*",
            )
            return
        tpl = SWARM_TEMPLATES.get(rest.strip().lower())
        if not tpl:
            await safe_send_message(
                context, chat_id,
                f"❌ Templat '{rest.strip()}' tidak ada. Lihat `/swarm template`.",
            )
            return
        raw = tpl  # alir ke `topic = raw` di bawah → eksekusi misi templat

    topic = raw
    if not topic:
        text = (
            "⚡ **Panduan Swarm Eksekusi Langsung (Mode 2: Bekerja Nyata):**\n\n"
            "Format: `/swarm <perintah / tugas nyata yang ingin dikerjakan bersama>`\n\n"
            "**Contoh:**\n"
            "• `/swarm Scrape 20 mouse gaming terlaris di Shopee & Tokopedia dan buatkan CSV-nya`\n"
            "• `/swarm Buatkan script Python monitoring RAM/CPU dan jalankan di sandbox`\n"
            "• `/swarm Audit port lokal dan status keamanan server`\n\n"
            "**Subcommand:**\n"
            "• `/swarm status` — status swarm & key agen\n"
            "• `/swarm cancel` — hentikan misi berjalan\n"
            "• `/swarm template [nama]` — misi siap pakai\n"
            "• `/swarm model <id|nama> <provider> [model]` — ganti model agen\n"
            "• `/mode swarm` — semua chat teks jadi misi swarm\n\n"
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

    from alfa.bot.progress import SwarmProgressReporter

    reporter = SwarmProgressReporter(context, chat_id, topic)
    await reporter.start()

    try:
        from alfa.swarm import engine as swarm_engine

        result = await swarm_engine.conduct_multi_agent_meeting(
            topic=topic, rounds=1, mode="execute"
        )
    except _ADV_ERR as e:
        await reporter.stop("❌ Misi gagal.")
        logger.error(f"Error during Telegram /swarm execution: {e}")
        await safe_send_message(
            context, chat_id, f"❌ Terjadi kesalahan saat eksekusi swarm: {str(e)}"
        )
        return

    await reporter.stop("✅ Selesai — laporan lengkap di bawah ⬇️")

    try:
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
                except _ADV_ERR as file_err:
                    logger.warning(
                        f"Failed to send deliverable file to Telegram: {file_err}"
                    )
    except _ADV_ERR as e:
        logger.error(f"Error sending Telegram /swarm report: {e}")
        await safe_send_message(
            context, chat_id, f"❌ Gagal mengirim laporan swarm: {str(e)}"
        )

async def resume_swarm_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /resume_swarm or /resume to resume an interrupted/cancelled swarm session."""
    user_id = update.effective_user.id if update.effective_user else 0
    chat_id = update.effective_chat.id if update.effective_chat else 0
    if not is_authorized(user_id):
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
            # Akses dict dengan .get() + str(): checkpoint yang tidak lengkap
            # (updated_at None, status non-str) tidak boleh MATIkan seluruh perintah.
            session_id = str(r.get("session_id") or "?")
            status = str(r.get("status") or "?").upper()
            topic = str(r.get("topic") or "")
            steps_done = r.get("steps_done", 0)
            steps_total = r.get("steps_total", "?")
            updated_at = str(r.get("updated_at") or "?")[:19]
            text += (
                f"• `{session_id}` [{status}]\n"
                f"  📌 Topik: _{topic}_\n"
                f"  📊 Progres: {steps_done}/{steps_total} langkah\n"
                f"  🕒 Update: `{updated_at}`\n\n"
            )
        text += "Gunakan `/resume <session_id>` untuk melanjutkan sesi."
        await safe_send_message(context, chat_id, text)
        return

    await safe_send_message(
        context,
        chat_id,
        f"🔄 **Melanjutkan sesi swarm `{session_id}` dari checkpoint...**",
    )
    from alfa.bot.progress import SwarmProgressReporter

    reporter = SwarmProgressReporter(context, chat_id, session_id, header="🔄 **Resume Swarm**")
    await reporter.start()
    try:
        from alfa.swarm import engine as swarm_engine

        result = await swarm_engine.resume_swarm_session(session_id)
        await reporter.stop("✅ Lanjutan selesai — hasil di bawah ⬇️")
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
            f"🏆 **LAPORAN HASIL LANJUTAN EKSEKUSI:**\n\n{result.get('consensus', '')}"
        )
        await safe_send_message(context, chat_id, final_text)
    except _ADV_ERR as e:
        try:
            await reporter.stop("❌ Resume gagal.")
        except _ADV_ERR:
            pass
        logger.error(f"Error during /resume_swarm: {e}")
        await safe_send_message(
            context, chat_id, f"❌ Terjadi kesalahan saat resume: {str(e)}"
        )

async def ram_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/ram atau /bersihkan — pantau dan optimalkan pemakaian RAM (ALFA Bot, Chromium, & WA Sheets Bot)."""
    user_id = update.effective_user.id if update.effective_user else 0
    chat_id = update.effective_chat.id if update.effective_chat else 0
    if not is_authorized(user_id):
        return

    from alfa.tools.system.management import system_clean_memory_and_cache

    do_recycle = False
    if context.args and any(a.lower() in ("wa", "restart", "full", "recycle") for a in context.args):
        do_recycle = True

    res = system_clean_memory_and_cache(recycle_wa_if_needed=do_recycle)
    sys_ram = res.get("system_ram", {})
    alfa_mb = res.get("alfa_bot_mb", 0)
    wa_mb = res.get("wa_sheets_bot_mb", 0)
    wa_procs = res.get("wa_process_count", 0)
    gc_objs = res.get("python_gc_objects_collected", 0)
    cleaned_tmp = res.get("cleaned_orphaned_tmp_dirs", 0)
    recycled = res.get("wa_recycled", False)

    lines = [
        "🧹 **Optimasi & Diagnostik Memori (RAM)**\n",
        f"🖥️ **Sistem:** {sys_ram.get('used_mb', 0)} MB / {sys_ram.get('total_mb', 0)} MB ({sys_ram.get('used_percent', 0)}% terpakai)",
        f"   • Tersedia: `{sys_ram.get('available_mb', 0)} MB`\n",
        f"🤖 **ALFA Python Bot:** `{alfa_mb} MB`",
        f"📱 **WA Sheets Bot & Chrome:** `{wa_mb} MB` ({wa_procs} proses)\n",
        "♻️ **Hasil Pembersihan:**",
        f"   • Python GC: {gc_objs} objek dibebaskan",
        f"   • Temp Chromium: {cleaned_tmp} direktori yatim dibersihkan",
    ]
    if recycled:
        lines.append("   • WA Sheets Bot: **Berhasil di-recycle & RAM di-reset fresh!** ✅")
    elif wa_mb > 1000:
        lines.append(f"\n⚠️ _Pemakaian RAM WA Bot cukup tinggi ({wa_mb} MB). Ketik `/ram full` untuk me-restart fresh._")

    await safe_send_message(context, chat_id, "\n".join(lines))

async def skills_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /skills command - view self-improving learned skills and metrics."""
    user = update.effective_user
    chat_id = update.effective_chat.id if update.effective_chat else 0
    user_id = user.id if user else 0
    if not is_authorized(user_id):
        return

    from alfa.core.brain.learning_loop import get_learning_loop_metrics

    m = get_learning_loop_metrics()

    avg_conf_pct = int(m.get("avg_confidence", 1.0) * 100)
    card_lines = [
        "🧠 *ALFA OS: SOTA SELF-IMPROVING LEARNING ENGINE*",
        "• Arsitektur: `Hermes-Reflexion-Supreme-v2 (Active Continual Learning)`",
        f"• Total Aturan Terkunci: *{m.get('total_active_skills', 0)} skill*",
        f"• Trajectory Terekam: *{m.get('total_trajectories', 0)} turn*",
        f"• Rata-rata Confidence: *{avg_conf_pct}%*",
        f"• Total Pemanggilan Aturan: *{m.get('total_hits', 0)} kali*\n",
        "📋 *Aturan & Pelajaran Prioritas Tinggi:*",
    ]
    for idx, s in enumerate(m.get("top_skills", []), 1):
        # .get() + str(): skill dengan field hilang tidak boleh mematikan perintah.
        rule = str(s.get("learned_rule") or "")
        rule_preview = rule[:120] + ("..." if len(rule) > 120 else "")
        conf_pct = int((s.get("confidence") or 1.0) * 100)
        succ = s.get("success_count", 0)
        fail = s.get("failure_count", 0)
        topic = str(s.get("topic") or "?")
        card_lines.append(
            f"{idx}. 🏷️ *{topic}*\n"
            f"   └ Conf: `{conf_pct}%` | Hits: `{s.get('hit_count', 0)}` | Rate: `+{succ}/-{fail}`\n"
            f"   └ \"_{rule_preview}_\""
        )

    card_lines.append(
        "\n⚡ *Cara Mengajari Agen:*\n"
        "• *Auto-Reflexion:* Cukup katakan _'salah, harusnya...'_, agen otomatis mengekstrak dan menyimpan aturan baru.\n"
        "• *Manual Seed:* Gunakan format pesan untuk mengajari aturan kapan saja."
    )
    await safe_send_message(context, chat_id, "\n".join(card_lines))

async def apex_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /apex and /level5 commands - display Level 5+ Sovereign Cognitive Apex status."""
    user = update.effective_user
    chat_id = update.effective_chat.id if update.effective_chat else 0
    user_id = user.id if user else 0
    if not is_authorized(user_id):
        return

    from alfa.core.apex import get_apex_full_status, run_autonomous_apex_maintenance

    # Run non-intrusive autonomous maintenance & sync cycle.
    # WAJIB di-thread: kalau sinkron, event loop bot membeku selama maintenance.
    try:
        await asyncio.to_thread(run_autonomous_apex_maintenance, force=False)
    except Exception as e:
        logger.warning(f"[apex] autonomous maintenance gagal: {e}")
    st = get_apex_full_status()
    gov = st.get("governor", {})
    dream = st.get("dreaming", {})
    world = st.get("world_model", {})
    canary = st.get("canary_evolution", {})
    learn = st.get("learning_loop", {})
    vault = st.get("cloud_rescue_vault", {})
    ledgers = st.get("symbolic_ledgers", {})
    graphrag = st.get("temporal_graphrag", {})
    factory = st.get("software_factory", {})
    comp_use = st.get("computer_use", {})

    lines = [
        "🌌 *ALFA OS: LEVEL 5+ SOVEREIGN COGNITIVE APEX*",
        f"• Status Otonomi: `{st.get('autonomy_level', 'Level 5+ Apex')}`\n",
        "1️⃣ *Neuro-Symbolic AST Prover & Ledger Auditor*",
        "   • Status Gate: `ACTIVE (0% Hallucination + Formula Audit)`",
        f"   • Aturan Terkunci: *{learn.get('total_active_skills', 0)} rules* _(Conf: {int(learn.get('avg_confidence', 1.0)*100)}%)_",
        f"   • Master Ledger Terverifikasi: *{ledgers.get('audited_ledgers_count', 0)} berkas Excel (0 Circular Ref)*\n",
        "2️⃣ *Offline Dreaming & Fast-Path Compiler*",
        f"   • Compiled Fast-Paths: *{dream.get('total_compiled_fastpaths', 0)} jalur aktif*",
        f"   • Eksekusi Instan (0 Token): *{dream.get('total_fastpath_hits', 0)} hits*",
        f"   • Estimasi Penghematan: *~{dream.get('estimated_tokens_saved', 0)} token*\n",
        "3️⃣ *Temporal GraphRAG Second Brain (Multi-Hop)*",
        f"   • Simpul Pengetahuan (Nodes): *{graphrag.get('total_entities', 0)} entitas*",
        f"   • Jaringan Asosiasi (Edges): *{graphrag.get('total_relations', 0)} relasi lintas waktu*\n",
        "4️⃣ *Autonomous Software Factory & Vision Computer-Use*",
        f"   • Aplikasi Full-Stack Terbangun: *{factory.get('total_builds', 0)} builds* _(Avg E2E: {factory.get('avg_e2e_score', 100)}%)_",
        f"   • Vision GUI Display: `{comp_use.get('display', ':0')} ({comp_use.get('resolution', '1920x1080')})`",
        f"   • Dynamic Canary Tools: *{canary.get('active_synthesized_tools', 0)} tools*\n",
        "5️⃣ *World-Model, Cloud Vault & Thermal Governor*",
        f"   • Mode Governor: `{gov.get('governor_mode', 'APEX_TURBO')}` (`{gov.get('cpu_temp_celsius', 45.0)}°C` | RAM: `{gov.get('ram_available_mb', 0)} MB`)",
        f"   • Brankas Lokal/Cloud: *{vault.get('total_vaulted_files', 0)} berkas* | Alert: *{world.get('unresolved_anomalies_count', 0)}*",
        "   • Proteksi Mutlak: `wa-sheets-bot.service (Quarantined Safe)`",
    ]
    await safe_send_message(context, chat_id, "\n".join(lines))
