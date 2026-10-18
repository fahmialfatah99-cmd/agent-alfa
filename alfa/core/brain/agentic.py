"""OpenAI-compatible agentic turn loop with tool calls and wrap-up."""

import json
import logging
from typing import Any

from alfa.core.brain.config import MAX_ITERATIONS
from alfa.core.brain.convo import _compact_convo
from alfa.core.brain.tool_exec import _execute_tool
from alfa.core.brain.tool_schema import build_openai_tools

logger = logging.getLogger("MainBrain")


async def run_openai_agentic_turn(
    provider: str,
    base_url: str,
    api_key: str,
    model: str,
    system_instruction: str,
    user_text: str,
    history: list[dict[str, str]] | None = None,
    key_id=None,
    key_label: str = "",
    context: str = "telegram_chat",
    tools_schema: list[dict[str, Any]] | None = None,
    approval_gate=None,
    timeout: float = 180.0,
    raw_errors: bool = False,
) -> str | None:
    """
    Satu turn agentik penuh di provider OpenAI-compatible:
    kirim pesan + tools -> eksekusi tool_calls -> ulangi sampai jawaban final.
    tools_schema=None memakai set lengkap; list kosong = tanpa tools (chat polos).
    approval_gate: callable async (tool_name, args_json)->Optional[str];
    None = boleh, str = tolak dan pakai teks itu sbg hasil tool.
    Return teks jawaban, atau None bila gagal total (pemanggil bisa fallback).
    """
    try:
        import httpx

        from alfa.core import token_usage
        from alfa.core.rate_limiter import check_rate_limit

        allowed, reason = check_rate_limit(user_id=1, provider=provider)
        if not allowed:
            logger.warning(f"[RateLimit] {provider} {model}: {reason}")

        if tools_schema is None:
            txt_low = (user_text or "").lower().strip()
            # Fast check: apakah pertanyaan sederhana/percakapan yang benar-benar tidak membutuhkan tool?
            # Hanya nonaktifkan tools jika pesan murni salam/basa-basi pendek tanpa kata aksi
            pure_greetings = {
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
                "siap bos",
                "mantap",
                "sip",
                "yoi",
            }
            is_simple_chat = txt_low in pure_greetings
            has_action_trigger = any(
                k in txt_low
                for k in [
                    "buat",
                    "bikin",
                    "tulis",
                    "cari",
                    "search",
                    "googling",
                    "browse",
                    "web",
                    "scrape",
                    "jalankan",
                    "run",
                    "eksekusi",
                    "hitung",
                    "baca",
                    "cek",
                    "analisis",
                    "pdf",
                    "excel",
                    "gambar",
                    "foto",
                    "drive",
                    "email",
                    "rapat",
                    "meeting",
                    "jadwal",
                    "ingat",
                    "catat",
                    "simpan",
                    "hapus",
                    "file",
                    "folder",
                    "kode",
                    "code",
                    "python",
                    "bash",
                    "curl",
                    "swarm",
                    "screenshot",
                    "screnshoot",
                    "ss",
                    "layar",
                    "desktop",
                    "tangkap",
                    "capture",
                    "kamera",
                    "webcam",
                    "putar",
                    "play",
                    "setel",
                    "nyalakan",
                    "lagu",
                    "musik",
                    "music",
                    "song",
                    "youtube",
                    "yt",
                    "spotify",
                    "video",
                    "audio",
                    "suara",
                    "buka",
                    "open",
                    "launch",
                    "tonton",
                    "watch",
                    "volume",
                    "notifikasi",
                    "aplikasi",
                    "app",
                    "unduh",
                    "download",
                    "perintah",
                    "terminal",
                    "kirim",
                ]
            )

            if is_simple_chat and not has_action_trigger:
                tools_schema = []
            else:
                tools_schema = build_openai_tools()
                # TOOL-RAG: suntikkan hanya tool relevan (hemat token, cegah confusion)
                try:
                    from alfa.tools.rag import select_relevant_tools

                    tools_schema = select_relevant_tools(
                        tools_schema, user_text, history=history
                    )
                except Exception:
                    pass  # fail-open: set lengkap

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_instruction}
        ]
        for h in (history or [])[-10:]:
            role = "assistant" if h.get("role") == "model" else "user"
            if h.get("content"):
                messages.append({"role": role, "content": h["content"]})
        messages.append({"role": "user", "content": user_text})

        url = f"{(base_url or '').rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload_base = {
            "model": model,
            "messages": messages,
            "temperature": 0.75,
            "stream": False,
        }

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(timeout, connect=15.0)
        ) as client:
            convo = list(messages)
            for _iteration in range(MAX_ITERATIONS):
                _compact_convo(convo)
                payload = dict(payload_base, messages=convo)
                if tools_schema:
                    payload["tools"] = tools_schema
                res = await client.post(url, headers=headers, json=payload)
                if res.status_code != 200:
                    err_text = res.text[:300]
                    logger.error(
                        f"[MainBrain:{provider}] HTTP {res.status_code}: {err_text}"
                    )
                    if raw_errors:
                        return None  # pemanggil swarm: teruskan ke fallback provider
                    if res.status_code == 402:
                        return (
                            f"⚠️ **Gagal memanggil `{model}` via {provider.upper()} (HTTP 402: Saldo / Credit Habis).**\n\n"
                            f"Kredit di akun {provider.upper()} kamu kosong/tidak mencukupi untuk menjalankan model ini. "
                            f"Silakan top up kredit di dashboard provider atau beralih ke model Gemini / model gratis di menu dropdown."
                        )
                    if res.status_code == 404:
                        return (
                            f"⚠️ **Model `{model}` tidak ditemukan di gateway {provider.upper()} (HTTP 404).**\n\n"
                            f"Silakan gunakan model lain yang aktif di daftar dropdown pemilih model."
                        )
                    if res.status_code == 429:
                        return (
                            f"⚠️ **Rate Limit Terlampaui ({provider.upper()} HTTP 429).**\n\n"
                            f"Batas kuota/request per menit untuk model ini telah tercapai. Coba beberapa saat lagi."
                        )
                    return None
                data = res.json()
                token_usage.from_openai_json(
                    data,
                    provider=provider,
                    model=model,
                    key_id=key_id,
                    key_label=key_label,
                    context=context,
                )
                msg = data["choices"][0]["message"]
                tool_calls = msg.get("tool_calls")

                if not tool_calls:
                    content = (msg.get("content") or "").strip()
                    return content or "(provider tidak mengirim teks)"

                convo.append(
                    {
                        "role": "assistant",
                        "content": msg.get("content") or "",
                        "tool_calls": tool_calls,
                    }
                )
                for tc in tool_calls:
                    fn = tc.get("function", {})
                    name = fn.get("name", "")
                    raw_args = fn.get("arguments", "{}")
                    out = None
                    if approval_gate is not None:
                        try:
                            denial = await approval_gate(name, raw_args)
                            if denial:
                                out = denial
                        except Exception as gate_err:
                            logger.warning(f"[Gate] error (fail-open): {gate_err!r}")
                    if out is None:
                        out = _execute_tool(name, raw_args)
                    logger.info(f"[MainBrain] tool {name} -> {out[:80]}")
                    convo.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.get("id", ""),
                            "content": out,
                        }
                    )

            # Batas iterasi tercapai: jangan buang seluruh progres.
            # Minta ringkasan akhir TANPA tools agar hasil tetap berguna.
            logger.warning(
                f"[MainBrain] batas {MAX_ITERATIONS} iterasi tercapai -> minta wrap-up."
            )
            convo.append(
                {
                    "role": "user",
                    "content": (
                        "[SISTEM] Batas putaran tool tercapai. STOP memanggil tool. "
                        "Ringkas apa yang SUDAH berhasil dikerjakan, hasil/data penting "
                        "yang sudah didapat, dan langkah tersisa yang perlu "
                        "dilanjutkan di giliran berikutnya."
                    ),
                }
            )
            try:
                wrap_payload = dict(payload_base, messages=_compact_convo(convo))
                res2 = await client.post(url, headers=headers, json=wrap_payload)
                if res2.status_code == 200:
                    token_usage.from_openai_json(
                        res2.json(),
                        provider=provider,
                        model=model,
                        key_id=key_id,
                        key_label=key_label,
                        context=f"{context}:wrapup",
                    )
                    wrap = (
                        res2.json()
                        .get("choices", [{}])[0]
                        .get("message", {})
                        .get("content")
                        or ""
                    ).strip()
                    if wrap:
                        return (
                            f"⏳ *Progres parsial (batas iterasi tercapai):*\n\n{wrap}"
                        )
            except Exception as wrap_err:
                logger.warning(f"[MainBrain] wrap-up gagal: {wrap_err!r}")
            return None
    except Exception as e:
        logger.error(f"[MainBrain:{provider}] error: {e!r}")
        return None


async def run_openai_agentic_turn_streaming(
    provider: str,
    base_url: str,
    api_key: str,
    model: str,
    system_instruction: str,
    user_text: str,
    history: list[dict[str, str]] | None = None,
    key_id=None,
    key_label: str = "",
    context: str = "telegram_chat",
    tools_schema: list[dict[str, Any]] | None = None,
    approval_gate=None,
):
    try:
        import httpx

        from alfa.core.brain.config import MAX_ITERATIONS
        from alfa.core.brain.convo import _compact_convo
        from alfa.core.brain.tool_exec import _execute_tool
        from alfa.core.brain.tool_schema import build_openai_tools

        logger = logging.getLogger("MainBrain")

        if tools_schema is None:
            txt_low = (user_text or "").lower().strip()
            pure_greetings = {
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
                "siap bos",
                "mantap",
                "sip",
                "yoi",
            }
            is_simple_chat = txt_low in pure_greetings
            has_action_trigger = any(
                k in txt_low
                for k in [
                    "buat",
                    "bikin",
                    "tulis",
                    "cari",
                    "search",
                    "googling",
                    "browse",
                    "web",
                    "scrape",
                    "jalankan",
                    "run",
                    "eksekusi",
                    "hitung",
                    "baca",
                    "cek",
                    "analisis",
                    "pdf",
                    "excel",
                    "gambar",
                    "foto",
                    "drive",
                    "email",
                    "rapat",
                    "meeting",
                    "jadwal",
                    "ingat",
                    "catat",
                    "simpan",
                    "hapus",
                    "file",
                    "folder",
                    "kode",
                    "code",
                    "python",
                    "bash",
                    "curl",
                    "swarm",
                    "screenshot",
                    "screnshoot",
                    "ss",
                    "layar",
                    "desktop",
                    "tangkap",
                    "capture",
                    "kamera",
                    "webcam",
                    "putar",
                    "play",
                    "setel",
                    "nyalakan",
                    "lagu",
                    "musik",
                    "music",
                    "song",
                    "youtube",
                    "yt",
                    "spotify",
                    "video",
                    "audio",
                    "suara",
                    "buka",
                    "open",
                    "launch",
                    "tonton",
                    "watch",
                    "volume",
                    "notifikasi",
                    "aplikasi",
                    "app",
                    "unduh",
                    "download",
                    "perintah",
                    "terminal",
                    "kirim",
                ]
            )
            if is_simple_chat and not has_action_trigger:
                tools_schema = []
            else:
                tools_schema = build_openai_tools()
                try:
                    from alfa.tools.rag import select_relevant_tools

                    tools_schema = select_relevant_tools(
                        tools_schema, user_text, history=history
                    )
                except Exception:
                    pass

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_instruction}
        ]
        for h in (history or [])[-10:]:
            role = "assistant" if h.get("role") == "model" else "user"
            if h.get("content"):
                messages.append({"role": role, "content": h["content"]})
        messages.append({"role": "user", "content": user_text})

        url = f"{(base_url or '').rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload_base = {
            "model": model,
            "messages": messages,
            "temperature": 0.75,
            "stream": True,
        }

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(180.0, connect=15.0)
        ) as client:
            convo = list(messages)
            for _iteration in range(MAX_ITERATIONS):
                _compact_convo(convo)
                payload = dict(payload_base, messages=convo)
                if tools_schema:
                    payload["tools"] = tools_schema

                try:
                    async with client.stream(
                        "POST", url, headers=headers, json=payload
                    ) as res:
                        if res.status_code != 200:
                            err_bytes = await res.aread()
                            err_text = err_bytes.decode("utf-8", errors="ignore")[:300]
                            logger.error(
                                f"[MainBrain:{provider}] HTTP {res.status_code}: {err_text}"
                            )
                            # fallback if streaming completely fails at connection
                            raise Exception(f"HTTP {res.status_code}")

                        current_text = ""
                        tool_calls_buffer = {}

                        async for line in res.aiter_lines():
                            if line.startswith("data: "):
                                data_str = line[6:].strip()
                                if data_str == "[DONE]":
                                    break
                                try:
                                    chunk = json.loads(data_str)
                                    if not chunk.get("choices"):
                                        continue
                                    delta = chunk["choices"][0].get("delta", {})

                                    if delta.get("content"):
                                        chunk_text = delta["content"]
                                        current_text += chunk_text
                                        yield chunk_text

                                    if "tool_calls" in delta:
                                        for tc in delta["tool_calls"]:
                                            idx = tc["index"]
                                            if idx not in tool_calls_buffer:
                                                tool_calls_buffer[idx] = {
                                                    "id": tc.get("id", ""),
                                                    "type": "function",
                                                    "function": {
                                                        "name": tc.get(
                                                            "function", {}
                                                        ).get("name", ""),
                                                        "arguments": "",
                                                    },
                                                }
                                            if (
                                                "function" in tc
                                                and "arguments" in tc["function"]
                                            ):
                                                tool_calls_buffer[idx]["function"][
                                                    "arguments"
                                                ] += tc["function"]["arguments"]
                                            if tc.get("id"):
                                                tool_calls_buffer[idx]["id"] = tc["id"]
                                except Exception:
                                    pass

                except Exception as stream_err:
                    logger.warning(
                        f"[MainBrain] streaming err: {stream_err!r}, falling back to non-streaming"
                    )
                    # Fallback to non-streaming
                    from alfa.core.brain.agentic import run_openai_agentic_turn

                    fallback_res = await run_openai_agentic_turn(
                        provider,
                        base_url,
                        api_key,
                        model,
                        system_instruction,
                        user_text,
                        history,
                        key_id,
                        key_label,
                        context,
                        tools_schema,
                        approval_gate,
                    )
                    if fallback_res:
                        yield fallback_res
                    return

                # After stream finishes, check if we had tool calls
                if not tool_calls_buffer:
                    if not current_text.strip():
                        yield "(provider tidak mengirim teks)"
                    return  # Done

                tool_calls = list(tool_calls_buffer.values())
                convo.append(
                    {
                        "role": "assistant",
                        "content": current_text,
                        "tool_calls": tool_calls,
                    }
                )

                for tc in tool_calls:
                    fn = tc.get("function", {})
                    name = fn.get("name", "")
                    raw_args = fn.get("arguments", "{}")
                    out = None
                    if approval_gate is not None:
                        try:
                            denial = await approval_gate(name, raw_args)
                            if denial:
                                out = denial
                        except Exception as gate_err:
                            logger.warning(f"[Gate] error (fail-open): {gate_err!r}")
                    if out is None:
                        out = _execute_tool(name, raw_args)
                    logger.info(f"[MainBrain] tool {name} -> {str(out)[:80]}")
                    convo.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.get("id", ""),
                            "content": out,
                        }
                    )

            # max iterations
            logger.warning(
                f"[MainBrain] batas {MAX_ITERATIONS} iterasi tercapai -> minta wrap-up."
            )
            convo.append(
                {
                    "role": "user",
                    "content": "[SISTEM] Batas putaran tool tercapai. STOP memanggil tool. Ringkas apa yang SUDAH berhasil dikerjakan, hasil/data penting yang sudah didapat, dan langkah tersisa yang perlu dilanjutkan di giliran berikutnya.",
                }
            )

            try:
                payload_wrap = dict(
                    payload_base, messages=_compact_convo(convo), stream=True
                )
                async with client.stream(
                    "POST", url, headers=headers, json=payload_wrap
                ) as res2:
                    if res2.status_code == 200:
                        yield "\n\n⏳ *Progres parsial (batas iterasi tercapai):*\n\n"
                        async for line in res2.aiter_lines():
                            if line.startswith("data: "):
                                data_str = line[6:].strip()
                                if data_str == "[DONE]":
                                    break
                                try:
                                    chunk = json.loads(data_str)
                                    delta = chunk["choices"][0].get("delta", {})
                                    if delta.get("content"):
                                        yield delta["content"]
                                except Exception:
                                    pass
            except Exception as wrap_err:
                logger.warning(f"[MainBrain] wrap-up gagal: {wrap_err!r}")
            return

    except Exception as e:
        logger.error(f"[MainBrain:{provider}] streaming error: {e!r}")
        # fallback
        from alfa.core.brain.agentic import run_openai_agentic_turn

        fallback_res = await run_openai_agentic_turn(
            provider,
            base_url,
            api_key,
            model,
            system_instruction,
            user_text,
            history,
            key_id,
            key_label,
            context,
            tools_schema,
            approval_gate,
        )
        if fallback_res:
            yield fallback_res
