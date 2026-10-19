"""Pipeline Stage 3: Anti-Hallucination and Verification Pass."""

from __future__ import annotations

import logging
from typing import Any

from alfa.bot.helpers import _artifact_signature, _meetings_count
from alfa.bot.reply_auditor import evaluate_reply_audits
from alfa.core import token_usage

logger = logging.getLogger("AuditPipeline")

_AUDIT_ERR: tuple[type[BaseException], ...] = (
    OSError,
    ValueError,
    RuntimeError,
    TypeError,
    KeyError,
    AttributeError,
    ImportError,
    TimeoutError,
    ConnectionError,
)


async def audit_correction_pass(
    gemini_client: Any,
    model: str,
    turn_contents: list,
    config: Any,
    drive_tool_loop: Any,
    gkey_id: Any,
    gkey_label: str,
    prompt_low: str,
    reply_text: str,
    meeting_intent: bool,
    action_intent: bool,
    meetings_before: int,
    executed_tool_names: list,
    art_before: Any,
    approval_gate: Any,
) -> str:
    """Audit klaim bogus (rapat/berkas dsb.) + pass koreksi bila terdeteksi."""
    from google.genai import types

    new_meetings = _meetings_count() - meetings_before
    reply_low = reply_text.lower()

    audit_kind, audit_parts = evaluate_reply_audits(
        prompt_low=prompt_low,
        reply_low=reply_low,
        meeting_intent=meeting_intent,
        action_intent=action_intent,
        new_meetings=new_meetings,
        executed_tool_names=executed_tool_names,
        art_before=art_before,
        art_after=_artifact_signature(),
    )

    if audit_kind:
        logger.warning(
            f"[AUDIT] {audit_kind} terdeteksi -> pass koreksi ({model})"
        )
        # Pakai konteks GILIRAN INI (termasuk riwayat tool) — bukan `contents`
        # yang tidak memuat hasil tool, agar model tahu apa yang sudah/belum jalan.
        turn_contents.append(
            types.Content(
                role="user",
                parts=[types.Part.from_text(text="\n".join(audit_parts))],
            )
        )
        try:
            response2 = await gemini_client.aio.models.generate_content(
                model=model, contents=turn_contents, config=config
            )
            token_usage.from_gemini_response(
                response2,
                model=f"{model}:audit",
                key_id=gkey_id,
                key_label=gkey_label or "gemini-env",
                context="telegram_chat",
            )
            # Izinkan model MENGAMBIL AKSI pada pass koreksi — kalau dia
            # tetap memanggil tool, jalankan sampai selesai.
            response2 = await drive_tool_loop(response2, config)
            if response2.text and response2.text.strip():
                reply_text = response2.text
        except _AUDIT_ERR as audit_err:
            logger.warning(f"[AUDIT] pass koreksi gagal: {audit_err}")
        logger.warning(
            f"[AUDIT] Koreksi selesai ({audit_kind}); "
            f"rapat baru: {_meetings_count() - meetings_before}; "
            f"artefak berubah: {_artifact_signature() != art_before}"
        )
    return reply_text
