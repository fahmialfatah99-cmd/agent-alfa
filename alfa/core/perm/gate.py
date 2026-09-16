"""Human-in-the-loop permission gatekeeper and async approval dispatcher."""

import asyncio
import json
import logging
import os
import sys
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple

from alfa.core.perm.constants import (
    APPROVAL_TIMEOUT,
    DEFAULT_TIER,
    FAIL_MODE,
    PERMISSION_GATE_ENABLED,
    RiskTier,
    SAFE_TOOLS,
    TOOL_CLASSIFICATION,
    TRUST_THRESHOLD,
    logger,
)
from alfa.core.perm.store import (
    get_trust_score,
    is_always_allowed,
    log_permission_decision,
    save_always_allow,
    update_trust_score,
)


def get_tool_tier(tool_name: str) -> RiskTier:
    """Get risk tier for a tool."""
    if tool_name in SAFE_TOOLS:
        return RiskTier.LOW
    classification = TOOL_CLASSIFICATION.get(tool_name)
    if classification:
        return classification[0]
    return DEFAULT_TIER


def should_auto_approve(chat_id: int, tool_name: str) -> Tuple[bool, str]:
    """Determine if request should be auto-approved based on trust score and tier."""
    tier = get_tool_tier(tool_name)
    trust = get_trust_score(chat_id)
    
    # Auto-approve LOW tier always
    if tier == RiskTier.LOW:
        return True, "auto_approved"
    
    # Auto-approve MEDIUM tier if trust >= threshold
    if tier == RiskTier.MEDIUM and trust >= TRUST_THRESHOLD:
        return True, "auto_approved"
    
    # Auto-approve HIGH/CRITICAL only if very high trust
    if tier in (RiskTier.HIGH, RiskTier.CRITICAL) and trust >= 0.9:
        return True, "auto_approved"
    
    return False, ""


# ── Registry permintaan yang menunggu keputusan ──────────────────────────────
_PENDING: Dict[str, dict] = {}


def is_enabled() -> bool:
    return PERMISSION_GATE_ENABLED


def make_gate(chat_id: Optional[int]):
    """Kembalikan closure async gate(tool_name, args_json)->Optional[str].
    Return None = boleh jalan; str = pesan penolakan utk dimakan model."""
    if not PERMISSION_GATE_ENABLED or chat_id is None:
        return None

    async def gate(tool_name: str, arguments_json: str = "{}") -> Optional[str]:
        return await request_approval(tool_name, arguments_json, chat_id)

    return gate


async def request_approval(tool_name: str, arguments_json: str = "{}",
                           chat_id: int = None) -> Optional[str]:
    """Tanya izin ke pengguna via tombol Telegram.
    Return None bila diizinkan; string penolakan bila ditolak/timeout."""
    if not PERMISSION_GATE_ENABLED or chat_id is None:
        return None
    if tool_name in SAFE_TOOLS:
        return None
    if is_always_allowed(chat_id, tool_name):
        return None

    # Ringkas argumen agar enak dibaca di tombol/pesan
    try:
        args = json.loads(arguments_json or "{}")
        preview_parts = []
        for k, v in list(args.items())[:3]:
            s = str(v).replace("\n", " ")
            if len(s) > 120:
                s = s[:117] + "..."
            preview_parts.append(f"• {k}: {s}")
        arg_preview = "\n".join(preview_parts) if preview_parts else "(tanpa argumen)"
    except Exception:
        arg_preview = str(arguments_json)[:300]

    req_id = uuid.uuid4().hex[:10]
    ev = asyncio.Event()
    _PENDING[req_id] = {"event": ev, "decision": "", "chat_id": int(chat_id)}

    keyboard = [
        [
            ("✅ Izinkan", "once"),
            ("🔁 Izinkan Selalu", "always"),
            ("❌ Tolak", "deny"),
        ]
    ]

    sent_message = None
    try:
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        from subagents import get_telegram_app
        app = get_telegram_app()
        markup = InlineKeyboardMarkup([[
            InlineKeyboardButton(text, callback_data=f"perm|{req_id}|{act}")
            for text, act in row] for row in keyboard])
        sent_message = await app.bot.send_message(
            chat_id=int(chat_id),
            text=(
                "🔐 *PERMINTAAN IZIN AGENT*\n\n"
                f"🛠 Tool: `{tool_name}`\n"
                f"{arg_preview}\n\n"
                "Agent butuh persetujuanmu untuk melanjutkan."
            ),
            reply_markup=markup,
        )
    except Exception as e:
        logger.warning(
            f"Gagal kirim keyboard izin ({e}) -> penolakan aman (fail-closed).")
        _PENDING.pop(req_id, None)
        fail_mode = os.getenv("PERMISSION_GATE_FAIL_MODE", "deny").strip().lower()
        if fail_mode == "allow":
            return None
        return (
            f"[IZIN DITOLAK] Tool '{tool_name}' tergolong sensitif dan membutuhkan "
            f"konfirmasi izin langsung dari pemilik, tetapi notifikasi Telegram tidak dapat dikirim ({e}). "
            f"Eksekusi dibatalkan demi keamanan."
        )

    # Tunggu keputusan pengguna
    decision = "timeout"
    try:
        await asyncio.wait_for(ev.wait(), timeout=APPROVAL_TIMEOUT)
        decision = _PENDING.get(req_id, {}).get("decision") or "timeout"
    except asyncio.TimeoutError:
        pass
    finally:
        _PENDING.pop(req_id, None)

    label = _LABELS.get(decision, decision)
    if sent_message is not None:
        try:
            from subagents import get_telegram_app
            app = get_telegram_app()
            base_text = sent_message.text or ""
            await app.bot.edit_message_text(
                chat_id=int(chat_id), message_id=sent_message.message_id,
                text=f"{base_text}\n\n→ {label}")
        except Exception as e:
            logger.debug(f"edit pesan izin gagal (abaikan): {e}")

    if decision == "always":
        save_always_allow(int(chat_id), tool_name)
        logger.info(f"[Gate] {tool_name} -> ALWAYS ALLOW utk chat {chat_id}")
        return None
    if decision == "once":
        logger.info(f"[Gate] {tool_name} -> allow sekali (chat {chat_id})")
        return None

    logger.info(f"[Gate] {tool_name} -> DENIED ({decision}, chat {chat_id})")
    return (
        f"[DITOLAK USER] Pengguna menolak eksekusi tool '{tool_name}' "
        f"(alasan: {label}). Jangan coba lagi dengan cara yang sama untuk "
        f"permintaan ini; tanyakan alternatif kepada pengguna."
    )


async def handle_permission_callback(update, context) -> None:
    """Handler CallbackQueryHandler utk data 'perm|<req_id>|<decision>'."""
    query = update.callback_query
    try:
        _, req_id, decision = query.data.split("|", 2)
    except Exception:
        await query.answer()
        return

    entry = _PENDING.get(req_id)
    if not entry:
        await query.answer("Permintaan sudah kedaluwarsa.", show_alert=False)
        return

    # Hanya pemilik chat yang boleh memutuskan
    try:
        if int(query.from_user.id) != entry["chat_id"]:
            await query.answer("Bukan permintaan untuk kamu.", show_alert=True)
            return
    except Exception:
        pass

    entry["decision"] = decision
    entry["event"].set()
    try:
        await query.answer(_LABELS.get(decision, decision))
    except Exception:
        pass


def wrap_tool_for_afc(fn):
    """Bungkus fungsi tool sinkron menjadi async + gate — dipakai jalur
    Gemini AFC manual bila diperlukan (reserved)."""
    import functools

    name = getattr(fn, "__name__", "")

    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        denial = await request_approval(name, json.dumps(kwargs, default=str))
        if denial:
            return denial
        return fn(*args, **kwargs)

    return wrapper


# ── Defensive Security Auditor (migrated from security_auditor.py) ────────────
import socket
import ssl
import stat
import subprocess
import urllib.parse
import urllib.request
from datetime import datetime
