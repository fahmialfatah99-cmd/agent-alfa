"""Perintah & callback /sites (daftar aplikasi lokal)."""
from __future__ import annotations

import logging
from typing import Any, cast

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from alfa import tools
from alfa.bot.advanced_commands._common import _ADV_ERR
from alfa.bot.advanced_commands._compat import is_authorized, safe_send_message
from alfa.bot.advanced_commands.wa import _wa_esc

logger = logging.getLogger("TelegramAIAgent")

_SITES_CACHE: dict = {}
_SITES_TTL = 30

def _lan_ip() -> str:
    try:
        import socket as _s

        s = _s.socket(_s.AF_INET, _s.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return str(ip)
    except OSError:
        return "127.0.0.1"

def _sites_cached(user_id: int) -> list[dict]:
    import time as _t

    now = _t.monotonic()
    hit = _SITES_CACHE.get(user_id)
    if hit and now - hit[0] < _SITES_TTL:
        return cast("list[dict[str, Any]]", hit[1])
    rows = tools.serve_site(action="status").get("sites", []) or []
    _SITES_CACHE[user_id] = (now, rows)
    return rows

def _site_kb(rows: list[dict]) -> InlineKeyboardMarkup:
    kb = []
    for i, s in enumerate(rows):
        dot = "🟢" if (s.get("backend_on") or s.get("frontend_on")) else "⚪"
        label = f"{dot} {_wa_esc(s.get('title', s.get('slug', '?'))[:28])}"
        kb.append([InlineKeyboardButton(label, callback_data=f"st|view|{i}")])
    kb.append([InlineKeyboardButton("🔄 Refresh", callback_data="st|list")])
    return InlineKeyboardMarkup(kb)

async def sites_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/sites — daftar website/proyek hasil agent, hidupkan dari Telegram."""
    user_id = update.effective_user.id if update.effective_user else 0
    chat_id = update.effective_chat.id if update.effective_chat else 0
    if not is_authorized(user_id):
        return

    _SITES_CACHE.pop(user_id, None)
    rows = _sites_cached(user_id)
    if not rows:
        await safe_send_message(
            context, chat_id,
            "🌐 Belum ada situs terdaftar. Misi swarm website otomatis masuk sini setelah harvest.",
        )
        return
    on = sum(1 for s in rows if s.get("backend_on") or s.get("frontend_on"))
    await safe_send_message(
        context, chat_id,
        f"🌐 **Galeri Hasil Kerja Agent ({on}/{len(rows)} hidup):**\nKetuk untuk kelola:",
        reply_markup=_site_kb(rows),
    )

async def handle_sites_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Router callback st|*. Return True bila ditangani."""
    query = update.callback_query
    if not query or not (query.data or "").startswith("st|"):
        return False
    user_id = update.effective_user.id if update.effective_user else 0
    chat_id = update.effective_chat.id if update.effective_chat else 0
    if not is_authorized(user_id):
        await query.answer()
        return True
    await query.answer()
    parts = (query.data or "").split("|")
    action = parts[1] if len(parts) > 1 else ""
    idx = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else -1

    async def _edit(text, markup=None):
        try:
            await query.edit_message_text(text=text, reply_markup=markup, parse_mode="Markdown")
        except TelegramError as e:
            # "message is not modified" = isi sama persis -> JANGAN kirim ulang
            # (menghasilkan pesan duplikat yang membingungkan user).
            if "not modified" in str(e).lower():
                return
            await safe_send_message(context, chat_id, text, reply_markup=markup)
        except _ADV_ERR:
            await safe_send_message(context, chat_id, text, reply_markup=markup)

    try:
        if action == "list":
            _SITES_CACHE.pop(user_id, None)
            rows = _sites_cached(user_id)
            on = sum(1 for s in rows if s.get("backend_on") or s.get("frontend_on"))
            await _edit(
                f"🌐 **Galeri Hasil Kerja Agent ({on}/{len(rows)} hidup):**\nKetuk untuk kelola:",
                _site_kb(rows),
            )
            return True
        rows = _sites_cached(user_id)
        if not (0 <= idx < len(rows)):
            await _edit("⏳ Daftar kedaluwarsa — muat ulang:", _site_kb(_sites_cached(user_id)))
            return True
        slug = rows[idx]["slug"]
        if action == "view":
            s = tools.serve_site(action="status").get("sites", []) or []
            hit = next((x for x in s if x.get("slug") == slug), rows[idx])
            stack = hit.get("stack", {}) or {}
            runnable = bool(
                stack.get("has_backend") or stack.get("has_frontend") or stack.get("has_php")
            )
            if not runnable:
                # Proyek non-server: tanpa tombol start/stop, tampilkan cara pakai.
                try:
                    info = tools.serve_site(action="start", slug=slug)
                    howto = info.get("note", "proyek non-server")
                except _ADV_ERR:
                    howto = "proyek non-server"
                kb = [[InlineKeyboardButton("◀️ Galeri", callback_data="st|list")]]
                await _edit(
                    f"📦 **{_wa_esc(hit.get('title', slug))}**\n`{slug}`\n"
                    f"_{_wa_esc(howto)}_\n\n"
                    "Jalankan manual dari terminal atau suruh agent via chat.",
                    InlineKeyboardMarkup(kb),
                )
                return True
            ip = _lan_ip()
            lines = [f"{'🟢' if hit.get('backend_on') else '⚪'} Backend"]
            if hit.get("backend_port"):
                lines[0] += f" — `http://{ip}:{hit['backend_port']}`"
            lines.append(f"{'🟢' if hit.get('frontend_on') else '⚪'} Frontend")
            if hit.get("frontend_port"):
                lines[1] += f" — `http://{ip}:{hit['frontend_port']}`"
            kb = [
                [InlineKeyboardButton("▶️ Hidupkan", callback_data=f"st|start|{idx}"),
                 InlineKeyboardButton("⏹️ Matikan", callback_data=f"st|stop|{idx}")],
                [InlineKeyboardButton("📜 Log", callback_data=f"st|logs|{idx}"),
                 InlineKeyboardButton("◀️ Galeri", callback_data="st|list")],
            ]
            await _edit(
                f"🌐 **{_wa_esc(hit.get('title', slug))}**\n`{slug}`\n" + "\n".join(lines),
                InlineKeyboardMarkup(kb),
            )
        elif action in ("start", "stop"):
            res = tools.serve_site(action=action, slug=slug)
            _SITES_CACHE.pop(user_id, None)
            if res.get("status") == "error":
                await _edit(f"❌ {res.get('message')}")
            else:
                det = [f"• {k}: `{v}`" for k, v in res.items() if k not in ("status", "slug", "title")]
                await _edit(
                    f"{'🟢' if action == 'start' else '⏹️'} **{_wa_esc(res.get('title', slug))}** "
                    f"{'hidup' if action == 'start' else 'mati'}.\n" + "\n".join(det),
                    InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Galeri", callback_data="st|list")]]),
                )
        elif action == "logs":
            res = tools.serve_site(action="logs", slug=slug)
            chunks = []
            for k, v in (res.get("logs") or {}).items():
                tail = (v or "").strip().split("\n")[-12:]
                chunks.append(f"**{k}:**\n```\n" + "\n".join(tail[-12:]) + "\n```")
            await _edit(
                f"📜 **Log {slug}:**\n" + ("\n".join(chunks) if chunks else "_kosong_"),
                InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Galeri", callback_data="st|list")]]),
            )
    except _ADV_ERR as e:
        logger.warning(f"[sites_menu] {e}")
    return True
