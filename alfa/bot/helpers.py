"""Helper functions and message formatting utilities for ALFA Telegram Bot."""

import asyncio
import logging
import os
import sqlite3
import time
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, constants
from telegram.ext import ContextTypes

from alfa.core import database
from alfa.tools import SANDBOX_DIR

logger = logging.getLogger("TelegramAIAgent")


def strip_thought_blocks(text: str) -> str:
    """Buang blok penalaran mentah (<thought>...</thought>) dari balasan user-facing.

    Aman untuk blok kode: hanya pola tag persis (case-insensitive) yang dibuang.
    """
    import re as _re

    if not text or "<thought" not in text.lower():
        return text
    cleaned = _re.sub(r"<thought\b[^>]*>.*?</thought\s*>", "", text, flags=_re.S | _re.I)
    cleaned = _re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned if cleaned.strip() else text


def clean_telegram_markdown(text: str) -> str:
    """Format and sanitize markdown text for optimal Telegram rendering.

    - Strips raw <thought> blocks
    - Strips internal audit disclaimers / apologies
    - Formats ### / #### headers as bold emoji titles
    - Formats bullets (*, -) to unicode bullets (•, ▫️)
    - Replaces raw divider dashes with clean spacing
    - Converts **bold** to Telegram *bold* outside code blocks
    - Wraps raw markdown tables into monospace code blocks
    - Escapes isolated identifier underscores (e.g. data_2026.xlsx)
    - Balances asterisks to prevent Telegram Markdown v1 entity parse errors
    """
    if not text:
        return ""

    import re as _re

    # 1. Thought blocks
    if "<thought" in text.lower():
        text = _re.sub(r"<thought\b[^>]*>.*?</thought\s*>", "", text, flags=_re.S | _re.I)

    # 1b. LaTeX math blocks ($$...$$, \[...\], \(...\))
    text = _re.sub(r"\$\$([\s\S]*?)\$\$", r"```\n\1\n```", text)
    text = _re.sub(r"\\\[([\s\S]*?)\\\]", r"```\n\1\n```", text)
    text = _re.sub(r"\\\(([\s\S]*?)\\\)", r"`\1`", text)

    # 2. Audit apologies / disclaimer leaks
    text = _re.sub(
        r"^(?:Siap|Maaf)[^\n]*?(?:terima kasih auditnya|aku jujur akui|audit)[^\n]*?\n+",
        "",
        text,
        flags=_re.IGNORECASE | _re.MULTILINE,
    )
    text = _re.sub(
        r"\n*Status:\s*\*{1,2}SELESAI\*{1,2}\s*\([^)]*belum ada berkas[^)]*\)[^\n]*",
        "",
        text,
        flags=_re.IGNORECASE,
    )
    text = _re.sub(
        r"\n*Kalau kamu mau ringkasan ini diexport jadi file PDF[^\n]*",
        "",
        text,
        flags=_re.IGNORECASE,
    )
    text = _re.sub(
        r"⛔\s*SISTEM AUDIT KEBENARAN:[\s\S]*?(?:Dilarang klaim palsu\.|$)",
        "",
        text,
        flags=_re.IGNORECASE,
    )

    # 3. Process line-by-line (preserving code blocks)
    lines = text.split("\n")
    processed_lines: list[str] = []
    table_buf: list[str] = []
    in_code_block = False

    def flush_table():
        nonlocal table_buf
        if table_buf:
            if len(table_buf) >= 2 and any("|" in tb_line for tb_line in table_buf):
                processed_lines.append("```\n" + "\n".join(table_buf) + "\n```")
            else:
                processed_lines.extend(table_buf)
            table_buf = []

    for line in lines:
        if line.strip().startswith("```"):
            flush_table()
            in_code_block = not in_code_block
            processed_lines.append(line)
            continue

        if in_code_block:
            processed_lines.append(line)
            continue

        stripped = line.strip()

        # Check for markdown table row: | a | b |
        if stripped.startswith("|") and stripped.count("|") >= 2:
            table_buf.append(line)
            continue
        else:
            flush_table()

        # Horizontal rules: ---, ***, ___
        if _re.match(r"^(\s*[-*_]\s*){3,}$", line):
            processed_lines.append("")
            continue

        def _format_header(raw_title: str, default_icon: str) -> str:
            t = raw_title.strip()
            if t.startswith("**") and t.endswith("**") and len(t) > 4:
                t = t[2:-2].strip()
            elif t.startswith("*") and t.endswith("*") and len(t) > 2:
                t = t[1:-1].strip()
            emoji_m = _re.match(r"^([^\w\s*#_~`\"'\(\)\[\]\-]+)\s*(.*)$", t)
            if emoji_m and emoji_m.group(1).strip():
                emoji = emoji_m.group(1).strip()
                rest = emoji_m.group(2).strip()
                if rest.startswith("**") and rest.endswith("**") and len(rest) > 4:
                    rest = rest[2:-2].strip()
                elif rest.startswith("*") and rest.endswith("*") and len(rest) > 2:
                    rest = rest[1:-1].strip()
                return f"{emoji} *{rest}*"
            return f"{default_icon} *{t}*"

        # Header 1-3 (#, ##, ###)
        m_h13 = _re.match(r"^#{1,3}\s+(.*)$", line)
        if m_h13:
            processed_lines.append(_format_header(m_h13.group(1), "📌"))
            continue

        # Header 4-6 (####)
        m_h4 = _re.match(r"^#{4,6}\s+(.*)$", line)
        if m_h4:
            processed_lines.append(_format_header(m_h4.group(1), "🔹"))
            continue

        # Nested bullets (2+ spaces followed by * or - or +)
        m_nested = _re.match(r"^(\s{2,})[*+-]\s+(.*)$", line)
        if m_nested:
            indent = m_nested.group(1)
            content = m_nested.group(2)
            processed_lines.append(f"{indent}▫️ {content}")
            continue

        # Top-level bullets (*, -, +)
        m_top = _re.match(r"^[*+-]\s+(.*)$", line)
        if m_top:
            content = m_top.group(1)
            processed_lines.append(f"• {content}")
            continue

        processed_lines.append(line)

    flush_table()
    res = "\n".join(processed_lines)

    # 4. Inline formatting outside code blocks
    parts = _re.split(r"(```[\s\S]*?```|`[^`]+`)", res)
    for i in range(0, len(parts), 2):
        # Convert **bold** to *bold*
        parts[i] = _re.sub(r"\*\*([^*]+)\*\*", r"*\1*", parts[i])
        # Escape isolated underscores in identifiers (e.g. abc_def.xlsx -> abc\_def.xlsx)
        parts[i] = _re.sub(r"(?<=\w)_(?=\w)", r"\_", parts[i])

    res = "".join(parts)

    # 5. Asterisk pairing check (Telegram Markdown v1 will reject odd asterisks)
    parts = _re.split(r"(```[\s\S]*?```|`[^`]+`)", res)
    total_stars = sum(parts[i].count("*") for i in range(0, len(parts), 2))
    if total_stars % 2 != 0:
        # Escape the last rogue asterisk
        for i in range(len(parts) - 1, -1, -2):
            if "*" in parts[i]:
                idx = parts[i].rfind("*")
                parts[i] = parts[i][:idx] + "\\*" + parts[i][idx + 1:]
                break
        res = "".join(parts)

    res = _re.sub(r"\n{3,}", "\n\n", res).strip()
    return res


# --- Edit-in-place target untuk tombol menu -------------------------------
# Saat user menekan tombol inline, output perintah diedit ke pesan menu itu
# sendiri (rapi, satu pesan) alih-alih kirim pesan baru. Target di-key per
# objek `context` (unik per update di PTB) sehingga tidak pernah bocor ke
# update lain, dan dipakai sekali lalu dibuang.
_MENU_TARGET: dict[int, tuple] = {}
_TARGET_TTL = 30.0


def set_menu_target(context, query, chat_id: int, back: bool = True) -> None:
    """Tandai pesan menu yang sedang diklik agar jawaban mengeditnya.

    back=False → jangan tambahkan tombol ◀️ Menu (untuk render ulang menu).
    """
    now = time.monotonic()
    for k in [k for k, v in _MENU_TARGET.items() if now - v[2] > _TARGET_TTL]:
        _MENU_TARGET.pop(k, None)
    _MENU_TARGET[id(context)] = (query, chat_id, now, back)


def clear_menu_target(context) -> None:
    _MENU_TARGET.pop(id(context), None)


def _pop_menu_target(context, chat_id: int):
    """Ambil target (sekali pakai). None bila tidak cocok/kedaluwarsa."""
    entry = _MENU_TARGET.pop(id(context), None)
    if not entry:
        return None
    query, cid, ts, back = entry
    if cid != chat_id or time.monotonic() - ts > _TARGET_TTL:
        return None
    return (query, back)


def _with_back_button(reply_markup):
    """Tambahkan tombol ◀️ Menu ke markup (tanpa merusak markup asli)."""
    try:
        rows = [list(r) for r in (reply_markup.inline_keyboard if reply_markup else [])]
    except (AttributeError, TypeError):
        rows = []
    has_back = any(
        getattr(b, "callback_data", None) == "btn_menu" for row in rows for b in row
    )
    if not has_back:
        rows.append([InlineKeyboardButton("◀️ Menu", callback_data="btn_menu")])
    return InlineKeyboardMarkup(rows)

ARTIFACT_DIRS = [
    os.path.expanduser("~/Dokumen/ALFA_SWARM_OUTPUTS"),
    SANDBOX_DIR,
]
ARTIFACT_NOUNS = (
    "laporan",
    "file",
    "csv",
    "excel",
    "pdf",
    "website",
    "scrape",
    "grafik",
    "chart",
    "pptx",
    "dokumen",
    "landing",
)
COMPLETION_VERBS = (
    "sudah",
    "selesai",
    "berhasil",
    "telah dibuat",
    "sudah dibuat",
    "aku buatkan",
)


def _meetings_count() -> int:
    """Ground truth: jumlah rapat NYATA di database."""
    try:
        with database.get_sync_db() as conn:
            row = conn.execute("SELECT COUNT(*) FROM agent_meetings").fetchone()
            return int(row[0]) if row else 0
    except (sqlite3.Error, OSError, AttributeError):
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
        except (OSError, UnicodeDecodeError, ValueError):
            pass
    return sorted(sig)


def split_message(text: str, max_length: int = 3900) -> list[str]:
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
    context: Any,
    chat_id: int,
    text: str,
    reply_to_message_id: int | None = None,
    reply_markup: InlineKeyboardMarkup | None = None,
):
    """
    Safely send message to Telegram with automatic chunking and fallback to plain text
    if Markdown parsing fails.
    """
    cleaned = clean_telegram_markdown(text)
    chunks = split_message(cleaned)

    # Jika dipanggil dari siklus tombol menu → edit pesan menu di tempat
    target = _pop_menu_target(context, chat_id)
    if target is not None:
        query, want_back = target
        markup = _with_back_button(reply_markup) if want_back else reply_markup
        try:
            await query.edit_message_text(
                text=chunks[0], parse_mode=constants.ParseMode.MARKDOWN, reply_markup=markup
            )
            chunks = chunks[1:]
            if not chunks:
                return
        except Exception:
            try:
                await query.edit_message_text(text=chunks[0], reply_markup=markup)
                chunks = chunks[1:]
                if not chunks:
                    return
            except Exception:
                pass  # gagal edit (mis. teks identik/kelamaan) → kirim biasa

    for i, chunk in enumerate(chunks):
        markup = reply_markup if i == len(chunks) - 1 else None
        reply_id = reply_to_message_id if i == 0 else None
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=chunk,
                parse_mode=constants.ParseMode.MARKDOWN,
                reply_to_message_id=reply_id,
                reply_markup=markup,
            )
        except Exception:
            try:
                # Fallback to plain text without parse mode
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=chunk,
                    reply_to_message_id=reply_id,
                    reply_markup=markup,
                )
            except Exception:
                try:
                    # Last resort: tanpa markup sama sekali (tombol URL invalid
                    # tidak boleh membuat pesan hilang total)
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=chunk,
                        reply_to_message_id=reply_id,
                    )
                except Exception as e:
                    logger.error(f"Failed to send message chunk: {e}")


async def send_typing_loop(
    chat_id: int,
    context: ContextTypes.DEFAULT_TYPE,
    stop_event: asyncio.Event,
    action=constants.ChatAction.TYPING,
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
    if len(text) > 900 and (
        text.count("\n- ") >= 4 or text.count("\n* ") >= 4 or text.count("\n1. ") >= 3
    ):
        return True
    return False
