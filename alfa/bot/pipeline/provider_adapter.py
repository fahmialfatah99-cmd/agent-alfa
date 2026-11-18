"""Pipeline Stage 4: Cross-Provider Execution (OpenAI-compatible & Vault Key Fallbacks)."""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

from alfa.bot.config import (
    AUDIT_CORRECTION_TEXT,
    MEETING_FABRICATION_MARKERS,
)
from alfa.bot.helpers import _meetings_count
from alfa.core.perm.gate import gate_is_interactive

logger = logging.getLogger("ProviderAdapter")


def _is_anthropic(provider: str | None) -> bool:
    """True untuk provider yang memakai Messages API native (bukan OpenAI)."""
    return (provider or "").strip().lower() in {"anthropic", "claude"}


async def _anthropic_turn(
    brain: dict,
    preferred_model: str,
    system_instruction: str,
    user_text: str,
    history_msgs: list,
    approval_gate: Any,
    streamer: Any,
    *,
    timeout: float = 180.0,
) -> str:
    """Jalankan giliran native Anthropic; return "" bila gagal total."""
    from alfa.core.brain import anthropic_native

    kwargs: dict[str, Any] = {
        "api_key": brain.get("api_key") or "",
        "model": brain.get("model") or preferred_model,
        "system_instruction": system_instruction,
        "user_text": user_text,
        "history": history_msgs,
        "base_url": brain.get("base_url") or "",
        "key_id": brain.get("key_id"),
        "key_label": brain.get("label") or "anthropic",
        "context": "telegram_chat:anthropic",
        "approval_gate": approval_gate,
        "timeout": timeout,
    }
    if streamer and not gate_is_interactive(approval_gate):
        chunks: list[str] = []
        try:
            async for chunk in anthropic_native.run_anthropic_agentic_turn_streaming(
                **kwargs
            ):
                chunks.append(chunk)
                await streamer.push_chunk(chunk)
            text = "".join(chunks)
            if text.strip():
                return text
            logger.info("[Anthropic] streaming kosong -> fallback non-stream")
        except _PROVIDER_ERR as exc:
            logger.warning("[Anthropic] streaming gagal, fallback non-stream: %s", exc)
    return (
        await anthropic_native.run_anthropic_agentic_turn(**kwargs)
    ) or ""

_PROVIDER_ERR: tuple[type[BaseException], ...] = (
    OSError,
    ValueError,
    RuntimeError,
    TypeError,
    KeyError,
    AttributeError,
    ImportError,
    TimeoutError,
    ConnectionError,
    sqlite3.Error,
)


async def openai_compat_turn(
    mb: Any,
    brain: dict,
    preferred_model: str,
    system_instruction: str,
    user_prompt: str,
    multimodal_parts: list | None,
    history_msgs: list,
    history_rows: list,
    approval_gate: Any,
    streamer: Any,
    meeting_intent: bool,
    meetings_before: int,
    db: Any,
    user_id: int,
    display_user_text: str,
) -> str:
    """Giliran lewat provider OpenAI-compatible; return "" bila gagal total."""
    compat_text = user_prompt or ""
    if multimodal_parts:
        compat_text = (
            compat_text
            + "\n[Lampiran media tidak didukung provider otak utama saat ini]"
        ).strip()

    # `gate_on` = ada kanal persetujuan manusia interaktif. Gate permisif
    # (ALLOW_ALL_GATE / None) tidak menambah satu langkah dialog.
    gate_on = gate_is_interactive(approval_gate)

    async def _invoke(text: str) -> str:
        """Pilih jalur native Anthropic atau OpenAI-compatible."""
        if _is_anthropic(brain.get("provider")):
            return await _anthropic_turn(
                brain,
                preferred_model,
                system_instruction,
                text,
                history_msgs,
                approval_gate,
                streamer,
            )
        if (
            streamer
            and not gate_on
            and hasattr(mb, "run_openai_agentic_turn_streaming")
        ):
            try:
                streamed_text = ""
                async for chunk in mb.run_openai_agentic_turn_streaming(
                    provider=brain["provider"],
                    base_url=brain["base_url"],
                    api_key=brain["api_key"],
                    model=brain["model"] or preferred_model,
                    system_instruction=system_instruction,
                    user_text=text,
                    history=history_msgs,
                    key_id=brain["key_id"],
                    key_label=brain["label"],
                    approval_gate=approval_gate,
                ):
                    streamed_text += chunk
                    await streamer.push_chunk(chunk)
                if str(streamed_text).strip():
                    return streamed_text
                logger.info("[ProviderAdapter] streaming kosong -> non-stream")
            except _PROVIDER_ERR as e:
                logger.warning(f"Streaming failed for OpenAI compatible, fallback: {e}")
        result = await mb.run_openai_agentic_turn(
            provider=brain["provider"],
            base_url=brain["base_url"],
            api_key=brain["api_key"],
            model=brain["model"] or preferred_model,
            system_instruction=system_instruction,
            user_text=text,
            history=history_msgs,
            key_id=brain["key_id"],
            key_label=brain["label"],
            approval_gate=approval_gate,
        )
        return str(result or "")

    reply_text = await _invoke(compat_text)

    new_meetings = _meetings_count() - meetings_before
    if meeting_intent and new_meetings == 0 and reply_text:
        low = reply_text.lower()
        if ("rapat" in low or "meeting" in low) and any(
            mk in low for mk in MEETING_FABRICATION_MARKERS
        ):
            logger.warning("[AUDIT-compat] klaim rapat tanpa tool -> pass koreksi")
            corrected = await _invoke(
                compat_text + "\n\n" + AUDIT_CORRECTION_TEXT
            )
            if corrected:
                reply_text = corrected
    if reply_text:
        from alfa.bot.helpers import clean_telegram_markdown as _clean

        reply_text = _clean(str(reply_text))
        await db.save_chat_message(user_id, "model", reply_text)
        try:
            from alfa.memory import reflection as memory_reflection

            refl_history = list(history_rows) + [
                {"role": "user", "content": display_user_text},
                {"role": "model", "content": reply_text},
            ]
            memory_reflection.maybe_schedule_reflection(user_id, refl_history)
        except (ImportError, RuntimeError, AttributeError, TypeError) as refl_err:
            logger.debug(f"reflection scheduling(error): {refl_err}")
        return str(reply_text)
    logger.warning(
        f"[MainBrain:{brain['provider']}] gagal total -> fallback rantai Gemini"
    )
    return ""


async def try_alt_provider_keys(
    db: Any,
    mb: Any,
    system_instruction: str,
    user_prompt: str,
    history_msgs: list,
    user_id: int,
    approval_gate: Any = None,
) -> str | None:
    """Coba kunci aktif non-Gemini di vault; return teks bila satu berhasil.

    ``approval_gate`` WAJIB diteruskan. Tanpa gate, jalur fallback ini
    menjalankan tool apa pun tanpa human-in-the-loop — jalur yang sama dengan
    percobaan utama, jadi wajib punya gate yang sama.
    """
    if approval_gate is None:
        logger.error(
            "[Fallback] ditolak: approval_gate tidak diteruskan "
            "(deny-by-default) — jalur fallback tidak boleh berjalan tanpa gate."
        )
        return None
    try:
        alt_keys = db.list_active_keys_sync(exclude_provider="gemini")
    except (sqlite3.Error, TypeError, ValueError, AttributeError):
        alt_keys = []
    for key in alt_keys:
        prov = (key.get("provider") or "").lower()
        if not (key.get("api_key") or "").strip():
            continue
        if not (key.get("base_url") or "").strip():
            logger.warning(
                f"[Fallback] lewati {prov} ({key.get('name')}): base_url kosong."
            )
            continue
        try:
            logger.info(
                f"[Fallback] mencoba {prov} ({key.get('name')}) model "
                f"{key.get('default_model')}"
            )
            if _is_anthropic(prov):
                from alfa.core.brain import anthropic_native

                reply_text = await anthropic_native.run_anthropic_agentic_turn(
                    api_key=key["api_key"].strip(),
                    model=key.get("default_model") or "",
                    system_instruction=system_instruction,
                    user_text=user_prompt,
                    history=history_msgs,
                    base_url=key.get("base_url") or "",
                    timeout=60.0,
                    key_id=key.get("id"),
                    key_label=key.get("name", f"{prov}-fallback"),
                    context="telegram_chat:fallback",
                    approval_gate=approval_gate,
                )
            else:
                reply_text = await mb.run_openai_agentic_turn(
                    provider=prov,
                    base_url=key.get("base_url") or "",
                    api_key=key["api_key"].strip(),
                    model=key.get("default_model") or "",
                    system_instruction=system_instruction,
                    user_text=user_prompt,
                    history=history_msgs,
                    timeout=60.0,
                    key_id=key.get("id"),
                    key_label=key.get("name", f"{prov}-fallback"),
                    context="telegram_chat:fallback",
                    approval_gate=approval_gate,
                )
            if reply_text:
                logger.info(
                    f"[Fallback] sukses via {prov}/{key.get('default_model')}"
                )
                from alfa.bot.helpers import clean_telegram_markdown as _clean3

                reply_text = _clean3(str(reply_text))
                await db.save_chat_message(user_id, "model", reply_text)
                return str(reply_text)
        except _PROVIDER_ERR as fe:
            logger.warning(f"[Fallback] {prov} gagal juga: {fe}")
    return None
