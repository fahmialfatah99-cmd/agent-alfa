"""Native Anthropic Messages API adapter (tool-use loop + streaming).

Provider Anthropic tidak benar-benar OpenAI-compatible pada jalur tool-use:
``/v1/messages`` memakai ``system`` terpisah, blok ``tool_use`` dan
``tool_result``. Modul ini menjembatani skema tool internal (format OpenAI)
ke format Anthropic, menjalankan loop tool dengan permission gate yang sama,
dan mengembalikan ``None`` bila gagal total supaya pemanggil bisa fallback
ke rantai Gemini tanpa perubahan perilaku.

Semua error jaringan/format ditelan dengan log — tidak pernah melempar ke
pemanggil utama.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import AsyncIterator
from typing import Any

import httpx

from alfa.core.brain.config import MAX_ITERATIONS

logger = logging.getLogger("AnthropicNative")

_ANTHROPIC_VERSION = "2023-06-01"
_DEFAULT_MODEL = "claude-3-7-sonnet-latest"
_ERR = (
    httpx.HTTPError,
    ValueError,
    KeyError,
    IndexError,
    TypeError,
    RuntimeError,
    AttributeError,
    OSError,
    TimeoutError,
    ConnectionError,
)

# Salam murni tidak perlu skema tool (hemat token); daftar ini sengaja kecil
# dan konservatif — pertanyaan apa pun yang mengandung kata aksi tetap diberi
# tool oleh TOOL-RAG.
_PURE_GREETINGS = {
    "halo",
    "hai",
    "hei",
    "pagi",
    "siang",
    "sore",
    "malam",
    "selamat pagi",
    "selamat siang",
    "selamat sore",
    "selamat malam",
    "apa kabar",
    "siapa kamu",
    "tes",
    "ping",
    "test",
    "makasih",
    "terima kasih",
    "thanks",
    "thank you",
    "ok",
    "oke",
    "siap",
    "sip",
    "yoi",
}


def _max_tokens() -> int:
    try:
        return max(256, int(os.getenv("ANTHROPIC_MAX_TOKENS", "8192")))
    except (TypeError, ValueError):
        return 8192


def _temperature() -> float:
    try:
        value = float(os.getenv("ANTHROPIC_TEMPERATURE", "0.7"))
    except (TypeError, ValueError):
        return 0.7
    return min(max(value, 0.0), 1.0)


def messages_url(base_url: str | None) -> str:
    """Normalisasi base URL vault menjadi endpoint ``/v1/messages``."""
    base = (base_url or "https://api.anthropic.com").strip().rstrip("/")
    if base.endswith("/v1/messages"):
        return base
    if base.endswith("/v1"):
        return f"{base}/messages"
    return f"{base}/v1/messages"


def _resolve_model(model: str | None) -> str:
    """Pakai model Claude yang valid; hindari nama model Gemini nyasar."""
    name = (model or "").strip()
    if not name or name.lower().startswith(("gemini", "gemma")):
        return os.getenv("ANTHROPIC_MODEL", _DEFAULT_MODEL)
    return name


def _headers(api_key: str) -> dict[str, str]:
    return {
        "x-api-key": api_key,
        "anthropic-version": _ANTHROPIC_VERSION,
        "content-type": "application/json",
        "accept": "application/json",
    }


def to_anthropic_tools(
    tools_schema: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Konversi skema tool OpenAI (``type:function``) ke format Anthropic."""
    converted: list[dict[str, Any]] = []
    for item in tools_schema or []:
        fn = (item or {}).get("function") or {}
        name = str(fn.get("name") or "").strip()
        if not name:
            continue
        schema = fn.get("parameters")
        if not isinstance(schema, dict):
            schema = {"type": "object", "properties": {}}
        converted.append(
            {
                "name": name,
                "description": str(fn.get("description") or name)[:1024],
                "input_schema": schema,
            }
        )
    return converted


def _history_messages(history: list[dict[str, Any]] | None) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    started = False
    for item in (history or [])[-10:]:
        content = item.get("content")
        if not content:
            continue
        role = "assistant" if str(item.get("role")) in {"model", "assistant"} else "user"
        # Messages API mensyaratkan pesan pertama berperan user; buang
        # assistant pembuka yang terbawa saat jendela riwayat terpotong.
        if not started and role == "assistant":
            continue
        started = True
        messages.append({"role": role, "content": str(content)})
    return messages


def _default_tools(
    user_text: str, history: list[dict[str, Any]] | None
) -> list[dict[str, Any]]:
    low = (user_text or "").lower().strip()
    if low in _PURE_GREETINGS and len(low) < 40:
        return []
    from alfa.core.brain.tool_schema import build_openai_tools

    tools = build_openai_tools()
    try:
        from alfa.tools.rag import select_relevant_tools

        tools = select_relevant_tools(tools, user_text, history=history)
    except (ImportError, ValueError, TypeError, KeyError):
        pass  # fail-open: set lengkap
    return tools


def _text_of(content: list[dict[str, Any]]) -> str:
    return "".join(
        str(block.get("text") or "")
        for block in content
        if isinstance(block, dict) and block.get("type") == "text"
    ).strip()


def _tool_uses(content: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        block
        for block in content
        if isinstance(block, dict) and block.get("type") == "tool_use"
    ]


async def _request_messages(
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout: float,
) -> dict[str, Any]:
    """Satu request non-streaming; dipisah agar mudah diuji/monkeypatch."""
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(url, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, dict) else {}


async def _wrap_up(
    *,
    url: str,
    headers: dict[str, str],
    model: str,
    system_instruction: str,
    messages: list[dict[str, Any]],
    timeout: float,
    key_id,
    key_label: str,
    context: str,
) -> str | None:
    """Ringkasan akhir tanpa tools setelah batas iterasi tercapai."""
    try:
        from alfa.core import token_usage

        wrap = await _request_messages(
            url,
            headers,
            {
                "model": model,
                "max_tokens": _max_tokens(),
                "temperature": _temperature(),
                "system": system_instruction,
                "messages": messages,
            },
            timeout,
        )
        token_usage.from_anthropic_json(
            wrap,
            provider="anthropic",
            model=model,
            key_id=key_id,
            key_label=key_label,
            context=f"{context}:wrapup",
        )
        text = _text_of(wrap.get("content") or [])
        if text:
            return f"⏳ *Progres parsial (batas iterasi tercapai):*\n\n{text}"
    except _ERR as wrap_err:
        logger.warning("[Anthropic] wrap-up gagal: %s", wrap_err)
    return None


async def run_anthropic_agentic_turn(
    api_key: str,
    model: str,
    system_instruction: str,
    user_text: str,
    history: list[dict[str, Any]] | None = None,
    base_url: str = "",
    key_id=None,
    key_label: str = "",
    context: str = "telegram_chat",
    tools_schema: list[dict[str, Any]] | None = None,
    approval_gate=None,
    timeout: float = 180.0,
) -> str | None:
    """Satu giliran agentik native Anthropic (Messages API + tool-use loop)."""
    key = (api_key or "").strip()
    if not key:
        logger.warning("[Anthropic] api_key kosong -> lewati")
        return None

    try:
        from alfa.core import token_usage
        from alfa.core.brain.agentic import _run_tool_calls
        from alfa.core.rate_limiter import check_rate_limit
        from alfa.core.runtime_ctx import get_current_user_id

        _uid = get_current_user_id() or 0
        allowed, reason = check_rate_limit(user_id=_uid, provider="anthropic")
        if not allowed:
            logger.warning("[Anthropic] rate limit: %s", reason)
            return (
                "⏳ *Kuota harian tercapai.*\n\n"
                f"Batas pemakaian untuk hari ini sudah habis ({reason}). "
                "Coba lagi besok atau naikkan batasnya di Dashboard > Budget."
            )

        if tools_schema is None:
            tools_schema = _default_tools(user_text, history)
        tools = to_anthropic_tools(tools_schema)
        url = messages_url(base_url)
        headers = _headers(key)
        resolved_model = _resolve_model(model)

        messages: list[dict[str, Any]] = _history_messages(history)
        messages.append({"role": "user", "content": user_text})

        payload_base: dict[str, Any] = {
            "model": resolved_model,
            "max_tokens": _max_tokens(),
            "temperature": _temperature(),
            "system": system_instruction,
        }
        if tools:
            payload_base["tools"] = tools

        executed_signatures: list[tuple[str, str]] = []
        repetition_count = 0

        for iteration in range(MAX_ITERATIONS):
            data = await _request_messages(
                url, headers, {**payload_base, "messages": messages}, timeout
            )
            token_usage.from_anthropic_json(
                data,
                provider="anthropic",
                model=resolved_model,
                key_id=key_id,
                key_label=key_label,
                context=context,
            )
            content = data.get("content") or []
            if not isinstance(content, list):
                content = []
            uses = _tool_uses(content)
            if not uses:
                return _text_of(content) or "(provider tidak mengirim teks)"

            signatures = [
                (
                    str(block.get("name") or ""),
                    json.dumps(block.get("input") or {}, sort_keys=True, default=str),
                )
                for block in uses
            ]
            if signatures and all(sig in executed_signatures for sig in signatures):
                repetition_count += 1
                if repetition_count >= 2:
                    logger.warning(
                        "[Anthropic] tool call berulang (%s) -> wrap-up",
                        signatures[:1],
                    )
                    break
            else:
                repetition_count = 0
            executed_signatures.extend(signatures)

            messages.append({"role": "assistant", "content": content})
            tool_calls = [
                {
                    "id": str(block.get("id") or f"toolu_{iteration}_{idx}"),
                    "function": {
                        "name": str(block.get("name") or ""),
                        "arguments": json.dumps(
                            block.get("input") or {}, ensure_ascii=False, default=str
                        ),
                    },
                }
                for idx, block in enumerate(uses)
            ]
            outputs = await _run_tool_calls(approval_gate, tool_calls)
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": call["id"],
                            "content": str(output),
                        }
                        for call, output in zip(tool_calls, outputs, strict=True)
                    ],
                }
            )

        # Batas iterasi: minta ringkasan tanpa tools agar progres tidak hilang.
        messages.append(
            {
                "role": "user",
                "content": (
                    "[SISTEM] Batas putaran tool tercapai. STOP memanggil tool. "
                    "Ringkas apa yang SUDAH berhasil dikerjakan, hasil/data penting "
                    "yang sudah didapat, dan langkah tersisa."
                ),
            }
        )
        return await _wrap_up(
            url=url,
            headers=headers,
            model=resolved_model,
            system_instruction=system_instruction,
            messages=messages,
            timeout=timeout,
            key_id=key_id,
            key_label=key_label,
            context=context,
        )
    except _ERR:
        logger.exception("[Anthropic] turn gagal")
        return None


def _finalize_stream_blocks(
    blocks: dict[int, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Ubah akumulasi blok streaming menjadi content blocks Anthropic valid."""
    content: list[dict[str, Any]] = []
    for index in sorted(blocks):
        block = dict(blocks[index])
        raw_json = str(block.pop("_json", "") or "")
        if block.get("type") == "tool_use":
            try:
                block["input"] = json.loads(raw_json) if raw_json else {}
            except ValueError:
                block["input"] = {}
        elif block.get("type") == "text":
            text = str(block.get("text") or "")
            if not text:
                continue
            block["text"] = text
        content.append(block)
    return content


async def run_anthropic_agentic_turn_streaming(
    api_key: str,
    model: str,
    system_instruction: str,
    user_text: str,
    history: list[dict[str, Any]] | None = None,
    base_url: str = "",
    key_id=None,
    key_label: str = "",
    context: str = "telegram_chat",
    tools_schema: list[dict[str, Any]] | None = None,
    approval_gate=None,
    timeout: float = 180.0,
) -> AsyncIterator[str]:
    """Versi streaming native; yield potongan teks saat tiba."""
    key = (api_key or "").strip()
    if not key:
        logger.warning("[Anthropic] api_key kosong -> streaming dilewati")
        return

    try:
        from alfa.core import token_usage
        from alfa.core.brain.agentic import _run_tool_calls
        from alfa.core.rate_limiter import check_rate_limit
        from alfa.core.runtime_ctx import get_current_user_id

        _uid = get_current_user_id() or 0
        allowed, reason = check_rate_limit(user_id=_uid, provider="anthropic")
        if not allowed:
            logger.warning("[Anthropic] rate limit streaming: %s", reason)
            yield (
                "⏳ *Kuota harian tercapai.*\n\n"
                f"Batas pemakaian untuk hari ini sudah habis ({reason})."
            )
            return

        if tools_schema is None:
            tools_schema = _default_tools(user_text, history)
        tools = to_anthropic_tools(tools_schema)
        url = messages_url(base_url)
        headers = _headers(key)
        resolved_model = _resolve_model(model)

        messages: list[dict[str, Any]] = _history_messages(history)
        messages.append({"role": "user", "content": user_text})

        payload_base: dict[str, Any] = {
            "model": resolved_model,
            "max_tokens": _max_tokens(),
            "temperature": _temperature(),
            "system": system_instruction,
            "stream": True,
        }
        if tools:
            payload_base["tools"] = tools

        executed_signatures: list[tuple[str, str]] = []
        repetition_count = 0

        for iteration in range(MAX_ITERATIONS):
            blocks: dict[int, dict[str, Any]] = {}
            stop_reason: str | None = None
            usage_in = 0
            usage_out = 0

            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream(
                    "POST",
                    url,
                    headers=headers,
                    json={**payload_base, "messages": messages},
                ) as response:
                    if response.status_code != 200:
                        body = (await response.aread()).decode(
                            "utf-8", errors="replace"
                        )
                        logger.warning(
                            "[Anthropic] HTTP %s: %s",
                            response.status_code,
                            body[:300],
                        )
                        return
                    async for line in response.aiter_lines():
                        if not line or not line.startswith("data:"):
                            continue
                        raw = line[5:].strip()
                        if not raw or raw == "[DONE]":
                            continue
                        try:
                            event = json.loads(raw)
                        except ValueError:
                            continue
                        event_type = event.get("type")
                        if event_type == "message_start":
                            usage = (event.get("message") or {}).get("usage") or {}
                            usage_in = int(usage.get("input_tokens") or 0)
                        elif event_type == "content_block_start":
                            index = int(event.get("index") or 0)
                            block = event.get("content_block") or {}
                            if block.get("type") == "tool_use":
                                blocks[index] = {
                                    "type": "tool_use",
                                    "id": str(block.get("id") or ""),
                                    "name": str(block.get("name") or ""),
                                    "input": {},
                                    "_json": "",
                                }
                            elif block.get("type") == "text":
                                initial = str(block.get("text") or "")
                                blocks[index] = {"type": "text", "text": initial}
                                if initial:
                                    yield initial
                        elif event_type == "content_block_delta":
                            index = int(event.get("index") or 0)
                            delta = event.get("delta") or {}
                            if delta.get("type") == "text_delta":
                                chunk = str(delta.get("text") or "")
                                if chunk:
                                    entry = blocks.setdefault(
                                        index, {"type": "text", "text": ""}
                                    )
                                    entry["text"] = str(entry.get("text") or "") + chunk
                                    yield chunk
                            elif delta.get("type") == "input_json_delta":
                                entry = blocks.setdefault(
                                    index,
                                    {
                                        "type": "tool_use",
                                        "id": "",
                                        "name": "",
                                        "input": {},
                                        "_json": "",
                                    },
                                )
                                entry["_json"] = str(entry.get("_json") or "") + str(
                                    delta.get("partial_json") or ""
                                )
                        elif event_type == "message_delta":
                            stop_reason = (event.get("delta") or {}).get("stop_reason")
                            usage_out = int(
                                (event.get("usage") or {}).get("output_tokens") or 0
                            )

            token_usage.record(
                provider="anthropic",
                model=resolved_model,
                key_id=key_id,
                key_label=key_label,
                context=context,
                prompt_tokens=usage_in,
                completion_tokens=usage_out,
            )

            content = _finalize_stream_blocks(blocks)
            uses = _tool_uses(content)
            if not uses or stop_reason != "tool_use":
                return

            signatures = [
                (
                    str(block.get("name") or ""),
                    json.dumps(block.get("input") or {}, sort_keys=True, default=str),
                )
                for block in uses
            ]
            if signatures and all(sig in executed_signatures for sig in signatures):
                repetition_count += 1
                if repetition_count >= 2:
                    logger.warning(
                        "[Anthropic] streaming tool berulang -> berhenti"
                    )
                    return
            else:
                repetition_count = 0
            executed_signatures.extend(signatures)

            messages.append({"role": "assistant", "content": content})
            tool_calls = [
                {
                    "id": str(block.get("id") or f"toolu_{iteration}_{idx}"),
                    "function": {
                        "name": str(block.get("name") or ""),
                        "arguments": json.dumps(
                            block.get("input") or {}, ensure_ascii=False, default=str
                        ),
                    },
                }
                for idx, block in enumerate(uses)
            ]
            outputs = await _run_tool_calls(approval_gate, tool_calls)
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": call["id"],
                            "content": str(output),
                        }
                        for call, output in zip(tool_calls, outputs, strict=True)
                    ],
                }
            )
    except _ERR:
        logger.exception("[Anthropic] streaming gagal")
        return


__all__ = [
    "messages_url",
    "run_anthropic_agentic_turn",
    "run_anthropic_agentic_turn_streaming",
    "to_anthropic_tools",
]
