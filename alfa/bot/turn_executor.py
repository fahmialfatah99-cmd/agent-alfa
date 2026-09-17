"""Core autonomous agent turn execution engine."""

import asyncio
import json
import logging
import os
import sys

import plugins
from alfa.bot.config import (
    ALFA_PROMPT_PATH,
    ANTIGRAVITY_WORKFLOW_BLOCK,
    AUDIT_CORRECTION_TEXT,
    BASE_SYSTEM_PROMPT,
    CAPABILITIES_BLOCK,
    CODING_DELIVERY_BLOCK,
    ENFORCEMENT_BLOCK,
    GEMINI_MODEL,
    MEETING_FABRICATION_MARKERS,
    MEETING_INTENT_KEYWORDS,
    OWNER_NAME,
    SUPERPOWERS_SKILLS_BLOCK,
    TOOL_FIRST_EXECUTION_BLOCK,
    UI_UX_PRO_MAX_BLOCK,
    resolve_main_gemini,
)
from alfa.bot.helpers import (
    ARTIFACT_NOUNS,
    COMPLETION_VERBS,
    _artifact_signature,
    _meetings_count,
)
from alfa.bot.streamer import TelegramStreamer
from alfa.core import brain as main_brain
from alfa.core import database, token_usage
from alfa.core import permissions as permission_gate
from alfa.tools import (
    AVAILABLE_TOOLS,
    current_chat_id_var,
    current_user_id_var,
)

logger = logging.getLogger("TelegramAIAgent")


def _get_bot():
    return sys.modules.get("alfa.bot.telegram_bot")


async def run_agent_turn(
    user_id: int,
    user_prompt: str,
    multimodal_parts: list | None = None,
    chat_id: int | None = None,
    override_model: str | None = None,
    override_key_id: int | None = None,
    streamer: TelegramStreamer | None = None,
) -> str:
    """
    Executes an autonomous agent turn with memory context, real tool calling, and multimodal inputs.
    Propagates contextvars for per-user tool isolation.
    Supports MAIN BRAIN lintas-provider: otak mengikuti kunci yang diaktivasi di vault atau pilihan model aktif.
    """
    global gemini_client

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
        except Exception as e:
            logger.warning(f"Gagal menyiapkan klien Gemini fallback: {e}")
            gemini_client, gkey_id, gkey_label = None, None, ""

    # Set context variables for tools
    current_user_id_var.set(user_id)
    current_chat_id_var.set(chat_id or user_id)

    # Permission Gate (human-in-the-loop) utk tool berbahaya
    approval_gate = _pg.make_gate(chat_id or user_id)

    # 1. Fetch recent chat history from SQLite
    history_rows = await _db.get_recent_chat_history(user_id, limit=12)

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

    memory_context_parts = []
    if user_memories:
        memory_context_parts.append("📌 FAKTA & CATATAN PRIBADI TERSIMPAN:")
        for m in user_memories:
            memory_context_parts.append(
                f"- [{m['category']}] {m['key_topic']}: {m['content']}"
            )

    if kg_triples:
        memory_context_parts.append("🕸️ RELASI KNOWLEDGE GRAPH:")
        for k in kg_triples:
            tag_str = f" ({k['tags']})" if k.get("tags") else ""
            memory_context_parts.append(
                f"- {k['entity']} -> [{k['relation']}] -> {k['target_value']}{tag_str}"
            )

    # 5b. AUTO-RAG: ambil potongan dokumen Drive yang relevan dgn pertanyaan (hanya saat relevan)
    p_check = (user_prompt or "").lower().strip()
    should_search_rag = (
        len(p_check) > 15
        and not any(
            p_check == g or p_check.startswith(g + " ")
            for g in [
                "halo",
                "hai",
                "pagi",
                "siang",
                "malam",
                "apa kabar",
                "siapa kamu",
                "tes",
                "ping",
            ]
        )
        and any(
            k in p_check
            for k in [
                "dokumen",
                "drive",
                "file",
                "catatan",
                "ingat",
                "materi",
                "referensi",
                "data",
                "info",
                "tentang",
                "jelaskan",
                "bagaimana",
                "apa itu",
                "siapa",
            ]
        )
    )

    if should_search_rag:
        try:
            from alfa.memory import vector as vector_memory

            brain_hits = vector_memory.semantic_search(
                user_id=user_id, query=user_prompt or "", top_k=4
            )
            relevant = [
                h for h in brain_hits if (h.get("similarity_score") or 0) >= 0.25
            ]
            if relevant:
                memory_context_parts.append(
                    "📄 PENGETAHUAN DARI DOKUMEN DRIVE (Second Brain):"
                )
                for h in relevant:
                    memory_context_parts.append(
                        f"- [{h.get('doc_title','?')}] {str(h.get('chunk_text',''))[:350]}"
                    )
        except Exception as rag_err:
            logger.debug(f"Auto-RAG skipped: {rag_err}")

    memory_block = ""
    if memory_context_parts:
        memory_block = (
            "\n\n======================================================\n"
            "🧠 [INGATAN JANGKA PANJANG & SECOND BRAIN AKTIF]\n"
            f"Berikut adalah seluruh ingatan jangka panjang dan fakta yang tersimpan tentang {OWNER_NAME}. "
            "Pahami dan gunakan fakta ini secara alami dalam percakapan tanpa perlu bertanya ulang:\n"
            + "\n".join(memory_context_parts)
            + "\n======================================================\n"
        )

    # 6. Fetch user settings for prompt override / preferred model
    user_settings = await _db.get_user_settings(user_id)

    # Reload latest prompt from file if available
    active_base_prompt = BASE_SYSTEM_PROMPT
    if os.path.exists(ALFA_PROMPT_PATH):
        try:
            with open(ALFA_PROMPT_PATH, encoding="utf-8") as f:
                active_base_prompt = f.read().strip()
        except Exception:
            pass

    brain_model_override = _db.get_main_brain_model()
    preferred_model = override_model or user_settings.get("model_name") or GEMINI_MODEL
    current_active_model = (
        override_model or brain.get("model") or brain_model_override or preferred_model
    )
    current_active_provider = brain.get("provider", "gemini").upper()
    current_key_label = brain.get("label", "")

    active_identity_block = (
        f"\n\n### 🤖 INFORMASI ENGINE & MODEL AKTIF SAAT INI (GROUND TRUTH)\n"
        f"- MODEL AI AKTIF SAAT INI: `{current_active_model}`\n"
        f"- PROVIDER / GATEWAY: `{current_active_provider}`\n"
        f"- KUNCI/AKUN VAULT: `{current_key_label}`\n"
        f"- Jika pengguna bertanya kamu pakai model apa, model apa yang sedang aktif, atau identitas enginemu, "
        f"jawab dengan jujur dan jelas bahwa saat ini kamu ditenagai oleh model `{current_active_model}` ({current_active_provider})!\n"
    )

    base_instruction = user_settings.get("system_prompt_override") or active_base_prompt
    full_system_instruction = (
        base_instruction
        + active_identity_block
        + memory_block
        + ENFORCEMENT_BLOCK
        + CODING_DELIVERY_BLOCK
        + CAPABILITIES_BLOCK
        + ANTIGRAVITY_WORKFLOW_BLOCK
        + TOOL_FIRST_EXECUTION_BLOCK
        + SUPERPOWERS_SKILLS_BLOCK
        + UI_UX_PRO_MAX_BLOCK
    )

    # 7. Call Gemini with Agent Tools and fast fallback chain
    fallback_chain = [
        m.strip()
        for m in os.getenv(
            "GEMINI_FALLBACK_MODELS",
            "gemini-3.6-flash,gemini-3.7-flash,gemini-flash-latest",
        ).split(",")
        if m.strip()
    ]

    base_model = current_active_model
    candidate_models = (
        [base_model]
        + (
            [preferred_model]
            if preferred_model and preferred_model != base_model
            else []
        )
        + fallback_chain
    )
    models_to_try = list(dict.fromkeys(candidate_models))

    last_error = None
    meetings_before = _meetings_count()
    art_before = _artifact_signature()
    prompt_low = (user_prompt or "").lower()
    meeting_intent = any(k in prompt_low for k in MEETING_INTENT_KEYWORDS)

    history_msgs = [{"role": r["role"], "content": r["content"]} for r in history_rows]

    # ══ OTAK UTAMA LINTAS PROVIDER (OpenRouter/Ox Alpha/Custom/NVIDIA dll) ══
    if brain["provider"] != "gemini":
        compat_text = user_prompt or ""
        if multimodal_parts:
            compat_text = (
                compat_text
                + "\n[Lampiran media tidak didukung provider otak utama saat ini]"
            ).strip()
        reply_text = await _mb.run_openai_agentic_turn(
            provider=brain["provider"],
            base_url=brain["base_url"],
            api_key=brain["api_key"],
            model=brain["model"] or preferred_model,
            system_instruction=full_system_instruction,
            user_text=compat_text,
            history=history_msgs,
            key_id=brain["key_id"],
            key_label=brain["label"],
            approval_gate=approval_gate,
        )
        new_meetings = _meetings_count() - meetings_before
        if meeting_intent and new_meetings == 0 and reply_text:
            low = reply_text.lower()
            if ("rapat" in low or "meeting" in low) and any(
                mk in low for mk in MEETING_FABRICATION_MARKERS
            ):
                logger.warning("[AUDIT-compat] klaim rapat tanpa tool -> pass koreksi")
                corrected = await _mb.run_openai_agentic_turn(
                    provider=brain["provider"],
                    base_url=brain["base_url"],
                    api_key=brain["api_key"],
                    model=brain["model"] or preferred_model,
                    system_instruction=full_system_instruction,
                    user_text=compat_text + "\n\n" + AUDIT_CORRECTION_TEXT,
                    history=history_msgs,
                    key_id=brain["key_id"],
                    key_label=brain["label"],
                    approval_gate=approval_gate,
                )
                if corrected:
                    reply_text = corrected
        if reply_text:
            await _db.save_chat_message(user_id, "model", reply_text)
            try:
                from alfa.memory import reflection as memory_reflection

                refl_history = list(history_rows) + [
                    {"role": "user", "content": display_user_text},
                    {"role": "model", "content": reply_text},
                ]
                memory_reflection.maybe_schedule_reflection(user_id, refl_history)
            except Exception:
                pass
            return reply_text
        logger.warning(
            f"[MainBrain:{brain['provider']}] gagal total -> fallback rantai Gemini"
        )

    if gemini_client is None:
        gemini_client, gkey_id, gkey_label = _resolve()
    if gemini_client is None:
        return (
            "⚠️ **Semua otak AI gagal merespons** (OpenRouter/NVIDIA error dan "
            "kunci Gemini tidak tersedia). Coba lagi nanti atau cek Dashboard > API Keys."
        )

    for model_name in models_to_try:
        try:
            gate_on = approval_gate is not None
            all_tools = list(AVAILABLE_TOOLS)
            try:
                plugin_tools = plugins.load_all_plugin_tools()
                if plugin_tools:
                    all_tools = list(AVAILABLE_TOOLS) + plugin_tools
            except Exception as e:
                logger.warning(f"Failed to load dynamic plugins: {e}")

            seen_fn_names = set()
            deduped_tools = []
            for f in all_tools:
                nm = getattr(f, "__name__", "")
                if nm and nm not in seen_fn_names:
                    seen_fn_names.add(nm)
                    deduped_tools.append(f)
                elif not nm and f not in deduped_tools:
                    deduped_tools.append(f)
            all_tools = deduped_tools

            gemini_tools = all_tools
            try:
                from alfa.tools.rag import select_relevant_functions

                gemini_tools = select_relevant_functions(
                    all_tools, user_prompt or "", history=history_msgs
                )
            except Exception:
                pass
            config = types.GenerateContentConfig(
                system_instruction=full_system_instruction,
                temperature=0.75,
                tools=gemini_tools,
                automatic_function_calling=(
                    types.AutomaticFunctionCallingConfig(disable=True)
                    if gate_on
                    else None
                ),
            )

            if (
                streamer
                and not gate_on
                and hasattr(gemini_client.aio.models, "generate_content_stream")
            ):
                try:
                    response_stream = (
                        await gemini_client.aio.models.generate_content_stream(
                            model=model_name, contents=contents, config=config
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
                        except Exception:
                            pass
                    response = last_chunk
                    reply_text = (
                        streamed_text
                        or (last_chunk.text if last_chunk else "")
                        or "✅ Permintaan selesai diproses."
                    )
                except Exception as stream_err:
                    logger.warning(
                        f"generate_content_stream error on {model_name}: {stream_err}. Falling back to generate_content."
                    )
                    response = await gemini_client.aio.models.generate_content(
                        model=model_name, contents=contents, config=config
                    )
                    token_usage.from_gemini_response(
                        response,
                        model=model_name,
                        key_id=gkey_id,
                        key_label=gkey_label or "gemini-env",
                        context="telegram_chat",
                    )
                    try:
                        reply_text = response.text or "✅ Permintaan selesai diproses."
                    except Exception:
                        reply_text = "✅ Permintaan selesai diproses."
            else:
                response = await gemini_client.aio.models.generate_content(
                    model=model_name, contents=contents, config=config
                )
                token_usage.from_gemini_response(
                    response,
                    model=model_name,
                    key_id=gkey_id,
                    key_label=gkey_label or "gemini-env",
                    context="telegram_chat",
                )

            if gate_on:
                _turn_contents = list(contents or [])
                for _iter in range(_mb.MAX_ITERATIONS):
                    fcs = list(getattr(response, "function_calls", None) or [])
                    if not fcs:
                        break
                    try:
                        model_content = response.candidates[0].content
                        if model_content is not None:
                            _turn_contents.append(model_content)
                    except Exception:
                        pass
                    for fc in fcs:
                        args_json = json.dumps(
                            dict(fc.args or {}), ensure_ascii=False, default=str
                        )
                        denial = await approval_gate(fc.name, args_json)
                        if denial:
                            out = denial
                        else:
                            out = await asyncio.to_thread(
                                _mb._execute_tool, fc.name, args_json
                            )
                        logger.info(f"[GatePath] tool {fc.name} -> {str(out)[:80]}")
                        _turn_contents.append(
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
                    response = await gemini_client.aio.models.generate_content(
                        model=model_name, contents=_turn_contents, config=config
                    )
                    token_usage.from_gemini_response(
                        response,
                        model=model_name,
                        key_id=gkey_id,
                        key_label=gkey_label or "gemini-env",
                        context="telegram_chat:gate",
                    )

            if "reply_text" not in locals() or not reply_text:
                try:
                    reply_text = response.text or "✅ Permintaan selesai diproses."
                except Exception:
                    reply_text = "✅ Permintaan selesai diproses."

            new_meetings = _meetings_count() - meetings_before
            reply_low = reply_text.lower()

            need_meeting_audit = (
                meeting_intent
                and new_meetings == 0
                and ("rapat" in reply_low or "meeting" in reply_low)
                and any(mk in reply_low for mk in MEETING_FABRICATION_MARKERS)
            )
            need_artifact_audit = (
                any(n in prompt_low for n in ARTIFACT_NOUNS)
                and _artifact_signature() == art_before
                and new_meetings == 0
                and any(v in reply_low for v in COMPLETION_VERBS)
                and any(n in reply_low for n in ARTIFACT_NOUNS)
            )

            if need_meeting_audit or need_artifact_audit:
                audit_kind = (
                    "RAPAT FIKTIF" if need_meeting_audit else "ARTEFAK BELUM DIBUAT"
                )
                logger.warning(
                    f"[AUDIT] {audit_kind} terdeteksi -> pass koreksi ({model_name})"
                )
                audit_parts = ["⛔ SISTEM AUDIT KEBENARAN:"]
                if need_meeting_audit:
                    audit_parts.append(
                        "TIDAK ADA rapat nyata dijalankan (tool conduct_ai_meeting tidak dipanggil)."
                    )
                if need_artifact_audit:
                    audit_parts.append(
                        "TIDAK ADA berkas baru tercipta di sistem, padahal jawabanmu mengklaim selesai."
                    )
                audit_parts.append(
                    "Perbaiki SEKARANG: panggil tool pembuatnya secara nyata "
                    "(conduct_ai_meeting / execute_python_sandbox / generate_pdf_report / "
                    "generate_excel_spreadsheet / universal_deep_scraper) ATAU jawab jujur "
                    "bahwa belum dieksekusi. Dilarang klaim palsu."
                )
                contents.append(
                    types.Content(
                        role="user",
                        parts=[types.Part.from_text(text="\n".join(audit_parts))],
                    )
                )
                response2 = await gemini_client.aio.models.generate_content(
                    model=model_name, contents=contents, config=config
                )
                token_usage.from_gemini_response(
                    response2,
                    model=f"{model_name}:audit",
                    key_id=gkey_id,
                    key_label=gkey_label or "gemini-env",
                    context="telegram_chat",
                )
                if response2.text and response2.text.strip():
                    reply_text = response2.text
                logger.warning(
                    f"[AUDIT] Koreksi selesai ({audit_kind}); "
                    f"rapat baru: {_meetings_count() - meetings_before}; "
                    f"artefak berubah: {_artifact_signature() != art_before}"
                )

            await _db.save_chat_message(user_id, "model", reply_text)
            return reply_text

        except Exception as e:
            logger.warning(f"Model {model_name} failed: {e}. Trying next candidate...")
            last_error = e

    logger.error(
        f"All Gemini candidates failed: {last_error}. Mencoba kunci vault lain..."
    )
    try:
        alt_keys = _db.list_active_keys_sync(exclude_provider="gemini")
    except Exception:
        alt_keys = []
    for key in alt_keys:
        prov = (key.get("provider") or "").lower()
        if not (key.get("api_key") or "").strip():
            continue
        try:
            logger.info(
                f"[Fallback] mencoba {prov} ({key.get('name')}) model "
                f"{key.get('default_model')}"
            )
            reply_text = await _mb.run_openai_agentic_turn(
                provider=prov,
                base_url=key.get("base_url") or "",
                api_key=key["api_key"].strip(),
                model=key.get("default_model") or "",
                system_instruction=full_system_instruction,
                user_text=user_prompt,
                history=history_msgs,
                key_id=key.get("id"),
                key_label=key.get("name", f"{prov}-fallback"),
                context="telegram_chat:fallback",
            )
            if reply_text:
                logger.info(f"[Fallback] sukses via {prov}/{key.get('default_model')}")
                await _db.save_chat_message(user_id, "model", reply_text)
                return reply_text
        except Exception as fe:
            logger.warning(f"[Fallback] {prov} gagal juga: {fe}")

    logger.error(f"All candidate models failed: {last_error}", exc_info=True)
    return f"❌ Terjadi kesalahan saat memproses permintaan:\n`{str(last_error)}`"
