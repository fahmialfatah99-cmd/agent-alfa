"""Core autonomous agent turn execution engine (Modular Pipeline Coordinator)."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import sys
from typing import Any

from alfa.bot.config import (
    MEETING_INTENT_KEYWORDS,
    resolve_main_gemini,
)
from alfa.bot.helpers import (
    _artifact_signature,
    _meetings_count,
)
from alfa.bot.pipeline import (
    audit_correction_pass as _audit_correction_pass,
)
from alfa.bot.pipeline import (
    build_memory_block as _build_memory_block,
)
from alfa.bot.pipeline import (
    build_system_instruction as _build_system_instruction,
)
from alfa.bot.pipeline import (
    format_compaction as _format_compaction,
)
from alfa.bot.pipeline import (
    maybe_compact_history as _maybe_compact_history,
)
from alfa.bot.pipeline import (
    openai_compat_turn as _openai_compat_turn,
)
from alfa.bot.pipeline import (
    prepare_tools_and_configs as _prepare_tools_and_configs,
)
from alfa.bot.pipeline import (
    summarize_chunk as _summarize_chunk,
)
from alfa.bot.pipeline import (
    try_alt_provider_keys as _try_alt_provider_keys,
)
from alfa.bot.streamer import TelegramStreamer
from alfa.core import brain as main_brain
from alfa.core import database, token_usage
from alfa.core import permissions as permission_gate
from alfa.tools import (
    current_chat_id_var,
    current_user_id_var,
    current_user_prompt_var,
)

logger = logging.getLogger("TelegramAIAgent")

# Lazily-initialized shared Gemini client (set on first turn via _resolve).
gemini_client: Any = None

_TURN_EXEC_ERR: tuple[type[BaseException], ...] = (
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


def _ensure_genai_errors() -> None:
    global _TURN_EXEC_ERR
    try:
        from google.genai.errors import APIError as _GenAIAPIError

        if _GenAIAPIError not in _TURN_EXEC_ERR:
            _TURN_EXEC_ERR = (*_TURN_EXEC_ERR, _GenAIAPIError)
    except ImportError:
        pass


def _get_bot():
    return sys.modules.get("alfa.bot.telegram_bot")


async def _run_agent_turn_impl(
    user_id: int,
    user_prompt: str,
    multimodal_parts: list | None = None,
    chat_id: int | None = None,
    override_model: str | None = None,
    override_key_id: int | None = None,
    streamer: TelegramStreamer | None = None,
) -> str:
    """Executes an autonomous agent turn with memory context, real tool calling, and multimodal inputs.

    Propagates contextvars for per-user tool isolation.
    Supports MAIN BRAIN lintas-provider: otak mengikuti kunci yang diaktivasi di vault atau pilihan model aktif.
    """
    global gemini_client
    _ensure_genai_errors()

    bot = _get_bot()
    _db = getattr(bot, "database", database) if bot else database
    _mb = getattr(bot, "main_brain", main_brain) if bot else main_brain
    _pg = getattr(bot, "permission_gate", permission_gate) if bot else permission_gate
    _resolve = (
        getattr(bot, "resolve_main_gemini", resolve_main_gemini)
        if bot
        else resolve_main_gemini
    )

    brain = _mb.get_main_brain(
        override_key_id=override_key_id, override_model=override_model
    )
    if brain["provider"] == "gemini":
        gemini_client, gkey_id, gkey_label = _resolve(key_id=override_key_id)
        if not gemini_client:
            return (
                "⚠️ **API key belum tersedia.**\n"
                "Aktivasi kunci (Gemini/OpenRouter/custom) di Dashboard > API Key Vault — "
                "kunci yang terakhir diaktifkan menjadi otak utama agent."
            )
    else:
        try:
            gemini_client, gkey_id, gkey_label = _resolve()
        except _TURN_EXEC_ERR as e:
            logger.warning(f"Gagal menyiapkan klien Gemini fallback: {e}")
            gemini_client, gkey_id, gkey_label = None, None, ""

    # Set context variables for tools
    current_user_id_var.set(user_id)
    current_chat_id_var.set(chat_id or user_id)
    current_user_prompt_var.set(user_prompt or "")

    # Permission Gate (human-in-the-loop) utk tool berbahaya.
    # `make_gate` mengembalikan None saat operator mematikan gate; pada kasus
    # itu kita pakai ALLOW_ALL_GATE (permissive) sehingga brain tidak
    # menolaknya dengan deny-by-default.
    approval_gate = _pg.make_gate(chat_id or user_id) or _pg.ALLOW_ALL_GATE

    # 1. Fetch recent chat history from SQLite
    history_rows = await _db.get_recent_chat_history(user_id, limit=12)

    # 1b. Compaction: ringkas riwayat lama jadi memori rolling (hemat token).
    try:
        _compaction_block = await _maybe_compact_history(_db, user_id, gemini_client=gemini_client)
    except _TURN_EXEC_ERR as _ce:
        logger.debug(f"compaction dilewati: {_ce}")
        _compaction_block = ""

    # 2. Build contents payload
    from google.genai import types

    contents = []

    for row in history_rows:
        role = "user" if row["role"] == "user" else "model"
        contents.append(
            types.Content(role=role, parts=[types.Part.from_text(text=row["content"])])
        )

    # 3. Add current turn with any multimodal attachments
    current_parts = []
    if multimodal_parts:
        current_parts.extend(multimodal_parts)
    if user_prompt:
        current_parts.append(types.Part.from_text(text=user_prompt))

    contents.append(types.Content(role="user", parts=current_parts))

    # 4. Save user turn to database
    display_user_text = user_prompt or "[Lampiran Media]"
    await _db.save_chat_message(user_id, "user", display_user_text)

    # 5. Fetch all long-term memories & knowledge graph for instant recall
    user_memories = await _db.get_all_memories(user_id)
    kg_triples = _db.get_all_knowledge_graph_sync(user_id)

    memory_block = _build_memory_block(
        user_id, user_prompt, user_memories, kg_triples, _compaction_block
    )

    full_system_instruction, preferred_model, current_active_model = (
        await _build_system_instruction(
            _db, user_id, brain, override_model, memory_block
        )
    )

    # 7. Call Gemini with Agent Tools and fast fallback chain
    fallback_chain = [
        m.strip()
        for m in os.getenv(
            "GEMINI_FALLBACK_MODELS",
            "gemini-3.8-flash,gemini-flash-lite-latest,gemini-3.5-flash",
        ).split(",")
        if m.strip()
    ]

    from alfa.core.brain.model_router import route_candidate_models

    brain_model_override = _db.get_main_brain_model() if hasattr(_db, "get_main_brain_model") else None
    models_to_try = route_candidate_models(
        user_prompt=user_prompt or "",
        base_model=current_active_model,
        fallback_chain=fallback_chain,
        override_model=override_model or brain_model_override,
    )

    last_error = None
    meetings_before = _meetings_count()
    art_before = _artifact_signature()
    prompt_low = (user_prompt or "").lower()
    from alfa.tools.rag import is_action_request

    action_intent = is_action_request(user_prompt or "")
    meeting_intent = any(k in prompt_low for k in MEETING_INTENT_KEYWORDS)

    history_msgs = [{"role": r["role"], "content": r["content"]} for r in history_rows]

    if brain["provider"] != "gemini":
        reply_text = await _openai_compat_turn(
            _mb,
            brain,
            preferred_model,
            full_system_instruction,
            user_prompt,
            multimodal_parts,
            history_msgs,
            history_rows,
            approval_gate,
            streamer,
            meeting_intent,
            meetings_before,
            _db,
            user_id,
            display_user_text,
        )
        if reply_text:
            return reply_text

    if gemini_client is None:
        gemini_client, gkey_id, gkey_label = _resolve()
    if gemini_client is None:
        return (
            "⚠️ **Semua otak AI gagal merespons** (OpenRouter/NVIDIA error dan "
            "kunci Gemini tidak tersedia). Coba lagi nanti atau cek Dashboard > API Keys."
        )

    for model_name in models_to_try:
        try:
            gate_on = _pg.gate_is_interactive(approval_gate)
            all_tools, config, config_force, config_wrapup = (
                _prepare_tools_and_configs(
                    model_name,
                    full_system_instruction,
                    user_prompt,
                    history_msgs,
                    action_intent,
                )
            )

            executed_tool_names: list[str] = []
            _turn_contents = list(contents or [])

            async def _drive_tool_loop(
                resp,
                cfg,
                *,
                _model: str = model_name,
                _contents: list = _turn_contents,
                _executed: list = executed_tool_names,
            ):
                """Putar loop tool sampai model berhenti memanggil tool.

                Panggilan PERTAMA memakai config_force (mode ANY) supaya
                permintaan aksi tidak bisa dijawab basa-basi tanpa tool.
                Putaran berikutnya memakai config AUTO sehingga giliran selalu
                ditutup dengan jawaban teks nyata — bukan loop tool tanpa akhir
                yang berujung balasan generik '✅ Permintaan selesai diproses.'.
                """
                nonlocal reply_text
                for _iter in range(_mb.MAX_ITERATIONS):
                    fcs = list(getattr(resp, "function_calls", None) or [])
                    if not fcs:
                        break
                    try:
                        model_content = resp.candidates[0].content
                        if model_content is not None:
                            _contents.append(model_content)
                    except (AttributeError, IndexError, TypeError, ValueError):
                        pass
                    for fc in fcs:
                        _executed.append(fc.name)
                        args_json = json.dumps(
                            dict(fc.args or {}), ensure_ascii=False, default=str
                        )
                        if approval_gate is None:
                            # Deny-by-default: tanpa gate, tool tidak boleh jalan.
                            denial = (
                                f"[DITOLAK] Tool '{fc.name}' tidak dieksekusi karena "
                                "tidak ada permission gate yang tersambung."
                            )
                        else:
                            try:
                                denial = await approval_gate(fc.name, args_json)
                            except Exception as gate_err:  # noqa: BLE001 - fail-closed
                                logger.exception(
                                    "[GatePath] gate error (fail-closed) for %s",
                                    fc.name,
                                )
                                denial = (
                                    f"[DITOLAK] Tool '{fc.name}' tidak dieksekusi "
                                    f"karena permission gate gagal ({gate_err})."
                                )
                        if denial:
                            out = denial
                        else:
                            try:
                                out = await asyncio.wait_for(
                                    asyncio.to_thread(
                                        _mb._execute_tool, fc.name, args_json
                                    ),
                                    timeout=180.0,
                                )
                            except TimeoutError:
                                out = f"[ERROR timeout] Tool '{fc.name}' melebihi batas waktu eksekusi (180 detik)."
                                logger.exception(f"[ToolTimeout] {fc.name} timed out after 180s")
                        logger.info(f"[GatePath] tool {fc.name} -> {str(out)[:80]}")
                        _contents.append(
                            types.Content(
                                role="user",
                                parts=[
                                    types.Part(
                                        function_response=types.FunctionResponse(
                                            name=fc.name,
                                            response={"result": str(out)[:4000]},
                                        )
                                    )
                                ],
                            )
                        )
                    resp = await gemini_client.aio.models.generate_content(
                        model=_model, contents=_contents, config=cfg
                    )
                    token_usage.from_gemini_response(
                        resp,
                        model=_model,
                        key_id=gkey_id,
                        key_label=gkey_label or "gemini-env",
                        context="telegram_chat:gate",
                    )
                    try:
                        turn_text = resp.text or ""
                    except (AttributeError, IndexError, TypeError, ValueError):
                        turn_text = ""
                    if turn_text:
                        reply_text = turn_text
                return resp

            reply_text = ""

            if (
                streamer
                and not gate_on
                and not action_intent
                and hasattr(gemini_client.aio.models, "generate_content_stream")
            ):
                try:
                    response_stream = (
                        await gemini_client.aio.models.generate_content_stream(
                            model=model_name, contents=contents, config=config_force
                        )
                    )
                    streamed_text = ""
                    last_chunk = None
                    async for chunk in response_stream:
                        last_chunk = chunk
                        c_text = getattr(chunk, "text", None)
                        if c_text:
                            streamed_text += c_text
                            await streamer.push_chunk(c_text)
                    if last_chunk:
                        try:
                            token_usage.from_gemini_response(
                                last_chunk,
                                model=model_name,
                                key_id=gkey_id,
                                key_label=gkey_label or "gemini-env",
                                context="telegram_chat:stream",
                            )
                        except (AttributeError, TypeError, ValueError):
                            pass
                    response = last_chunk
                    reply_text = streamed_text

                except Exception as stream_err:
                    logger.warning(
                        f"generate_content_stream error on {model_name}: {stream_err}. Falling back to generate_content."
                    )
                    response = await gemini_client.aio.models.generate_content(
                        model=model_name, contents=contents, config=config_force
                    )
                    token_usage.from_gemini_response(
                        response,
                        model=model_name,
                        key_id=gkey_id,
                        key_label=gkey_label or "gemini-env",
                        context="telegram_chat",
                    )
                    try:
                        reply_text = response.text or ""
                    except (AttributeError, IndexError, TypeError, ValueError):
                        reply_text = ""
            else:
                response = await gemini_client.aio.models.generate_content(
                    model=model_name, contents=contents, config=config_force
                )
                token_usage.from_gemini_response(
                    response,
                    model=model_name,
                    key_id=gkey_id,
                    key_label=gkey_label or "gemini-env",
                    context="telegram_chat",
                )
                try:
                    reply_text = response.text or ""
                except (AttributeError, IndexError, TypeError, ValueError):
                    reply_text = ""

            response = await _drive_tool_loop(response, config)

            if not (reply_text or "").strip():
                # Wrap-up TANPA tools: model wajib merangkum hasil eksekusi nyata.
                logger.warning(
                    f"[WrapUp] jawaban kosong setelah {len(executed_tool_names)} tool "
                    f"-> minta ringkasan teks ({model_name})"
                )
                _turn_contents.append(
                    types.Content(
                        role="user",
                        parts=[
                            types.Part.from_text(
                                text=(
                                    "[SISTEM] Berhenti memanggil tool. Ringkas dalam bahasa "
                                    "Indonesia santai APA YANG SUDAH BENAR-BENAR dieksekusi "
                                    f"(tool: {', '.join(dict.fromkeys(executed_tool_names)) or '-'}), "
                                    "hasil/atau error nyatanya, dan sisa langkah bila belum "
                                    "selesai. DILARANG mengarang hasil."
                                )
                            )
                        ],
                    )
                )
                try:
                    response = await gemini_client.aio.models.generate_content(
                        model=model_name, contents=_turn_contents, config=config_wrapup
                    )
                    token_usage.from_gemini_response(
                        response,
                        model=f"{model_name}:wrapup",
                        key_id=gkey_id,
                        key_label=gkey_label or "gemini-env",
                        context="telegram_chat",
                    )
                    reply_text = (response.text or "").strip()
                except _TURN_EXEC_ERR as wrap_err:
                    logger.warning(f"[WrapUp] gagal: {wrap_err}")
                    reply_text = ""

            if not (reply_text or "").strip():
                ran = ", ".join(dict.fromkeys(executed_tool_names)) or "tidak ada"
                reply_text = (
                    "⚙️ Tool sudah dijalankan: "
                    f"`{ran}`.\nModel tidak mengirim ringkasan teks — "
                    "ulangi perintah dengan lebih spesifik agar hasilnya dirangkum."
                )

            reply_text = await _audit_correction_pass(
                gemini_client,
                model=model_name,
                turn_contents=_turn_contents,
                config=config,
                drive_tool_loop=_drive_tool_loop,
                gkey_id=gkey_id,
                gkey_label=gkey_label,
                prompt_low=prompt_low,
                reply_text=reply_text,
                meeting_intent=meeting_intent,
                action_intent=action_intent,
                meetings_before=meetings_before,
                executed_tool_names=executed_tool_names,
                art_before=art_before,
                approval_gate=approval_gate,
            )

            from alfa.bot.helpers import clean_telegram_markdown as _clean2

            reply_text = _clean2(str(reply_text))
            await _db.save_chat_message(user_id, "model", reply_text)
            return str(reply_text)

        except Exception as e:
            logger.warning(f"Model {model_name} failed: {e}. Trying next candidate...")
            last_error = e
            err_msg = str(e)
            if any(err_k in err_msg for err_k in ("429", "RESOURCE_EXHAUSTED", "503", "UNAVAILABLE")):
                try:
                    from alfa.core.brain.circuit_breaker import (
                        mark_model_exhausted,
                        parse_retry_delay,
                    )

                    delay = parse_retry_delay(e)
                    mark_model_exhausted(model_name, cooldown_seconds=delay, reason=err_msg[:100])
                except (ImportError, ValueError, TypeError, AttributeError, KeyError) as cb_err:
                    logger.debug(f"Circuit breaker mark error: {cb_err}")

    logger.error(
        f"All Gemini candidates failed: {last_error}. Mencoba kunci vault lain..."
    )
    alt_reply = await _try_alt_provider_keys(
        _db,
        _mb,
        full_system_instruction,
        user_prompt,
        history_msgs,
        user_id,
        approval_gate=approval_gate,
    )
    if alt_reply:
        return alt_reply

    logger.error(f"All candidate models failed: {last_error}", exc_info=True)
    err_reply = f"❌ Terjadi kesalahan saat memproses permintaan:\n`{str(last_error)}`"
    try:
        await _db.save_chat_message(user_id, "model", err_reply)
    except (sqlite3.Error, OSError, TypeError, ValueError):
        pass
    return err_reply


# ═════ PUBLIC ENTRY + OBSERVABILITY TURN METRICS ══════════════════════════════
async def run_agent_turn(
    user_id: int,
    user_prompt: str,
    multimodal_parts: list | None = None,
    chat_id: int | None = None,
    override_model: str | None = None,
    override_key_id: int | None = None,
    streamer: TelegramStreamer | None = None,
) -> str:
    """Jalankan satu giliran agent (dokumen lengkap di `_run_agent_turn_impl`).

    Wrapper publik menambahkan telemetri turn (mulai/selesai/gagal) yang
    terekspose via ``/api/metrics`` → ``alfa.core.metrics.snapshot()``.
    """
    from alfa.core.metrics import note_turn_finished, note_turn_started

    note_turn_started()
    try:
        result = await _run_agent_turn_impl(
            user_id,
            user_prompt,
            multimodal_parts=multimodal_parts,
            chat_id=chat_id,
            override_model=override_model,
            override_key_id=override_key_id,
            streamer=streamer,
        )
    except Exception:
        note_turn_finished(False)
        raise
    note_turn_finished(ok=not result.startswith(("❌", "⚠️")))
    return result


__all__ = [
    "_audit_correction_pass",
    "_build_memory_block",
    "_build_system_instruction",
    "_format_compaction",
    "_maybe_compact_history",
    "_openai_compat_turn",
    "_prepare_tools_and_configs",
    "_run_agent_turn_impl",
    "_summarize_chunk",
    "_try_alt_provider_keys",
    "run_agent_turn",
]
