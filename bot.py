#!/usr/bin/env python3
"""
Ultra-Advanced Telegram AI Agent Bot
Powered by Google Gemini 2.5 & Autonomous Function Calling
Features:
- Native Multimodal: Voice Notes, Photos/Vision, Documents (PDF/Code/Data)
- Autonomous Agent Tools: System Monitoring, Bash Execution, Live Web Search, Long-term Memory, Reminders
- Natural Indonesian/English TTS Voice Responses (Edge-TTS)
- Persistent SQLite Database for Chat History & Long-Term Memories
- Proactive Background Cron & Reminder Dispatcher
- Interactive Telegram Inline Menu
- Multi-layer Whitelist Security
"""

import os
import sys
import io
import asyncio
import logging
from datetime import datetime
from typing import List, Optional

from dotenv import load_dotenv
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    constants,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# Local modules
import database
import tools
from tools import AVAILABLE_TOOLS, get_system_stats
import tts_engine

# Load environment
load_dotenv()

# Setup logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("TelegramAIAgent")

# Configuration
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()

raw_allowed_users = os.getenv("ALLOWED_USER_IDS", "").strip()
ALLOWED_USER_IDS = [
    int(uid.strip()) for uid in raw_allowed_users.split(",") if uid.strip().isdigit()
]

# Load Dynamic System Prompt from ~/.alfa/system_prompt.txt if present
ALFA_PROMPT_PATH = os.path.expanduser("~/.alfa/system_prompt.txt")
if os.path.exists(ALFA_PROMPT_PATH):
    with open(ALFA_PROMPT_PATH, "r", encoding="utf-8") as f:
        SYSTEM_PROMPT = f.read().strip()
else:
    SYSTEM_PROMPT = """You are ALFA-CORE, an advanced autonomous Linux systems operator powered by Gemini API, serving both Terminal CLI and Telegram interfaces."""


# Initialize Gemini Client
gemini_client = None
if GEMINI_API_KEY and GEMINI_API_KEY != "your_gemini_api_key_here":
    try:
        from google import genai
        gemini_client = genai.Client(api_key=GEMINI_API_KEY)
        logger.info("Google GenAI client initialized.")
    except Exception as e:
        logger.error(f"Failed to initialize GenAI client: {e}")


def is_authorized(user_id: int) -> bool:
    """Check if the user is authorized to access the bot."""
    if not ALLOWED_USER_IDS:
        return True
    return user_id in ALLOWED_USER_IDS


def split_message(text: str, max_length: int = 4000) -> List[str]:
    """Split long response into safe Telegram message chunks."""
    if len(text) <= max_length:
        return [text]
    chunks = []
    lines = text.split("\n")
    current_chunk = ""
    for line in lines:
        if len(current_chunk) + len(line) + 1 > max_length:
            if current_chunk:
                chunks.append(current_chunk)
                current_chunk = ""
            while len(line) > max_length:
                chunks.append(line[:max_length])
                line = line[max_length:]
            current_chunk = line
        else:
            if current_chunk:
                current_chunk += "\n" + line
            else:
                current_chunk = line
    if current_chunk:
        chunks.append(current_chunk)
    return chunks


async def send_typing_loop(chat_id: int, context: ContextTypes.DEFAULT_TYPE, stop_event: asyncio.Event, action=constants.ChatAction.TYPING):
    """Keep sending chat action while processing."""
    while not stop_event.is_set():
        try:
            await context.bot.send_chat_action(chat_id=chat_id, action=action)
        except Exception:
            pass
        await asyncio.sleep(4)


# --- Core AI Generation Engine ---
async def run_agent_turn(
    user_id: int,
    user_prompt: str,
    multimodal_parts: Optional[list] = None
) -> str:
    """
    Executes an autonomous agent turn with memory context, tool calling, and multimodal inputs.
    """
    global gemini_client
    if not GEMINI_API_KEY or GEMINI_API_KEY == "your_gemini_api_key_here":
        return "⚠️ **GEMINI_API_KEY** belum diisi di file `.env`. Silakan isi API Key Anda agar AI dapat aktif."

    if not gemini_client:
        try:
            from google import genai
            gemini_client = genai.Client(api_key=GEMINI_API_KEY)
        except Exception as e:
            return f"❌ Gagal menginisialisasi Google GenAI: {e}"

    # 1. Fetch recent chat history from SQLite
    history_rows = await database.get_recent_chat_history(user_id, limit=10)
    
    # 2. Build contents payload
    from google.genai import types
    contents = []
    
    for row in history_rows:
        role = "user" if row["role"] == "user" else "model"
        contents.append(
            types.Content(
                role=role,
                parts=[types.Part.from_text(text=row["content"])]
            )
        )

    # 3. Add current turn with any multimodal attachments
    current_parts = []
    if multimodal_parts:
        current_parts.extend(multimodal_parts)
    if user_prompt:
        current_parts.append(types.Part.from_text(text=user_prompt))

    contents.append(types.Content(role="user", parts=current_parts))

    # 4. Save user turn to database
    display_user_text = user_prompt or "[Lampiran Media]"
    await database.save_chat_message(user_id, "user", display_user_text)

    # 5. Call Gemini with Agent Tools and robust fast model fallback
    candidate_models = [GEMINI_MODEL, "gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-3.6-flash"]
    # De-duplicate while preserving order
    models_to_try = list(dict.fromkeys(candidate_models))

    last_error = None
    for model_name in models_to_try:
        try:
            config = types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                temperature=0.7,
                tools=AVAILABLE_TOOLS,
            )

            response = gemini_client.models.generate_content(
                model=model_name,
                contents=contents,
                config=config
            )

            reply_text = response.text or "✅ Permintaan selesai diproses."
            
            # Save model response to database
            await database.save_chat_message(user_id, "model", reply_text)
            return reply_text

        except Exception as e:
            logger.warning(f"Model {model_name} failed: {e}. Trying fallback if available...")
            last_error = e

    logger.error(f"All candidate models failed: {last_error}", exc_info=True)
    return f"❌ Terjadi kesalahan saat memproses permintaan:\n`{str(last_error)}`"


# --- Telegram Command Handlers ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command."""
    user = update.effective_user
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
            InlineKeyboardButton("🎙️ Toggle Voice", callback_data="btn_toggle_voice"),
            InlineKeyboardButton("🧹 Reset Sesi", callback_data="btn_clear"),
        ],
        [
            InlineKeyboardButton("📖 Bantuan & Tools", callback_data="btn_help"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    welcome_text = (
        f"🤖 **Personal Autonomous AI Agent**\n"
        f"Halo, **{user.first_name}**! Saya asisten AI pribadi berbasis **Gemini 2.5** yang terhubung langsung dengan sistem Linux Anda.\n\n"
        f"⚡ **Fitur Super-Canggih Aktif:**\n"
        f"• 🎙️ **Voice Notes:** Kirim pesan suara, saya akan mendengar & menjawab.\n"
        f"• 👁️ **Vision / Gambar:** Kirim foto/screenshot untuk dianalisis.\n"
        f"• 📄 **Dokumen & PDF:** Kirim berkas untuk dirangkum/diolah.\n"
        f"• 🛠️ **Autonomous Tools:** Monitoring sistem, eksekusi bash, web search, memori permanen, pengingat otomatis.\n\n"
        f"Kirimkan pesan apa saja langsung ke chat ini!"
    )
    await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode=constants.ParseMode.MARKDOWN)


async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /menu command."""
    user = update.effective_user
    if not is_authorized(user.id):
        return

    settings = await database.get_user_settings(user.id)
    voice_status = "Aktif (ON) 🔊" if settings.get("voice_reply") else "Nonaktif (OFF) 🔇"

    keyboard = [
        [
            InlineKeyboardButton("📊 System Stats", callback_data="btn_stats"),
            InlineKeyboardButton("🧠 Lihat Memori", callback_data="btn_memory"),
        ],
        [
            InlineKeyboardButton(f"🎙️ Suara: {voice_status}", callback_data="btn_toggle_voice"),
            InlineKeyboardButton("🧹 Reset Konteks", callback_data="btn_clear"),
        ],
        [
            InlineKeyboardButton("❓ Daftar Perintah", callback_data="btn_help"),
        ]
    ]
    await update.message.reply_text("🎛️ **Menu Kontrol Agent:**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=constants.ParseMode.MARKDOWN)


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /stats command."""
    if not is_authorized(update.effective_user.id):
        return

    stats = get_system_stats()
    text = (
        f"📊 **Status Server / Laptop:**\n\n"
        f"• **CPU:** `{stats.get('cpu')}`\n"
        f"• **RAM:** `{stats.get('ram')}`\n"
        f"• **Disk:** `{stats.get('disk')}`\n"
        f"• **Uptime:** `{stats.get('uptime')}`\n\n"
        f"🔥 **Top Proses:**\n" + "\n".join([f"  - {p}" for p in stats.get('top_processes', [])])
    )
    await update.message.reply_text(text, parse_mode=constants.ParseMode.MARKDOWN)


async def memory_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /memory command."""
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        return

    memories = await database.get_all_memories(user_id)
    if not memories:
        await update.message.reply_text(
            "🧠 **Memori Jangka Panjang Kosong.**\n\nAnda bisa menyuruh bot mengingat sesuatu, contoh:\n_\"Ingat bahwa port backend saya adalah 8000\"_",
            parse_mode=constants.ParseMode.MARKDOWN
        )
        return

    text = "🧠 **Memori Jangka Panjang Tersimpan:**\n\n"
    for m in memories:
        text += f"• *[{m['category'].upper()}]* `{m['key_topic']}`:\n  {m['content']}\n\n"

    chunks = split_message(text)
    for c in chunks:
        await update.message.reply_text(c, parse_mode=constants.ParseMode.MARKDOWN)


async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /clear command."""
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        return

    await database.clear_user_chat_history(user_id)
    await update.message.reply_text("🧹 **Riwayat percakapan berhasil direset.** Memori jangka panjang tetap aman tersimpan!", parse_mode=constants.ParseMode.MARKDOWN)


async def id_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /id command."""
    user = update.effective_user
    await update.message.reply_text(
        f"👤 **Nama:** {user.full_name}\n🆔 **Telegram ID:** `{user.id}`\n💬 **Chat ID:** `{update.effective_chat.id}`",
        parse_mode=constants.ParseMode.MARKDOWN
    )


async def voice_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /voice toggle command."""
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        return

    is_on = await database.toggle_voice_setting(user_id)
    status_str = "AKTIF 🔊 (Bot akan membalas dengan Voice Note & Teks)" if is_on else "NONAKTIF 🔇 (Bot membalas teks saja)"
    await update.message.reply_text(f"🎙️ **Mode Suara:** {status_str}", parse_mode=constants.ParseMode.MARKDOWN)


# --- Callback Query Handler for Inline Buttons ---
async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline button clicks."""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    if not is_authorized(user_id):
        await query.edit_message_text("⛔ Akses ditolak.")
        return

    data = query.data
    if data == "btn_stats":
        stats = get_system_stats()
        text = (
            f"📊 **Status Server / Laptop:**\n\n"
            f"• **CPU:** `{stats.get('cpu')}`\n"
            f"• **RAM:** `{stats.get('ram')}`\n"
            f"• **Disk:** `{stats.get('disk')}`\n"
            f"• **Uptime:** `{stats.get('uptime')}`\n\n"
            f"🔥 **Top Proses:**\n" + "\n".join([f"  - {p}" for p in stats.get('top_processes', [])])
        )
        await query.message.reply_text(text, parse_mode=constants.ParseMode.MARKDOWN)

    elif data == "btn_memory":
        memories = await database.get_all_memories(user_id)
        if not memories:
            await query.message.reply_text("🧠 Memori masih kosong.", parse_mode=constants.ParseMode.MARKDOWN)
        else:
            text = "🧠 **Memori Tersimpan:**\n\n"
            for m in memories:
                text += f"• *[{m['category'].upper()}]* `{m['key_topic']}`: {m['content']}\n"
            await query.message.reply_text(text, parse_mode=constants.ParseMode.MARKDOWN)

    elif data == "btn_toggle_voice":
        is_on = await database.toggle_voice_setting(user_id)
        status_str = "AKTIF 🔊" if is_on else "NONAKTIF 🔇"
        await query.message.reply_text(f"🎙️ Mode Balasan Suara sekarang: **{status_str}**", parse_mode=constants.ParseMode.MARKDOWN)

    elif data == "btn_clear":
        await database.clear_user_chat_history(user_id)
        await query.message.reply_text("🧹 Konteks percakapan telah direset.", parse_mode=constants.ParseMode.MARKDOWN)

    elif data == "btn_help":
        help_text = (
            "📖 **Daftar Perintah & Fitur:**\n\n"
            "• `/menu` - Tampilkan tombol kontrol utama\n"
            "• `/stats` - Cek performa CPU, RAM, & Disk Linux\n"
            "• `/memory` - Cek data memori jangka panjang\n"
            "• `/voice` - Hidupkan/matikan respon suara\n"
            "• `/clear` - Hapus riwayat chat (mulai sesi baru)\n"
            "• `/id` - Cek ID Telegram Anda\n\n"
            "💬 **Tips Interaksi:**\n"
            "- Kirim pesan suara (Voice Note) untuk bicara langsung dengan AI.\n"
            "- Kirim foto kode/diagram untuk dianalisis.\n"
            "- Minta AI menjalankan perintah Linux (misal: *'cek file di folder Unduhan'*).\n"
            "- Minta AI browsing (misal: *'cari berita AI terkini hari ini'*)."
        )
        await query.message.reply_text(help_text, parse_mode=constants.ParseMode.MARKDOWN)


# --- Multimodal & Message Handlers ---
async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text messages."""
    if not update.message or not update.message.text:
        return
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if not is_authorized(user_id):
        await update.message.reply_text("⛔ Akses ditolak.")
        return

    user_text = update.message.text.strip()

    # Typing indicator
    stop_typing = asyncio.Event()
    typing_task = asyncio.create_task(send_typing_loop(chat_id, context, stop_typing, constants.ChatAction.TYPING))

    try:
        reply = await run_agent_turn(user_id=user_id, user_prompt=user_text)
    finally:
        stop_typing.set()
        await typing_task

    # Send text response
    chunks = split_message(reply)
    for chunk in chunks:
        try:
            await update.message.reply_text(chunk, parse_mode=constants.ParseMode.MARKDOWN)
        except Exception:
            await update.message.reply_text(chunk)

    # Auto-send any generated media artifacts (screenshot / webcam frame)
    await check_and_send_media_artifacts(update, context)

    # If voice mode enabled, generate and send voice note
    settings = await database.get_user_settings(user_id)
    if settings.get("voice_reply"):
        try:
            await context.bot.send_chat_action(chat_id=chat_id, action=constants.ChatAction.RECORD_VOICE)
            voice_path = await tts_engine.text_to_speech_ogg(reply)
            with open(voice_path, "rb") as voice_file:
                await update.message.reply_voice(voice=voice_file)
            if os.path.exists(voice_path):
                os.remove(voice_path)
        except Exception as tts_err:
            logger.error(f"TTS sending error: {tts_err}")


async def check_and_send_media_artifacts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Checks if any screenshot or webcam frame was generated and sends it directly as a photo."""
    sandbox_dir = "/dev/shm/alfa_sandbox"
    media_files = ["desktop_screen.png", "webcam_frame.jpg"]
    for m_file in media_files:
        full_path = os.path.join(sandbox_dir, m_file)
        if os.path.exists(full_path) and os.path.getsize(full_path) > 0:
            try:
                caption = "🖥️ Tangkapan Layar Desktop" if "screen" in m_file else "📷 Foto Kamera Webcam"
                with open(full_path, "rb") as f:
                    await update.message.reply_photo(photo=f, caption=caption)
                os.remove(full_path)
            except Exception as send_err:
                logger.error(f"Failed to send media artifact {full_path}: {send_err}")


async def handle_voice_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming Voice Notes / Audio."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if not is_authorized(user_id):
        await update.message.reply_text("⛔ Akses ditolak.")
        return

    voice = update.message.voice or update.message.audio
    if not voice:
        return

    stop_typing = asyncio.Event()
    typing_task = asyncio.create_task(send_typing_loop(chat_id, context, stop_typing, constants.ChatAction.RECORD_VOICE))

    try:
        # Download voice file
        file_obj = await context.bot.get_file(voice.file_id)
        voice_bytes_io = io.BytesIO()
        await file_obj.download_to_memory(voice_bytes_io)
        voice_bytes = voice_bytes_io.getvalue()

        from google.genai import types
        # Create audio part for Gemini 2.5
        audio_part = types.Part.from_bytes(data=voice_bytes, mime_type="audio/ogg")

        prompt = "Dengarkan rekaman suara di atas, pahami pertanyaannya, dan berikan jawaban yang lengkap dan akurat."
        reply = await run_agent_turn(user_id=user_id, user_prompt=prompt, multimodal_parts=[audio_part])
    finally:
        stop_typing.set()
        await typing_task

    # Send text reply
    chunks = split_message(reply)
    for chunk in chunks:
        try:
            await update.message.reply_text(chunk, parse_mode=constants.ParseMode.MARKDOWN)
        except Exception:
            await update.message.reply_text(chunk)

    # Always reply with voice for voice queries!
    try:
        voice_path = await tts_engine.text_to_speech_ogg(reply)
        with open(voice_path, "rb") as vf:
            await update.message.reply_voice(voice=vf)
        if os.path.exists(voice_path):
            os.remove(voice_path)
    except Exception as e:
        logger.error(f"TTS voice reply error: {e}")


async def handle_photo_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming photos & images."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if not is_authorized(user_id):
        await update.message.reply_text("⛔ Akses ditolak.")
        return

    photos = update.message.photo
    if not photos:
        return

    caption = update.message.caption or "Analisis gambar ini secara detail."

    stop_typing = asyncio.Event()
    typing_task = asyncio.create_task(send_typing_loop(chat_id, context, stop_typing, constants.ChatAction.UPLOAD_PHOTO))

    try:
        # Download highest resolution photo
        highest_photo = photos[-1]
        file_obj = await context.bot.get_file(highest_photo.file_id)
        photo_bytes_io = io.BytesIO()
        await file_obj.download_to_memory(photo_bytes_io)
        photo_bytes = photo_bytes_io.getvalue()

        from google.genai import types
        image_part = types.Part.from_bytes(data=photo_bytes, mime_type="image/jpeg")

        reply = await run_agent_turn(user_id=user_id, user_prompt=caption, multimodal_parts=[image_part])
    finally:
        stop_typing.set()
        await typing_task

    chunks = split_message(reply)
    for chunk in chunks:
        try:
            await update.message.reply_text(chunk, parse_mode=constants.ParseMode.MARKDOWN)
        except Exception:
            await update.message.reply_text(chunk)


async def handle_document_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming documents (PDF, text, code, csv)."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if not is_authorized(user_id):
        await update.message.reply_text("⛔ Akses ditolak.")
        return

    doc = update.message.document
    if not doc:
        return

    caption = update.message.caption or f"Tolong baca dan analisis dokumen '{doc.file_name}' ini."

    stop_typing = asyncio.Event()
    typing_task = asyncio.create_task(send_typing_loop(chat_id, context, stop_typing, constants.ChatAction.UPLOAD_DOCUMENT))

    try:
        file_obj = await context.bot.get_file(doc.file_id)
        doc_bytes_io = io.BytesIO()
        await file_obj.download_to_memory(doc_bytes_io)
        doc_bytes = doc_bytes_io.getvalue()

        from google.genai import types
        mime_type = doc.mime_type or "application/octet-stream"

        if "pdf" in mime_type:
            doc_part = types.Part.from_bytes(data=doc_bytes, mime_type="application/pdf")
            multimodal_parts = [doc_part]
            prompt = f"Dokumen PDF '{doc.file_name}': {caption}"
        else:
            # Try to decode as text
            try:
                text_content = doc_bytes.decode("utf-8", errors="replace")
                multimodal_parts = None
                prompt = f"Isi dokumen '{doc.file_name}':\n```\n{text_content[:8000]}\n```\n\nInstruksi: {caption}"
            except Exception:
                doc_part = types.Part.from_bytes(data=doc_bytes, mime_type=mime_type)
                multimodal_parts = [doc_part]
                prompt = f"Dokumen '{doc.file_name}': {caption}"

        reply = await run_agent_turn(user_id=user_id, user_prompt=prompt, multimodal_parts=multimodal_parts)
    finally:
        stop_typing.set()
        await typing_task

    chunks = split_message(reply)
    for chunk in chunks:
        try:
            await update.message.reply_text(chunk, parse_mode=constants.ParseMode.MARKDOWN)
        except Exception:
            await update.message.reply_text(chunk)


# --- Background Reminder / Cron Dispatcher ---
async def proactive_reminder_loop(application: Application):
    """Background task to poll and send scheduled reminders."""
    logger.info("Proactive reminder dispatcher started.")
    while True:
        try:
            due_reminders = await database.get_due_reminders()
            for r in due_reminders:
                rem_id = r["id"]
                chat_id = r["chat_id"]
                msg = r["message"]
                rem_time = r["reminder_time"]

                alert_text = (
                    f"⏰ **PENGINGAT OTOMATIS (REMINDER)**\n\n"
                    f"📌 **Pesan:** {msg}\n"
                    f"🕒 **Waktu:** `{rem_time}`"
                )
                try:
                    await application.bot.send_message(chat_id=chat_id, text=alert_text, parse_mode=constants.ParseMode.MARKDOWN)
                    await database.mark_reminder_executed(rem_id)
                    logger.info(f"Dispatched reminder #{rem_id} to chat {chat_id}")
                except Exception as send_err:
                    logger.error(f"Failed to dispatch reminder #{rem_id}: {send_err}")
        except Exception as e:
            logger.error(f"Error in reminder loop: {e}")

        await asyncio.sleep(20)


async def post_init(application: Application):
    """Post initialization hook."""
    await database.init_db()
    # Start background reminder dispatcher
    asyncio.create_task(proactive_reminder_loop(application))


def main():
    """Main application launcher."""
    if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "your_telegram_bot_token_here":
        print("❌ ERROR: TELEGRAM_BOT_TOKEN belum disetel di .env!")
        sys.exit(1)

    if not GEMINI_API_KEY or GEMINI_API_KEY == "your_gemini_api_key_here":
        print("⚠️ PERINGATAN: GEMINI_API_KEY belum diisi di .env.")

    print("🚀 Menginisialisasi Autonomous AI Agent Bot...")
    application = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    # Command handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("menu", menu_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("memory", memory_command))
    application.add_handler(CommandHandler("clear", clear_command))
    application.add_handler(CommandHandler("reset", clear_command))
    application.add_handler(CommandHandler("id", id_command))
    application.add_handler(CommandHandler("voice", voice_command))
    application.add_handler(CommandHandler("help", start_command))

    # Callback Query (Buttons)
    application.add_handler(CallbackQueryHandler(handle_callback_query))

    # Multimodal message handlers
    application.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_voice_message))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo_message))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document_message))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))

    print(f"✅ Bot Telegram Otonom siap melayani! Menunggu interaksi...")
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
