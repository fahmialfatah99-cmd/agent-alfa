"""Message and callback handlers for ALFA Telegram Bot."""

import asyncio
import io
import logging
import os
import sys
import time

from telegram import Update, constants
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


def _get_bot_module():
    """Retrieve telegram_bot module to support mocking in tests."""
    return sys.modules.get("alfa.bot.telegram_bot")


def _is_authorized(user_id: int) -> bool:
    mod = _get_bot_module()
    if mod and hasattr(mod, "is_authorized"):
        return mod.is_authorized(user_id)
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


async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline button clicks."""
    query = update.callback_query
    if not query:
        return

    data = query.data or ""
    if data.startswith("perm|") or data == "perm_done":
        return

    await query.answer()

    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if not _is_authorized(user_id):
        await query.edit_message_text("⛔ Akses ditolak.")
        return

    data = query.data
    if data == "btn_stats":
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
            "📖 **Daftar Perintah & Panduan Interaksi:**\n\n"
            "• `/menu` - Tampilkan tombol kontrol utama\n"
            "• `/wa` - Kontrol & pantau WhatsApp Google Sheets Bot\n"
            "• `/stats` - Cek performa CPU, RAM, Disk, & Baterai\n"
            "• `/memory` - Cek data memori jangka panjang\n"
            "• `/proactive` - Cek/atur inisiatif mandiri ambient bot\n"
            "• `/voice` - Hidupkan/matikan respon suara\n"
            "• `/clear` - Hapus riwayat chat (mulai sesi baru)\n"
            "• `/id` - Cek ID Telegram & Chat ID\n\n"
            "💬 **Contoh Perintah AI:**\n"
            "- *'Ambil screenshot desktop sekarang'* -> Mengirim foto layar aktif.\n"
            "- *'Cek status bot whatsapp'* -> Melihat kondisi wa-sheets-bot.\n"
            "- *'Restart wa sheets bot'* -> Merestart service WhatsApp bot.\n"
            "- *'Buatkan grafik plot fungsi sinus dan cosinus'* -> Menghasilkan gambar grafik.\n"
            "- *'Cari informasi berita AI terkini hari ini'* -> Browsing real-time.\n"
            "- *'Ingat bahwa email dev saya adalah admin@example.com'* -> Simpan memori.\n"
            "- *'Ingatkan saya jam 18:00 untuk evaluasi project'* -> Set pengingat otomatis."
        )
        await safe_send_message(context, chat_id, help_text)

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
    chat_id = update.effective_chat.id
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
            except Exception as send_err:
                logger.error(f"Failed to send media artifact {filename}: {send_err}")
            finally:
                try:
                    os.remove(full_path)
                except OSError:
                    pass

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

        ext = os.path.splitext(fname)[1].lower()
        if ext in [".png", ".jpg", ".jpeg", ".webp"]:
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
            except Exception as img_err:
                logger.error(f"Failed to send image {fname}: {img_err}")
            finally:
                try:
                    os.remove(fpath)
                except OSError:
                    pass
        else:
            try:
                with open(fpath, "rb") as df:
                    await context.bot.send_document(
                        chat_id=chat_id, document=df, caption=f"📄 Berkas: {fname}"
                    )
            except Exception as doc_err:
                logger.error(f"Failed to send document {fname}: {doc_err}")
            finally:
                try:
                    os.remove(fpath)
                except OSError:
                    pass


async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming text messages."""
    if not update.message or not update.message.text:
        return
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if not _is_authorized(user_id):
        await safe_send_message(
            context, chat_id, "⛔ Akses ditolak. ID Anda belum terdaftar di whitelist."
        )
        return

    user_text = update.message.text.strip()
    turn_start_time = time.time()

    streamer = None
    stop_typing = None
    typing_task = None
    try:
        streamer = TelegramStreamer(context=context, chat_id=chat_id, initial_text=None)
        await streamer.start()
    except Exception as se:
        logger.warning(f"[TelegramStreamer] Start failed: {se}")
        streamer = None

    if not streamer:
        stop_typing = asyncio.Event()
        typing_task = asyncio.create_task(
            send_typing_loop(chat_id, context, stop_typing, constants.ChatAction.TYPING)
        )

    try:
        reply = await _run_agent_turn(
            user_id=user_id,
            user_prompt=user_text,
            chat_id=chat_id,
            streamer=streamer,
        )
    except Exception as e:
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
        except Exception as fe:
            logger.error(
                f"[TelegramStreamer] Finalize failed: {fe}, fallback to safe_send_message"
            )
            await safe_send_message(context, chat_id, reply)
    else:
        await safe_send_message(context, chat_id, reply)

    await _check_and_send_media_artifacts(
        update, context, turn_start_time=turn_start_time
    )

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
        except Exception as tts_err:
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
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
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
                "gemini-3.6-flash",
                "gemini-3.5-flash",
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
                except Exception as tr_err:
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
    except Exception as e:
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
        except Exception as e:
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
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
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
    except Exception as e:
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


async def handle_document_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle incoming documents (PDF, TXT, code, Excel, CSV, and long Audio meeting files).
    """
    if not update.message:
        return
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if not _is_authorized(user_id):
        await safe_send_message(context, chat_id, "⛔ Akses ditolak.")
        return

    doc = update.message.document
    if not doc:
        return
    turn_start_time = time.time()

    caption = update.message.caption or "Analisis isi dokumen ini secara mendalam."
    file_name = doc.file_name or "file.bin"
    mime_type = doc.mime_type or "application/octet-stream"

    stop_typing = asyncio.Event()
    typing_task = asyncio.create_task(
        send_typing_loop(
            chat_id, context, stop_typing, constants.ChatAction.UPLOAD_DOCUMENT
        )
    )
    reply = "❌ Maaf, terjadi kesalahan saat memproses dokumenmu."

    try:
        doc_file = await context.bot.get_file(doc.file_id)
        doc_bytes_io = io.BytesIO()
        await doc_file.download_to_memory(doc_bytes_io)
        doc_bytes = doc_bytes_io.getvalue()

        from alfa.tools.filesystem import universal_file_extractor as ufe

        txt_ctx, part = ufe.process_uploaded_attachment(file_name, mime_type, doc_bytes)

        multimodal_parts = [part] if part is not None else None
        if txt_ctx:
            prompt = f"{txt_ctx}\n\nInstruksi Pengguna: {caption}"
        else:
            prompt = f"Dokumen/Berkas '{file_name}': {caption}"

        reply = await _run_agent_turn(
            user_id=user_id,
            user_prompt=prompt,
            multimodal_parts=multimodal_parts,
            chat_id=chat_id,
        )

    finally:
        stop_typing.set()
        await typing_task

    await safe_send_message(context, chat_id, reply)
    await _check_and_send_media_artifacts(
        update, context, turn_start_time=turn_start_time
    )
