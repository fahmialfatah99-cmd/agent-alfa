"""Message and callback handlers for ALFA Telegram Bot."""

import asyncio
import io
import logging
import os
import sys
import time
from typing import Any

from telegram import Update, constants
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from alfa import tools
from alfa.bot.config import (
    GEMINI_MODEL,
    _main_brain_gemini_model,
    is_authorized,
    resolve_main_gemini,
)
from alfa.bot.helpers import (
    safe_send_message,
    send_typing_loop,
    should_reply_with_text_instead_of_voice,
)
from alfa.bot.streamer import TelegramStreamer
from alfa.bot.turn_executor import run_agent_turn
from alfa.core import database
from alfa.media import tts_engine
from alfa.tools import SANDBOX_DIR, get_system_stats

logger = logging.getLogger("TelegramAIAgent")

_HANDLER_ERR = (
    TelegramError,
    OSError,
    ValueError,
    RuntimeError,
    TypeError,
    KeyError,
    AttributeError,
    ImportError,
)

# Registry untuk melacak task yang sedang berjalan per chat_id agar bisa di-cancel instan via /cancel
ACTIVE_CHAT_TASKS: dict[int, asyncio.Task] = {}


# --- Sapaan ringan: jawab langsung TANPA agent turn / tools ----------------
# Cegah model asal memanggil tool (mis. screenshot) untuk "halo".
_GREETING_EXACT = {
    "halo", "hallo", "hello", "hi", "hai", "hei", "hey", "hola",
    "pagi", "siang", "sore", "malam",
    "selamat pagi", "selamat siang", "selamat sore", "selamat malam",
    "assalamualaikum", "assalamu'alaikum", "salam",
    "tes", "test", "testing", "ping", "p",
    "apa kabar", "gimana kabar", "bagaimana kabar",
    "ok", "oke", "okey", "okay", "siap", "sip", "mantap",
    "makasih", "terima kasih", "thanks", "thank you", "trims",
    "baik", "noted", "hehe", "haha", "wkwk", "👍",
}


def greeting_reply(text: str) -> str | None:
    """Balasan sapaan instan, atau None bila bukan sapaan murni.

    Hanya cocok bila SELURUH pesan = sapaan (tanpa permintaan lain),
    jadi 'oke tolong screenshot' tetap masuk agent seperti biasa.
    """
    norm = (text or "").lower().strip()
    for ch in "!?.,-—…":
        norm = norm.replace(ch, " ")
    norm = " ".join(norm.split())
    if norm in _GREETING_EXACT:
        return (
            "Halo juga! 👋 Saya **ALFA**, asisten AI otonom.\n"
            "Ada yang bisa dibantu? Ketik `/menu` untuk lihat semua fitur."
        )
    return None


def _get_bot_module():
    """Retrieve telegram_bot module to support mocking in tests."""
    return sys.modules.get("alfa.bot.telegram_bot")


def _is_authorized(user_id: int) -> bool:
    mod = _get_bot_module()
    if mod and hasattr(mod, "is_authorized"):
        return bool(mod.is_authorized(user_id))
    return is_authorized(user_id)


async def _run_agent_turn(*args, **kwargs):
    mod = _get_bot_module()
    if mod and hasattr(mod, "run_agent_turn"):
        return await mod.run_agent_turn(*args, **kwargs)
    return await run_agent_turn(*args, **kwargs)


async def _check_and_send_media_artifacts(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    turn_start_time: float | None = None,
):
    mod = _get_bot_module()
    if (
        mod
        and hasattr(mod, "check_and_send_media_artifacts")
        and mod.check_and_send_media_artifacts is not check_and_send_media_artifacts
    ):
        try:
            return await mod.check_and_send_media_artifacts(
                update, context, turn_start_time=turn_start_time
            )
        except TypeError:
            return await mod.check_and_send_media_artifacts(update, context)
    return await check_and_send_media_artifacts(
        update, context, turn_start_time=turn_start_time
    )


_RECENT_DOCS: dict[int, dict[str, Any]] = {}


async def handle_doc_action_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE, data: str
) -> bool:
    """Handle 1-click interactive document export/analysis buttons."""
    if not data.startswith("docact:"):
        return False

    action = data.split(":", 1)[1]
    chat_id = update.effective_chat.id if update.effective_chat else 0
    user_id = update.effective_user.id if update.effective_user else 0

    doc_info = _RECENT_DOCS.get(chat_id)
    if not doc_info:
        await context.bot.send_message(
            chat_id=chat_id,
            text="⚠️ Data dokumen referensi sudah kedaluwarsa. Silakan unggah kembali dokumennya.",
        )
        return True

    turn_start_time = time.time()
    file_name = doc_info.get("file_name", "dokumen")
    txt_ctx = doc_info.get("txt_ctx", "")
    is_batch = doc_info.get("is_batch", False)
    docs_count = doc_info.get("docs_count", 1)
    file_names = doc_info.get("file_names", [file_name])

    # Bersihkan file keluaran lama di sandbox sebelum turn aksi agar tak terjadi double output
    if os.path.exists(SANDBOX_DIR):
        target_exts = {
            "excel": (".xlsx", ".xls", ".csv"),
            "pdf": (".pdf",),
        }.get(action, ())
        for f in os.listdir(SANDBOX_DIR):
            if any(f.lower().endswith(ext) for ext in target_exts):
                try:
                    os.remove(os.path.join(SANDBOX_DIR, f))
                except OSError:
                    pass

    if is_batch:
        file_list_str = ", ".join(file_names)
        action_prompts = {
            "pdf": (
                f"{txt_ctx}\n\nInstruksi Pengguna: Buatkan SATU (1) berkas laporan PDF resmi gabungan yang rapi dan profesional "
                f"berisi rincian material dari SELURUH {docs_count} dokumen ({file_list_str}) di atas menggunakan tool generate_pdf_report. "
                "SATUKAN semua dalam 1 file PDF lengkap dengan rekapitulasi total. Pastikan berkas tersimpan ke disk."
            ),
            "excel": (
                f"{txt_ctx}\n\nInstruksi Pengguna: Buatkan SATU (1) berkas spreadsheet Excel (.xlsx) gabungan yang komprehensif dan terstruktur rapi "
                f"berisi rincian material dari SELURUH {docs_count} berkas dokumen ({file_list_str}) di atas menggunakan tool generate_excel_spreadsheet "
                "dengan filename 'Rekap_Material_Gabungan.xlsx'.\n\n"
                "ATURAN MUTLAK:\n"
                "1. SATUKAN SEMUA rincian material dari SELURUH berkas ke dalam SATU file spreadsheet ini (DILARANG membuat file terpisah untuk masing-masing dokumen).\n"
                "2. Kolom tabel: ['No', 'Nama Dokumen / DO', 'Cluster', 'Nama Material / Item', 'QTY', 'Satuan'].\n"
                "3. HANYA panggil tool generate_excel_spreadsheet TEPAT SATU KALI untuk menghasilkan file gabungan ini.\n"
                "4. Pastikan rows_json berupa list of lists sesuai urutan headers di atas."
            ),
            "deep": (
                f"{txt_ctx}\n\nInstruksi Pengguna: Lakukan audit dan rekonsiliasi data mendalam untuk SELURUH {docs_count} dokumen "
                f"({file_list_str}): hitung total akumulasi material antar dokumen, verifikasi varians/anomali, dan sajikan rincian matematisnya secara presisi."
            ),
        }
    else:
        action_prompts = {
            "pdf": (
                f"{txt_ctx}\n\nInstruksi Pengguna: Buatkan berkas laporan PDF resmi yang rapi dan profesional "
                f"dari data dokumen '{file_name}' di atas menggunakan tool generate_pdf_report. Pastikan berkas tersimpan ke disk."
            ),
            "excel": (
                f"{txt_ctx}\n\nInstruksi Pengguna: Buatkan berkas spreadsheet Excel (.xlsx) baru yang terstruktur rapi "
                f"dari data dokumen '{file_name}' di atas menggunakan tool generate_excel_spreadsheet. "
                "Gunakan kolom: ['No', 'Nama Material / Item', 'QTY', 'Satuan'] dan pastikan hanya memanggil tool tepat satu kali. Pastikan berkas tersimpan ke disk."
            ),
            "deep": (
                f"{txt_ctx}\n\nInstruksi Pengguna: Lakukan audit data mendalam pada dokumen '{file_name}': hitung total rekonsiliasi, "
                f"verifikasi varians/selisih angka, dan sajikan rincian matematisnya secara presisi."
            ),
        }

    prompt = action_prompts.get(action)
    if not prompt:
        return False

    action_labels = {
        "pdf": "📄 Menyiapkan laporan PDF resmi...",
        "excel": "📊 Menghasilkan berkas spreadsheet Excel...",
        "deep": "🔍 Menjalankan analisis data mendalam...",
    }
    status_msg = await context.bot.send_message(
        chat_id=chat_id, text=action_labels.get(action, "Memproses permintaan...")
    )

    stop_typing = asyncio.Event()
    typing_task = asyncio.create_task(
        send_typing_loop(chat_id, context, stop_typing, constants.ChatAction.TYPING)
    )

    try:
        reply = await _run_agent_turn(
            user_id=user_id,
            user_prompt=prompt,
            chat_id=chat_id,
        )
    finally:
        stop_typing.set()
        await typing_task
        try:
            await status_msg.delete()
        except (TelegramError, OSError):
            pass

    await safe_send_message(context, chat_id, reply)
    await _check_and_send_media_artifacts(
        update, context, turn_start_time=turn_start_time
    )
    return True


async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline button clicks."""
    query = update.callback_query
    if not query:
        return

    data = query.data or ""
    if data.startswith("perm|") or data == "perm_done":
        return

    await query.answer()

    user_id = update.effective_user.id if update.effective_user else 0
    chat_id = update.effective_chat.id if update.effective_chat else 0
    if not _is_authorized(user_id):
        await query.edit_message_text("⛔ Akses ditolak.")
        return

    data = query.data or ""
    try:
        if await handle_doc_action_callback(update, context, data):
            return
    except _HANDLER_ERR as e:
        logger.debug(f"[callback] doc_action gagal: {e}")
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

    elif data == "btn_stats":
        stats = get_system_stats()
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

    elif data in ("btn_agents", "btn_tools", "btn_pipeline", "btn_tasks"):
        if data == "btn_agents":
            mod = _get_bot_module()
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
        mod = _get_bot_module()
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
        st = "🟢 RUNNING (Aktif)" if res.get("is_running") else "🔴 STOPPED (Mati)"
        await safe_send_message(
            context,
            chat_id,
            f"📱 **Status WhatsApp Bot:** {st}\n\n```\n{res.get('details', '')}\n```",
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


async def check_and_send_media_artifacts(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    turn_start_time: float | None = None,
):
    """
    Checks if any screenshot, webcam frame, Python chart, or document (PDF, Excel, PPTX, ZIP)
    was created during this turn and dispatches it directly to the Telegram user.
    Stale artifacts created before turn_start_time are pruned and never dispatched.
    """
    chat_id = update.effective_chat.id if update.effective_chat else 0
    if not os.path.exists(SANDBOX_DIR):
        return

    named_media = [
        ("desktop_screen.png", "🖥️ Tangkapan Layar Desktop"),
        ("webcam_frame.jpg", "📷 Foto Kamera Webcam"),
        ("generated_plot.png", "📊 Grafik Visualisasi Data (Python)"),
        ("dataset_analysis_chart.png", "📊 Grafik Analisis Dataset"),
        ("browser_screenshot.png", "🌐 Tangkapan Layar Browser (Camofox)"),
    ]

    for filename, caption in named_media:
        full_path = os.path.join(SANDBOX_DIR, filename)
        if os.path.exists(full_path) and os.path.getsize(full_path) > 0:
            mtime = os.path.getmtime(full_path)
            if turn_start_time is not None and mtime < (turn_start_time - 1.0):
                # Stale artifact from previous turn/task: delete and ignore
                try:
                    os.remove(full_path)
                except OSError:
                    pass
                continue
            try:
                with open(full_path, "rb") as photo_file:
                    await context.bot.send_photo(
                        chat_id=chat_id, photo=photo_file, caption=caption
                    )
            except _HANDLER_ERR as send_err:
                logger.error(f"Failed to send media artifact {filename}: {send_err}")
            finally:
                try:
                    os.remove(full_path)
                except OSError:
                    pass

    raw_candidates = []
    for fname in os.listdir(SANDBOX_DIR):
        fpath = os.path.join(SANDBOX_DIR, fname)
        if tools.is_internal_sandbox_artifact(fname):
            continue
        if tools.is_source_code_file(fname):
            continue
        if not os.path.isfile(fpath) or os.path.getsize(fpath) == 0:
            continue

        mtime = os.path.getmtime(fpath)
        if turn_start_time is not None and mtime < (turn_start_time - 1.0):
            # Stale file from earlier tests or background jobs: cleanup and skip
            try:
                os.remove(fpath)
            except OSError:
                pass
            continue
        raw_candidates.append((fname, fpath, mtime))

    # Kelompokkan berkas gambar dan dokumen
    docs_by_ext: dict[str, list[tuple[str, str, float]]] = {}
    images_to_send: list[tuple[str, str]] = []

    for fname, fpath, mtime in raw_candidates:
        ext = os.path.splitext(fname)[1].lower()
        if ext in [".png", ".jpg", ".jpeg", ".webp"]:
            images_to_send.append((fname, fpath))
        else:
            docs_by_ext.setdefault(ext, []).append((fname, fpath, mtime))

    # Kirim foto / grafik
    for fname, fpath in images_to_send:
        caption = (
            "📊 Grafik Visualisasi Data (Python)"
            if fname.startswith("generated_plot")
            else f"📸 Berkas Gambar: {fname}"
        )
        try:
            with open(fpath, "rb") as pf:
                await context.bot.send_photo(
                    chat_id=chat_id, photo=pf, caption=caption
                )
        except _HANDLER_ERR as img_err:
            logger.error(f"Failed to send image {fname}: {img_err}")
        finally:
            try:
                os.remove(fpath)
            except OSError:
                pass

    # Kirim dokumen dengan proteksi anti-duplicate per tipe berkas (cegah double file Excel/PDF)
    generic_names = {".xlsx": "data.xlsx", ".pdf": "laporan.pdf", ".pptx": "presentasi.pptx"}
    for ext, file_list in docs_by_ext.items():
        if len(file_list) > 1:
            gen_name = generic_names.get(ext)
            if gen_name and any(item[0].lower() != gen_name.lower() for item in file_list):
                # Buang file generic (misal: data.xlsx) jika ada file dengan nama spesifik (misal: Rekap_Material_Gabungan.xlsx)
                kept = []
                for item in file_list:
                    if item[0].lower() == gen_name.lower():
                        try:
                            os.remove(item[1])
                        except OSError:
                            pass
                    else:
                        kept.append(item)
                file_list = kept

        # Jika masih lebih dari 1 file dengan ekstensi sama, pilih 1 file termutakhir (mtime terbesar)
        if len(file_list) > 1:
            file_list.sort(key=lambda x: x[2], reverse=True)
            for item in file_list[1:]:
                try:
                    os.remove(item[1])
                except OSError:
                    pass
            file_list = [file_list[0]]

        for fname, fpath, _ in file_list:
            try:
                with open(fpath, "rb") as df:
                    await context.bot.send_document(
                        chat_id=chat_id, document=df, caption=f"📄 Berkas: {fname}"
                    )
            except _HANDLER_ERR as doc_err:
                logger.error(f"Failed to send document {fname}: {doc_err}")
            finally:
                try:
                    os.remove(fpath)
                except OSError:
                    pass


async def _long_turn_nudge(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    turn_task: "asyncio.Task",
    streamer,
    delay: float = 45.0,
) -> None:
    """Kirim SATU pesan penenang bila turn single-mode lama tanpa update terlihat."""
    try:
        await asyncio.sleep(delay)
        if turn_task.done():
            return
        if streamer is not None and getattr(streamer, "message_id", None):
            return  # streaming sudah tampil -> tak perlu nudge
        await safe_send_message(
            context,
            chat_id,
            "🧠 Masih diproses (menjalankan tools + menalar) — mohon tunggu, "
            "hasil dikirim utuh setelah selesai.",
        )
    except asyncio.CancelledError:
        pass
    except _HANDLER_ERR as e:
        logger.debug(f"[nudge] gagal: {e}")


async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming text messages."""
    if not update.message or not update.message.text:
        return
    user_id = update.effective_user.id if update.effective_user else 0
    chat_id = update.effective_chat.id if update.effective_chat else 0
    if not _is_authorized(user_id):
        await safe_send_message(
            context, chat_id, "⛔ Akses ditolak. ID Anda belum terdaftar di whitelist."
        )
        return

    user_text = update.message.text.strip()
    turn_start_time = time.time()
    swarm_files: list[str] = []

    # Sapaan murni → jawab instan, JANGAN lewat agent (hemat token + anti tool nyasar).
    fast = greeting_reply(user_text)
    if fast is not None:
        try:
            await database.save_chat_message(user_id, "user", user_text)
            await database.save_chat_message(user_id, "model", fast)
        except _HANDLER_ERR as db_err:
            logger.debug(f"[greeting] simpan riwayat gagal: {db_err}")
        await safe_send_message(context, chat_id, fast)
        return

    streamer = None
    stop_typing = None
    typing_task = None
    try:
        streamer = TelegramStreamer(context=context, chat_id=chat_id, initial_text=None)
        await streamer.start()
    except _HANDLER_ERR as se:
        logger.warning(f"[TelegramStreamer] Start failed: {se}")
        streamer = None

    if not streamer:
        stop_typing = asyncio.Event()
        typing_task = asyncio.create_task(
            send_typing_loop(chat_id, context, stop_typing, constants.ChatAction.TYPING)
        )

    try:
        use_swarm = False
        try:
            from alfa.bot.mode_commands import get_telegram_mode_sync

            use_swarm = get_telegram_mode_sync() == "swarm"
        except _HANDLER_ERR:
            use_swarm = False

        if use_swarm:
            # Mode SWARM: chat teks biasa = misi tim multi-agen.
            # Satu pesan status live (di-edit berkala) agar tak terkesan diam.
            if streamer:
                try:
                    await streamer.finalize(
                        "⚡ **Mode SWARM:** misi diteruskan ke tim multi-agen..."
                    )
                except _HANDLER_ERR:
                    pass
                streamer = None
            from alfa.bot.progress import SwarmProgressReporter

            reporter = SwarmProgressReporter(context, chat_id, user_text)
            await reporter.start()
            from alfa.bot.mode_commands import format_swarm_result, run_swarm_task

            swarm_task = asyncio.create_task(run_swarm_task(user_text))
            ACTIVE_CHAT_TASKS[chat_id] = swarm_task
            try:
                result = await swarm_task
            except asyncio.CancelledError:
                from alfa.swarm.workspace_hygiene import request_cancel_swarm

                request_cancel_swarm()
                await reporter.stop("⏹ Misi dibatalkan pengguna.")
                reply = "⏹ **Misi swarm telah dihentikan atas permintaan Anda.**"
                logger.info(f"[handle_text:swarm] Swarm task untuk chat_id={chat_id} dibatalkan pengguna.")
            except _HANDLER_ERR as e:
                logger.error(f"[handle_text:swarm] gagal untuk {user_id}: {e}", exc_info=True)
                await reporter.stop("❌ Misi gagal.")
                reply = (
                    "❌ Misi swarm gagal diproses "
                    f"({type(e).__name__}: {str(e)[:200]}). "
                    "Coba `/mode single` untuk 1 agen, atau kirim ulang."
                )
            else:
                if result.get("status") == "cancelled":
                    await reporter.stop("⏹ Misi swarm dihentikan pengguna.")
                    reply = "⏹ **Misi swarm telah dihentikan.** Eksekusi dibatalkan sebelum selesai."
                    swarm_files = []
                else:
                    await reporter.stop("✅ Selesai — laporan lengkap di bawah ⬇️")
                    steps_text, final_text, files = format_swarm_result(result)
                    await safe_send_message(context, chat_id, steps_text)
                    reply = final_text
                    swarm_files = files or []
            finally:
                ACTIVE_CHAT_TASKS.pop(chat_id, None)
        else:
            turn_task = asyncio.create_task(
                _run_agent_turn(
                    user_id=user_id,
                    user_prompt=user_text,
                    chat_id=chat_id,
                    streamer=streamer,
                )
            )
            ACTIVE_CHAT_TASKS[chat_id] = turn_task
            nudge_task = asyncio.create_task(
                _long_turn_nudge(context, chat_id, turn_task, streamer)
            )
            try:
                reply = await turn_task
            except asyncio.CancelledError:
                reply = "⏹ **Proses agen telah dibatalkan atas permintaan Anda.**"
                logger.info(f"[handle_text] Single turn untuk chat_id={chat_id} dibatalkan pengguna.")
            finally:
                ACTIVE_CHAT_TASKS.pop(chat_id, None)
                nudge_task.cancel()
                try:
                    await nudge_task
                except (asyncio.CancelledError, *_HANDLER_ERR):
                    pass
    except _HANDLER_ERR as e:
        # Jangan pernah diam: kegagalan turn harus tetap dibalas ke user.
        logger.error(f"[handle_text] turn gagal untuk {user_id}: {e}", exc_info=True)
        reply = (
            "❌ Maaf, permintaannya gagal diproses "
            f"({type(e).__name__}: {str(e)[:200]}). "
            "Coba kirim ulang perintahnya."
        )
    finally:
        if stop_typing and typing_task:
            stop_typing.set()
            await typing_task

    if streamer:
        try:
            await streamer.finalize(reply)
        except _HANDLER_ERR as fe:
            logger.error(
                f"[TelegramStreamer] Finalize failed: {fe}, fallback to safe_send_message"
            )
            await safe_send_message(context, chat_id, reply)
    else:
        await safe_send_message(context, chat_id, reply)

    await _check_and_send_media_artifacts(
        update, context, turn_start_time=turn_start_time
    )

    for fpath in swarm_files:
        try:
            with open(fpath, "rb") as f_doc:
                await context.bot.send_document(
                    chat_id=chat_id,
                    document=f_doc,
                    filename=os.path.basename(fpath),
                    caption=f"📁 **File Deliverable Swarm:** `{os.path.basename(fpath)}`",
                )
        except _HANDLER_ERR as file_err:
            logger.warning(f"Failed to send swarm file {fpath}: {file_err}")

    # If voice mode enabled and content is conversational, send voice note
    mod = _get_bot_module()
    db_mod = getattr(mod, "database", database) if mod else database
    settings = await db_mod.get_user_settings(user_id)
    if settings.get("voice_reply") and not should_reply_with_text_instead_of_voice(
        reply
    ):
        voice_path = None
        try:
            await context.bot.send_chat_action(
                chat_id=chat_id, action=constants.ChatAction.RECORD_VOICE
            )
            voice_path = await tts_engine.text_to_speech_ogg(reply)
            with open(voice_path, "rb") as voice_file:
                await update.message.reply_voice(voice=voice_file)
        except _HANDLER_ERR as tts_err:
            logger.error(f"TTS sending error: {tts_err}")
        finally:
            if voice_path and os.path.exists(voice_path):
                try:
                    os.remove(voice_path)
                except OSError:
                    pass


async def handle_voice_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle incoming Voice Notes & Audio.
    Smart Adaptive Reply: Sends ONLY ONE response (either Voice Note OR Text) based on content.
    """
    if not update.message:
        return
    user_id = update.effective_user.id if update.effective_user else 0
    chat_id = update.effective_chat.id if update.effective_chat else 0
    if not _is_authorized(user_id):
        await safe_send_message(context, chat_id, "⛔ Akses ditolak.")
        return

    voice = update.message.voice or update.message.audio
    if not voice:
        return
    turn_start_time = time.time()

    stop_typing = asyncio.Event()
    typing_task = asyncio.create_task(
        send_typing_loop(
            chat_id, context, stop_typing, constants.ChatAction.RECORD_VOICE
        )
    )
    try:
        file_obj = await context.bot.get_file(voice.file_id)
        voice_bytes_io = io.BytesIO()
        await file_obj.download_to_memory(voice_bytes_io)
        voice_bytes = voice_bytes_io.getvalue()

        from google.genai import types

        mime = getattr(voice, "mime_type", None) or "audio/ogg"
        audio_part = types.Part.from_bytes(data=voice_bytes, mime_type=mime)

        transcription_text = None
        transcribe_client, _, _ = resolve_main_gemini()
        if transcribe_client:
            transcribe_models = []
            for candidate in (
                _main_brain_gemini_model(),
                GEMINI_MODEL,
                "gemini-3.5-flash",
                "gemini-flash-lite-latest",
                "gemini-3-flash-preview",
            ):
                name = (candidate or "").strip()
                if name and name not in transcribe_models:
                    transcribe_models.append(name)
            transcribe_prompt = types.Part.from_text(
                text="Transkripsikan isi rekaman suara ini secara akurat ke dalam teks. Kembalikan HANYA teks transkripsinya tanpa kata pengantar."
            )
            for model_id in transcribe_models:
                try:
                    tr_resp = await transcribe_client.aio.models.generate_content(
                        model=model_id,
                        contents=[
                            types.Content(
                                role="user",
                                parts=[audio_part, transcribe_prompt],
                            )
                        ],
                    )
                    if tr_resp and tr_resp.text:
                        transcription_text = tr_resp.text.strip()
                        logger.info(
                            f"Transkripsi pesan suara ({model_id}): {transcription_text}"
                        )
                        break
                except _HANDLER_ERR as tr_err:
                    logger.debug(f"Fast transcription skipped ({model_id}): {tr_err}")

        if transcription_text:
            prompt = f'[PESAN SUARA PENGGUNA (Transkripsi): "{transcription_text}"]\nPahami instruksi di atas dan berikan jawaban yang lengkap dan akurat.'
        else:
            prompt = "Dengarkan rekaman suara ini dengan teliti, pahami instruksi/pertanyaannya, dan berikan jawaban yang lengkap dan akurat."

        reply = await _run_agent_turn(
            user_id=user_id,
            user_prompt=prompt,
            multimodal_parts=[audio_part],
            chat_id=chat_id,
        )
    except _HANDLER_ERR as e:
        logger.error(f"[handle_voice] turn gagal untuk {user_id}: {e}", exc_info=True)
        reply = (
            "❌ Maaf, pesan suaranya gagal diproses "
            f"({type(e).__name__}: {str(e)[:200]}). "
            "Coba kirim ulang."
        )
    finally:
        stop_typing.set()
        await typing_task

    await _check_and_send_media_artifacts(
        update, context, turn_start_time=turn_start_time
    )

    prefer_text = should_reply_with_text_instead_of_voice(reply)
    sent_voice = False

    if not prefer_text:
        voice_path = None
        try:
            await context.bot.send_chat_action(
                chat_id=chat_id, action=constants.ChatAction.RECORD_VOICE
            )
            voice_path = await tts_engine.text_to_speech_ogg(reply)
            with open(voice_path, "rb") as vf:
                await update.message.reply_voice(voice=vf)
            sent_voice = True
        except _HANDLER_ERR as e:
            logger.error(f"TTS voice reply error: {e}, falling back to text")
            sent_voice = False
        finally:
            if voice_path and os.path.exists(voice_path):
                try:
                    os.remove(voice_path)
                except OSError:
                    pass

    if not sent_voice:
        await safe_send_message(context, chat_id, reply)


async def handle_photo_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming photos & images for vision analysis."""
    if not update.message:
        return
    user_id = update.effective_user.id if update.effective_user else 0
    chat_id = update.effective_chat.id if update.effective_chat else 0
    if not _is_authorized(user_id):
        await safe_send_message(context, chat_id, "⛔ Akses ditolak.")
        return

    photos = update.message.photo
    if not photos:
        return
    turn_start_time = time.time()

    caption = update.message.caption or "Analisis gambar ini secara detail."
    best_photo = photos[-1]

    stop_typing = asyncio.Event()
    typing_task = asyncio.create_task(
        send_typing_loop(
            chat_id, context, stop_typing, constants.ChatAction.UPLOAD_PHOTO
        )
    )
    reply = "❌ Maaf, terjadi kesalahan saat memproses gambarmu."

    try:
        photo_file = await context.bot.get_file(best_photo.file_id)
        photo_bytes_io = io.BytesIO()
        await photo_file.download_to_memory(photo_bytes_io)
        photo_bytes = photo_bytes_io.getvalue()

        from alfa.tools.filesystem import universal_file_extractor as ufe

        photo_filename = f"photo_{int(time.time())}_{user_id}.jpg"
        txt_ctx, image_part = ufe.process_uploaded_attachment(
            photo_filename, "image/jpeg", photo_bytes, save_disk=True
        )

        prompt = f"{txt_ctx}\n\nInstruksi Pengguna: {caption}" if txt_ctx else caption
        multimodal_parts = [image_part] if image_part is not None else None

        reply = await _run_agent_turn(
            user_id=user_id,
            user_prompt=prompt,
            multimodal_parts=multimodal_parts,
            chat_id=chat_id,
        )
    except _HANDLER_ERR as e:
        logger.error(f"[handle_photo] turn gagal untuk {user_id}: {e}", exc_info=True)
        reply = (
            "❌ Maaf, fotonya gagal diproses "
            f"({type(e).__name__}: {str(e)[:200]}). "
            "Coba kirim ulang."
        )
    finally:
        stop_typing.set()
        await typing_task

    await safe_send_message(context, chat_id, reply)
    await _check_and_send_media_artifacts(
        update, context, turn_start_time=turn_start_time
    )


_DOC_BATCHES: dict[int, dict[str, Any]] = {}
_DOC_BATCH_LOCK = asyncio.Lock()


async def _execute_document_batch(chat_id: int, batch: dict[str, Any]):
    docs = batch.get("docs", [])
    if not docs:
        return
    user_id = batch.get("user_id", 0)
    context = batch.get("context")
    update = batch.get("latest_update")
    turn_start_time = batch.get("turn_start_time", time.time())
    captions = [c for c in batch.get("captions", []) if c]

    # Gabungkan caption pengguna jika ada
    user_caption = " ".join(captions).strip() if captions else ""

    stop_typing = asyncio.Event()
    typing_task = asyncio.create_task(
        send_typing_loop(
            chat_id, context, stop_typing, constants.ChatAction.UPLOAD_DOCUMENT
        )
    )
    reply = "❌ Maaf, terjadi kesalahan saat memproses dokumenmu."

    try:
        multimodal_parts = []
        for d in docs:
            if d.get("part") is not None:
                multimodal_parts.append(d["part"])

        if len(docs) > 1:
            # Multi-dokumen: rangkum langsung jadi SATU laporan rincian terpadu
            doc_blocks = []
            file_names = []
            for idx, d in enumerate(docs, 1):
                fname = d.get("file_name", f"file_{idx}")
                file_names.append(fname)
                tctx = (d.get("txt_ctx") or "").strip()
                if tctx:
                    doc_blocks.append(f"--- DOKUMEN {idx}: {fname} ---\n{tctx}")
                else:
                    doc_blocks.append(f"--- DOKUMEN {idx}: {fname} (lampiran berkas) ---")

            if not user_caption:
                user_caption = "Analisis dan berikan rincian penting isi seluruh dokumen ini."

            prompt = (
                f"[KUMPULAN {len(docs)} BERKAS DOKUMEN DIUNGGAH SEKALIGUS]:\n"
                f"Daftar Berkas: {', '.join(file_names)}\n\n"
                + "\n\n".join(doc_blocks)
                + f"\n\nInstruksi Pengguna: {user_caption}\n\n"
                "[PANDUAN LAPORAN RINCIAN MULTI-DOKUMEN DARI PENGGUNA]:\n"
                "- FORMAT WAJIB: CUKUP NAMA DOKUMEN DAN RINCIAN MATERIALNYA SECARA RAPI (JANGAN MEMBINGUNGKAN PEMBACA).\n"
                "- WAJIB JADIKAN 1 LAPORAN TERPADU DENGAN STRUKTUR RUNUT PER BERKAS:\n"
                "  📄 Nama Dokumen / Berkas (misal: CLR56-99-263_DOEID26101705.xls)\n"
                "  • Nama Material / Item : QTY Satuan\n"
                "- Di bagian akhir, berikan Rekapitulasi Total Material secara ringkas dan bersih.\n"
                "- DILARANG bertele-tele membuat ringkasan eksekutif panjang, analisis narasi umum, detail gudang/pemohon yang tidak relevan, atau mengacak material tanpa kejelasan dokumen asalnya.\n"
                "- Sajikan dengan format rapi, bersih, to-the-point, dan nyaman dibaca di Telegram."
            )
        else:
            # Dokumen tunggal
            d = docs[0]
            fname = d.get("file_name", "file.bin")
            tctx = (d.get("txt_ctx") or "").strip()
            if not user_caption:
                user_caption = "Berikan rincian material/isi dari dokumen ini."

            doc_summary_guidance = (
                "\n\n[PANDUAN FORMAT LAPORAN DOKUMEN]:\n"
                "- FORMAT WAJIB: CUKUP NAMA DOKUMEN DAN RINCIAN MATERIAL / ITEMNYA SECARA RAPI.\n"
                "- Tampilkan per butir jelas: • Nama Material / Item : QTY Satuan.\n"
                "- DILARANG bertele-tele membuat pembuka/penutup panjang, analisis narasi teoritis, atau status audit internal.\n"
                "- Sajikan dengan format yang padat, bersih, to-the-point, dan nyaman dibaca di Telegram."
            )
            if tctx:
                prompt = f"{tctx}\n\nInstruksi Pengguna: {user_caption}{doc_summary_guidance}"
            else:
                prompt = f"Dokumen/Berkas '{fname}': {user_caption}{doc_summary_guidance}"

        reply = await _run_agent_turn(
            user_id=user_id,
            user_prompt=prompt,
            multimodal_parts=multimodal_parts or None,
            chat_id=chat_id,
        )

        if len(docs) > 1:
            file_names = [d.get("file_name", "file") for d in docs]
            combined_blocks = []
            for idx, d in enumerate(docs, 1):
                fname = d.get("file_name", f"file_{idx}")
                tctx = (d.get("txt_ctx") or "").strip()
                if tctx:
                    combined_blocks.append(f"--- DOKUMEN {idx}: {fname} ---\n{tctx}")
                else:
                    combined_blocks.append(f"--- DOKUMEN {idx}: {fname} (lampiran berkas) ---")
            combined_txt = "\n\n".join(combined_blocks)

            _RECENT_DOCS[chat_id] = {
                "is_batch": True,
                "docs_count": len(docs),
                "file_name": f"{len(docs)} Berkas Gabungan ({file_names[0]} dkk)",
                "file_names": file_names,
                "mime_type": "multipart/batch",
                "txt_ctx": combined_txt,
                "summary_reply": reply,
                "time": time.time(),
            }
        elif docs:
            d = docs[0]
            if d.get("txt_ctx"):
                _RECENT_DOCS[chat_id] = {
                    "is_batch": False,
                    "docs_count": 1,
                    "file_name": d["file_name"],
                    "file_names": [d["file_name"]],
                    "mime_type": d["mime_type"],
                    "txt_ctx": d["txt_ctx"],
                    "summary_reply": reply,
                    "time": time.time(),
                }
    finally:
        stop_typing.set()
        await typing_task

    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    doc_buttons = [
        [
            InlineKeyboardButton("📄 Buat PDF Resmi", callback_data="docact:pdf"),
            InlineKeyboardButton("📊 Buat Excel Baru", callback_data="docact:excel"),
        ],
        [
            InlineKeyboardButton("🔍 Analisis Mendalam", callback_data="docact:deep"),
        ],
    ]
    doc_markup = InlineKeyboardMarkup(doc_buttons)

    await safe_send_message(context, chat_id, reply, reply_markup=doc_markup)
    if update:
        await _check_and_send_media_artifacts(
            update, context, turn_start_time=turn_start_time
        )


async def handle_document_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle incoming documents (PDF, TXT, code, Excel, CSV, and long Audio meeting files).
    Batches documents uploaded in rapid succession / albums into a single analysis turn.
    """
    if not update.message:
        return
    user_id = update.effective_user.id if update.effective_user else 0
    chat_id = update.effective_chat.id if update.effective_chat else 0
    if not _is_authorized(user_id):
        await safe_send_message(context, chat_id, "⛔ Akses ditolak.")
        return

    doc = update.message.document
    if not doc:
        return

    caption = (update.message.caption or "").strip()
    file_name = doc.file_name or "file.bin"
    mime_type = doc.mime_type or "application/octet-stream"

    try:
        doc_file = await context.bot.get_file(doc.file_id)
        doc_bytes_io = io.BytesIO()
        await doc_file.download_to_memory(doc_bytes_io)
        doc_bytes = doc_bytes_io.getvalue()
    except Exception as e:
        logger.error(f"[handle_document] Gagal unduh file '{file_name}': {e}")
        await safe_send_message(
            context, chat_id, f"❌ Gagal mengunduh berkas `{file_name}`: {e}"
        )
        return

    from alfa.tools.filesystem import universal_file_extractor as ufe

    try:
        txt_ctx, part = ufe.process_uploaded_attachment(file_name, mime_type, doc_bytes)
    except Exception as e:
        logger.warning(f"[handle_document] Gagal ekstraksi '{file_name}': {e}")
        txt_ctx, part = "", None

    doc_item = {
        "file_name": file_name,
        "mime_type": mime_type,
        "txt_ctx": txt_ctx,
        "part": part,
        "caption": caption,
    }

    async with _DOC_BATCH_LOCK:
        if chat_id not in _DOC_BATCHES:
            _DOC_BATCHES[chat_id] = {
                "docs": [],
                "captions": [],
                "task": None,
                "user_id": user_id,
                "context": context,
                "latest_update": update,
                "turn_start_time": time.time(),
            }
        batch = _DOC_BATCHES[chat_id]
        batch["docs"].append(doc_item)
        if caption:
            batch["captions"].append(caption)
        batch["latest_update"] = update

        if batch["task"] and not batch["task"].done():
            batch["task"].cancel()

        async def _delayed_batch_runner():
            try:
                # Jeda 1.2 detik untuk menampung album atau berkas yang dikirim bersamaan
                await asyncio.sleep(1.2)
            except asyncio.CancelledError:
                return

            async with _DOC_BATCH_LOCK:
                ready_batch = _DOC_BATCHES.pop(chat_id, None)

            if not ready_batch or not ready_batch.get("docs"):
                return

            await _execute_document_batch(chat_id, ready_batch)

        batch["task"] = asyncio.create_task(_delayed_batch_runner())
