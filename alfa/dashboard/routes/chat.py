"""Chat and conversation routes, SSE streaming, model selection, and code execution for ALFA Dashboard."""

import asyncio
import base64
import json
import os
import re
import sqlite3
import time
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import StreamingResponse

from alfa import tools
from alfa.core import database
from alfa.core.db import conversations as conv_db
from alfa.core.perm import make_headless_gate
from alfa.core.runtime_ctx import (
    current_conversation_id_var,
    set_tool_event_callback,
)
from alfa.dashboard.common import _get_bot, get_primary_user_id, logger
from alfa.dashboard.routes.auth import require_admin

chat_router = APIRouter(tags=["chat"])

#: Turn dashboard yang sedang berjalan: request_id -> asyncio.Task.
_ACTIVE_TURNS: dict[str, asyncio.Task[Any]] = {}
#: Indeks cepat conversation_id -> request_id untuk tombol Stop.
_ACTIVE_BY_CONVERSATION: dict[str, str] = {}


def active_turn_count() -> int:
    """Jumlah turn dashboard yang sedang berjalan (read-only, aman)."""
    return len(_ACTIVE_TURNS)


def cancel_active_turns() -> int:
    """Batalkan seluruh turn aktif saat shutdown; return jumlah yang dibatalkan."""
    tasks = list(_ACTIVE_TURNS.values())
    for task in tasks:
        task.cancel()
    _ACTIVE_TURNS.clear()
    _ACTIVE_BY_CONVERSATION.clear()
    return len(tasks)

_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}

#: Error realistis pada jalur chat/streaming (bukan Exception blanket).
_CHAT_ERR = (
    TypeError,
    ValueError,
    KeyError,
    IndexError,
    AttributeError,
    RuntimeError,
    OSError,
    ArithmeticError,
    UnicodeError,
    sqlite3.Error,
)


def _sse(payload: dict[str, Any]) -> str:
    """Serialize one Server-Sent Event frame (UTF-8, no ASCII escaping)."""
    return f"data: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"


class _DashboardStreamer:
    """Adapter minimal ``push_chunk`` yang dipakai ``run_agent_turn``.

    ``TelegramStreamer`` mengirim/mengedit pesan Telegram; dashboard hanya
    perlu meneruskan token ke antrean SSE.
    """

    def __init__(self, queue: asyncio.Queue[dict[str, Any]]):
        self._queue = queue

    async def push_chunk(self, chunk_text: str) -> None:
        if chunk_text:
            self._queue.put_nowait({"type": "token", "chunk": chunk_text})


def _process_chat_attachments(
    attachments: list[dict[str, Any]], *, save_disk: bool = True
) -> tuple[list[Any], list[str], list[str]]:
    """Decode base64 attachments into multimodal parts + text contexts."""
    from alfa.tools.filesystem import universal_file_extractor as ufe

    multimodal_parts: list[Any] = []
    text_contexts: list[str] = []
    saved_disk_paths: list[str] = []

    for att in attachments or []:
        if not isinstance(att, dict):
            continue
        fname = att.get("name", "attachment")
        mime = att.get("type", "application/octet-stream")
        b64_data = att.get("base64", "")
        if not b64_data or not isinstance(b64_data, str):
            continue
        if "," in b64_data:
            b64_data = b64_data.split(",", 1)[1]
        try:
            raw_bytes = base64.b64decode(b64_data)
        except (ValueError, TypeError):
            continue

        txt_ctx, part = ufe.process_uploaded_attachment(
            fname, mime, raw_bytes, save_disk=save_disk
        )
        if part is not None:
            multimodal_parts.append(part)
        if txt_ctx:
            text_contexts.append(txt_ctx)
            m = re.search(r"\[FILE TERSIMPAN DI DISK:\s*(.+?)\]", txt_ctx)
            if m:
                saved_disk_paths.append(m.group(1).strip())
    return multimodal_parts, text_contexts, saved_disk_paths


def _compose_prompt(
    message: str, text_contexts: list[str], expert_mode: str = "general"
) -> str:
    """Gabungkan konteks dokumen + pesan, lalu prefiks mode spesialis."""
    full_prompt = message
    if text_contexts:
        full_prompt = "\n\n".join(text_contexts) + (
            "\n\n" + message
            if message
            else "\n\nAnalisis isi dokumen terlampir di atas secara mendalam."
        )
    if expert_mode and expert_mode != "general":
        full_prompt = f"[Mode Spesialis: {expert_mode}]\n{full_prompt}"
    return full_prompt


def _parse_key_id(value: Any) -> int | None:
    if value in (None, "", "ollama"):
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


async def _require_conversation(
    uid: int, payload: dict[str, Any], message: str, model: str
) -> tuple[str, dict[str, Any]]:
    """Resolve thread from payload or create a new one (additive behavior)."""
    cid = str(payload.get("conversation_id") or "").strip()
    if cid:
        conv = await conv_db.get_conversation(uid, cid)
        if not conv:
            raise HTTPException(status_code=404, detail="Percakapan tidak ditemukan")
        return cid, conv
    conv = await conv_db.create_conversation(
        uid, title=conv_db.derive_title(message), model=model
    )
    return str(conv["id"]), conv


async def _last_message_id(uid: int, conversation_id: str) -> int | None:
    rows = await conv_db.get_messages(uid, conversation_id, limit=1)
    return int(rows[-1]["id"]) if rows else None


@chat_router.post("/api/chat")
async def chat_with_agent(payload: dict[str, Any]):
    """Send a message directly to the ALFA Agent with optional multimodal attachments and sub-second Fast-Path tool execution."""
    from alfa.core import fast_path_executor as fpe

    message = (payload.get("message") or "").strip()
    attachments = payload.get("attachments") or []

    if not message and not attachments:
        raise HTTPException(
            status_code=400, detail="message or attachments is required"
        )

    uid = get_primary_user_id()
    selected_model = payload.get("selected_model")
    selected_key_id = _parse_key_id(payload.get("key_id"))
    conversation_id = str(payload.get("conversation_id") or "").strip() or None

    multimodal_parts, text_contexts, saved_disk_paths = _process_chat_attachments(
        attachments
    )

    conversation_token = None
    if conversation_id:
        conv = await conv_db.get_conversation(uid, conversation_id)
        if not conv:
            raise HTTPException(status_code=404, detail="Percakapan tidak ditemukan")
        conversation_token = current_conversation_id_var.set(conversation_id)

    try:
        # 1. Check Sub-second Fast-Path Engine first (0.05s response)
        fast_result = fpe.try_execute_fast_path(
            user_prompt=message, saved_file_paths=saved_disk_paths
        )
        if fast_result is not None:
            reply = fast_result.get("reply") or ""
            if conversation_id:
                await database.save_chat_message(
                    uid, "user", message or "[Lampiran Media]"
                )
                await database.save_chat_message(uid, "model", reply)
                await conv_db.update_message_metadata(
                    uid,
                    conversation_id,
                    {
                        "model": "fast_path",
                        "tool_used": fast_result.get("tool_name"),
                        "execution_time_ms": fast_result.get("execution_time_ms"),
                    },
                )
            return {
                "status": "success",
                "reply": reply,
                "tool_used": fast_result.get("tool_name"),
                "execution_time_ms": fast_result.get("execution_time_ms"),
                "conversation_id": conversation_id,
                "timestamp": datetime.now().isoformat(),
            }

        # 2. Autonomous Multi-step LLM Turn
        expert_mode = (payload.get("expert_mode") or "general").strip()
        full_prompt = _compose_prompt(message, text_contexts, expert_mode)

        reply = await _get_bot().run_agent_turn(
            user_id=uid,
            user_prompt=full_prompt,
            multimodal_parts=multimodal_parts if multimodal_parts else None,
            chat_id=uid,
            override_model=selected_model,
            override_key_id=selected_key_id,
            approval_gate=make_headless_gate(uid),
        )
        if conversation_id:
            await conv_db.update_message_metadata(
                uid,
                conversation_id,
                {
                    "model": selected_model or "default",
                    "expert_mode": expert_mode,
                },
            )
        return {
            "status": "success",
            "reply": reply,
            "model_used": selected_model or "default",
            "conversation_id": conversation_id,
            "timestamp": datetime.now().isoformat(),
        }
    finally:
        if conversation_token is not None:
            current_conversation_id_var.reset(conversation_token)


@chat_router.post("/api/chat/stream")
async def chat_with_agent_stream(payload: dict[str, Any]):
    """SSE streaming nyata: token LLM, event tool, thread terisolasi, dan stop.

    Payload kompatibel dengan versi lama (``message``/``attachments``/
    ``selected_model``); field baru bersifat opsional:
    ``conversation_id``, ``regenerate``, ``edit_message_id``.
    """
    from alfa.core import fast_path_executor as fpe

    uid = get_primary_user_id()
    message = (payload.get("message") or "").strip()
    attachments = payload.get("attachments") or payload.get("files") or []
    selected_model = payload.get("selected_model") or payload.get("model")
    selected_key_id = _parse_key_id(payload.get("key_id"))
    expert_mode = (payload.get("expert_mode") or "general").strip()
    regenerate = payload.get("regenerate") in (True, 1, "1", "true", "True")
    edit_message_id: int | None = None
    if payload.get("edit_message_id") not in (None, ""):
        try:
            edit_message_id = int(str(payload.get("edit_message_id")))
        except (TypeError, ValueError):
            raise HTTPException(
                status_code=400, detail="edit_message_id tidak valid"
            ) from None

    multimodal_parts, text_contexts, saved_disk_paths = _process_chat_attachments(
        attachments
    )

    if regenerate:
        conversation_id = str(payload.get("conversation_id") or "").strip()
        conv = await conv_db.get_conversation(uid, conversation_id)
        if not conv:
            raise HTTPException(status_code=404, detail="Percakapan tidak ditemukan")
        last_user = await conv_db.get_last_user_message(uid, conversation_id)
        if not last_user:
            raise HTTPException(
                status_code=400, detail="Tidak ada pesan pengguna untuk dibuat ulang"
            )
        await conv_db.delete_messages_from(uid, conversation_id, int(last_user["id"]))
        message = str(last_user.get("content") or "")
        full_prompt = message
        if not full_prompt:
            raise HTTPException(
                status_code=400, detail="Pesan sebelumnya kosong; kirim pesan baru"
            )
    elif edit_message_id is not None:
        conversation_id = str(payload.get("conversation_id") or "").strip()
        conv = await conv_db.get_conversation(uid, conversation_id)
        if not conv:
            raise HTTPException(status_code=404, detail="Percakapan tidak ditemukan")
        if not message and not attachments:
            raise HTTPException(
                status_code=400, detail="message or attachments is required"
            )
        existing = await conv_db.get_messages(uid, conversation_id, limit=1000)
        target = next(
            (m for m in existing if int(m.get("id") or 0) == edit_message_id), None
        )
        if not target or target.get("role") != "user":
            raise HTTPException(
                status_code=400, detail="Pesan yang diedit tidak ditemukan"
            )
        await conv_db.delete_messages_from(uid, conversation_id, edit_message_id)
        full_prompt = _compose_prompt(message, text_contexts, expert_mode)
    else:
        if not message and not attachments:
            raise HTTPException(
                status_code=400, detail="message or attachments is required"
            )
        full_prompt = _compose_prompt(message, text_contexts, expert_mode)
        conversation_id, conv = await _require_conversation(
            uid, payload, message, selected_model or ""
        )

    request_id = uuid.uuid4().hex[:12]
    display_user_text = message or "[Lampiran Media]"
    model_used = selected_model or "default"

    async def event_generator():
        start_t = time.time()
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        loop = asyncio.get_running_loop()
        conv_token = current_conversation_id_var.set(conversation_id)

        def _on_tool_event(tool_name: str, summary: str) -> None:
            ev: dict[str, Any] = {"type": "tool", "name": tool_name}
            if summary:
                ev["args"] = summary
            try:
                loop.call_soon_threadsafe(queue.put_nowait, ev)
            except RuntimeError:
                pass

        cb_token = set_tool_event_callback(_on_tool_event)
        turn_task: asyncio.Task[Any] | None = None
        tool_events: list[dict[str, Any]] = []
        streamed_text = ""

        try:
            # 1. Fast path deterministik (tetap disimpan ke thread).
            fast_result = fpe.try_execute_fast_path(
                user_prompt=message, saved_file_paths=saved_disk_paths
            )
            if fast_result is not None:
                reply = fast_result.get("reply") or ""
                await database.save_chat_message(uid, "user", display_user_text)
                await database.save_chat_message(uid, "model", reply)
                meta = {
                    "model": "fast_path",
                    "tool_used": fast_result.get("tool_name"),
                    "execution_time_ms": fast_result.get("execution_time_ms"),
                }
                await conv_db.update_message_metadata(uid, conversation_id, meta)
                user_msg = await conv_db.get_last_user_message(uid, conversation_id)
                assistant_id = await _last_message_id(uid, conversation_id)
                yield _sse(
                    {
                        "type": "start",
                        "model": "fast_path",
                        "conversation_id": conversation_id,
                        "request_id": request_id,
                    }
                )
                words = reply.split(" ")
                for idx, word in enumerate(words):
                    chunk = word + (" " if idx < len(words) - 1 else "")
                    yield _sse({"type": "token", "chunk": chunk})
                    await asyncio.sleep(0.005)
                elapsed_ms = round((time.time() - start_t) * 1000, 1)
                yield _sse(
                    {
                        "type": "done",
                        "reply": reply,
                        "model_used": "Fast-Path Engine",
                        "execution_time_ms": elapsed_ms,
                        "conversation_id": conversation_id,
                        "request_id": request_id,
                        "user_message_id": user_msg.get("id") if user_msg else None,
                        "message_id": assistant_id,
                        "tools_called": [fast_result.get("tool_name")]
                        if fast_result.get("tool_name")
                        else [],
                        "metadata": meta,
                    }
                )
                return

            # 2. Progress awal (sebelum token pertama).
            yield _sse(
                {
                    "type": "progress",
                    "step": "1. Memvalidasi berkas & menyiapkan memori...",
                    "conversation_id": conversation_id,
                }
            )
            engine_label = selected_model or "Otak Utama"
            yield _sse(
                {
                    "type": "progress",
                    "step": f"2. Memanggil engine {engine_label} & eksekusi tools...",
                    "conversation_id": conversation_id,
                }
            )

            # 3. Giliran nyata: streamer meneruskan token ke antrean SSE.
            turn_task = asyncio.create_task(
                _get_bot().run_agent_turn(
                    user_id=uid,
                    user_prompt=full_prompt,
                    multimodal_parts=multimodal_parts if multimodal_parts else None,
                    chat_id=uid,
                    override_model=selected_model,
                    override_key_id=selected_key_id,
                    streamer=_DashboardStreamer(queue),
                    approval_gate=make_headless_gate(uid),
                )
            )
            _ACTIVE_TURNS[request_id] = turn_task
            _ACTIVE_BY_CONVERSATION[conversation_id] = request_id

            yield _sse(
                {
                    "type": "start",
                    "model": model_used,
                    "conversation_id": conversation_id,
                    "request_id": request_id,
                }
            )

            while True:
                if turn_task.done() and queue.empty():
                    break
                getter = asyncio.create_task(queue.get())
                done, _pending = await asyncio.wait(
                    {getter, turn_task},
                    timeout=1.0,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if getter in done:
                    event = getter.result()
                    if event.get("type") == "token":
                        streamed_text += str(event.get("chunk") or "")
                    elif event.get("type") == "tool":
                        tool_events.append(event)
                    yield _sse(event)
                    continue
                if not getter.done():
                    getter.cancel()
                    try:
                        await getter
                    except asyncio.CancelledError:
                        pass
                if not done:
                    yield ": ping\n\n"

            if turn_task.cancelled():
                elapsed_ms = round((time.time() - start_t) * 1000, 1)
                yield _sse(
                    {
                        "type": "stopped",
                        "message": "Generasi dihentikan.",
                        "reply": streamed_text,
                        "conversation_id": conversation_id,
                        "request_id": request_id,
                        "execution_time_ms": elapsed_ms,
                    }
                )
                return

            try:
                reply = await turn_task
            except _CHAT_ERR as exc:
                logger.error(f"Error in chat stream: {exc}", exc_info=True)
                yield _sse(
                    {
                        "type": "error",
                        "message": str(exc),
                        "conversation_id": conversation_id,
                        "request_id": request_id,
                    }
                )
                return

            if not reply:
                reply = (
                    "⚠️ Tidak ada respon yang dihasilkan oleh model AI. Pastikan "
                    "AI Gateway (9Router di port 20128) aktif atau periksa kuota "
                    "API Key di Vault."
                )

            yield _sse(
                {
                    "type": "progress",
                    "step": "3. Memformat respon Markdown & artefak...",
                    "conversation_id": conversation_id,
                }
            )

            elapsed_ms = round((time.time() - start_t) * 1000, 1)
            tools_called: list[str] = []
            for ev in tool_events:
                name = str(ev.get("name") or "")
                if name and name not in tools_called:
                    tools_called.append(name)
            metadata = {
                "model": model_used,
                "expert_mode": expert_mode,
                "execution_time_ms": elapsed_ms,
                "tools": tool_events,
            }
            user_msg = await conv_db.get_last_user_message(uid, conversation_id)
            assistant_id = await _last_message_id(uid, conversation_id)
            await conv_db.update_message_metadata(
                uid, conversation_id, metadata, message_id=assistant_id
            )

            yield _sse(
                {
                    "type": "done",
                    "reply": reply,
                    "streamed_reply": streamed_text,
                    "model_used": model_used,
                    "execution_time_ms": elapsed_ms,
                    "conversation_id": conversation_id,
                    "request_id": request_id,
                    "user_message_id": user_msg.get("id") if user_msg else None,
                    "message_id": assistant_id,
                    "tools_called": tools_called,
                    "metadata": metadata,
                }
            )
        except asyncio.CancelledError:
            if turn_task is not None and not turn_task.done():
                turn_task.cancel()
            raise
        finally:
            if turn_task is not None and not turn_task.done():
                turn_task.cancel()
            _ACTIVE_TURNS.pop(request_id, None)
            if _ACTIVE_BY_CONVERSATION.get(conversation_id) == request_id:
                _ACTIVE_BY_CONVERSATION.pop(conversation_id, None)
            try:
                from alfa.core.runtime_ctx import current_tool_event_cb_var

                current_tool_event_cb_var.reset(cb_token)
            except (ValueError, RuntimeError):
                set_tool_event_callback(None)
            current_conversation_id_var.reset(conv_token)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


@chat_router.get("/api/chat/conversations")
async def list_chat_conversations(q: str = "", limit: int = 50):
    """Daftar thread dashboard (pinned dulu, lalu aktivitas terbaru)."""
    uid = get_primary_user_id()
    items = await conv_db.list_conversations(uid, query=q, limit=limit)
    return {"status": "success", "total": len(items), "conversations": items}


@chat_router.post("/api/chat/conversations")
async def create_chat_conversation(
    payload: dict[str, Any], request: Request
):
    """Buat thread kosong baru (judul opsional)."""
    require_admin(request)
    uid = get_primary_user_id()
    conv = await conv_db.create_conversation(
        uid,
        title=payload.get("title") or "Obrolan Baru",
        model=payload.get("model") or "",
    )
    return {"status": "success", "conversation": conv}


@chat_router.get("/api/chat/conversations/{conversation_id}")
async def get_chat_conversation(conversation_id: str, messages: int = 1):
    """Detail thread + (opsional) seluruh pesan untuk render ulang UI."""
    uid = get_primary_user_id()
    conv = await conv_db.get_conversation(uid, conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Percakapan tidak ditemukan")
    payload: dict[str, Any] = {"status": "success", "conversation": conv}
    if messages:
        payload["messages"] = await conv_db.get_messages(uid, conversation_id)
    return payload


@chat_router.get("/api/chat/conversations/{conversation_id}/messages")
async def get_chat_conversation_messages(conversation_id: str):
    """Muat pesan satu thread (untuk membuka percakapan lama)."""
    uid = get_primary_user_id()
    conv = await conv_db.get_conversation(uid, conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Percakapan tidak ditemukan")
    rows = await conv_db.get_messages(uid, conversation_id)
    return {
        "status": "success",
        "conversation": conv,
        "total": len(rows),
        "messages": rows,
    }


@chat_router.patch("/api/chat/conversations/{conversation_id}")
async def update_chat_conversation(
    conversation_id: str, payload: dict[str, Any], request: Request
):
    """Rename dan/atau pin thread."""
    require_admin(request)
    uid = get_primary_user_id()
    conv = await conv_db.get_conversation(uid, conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Percakapan tidak ditemukan")

    changed = False
    if payload.get("title") is not None:
        changed = await conv_db.rename_conversation(
            uid, conversation_id, str(payload.get("title") or "")
        ) or changed
    if payload.get("pinned") is not None:
        changed = await conv_db.set_pinned(
            uid, conversation_id, bool(payload.get("pinned"))
        ) or changed
    updated = await conv_db.get_conversation(uid, conversation_id)
    return {
        "status": "success",
        "changed": changed,
        "conversation": updated,
    }


@chat_router.delete("/api/chat/conversations/{conversation_id}")
async def delete_chat_conversation(conversation_id: str, request: Request):
    """Hapus thread beserta seluruh pesannya (bukan riwayat kanal global)."""
    require_admin(request)
    uid = get_primary_user_id()
    deleted = await conv_db.delete_conversation(uid, conversation_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Percakapan tidak ditemukan")
    return {"status": "success", "deleted": True}


@chat_router.post("/api/chat/stop")
async def stop_chat_generation(payload: dict[str, Any], request: Request):
    """Batalkan giliran dashboard yang sedang berjalan (best-effort)."""
    require_admin(request)
    request_id = str(payload.get("request_id") or "").strip()
    conversation_id = str(payload.get("conversation_id") or "").strip()
    if not request_id and conversation_id:
        request_id = _ACTIVE_BY_CONVERSATION.get(conversation_id, "")

    task = _ACTIVE_TURNS.get(request_id) if request_id else None
    if task is None or task.done():
        return {"status": "success", "stopped": False}
    task.cancel()
    logger.info("Chat generation dihentikan: request=%s", request_id)
    return {"status": "success", "stopped": True, "request_id": request_id}


@chat_router.get("/api/chat/models")
async def get_chat_available_models():
    """Get all available AI models grouped by connected API keys in the vault."""
    keys = database.list_api_keys_sync()
    active_brain_model = database.get_main_brain_model()
    active_key_id = database.get_main_brain_key_id()

    model_list = []

    gemini_models = [
        {
            "id": "gemini-3.6-flash",
            "name": "Gemini 3.6 Flash (Default Agentic)",
            "provider": "gemini",
        },
        {
            "id": "gemini-3.7-flash",
            "name": "Gemini 3.7 Flash Thinking (Deep Logic)",
            "provider": "gemini",
        },
        {
            "id": "gemini-3.5-flash",
            "name": "Gemini 3.5 Flash (Stabil & Cepat)",
            "provider": "gemini",
        },
        {
            "id": "gemini-3.1-flash-lite",
            "name": "Gemini 3.1 Flash Lite (Ultra Ringan)",
            "provider": "gemini",
        },
        {
            "id": "gemini-3.5-flash-lite",
            "name": "Gemini 3.5 Flash Lite",
            "provider": "gemini",
        },
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
                model_list.append(
                    {
                        "id": gm["id"],
                        "name": f"✨ {gm['name']}",
                        "provider": f"Gemini ({kname})",
                        "key_id": kid,
                        "key_name": kname,
                        "is_active_key": is_act,
                    }
                )
        elif prov == "openrouter":
            or_models = [
                {
                    "id": "nvidia/nemotron-3-super-120b-a12b:free",
                    "name": "Nvidia Nemotron 120B (Free)",
                },
                {
                    "id": "anthropic/claude-sonnet-4.6",
                    "name": "Claude Sonnet 4.6 (Paid)",
                },
                {"id": "deepseek/deepseek-r1", "name": "DeepSeek R1 Reasoning (Paid)"},
                {"id": "deepseek/deepseek-chat", "name": "DeepSeek V3 (Paid)"},
                {
                    "id": def_m if def_m else "google/gemini-2.5-flash",
                    "name": f"Kunci Default ({def_m or 'gemini-2.5-flash'})",
                },
            ]
            seen_ids = set()
            for om in or_models:
                if om["id"] not in seen_ids:
                    seen_ids.add(om["id"])
                    model_list.append(
                        {
                            "id": om["id"],
                            "name": f"🌐 {om['name']}",
                            "provider": f"OpenRouter ({kname})",
                            "key_id": kid,
                            "key_name": kname,
                            "is_active_key": is_act,
                        }
                    )
        elif prov in ("groq", "openai", "custom", "nvidia", "9router"):
            model_list.append(
                {
                    "id": def_m or f"{prov}-model",
                    "name": f"⚡ {kname} ({def_m or prov})",
                    "provider": prov.upper(),
                    "key_id": kid,
                    "key_name": kname,
                    "is_active_key": is_act,
                }
            )

    if not has_gemini:
        for gm in gemini_models:
            model_list.append(
                {
                    "id": gm["id"],
                    "name": f"✨ {gm['name']}",
                    "provider": "Gemini (Env)",
                    "key_id": None,
                    "key_name": "GEMINI_API_KEY",
                    "is_active_key": True,
                }
            )

    is_offline = os.getenv("ALFA_OFFLINE_MODE", "").lower() in ("true", "1", "on")
    ollama_models = [
        {"id": "hermes3:latest", "name": "🦙 Hermes 3 Llama-3.1 8B (Offline Brain)"},
        {"id": "qwen2.5:latest", "name": "⚡ Qwen 2.5 7B Coder (Offline Brain)"},
        {"id": "deepseek-r1:8b", "name": "🧠 DeepSeek R1 8B Reasoning (Offline Brain)"},
    ]
    for om in ollama_models:
        model_list.append(
            {
                "id": om["id"],
                "name": om["name"],
                "provider": "Ollama Local Engine",
                "key_id": "ollama",
                "key_name": "Ollama (localhost:11434)",
                "is_active_key": is_offline,
            }
        )

    return {
        "status": "success",
        "active_model": active_brain_model or "gemini-3.6-flash",
        "active_key_id": active_key_id,
        "models": model_list,
    }


@chat_router.post("/api/chat/model")
async def set_chat_active_model(request: Request, payload: dict[str, Any]):
    """Set and persist default active model (hanya admin)."""
    require_admin(request)
    model = (payload.get("model") or "").strip()
    key_id = payload.get("key_id")
    if key_id == "ollama":
        os.environ["ALFA_OFFLINE_MODE"] = "true"
        os.environ["OLLAMA_MODEL"] = model
    elif key_id:
        os.environ["ALFA_OFFLINE_MODE"] = "false"
        try:
            database.activate_api_key_sync(
                int(key_id), custom_model=model if model else None
            )
        except (sqlite3.Error, ValueError, TypeError, OSError) as e:
            logger.warning(f"Failed activating key #{key_id}: {e}")
    else:
        os.environ["ALFA_OFFLINE_MODE"] = "false"
    if model:
        database.set_main_brain_model(model)
    return {
        "status": "success",
        "message": f"Model aktif berhasil dialihkan ke: {model}",
    }


@chat_router.delete("/api/chat/history")
async def clear_chat_history_api(request: Request, conversation_id: str = ""):
    """Wipe chat history (hanya admin).

    ``conversation_id`` opsional: hapus satu thread saja. Tanpa parameter,
    perilaku lama tetap dipertahankan (hapus seluruh riwayat kanal global).
    """
    require_admin(request)
    uid = get_primary_user_id()
    if conversation_id:
        await database.clear_user_chat_history(uid, conversation_id)
        await conv_db.touch_conversation(uid, conversation_id)
    else:
        await database.clear_user_chat_history(uid)
    return {
        "status": "success",
        "message": "Riwayat percakapan berhasil dibersihkan dari memori!",
    }


@chat_router.post("/api/chat/execute-code")
async def execute_chat_code_block(payload: dict[str, Any], request: Request):
    """Live Interactive Code Sandbox Execution right from Chat Code Blocks."""
    require_admin(request)
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
        tmp_js = os.path.join(tools.SANDBOX_DIR, f"script_{int(time.time() * 1000)}.js")
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
        "result": result,
    }


@chat_router.get("/api/chat/export")
async def export_chat_history(
    request: Request, format: str = "markdown", conversation_id: str = ""
):
    """Export current user conversation history (hanya admin).

    ``conversation_id`` opsional: bila diisi, hanya thread tersebut yang
    diekspor; bila kosong, perilaku lama (riwayat kanal global) dipertahankan.
    """
    require_admin(request)
    uid = get_primary_user_id()
    if conversation_id:
        rows = await conv_db.get_messages(uid, conversation_id, limit=1000)
    else:
        rows = await database.get_recent_chat_history(uid, limit=100)

    if format == "json":
        return {
            "status": "success",
            "exported_at": datetime.now().isoformat(),
            "total_messages": len(rows),
            "messages": [dict(r) for r in rows],
        }

    lines = [
        "# ALFA Sovereign Agent — Riwayat Percakapan",
        f"*Diekspor pada: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} WIB*",
        "",
        "---",
        "",
    ]
    for r in rows:
        role_label = (
            "👤 **Fahmi (User)**" if r["role"] == "user" else "🤖 **Agent ALFA**"
        )
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
        headers={
            "Content-Disposition": f"attachment; filename=alfa_chat_export_{int(time.time())}.md"
        },
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
                "description": "Mode otonom penuh dengan semua tools: web search, sandbox, media, OS, memory.",
            },
            {
                "id": "swarm",
                "name": "Autonomous Multi-Agent Swarm",
                "icon": "users",
                "color": "amber",
                "description": "Orkestrasi eksekusi tim AI multi-agent untuk proyek besar dan tugas multi-tahap secara tuntas.",
            },
            {
                "id": "coder",
                "name": "Senior Software Architect",
                "icon": "code-2",
                "color": "emerald",
                "description": "Fokus pada pembuatan kode berkualitas tinggi, refactoring, debug, dan testing di sandbox.",
            },
            {
                "id": "researcher",
                "name": "Deep Web & Academic Researcher",
                "icon": "search",
                "color": "violet",
                "description": "Riset mendalam menggunakan internet live, arXiv, PubMed, Wikipedia, dan perbandingan referensi.",
            },
            {
                "id": "data",
                "name": "Data Analyst & PDF Maestro",
                "icon": "file-spreadsheet",
                "color": "amber",
                "description": "Analisis Excel/CSV, visualisasi data, manipulasi PDF, OCR, dan konversi dokumen.",
            },
            {
                "id": "fast",
                "name": "Sub-Second Fast Native",
                "icon": "zap",
                "color": "rose",
                "description": "Eksekusi instan deterministik (< 50ms) untuk konversi gambar ke PDF, waifu2x, dll.",
            },
        ],
    }


@chat_router.post("/api/chat/async")
async def chat_with_agent_async(payload: dict[str, Any]):
    """Kirim tugas ke agent secara LATAR BELAKANG (fire-and-forget)."""
    from alfa.tools.filesystem import universal_file_extractor as ufe

    message = (payload.get("message") or "").strip()
    attachments = payload.get("attachments") or []
    if not message and not attachments:
        raise HTTPException(
            status_code=400, detail="message or attachments is required"
        )
    uid = get_primary_user_id()
    task_tag = f"[tugas-latar {datetime.now().strftime('%H:%M:%S')}]"
    conversation_id = str(payload.get("conversation_id") or "").strip() or None
    selected_model = payload.get("selected_model") or payload.get("model")
    selected_key_id = _parse_key_id(payload.get("key_id"))

    async def _runner():
        conversation_token = (
            current_conversation_id_var.set(conversation_id)
            if conversation_id
            else None
        )
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
                except (ValueError, TypeError):
                    continue

                txt_ctx, part = ufe.process_uploaded_attachment(fname, mime, raw_bytes)
                if part is not None:
                    multimodal_parts.append(part)
                if txt_ctx:
                    text_contexts.append(txt_ctx)

            full_prompt = message
            if text_contexts:
                full_prompt = "\n\n".join(text_contexts) + (
                    "\n\n" + message
                    if message
                    else "\n\nAnalisis isi dokumen terlampir di atas secara mendalam."
                )

            reply = await _get_bot().run_agent_turn(
                user_id=uid,
                user_prompt=full_prompt,
                multimodal_parts=multimodal_parts if multimodal_parts else None,
                chat_id=uid,
                override_model=selected_model,
                override_key_id=selected_key_id,
                approval_gate=make_headless_gate(uid),
            )
            if conversation_id:
                # run_agent_turn sudah menyimpan user+model ke thread; jangan
                # menambah duplikat. Cukup lampirkan metadata ke balasan.
                await conv_db.update_message_metadata(
                    uid,
                    conversation_id,
                    {"model": selected_model or "default", "background": True},
                )
            else:
                await database.save_chat_message(
                    uid, "model", f"{task_tag} SELESAI ✅\n\n{reply}"
                )
            logger.info(f"chat_async selesai: {task_tag}")
        except (TypeError, ValueError, KeyError, IndexError, AttributeError, RuntimeError, OSError, ArithmeticError, UnicodeError, sqlite3.Error) as e:
            logger.error(f"chat_async gagal ({task_tag}): {e}")
            try:
                if not conversation_id:
                    await database.save_chat_message(
                        uid, "model", f"{task_tag} GAGAL ❌: {e}"
                    )
            except (sqlite3.Error, OSError):
                pass
        finally:
            if conversation_token is not None:
                current_conversation_id_var.reset(conversation_token)

    asyncio.get_running_loop().create_task(_runner())
    return {
        "status": "accepted",
        "message": "Tugas dijalankan di latar belakang. Hasil muncul di riwayat chat saat selesai.",
        "tag": task_tag,
    }
