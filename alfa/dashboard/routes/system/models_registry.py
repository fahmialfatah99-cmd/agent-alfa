"""Model registry endpoints (live discovery + raw-key validation)."""

import time
from typing import Any

from fastapi import APIRouter, HTTPException

from alfa.dashboard.routes.system.provider_catalog import PROVIDER_MODELS

router = APIRouter()


@router.get("/api/models")
async def get_available_models():
    """Get verified models list per provider with live discovery from NVIDIA & OpenRouter."""
    import httpx

    try:
        async with httpx.AsyncClient(timeout=2.5) as client:
            r = await client.get("https://integrate.api.nvidia.com/v1/models")
            if r.status_code == 200:
                live_data = r.json().get("data", [])
                existing_ids = {m["id"] for m in PROVIDER_MODELS["nvidia"]}
                for item in live_data:
                    mid = item.get("id")
                    if mid and mid not in existing_ids:
                        cat = "NVIDIA Live Models"
                        if "nemotron" in mid:
                            cat = "NVIDIA Nemotron Ultra"
                        elif "llama" in mid:
                            cat = "Meta Llama on NVIDIA"
                        elif "mistral" in mid:
                            cat = "Mistral on NVIDIA"
                        elif "deepseek" in mid:
                            cat = "DeepSeek on NVIDIA"
                        elif "google" in mid or "gemma" in mid:
                            cat = "Google on NVIDIA"

                        PROVIDER_MODELS["nvidia"].append(
                            {
                                "id": mid,
                                "name": f"{mid} (Live NVIDIA NIM)",
                                "category": cat,
                                "pricing": "free_credits",
                                "pricing_label": "🟢 GRATIS (1000 NIM Credits)",
                            }
                        )
    except Exception:
        pass

    try:
        async with httpx.AsyncClient(timeout=2.5) as client:
            r = await client.get("https://openrouter.ai/api/v1/models")
            if r.status_code == 200:
                live_or = r.json().get("data", [])
                existing_or_ids = {m["id"] for m in PROVIDER_MODELS["openrouter"]}
                for item in live_or:
                    mid = item.get("id")
                    mname = item.get("name", mid)
                    if mid and mid not in existing_or_ids:
                        is_free = ":free" in mid
                        PROVIDER_MODELS["openrouter"].append(
                            {
                                "id": mid,
                                "name": f"{mname} ({mid})",
                                "category": (
                                    "OpenRouter Free"
                                    if is_free
                                    else "OpenRouter Live Catalog"
                                ),
                                "pricing": "free" if is_free else "paid",
                                "pricing_label": (
                                    "🟢 100% GRATIS" if is_free else "💎 BERBAYAR"
                                ),
                            }
                        )
    except Exception:
        pass

    try:
        async with httpx.AsyncClient(timeout=1.5) as client:
            r = await client.get("http://127.0.0.1:20128/v1/models")
            if r.status_code == 200:
                live_9r = r.json().get("data", [])
                existing_9r_ids = {m["id"] for m in PROVIDER_MODELS.get("9router", [])}
                for item in live_9r:
                    mid = item.get("id")
                    if mid and mid not in existing_9r_ids:
                        PROVIDER_MODELS["9router"].append(
                            {
                                "id": mid,
                                "name": f"{mid} (via 9Router)",
                                "category": "9Router Live Catalog",
                                "pricing": "free_tier",
                                "pricing_label": "🟢 9ROUTER",
                            }
                        )
    except Exception:
        pass

    return {"status": "success", "providers": PROVIDER_MODELS}


@router.post("/api/keys/validate")
async def validate_raw_api_key(payload: dict[str, Any]):
    """Test ping connection for unsaved raw credentials before saving."""
    provider = payload.get("provider", "gemini")
    api_key = payload.get("api_key", "").strip()
    model = payload.get("model", "").strip()
    base_url = payload.get("base_url", "").strip()

    if not api_key:
        raise HTTPException(
            status_code=400, detail="API Key wajib diisi untuk divalidasi"
        )

    start_t = time.time()
    if provider in [
        "nvidia",
        "nim",
        "openai",
        "groq",
        "openrouter",
        "9router",
        "ollama",
        "deepseek",
        "minimax",
        "moonshot",
        "kimi",
        "qwen",
        "dashscope",
    ]:
        try:
            import httpx

            url = base_url
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

            target_model = model
            if not target_model:
                if provider in ["nvidia", "nim"]:
                    target_model = "nvidia/llama-3.1-nemotron-70b-instruct"
                elif provider == "deepseek":
                    target_model = "deepseek-chat"
                elif provider == "minimax":
                    target_model = "MiniMax-Text-01"
                elif provider in ["moonshot", "kimi"]:
                    target_model = "moonshot-v1-8k"
                elif provider in ["qwen", "dashscope"]:
                    target_model = "qwen-plus"
                elif provider == "groq":
                    target_model = "llama-3.3-70b-versatile"
                elif provider == "openrouter":
                    target_model = "deepseek/deepseek-r1:free"
                elif provider == "9router":
                    target_model = "all"
                else:
                    target_model = "gpt-4o"

            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }
            if provider == "openrouter":
                headers["HTTP-Referer"] = "https://alfa-agent.local"
                headers["X-Title"] = "ALFA Swarm Validator"

            test_payload = {
                "model": target_model,
                "messages": [{"role": "user", "content": "Tes koneksi. Jawab: OK"}],
                "max_tokens": 10,
                "stream": False,
            }
            async with httpx.AsyncClient(timeout=12.0) as client:
                res = await client.post(
                    f"{url.rstrip('/')}/chat/completions",
                    headers=headers,
                    json=test_payload,
                )
                duration_ms = round((time.time() - start_t) * 1000, 1)
                if res.status_code == 200:
                    return {
                        "status": "success",
                        "duration_ms": duration_ms,
                        "message": f"Koneksi {provider.upper()} ({target_model}) Berhasil ({duration_ms}ms)!",
                    }
                elif res.status_code == 404 and provider in ["nvidia", "nim"]:
                    return {
                        "status": "error",
                        "status_code": 404,
                        "duration_ms": duration_ms,
                        "message": f"Model '{target_model}' memerlukan izin khusus enterprise di NVIDIA NIM. Coba pilih model aktif 'nvidia/llama-3.1-nemotron-70b-instruct' atau 'meta/llama-3.3-70b-instruct' yang 100% aktif untuk akun Free NIM!",
                    }
                elif res.status_code == 401:
                    return {
                        "status": "error",
                        "status_code": 401,
                        "duration_ms": duration_ms,
                        "message": f"API Key {provider.upper()} tidak valid atau tidak memiliki izin akses (HTTP 401 Unauthorized).",
                    }
                else:
                    return {
                        "status": "error",
                        "status_code": res.status_code,
                        "duration_ms": duration_ms,
                        "message": f"HTTP {res.status_code}: {res.text[:200]}",
                    }
        except Exception as e:
            return {"status": "error", "message": f"Error: {str(e)}"}
    else:
        try:
            from google import genai
            from google.genai import types

            target_model = model or "gemini-3.6-flash"
            client = genai.Client(api_key=api_key)
            await client.aio.models.generate_content(
                model=target_model,
                contents="Tes koneksi",
                config=types.GenerateContentConfig(max_output_tokens=10),
            )
            duration_ms = round((time.time() - start_t) * 1000, 1)
            return {
                "status": "success",
                "duration_ms": duration_ms,
                "message": f"Koneksi GEMINI ({target_model}) Berhasil ({duration_ms}ms)!",
            }
        except Exception as e:
            return {"status": "error", "message": f"Error: {str(e)}"}
