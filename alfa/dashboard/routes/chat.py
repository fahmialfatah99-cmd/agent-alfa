"""Chat and conversation routes, SSE streaming, model selection, and code execution for ALFA Dashboard."""

import asyncio
import base64
import json
import os
import re
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import StreamingResponse

from alfa.core import database
from alfa import tools
from alfa.dashboard.common import _get_bot, get_primary_user_id, logger

chat_router = APIRouter(tags=["chat"])


@chat_router.post("/api/chat")
async def chat_with_agent(payload: Dict[str, Any]):
    """Send a message directly to the ALFA Agent with optional multimodal attachments and sub-second Fast-Path tool execution."""
    import fast_path_executor as fpe
    import universal_file_extractor as ufe

    message = (payload.get("message") or "").strip()
    attachments = payload.get("attachments") or []

    if not message and not attachments:
        raise HTTPException(status_code=400, detail="message or attachments is required")

    uid = get_primary_user_id()

    multimodal_parts = []
    text_contexts = []
    saved_disk_paths = []

    for att in attachments:
        fname = att.get("name", "attachment")
        mime = att.get("type", "application/octet-stream")
        b64_data = att.get("base64", "")
        if not b64_data:
            continue
        if "," in b64_data:
            b64_data = b64_data.split(",", 1)[1]
        try:
            raw_bytes = base64.b64decode(b64_data)
        except Exception:
            continue

        txt_ctx, part = ufe.process_uploaded_attachment(fname, mime, raw_bytes, save_disk=True)
        if part is not None:
            multimodal_parts.append(part)
        if txt_ctx:
            text_contexts.append(txt_ctx)
            m = re.search(r'\[FILE TERSIMPAN DI DISK:\s*(.+?)\]', txt_ctx)
            if m:
                saved_disk_paths.append(m.group(1).strip())

    # 1. Check Sub-second Fast-Path Engine first (0.05s response)
    fast_result = fpe.try_execute_fast_path(user_prompt=message, saved_file_paths=saved_disk_paths)
    if fast_result is not None:
        return {
            "status": "success",
            "reply": fast_result.get("reply"),
            "tool_used": fast_result.get("tool_name"),
            "execution_time_ms": fast_result.get("execution_time_ms"),
            "timestamp": datetime.now().isoformat()
        }

    # 2. Extract active model override from payload
    selected_model = payload.get("selected_model")
    selected_key_id = payload.get("key_id")
    if selected_key_id:
        try:
            selected_key_id = int(selected_key_id)
        except Exception:
            selected_key_id = None

    # 3. Autonomous Multi-step LLM Turn
    full_prompt = message
    if text_contexts:
        full_prompt = "\n\n".join(text_contexts) + ("\n\n" + message if message else "\n\nAnalisis isi dokumen terlampir di atas secara mendalam.")

    reply = await _get_bot().run_agent_turn(
        user_id=uid,
        user_prompt=full_prompt,
        multimodal_parts=multimodal_parts if multimodal_parts else None,
        chat_id=uid,
        override_model=selected_model,
        override_key_id=selected_key_id
    )
    return {
        "status": "success",
        "reply": reply,
        "model_used": selected_model or "default",
        "timestamp": datetime.now().isoformat()
    }


@chat_router.post("/api/chat/stream")
async def chat_with_agent_stream(payload: Dict[str, Any]):
    """Server-Sent Events (SSE) streaming endpoint for real-time token delivery and live reasoning steps."""
    import fast_path_executor as fpe
    import universal_file_extractor as ufe

    message = (payload.get("message") or "").strip()
    attachments = payload.get("attachments") or payload.get("files") or []

    if not message and not attachments:
        raise HTTPException(status_code=400, detail="message or attachments is required")

    uid = get_primary_user_id()

    multimodal_parts = []
    text_contexts = []
    saved_disk_paths = []

    for att in attachments:
        fname = att.get("name", "attachment")
        mime = att.get("type", "application/octet-stream")
        b64_data = att.get("base64", "")
        if not b64_data:
            continue
        if "," in b64_data:
            b64_data = b64_data.split(",", 1)[1]
        try:
            raw_bytes = base64.b64decode(b64_data)
        except Exception:
            continue

        txt_ctx, part = ufe.process_uploaded_attachment(fname, mime, raw_bytes, save_disk=True)
        if part is not None:
            multimodal_parts.append(part)
        if txt_ctx:
            text_contexts.append(txt_ctx)
            m = re.search(r'\[FILE TERSIMPAN DI DISK:\s*(.+?)\]', txt_ctx)
            if m:
                saved_disk_paths.append(m.group(1).strip())

    selected_model = payload.get("selected_model") or payload.get("model")
    selected_key_id = payload.get("key_id")
    if selected_key_id:
        try:
            selected_key_id = int(selected_key_id)
        except Exception:
            selected_key_id = None

    expert_mode = (payload.get("expert_mode") or "general").strip()
    full_prompt = message
    if text_contexts:
        full_prompt = "\n\n".join(text_contexts) + ("\n\n" + message if message else "\n\nAnalisis isi dokumen terlampir di atas secara mendalam.")
    if expert_mode and expert_mode != "general":
        full_prompt = f"[Mode Spesialis: {expert_mode}]\n{full_prompt}"

    async def event_generator():
        start_t = time.time()

        # 1. Check Fast Path
        fast_result = fpe.try_execute_fast_path(user_prompt=message, saved_file_paths=saved_disk_paths)
        if fast_result is not None:
            reply = fast_result.get("reply", "")
            yield f"data: {json.dumps({'type': 'start', 'model': 'fast_path'})}\n\n"
            words = reply.split(" ")
            for i, w in enumerate(words):
                chunk = w + (" " if i < len(words) - 1 else "")
                yield f"data: {json.dumps({'type': 'token', 'chunk': chunk})}\n\n"
                await asyncio.sleep(0.015)
            elapsed_ms = round((time.time() - start_t) * 1000, 1)
            yield f"data: {json.dumps({'type': 'done', 'reply': reply, 'model_used': 'Fast-Path Engine', 'execution_time_ms': elapsed_ms})}\n\n"
            return

        # 2. Yield reasoning progress
        yield f"data: {json.dumps({'type': 'progress', 'step': '1. Memvalidasi berkas & menyiapkan memori...'})}\n\n"
        await asyncio.sleep(0.05)
        engine_label = selected_model or 'Otak Utama'
        yield f"data: {json.dumps({'type': 'progress', 'step': f'2. Memanggil engine {engine_label} & eksekusi tools...'})}\n\n"

        turn_task = asyncio.create_task(_get_bot().run_agent_turn(
            user_id=uid,
            user_prompt=full_prompt,
            multimodal_parts=multimodal_parts if multimodal_parts else None,
            chat_id=uid,
            override_model=selected_model,
            override_key_id=selected_key_id
        ))

        while not turn_task.done():
            yield ": ping\n\n"
            await asyncio.sleep(2.0)

        try:
            reply = await turn_task
        except Exception as e:
            logger.error(f"Error in chat stream: {e}", exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
            return

        yield f"data: {json.dumps({'type': 'progress', 'step': '3. Memformat respon Markdown & artefak...'})}\n\n"
        if not reply:
            reply = "⚠️ Tidak ada respon yang dihasilkan oleh model AI. Pastikan AI Gateway (9Router di port 20128) aktif atau periksa kuota API Key di Vault."

        yield f"data: {json.dumps({'type': 'start', 'model': selected_model or 'default'})}\n\n"

        lines = (reply or "").split("\n")
        for line_idx, line in enumerate(lines):
            words = line.split(" ")
            for w_idx, w in enumerate(words):
                token = w + (" " if w_idx < len(words) - 1 else "")
                yield f"data: {json.dumps({'type': 'token', 'chunk': token})}\n\n"
                await asyncio.sleep(0.008)
            if line_idx < len(lines) - 1:
                yield f"data: {json.dumps({'type': 'token', 'chunk': chr(10)})}\n\n"
                await asyncio.sleep(0.01)

        elapsed_ms = round((time.time() - start_t) * 1000, 1)
        yield f"data: {json.dumps({'type': 'done', 'reply': reply, 'model_used': selected_model or 'default', 'execution_time_ms': elapsed_ms})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@chat_router.get("/api/chat/models")
async def get_chat_available_models():
    """Get all available AI models grouped by connected API keys in the vault."""
    keys = database.list_api_keys_sync()
    active_brain_model = database.get_main_brain_model()
    active_key_id = database.get_main_brain_key_id()

    model_list = []

    gemini_models = [
        {"id": "gemini-3.6-flash", "name": "Gemini 3.6 Flash (Default Agentic)", "provider": "gemini"},
        {"id": "gemini-3.7-flash", "name": "Gemini 3.7 Flash Thinking (Deep Logic)", "provider": "gemini"},
        {"id": "gemini-3.5-flash", "name": "Gemini 3.5 Flash (Stabil & Cepat)", "provider": "gemini"},
        {"id": "gemini-3.1-flash-lite", "name": "Gemini 3.1 Flash Lite (Ultra Ringan)", "provider": "gemini"},
        {"id": "gemini-3.5-flash-lite", "name": "Gemini 3.5 Flash Lite", "provider": "gemini"},
    ]

    has_gemini = False
    for k in keys:
        prov = (k.get("provider") or "").lower()
        def_m = k.get("default_model") or ""
        kid = k.get("id")
        kname = k.get("name")
        is_act = k.get("is_active", False)

        if prov == "gemini":
            has_gemini = True
            for gm in gemini_models:
                model_list.append({
                    "id": gm["id"],
                    "name": f"✨ {gm['name']}",
                    "provider": f"Gemini ({kname})",
                    "key_id": kid,
                    "key_name": kname,
                    "is_active_key": is_act
                })
        elif prov == "openrouter":
            or_models = [
                {"id": "nvidia/nemotron-3-super-120b-a12b:free", "name": "Nvidia Nemotron 120B (Free)"},
                {"id": "anthropic/claude-sonnet-4.6", "name": "Claude Sonnet 4.6 (Paid)"},
                {"id": "deepseek/deepseek-r1", "name": "DeepSeek R1 Reasoning (Paid)"},
                {"id": "deepseek/deepseek-chat", "name": "DeepSeek V3 (Paid)"},
                {"id": def_m if def_m else "google/gemini-2.5-flash", "name": f"Kunci Default ({def_m or 'gemini-2.5-flash'})"},
            ]
            seen_ids = set()
            for om in or_models:
                if om["id"] not in seen_ids:
                    seen_ids.add(om["id"])
                    model_list.append({
                        "id": om["id"],
                        "name": f"🌐 {om['name']}",
                        "provider": f"OpenRouter ({kname})",
                        "key_id": kid,
                        "key_name": kname,
                        "is_active_key": is_act
                    })
        elif prov in ("groq", "openai", "custom", "nvidia", "9router"):
            model_list.append({
                "id": def_m or f"{prov}-model",
                "name": f"⚡ {kname} ({def_m or prov})",
                "provider": prov.upper(),
                "key_id": kid,
                "key_name": kname,
                "is_active_key": is_act
            })

    if not has_gemini:
        for gm in gemini_models:
            model_list.append({
                "id": gm["id"],
                "name": f"✨ {gm['name']}",
                "provider": "Gemini (Env)",
                "key_id": None,
                "key_name": "GEMINI_API_KEY",
                "is_active_key": True
            })

    is_offline = os.getenv("ALFA_OFFLINE_MODE", "").lower() in ("true", "1", "on")
    ollama_models = [
        {"id": "hermes3:latest", "name": "🦙 Hermes 3 Llama-3.1 8B (Offline Brain)"},
        {"id": "qwen2.5:latest", "name": "⚡ Qwen 2.5 7B Coder (Offline Brain)"},
        {"id": "deepseek-r1:8b", "name": "🧠 DeepSeek R1 8B Reasoning (Offline Brain)"},
    ]
    for om in ollama_models:
        model_list.append({
            "id": om["id"],
            "name": om["name"],
            "provider": "Ollama Local Engine",
            "key_id": "ollama",
            "key_name": "Ollama (localhost:11434)",
            "is_active_key": is_offline
        })

    return {
        "status": "success",
        "active_model": active_brain_model or "gemini-3.6-flash",
        "active_key_id": active_key_id,
        "models": model_list
    }


@chat_router.post("/api/chat/model")
async def set_chat_active_model(payload: Dict[str, Any]):
    """Set and persist default active model."""
    model = (payload.get("model") or "").strip()
    key_id = payload.get("key_id")
    if key_id == "ollama":
        os.environ["ALFA_OFFLINE_MODE"] = "true"
        os.environ["OLLAMA_MODEL"] = model
    elif key_id:
        os.environ["ALFA_OFFLINE_MODE"] = "false"
        try:
            database.activate_api_key_sync(int(key_id), custom_model=model if model else None)
        except Exception as e:
            logger.warning(f"Failed activating key #{key_id}: {e}")
    else:
        os.environ["ALFA_OFFLINE_MODE"] = "false"
    if model:
        database.set_main_brain_model(model)
    return {"status": "success", "message": f"Model aktif berhasil dialihkan ke: {model}"}


@chat_router.delete("/api/chat/history")
async def clear_chat_history_api():
    """Wipe chat conversation history from database."""
    uid = get_primary_user_id()
    await database.clear_user_chat_history(uid)
    return {"status": "success", "message": "Riwayat percakapan berhasil dibersihkan dari memori!"}


@chat_router.post("/api/chat/execute-code")
async def execute_chat_code_block(payload: Dict[str, Any]):
    """Live Interactive Code Sandbox Execution right from Chat Code Blocks."""
    language = (payload.get("language") or "python").lower().strip()
    raw_code = (payload.get("code") or "").strip()
    clean_code = tools._clean_code_snippet(raw_code)
    if not clean_code:
        raise HTTPException(status_code=400, detail="code is required")

    uid = get_primary_user_id()
    tools.current_user_id_var.set(uid)
    tools.current_chat_id_var.set(uid)

    t0 = time.perf_counter()

    if language in ("python", "py", "python3"):
        result = tools.execute_python_sandbox(code=clean_code)
    elif language in ("bash", "sh", "shell", "zsh"):
        result = tools.execute_bash_command(command=clean_code)
    elif language in ("js", "javascript", "node"):
        tmp_js = os.path.join(tools.SANDBOX_DIR, f"script_{int(time.time()*1000)}.js")
        os.makedirs(tools.SANDBOX_DIR, exist_ok=True)
        with open(tmp_js, "w", encoding="utf-8") as f:
            f.write(clean_code)
        result = tools.execute_bash_command(command=f"node {tmp_js}")
    else:
        result = tools.execute_python_sandbox(code=clean_code)

    elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)

    return {
        "status": "success",
        "language": language,
        "execution_time_ms": elapsed_ms,
        "result": result
    }


@chat_router.get("/api/chat/export")
async def export_chat_history(format: str = "markdown"):
    """Export current user conversation history into Markdown (.md) or JSON."""
    uid = get_primary_user_id()
    rows = await database.get_recent_chat_history(uid, limit=100)

    if format == "json":
        return {
            "status": "success",
            "exported_at": datetime.now().isoformat(),
            "total_messages": len(rows),
            "messages": [dict(r) for r in rows]
        }

    lines = [
        "# ALFA Sovereign Agent — Riwayat Percakapan",
        f"*Diekspor pada: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} WIB*",
        "",
        "---",
        ""
    ]
    for r in rows:
        role_label = "👤 **Fahmi (User)**" if r["role"] == "user" else "🤖 **Agent ALFA**"
        ts = r.get("timestamp") or ""
        lines.append(f"### {role_label}  `{ts}`")
        lines.append("")
        lines.append(r["content"])
        lines.append("")
        lines.append("---")
        lines.append("")

    md_content = "\n".join(lines)
    return Response(
        content=md_content,
        media_type="text/markdown",
        headers={"Content-Disposition": f"attachment; filename=alfa_chat_export_{int(time.time())}.md"}
    )


@chat_router.get("/api/chat/modes")
async def get_chat_expert_modes():
    """Available expert persona modes with tailored system instructions."""
    return {
        "status": "success",
        "modes": [
            {
                "id": "general",
                "name": "Super Agent (130+ Tools)",
                "icon": "bot",
                "color": "cyan",
                "description": "Mode otonom penuh dengan semua tools: web search, sandbox, media, OS, memory."
            },
            {
                "id": "swarm",
                "name": "Autonomous Multi-Agent Swarm",
                "icon": "users",
                "color": "amber",
                "description": "Orkestrasi eksekusi tim AI multi-agent untuk proyek besar dan tugas multi-tahap secara tuntas."
            },
            {
                "id": "coder",
                "name": "Senior Software Architect",
                "icon": "code-2",
                "color": "emerald",
                "description": "Fokus pada pembuatan kode berkualitas tinggi, refactoring, debug, dan testing di sandbox."
            },
            {
                "id": "researcher",
                "name": "Deep Web & Academic Researcher",
                "icon": "search",
                "color": "violet",
                "description": "Riset mendalam menggunakan internet live, arXiv, PubMed, Wikipedia, dan perbandingan referensi."
            },
            {
                "id": "data",
                "name": "Data Analyst & PDF Maestro",
                "icon": "file-spreadsheet",
                "color": "amber",
                "description": "Analisis Excel/CSV, visualisasi data, manipulasi PDF, OCR, dan konversi dokumen."
            },
            {
                "id": "fast",
                "name": "Sub-Second Fast Native",
                "icon": "zap",
                "color": "rose",
                "description": "Eksekusi instan deterministik (< 50ms) untuk konversi gambar ke PDF, waifu2x, dll."
            }
        ]
    }


@chat_router.post("/api/chat/async")
async def chat_with_agent_async(payload: Dict[str, Any]):
    """Kirim tugas ke agent secara LATAR BELAKANG (fire-and-forget)."""
    import universal_file_extractor as ufe

    message = (payload.get("message") or "").strip()
    attachments = payload.get("attachments") or []
    if not message and not attachments:
        raise HTTPException(status_code=400, detail="message or attachments is required")
    uid = get_primary_user_id()
    task_tag = f"[tugas-latar {datetime.now().strftime('%H:%M:%S')}]"

    async def _runner():
        try:
            multimodal_parts = []
            text_contexts = []
            for att in attachments:
                fname = att.get("name", "attachment")
                mime = att.get("type", "application/octet-stream")
                b64_data = att.get("base64", "")
                if not b64_data:
                    continue
                if "," in b64_data:
                    b64_data = b64_data.split(",", 1)[1]
                try:
                    raw_bytes = base64.b64decode(b64_data)
                except Exception:
                    continue

                txt_ctx, part = ufe.process_uploaded_attachment(fname, mime, raw_bytes)
                if part is not None:
                    multimodal_parts.append(part)
                if txt_ctx:
                    text_contexts.append(txt_ctx)

            full_prompt = message
            if text_contexts:
                full_prompt = "\n\n".join(text_contexts) + ("\n\n" + message if message else "\n\nAnalisis isi dokumen terlampir di atas secara mendalam.")

            reply = await _get_bot().run_agent_turn(
                user_id=uid,
                user_prompt=full_prompt,
                multimodal_parts=multimodal_parts if multimodal_parts else None,
                chat_id=uid
            )
            await database.save_chat_message(
                uid, "model", f"{task_tag} SELESAI ✅\n\n{reply}")
            logger.info(f"chat_async selesai: {task_tag}")
        except Exception as e:
            logger.error(f"chat_async gagal ({task_tag}): {e}")
            try:
                await database.save_chat_message(
                    uid, "model", f"{task_tag} GAGAL ❌: {e}")
            except Exception:
                pass

    asyncio.get_running_loop().create_task(_runner())
    return {
        "status": "accepted",
        "message": "Tugas dijalankan di latar belakang. Hasil muncul di riwayat chat saat selesai.",
        "tag": task_tag
    }
