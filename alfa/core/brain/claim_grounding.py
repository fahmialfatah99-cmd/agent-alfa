"""Grounding atribusi tool/library pada balasan agen.

Model bahasa kadang menyebut tool, library, atau engine yang sebenarnya tidak
dipanggil pada giliran tersebut (mis. ``"berhasil diekstrak dengan OCR
tesseract"`` padahal yang berjalan hanya tool vision). Modul ini memeriksa
klaim tersebut secara deterministik terhadap catatan eksekusi tool
(:mod:`alfa.core.runtime_ctx`) dan menambahkan peringatan yang jujur bila
klaim tidak terbukti.

Prinsip keamanan:

- hanya memeriksa istilah yang sudah dikurasi + nama tool yang ditulis dalam
  backtick, sehingga percakapan biasa tidak memicu peringatan;
- klaim harus berada dekat kata kerja penggunaan (``pakai``, ``dengan``,
  ``berhasil``, dst.) dan tidak sedang dalam konteks kondisional/negasi;
- semua kegagalan guard ditelan dengan log — tidak boleh mematikan giliran.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger("TelegramAIAgent")

_ATTRIBUTION_MARKER = "Catatan atribusi"

#: Alias library/engine -> token yang membuktikan eksekusi nyata.
_CLAIM_ALIASES: dict[str, tuple[str, ...]] = {
    "tesseract": ("tesseract", "pytesseract"),
    "pytesseract": ("tesseract", "pytesseract"),
    "easyocr": ("easyocr",),
    "paddleocr": ("paddleocr",),
    "whisper": ("whisper",),
    "playwright": ("playwright",),
    "puppeteer": ("puppeteer",),
    "selenium": ("selenium",),
    "ffmpeg": ("ffmpeg",),
    "openpyxl": ("openpyxl",),
    "pandas": ("pandas",),
    "libreoffice": ("libreoffice", "soffice"),
    "soffice": ("libreoffice", "soffice"),
    "pdftotext": ("pdftotext", "poppler"),
    "yt-dlp": ("yt-dlp", "youtube-dl"),
}

#: Kata kerja/frasa yang menandakan klaim *penggunaan*, bukan sekadar definisi.
_CLAIM_RE = re.compile(
    r"(?i)\b(pakai|memakai|menggunakan|gunakan|dipakai|dengan|via|berhasil|"
    r"sukses|sudah|telah|proses|ekstrak|ekstraksi|baca|membaca|scan|pindai|"
    r"konversi|render|jalankan|menjalankan)\b"
)

#: Penanda konteks kondisional/contoh -> bukan klaim eksekusi.
_CONDITIONAL_RE = re.compile(
    r"(?i)\b(jika|kalau|bila|seandainya|misalnya|contoh|opsi|alternatif)\b"
)

#: Negasi di dekat alias -> bukan klaim eksekusi.
_NEGATION_RE = re.compile(
    r"(?i)\b(tidak|belum|tanpa|bukan|gak|nggak|ngga|ga)\b"
)

_TOOL_NAME_RE = re.compile(r"`([A-Za-z][A-Za-z0-9_]{3,})`")

#: Error realistis saat memeriksa teks/registry (guard tidak boleh crash).
_GROUND_ERR = (
    AttributeError,
    ImportError,
    OSError,
    RuntimeError,
    TypeError,
    ValueError,
    re.error,
)


@dataclass(frozen=True)
class AttributionIssue:
    """Satu klaim tool/library yang tidak sesuai catatan eksekusi."""

    term: str
    reason: str

    def render(self) -> str:
        return f"`{self.term}` — {self.reason}"


def _in_fenced_code_block(reply: str, position: int) -> bool:
    """Apakah posisi berada di dalam fenced code block (```...```)?"""
    return reply[:position].count("```") % 2 == 1


def _executed_tokens(
    executed_tool_calls: list[dict[str, str]] | None,
) -> tuple[set[str], str]:
    """Kembalikan nama tool unik dan blob nama+argumen untuk pencocokan."""
    names: set[str] = set()
    parts: list[str] = []
    for call in executed_tool_calls or []:
        name = str(call.get("tool") or "").strip()
        if name:
            names.add(name)
            parts.append(name)
        args = str(call.get("args") or "")
        if args:
            parts.append(args)
    return names, " ".join(parts).lower()


def _is_claim_context(reply: str, start: int, end: int) -> bool:
    """Apakah kemunculan istilah berada dalam konteks klaim penggunaan."""
    left = max(0, start - 180)
    right = min(len(reply), end + 180)
    window = reply[left:right]
    if not _CLAIM_RE.search(window):
        return False
    if _CONDITIONAL_RE.search(window):
        return False
    before = reply[max(0, start - 60) : start]
    return not _NEGATION_RE.search(before)


def _grounded_alias(alias: str, executed_blob: str) -> bool:
    """Apakah alias (atau sinonimnya) tercatat dieksekusi?"""
    for token in _CLAIM_ALIASES.get(alias, (alias,)):
        if token.lower() in executed_blob:
            return True
    return False


def _alias_issues(
    reply: str,
    executed_blob: str,
) -> list[AttributionIssue]:
    """Periksa klaim library/engine yang dikurasi."""
    candidates: list[tuple[int, int, str]] = []
    for alias in _CLAIM_ALIASES:
        pattern = re.compile(rf"(?i)\b{re.escape(alias)}\b")
        for match in pattern.finditer(reply):
            candidates.append((match.start(), match.end(), alias))

    candidates.sort(key=lambda item: (item[0], item[1]))
    issues: list[AttributionIssue] = []
    seen_groups: set[tuple[str, ...]] = set()
    taken_until = -1
    for start, end, alias in candidates:
        if start < taken_until:
            continue
        if _in_fenced_code_block(reply, start):
            continue
        if not _is_claim_context(reply, start, end):
            continue
        taken_until = end
        if _grounded_alias(alias, executed_blob):
            continue
        group = tuple(sorted(_CLAIM_ALIASES.get(alias, (alias,))))
        if group in seen_groups:
            continue
        seen_groups.add(group)
        issues.append(
            AttributionIssue(
                alias,
                "tidak ada eksekusi yang cocok pada giliran ini",
            )
        )
    return issues


def _tool_name_issues(
    reply: str,
    executed_names: set[str],
) -> list[AttributionIssue]:
    """Periksa nama tool yang ditulis eksplisit dalam backtick."""
    try:
        from alfa.tools.registry import TOOL_REGISTRY
    except ImportError:
        return []

    issues: list[AttributionIssue] = []
    seen: set[str] = set()
    for match in _TOOL_NAME_RE.finditer(reply):
        name = match.group(1)
        if name in seen or name not in TOOL_REGISTRY or name in executed_names:
            continue
        if _in_fenced_code_block(reply, match.start()):
            continue
        if not _is_claim_context(reply, match.start(), match.end()):
            continue
        seen.add(name)
        issues.append(
            AttributionIssue(
                name,
                "tool ini tidak tercatat dieksekusi pada giliran ini",
            )
        )
    return issues


def verify_attribution_claims(
    reply: str,
    executed_tool_calls: list[dict[str, str]] | None,
) -> list[AttributionIssue]:
    """Kembalikan klaim atribusi yang tidak terbukti pada ``reply``."""
    if not reply:
        return []

    executed_names, executed_blob = _executed_tokens(executed_tool_calls)
    issues = _alias_issues(reply, executed_blob)
    issues.extend(_tool_name_issues(reply, executed_names))

    # Hilangkan duplikat berdasarkan istilah (urutan tetap).
    unique: list[AttributionIssue] = []
    for issue in issues:
        if issue.term not in {item.term for item in unique}:
            unique.append(issue)
    return unique


def format_attribution_warning(
    issues: list[AttributionIssue],
    executed_names: list[str] | None = None,
) -> str:
    """Format peringatan atribusi yang ditempelkan ke balasan pengguna."""
    lines = [
        "",
        "⚠️ *Catatan atribusi:* ada tool/library yang disebut tetapi tidak "
        "tercatat dieksekusi pada giliran ini.",
    ]
    for issue in issues[:3]:
        lines.append(f"• {issue.render()}")
    if len(issues) > 3:
        lines.append(f"• …dan {len(issues) - 3} klaim lain.")
    names = [name for name in (executed_names or []) if name]
    if names:
        shown = ", ".join(f"`{name}`" for name in names[:8])
        suffix = "…" if len(names) > 8 else ""
        lines.append(f"Tool yang tercatat: {shown}{suffix}")
    else:
        lines.append("Tidak ada tool yang tercatat pada giliran ini.")
    lines.append("Gunakan daftar tool yang tercatat di atas sebagai acuan.")
    return "\n".join(lines)


def apply_attribution_guard(
    reply: str,
    executed_tool_calls: list[dict[str, str]] | None,
) -> tuple[str, list[AttributionIssue]]:
    """Terapkan grounding atribusi; tidak pernah melempar exception.

    Returns:
        ``(reply_final, issues)`` — ``reply_final`` sama dengan input bila
        tidak ada masalah, atau sudah diberi peringatan bila ada.
    """
    if not reply or _ATTRIBUTION_MARKER in reply:
        return reply, []

    try:
        issues = verify_attribution_claims(reply, executed_tool_calls)
    except _GROUND_ERR as exc:
        logger.warning("Grounding atribusi dilewati karena error: %s", exc)
        return reply, []

    if not issues:
        return reply, []

    logger.warning(
        "Klaim atribusi tool tidak terbukti: %s",
        "; ".join(issue.render() for issue in issues),
    )
    names = [
        str(call.get("tool") or "")
        for call in (executed_tool_calls or [])
        if call.get("tool")
    ]
    return (
        reply.rstrip() + "\n" + format_attribution_warning(issues, names),
        issues,
    )


__all__ = [
    "AttributionIssue",
    "apply_attribution_guard",
    "format_attribution_warning",
    "verify_attribution_claims",
]
