"""Digest WA cerdas: rangkuman AI atas catatan laporan WA terekam.

Kirim ke pemilik via Telegram (jadwal harian + on-demand /waringkas).
TIDAK menyentuh sisi WA: tanpa autoreply, tanpa kirim pesan WA.
"""

import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger("TelegramAIAgent")

SETTINGS_PREFIX = "wa_digest_"


def _setting(key: str, default: str = "") -> str:
    try:
        from alfa.core import database

        with database.get_sync_db() as conn:
            row = conn.execute(
                "SELECT value FROM system_settings WHERE key = ?", (key,)
            ).fetchone()
            if row and row["value"]:
                return str(row["value"])
    except Exception:
        pass
    return default


def _set_setting(key: str, value: str) -> None:
    try:
        from alfa.core import database

        with database.get_sync_db() as conn:
            conn.execute(
                "INSERT INTO system_settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
            conn.commit()
    except Exception as e:
        logger.debug(f"[digest] set setting gagal: {e}")


def digest_enabled() -> bool:
    return _setting(SETTINGS_PREFIX + "enabled", "1") != "0"


def digest_hours() -> list[str]:
    raw = _setting(SETTINGS_PREFIX + "hours", "07:00")
    return [h.strip() for h in raw.split(",") if h.strip()]


def _parse_ts(ts: str):
    for fmt in ("%d/%m/%Y, %H.%M.%S", "%d/%m/%Y %H.%M.%S", "%d/%m/%Y, %H:%M:%S"):
        try:
            return datetime.strptime(str(ts or "").strip(), fmt)
        except Exception:
            continue
    return None


def collect_records(report_format: str = "", limit: int = 50) -> list[dict]:
    """Ambil catatan terbaru; yang ber-timestamp hari ini didahulukan."""
    from alfa import tools as _tools

    res = _tools.wa_get_records(report_format=report_format, limit=limit)
    if not isinstance(res, dict) or res.get("status") == "error":
        return []
    recs = res.get("records", []) or []
    today = datetime.now().date()
    fresh: list[Any] = []
    stale: list[Any] = []
    for r in recs:
        dt = _parse_ts(r.get("timestamp", ""))
        (fresh if (dt is None or dt.date() == today) else stale).append(r)
    return (fresh + stale)[: max(1, min(limit, 30))]


def _esc(t) -> str:
    return (
        str(t or "")
        .replace("`", "'").replace("*", "·").replace("_", "‑")
        .replace("[", "(").replace("]", ")")
    )


async def summarize_records(records: list[dict]) -> str:
    """Ringkasan AI (satu turn murah). Return '' bila kuota habis/gagal."""
    if not records:
        return ""
    lines = []
    for r in records[:20]:
        body = " ".join(str(r.get("body", "")).split())[:300]
        lines.append(
            f"- [{r.get('format_name', r.get('tab', '?'))}] "
            f"{r.get('timestamp', '')} | {r.get('sender', '?')} di {r.get('group', '?')}: {body}"
        )
    prompt = (
        "[RINGKASAN WA] Berikut catatan laporan WhatsApp terbaru. Buat ringkasan "
        "cerdas Bahasa Indonesia santai, rapi, dan terstruktur (maksimal 12 baris):\n"
        "1) 3-5 hal PALING PENTING/mendesak (apa, siapa, di mana)\n"
        "2) Pola/masalah berulang bila ada\n"
        "3) Satu saran tindak lanjut konkret.\n"
        "Fakta saja — DILARANG mengarang.\n\n" + "\n".join(lines)
    )
    try:
        from alfa.bot.config import ALLOWED_USER_IDS
        from alfa.bot.turn_executor import run_agent_turn

        owner = int(ALLOWED_USER_IDS[0]) if ALLOWED_USER_IDS else 0
        out = await run_agent_turn(user_id=owner, user_prompt=prompt, chat_id=owner)
        return (out or "").strip()
    except Exception as e:
        logger.warning(f"[digest] ringkasan AI gagal: {e}")
        return ""


async def build_digest_text(report_format: str = "", limit: int = 15) -> str:
    """Susun teks digest lengkap (statistik + sorotan + ringkasan AI)."""
    recs = collect_records(report_format, max(limit, 15))
    title = f" — **{_esc(report_format)}**" if report_format else ""
    if not recs:
        return f"📭 **Digest WA{title}:** belum ada catatan terekam."
    counts: dict[str, int] = {}
    for r in recs:
        k = str(r.get("format_name", r.get("tab", "?")))
        counts[k] = counts.get(k, 0) + 1
    stat = ", ".join(f"{_esc(k)}×{v}" for k, v in sorted(counts.items()))
    lines = [
        f"📊 **Digest Cerdas WA{title}** ({len(recs)} catatan)",
        f"_{_esc(stat)}_",
        "",
    ]
    ai = await summarize_records(recs)
    if ai:
        from alfa.bot.helpers import clean_telegram_markdown

        lines.append("🧠 **Sorotan AI:**")
        lines.append(clean_telegram_markdown(ai).strip()[:1500])
        lines.append("")
    lines.append("📌 **Catatan Terbaru:**")
    for r in recs[:5]:
        fmt_name = _esc(r.get("format_name", r.get("tab", "?")))
        ts = _esc(r.get("timestamp", ""))
        sender = _esc(r.get("sender", "?"))
        group = _esc(r.get("group", ""))
        from_str = f"{sender} ({group})" if group and group != "?" else sender
        raw_body = " ".join(str(r.get("body", "")).split())
        body_snippet = _esc(raw_body[:140] + ("…" if len(raw_body) > 140 else ""))
        lines.append(f"• **{fmt_name}** · {ts} — {from_str}:\n  {body_snippet}")
    return "\n".join(lines)


async def send_digest(context_or_app, chat_id: int, report_format: str = "") -> bool:
    """Bangun + kirim digest ke satu chat Telegram. Return sukses."""
    try:
        from alfa.bot.helpers import safe_send_message

        text = await build_digest_text(report_format)
        await safe_send_message(context_or_app, chat_id, text)
        return True
    except Exception as e:
        logger.warning(f"[digest] kirim gagal: {e}")
        return False


__all__ = [
    "build_digest_text",
    "collect_records",
    "digest_enabled",
    "digest_hours",
    "send_digest",
    "summarize_records",
]
