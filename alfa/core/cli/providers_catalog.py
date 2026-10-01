"""Provider catalog data, normalization, and live-sync for DirectAI."""

from __future__ import annotations

import os
from typing import Any

import requests


def normalize_provider(name: str | None) -> str:
    """Normalize provider aliases to match canonical names."""
    if not name:
        return "google"
    p = name.strip().lower()
    if p in ("nim", "nvidia_nim"):
        return "nvidia"
    if p in ("gemini", "google_gemini"):
        return "google"
    if p in ("dashscope", "alibaba"):
        return "qwen"
    if p in ("kimi", "moonshotai"):
        return "moonshot"
    if p in ("9r", "router", "ninerouter"):
        return "9router"
    if p in ("agy",):
        return "antigravity"
    return p
PROVIDERS_CATALOG: dict[str, Any] = {
    "9router": {
        "name": "9Router AI Gateway (Local)",
        "models": [
            "ag/gemini-3.8-flash",
            "ag/gemini-3.7-flash",
            "ag/gemini-3.6-flash",
            "ag/claude-sonnet-4-6",
            "ag/claude-opus-4-6-thinking",
            "ag/gpt-oss-120b-medium",
            "gemini/gemini-3.8-flash",
            "gemini/gemini-3.7-flash",
            "gemini/gemini-3.6-flash",
            "nvidia/deepseek-ai/deepseek-v4-pro",
            "nvidia/deepseek-ai/deepseek-v4-flash",
            "nvidia/moonshotai/kimi-k2.6",
            "nvidia/nemotron-3-ultra-550b-a55b",
            "gratisan",
            "antigravity",
            "all",
        ],
        "env_keys": ["NINEROUTER_API_KEY", "ROUTER_API_KEY", "ROUTER_KEY"],
        "default_model": "ag/gemini-3.8-flash",
        "default_url": "http://127.0.0.1:20128/v1",
    },
    "google": {
        "name": "Google Gemini",
        "models": [
            "gemini-3.8-flash",
            "gemini-3.8-pro",
            "gemini-3.8-flash-lite",
            "gemini-3.7-flash",
            "gemini-3.6-flash",
            "gemini-3.1-pro-preview",
            "gemini-3.1-flash-lite",
            "gemini-omni-flash-preview",
            "gemini-flash-latest",
            "gemini-pro-latest",
        ],
        "env_keys": ["GEMINI_API_KEY", "GOOGLE_API_KEY"],
        "default_model": os.getenv("GEMINI_MODEL", "gemini-3.8-flash"),
        "default_url": "https://generativelanguage.googleapis.com/v1beta",
    },
    "nvidia": {
        "name": "NVIDIA NIM",
        "models": [
            "nvidia/llama-3.1-nemotron-70b-instruct",
            "meta/llama-3.3-70b-instruct",
            "deepseek-ai/deepseek-r1",
            "deepseek-ai/deepseek-v3",
            "qwen/qwen2.5-coder-32b-instruct",
            "qwen/qwen2.5-72b-instruct",
            "nvidia/nemotron-4-340b-instruct",
            "nvidia/llama-3.1-nemotron-51b-instruct",
            "nvidia/nemotron-mini-4b-instruct",
            "mistralai/mistral-large-2-instruct",
            "mistralai/mixtral-8x22b-instruct-v0.1",
            "mistralai/codestral-22b-instruct-v0.1",
            "meta/llama-3.1-405b-instruct",
            "meta/llama-3.1-8b-instruct",
            "deepseek-ai/deepseek-r1-distill-qwen-32b",
            "deepseek-ai/deepseek-r1-distill-llama-70b",
            "nvidia/llama-3.2-11b-vision-instruct",
            "nvidia/llama-3.2-90b-vision-instruct",
        ],
        "env_keys": ["NVIDIA_API_KEY", "NIM_API_KEY"],
        "default_model": "nvidia/llama-3.1-nemotron-70b-instruct",
        "default_url": "https://integrate.api.nvidia.com/v1",
    },
    "deepseek": {
        "name": "DeepSeek Official",
        "models": [
            "deepseek-chat",
            "deepseek-reasoner",
            "deepseek-coder",
        ],
        "env_keys": ["DEEPSEEK_API_KEY"],
        "default_model": "deepseek-chat",
        "default_url": "https://api.deepseek.com/v1",
    },
    "qwen": {
        "name": "Alibaba Cloud Qwen",
        "models": [
            "qwen-max",
            "qwen-plus",
            "qwen-turbo",
            "qwen2.5-coder-32b-instruct",
        ],
        "env_keys": ["DASHSCOPE_API_KEY", "QWEN_API_KEY"],
        "default_model": "qwen-plus",
        "default_url": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    },
    "minimax": {
        "name": "MiniMax AI",
        "models": [
            "MiniMax-Text-01",
            "abab6.5s-chat",
            "abab6.5g-chat",
            "abab6.5t-chat",
        ],
        "env_keys": ["MINIMAX_API_KEY"],
        "default_model": "MiniMax-Text-01",
        "default_url": "https://api.minimax.chat/v1",
    },
    "moonshot": {
        "name": "Moonshot Kimi",
        "models": [
            "moonshot-v1-8k",
            "moonshot-v1-32k",
            "moonshot-v1-128k",
        ],
        "env_keys": ["MOONSHOT_API_KEY", "KIMI_API_KEY"],
        "default_model": "moonshot-v1-8k",
        "default_url": "https://api.moonshot.cn/v1",
    },
    "openrouter": {
        "name": "OpenRouter (Multi-Model)",
        "models": [
            "deepseek/deepseek-r1:free",
            "meta-llama/llama-3.3-70b-instruct:free",
            "google/gemini-2.0-flash-exp:free",
            "qwen/qwen-2.5-coder-32b-instruct:free",
            "mistralai/mistral-small-24b-instruct-2501:free",
        ],
        "env_keys": ["OPENROUTER_API_KEY"],
        "default_model": "deepseek/deepseek-r1:free",
        "default_url": "https://openrouter.ai/api/v1",
    },
    "antigravity": {
        "name": "Antigravity Proxy",
        "models": [
            "gemini-3.8-flash",
            "gemini-3.6-flash",
            "claude-sonnet-4.6",
            "claude-opus-4.6",
            "gpt-oss-120b",
        ],
        "env_keys": ["ANTIGRAVITY_API_KEY"],
        "default_model": "gemini-3.8-flash",
        "default_url": "http://127.0.0.1:8890/v1",
    },
    "openai": {
        "name": "OpenAI",
        "models": [
            "gpt-4o",
            "gpt-4o-mini",
            "o3-mini",
            "o1",
            "o1-mini",
        ],
        "env_keys": ["OPENAI_API_KEY"],
        "default_model": "gpt-4o-mini",
        "default_url": "https://api.openai.com/v1",
    },
    "anthropic": {
        "name": "Anthropic Claude",
        "models": [
            "claude-3-7-sonnet-latest",
            "claude-3-5-sonnet-latest",
            "claude-3-5-haiku-latest",
        ],
        "env_keys": ["ANTHROPIC_API_KEY"],
        "default_model": "claude-3-7-sonnet-latest",
        "default_url": "https://api.anthropic.com",
    },
    "groq": {
        "name": "Groq (Ultra-Fast)",
        "models": [
            "llama-3.3-70b-versatile",
            "llama-3.1-8b-instant",
            "mixtral-8x7b-32768",
        ],
        "env_keys": ["GROQ_API_KEY"],
        "default_model": "llama-3.3-70b-versatile",
        "default_url": "https://api.groq.com/openai/v1",
    },
    "ollama": {
        "name": "Ollama (Local Offline)",
        "models": ["llama3.2", "llama3.1", "deepseek-r1", "qwen2.5-coder"],
        "env_keys": [],
        "default_model": "llama3.2",
        "default_url": "http://localhost:11434",
    },
}

# Provider aliases mapping
PROVIDERS_CATALOG["gemini"] = PROVIDERS_CATALOG["google"]
PROVIDERS_CATALOG["nim"] = PROVIDERS_CATALOG["nvidia"]
def sync_providers_catalog() -> dict[str, Any]:
    """Synchronize providers catalog with 9router live models and web dashboard."""
    # 1. Fetch live models from 9Router Gateway (http://127.0.0.1:20128/v1/models)
    try:
        r = requests.get("http://127.0.0.1:20128/v1/models", timeout=1.0)
        if r.status_code == 200:
            live_data = r.json().get("data", [])
            existing = set(PROVIDERS_CATALOG["9router"]["models"])
            for item in live_data:
                mid = item.get("id")
                if mid and mid not in existing:
                    PROVIDERS_CATALOG["9router"]["models"].append(mid)
                    existing.add(mid)
    except Exception:
        pass

    # 2. Sync from web PROVIDER_MODELS if available
    try:
        from alfa.dashboard.routes.system.provider_catalog import PROVIDER_MODELS

        for prov, model_list in PROVIDER_MODELS.items():
            norm_p = normalize_provider(prov)
            if norm_p in PROVIDERS_CATALOG:
                existing_m = set(PROVIDERS_CATALOG[norm_p]["models"])
                for item in model_list:
                    mid = item.get("id") if isinstance(item, dict) else str(item)
                    if mid and mid not in existing_m:
                        PROVIDERS_CATALOG[norm_p]["models"].append(mid)
                        existing_m.add(mid)
    except Exception:
        pass

    return PROVIDERS_CATALOG
PRESETS: dict[str, Any] = {
    "fast": {
        "temperature": 0.2,
        "max_tokens": 1024,
        "description": "Fast deterministic answers",
    },
    "smart": {
        "temperature": 0.7,
        "max_tokens": 4096,
        "description": "Balanced intelligence & reasoning",
    },
    "creative": {
        "temperature": 0.9,
        "max_tokens": 4096,
        "description": "High creativity and variation",
    },
    "precise": {
        "temperature": 0.1,
        "max_tokens": 2048,
        "description": "Deterministic, factual & concise",
    },
    "coding": {
        "temperature": 0.2,
        "max_tokens": 8192,
        "description": "Optimized for code generation & debugging",
    },
}
DEFAULT_SYSTEM_PROMPT = """Anda adalah ALFA Sovereign AI - Autonomous Developer & Coding Assistant yang berjalan secara LOKAL di komputer pengguna.
Lingkungan kerja Anda:
1. Anda beroperasi langsung di terminal proyek lokal pengguna, BUKAN di browser web atau server terisolasi.
2. Anda memiliki akses langsung ke sistem file proyek lokal, pembacaan file, penulisan kode, dan shell terminal.
3. JANGAN PERNAH mengatakan "Saya tidak memiliki akses langsung ke sistem file lokal Anda". Anda beroperasi di mesin lokal user.
4. Jika user meminta memeriksa folder, membaca file, atau membuat kode, berikan jawaban langsung berdasarkan konteks proyek lokal.
5. Berkomunikasi dengan jelas, solutif, ringkas, dan teknis."""
