"""Utility functions for message processing."""

import logging
import os
from typing import TYPE_CHECKING, List, Optional

from telegram import InlineKeyboardMarkup, constants

if TYPE_CHECKING:
    from telegram.ext import ContextTypes
    from telegram import Update

logger = logging.getLogger(__name__)


def split_message(text: str, max_length: int = 3900) -> List[str]:
    """Split long response into safe Telegram message chunks without breaking code fences."""
    if len(text) <= max_length:
        return [text]
    
    chunks = []
    lines = text.split("\n")
    current_chunk = ""
    in_code_block = False
    code_block_lang = ""

    for line in lines:
        if line.strip().startswith("```"):
            if not in_code_block:
                in_code_block = True
                code_block_lang = line.strip()[3:]
            else:
                in_code_block = False

        if len(current_chunk) + len(line) + 2 > max_length:
            if current_chunk:
                if in_code_block:
                    current_chunk += "\n```"
                chunks.append(current_chunk)
                current_chunk = ""
                if in_code_block:
                    current_chunk = f"```{code_block_lang}\n"

            while len(line) > max_length:
                chunks.append(line[:max_length])
                line = line[max_length:]
            current_chunk += line if not current_chunk else "\n" + line
        else:
            if current_chunk:
                current_chunk += "\n" + line
            else:
                current_chunk = line

    if current_chunk:
        chunks.append(current_chunk)
    return chunks


async def safe_send_message(
    context: "ContextTypes.DEFAULT_TYPE",
    chat_id: int,
    text: str,
    reply_to_message_id: Optional[int] = None,
    reply_markup: Optional[InlineKeyboardMarkup] = None
):
    """Safely send message to Telegram with automatic chunking and fallback to plain text."""
    chunks = split_message(text)
    for i, chunk in enumerate(chunks):
        markup = reply_markup if i == len(chunks) - 1 else None
        reply_id = reply_to_message_id if i == 0 else None
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=chunk,
                parse_mode=constants.ParseMode.MARKDOWN,
                reply_to_message_id=reply_id,
                reply_markup=markup
            )
        except Exception:
            try:
                # Fallback to plain text without parse mode
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=chunk,
                    reply_to_message_id=reply_id,
                    reply_markup=markup
                )
            except Exception as e:
                logger.error(f"Failed to send message chunk: {e}")


async def send_typing_loop(
    context: "ContextTypes.DEFAULT_TYPE",
    chat_id: int,
    action=constants.ChatAction.TYPING
):
    """Context manager for sending typing indicator during processing."""
    import asyncio
    
    stop_event = asyncio.Event()
    
    async def _loop():
        while not stop_event.is_set():
            try:
                await context.bot.send_chat_action(chat_id=chat_id, action=action)
            except Exception:
                pass
            await asyncio.sleep(4)
    
    task = asyncio.create_task(_loop())
    try:
        yield
    finally:
        stop_event.set()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


async def check_and_send_media_artifacts(update: "Update", context: "ContextTypes.DEFAULT_TYPE"):
    """Check if any media artifacts were created and send them to the user."""
    from tools import SANDBOX_DIR, is_internal_sandbox_artifact, is_source_code_file
    
    chat_id = update.effective_chat.id
    if not os.path.exists(SANDBOX_DIR):
        return

    # Standard named media
    named_media = [
        ("desktop_screen.png", "🖥️ Tangkapan Layar Desktop"),
        ("webcam_frame.jpg", "📷 Foto Kamera Webcam"),
        ("generated_plot.png", "📊 Grafik Visualisasi Data (Python)"),
        ("browser_screenshot.png", "🌐 Tangkapan Layar Browser (Camofox)"),
    ]

    for filename, caption in named_media:
        full_path = os.path.join(SANDBOX_DIR, filename)
        if os.path.exists(full_path) and os.path.getsize(full_path) > 0:
            try:
                with open(full_path, "rb") as photo_file:
                    await context.bot.send_photo(
                        chat_id=chat_id,
                        photo=photo_file,
                        caption=caption
                    )
            except Exception as send_err:
                logger.error(f"Failed to send media artifact {filename}: {send_err}")
            finally:
                try:
                    os.remove(full_path)
                except OSError:
                    pass

    # Check all other files in sandbox
    for fname in os.listdir(SANDBOX_DIR):
        fpath = os.path.join(SANDBOX_DIR, fname)
        if is_internal_sandbox_artifact(fname) or is_source_code_file(fname):
            continue
        if not os.path.isfile(fpath) or os.path.getsize(fpath) == 0:
            continue
        
        ext = os.path.splitext(fname)[1].lower()
        if ext in ['.png', '.jpg', '.jpeg', '.webp']:
            try:
                with open(fpath, "rb") as pf:
                    await context.bot.send_photo(
                        chat_id=chat_id,
                        photo=pf,
                        caption=f"📸 Berkas Gambar: {fname}"
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
                        chat_id=chat_id,
                        document=df,
                        caption=f"📄 Berkas: {fname}"
                    )
            except Exception as doc_err:
                logger.error(f"Failed to send document {fname}: {doc_err}")
            finally:
                try:
                    os.remove(fpath)
                except OSError:
                    pass
