"""
Multi-provider LLM Client & agent response generation for ALFA Swarm.
Supports Gemini (with automatic function calling) and OpenAI-compatible providers.
"""

import asyncio
import logging
import os
import sqlite3
import sys
from typing import Any

# LAZY (PEMROSESAN AWAL LAMBAT): `import google.genai` sendiri ≈1.0–1.5 s karena
# type-model raksasa `google.genai.types` — diimpor di sini di awal proses akan
# memperlambat setiap startup bot/dashboard/swarm worker. genai & types kini
# dibuat lewat `_ensure_genai()` saat pertama sebuah turn memanggil Gemini.
genai: Any = None
types: Any = None


def _ensure_genai() -> None:
    global genai, types
    if genai is None:
        import google.genai as _genai  # noqa: PLC0415 — lazy disengaja
        from google.genai import types as _types  # noqa: PLC0415 — lazy disengaja

        genai = _genai
        types = _types


from alfa.core import database, token_usage  # noqa: E402 — di bawah helper lazy

logger = logging.getLogger(__name__)

#: Tool yang boleh dijalankan agen swarm tanpa kanal approval manusia.
#:
#: Batas keamanan tool ini bukan "tidak ada" — melainkan:
#:   * ``execute_bash_command`` / ``execute_python_sandbox`` → sandbox Docker
#:     terisolasi (network none, cap-drop ALL, no-new-privileges, working_dir
#:     dibatasi ke root yang diizinkan) + blocklist perintah destruktif.
#:   * sisanya → read-only / write ringan.
#: Tool HIGH/CRITICAL di luar daftar ini (vault, ssh, crontab, hardware)
#: tetap DITOLAK pada jalur swarm karena tidak ada kanal persetujuan.
SWARM_HEADLESS_ALLOWED = {
    "execute_bash_command",
    "execute_python_sandbox",
    "apex_software_factory_build",
    "apex_repo_architect_build",
    "rea_clone_and_build_app",
    "rea_synthesize_skill_from_code",
    "apex_neuro_symbolic_verify",
    "apex_temporal_graphrag_query",
    "apex_system_telemetry",
    "apex_run_dreaming_consolidation",
    "serve_site",
    "list_managed_sites",
}


async def swarm_headless_gate(tool_name: str, arguments_json: str = "{}") -> str | None:
    """Gate headless untuk agen swarm (tidak ada kanal Telegram).

    Return None = boleh jalan; string = pesan penolakan.
    """
    from alfa.core.perm.gate import check_headless_approval

    if tool_name in SWARM_HEADLESS_ALLOWED:
        return None
    return check_headless_approval(None, tool_name, arguments_json)


def _filter_cooled_down_models(models: list[str]) -> list[str]:
    """Buang model yang sedang dalam masa pendinginan (circuit breaker)."""
    try:
        from alfa.core.brain.circuit_breaker import get_available_models

        return get_available_models(models)
    except (ImportError, AttributeError, TypeError):
        return models


def _mark_model_exhausted(model_name: str, error: BaseException | str) -> None:
    """Tandai model sebagai cooldown bila error menunjukkan kuota/masalah layanan."""
    try:
        from alfa.core.brain.circuit_breaker import (
            mark_model_exhausted,
            parse_retry_delay,
        )

        text = str(error)
        if not any(
            code in text
            for code in ("429", "RESOURCE_EXHAUSTED", "503", "UNAVAILABLE", "quota")
        ):
            return
        mark_model_exhausted(
            model_name, cooldown_seconds=parse_retry_delay(error), reason=text[:120]
        )
    except (ImportError, AttributeError, TypeError, ValueError):
        pass


KNOWN_OPENAI_PROVIDERS = {
    "openai",
    "groq",
    "openrouter",
    "9router",
    "ollama",
    "nvidia",
    "nim",
    "deepseek",
    "minimax",
    "moonshot",
    "kimi",
    "qwen",
    "dashscope",
}


def _default_gemini_model() -> str:
    """Model Gemini default yang SELALU hidup: ikut otak utama vault,
    lalu default kunci gemini aktif, terakhir generik terbaru."""
    try:
        m = (database.get_main_brain_model() or "").strip()
        if m:
            return m
    except (sqlite3.Error, TypeError, ValueError):
        pass
    try:
        k = database.get_active_api_key_sync("gemini")
        m = ((k or {}).get("default_model") or "").strip()
        if m:
            return m
    except (sqlite3.Error, TypeError, ValueError, AttributeError):
        pass
    return "gemini-flash-latest"


def get_agent_api_client(
    agent: dict[str, Any],
) -> tuple[str, str, str, str | None, int | None]:
    """Resolve (provider, api_key, model, base_url, key_id) for a specific agent."""
    provider = (agent.get("provider") or "gemini").lower()
    model = agent.get("model") or (
        _default_gemini_model() if provider == "gemini" else ""
    )
    api_key = ""
    base_url = ""
    key_id = None

    if agent.get("api_key_id"):
        with database.get_sync_db() as conn:
            row = conn.execute(
                "SELECT id, provider, api_key, default_model, base_url FROM api_keys WHERE id = ?",
                (agent["api_key_id"],),
            ).fetchone()
            if row:
                provider = row["provider"]
                api_key = database.decrypt_key(row["api_key"])
                base_url = row["base_url"] or ""
                key_id = row["id"]
                if not agent.get("model"):
                    model = row["default_model"]

    if not api_key:
        active_key = database.get_active_api_key_sync(provider)
        if active_key:
            api_key = active_key["api_key"]
            base_url = active_key.get("base_url") or ""
            key_id = active_key.get("id")
        if not api_key:
            if provider == "gemini":
                api_key = os.getenv("GEMINI_API_KEY", "")
            elif provider == "openai":
                api_key = os.getenv("OPENAI_API_KEY", "")
            elif provider == "groq":
                api_key = os.getenv("GROQ_API_KEY", "")
            elif provider in ["nvidia", "nim"]:
                api_key = os.getenv("NVIDIA_API_KEY", "")
            elif provider == "deepseek":
                api_key = os.getenv("DEEPSEEK_API_KEY", "")
            elif provider == "openrouter":
                api_key = os.getenv("OPENROUTER_API_KEY", "")
            elif provider == "minimax":
                api_key = os.getenv("MINIMAX_API_KEY", "")
            elif provider in ["moonshot", "kimi"]:
                api_key = os.getenv("MOONSHOT_API_KEY", "")
            elif provider in ["qwen", "dashscope"]:
                api_key = os.getenv("DASHSCOPE_API_KEY", os.getenv("QWEN_API_KEY", ""))
            elif provider == "9router":
                api_key = os.getenv("NINEROUTER_API_KEY", os.getenv("ROUTER_API_KEY", ""))

    if not base_url:
        base_url = {
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
        }.get(provider, "")

    if provider == "9router":
        if not base_url:
            base_url = "http://127.0.0.1:20128/v1"
        if not model:
            model = "all"
        if not api_key:
            try:
                import glob as _glob
                import sqlite3 as _sq

                db_paths = _glob.glob(
                    os.path.expanduser("~/.9router/db/data.sqlite")
                ) + _glob.glob(os.path.expandvars(r"%APPDATA%\9router\db\data.sqlite"))
                for dbp in db_paths:
                    if os.path.exists(dbp):
                        with _sq.connect(dbp) as _c:
                            rk = _c.execute(
                                "SELECT key FROM apiKeys WHERE isActive=1 LIMIT 1"
                            ).fetchone()
                            if rk and rk[0]:
                                api_key = rk[0]
                                break
            except (sqlite3.Error, OSError, TypeError, ValueError, IndexError):
                pass

    # Fallback otomatis bila provider spesifik agen belum memiliki kunci aktif di vault
    if not api_key:
        for fb_prov in ("9router", "gemini", "nvidia", "groq", "openrouter", "openai"):
            fb_key = database.get_active_api_key_sync(fb_prov)
            if fb_key and fb_key.get("api_key"):
                provider = fb_prov
                api_key = fb_key["api_key"]
                base_url = fb_key.get("base_url") or (
                    "http://127.0.0.1:20128/v1" if fb_prov == "9router" else ""
                )
                key_id = fb_key.get("id")
                model = fb_key.get("default_model") or (
                    "antigravity" if fb_prov == "9router" else _default_gemini_model()
                )
                break

    return provider, api_key, model, base_url, key_id


async def _generate_with_gemini(
    agent_name: str,
    api_key: str,
    models: list[str],
    prompt: str,
    final_instruction: str,
    key_id=None,
    key_label: str = "",
    context: str = "swarm",
    max_tokens: int = 500,
    thinking_budget: int | None = None,
    timeout_s: float = 180.0,
    tools: list[Any] | None = None,
) -> str | None:
    """Try a chain of Gemini models. Returns text or None if all fail."""
    default_chain = os.getenv(
        "GEMINI_FALLBACK_MODELS",
        "gemini-3.5-flash,gemini-flash-lite-latest,gemini-3-flash-preview",
    ).split(",")
    candidate_models = [m for m in models + [x.strip() for x in default_chain] if m]
    unique_models = list(dict.fromkeys(candidate_models))
    # Circuit breaker: model yang sedang cooldown (429/503) dilewati agar
    # swarm tidak wasting waktu & kuota untuk provider yang sudah mati.
    unique_models = _filter_cooled_down_models(unique_models)

    last_err: BaseException | None = None
    try:
        _ensure_genai()
        client = genai.Client(api_key=api_key)
    except Exception as client_err:
        logger.error(
            f"Failed to initialize Gemini client for agent '{agent_name}': {client_err!r}"
        )
        return None
    for m in unique_models:
        try:
            cfg_kw: dict[str, Any] = dict(
                system_instruction=final_instruction,
                # Gemini 3.x: None -> default server 1.0 (rekomendasi Google).
                temperature=(
                    None
                    if str(m).lower().removeprefix("models/").startswith("gemini-3")
                    else 0.7
                ),
                max_output_tokens=max_tokens,
            )
            if thinking_budget is not None:
                cfg_kw["thinking_config"] = types.ThinkingConfig(
                    thinking_budget=thinking_budget
                )
            if tools:
                cfg_kw["tools"] = list(tools)
            try:
                response = await asyncio.wait_for(
                    client.aio.models.generate_content(
                        model=m,
                        contents=prompt,
                        config=types.GenerateContentConfig(**cfg_kw),
                    ),
                    timeout=timeout_s,
                )
            except asyncio.TimeoutError:
                last_err = TimeoutError(
                    f"[gemini] HARD DEADLINE {timeout_s}s terlampaui untuk model '{m}'"
                )
                logger.warning(f"{last_err}. Trying next fallback...")
                continue
            if response and response.text:
                token_usage.from_gemini_response(
                    response,
                    model=m,
                    key_id=key_id,
                    key_label=key_label or f"agent:{agent_name}",
                    context=context,
                )
                return str(response.text).strip()
        except Exception as e:
            last_err = e
            _mark_model_exhausted(m, e)
            logger.warning(
                f"Model '{m}' failed for agent '{agent_name}': {e}. Trying next fallback..."
            )

    logger.error(f"All Gemini models failed for agent '{agent_name}': {last_err!r}")
    return None


async def _generate_with_openai_compat(
    agent_name: str,
    provider: str,
    api_key: str,
    model: str,
    base_url: str | None,
    prompt: str,
    final_instruction: str,
    key_id=None,
    key_label: str = "",
    context: str = "swarm",
    max_tokens: int = 500,
    timeout_s: float = 180.0,
    require_content: bool = False,
) -> str | None:
    """Call an OpenAI-compatible endpoint. Returns text or None on failure.

    require_content=True: konten reasoning-saja (tanpa content nyata) dianggap
    GAGAL (return None) agar rantai fallback provider tetap jalan — dipakai
    pemanggil yang butuh aksi tool, bukan teks hiasan.
    """
    try:
        import httpx

        url = base_url or ""
        if not url:
            if provider in ["nvidia", "nim"]:
                url = "https://integrate.api.nvidia.com/v1"
            elif provider == "deepseek":
                url = "https://api.deepseek.com/v1"
            elif provider == "minimax":
                url = "https://api.minimax.chat/v1"
            elif provider in ["moonshot", "kimi"]:
                url = "https://api.moonshot.cn/v1"
            elif provider in ["qwen", "dashscope"]:
                url = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
            elif provider == "openai":
                url = "https://api.openai.com/v1"
            elif provider == "groq":
                url = "https://api.groq.com/openai/v1"
            elif provider == "openrouter":
                url = "https://openrouter.ai/api/v1"
            elif provider == "9router":
                url = "http://127.0.0.1:20128/v1"
            elif provider == "ollama":
                url = "http://localhost:11434/v1"

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        if provider == "openrouter":
            headers["HTTP-Referer"] = "https://alfa-agent.local"
            headers["X-Title"] = "ALFA Sovereign Agent"

        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": final_instruction},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.7,
            "max_tokens": max_tokens,
            "stream": False,
        }

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_s, connect=10.0)
        ) as http_client:
            try:
                res = await asyncio.wait_for(
                    http_client.post(
                        f"{url.rstrip('/')}/chat/completions",
                        headers=headers,
                        json=payload,
                    ),
                    timeout=timeout_s,
                )
            except asyncio.TimeoutError:
                logger.error(
                    f"[{provider}] HARD DEADLINE {timeout_s}s terlampaui untuk "
                    f"'{agent_name}' (respons menetes?) - batal & lanjut fallback."
                )
                return None
            if res.status_code == 200:
                try:
                    data = res.json()
                    token_usage.from_openai_json(
                        data,
                        provider=provider,
                        model=model,
                        key_id=key_id,
                        key_label=key_label or f"agent:{agent_name}",
                        context=context,
                    )
                    msg0 = (data.get("choices") or [{}])[0].get("message") or {}
                    content = (msg0.get("content") or "").strip()
                    if not content:
                        reason_only = (
                            msg0.get("reasoning_content") or msg0.get("reasoning") or ""
                        ).strip()
                        if reason_only and not require_content:
                            logger.warning(
                                f"[{provider}] content kosong, fallback reasoning ({len(reason_only)} char)"
                            )
                            return reason_only
                        logger.warning(
                            f"[{provider}] content kosong untuk '{agent_name}' "
                            f"(reasoning {len(reason_only)} char diabaikan) -> fallback provider."
                        )
                        return None
                    if content:
                        return content
                except (ValueError, KeyError, IndexError, TypeError, AttributeError) as parse_err:
                    logger.warning(
                        f"[{provider}] JSON parse fallback ({parse_err!r}) -> mencoba parsing SSE chunks"
                    )
                    content_parts = []
                    for line in res.text.splitlines():
                        line_str = line.strip()
                        if line_str.startswith("data: ") and line_str != "data: [DONE]":
                            try:
                                import json as _json

                                chunk = _json.loads(line_str[6:].strip())
                                delta = (chunk.get("choices") or [{}])[0].get(
                                    "delta", {}
                                )
                                c = (
                                    delta.get("content")
                                    or delta.get("reasoning_content")
                                    or ""
                                )
                                if c:
                                    content_parts.append(c)
                            except (ValueError, KeyError, IndexError, TypeError, AttributeError):
                                pass
                    if content_parts:
                        return "".join(content_parts).strip()
                return None

            if res.status_code == 402:
                import re as _re

                m_afford = _re.search(r"can only afford (\d+)", res.text)
                if m_afford:
                    afford = max(256, int(m_afford.group(1)) - 128)
                    payload["max_tokens"] = afford
                    logger.warning(
                        f"[{provider}] kuota terbatas - retry dengan max_tokens={afford}"
                    )
                    try:
                        res = await http_client.post(
                            f"{url.rstrip('/')}/chat/completions",
                            headers=headers,
                            json=payload,
                        )
                    except (httpx.HTTPError, ValueError, TypeError) as retry_err:
                        logger.error(
                            f"[{provider}] retry 402 gagal: {type(retry_err).__name__}: {retry_err}"
                        )
                        return None
                    if res.status_code == 200:
                        data = res.json()
                        token_usage.from_openai_json(
                            data,
                            provider=provider,
                            model=model,
                            key_id=key_id,
                            key_label=key_label,
                            context=context,
                        )
                        msg0 = (data.get("choices") or [{}])[0].get("message") or {}
                        content = (msg0.get("content") or "").strip()
                        if content:
                            return content
                    else:
                        logger.error(
                            f"[{provider}] retry 402 tetap gagal HTTP {res.status_code}"
                        )
                err_detail = res.text[:200] or "(empty body)"
                logger.error(
                    f"{provider} HTTP {res.status_code} for agent '{agent_name}' (model={model}): {err_detail}"
                )
                return None

            if res.status_code == 429:
                retry_after_str = res.headers.get("Retry-After", "2")
                try:
                    delay = min(max(float(retry_after_str), 1.0), 5.0)
                except ValueError:
                    delay = 2.0
                logger.warning(
                    f"[{provider}] HTTP 429 Rate Limit for '{agent_name}'. Backing off {delay}s..."
                )
                await asyncio.sleep(delay)
                try:
                    res = await http_client.post(
                        f"{url.rstrip('/')}/chat/completions",
                        headers=headers,
                        json=payload,
                    )
                    if res.status_code == 200:
                        data = res.json()
                        token_usage.from_openai_json(
                            data,
                            provider=provider,
                            model=model,
                            key_id=key_id,
                            key_label=key_label,
                            context=context,
                        )
                        msg0 = (data.get("choices") or [{}])[0].get("message") or {}
                        content = (msg0.get("content") or "").strip()
                        if content:
                            return content
                except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as retry_err:
                    logger.error(f"[{provider}] retry 429 failed: {retry_err}")

            err_detail = res.text[:200] or "(empty body)"
            # Circuit breaker: 429/503 → model diberi masa pendinginan
            # supaya langkah swarm berikutnya tidak mencoba provider mati.
            _mark_model_exhausted(
                model, f"HTTP {res.status_code}: {err_detail}"
            )
            logger.error(
                f"{provider} HTTP {res.status_code} for agent '{agent_name}' (model={model}): {err_detail}"
            )
            return None
    except Exception as e:
        _mark_model_exhausted(model, e)
        logger.error(f"Error in {provider} agent '{agent_name}': {e!r}")
        return None


async def generate_agent_response(
    agent: dict[str, Any],
    prompt: str,
    system_instruction: str,
    max_tokens: int | None = None,
    timeout_s: float = 180.0,
    thinking_budget: int | None = None,
) -> str | None:
    """Generate response for a specific agent using its configured provider and key."""
    # Check if patched on swarm_engine or alfa.swarm.engine
    for mod_name in ("swarm_engine", "alfa.swarm.engine"):
        mod = sys.modules.get(mod_name)
        if mod and hasattr(mod, "generate_agent_response"):
            fn = mod.generate_agent_response
            if fn is not generate_agent_response and callable(fn):
                res: str | None = await fn(
                    agent=agent,
                    prompt=prompt,
                    system_instruction=system_instruction,
                    max_tokens=max_tokens,
                    timeout_s=timeout_s,
                    thinking_budget=thinking_budget,
                )
                return res

    provider, api_key, model, base_url, key_id = get_agent_api_client(agent)
    agent_name = agent.get("name", "Agent")
    enable_tools = bool(agent.get("enable_tools"))
    eff_max_tokens = max_tokens or (4000 if enable_tools else 500)

    tone_directive = (
        "\n\n[PANDUAN OUTPUT & GAYA BICARA]:"
        "\n1. BICARA SANTAI & GAUL: Gunakan gaya bahasa santai, luwes, natural ala software engineer/tech specialist di war room (jangan kaku, hindari basa-basi robot seperti 'Sebagai AI...', 'Tentu saja...')."
        "\n2. ON-POINT & REALISTIS: Langsung sebutkan fakta teknis nyata dan aksi nyata yang dilakukan tanpa bertele-tele. Maksimal 2-4 kalimat."
    )
    if enable_tools:
        final_instruction = (
            (system_instruction or "Kamu adalah engineer spesialis di AI Swarm.")
            + "\n\n[DISIPLIN EKSEKUSI]:\n"
            "1. Setiap giliran WAJIB memuat panggilan function call.\n"
            "2. Kerjakan sendiri lewat tool — jangan memberi instruksi ke orang lain.\n"
            "3. Sebelum melapor selesai, pastikan file benar-benar ditulis via tool."
            "\n\n[ATURAN JUJUR]: Akhiri dengan label SELESAI/SEBAGIAN/GAGAL sesuai bukti. "
            "Dilarang label neural/AI/teruji/production-ready/deployed tanpa bukti "
            "(hasil tes, file nyata, URL hidup). Dilarang dummy sebagai hasil asli."
        )
    else:
        final_instruction = (
            system_instruction or "Kamu adalah engineer spesialis di AI Swarm."
        ) + tone_directive

    key_label = f"agent:{agent_name}"

    cache_hit = None
    if not enable_tools:
        try:
            from alfa.core.brain import cache as _llm_cache

            cache_hit = _llm_cache.lookup_for(
                provider, model, system_instruction, prompt, eff_max_tokens
            )
            if cache_hit is not None:
                logger.debug(f"LLM cache hit untuk '{agent_name}' ({model})")
                return cache_hit
        except (ImportError, OSError, ValueError, TypeError):
            pass

    def gemini_like_tools() -> list[Any]:
        try:
            from alfa import tools as _t
            from alfa.core import brain as _mb

            return [
                getattr(_t, n)
                for n in sorted(_mb.SAFE_TOOL_NAMES)
                if hasattr(_t, n) and callable(getattr(_t, n))
            ]
        except (ImportError, AttributeError, TypeError):
            return []

    result = None
    if provider == "gemini":
        gemini_tools = None
        if enable_tools:
            gemini_tools = gemini_like_tools() or None
            try:
                from alfa import tools as _t
                from alfa.core import brain as _mb

                gemini_tools = [
                    getattr(_t, n)
                    for n in sorted(_mb.SAFE_TOOL_NAMES)
                    if hasattr(_t, n) and callable(getattr(_t, n))
                ]
            except (ImportError, AttributeError, TypeError) as tools_err:
                logger.warning(
                    f"Tools swarm utk '{agent_name}' gagal dimuat: {tools_err}"
                )
        result = await _generate_with_gemini(
            agent_name=agent_name,
            api_key=api_key or os.getenv("GEMINI_API_KEY", ""),
            models=[model],
            prompt=prompt,
            final_instruction=final_instruction,
            key_id=key_id,
            key_label=key_label,
            context="swarm",
            max_tokens=eff_max_tokens,
            timeout_s=timeout_s,
            thinking_budget=thinking_budget,
            tools=gemini_tools,
        )
    else:
        if enable_tools:
            if not api_key:
                logger.warning(
                    f"Agen ber-tool '{agent_name}' tidak punya API key untuk provider '{provider}' -> langsung fallback Gemini."
                )
                result = None
            else:
                try:
                    from alfa.core import brain as _mb

                    result = await _mb.run_openai_agentic_turn(
                        provider=provider,
                        base_url=base_url or "",
                        api_key=api_key,
                        model=model,
                        system_instruction=final_instruction,
                        user_text=prompt,
                        key_id=key_id,
                        key_label=key_label,
                        context="swarm",
                        tools_schema=_mb.build_openai_tools(safe_only=True),
                        # Tanpa gate, jalur swarm bisa menjalankan tool apa pun
                        # tanpa human-in-the-loop (deny-by-default di brain).
                        approval_gate=swarm_headless_gate,
                        raw_errors=True,
                    )
                except Exception as agentic_err:
                    logger.warning(f"Agentic turn '{agent_name}' error: {agentic_err!r}")
                    result = None
            if isinstance(result, str) and (
                result.startswith("(provider tidak mengirim teks)")
                or not result.strip()
            ):
                logger.warning(
                    f"Agentic turn '{agent_name}' balas kosong -> paksa fallback."
                )
                result = None
        if result is None:
            if not base_url and provider not in KNOWN_OPENAI_PROVIDERS:
                logger.warning(
                    f"Provider '{provider}' tanpa base_url untuk '{agent_name}' - "
                    "fallback ke Gemini."
                )
            result = await _generate_with_openai_compat(
                agent_name=agent_name,
                provider=provider,
                api_key=api_key,
                model=model,
                base_url=base_url,
                prompt=prompt,
                final_instruction=final_instruction,
                key_id=key_id,
                key_label=key_label,
                context="swarm",
                max_tokens=eff_max_tokens,
                timeout_s=timeout_s,
                require_content=enable_tools,
            )
        if result is None and enable_tools:
            try:
                gem_keys = [
                    k
                    for k in database.list_active_keys_sync()
                    if (k.get("provider") or "").lower() == "gemini"
                    and k.get("id") != key_id
                ]
            except (sqlite3.Error, TypeError, ValueError, AttributeError):
                gem_keys = []
            for gk in gem_keys:
                try:
                    logger.warning(
                        f"Agen ber-tool '{agent_name}' gagal via {provider} "
                        f"-> fallback Gemini agentic k#{gk.get('id')} (tools tetap aktif)."
                    )
                    gagent = {
                        "name": agent_name,
                        "provider": "gemini",
                        "model": (
                            gk.get("default_model") or "gemini-flash-latest"
                        ).strip(),
                        "api_key_id": gk.get("id"),
                        "enable_tools": 1,
                    }
                    result = await generate_agent_response(
                        gagent,
                        prompt,
                        "Kamu agen pelaksana swarm. KERJA MENGGUNAKAN TOOL: setiap "
                        "giliran WAJIB memuat panggilan function call "
                        "(write_local_file / edit_file_precise / execute_bash_command). "
                        "Membalas teks saja = GAGAL.",
                        max_tokens=eff_max_tokens,
                        timeout_s=timeout_s,
                        thinking_budget=thinking_budget,
                    )
                    if result is not None:
                        break
                except Exception as fb_err:
                    logger.warning(f"Gemini agentic fallback gagal: {fb_err!r}")

        if result is None and os.getenv("GEMINI_API_KEY"):
            logger.warning(
                f"Provider '{provider}' gagal untuk '{agent_name}' - fallback ke Gemini."
            )
            result = await _generate_with_gemini(
                agent_name=f"{agent_name} (fallback)",
                api_key=os.getenv("GEMINI_API_KEY", ""),
                models=["gemini-3.5-flash", "gemini-flash-lite-latest"],
                prompt=prompt,
                final_instruction=final_instruction,
                key_id=None,
                key_label="gemini-fallback",
                context="swarm",
                thinking_budget=thinking_budget,
            )

    if result is None:
        logger.error(
            f"[Swarm] '{agent_name}': semua provider & fallback gagal "
            f"(primary: {provider}) — langkah ini dilaporkan GAGAL."
        )
        return None
    if not enable_tools and isinstance(result, str):
        try:
            from alfa.core.brain import cache as _llm_cache

            _llm_cache.store_for(
                provider, model, system_instruction, prompt, result, eff_max_tokens
            )
        except (ImportError, OSError, ValueError, TypeError):
            pass
    return result
