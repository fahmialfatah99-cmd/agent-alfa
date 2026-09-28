"""Human-in-the-loop permission gatekeeper and async approval dispatcher."""

import asyncio
import json
import os
import uuid

from alfa.core.perm.constants import (
    _LABELS,
    APPROVAL_TIMEOUT,
    DEFAULT_TIER,
    NO_CHANNEL_POLICY,
    PERMISSION_GATE_ENABLED,
    SAFE_TOOLS,
    TOOL_CLASSIFICATION,
    TRUST_THRESHOLD,
    RiskTier,
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


def should_auto_approve(chat_id: int, tool_name: str) -> tuple[bool, str]:
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


def check_headless_approval(
    chat_id: int | None, tool_name: str, arguments_json: str = "{}"
) -> str | None:
    """Persetujuan non-interaktif untuk eksekusi dashboard-direct dan MCP.

    Tidak ada prompt Telegram, jadi berlaku kebijakan NO_CHANNEL_POLICY yang
    sama seperti cabang tanpa-kanal di request_approval (bukan trust score):
    batas keamanannya adalah auth dashboard / operator lokal.
    Return None bila diizinkan; pesan penolakan bila ditolak.
    """
    import time as _time

    if not PERMISSION_GATE_ENABLED:
        return None
    if chat_id is None:
        chat_id = 0
    tier = get_tool_tier(tool_name)
    started = _time.time()
    if _no_channel_allows(tier):
        _record(
            chat_id,
            tool_name,
            tier,
            "auto_approved:headless",
            arguments_json,
            started,
        )
        return None
    _record(chat_id, tool_name, tier, "deny:headless_tier", arguments_json, started)
    return (
        f"[DITOLAK] Tool '{tool_name}' (tier {tier.value}) tidak diizinkan tanpa "
        f"kanal approval (kebijakan NO_CHANNEL_POLICY={NO_CHANNEL_POLICY}). "
        f"Jalankan melalui bot Telegram dengan approval interaktif."
    )


# ── Registry permintaan yang menunggu keputusan ──────────────────────────────
_PENDING: dict[str, dict] = {}


def is_enabled() -> bool:
    return PERMISSION_GATE_ENABLED


def make_gate(chat_id: int | None):
    """Kembalikan closure async gate(tool_name, args_json)->Optional[str].
    Return None = boleh jalan; str = pesan penolakan utk dimakan model."""
    if not PERMISSION_GATE_ENABLED or chat_id is None:
        return None

    async def gate(tool_name: str, arguments_json: str = "{}") -> str | None:
        return await request_approval(tool_name, arguments_json, chat_id)

    return gate


def _no_channel_allows(tier: RiskTier) -> bool:
    """Bolehkan tool saat tidak ada kanal approval (dashboard tanpa Telegram)."""
    if NO_CHANNEL_POLICY == "allow_all":
        return True
    if NO_CHANNEL_POLICY in {"allow_low_medium", "allow_low_medium_only"}:
        return tier in (RiskTier.LOW, RiskTier.MEDIUM)
    return False


# Kunci argumen yang nilainya tidak boleh tersimpan mentah di audit trail.
_SECRET_KEY_HINTS = (
    "password",
    "passwd",
    "api_key",
    "apikey",
    "secret",
    "token",
    "private_key",
    "client_secret",
    "access_key",
)

_REDACTED = "***REDACTED***"


def _redact_args_json(args_json: str) -> str:
    """Mask secret values in tool arguments before persisting to audit trail."""
    if not args_json:
        return args_json
    try:
        data = json.loads(args_json)
        if isinstance(data, dict):
            redacted = {
                k: (_REDACTED if any(h in k.lower() for h in _SECRET_KEY_HINTS) else v)
                for k, v in data.items()
            }
            return json.dumps(redacted, ensure_ascii=False, default=str)
    except Exception:
        pass
    import re as _re

    try:
        return _re.sub(
            r'("(?:[^"\\]|\\.)*(?:password|passwd|api_key|apikey|secret|token|private_key|client_secret|access_key)(?:[^"\\]|\\.)*"\s*:\s*)"(?:[^"\\]|\\.)*"',
            r"\1" + f'"{_REDACTED}"',
            args_json,
            flags=_re.IGNORECASE,
        )
    except Exception:
        return args_json


def _record(
    chat_id: int,
    tool_name: str,
    tier: RiskTier,
    decision: str,
    args_json: str,
    started: float,
) -> None:
    """Simpan audit trail + update trust score (skor naik saat user mengizinkan)."""
    import time as _time

    args_json = _redact_args_json(args_json)
    rt = max(0.0, _time.time() - started)
    try:
        log_permission_decision(
            int(chat_id),
            tool_name,
            tier.value,
            decision,
            args_json,
            rt,
        )
    except Exception:  # noqa: BLE001
        pass
    if decision in ("once", "always", "auto_approved"):
        try:
            update_trust_score(
                int(chat_id), was_safe=(tier == RiskTier.LOW), response_time=rt
            )
        except Exception:  # noqa: BLE001
            pass


async def request_approval(
    tool_name: str, arguments_json: str = "{}", chat_id: int | None = None
) -> str | None:
    """Tanya izin ke pengguna via tombol Telegram.
    Return None bila diizinkan; string penolakan bila ditolak/timeout."""
    if not PERMISSION_GATE_ENABLED or chat_id is None:
        return None
    if tool_name in SAFE_TOOLS:
        return None
    if is_always_allowed(chat_id, tool_name):
        return None

    import time as _time

    tier = get_tool_tier(tool_name)
    started = _time.time()

    # 1) Skor kepercayaan: tool LOW selalu lolos, MEDIUM lolos bila trust cukup
    auto_ok, auto_reason = should_auto_approve(chat_id, tool_name)
    if auto_ok:
        _record(
            chat_id,
            tool_name,
            tier,
            auto_reason or "auto_approved",
            arguments_json,
            started,
        )
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

        from alfa.swarm.subagents import get_telegram_app

        app = get_telegram_app()
        markup = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(text, callback_data=f"perm|{req_id}|{act}")
                    for text, act in row
                ]
                for row in keyboard
            ]
        )
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
        _PENDING.pop(req_id, None)
        # 2) Tidak ada kanal approval (mis. Web Dashboard tanpa bot Telegram).
        #    Dulu selalu fail-closed -> agent benar-benar tidak bisa bergerak.
        if _no_channel_allows(tier):
            _record(
                chat_id,
                tool_name,
                tier,
                "auto_approved:no_channel",
                arguments_json,
                started,
            )
            logger.warning(
                f"[Gate] Tidak ada kanal izin untuk {tool_name}; "
                f"tier {tier.value} diizinkan otomatis (NO_CHANNEL_POLICY="
                f"{NO_CHANNEL_POLICY}). Alasan: {e}"
            )
            return None
        logger.warning(
            f"Gagal kirim keyboard izin ({e}) -> penolakan aman (fail-closed)."
        )
        fail_mode = os.getenv("PERMISSION_GATE_FAIL_MODE", "deny").strip().lower()
        if fail_mode == "allow":
            _record(
                chat_id,
                tool_name,
                tier,
                "auto_approved:fail_open",
                arguments_json,
                started,
            )
            return None
        _record(chat_id, tool_name, tier, "deny:no_channel", arguments_json, started)
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
    if decision == "timeout" and sent_message is not None:
        try:
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup

            from alfa.swarm.subagents import get_telegram_app

            app = get_telegram_app()
            if app:
                base_text = sent_message.text or ""
                timeout_markup = InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                "⏰ Kedaluwarsa (Timeout)", callback_data="perm_done"
                            )
                        ]
                    ]
                )
                await app.bot.edit_message_text(
                    chat_id=int(chat_id),
                    message_id=sent_message.message_id,
                    text=f"{base_text}\n\n→ Status: {label}",
                    reply_markup=timeout_markup,
                )
        except Exception as e:
            logger.debug(f"edit pesan izin timeout gagal (abaikan): {e}")
    elif sent_message is not None:
        # Fallback jika belum sempat diedit via callback query handler
        try:
            from alfa.swarm.subagents import get_telegram_app

            app = get_telegram_app()
            if app:
                base_text = sent_message.text or ""
                if "\n\n→ Status:" not in base_text and "\n\n→ " not in base_text:
                    await app.bot.edit_message_text(
                        chat_id=int(chat_id),
                        message_id=sent_message.message_id,
                        text=f"{base_text}\n\n→ Status: {label}",
                    )
        except Exception as e:
            logger.debug(f"edit pesan izin fallback gagal (abaikan): {e}")

    if decision == "always":
        save_always_allow(int(chat_id), tool_name)
        _record(chat_id, tool_name, tier, "always", arguments_json, started)
        logger.info(f"[Gate] {tool_name} -> ALWAYS ALLOW utk chat {chat_id}")
        return None
    if decision == "once":
        _record(chat_id, tool_name, tier, "once", arguments_json, started)
        logger.info(f"[Gate] {tool_name} -> allow sekali (chat {chat_id})")
        return None

    _record(chat_id, tool_name, tier, decision or "deny", arguments_json, started)
    logger.info(f"[Gate] {tool_name} -> DENIED ({decision}, chat {chat_id})")
    return (
        f"[DITOLAK USER] Pengguna menolak eksekusi tool '{tool_name}' "
        f"(alasan: {label}). Jangan coba lagi dengan cara yang sama untuk "
        f"permintaan ini; tanyakan alternatif kepada pengguna."
    )


async def handle_permission_callback(update, context) -> None:
    """Handler CallbackQueryHandler utk data 'perm|<req_id>|<decision>' atau 'perm_done'."""
    query = update.callback_query
    if not query:
        return

    data = query.data or ""
    if data == "perm_done":
        try:
            await query.answer(
                "Permintaan izin ini sudah selesai diproses.", show_alert=False
            )
        except Exception:
            pass
        return

    try:
        _, req_id, decision = data.split("|", 2)
    except Exception:
        try:
            await query.answer()
        except Exception:
            pass
        return

    entry = _PENDING.get(req_id)
    if not entry:
        try:
            await query.answer(
                "Permintaan sudah kedaluwarsa atau telah diproses.", show_alert=False
            )
        except Exception:
            pass
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

    label = _LABELS.get(decision, decision)
    if decision == "once":
        status_btn = "✅ Telah Diizinkan (Sekali)"
    elif decision == "always":
        status_btn = "🔁 Telah Diizinkan Selalu"
    elif decision == "deny":
        status_btn = "❌ Telah Ditolak"
    else:
        status_btn = f"🔘 {label}"

    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    updated_markup = InlineKeyboardMarkup(
        [[InlineKeyboardButton(status_btn, callback_data="perm_done")]]
    )

    # 1. Beri feedback respons instan ke Telegram (toast alert)
    try:
        await query.answer(f"Pilihan disimpan: {status_btn}")
    except Exception as e:
        logger.debug(f"query.answer gagal: {e}")

    # 2. Perbarui tampilan teks pesan dan ganti tombol menjadi status final
    try:
        base_text = query.message.text if query.message else ""
        if "\n\n→ Status:" in base_text:
            base_text = base_text.split("\n\n→ Status:")[0]
        elif "\n\n→ " in base_text:
            base_text = base_text.split("\n\n→ ")[0]

        new_text = f"{base_text}\n\n→ Status: {label}"
        await query.edit_message_text(text=new_text, reply_markup=updated_markup)
    except Exception as e:
        logger.debug(f"edit_message_text pada callback gagal: {e}")


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
