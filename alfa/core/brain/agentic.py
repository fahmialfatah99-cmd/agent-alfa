"""OpenAI-compatible agentic turn loop with tool calls and wrap-up."""

import asyncio
import json
import logging
from typing import Any

from alfa.core.brain.config import MAX_ITERATIONS, TOOL_EXEC_TIMEOUT
from alfa.core.brain.convo import _compact_convo
from alfa.core.brain.tool_exec import _execute_tool
from alfa.core.brain.tool_schema import build_openai_tools

logger = logging.getLogger("MainBrain")

# Pesan penolakan ketika tool dipanggil tanpa approval gate yang tersambung.
# Deny-by-default: pemanggil WAJIB menyambungkan gate (interaktif Telegram,
# headless policy dashboard, atau ALLOW_ALL_GATE saat operator mematikan gate).
# Tanpa ini, tool apa pun bisa dieksekusi tanpa human-in-the-loop.
_NO_GATE_DENIAL = (
    "[DITOLAK] Tool '{name}' tidak dieksekusi karena tidak ada permission gate "
    "yang tersambung pada jalur ini (deny-by-default). Minta persetujuan "
    "pemilik, atau jalankan lewat jalur yang menyambungkan gate."
)


async def _resolve_tool_outcome(
    approval_gate,
    name: str,
    raw_args: str,
) -> str:
    """Jalankan gate untuk satu tool call; kembalikan output tool.

    Fail-CLOSED: bila gate melempar error, tool TIDAK dieksekusi. Bila gate
    tidak tersambung (None), tool juga ditolak.
    """
    if approval_gate is None:
        logger.error(
            "[MainBrain] tool %s ditolak: approval_gate tidak tersambung "
            "(deny-by-default).",
            name,
        )
        return _NO_GATE_DENIAL.format(name=name)
    try:
        denial = await approval_gate(name, raw_args)
    except Exception as gate_err:  # noqa: BLE001 - fail-closed on gate failure
        logger.exception(
            "[MainBrain] tool %s ditolak: permission gate error (fail-closed)",
            name,
        )
        return (
            f"[DITOLAK] Tool '{name}' tidak dieksekusi karena permission gate "
            f"gagal ({gate_err}). Percobaan ulang tidak akan dicoba otomatis."
        )
    if denial:
        return str(denial)
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(_execute_tool, name, raw_args),
            timeout=TOOL_EXEC_TIMEOUT + 5,
        )
    except (asyncio.TimeoutError, TimeoutError):
        return (
            f"[ERROR timeout] Tool '{name}' melebihi batas waktu eksekusi "
            f"({TOOL_EXEC_TIMEOUT} detik) dan dibatalkan."
        )
    return str(result)


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
    None = TIDAK BOLEH menjalankan tool (deny-by-default), str = tolak dan
    pakai teks itu sbg hasil tool. Gate yang melempar error juga menolak
    (fail-closed).
    Return teks jawaban, atau None bila gagal total (pemanggil bisa fallback).
    """
    try:
        import httpx

        from alfa.core import token_usage
        from alfa.core.rate_limiter import check_rate_limit
        from alfa.core.runtime_ctx import get_current_user_id

        # Rate limit HARUS di-enforce, bukan hanya di-log. Sebelumnya
        # `allowed` diabaikan sehingga kuota harian tidak pernah membatasi
        # apa pun. `user_id` diambil dari context runtime (user nyata),
        # bukan hardcode 1.
        _uid = get_current_user_id() or 0
        allowed, reason = check_rate_limit(user_id=_uid, provider=provider)
        if not allowed:
            logger.warning(f"[RateLimit] {provider} {model}: {reason}")
            return (
                f"⏳ *Kuota harian tercapai.*\n\n"
                f"Batas pemakaian untuk hari ini sudah habis ({reason}). "
                f"Coba lagi besok atau naikkan batasnya di Dashboard > Budget."
            )

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
                except (ImportError, ValueError, TypeError, KeyError):
                    pass  # fail-open: set lengkap

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_instruction}
        ]
        for h in (history or [])[-10:]:
            role = "assistant" if h.get("role") == "model" else "user"
            if h.get("content"):
                messages.append({"role": role, "content": h["content"]})
        messages.append({"role": "user", "content": user_text})

        prov = (provider or "").lower().strip()
        eff_base_url = (base_url or "").strip()
        if not eff_base_url:
            eff_base_url = {
                "openai": "https://api.openai.com/v1",
                "groq": "https://api.groq.com/openai/v1",
                "openrouter": "https://openrouter.ai/api/v1",
                "deepseek": "https://api.deepseek.com/v1",
                "nvidia": "https://integrate.api.nvidia.com/v1",
                "nim": "https://integrate.api.nvidia.com/v1",
                "minimax": "https://api.minimax.chat/v1",
                "moonshot": "https://api.moonshot.cn/v1",
                "kimi": "https://api.moonshot.cn/v1",
                "qwen": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
                "dashscope": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
                "9router": "http://127.0.0.1:20128/v1",
                "ollama": "http://localhost:11434/v1",
            }.get(prov, "")

        if not eff_base_url or not (api_key or "").strip():
            logger.warning(
                f"[MainBrain:{provider}] Base URL atau API key kosong untuk {provider} ({model}) -> batal"
            )
            return None

        url = f"{eff_base_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key.strip()}",
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
                from alfa.swarm.workspace_hygiene import _cancel_requested, current_session_id

                sess_id = current_session_id()
                if sess_id and _cancel_requested(sess_id):
                    logger.info(
                        f"[MainBrain] pembatalan terdeteksi sebelum tool call (iterasi {_iteration})"
                    )
                    return "⏹ Misi dihentikan atas permintaan pengguna (/cancel)."

                for tc in tool_calls:
                    fn = tc.get("function", {})
                    name = fn.get("name", "")
                    raw_args = fn.get("arguments", "{}")
                    out = await _resolve_tool_outcome(approval_gate, name, raw_args)
                    logger.info(f"[MainBrain] tool {name} -> {str(out)[:80]}")
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
            except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as wrap_err:
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
        from alfa.core.brain.tool_schema import build_openai_tools
        from alfa.core.rate_limiter import check_rate_limit
        from alfa.core.runtime_ctx import get_current_user_id

        logger = logging.getLogger("MainBrain")

        # Rate limit juga di-enforce pada jalur streaming (lihat fungsi
        # non-streaming untuk penjelasan).
        _uid = get_current_user_id() or 0
        allowed, reason = check_rate_limit(user_id=_uid, provider=provider)
        if not allowed:
            logger.warning(f"[RateLimit] {provider} {model}: {reason}")
            yield (
                f"⏳ *Kuota harian tercapai.*\n\n"
                f"Batas pemakaian untuk hari ini sudah habis ({reason}). "
                f"Coba lagi besok atau naikkan batasnya di Dashboard > Budget."
            )
            return

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
                except (ImportError, ValueError, TypeError, KeyError):
                    pass

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_instruction}
        ]
        for h in (history or [])[-10:]:
            role = "assistant" if h.get("role") == "model" else "user"
            if h.get("content"):
                messages.append({"role": role, "content": h["content"]})
        messages.append({"role": "user", "content": user_text})

        prov = (provider or "").lower().strip()
        eff_base_url = (base_url or "").strip()
        if not eff_base_url:
            eff_base_url = {
                "openai": "https://api.openai.com/v1",
                "groq": "https://api.groq.com/openai/v1",
                "openrouter": "https://openrouter.ai/api/v1",
                "deepseek": "https://api.deepseek.com/v1",
                "nvidia": "https://integrate.api.nvidia.com/v1",
                "nim": "https://integrate.api.nvidia.com/v1",
                "minimax": "https://api.minimax.chat/v1",
                "moonshot": "https://api.moonshot.cn/v1",
                "kimi": "https://api.moonshot.cn/v1",
                "qwen": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
                "dashscope": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
                "9router": "http://127.0.0.1:20128/v1",
                "ollama": "http://localhost:11434/v1",
            }.get(prov, "")

        if not eff_base_url or not (api_key or "").strip():
            logger.warning(
                f"[MainBrain:{provider}] Base URL atau API key kosong untuk {provider} ({model}) -> batal streaming"
            )
            return

        url = f"{eff_base_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key.strip()}",
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
                                except (ValueError, KeyError, IndexError, TypeError):
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

                from alfa.swarm.workspace_hygiene import _cancel_requested, current_session_id

                sess_id = current_session_id()
                if sess_id and _cancel_requested(sess_id):
                    logger.info(
                        "[MainBrain] pembatalan terdeteksi sebelum streaming tool call"
                    )
                    yield "⏹ Misi dihentikan atas permintaan pengguna (/cancel)."
                    return

                for tc in tool_calls:
                    fn = tc.get("function", {})
                    name = fn.get("name", "")
                    raw_args = fn.get("arguments", "{}")
                    out = await _resolve_tool_outcome(approval_gate, name, raw_args)
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
                                except (ValueError, KeyError, IndexError, TypeError):
                                    pass
            except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as wrap_err:
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
