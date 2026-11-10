"""Reminder, secure password, and focus session tools."""
import logging
import math
import secrets
import string
from typing import Any

from alfa.core import database
from alfa.tools.registry import register_tool

logger = logging.getLogger("AgentTools.Integrations")

@register_tool(category="system")
def schedule_reminder(reminder_time_iso: str, message: str) -> dict[str, Any]:
    """
    Schedule a future proactive reminder or alert that the bot will send directly to Telegram.

    Args:
        reminder_time_iso: The target time in ISO format (YYYY-MM-DDTHH:MM:SS), e.g. '2026-08-19T08:00:00'.
        message: The reminder message content.
    """
    try:
        user_id = _current_user_id()
        chat_id = _current_chat_id()
        rem_id = database.add_reminder_sync(
            user_id=user_id,
            chat_id=chat_id,
            reminder_time_iso=reminder_time_iso,
            message=message,
        )
        return {
            "status": "success",
            "reminder_id": rem_id,
            "message": f"Pengingat #{rem_id} berhasil dijadwalkan pada {reminder_time_iso}: '{message}'",
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

@register_tool(category="system")
def generate_secure_password(
    length: int = 20,
    include_uppercase: bool = True,
    include_digits: bool = True,
    include_special: bool = True,
    count: int = 1,
) -> dict[str, Any]:
    """
    Generate one or more cryptographically secure random passwords.

    Args:
        length: Password length (8-128 characters, default: 20).
        include_uppercase: Include uppercase letters (default: True).
        include_digits: Include digits (default: True).
        include_special: Include special characters !@#$%^&* (default: True).
        count: Number of passwords to generate (1-10, default: 1).
    """
    try:
        length = max(8, min(128, length))
        count = max(1, min(10, count))

        chars = string.ascii_lowercase
        if include_uppercase:
            chars += string.ascii_uppercase
        if include_digits:
            chars += string.digits
        if include_special:
            chars += "!@#$%^&*_+-=?."

        passwords = []
        for _ in range(count):
            pw = "".join(secrets.choice(chars) for _ in range(length))
            passwords.append(pw)

        # Calculate entropy
        entropy = round(math.log2(len(chars)) * length, 1)
        strength = (
            "Sangat Kuat 🟢"
            if entropy > 80
            else (
                "Kuat 🔵"
                if entropy > 60
                else "Cukup 🟡"
                if entropy > 40
                else "Lemah 🔴"
            )
        )

        return {
            "status": "success",
            "passwords": passwords,
            "length": length,
            "entropy_bits": entropy,
            "strength": strength,
            "charset_size": len(chars),
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

@register_tool(category="system")
def start_focus_session(
    title: str, duration_minutes: int = 25, notes: str = ""
) -> dict[str, Any]:
    """
    GOD MODE: Focus & Pomodoro Productivity Session.
    Starts a deep work focus session with automatic timer, records target end time,
    and schedules an automatic Telegram completion alert.

    Args:
        title: Title/objective of the focus session (e.g. 'Code Review Backend', 'Menulis Laporan').
        duration_minutes: Duration in minutes (default: 25).
        notes: Optional extra notes for the session.
    """
    uid = _current_user_id()
    cid = _current_chat_id()
    if not uid:
        return {"status": "error", "message": "User context tidak ditemukan."}
    res = database.start_focus_session_sync(uid, cid, title, duration_minutes, notes)
    return {
        "status": "success",
        "message": f"🎯 Sesi fokus '{title}' ({duration_minutes} menit) dimulai! Berakhir pada: {res['end_time']}. Bot akan mengirim notifikasi saat waktu habis.",
        "session_details": res,
    }


def _current_user_id() -> int:
    """User id aktif — diambil lewat paket publik agar patch/mock tetap berlaku."""
    from alfa.tools.system import integrations as _pkg

    return _pkg.get_current_user_id()


def _current_chat_id() -> int:
    """Chat id aktif — diambil lewat paket publik agar patch/mock tetap berlaku."""
    from alfa.tools.system import integrations as _pkg

    return _pkg.get_current_chat_id()
