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
    need_artifact_audit = (
        any(n in prompt_low for n in ARTIFACT_NOUNS)
        and art_after == art_before
        and new_meetings == 0
        and any(v in reply_low for v in COMPLETION_VERBS)
        and any(n in reply_low for n in ARTIFACT_NOUNS)
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
