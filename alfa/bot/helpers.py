"""Helper functions and message formatting utilities for ALFA Telegram Bot."""

import asyncio
import logging
import os
from typing import List, Optional
from telegram import InlineKeyboardMarkup, constants
from telegram.ext import ContextTypes

from alfa.core import database
from alfa.tools import SANDBOX_DIR
from alfa.bot.config import OWNER_NAME

logger = logging.getLogger("TelegramAIAgent")

ARTIFACT_DIRS = [
    os.path.expanduser("~/Dokumen/ALFA_SWARM_OUTPUTS"),
    SANDBOX_DIR,
]
ARTIFACT_NOUNS = ('laporan', 'file', 'csv', 'excel', 'pdf', 'website', 'scrape',
                  'grafik', 'chart', 'pptx', 'dokumen', 'landing')
COMPLETION_VERBS = ('sudah', 'selesai', 'berhasil', 'telah dibuat', 'sudah dibuat',
                    'aku buatkan')


def _meetings_count() -> int:
    """Ground truth: jumlah rapat NYATA di database."""
    try:
        with database.get_sync_db() as conn:
            row = conn.execute("SELECT COUNT(*) FROM agent_meetings").fetchone()
            return int(row[0]) if row else 0
    except Exception:
        return 0


def _artifact_signature() -> list:
    """Snapshot (path,size,mtime) berkas output - ground truth klaim artefak."""
    sig = []
    for d in ARTIFACT_DIRS:
        try:
            for root, _, files in os.walk(d):
                for f in files:
                    p = os.path.join(root, f)
                    try:
                        st = os.stat(p)
                        sig.append((p, st.st_size, int(st.st_mtime)))
                    except OSError:
                        pass
        except Exception:
            pass
    return sorted(sig)


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
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    text: str,
    reply_to_message_id: Optional[int] = None,
    reply_markup: Optional[InlineKeyboardMarkup] = None
):
    """
    Safely send message to Telegram with automatic chunking and fallback to plain text
    if Markdown parsing fails.
    """
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
    chat_id: int,
    context: ContextTypes.DEFAULT_TYPE,
    stop_event: asyncio.Event,
    action=constants.ChatAction.TYPING
):
    """Keep sending chat action indicator while processing."""
    while not stop_event.is_set():
        try:
            await context.bot.send_chat_action(chat_id=chat_id, action=action)
        except Exception:
            pass
        await asyncio.sleep(4)


def should_reply_with_text_instead_of_voice(text: str) -> bool:
    """
    Decide whether an AI response is best delivered as Text rather than a Voice Note.
    Returns True (send Text) if the reply contains code blocks, tables, commands, or heavy technical data.
    Returns False (send Voice Note) for conversational speech, summaries, and explanations.
    """
    if "```" in text:
        return True
    if "\n|" in text and ("|---" in text or "|:---" in text or "---|" in text):
        return True
    import re
    urls = re.findall(r"https?://\S+", text)
    if len(urls) >= 2:
        return True
    if len(text) > 900 and (text.count("\n- ") >= 4 or text.count("\n* ") >= 4 or text.count("\n1. ") >= 3):
        return True
    return False
