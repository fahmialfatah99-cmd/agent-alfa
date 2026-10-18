"""Menu WA interaktif: navigasi tombol + edit-di-tempat (satu pesan, rapi).

Skema callback (≤64 byte):  wx|<aksi>|<arg>
  home            panel /wa
  chats|<page>    daftar chat (tombol per chat)
  chat|<idx>      riwayat satu chat (idx = cache daftar terakhir user)
  in|<page>       pesan masuk + tombol refresh
  fmt             daftar format + tombol toggle per baris
  ft|<idx>        toggle format lalu render ulang daftar
  rep|<page>|<f>  laporan (f = idx format, -1 = semua)
  send            petunjuk /wakirim
"""

import logging
import time
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest, RetryAfter
from telegram.ext import ContextTypes

from alfa.bot.advanced_commands import (
    _WA_TYPE_ICON,
    _wa_esc,
    _wa_sender,
    _wa_time,
    _wa_time_iso,
)
from alfa.bot.config import is_authorized

logger = logging.getLogger("TelegramAIAgent")

_PAGE_CHATS = 8
_PAGE_IN = 6
_PAGE_REP = 3

# Cache daftar terakhir per user agar callback pakai indeks pendek (TTL 5 mnt)
_CACHE: dict[int, dict[str, Any]] = {}
_CACHE_TTL = 300.0


def _get_bot_module():
    import sys

    return sys.modules.get("alfa.bot.telegram_bot")


def _is_authorized(user_id: int) -> bool:
    mod = _get_bot_module()
    if mod and hasattr(mod, "is_authorized"):
        return bool(mod.is_authorized(user_id))
    return is_authorized(user_id)


def _cache_get(user_id: int, key: str) -> list:
    slot = _CACHE.get(user_id)
    if not slot or time.monotonic() - slot.get("ts", 0) > _CACHE_TTL:
        return []
    return slot.get(key, []) or []


def _cache_put(user_id: int, key: str, value: list) -> None:
    slot = _CACHE.get(user_id) or {"ts": time.monotonic()}
    slot[key] = value
    slot["ts"] = time.monotonic()
    _CACHE[user_id] = slot


def _nav_row(prefix: str, page: int, total_pages: int, extra: str = "") -> list:
    row = []
    if page > 0:
        row.append(InlineKeyboardButton("◀️", callback_data=f"wx|{prefix}|{page - 1}{extra}"))
    row.append(InlineKeyboardButton(f"{page + 1}/{max(1, total_pages)}", callback_data="wx|noop"))
    if page < total_pages - 1:
        row.append(InlineKeyboardButton("▶️", callback_data=f"wx|{prefix}|{page + 1}{extra}"))
    return row


async def _edit_or_send(
    query, context: ContextTypes.DEFAULT_TYPE, chat_id: int, text: str, markup=None
) -> None:
    try:
        await query.edit_message_text(text=text, reply_markup=markup, parse_mode="Markdown")
        return
    except BadRequest as e:
        if "message is not modified" in str(e).lower():
            return
    except RetryAfter:
        return
    except Exception:
        pass
    try:
        await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=markup, parse_mode="Markdown")
    except Exception:
        try:
            await context.bot.send_message(chat_id=chat_id, text=text)
        except Exception as e2:
            logger.warning(f"[wa_menu] kirim gagal: {e2}")


def _chat_label(c: dict) -> str:
    icon = "👥" if c.get("is_group") else "👤"
    name = _wa_esc(str(c.get("name", "?"))[:28])
    unread = f" ({c['unread']})" if c.get("unread") else ""
    return f"{icon} {name}{unread}"


async def render_chats(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0) -> None:
    from alfa import tools as _tools

    query = update.callback_query
    chat_id = update.effective_chat.id if update.effective_chat else 0
    user_id = update.effective_user.id if update.effective_user else 0
    res = _tools.wa_get_chats(limit=40)
    if isinstance(res, dict) and res.get("status") == "error":
        await _edit_or_send(query, context, chat_id, f"📵 {res.get('message')}\nCek `/wa` untuk scan QR.")
        return
    chats = res.get("chats", []) or []
    _cache_put(user_id, "chats", chats)
    if not chats:
        await _edit_or_send(query, context, chat_id, "💬 Belum ada chat WA.", _home_kb())
        return
    pages = max(1, (len(chats) + _PAGE_CHATS - 1) // _PAGE_CHATS)
    page = max(0, min(page, pages - 1))
    chunk = chats[page * _PAGE_CHATS : page * _PAGE_CHATS + _PAGE_CHATS]
    kb = [[InlineKeyboardButton(_chat_label(c), callback_data=f"wx|chat|{page * _PAGE_CHATS + i}")] for i, c in enumerate(chunk)]
    kb.append(_nav_row("chats", page, pages))
    kb.append([InlineKeyboardButton("🏠 Menu WA", callback_data="wx|home")])
    await _edit_or_send(
        query, context, chat_id,
        "💬 **Chat WhatsApp** — ketuk untuk baca isi:",
        InlineKeyboardMarkup(kb),
    )


async def render_chat_detail(update: Update, context: ContextTypes.DEFAULT_TYPE, idx: int) -> None:
    from alfa import tools as _tools

    query = update.callback_query
    chat_id = update.effective_chat.id if update.effective_chat else 0
    user_id = update.effective_user.id if update.effective_user else 0
    chats = _cache_get(user_id, "chats")
    if not chats or not (0 <= idx < len(chats)):
        # Cache basi — muat ulang lalu minta pilih lagi
        await render_chats(update, context, 0)
        return
    target = chats[idx]
    ref = target.get("id") or target.get("name")
    res = _tools.wa_get_messages(chat=ref, limit=12)
    if isinstance(res, dict) and res.get("status") == "error":
        await _edit_or_send(query, context, chat_id, f"📵 {res.get('message')}")
        return
    msgs = res.get("messages", []) or []
    lines = [f"💬 **{_wa_esc(res.get('chat_name', target.get('name', '?')))}**\n"]
    for m in msgs[-12:]:
        who = "kamu" if m.get("from_me") else _wa_esc(m.get("sender", "?"))
        lines.append(f"[{_wa_time(m.get('ts', 0))}] **{who}:** {_wa_esc(m.get('body', ''))[:220]}")
    kb = [
        [InlineKeyboardButton("◀️ Daftar Chat", callback_data="wx|chats|0")],
        [InlineKeyboardButton("🏠 Menu WA", callback_data="wx|home")],
    ]
    await _edit_or_send(query, context, chat_id, "\n".join(lines) or "💬 Kosong.", InlineKeyboardMarkup(kb))


async def render_incoming(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0) -> None:
    from alfa import tools as _tools

    query = update.callback_query
    chat_id = update.effective_chat.id if update.effective_chat else 0
    res = _tools.wa_get_incoming(limit=30)
    if isinstance(res, dict) and res.get("status") == "error":
        await _edit_or_send(query, context, chat_id, f"📵 {res.get('message')}")
        return
    items = res.get("incoming", []) or []
    if not items:
        kb = [[InlineKeyboardButton("🔄 Refresh", callback_data="wx|in|0")],
              [InlineKeyboardButton("🏠 Menu WA", callback_data="wx|home")]]
        await _edit_or_send(query, context, chat_id, "📥 Belum ada pesan masuk terekam.", InlineKeyboardMarkup(kb))
        return
    ordered = list(reversed(items))
    pages = max(1, (len(ordered) + _PAGE_IN - 1) // _PAGE_IN)
    page = max(0, min(page, pages - 1))
    chunk = ordered[page * _PAGE_IN : page * _PAGE_IN + _PAGE_IN]
    lines = ["📥 **Pesan WA Masuk**\n"]
    for it in chunk:
        icon = _WA_TYPE_ICON.get(str(it.get("msg_type") or ""), "") or ("👥" if it.get("is_group") else "👤")
        chat = _wa_esc(it.get("chat_name") or "")
        if not chat:
            raw = str(it.get("chat") or "").split("@")[0]
            chat = ("…" + raw[-4:]) if raw.isdigit() and len(raw) > 8 else (raw or "?")
        body = _wa_esc(it.get("body", ""))[:160] or "_(kosong)_"
        if it.get("is_group") and not it.get("from_me"):
            lines.append(f"{icon} **{chat}** — {_wa_sender(it)} · {_wa_time_iso(it.get('ts', ''))}\n   {body}")
        else:
            lines.append(f"{icon} **{chat}** · {_wa_time_iso(it.get('ts', ''))}\n   {body}")
    kb = [[InlineKeyboardButton("🔄 Refresh", callback_data="wx|in|0")]]
    kb.append(_nav_row("in", page, pages))
    kb.append([InlineKeyboardButton("🏠 Menu WA", callback_data="wx|home")])
    await _edit_or_send(query, context, chat_id, "\n".join(lines), InlineKeyboardMarkup(kb))


async def render_formats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from alfa import tools as _tools

    query = update.callback_query
    chat_id = update.effective_chat.id if update.effective_chat else 0
    user_id = update.effective_user.id if update.effective_user else 0
    res = _tools.wa_list_formats()
    if isinstance(res, dict) and res.get("status") == "error":
        await _edit_or_send(query, context, chat_id, f"📵 {res.get('message')}")
        return
    fmts = res.get("formats", []) or []
    _cache_put(user_id, "formats", [f.get("name", "?") for f in fmts])
    on = sum(1 for f in fmts if f.get("enabled", True))
    kb = []
    for i, f in enumerate(fmts):
        icon = "✅" if f.get("enabled", True) else "⛔"
        kb.append([InlineKeyboardButton(f"{icon} {_wa_esc(str(f.get('name', '?'))[:30])}", callback_data=f"wx|ft|{i}")])
    kb.append([InlineKeyboardButton("🏠 Menu WA", callback_data="wx|home")])
    await _edit_or_send(
        query, context, chat_id,
        f"📋 **Format Pencatatan ({on}/{len(fmts)} aktif)**\nKetuk untuk hidup/matikan • atur keyword via `/waformat`",
        InlineKeyboardMarkup(kb),
    )


async def render_reports(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0, fidx: int = -1) -> None:
    from alfa import tools as _tools

    query = update.callback_query
    chat_id = update.effective_chat.id if update.effective_chat else 0
    user_id = update.effective_user.id if update.effective_user else 0
    fmt_names = _cache_get(user_id, "formats")
    fmt = ""
    if fidx >= 0 and fidx < len(fmt_names):
        fmt = fmt_names[fidx]
    res = _tools.wa_get_records(report_format=fmt, limit=30)
    if isinstance(res, dict) and res.get("status") == "error":
        await _edit_or_send(query, context, chat_id, f"📵 {res.get('message')}")
        return
    recs = res.get("records", []) or []
    title = f" — **{_wa_esc(fmt)}**" if fmt else ""
    if not recs:
        kb = [[InlineKeyboardButton("🏠 Menu WA", callback_data="wx|home")]]
        await _edit_or_send(query, context, chat_id, f"📊 Belum ada catatan{title}.", InlineKeyboardMarkup(kb))
        return
    pages = max(1, (len(recs) + _PAGE_REP - 1) // _PAGE_REP)
    page = max(0, min(page, pages - 1))
    chunk = recs[page * _PAGE_REP : page * _PAGE_REP + _PAGE_REP]
    lines = [f"📊 **Laporan{title}**\n"]
    for r in chunk:
        sync = "☁️" if r.get("synced_to_sheets") else "💾"
        body = _wa_esc(str(r.get("body", ""))[:200]).replace("\n", " ")
        lines.append(
            f"{sync} **{_wa_esc(r.get('format_name', r.get('tab', '?')))}** · {_wa_esc(r.get('timestamp', ''))}\n"
            f"   👤 {_wa_esc(r.get('sender', '?'))} di **{_wa_esc(r.get('group', '?'))}**\n"
            f"   _{body}_"
        )
    kb = [_nav_row("rep", page, pages, f"|{fidx}")]
    kb.append([InlineKeyboardButton("🏠 Menu WA", callback_data="wx|home")])
    await _edit_or_send(query, context, chat_id, "\n".join(lines), InlineKeyboardMarkup(kb))


def _home_kb() -> InlineKeyboardMarkup:
    # Susunan SAMA dengan panel /wa (wa_command) — satu versi menu WA saja.
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💬 Chat", callback_data="wx|chats|0"),
         InlineKeyboardButton("📥 Masuk", callback_data="wx|in|0")],
        [InlineKeyboardButton("📋 Format", callback_data="wx|fmt"),
         InlineKeyboardButton("📊 Laporan", callback_data="wx|rep|0|-1")],
        [InlineKeyboardButton("🔄 Restart", callback_data="btn_wa_restart"),
         InlineKeyboardButton("📊 Cek Status", callback_data="btn_wa_status")],
        [InlineKeyboardButton("▶️ Start", callback_data="btn_wa_start"),
         InlineKeyboardButton("⏹️ Stop", callback_data="btn_wa_stop")],
        [InlineKeyboardButton("◀️ Menu Utama", callback_data="btn_menu")],
    ])


async def render_home(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from alfa import tools as _tools

    query = update.callback_query
    chat_id = update.effective_chat.id if update.effective_chat else 0
    try:
        st = _tools.manage_wa_sheets_bot("status")
        svc = "🟢 jalan" if st.get("is_running") else "🔴 mati"
    except Exception:
        svc = "?"
    try:
        me = _tools.wa_get_me()
        who = me.get("me", {}).get("pushname", "") if isinstance(me, dict) and me.get("status") == "success" else ""
    except Exception:
        who = ""
    text = f"📱 **Menu WhatsApp** (service {svc}" + (f" • {who}" if who else "") + ")\nPilih fitur:\n✉️ Kirim via `/wakirim <tujuan> <pesan>`"
    kb = _home_kb()
    try:
        dash_url = (_tools.open_web_dashboard(port=8080).get("network_url") or "")
        if dash_url and not dash_url.startswith("http://localhost"):
            rows = [list(r) for r in kb.inline_keyboard]
            rows.insert(
                len(rows) - 1,
                [InlineKeyboardButton("🌐 Buka Web Dashboard", url=dash_url)],
            )
            kb = InlineKeyboardMarkup(rows)
    except Exception:
        pass
    if query is not None:
        await _edit_or_send(query, context, chat_id, text, kb)
    else:
        from alfa.bot.helpers import safe_send_message

        await safe_send_message(context, chat_id, text, reply_markup=kb)


async def handle_wa_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Router callback wx|*. Return True bila ditangani."""
    query = update.callback_query
    if not query:
        return False
    data = query.data or ""
    if not data.startswith("wx|"):
        return False
    user_id = update.effective_user.id if update.effective_user else 0
    chat_id = update.effective_chat.id if update.effective_chat else 0
    if not _is_authorized(user_id):
        await query.answer()
        return True
    await query.answer()
    parts = data.split("|")
    action = parts[1] if len(parts) > 1 else ""
    try:
        if action == "home":
            await render_home(update, context)
        elif action == "chats":
            await render_chats(update, context, int(parts[2]) if len(parts) > 2 else 0)
        elif action == "chat":
            await render_chat_detail(update, context, int(parts[2]) if len(parts) > 2 else -1)
        elif action == "in":
            await render_incoming(update, context, int(parts[2]) if len(parts) > 2 else 0)
        elif action == "fmt":
            await render_formats(update, context)
        elif action == "ft":
            from alfa import tools as _tools

            names = _cache_get(user_id, "formats")
            idx = int(parts[2]) if len(parts) > 2 else -1
            if 0 <= idx < len(names):
                cur = _tools.wa_list_formats()
                fmts = cur.get("formats", []) if isinstance(cur, dict) else []
                enabled = True
                for f in fmts:
                    if f.get("name") == names[idx]:
                        enabled = not f.get("enabled", True)
                _tools.wa_toggle_format(name=names[idx], enabled=enabled)
            await render_formats(update, context)
        elif action == "rep":
            page = int(parts[2]) if len(parts) > 2 else 0
            fidx = int(parts[3]) if len(parts) > 3 else -1
            await render_reports(update, context, page, fidx)
        elif action == "send":
            await _edit_or_send(
                query, context, chat_id,
                "✉️ **Kirim WA:** `/wakirim <nomor|nama grup> <pesan>`\nContoh: `/wakirim 0812xxxx halo`",
                _home_kb(),
            )
        elif action == "noop":
            pass
    except (ValueError, IndexError):
        pass
    except Exception as e:
        logger.warning(f"[wa_menu] {e}")
    return True


__all__ = [
    "handle_wa_callback",
    "render_chats",
    "render_chat_detail",
    "render_formats",
    "render_home",
    "render_incoming",
    "render_reports",
]
