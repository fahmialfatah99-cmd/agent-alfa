"""Runtime tuning knobs shared by brain, bot pipeline, and system tools.

Satu sumber kebenaran untuk timeout, batas output tool, dan temperature
sehingga lapisan-lapisan (host exec → tool_exec → brain → turn_executor)
tidak lagi saling memotong dengan angka hardcode yang berbeda.

Semua nilai dibaca dari env saat dipanggil (setelah ``.env`` dimuat).
"""

from __future__ import annotations

import os

from alfa.core.config import ensure_env_loaded


def _env_int(name: str, default: int) -> int:
    ensure_env_loaded()
    try:
        return int(str(os.getenv(name, default)).strip())
    except (TypeError, ValueError):
        return default


def _unrestricted() -> bool:
    ensure_env_loaded()
    return os.getenv("ALFA_UNRESTRICTED", "false").strip().lower() == "true"


def host_exec_timeout(unrestricted: bool | None = None, default_restricted: int = 45) -> int:
    """Timeout subprocess host (bash/python). ``ALFA_HOST_TIMEOUT`` override."""
    if unrestricted is None:
        unrestricted = _unrestricted()
    return _env_int("ALFA_HOST_TIMEOUT", 600 if unrestricted else default_restricted)


def tool_exec_timeout() -> int:
    """Timeout satu panggilan tool di brain/turn executor.

    Selalu > timeout host supaya subprocess sempat dihentikan rapi oleh
    tool-nya sendiri (killpg) sebelum lapisan atas menyerah — mencegah
    proses yatim dan laporan "timeout" palsu.
    """
    explicit = os.getenv("ALFA_TOOL_TIMEOUT", "").strip()
    if explicit:
        return _env_int("ALFA_TOOL_TIMEOUT", 300)
    return max(300, host_exec_timeout() + 30)


def max_tool_output() -> int:
    """Batas karakter hasil tool yang dikirim balik ke model."""
    return max(1000, _env_int("ALFA_MAX_TOOL_OUTPUT", 12000))


def truncate_middle(text: str, limit: int, head_ratio: float = 0.6) -> str:
    """Potong teks panjang dengan menjaga KEPALA dan EKOR.

    Error/traceback hampir selalu ada di akhir output, jadi pemotongan
    head-only membuang informasi paling penting bagi agent.
    """
    text = "" if text is None else str(text)
    if limit <= 0 or len(text) <= limit:
        return text
    marker = f"\n...[{len(text) - limit} karakter dipotong]...\n"
    budget = max(0, limit - len(marker))
    head = int(budget * head_ratio)
    tail = budget - head
    return text[:head] + marker + (text[-tail:] if tail else "")


def tool_temperature(model: str = "") -> float | None:
    """Temperature untuk panggilan tool-calling.

    - ``ALFA_TEMPERATURE`` di env selalu menang (untuk semua provider).
    - Model Gemini 3.x: ``None`` → pakai default server (1.0). Google sangat
      menyarankan tidak menurunkannya; nilai < 1.0 bisa memicu looping.
    - Provider lain: 0.3 (lebih deterministik untuk argumen tool).
    """
    ensure_env_loaded()
    raw = os.getenv("ALFA_TEMPERATURE", "").strip()
    if raw:
        try:
            return float(raw)
        except ValueError:
            pass
    if (model or "").lower().removeprefix("models/").startswith("gemini-3"):
        return None
    return 0.3
