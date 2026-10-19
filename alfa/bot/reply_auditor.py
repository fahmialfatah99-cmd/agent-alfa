"""Pure reply-audit predicates for the Telegram agent turn.

Detects fabricated claims (fake meetings, uncreated artifacts, unexecuted
actions) from the model reply. Fully deterministic — no LLM calls — so it
is cheaply unit-testable.
"""

from __future__ import annotations

from typing import Any

from alfa.bot.config import MEETING_FABRICATION_MARKERS
from alfa.bot.helpers import ARTIFACT_NOUNS, COMPLETION_VERBS

ACTION_CLAIM_MARKERS = (
    "sudah",
    "berhasil",
    "selesai",
    "diputar",
    "memutar",
    "playing",
    "dibuka",
    "membuka",
    "terbuka",
    "sudah kubuka",
    "sudah ku",
)

ACTION_TOOLS = {
    "browser_open_url",
    "desktop_launch_app",
    "control_linux_hardware",
    "execute_bash_command",
    "web_search",
    "open_url_in_system_browser",
    "play_youtube_music",
    "execute_python_sandbox",
    "browser_use_autonomous_task",
    "vision_click_target",
    "desktop_click_coordinate",
    "desktop_type_keys",
}

FIX_INSTRUCTION = (
    "Perbaiki SEKARANG: panggil tool yang sesuai secara nyata "
    "(play_youtube_music / open_url_in_system_browser / desktop_launch_app / "
    "browser_open_url / execute_bash_command / conduct_ai_meeting / "
    "execute_python_sandbox / generate_pdf_report / generate_excel_spreadsheet) "
    "ATAU jawab jujur bahwa belum dieksekusi. Dilarang klaim palsu."
)


TEXT_SUMMARY_MARKERS = (
    "ringkas",
    "ringkasan",
    "rangkum",
    "rangkuman",
    "kesimpulan",
    "analisis",
    "analisa",
    "penjelasan",
    "ulasan",
    "rekapitulasi",
    "rekap",
    "poin",
    "baca",
    "lihat",
    "cek",
    "pahami",
    "jelaskan",
    "isi file",
    "apa isi",
)

EXPLICIT_FILE_CREATION_MARKERS = (
    "buat file",
    "buatkan file",
    "bikin file",
    "bikinkan file",
    "generate file",
    "buat berkas",
    "buatkan berkas",
    "bikin berkas",
    "buat pdf",
    "buatkan pdf",
    "bikin pdf",
    "generate pdf",
    "export pdf",
    "jadikan pdf",
    "ekspor pdf",
    "buat excel",
    "buatkan excel",
    "bikin excel",
    "generate excel",
    "export excel",
    "jadikan excel",
    "ekspor excel",
    "buat csv",
    "buatkan csv",
    "bikin csv",
    "generate csv",
    "export csv",
    "jadikan csv",
    "buat docx",
    "buatkan docx",
    "buat word",
    "buatkan word",
    "export word",
    "buat pptx",
    "buatkan pptx",
    "buat presentasi",
    "buat laporan pdf",
    "buatkan laporan pdf",
    "buat laporan excel",
    "buatkan laporan excel",
    "export ke",
    "ekspor ke",
    "simpan ke file",
    "simpan sebagai file",
    "save to file",
    "save as",
)

ARTIFACT_CREATION_MARKERS = (
    "buat",
    "buatkan",
    "bikin",
    "bikinkan",
    "generate",
    "ciptakan",
    "export",
    "ekspor",
    "jadikan",
    "render",
    "create",
)


def _extract_user_instruction(prompt_low: str) -> str:
    """Isolate actual user instruction from prompt, discarding system scaffolding."""
    import re as _re

    p = prompt_low.lower()
    if "instruksi pengguna:" in p:
        part = p.split("instruksi pengguna:", 1)[1]
        part = _re.split(r"\[panduan\b|\[file tersimpan\b|\n\n\[", part)[0]
        return part.strip()
    cleaned_lines = []
    for line in p.splitlines():
        line_str = line.strip()
        if line_str.startswith("[") and line_str.endswith("]"):
            continue
        if line_str.startswith("*(") and line_str.endswith(")*"):
            continue
        if line_str.startswith("|") and line_str.endswith("|"):
            continue
        cleaned_lines.append(line)
    return "\n".join(cleaned_lines).strip()


def evaluate_reply_audits(
    *,
    prompt_low: str,
    reply_low: str,
    meeting_intent: bool,
    action_intent: bool,
    new_meetings: int,
    executed_tool_names: list[str],
    art_before: Any,
    art_after: Any,
) -> tuple[str | None, list[str]]:
    """Evaluate reply for fabricated claims.

    Returns (audit_kind, audit_parts) where audit_kind is None when clean.
    audit_parts is the full correction message (header + findings + fix).
    """
    need_meeting_audit = (
        meeting_intent
        and new_meetings == 0
        and ("rapat" in reply_low or "meeting" in reply_low)
        and any(mk in reply_low for mk in MEETING_FABRICATION_MARKERS)
    )

    user_inst = _extract_user_instruction(prompt_low)
    has_explicit_file_creation = any(
        ef in user_inst for ef in EXPLICIT_FILE_CREATION_MARKERS
    )
    is_text_request = any(ts in user_inst for ts in TEXT_SUMMARY_MARKERS)

    if has_explicit_file_creation:
        has_creation_intent = True
    elif is_text_request:
        has_creation_intent = False
    else:
        has_creation_intent = any(
            v in user_inst for v in ARTIFACT_CREATION_MARKERS
        ) and any(n in user_inst for n in ARTIFACT_NOUNS)

    # Claim in reply must match completion verb AND artifact noun
    claims_file_done = any(v in reply_low for v in COMPLETION_VERBS) and any(
        n in reply_low for n in ARTIFACT_NOUNS
    )

    need_artifact_audit = (
        has_creation_intent
        and art_after == art_before
        and new_meetings == 0
        and claims_file_done
    )
    need_action_audit = (
        action_intent
        and not ACTION_TOOLS.intersection(executed_tool_names)
        and any(marker in reply_low for marker in ACTION_CLAIM_MARKERS)
    )

    if not (need_meeting_audit or need_artifact_audit or need_action_audit):
        return None, []

    audit_kind = (
        "RAPAT FIKTIF"
        if need_meeting_audit
        else "ARTEFAK BELUM DIBUAT"
        if need_artifact_audit
        else "AKSI BELUM DIJALANKAN"
    )
    parts = ["⛔ SISTEM AUDIT KEBENARAN:"]
    if need_meeting_audit:
        parts.append(
            "TIDAK ADA rapat nyata dijalankan (tool conduct_ai_meeting tidak dipanggil)."
        )
    if need_artifact_audit:
        parts.append(
            "TIDAK ADA berkas baru tercipta di sistem, padahal jawabanmu mengklaim selesai."
        )
    if need_action_audit:
        parts.append(
            "TIDAK ADA tool aksi nyata yang dipanggil untuk membuka/memutar/menjalankan perintah."
        )
    parts.append(FIX_INSTRUCTION)
    return audit_kind, parts
