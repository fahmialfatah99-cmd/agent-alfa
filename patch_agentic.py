import json
import logging
from typing import Any


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
            pure_greetings = {"halo", "hai", "hei", "pagi", "siang", "sore", "malam", "selamat pagi", "selamat siang", "selamat sore", "selamat malam", "apa kabar", "siapa kamu", "tes", "ping", "test", "makasih", "terima kasih", "thanks", "thank you", "ok", "oke", "siap", "siap bos", "mantap", "sip", "yoi"}
            is_simple_chat = txt_low in pure_greetings
            has_action_trigger = any(k in txt_low for k in ["buat", "bikin", "tulis", "cari", "search", "googling", "browse", "web", "scrape", "jalankan", "run", "eksekusi", "hitung", "baca", "cek", "analisis", "pdf", "excel", "gambar", "foto", "drive", "email", "rapat", "meeting", "jadwal", "ingat", "catat", "simpan", "hapus", "file", "folder", "kode", "code", "python", "bash", "curl", "swarm", "screenshot", "screnshoot", "ss", "layar", "desktop", "tangkap", "capture", "kamera", "webcam", "putar", "play", "setel", "nyalakan", "lagu", "musik", "music", "song", "youtube", "yt", "spotify", "video", "audio", "suara", "buka", "open", "launch", "tonton", "watch", "volume", "notifikasi", "aplikasi", "app", "unduh", "download", "perintah", "terminal", "kirim"])
            if is_simple_chat and not has_action_trigger:
                tools_schema = []
            else:
                tools_schema = build_openai_tools()
                try:
                    from alfa.tools.rag import select_relevant_tools
                    tools_schema = select_relevant_tools(tools_schema, user_text, history=history)
                except Exception:
                    pass

        messages: list[dict[str, Any]] = [{"role": "system", "content": system_instruction}]
        for h in (history or [])[-10:]:
            role = "assistant" if h.get("role") == "model" else "user"
            if h.get("content"):
                messages.append({"role": role, "content": h["content"]})
        messages.append({"role": "user", "content": user_text})

        url = f"{(base_url or '').rstrip('/')}/chat/completions"
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        payload_base = {"model": model, "messages": messages, "temperature": 0.75, "stream": True}

        async with httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=15.0)) as client:
            convo = list(messages)
            for _iteration in range(MAX_ITERATIONS):
                _compact_convo(convo)
                payload = dict(payload_base, messages=convo)
                if tools_schema:
                    payload["tools"] = tools_schema

                try:
                    async with client.stream("POST", url, headers=headers, json=payload) as res:
                        if res.status_code != 200:
                            err_text = await res.aread()
                            err_text = err_text.decode('utf-8', errors='ignore')[:300]
                            logger.error(f"[MainBrain:{provider}] HTTP {res.status_code}: {err_text}")
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
                                                    "function": {"name": tc.get("function", {}).get("name", ""), "arguments": ""}
                                                }
                                            if "function" in tc and "arguments" in tc["function"]:
                                                tool_calls_buffer[idx]["function"]["arguments"] += tc["function"]["arguments"]
                                            if tc.get("id"):
                                                tool_calls_buffer[idx]["id"] = tc["id"]
                                except Exception:
                                    pass

                except Exception as stream_err:
                    logger.warning(f"[MainBrain] streaming err: {stream_err!r}, falling back to non-streaming")
                    # Fallback to non-streaming
                    from alfa.core.brain.agentic import run_openai_agentic_turn
                    fallback_res = await run_openai_agentic_turn(provider, base_url, api_key, model, system_instruction, user_text, history, key_id, key_label, context, tools_schema, approval_gate)
                    if fallback_res:
                        yield fallback_res
                    return

                # After stream finishes, check if we had tool calls
                if not tool_calls_buffer:
                    if not current_text.strip():
                        yield "(provider tidak mengirim teks)"
                    return # Done

                tool_calls = list(tool_calls_buffer.values())
                convo.append({
                    "role": "assistant",
                    "content": current_text,
                    "tool_calls": tool_calls,
                })

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
                    convo.append({
                        "role": "tool",
                        "tool_call_id": tc.get("id", ""),
                        "content": out,
                    })

            # max iterations
            logger.warning(f"[MainBrain] batas {MAX_ITERATIONS} iterasi tercapai -> minta wrap-up.")
            convo.append({
                "role": "user",
                "content": "[SISTEM] Batas putaran tool tercapai. STOP memanggil tool. Ringkas apa yang SUDAH berhasil dikerjakan, hasil/data penting yang sudah didapat, dan langkah tersisa yang perlu dilanjutkan di giliran berikutnya."
            })

            try:
                payload_wrap = dict(payload_base, messages=_compact_convo(convo), stream=True)
                async with client.stream("POST", url, headers=headers, json=payload_wrap) as res2:
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
        fallback_res = await run_openai_agentic_turn(provider, base_url, api_key, model, system_instruction, user_text, history, key_id, key_label, context, tools_schema, approval_gate)
        if fallback_res:
            yield fallback_res
