"""Router callback query & dispatch menu dashboard."""
from __future__ import annotations

import logging
import os

from telegram import Update
from telegram.ext import ContextTypes

from alfa import tools
from alfa.bot.handlers._compat import (
    bot_module,
    doc_action_callback,
    forward_action_callback,
    is_authorized,
    safe_send_message,
    system_stats,
)
from alfa.bot.handlers._state import _HANDLER_ERR
from alfa.core import database

logger = logging.getLogger("TelegramAIAgent")

async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline button clicks."""
    query = update.callback_query
    if not query:
        return

    data = query.data or ""
    if data.startswith("perm|") or data == "perm_done":
        # HARUS answer() juga di jalur ini — kalau tidak, spinner di client
        # berputar selamanya karena callback tidak pernah dikonfirmasi.
        await query.answer()
        return

    await query.answer()

    user_id = update.effective_user.id if update.effective_user else 0
    chat_id = update.effective_chat.id if update.effective_chat else 0
    if not is_authorized(user_id):
        await query.edit_message_text("⛔ Akses ditolak.")
        return

    data = query.data or ""
    if data == "budget:reset":
        from alfa.core import rate_limiter

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

    try:
        if await doc_action_callback(update, context, data):
            return
    except _HANDLER_ERR as e:
        logger.debug(f"[callback] doc_action gagal: {e}")
    try:
        if await forward_action_callback(update, context, data):
            return
    except _HANDLER_ERR as e:
        logger.debug(f"[callback] forward_action gagal: {e}")
    try:
        from alfa.bot.mode_commands import handle_persona_callback

        if await handle_persona_callback(update, context):
            return
    except _HANDLER_ERR as e:
        logger.debug(f"[callback] persona router gagal: {e}")
    try:
        from alfa.bot.wa_menu import handle_wa_callback

        if await handle_wa_callback(update, context):
            return
    except _HANDLER_ERR as e:
        logger.debug(f"[callback] wa_menu router gagal: {e}")
    try:
        from alfa.bot.advanced_commands import handle_sites_callback

        if await handle_sites_callback(update, context):
            return
    except _HANDLER_ERR as e:
        logger.debug(f"[callback] sites router gagal: {e}")
    try:
        from alfa.bot.cloud_menu import handle_cloud_callback

        if await handle_cloud_callback(update, context):
            return
    except _HANDLER_ERR as e:
        logger.debug(f"[callback] cloud_menu router gagal: {e}")

    if data.startswith("artcraft|"):
        from alfa.tools.desktop.artcraft import artcraft_launch_gui

        parts = data.split("|")
        app_name = parts[2] if len(parts) > 2 else "gridcraft"
        cluster = parts[3].lower() if len(parts) > 3 else "lahat"
        if cluster == "curup":
            excel_path = os.path.expanduser("~/alfa_projects/curup_material/Rekap_Pengambilan_Material_Curup.xlsx")
        else:
            excel_path = os.path.expanduser("~/alfa_projects/lahat_material/Rekap_Pengambilan_Material_Lahat.xlsx")
        res = artcraft_launch_gui(app_name, excel_path if os.path.exists(excel_path) else None)
        await safe_send_message(context, chat_id, f"🚀 {res.get('message', 'Aplikasi diluncurkan.')}")
        return

    # Tombol menu utama → output perintah mengedit pesan menu di tempat
    from alfa.bot.helpers import clear_menu_target, set_menu_target

    set_menu_target(context, query, chat_id, back=(data != "btn_menu"))
    try:
        await _dispatch_menu_callback(update, context, data, user_id, chat_id)
    finally:
        clear_menu_target(context)

async def _dispatch_menu_callback(update, context, data, user_id, chat_id):
    if data == "btn_menu":
        from alfa.bot.basic_commands import menu_command

        await menu_command(update, context)

    elif data in ("btn_sheets", "btn_gdrive", "btn_cloud"):
        from alfa.bot.cloud_menu import (
            render_cloud_hub,
            render_drive_home,
            render_sheets_home,
        )

        if data == "btn_sheets":
            await render_sheets_home(update, context, 0)
        elif data == "btn_gdrive":
            await render_drive_home(update, context)
        else:
            await render_cloud_hub(update, context)

    elif data == "btn_stats":
        stats = system_stats()
        text = (
            f"📊 **Status Server / Laptop Real-Time:**\n\n"
            f"• **CPU:** `{stats.get('cpu')}`\n"
            f"• **RAM:** `{stats.get('ram')}`\n"
            f"• **Swap:** `{stats.get('swap')}`\n"
            f"• **Disk:** `{stats.get('disk')}`\n"
            f"• **Power:** `{stats.get('battery')}`\n"
            f"• **IP:** `{stats.get('ip_addresses')}`\n"
            f"• **Uptime:** `{stats.get('uptime')}`\n\n"
            f"🔥 **Top RAM:**\n"
            + "\n".join([f"  - {p}" for p in stats.get("top_ram_processes", [])])
        )
        await safe_send_message(context, chat_id, text)

    elif data == "btn_rekap_lahat":
        from alfa.tools.telecom_tools import reconcile_whatsapp_material_group

        await safe_send_message(context, chat_id, "⏳ *Menyusun Rekapitulasi Material WhatsApp Cluster Lahat...*")
        res = reconcile_whatsapp_material_group(
            group_name_or_id="pengambilan material lahat",
            auto_launch_gridcraft=False,
        )
        if res.get("status") == "success":
            tot_cable = res.get("total_cable_m", 0)
            cable_str = f"🌐 *Kabel Udara (KU 24):* *{tot_cable:,.0f} meter*\n" if tot_cable > 0 else ""
            acc_map = res.get("accessories_breakdown", {})
            acc_str = ""
            if acc_map:
                acc_str = (
                    f"🔩 *Aksesoris FTTH:*\n"
                    f"• Stoping: {acc_map.get('ACC-STOPING', 0)} pcs | Dead End: {acc_map.get('ACC-DEADEND', 0)} pcs\n"
                    f"• Full Clamp: {acc_map.get('ACC-FULCLAM', 0)} pcs | Suspen: {acc_map.get('ACC-SUSPEN', 0)} pcs\n"
                    f"• Stainless Belt: {acc_map.get('ACC-BELT', 0)} roll | Slack Hanger: {acc_map.get('ACC-HANGER', 0)} pcs\n\n"
                )

            card = (
                f"📦 *REKAPITULASI MATERIAL MASTER LAHAT*\n\n"
                f"📊 *Tiang Lapangan:*\n"
                f"• Total Bersih: *{res.get('total_net')} batang*\n"
                f"• Total Bruto: {res.get('total_bruto')} btg | Retur: {res.get('total_retur')} btg\n\n"
                f"{cable_str}"
                f"{acc_str}"
                f"👷 *Mandor Terverifikasi:* {', '.join(res.get('mandors', []))}\n"
                f"📁 *Berkas Master:* `{res.get('excel_file')}`\n\n"
                f"💡 _Data diperbarui in-place pada Master Ledger Kumulatif tanpa membuat berkas baru._"
            )
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup

            kb = [
                [InlineKeyboardButton("📊 Buka GridCraft Lahat", callback_data="artcraft|open|gridcraft|lahat")],
                [InlineKeyboardButton("📦 Rekap Curup", callback_data="btn_rekap_curup")],
                [InlineKeyboardButton("◀️ Menu Utama", callback_data="btn_menu")],
            ]
            await safe_send_message(context, chat_id, card, reply_markup=InlineKeyboardMarkup(kb))
        else:
            await safe_send_message(context, chat_id, f"⚠️ Gagal merekap material: {res.get('message')}")

    elif data == "btn_rekap_curup":
        from alfa.tools.telecom_tools import reconcile_whatsapp_material_group

        await safe_send_message(context, chat_id, "⏳ *Menyusun Rekapitulasi Material WhatsApp Cluster Curup...*")
        res = reconcile_whatsapp_material_group(
            group_name_or_id="Laporan pengambilan mandor curup",
            auto_launch_gridcraft=False,
        )
        if res.get("status") == "success":
            tot_cable = res.get("total_cable_m", 0)
            cable_str = f"🌐 *Kabel Udara (KU 24):* *{tot_cable:,.0f} meter*\n" if tot_cable > 0 else ""
            acc_map = res.get("accessories_breakdown", {})
            acc_str = ""
            if acc_map:
                acc_lines = []
                if acc_map.get('ACC-STOPING'):
                    acc_lines.append(f"• Stoping: {acc_map['ACC-STOPING']} pcs")
                if acc_map.get('ACC-DEADEND'):
                    acc_lines.append(f"• Dead End: {acc_map['ACC-DEADEND']} pcs")
                if acc_map.get('ACC-FULCLAM'):
                    acc_lines.append(f"• Full Clamp/Pole Clamp: {acc_map['ACC-FULCLAM']} pcs")
                if acc_map.get('ACC-SUSPEN'):
                    acc_lines.append(f"• Suspen: {acc_map['ACC-SUSPEN']} pcs")
                if acc_map.get('ACC-HANGER'):
                    acc_lines.append(f"• Slack Hanger: {acc_map['ACC-HANGER']} pcs")
                if acc_map.get('ACC-BUAYA'):
                    acc_lines.append(f"• Clamp Buaya: {acc_map['ACC-BUAYA']} pcs")
                if acc_map.get('ACC-BELT'):
                    acc_lines.append(f"• Stainless Belt: {acc_map['ACC-BELT']} roll")
                if acc_lines:
                    acc_str = "🔩 *Aksesoris FTTH:*\n" + "\n".join(acc_lines) + "\n\n"

            pole_breakdown = res.get("breakdown", {})
            pole_str = ""
            if pole_breakdown:
                pole_items = [f"{k}: {v} btg" for k, v in pole_breakdown.items() if v != 0]
                if pole_items:
                    pole_str = f" ({', '.join(pole_items)})"

            card = (
                f"📦 *REKAPITULASI MATERIAL MASTER CURUP*\n\n"
                f"📊 *Tiang Lapangan:*\n"
                f"• Total Bersih: *{res.get('total_net')} batang*{pole_str}\n"
                f"• Total Bruto: {res.get('total_bruto')} btg | Retur: {res.get('total_retur')} btg\n\n"
                f"{cable_str}"
                f"{acc_str}"
                f"👷 *Mandor Terverifikasi:* {', '.join(res.get('mandors', []))}\n"
                f"📁 *Berkas Master:* `{res.get('excel_file')}`\n\n"
                f"💡 _Data diperbarui in-place pada Master Ledger Kumulatif tanpa membuat berkas baru._"
            )
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup

            kb = [
                [InlineKeyboardButton("📊 Buka GridCraft Curup", callback_data="artcraft|open|gridcraft|curup")],
                [InlineKeyboardButton("📦 Rekap Lahat", callback_data="btn_rekap_lahat")],
                [InlineKeyboardButton("◀️ Menu Utama", callback_data="btn_menu")],
            ]
            await safe_send_message(context, chat_id, card, reply_markup=InlineKeyboardMarkup(kb))
        else:
            await safe_send_message(context, chat_id, f"⚠️ Gagal merekap material: {res.get('message')}")

    elif data == "btn_daily_briefing":
        from alfa.tools.telecom_tools import generate_daily_executive_briefing

        await safe_send_message(context, chat_id, "⏳ *Menyiapkan Executive Daily Briefing Proyek...*")
        res = generate_daily_executive_briefing(shift="now", only_unreported=False)
        if res.get("status") == "success":
            await safe_send_message(context, chat_id, res.get("briefing_card", "Briefing selesai."))
        else:
            await safe_send_message(context, chat_id, f"⚠️ Gagal menyusun briefing: {res.get('message')}")

    elif data == "btn_artcraft":
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        text = (
            "🎨 *ArtCraft Suite (Desktop Office & CAD Tools):*\n\n"
            "• 📊 *GridCraft*: Analisis spreadsheet Excel dinamis & formula audit.\n"
            "• 📄 *PdfCraft*: Manipulasi PDF (gabung, pisah, watermark, kompresi, enkripsi).\n"
            "• 📐 *CadCraft*: Konversi denah DWG/DXF FTTH ke PDF/SVG, kalkulasi rute kabel.\n"
            "• 🖼️ *PhotoCraft*: Pemrosesan & optimasi dokumentasi foto lapangan.\n"
            "• 💡 *LightCraft*: Penyesuaian eksposur visual foto tiang & material.\n"
            "• ✒️ *DesignCraft*: Desain diagram arsitektur jaringan & mockup vektor.\n\n"
            "Aplikasi dapat dipanggil lewat CLI maupun antarmuka visual GUI."
        )
        kb = [
            [InlineKeyboardButton("📊 Buka GridCraft Lahat", callback_data="artcraft|open|gridcraft")],
            [InlineKeyboardButton("◀️ Menu Utama", callback_data="btn_menu")],
        ]
        await safe_send_message(context, chat_id, text, reply_markup=InlineKeyboardMarkup(kb))

    elif data == "btn_ram":
        from alfa.bot.advanced_commands import ram_command

        await ram_command(update, context)

    elif data == "btn_memory":
        memories = await database.get_all_memories(user_id)
        if not memories:
            await safe_send_message(
                context, chat_id, "🧠 Memori jangka panjang masih kosong."
            )
        else:
            text = f"🧠 **Memori Tersimpan ({len(memories)} item):**\n\n"
            for m in memories:
                text += f"• *[{m['category'].upper()}]* `{m['key_topic']}`:\n  {m['content']}\n\n"
            await safe_send_message(context, chat_id, text)

    elif data == "btn_toggle_voice":
        is_on = await database.toggle_voice_setting(user_id)
        status_str = "AKTIF 🔊" if is_on else "NONAKTIF 🔇"
        await safe_send_message(
            context, chat_id, f"🎙️ Mode Balasan Suara sekarang: **{status_str}**"
        )

    elif data == "btn_python_info":
        info_text = (
            "📈 **Python Sandbox & Data Plotter:**\n\n"
            "Anda dapat meminta bot untuk:\n"
            "• Menghitung data kompleks, rumus matematika, atau simulasi.\n"
            "• Membuat grafik statistik / visualisasi (misal: *'Buatkan grafik perbandingan penjualan 2024-2026'*).\n"
            "• Menjalankan snippet kode Python secara langsung.\n"
            "Grafik yang dihasilkan akan otomatis dikirimkan sebagai gambar langsung ke chat Telegram!"
        )
        await safe_send_message(context, chat_id, info_text)

    elif data == "btn_clear":
        await database.clear_user_chat_history(user_id)
        await safe_send_message(
            context, chat_id, "🧹 Konteks percakapan telah direset."
        )

    elif data == "btn_help":
        help_text = (
            "📖 **Daftar Perintah Lengkap:**\n\n"
            "🧭 **Mode Eksekusi:**\n"
            "• `/mode single|swarm|status` - Alih/lihat mode\n"
            "• `/single [tugas]` - Single agent (pindah / sekali-jalan)\n"
            "• `/status` - Status mode, swarm, agen, server\n\n"
            "⚡ **Swarm Multi-Agent:**\n"
            "• `/swarm <tugas>` - Eksekusi nyata tim agen\n"
            "• `/swarm status|cancel` - Status / hentikan misi\n"
            "• `/swarm model <id|nama> <provider> [model]` - Ganti model agen\n"
            "• `/swarm template [nama]` - Misi siap pakai\n"
            "• `/rapat <topik>` - Rapat plan (diskusi + action plan)\n"
            "• `/resume [session]` - Lanjutkan sesi swarm\n"
            "• `/cancel` - Hentikan misi berjalan\n\n"
            "🤖 **Agen & Tools:**\n"
            "• `/agents` - Daftar workforce\n"
            "• `/persona [nama|id|reset]` - Persona single-mode\n"
            "• `/tools` - 148 tools real\n"
            "• `/cekagen` - Audit kesehatan konfigurasi\n\n"
            "☁️ **Google Sheets & Drive:**\n"
            "• `/sheets` (`/sheet`) - Panel file & tab Google Sheets terhubung\n"
            "• `/drive` (`/gdrive`) - Jelajahi Google Drive cloud & mount lokal\n"
            "• `/cloud` - Hub terpadu Google Sheets & Google Drive\n"
            "• `/setsheet [link|id]` - Konfigurasi spreadsheet aktif\n\n"
            "🔁 **Otomasi:**\n"
            "• `/pipeline [list|run <id>]` - Workflow DAG\n"
            "• `/tugas` - Subagent latar & checkpoint\n"
            "• `/cron` - Tugas berulang (single/swarm)\n"
            "• `/budget` - Monitor kuota token harian\n"
            "• `/proactive` - Inisiatif ambient\n\n"
            "🧰 **Lainnya:**\n"
            "• `/menu` `/dashboard` `/sites` `/wa` `/keys` (`/vault`)\n"
            "• `/wachat` `/wamasuk` `/wakirim` `/wacari` — pantau & kirim WA\n"
            "• `/waformat` `/wareport` — atur & baca pencatatan otomatis\n"
            "• `/waringkas [format]` — digest cerdas + sorotan AI (otomatis tiap 07:00)\n"
            "• `/stats` `/memory` `/voice` `/clear` (`/reset`) `/id`\n"
            "• Alias: `/eksekusi`=`/swarm` • `/meeting`=`/rapat` • `/tasks`=`/cron` • `/stop`=`/cancel`\n"
            "• Alias: `/web` `/app`=`/dashboard` • `/washeets`=`/wa` • `/batal`=`/cancel` • `/resume_swarm`=`/resume` • `/reset`=`/clear`\n\n"
            "💬 **Contoh Perintah AI:**\n"
            "- *'Ambil screenshot desktop sekarang'* -> Mengirim foto layar aktif.\n"
            "- *'/swarm buatkan script monitoring RAM dan jalankan'* -> Misi tim.\n"
            "- *'/rapat strategi hemat token API'* -> Diskusi + action plan.\n"
            "- *'Buatkan grafik plot fungsi sinus dan cosinus'* -> Menghasilkan gambar grafik.\n"
            "- *'Cari informasi berita AI terkini hari ini'* -> Browsing real-time.\n"
            "- *'Ingat bahwa email dev saya adalah admin@example.com'* -> Simpan memori.\n"
            "- *'Ingatkan saya jam 18:00 untuk evaluasi project'* -> Set pengingat otomatis."
        )
        await safe_send_message(context, chat_id, help_text)

    elif data in ("btn_mode_single", "btn_mode_swarm", "btn_status"):
        from alfa.bot.mode_commands import (
            get_telegram_mode_sync,
            set_telegram_mode_sync,
            status_command,
        )

        if data == "btn_mode_single":
            set_telegram_mode_sync("single")
            await safe_send_message(
                context, chat_id, "🧍 **Mode SINGLE aktif.** Chat biasa ditangani 1 agen otonom."
            )
        elif data == "btn_mode_swarm":
            set_telegram_mode_sync("swarm")
            await safe_send_message(
                context,
                chat_id,
                "⚡ **Mode SWARM aktif.** Chat teks berikutnya dieksekusi tim multi-agen.\n"
                "Kembali: `/mode single` • Batal: `/cancel`",
            )
        else:
            await status_command(update, context)

    elif data in ("btn_meeting_info", "btn_swarm_info"):
        if data == "btn_meeting_info":
            await safe_send_message(
                context,
                chat_id,
                "🏛️ **Rapat AI (Plan):** `/rapat <topik>`\n"
                "Contoh: `/rapat strategi hemat token API`\n"
                "Hasil: diskusi round-table + konsensus + action plan.",
            )
        else:
            swarm_note = "(mode swarm aktif ⚡)"
            try:
                from alfa.bot.mode_commands import get_telegram_mode_sync

                if get_telegram_mode_sync() != "swarm":
                    swarm_note = "(mode single 🧍 — tetap bisa sekali-jalan)"
            except _HANDLER_ERR:
                pass
            await safe_send_message(
                context,
                chat_id,
                f"⚡ **Eksekusi Swarm:** `/swarm <tugas>` {swarm_note}\n"
                "Contoh: `/swarm buatkan script monitoring RAM dan jalankan`\n"
                "Atau aktifkan permanen: `/mode swarm` lalu chat biasa.",
            )

    elif data == "btn_swarm_export_last":
        from alfa.swarm.deliberation import (
            export_meeting_report_files,
            load_last_meeting_state,
        )

        st = load_last_meeting_state()
        if not st:
            await safe_send_message(
                context,
                chat_id,
                "ℹ️ Belum ada riwayat rapat terakhir yang tersimpan untuk diekspor.",
            )
        else:
            files = st.get("report_files") or {}
            if not files or not all(os.path.exists(p) for p in files.values()):
                files = export_meeting_report_files(st)
            sent_any = False
            for fmt, fpath in files.items():
                if fpath and os.path.exists(fpath):
                    try:
                        with open(fpath, "rb") as doc_f:
                            await context.bot.send_document(
                                chat_id=chat_id,
                                document=doc_f,
                                filename=os.path.basename(fpath),
                                caption=f"📄 Laporan Rapat ({fmt.upper()}): {st.get('topic', '')[:80]}",
                            )
                        sent_any = True
                    except Exception as doc_err:
                        logger.warning(f"Failed sending meeting report {fpath}: {doc_err}")
            if not sent_any:
                await safe_send_message(
                    context, chat_id, "⚠️ Gagal mengirim file laporan rapat."
                )

    elif data == "btn_swarm_exec_last":
        from alfa.bot.mode_commands import format_swarm_result
        from alfa.swarm import engine as swarm_engine
        from alfa.swarm.deliberation import load_last_meeting_state

        st = load_last_meeting_state()
        if not st or not st.get("topic"):
            await safe_send_message(
                context,
                chat_id,
                "ℹ️ Belum ada Action Plan rapat terakhir yang bisa dieksekusi.",
            )
        else:
            exec_topic = f"{st.get('topic', '')} — Eksekusi Action Plan: {str(st.get('action_plan') or st.get('consensus') or '')[:350]}"
            await safe_send_message(
                context,
                chat_id,
                f"⚡ **Mengeksekusi Action Plan Rapat Terakhir...**\n📌 _{st.get('topic', '')[:120]}_",
            )
            res = await swarm_engine.conduct_multi_agent_meeting(
                topic=exec_topic, rounds=1, mode="execute"
            )
            steps_txt, final_txt, out_files = format_swarm_result(res)
            await safe_send_message(context, chat_id, steps_txt)
            await safe_send_message(context, chat_id, final_txt)
            for fp in out_files[:4]:
                if fp and os.path.exists(fp):
                    try:
                        with open(fp, "rb") as df:
                            await context.bot.send_document(
                                chat_id=chat_id,
                                document=df,
                                filename=os.path.basename(fp),
                            )
                    except Exception as exc:
                        logger.debug("Kegagalan tak terduga di _dispatch_menu_callback: %s", exc)

    elif data in ("btn_agents", "btn_tools", "btn_pipeline", "btn_tasks"):
        if data == "btn_agents":
            mod = bot_module()
            fn = getattr(mod, "agents_command", None) if mod else None
            if callable(fn):
                await fn(update, context)
            else:
                from alfa.bot.advanced_commands import agents_command as _agents

                await _agents(update, context)
        elif data == "btn_tools":
            from alfa.bot.mode_commands import tools_command as _tools

            await _tools(update, context)
        elif data == "btn_pipeline":
            from alfa.bot.mode_commands import pipeline_command as _pipe

            await _pipe(update, context)
        else:
            from alfa.bot.mode_commands import tugas_command as _tugas

            await _tugas(update, context)

    elif data == "btn_persona":
        from alfa.bot.mode_commands import render_persona_menu as _pm

        await _pm(update, context)

    elif data in ("btn_keys", "btn_cekagen", "btn_cron", "btn_proactive", "btn_dashboard", "btn_wa", "btn_sites", "btn_budget"):
        mod = bot_module()
        mapping = {
            "btn_keys": "keys_command",
            "btn_cekagen": "cekagen_command",
            "btn_cron": "cron_command",
            "btn_proactive": "proactive_command",
            "btn_dashboard": "dashboard_command",
            "btn_wa": "wa_command",
            "btn_sites": "sites_command",
            "btn_budget": "budget_command",
        }
        fn = getattr(mod, mapping[data], None) if mod else None
        if not callable(fn):
            from alfa.bot import advanced_commands as _ac
            from alfa.bot import basic_commands as _bc

            fn = getattr(_ac, mapping[data], None) or getattr(_bc, mapping[data], None)
        if callable(fn):
            await fn(update, context)

    elif data == "btn_wa_status":
        res = tools.manage_wa_sheets_bot("status")
        st_status = "🟢 RUNNING (Aktif)" if res.get("is_running") else "🔴 STOPPED (Mati)"
        await safe_send_message(
            context,
            chat_id,
            f"📱 **Status WhatsApp Bot:** {st_status}\n\n```\n{res.get('details', '')}\n```",
        )

    elif data == "btn_wa_restart":
        res = tools.manage_wa_sheets_bot("restart")
        await safe_send_message(
            context, chat_id, f"🔄 {res.get('message', 'Restart diproses.')}"
        )

    elif data == "btn_wa_start":
        res = tools.manage_wa_sheets_bot("start")
        await safe_send_message(
            context, chat_id, f"▶️ {res.get('message', 'Start diproses.')}"
        )

    elif data == "btn_wa_stop":
        res = tools.manage_wa_sheets_bot("stop")
        await safe_send_message(
            context, chat_id, f"⏹️ {res.get('message', 'Stop diproses.')}"
        )
