"""Verifikasi klaim artefak pada balasan agen.

Model bahasa sering mengklaim "file sudah diperbarui" padahal penulisan
belum tersimpan (atau gagal). Modul ini memeriksa klaim tersebut secara
deterministik *sebelum* balasan dikirim ke pengguna:

- file yang disebut harus ada,
- ``mtime`` file harus berada di dalam jendela giliran,
- bila balasan mengklaim sheet Excel baru, sheet itu harus benar-benar ada.

Guard ini tidak mengubah isi balasan selain menambahkan peringatan yang
jelas ketika klaim tidak terbukti. Semua kegagalan verifikasi ditelan
dengan log — verifikasi tidak boleh mematikan giliran.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("TelegramAIAgent")

# Toleransi clock skew antara mtime filesystem dan waktu mulai giliran.
_MTIME_TOLERANCE_SEC = 5.0

# Ekstensi artefak yang lazim diklaim agen.
_ARTIFACT_SUFFIXES = (
    "xlsx",
    "xlsm",
    "xls",
    "csv",
    "pdf",
    "docx",
    "pptx",
    "json",
    "txt",
    "md",
    "png",
    "jpg",
    "jpeg",
)

_PATH_RE = re.compile(
    r"(?<![\w/])("
    r"(?:~|/home/[A-Za-z0-9._-]+|/tmp|/var/tmp|/mnt|/media)"
    r"/[^\s`'\"<>|]+?"
    r"\.(?:" + "|".join(_ARTIFACT_SUFFIXES) + r")"
    r")",
    re.IGNORECASE,
)

# Kata kerja yang menandakan klaim *mutasi* file, bukan sekadar pembacaan.
_MUTATION_RE = re.compile(
    r"(perbaru|memperbarui|diperbarui|ditambahkan|menambahkan|tambahkan|"
    r"disimpan|tersimpan|menyimpan|dibuat|membuat|ditulis|menulis|"
    r"diubah|mengubah|update|meng-?update|beres)",
    re.IGNORECASE,
)

# Nama sheet yang diklaim, biasanya ditulis dalam backtick/quote.
_SHEET_RE = re.compile(
    r"(?:sheet\s+baru|sheet)\s*[:\-]?\s*[`\"']([^`\"'\n]{2,60})[`\"']",
    re.IGNORECASE,
)

_XLSX_SUFFIXES = {".xlsx", ".xlsm"}


@dataclass(frozen=True)
class ArtifactIssue:
    """Satu klaim artefak yang tidak terbukti."""

    path: str
    reason: str

    def render(self) -> str:
        return f"`{self.path}` — {self.reason}"


def _mutation_window_has_claim(reply: str, start: int, end: int) -> bool:
    """Apakah ada kata kerja mutasi di sekitar kemunculan path?"""
    left = max(0, start - 300)
    right = min(len(reply), end + 300)
    return bool(_MUTATION_RE.search(reply[left:right]))


def _claimed_sheets(reply: str) -> list[str]:
    """Ambil nama sheet yang diklaim di balasan (deduplikasi, urutan tetap)."""
    names: list[str] = []
    for match in _SHEET_RE.finditer(reply):
        name = match.group(1).strip()
        if name and name not in names:
            names.append(name)
    return names


def _verify_excel_sheets(path: Path, claimed: list[str]) -> list[ArtifactIssue]:
    """Pastikan sheet yang diklaim benar-benar ada di workbook."""
    if not claimed:
        return []
    try:
        from openpyxl import load_workbook

        wb = load_workbook(path, read_only=True)
    except Exception as exc:  # noqa: BLE001 - file korup/format asing bukan crash
        logger.warning("Verifikasi Excel gagal membuka %s: %s", path, exc)
        return [ArtifactIssue(str(path), "file Excel tidak bisa dibuka untuk verifikasi")]
    try:
        existing = set(wb.sheetnames)
    finally:
        wb.close()
    missing = [name for name in claimed if name not in existing]
    if not missing:
        return []
    detail = ", ".join(repr(name) for name in missing)
    return [
        ArtifactIssue(
            str(path),
            f"sheet {detail} tidak ditemukan setelah giliran ini",
        )
    ]


def verify_artifact_claims(
    reply: str,
    turn_started_at: float,
) -> list[ArtifactIssue]:
    """Kembalikan daftar klaim artefak yang tidak terbukti pada ``reply``.

    Hanya path yang berada dekat kata kerja mutasi yang diperiksa, sehingga
    penyebutan file sebagai *input* (mis. "saya baca file X") tidak memicu
    peringatan palsu.
    """
    if not reply or not turn_started_at:
        return []

    issues: list[ArtifactIssue] = []
    seen_paths: set[str] = set()

    for match in _PATH_RE.finditer(reply):
        raw_path = match.group(1).rstrip(".,;:)]}")
        if raw_path in seen_paths:
            continue
        seen_paths.add(raw_path)

        if not _mutation_window_has_claim(reply, match.start(), match.end()):
            continue

        path = Path(raw_path).expanduser()
        if not path.exists():
            issues.append(ArtifactIssue(raw_path, "file tidak ditemukan"))
            continue
        if not path.is_file():
            issues.append(ArtifactIssue(raw_path, "path bukan file"))
            continue

        try:
            mtime = path.stat().st_mtime
        except OSError as exc:
            issues.append(ArtifactIssue(raw_path, f"metadata file tidak terbaca ({exc})"))
            continue

        if mtime < (turn_started_at - _MTIME_TOLERANCE_SEC):
            issues.append(
                ArtifactIssue(
                    raw_path,
                    "file tidak berubah selama giliran ini (perubahan mungkin belum tersimpan)",
                )
            )
            continue

        if path.suffix.lower() in _XLSX_SUFFIXES:
            window = reply[max(0, match.start() - 800) : match.end() + 800]
            issues.extend(_verify_excel_sheets(path, _claimed_sheets(window)))

    return issues


def format_verification_warning(issues: list[ArtifactIssue]) -> str:
    """Format peringatan yang ditempelkan ke balasan pengguna."""
    lines = [
        "",
        "⚠️ *Verifikasi otomatis:* klaim perubahan file belum terbukti.",
    ]
    for issue in issues[:3]:
        lines.append(f"• {issue.render()}")
    if len(issues) > 3:
        lines.append(f"• …dan {len(issues) - 3} klaim lain.")
    lines.append(
        "Mohon cek ulang file tersebut sebelum menganggap perubahannya tersimpan."
    )
    return "\n".join(lines)


def apply_artifact_guard(
    reply: str,
    turn_started_at: float,
) -> tuple[str, list[ArtifactIssue]]:
    """Terapkan guard ke balasan; tidak pernah melempar exception.

    Returns:
        ``(reply_final, issues)`` — ``reply_final`` sama dengan input bila
        tidak ada masalah, atau sudah diberi peringatan bila ada.
    """
    if "Verifikasi otomatis" in reply:
        # Sudah pernah diverifikasi (mis. guard dipanggil di dua lapisan).
        return reply, []

    try:
        issues = verify_artifact_claims(reply, turn_started_at)
    except Exception as exc:  # noqa: BLE001 - guard tidak boleh mematikan turn
        logger.warning("Verifikasi artefak dilewati karena error: %s", exc)
        return reply, []

    if not issues:
        return reply, []

    logger.warning(
        "Klaim artefak tidak terbukti: %s",
        "; ".join(issue.render() for issue in issues),
    )
    return reply.rstrip() + "\n" + format_verification_warning(issues), issues


__all__ = [
    "ArtifactIssue",
    "apply_artifact_guard",
    "format_verification_warning",
    "verify_artifact_claims",
]
