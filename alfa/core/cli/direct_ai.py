"""ALFA Sovereign AI - Direct LLM Execution Engine (Standalone Mode).

Provides standalone multi-provider AI access (Google, OpenAI, Anthropic, Groq, Ollama)
without requiring an active ALFA backend server, bringing DevCLI capabilities natively into Python.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Callable, Generator

import requests

from alfa.core.cli.constants import (
    CONFIG_FILE,
    RICH_AVAILABLE,
    Colors,
    print_status,
)

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


PROVIDERS_CATALOG = {
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
        from alfa.dashboard.routes.system.keys_models import PROVIDER_MODELS

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

PRESETS = {
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


class DirectAIClient:
    """Client for executing standalone LLM inference directly with multi-provider fallback."""

    def __init__(
        self,
        provider: str | None = None,
        model: str | None = None,
        system_prompt: str | None = None,
    ):
        self._load_env_file()
        self.config = self._load_saved_config()

        # Resolve provider
        raw_provider = (
            provider
            or self.config.get("provider")
            or os.getenv("AI_PROVIDER")
            or "google"
        )
        self.provider = normalize_provider(raw_provider)
        if self.provider not in PROVIDERS_CATALOG:
            self.provider = "google"

        # Resolve model
        catalog = PROVIDERS_CATALOG[self.provider]
        if model:
            self.model = model
        elif (
            self.config.get("provider") == self.provider
            and self.config.get("model")
            and self.config.get("model") in catalog["models"]
        ):
            self.model = self.config.get("model")
        elif os.getenv("AI_MODEL"):
            self.model = os.getenv("AI_MODEL")
        else:
            self.model = catalog["default_model"]

        self.system_prompt = system_prompt or DEFAULT_SYSTEM_PROMPT
        self.temperature = float(self.config.get("temperature", 0.7))
        self.max_tokens = int(self.config.get("max_tokens", 4096))
        self.base_url = (
            self.config.get("base_url")
            or os.getenv("API_BASE_URL")
            or catalog["default_url"]
        )
        self.history: list[dict[str, str]] = []
        self.attached_files: list[str] = []

    def _load_env_file(self) -> None:
        """Load .env file if present in current working directory, parent, or ALFA install root."""
        env_paths = [Path.cwd() / ".env", Path.cwd().parent / ".env"]
        install_root = Path(__file__).resolve().parent.parent.parent.parent
        if (install_root / ".env") not in env_paths:
            env_paths.append(install_root / ".env")

        for path in env_paths:
            if path.exists():
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if line and not line.startswith("#") and "=" in line:
                                k, v = line.split("=", 1)
                                k = k.strip()
                                v = v.strip().strip("'\"")
                                if k not in os.environ:
                                    os.environ[k] = v
                except Exception:
                    pass

    def _load_saved_config(self) -> dict[str, Any]:
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def get_api_key(self) -> str:
        """Resolve API key with multi-tiered fallback: Env -> Config -> SQLite Vault -> 9Router SQLite."""
        catalog = PROVIDERS_CATALOG.get(self.provider, {})
        norm_prov = normalize_provider(self.provider)

        # 1. Check environment variables
        for key_name in catalog.get("env_keys", []):
            val = os.getenv(key_name)
            if val:
                return val.strip()

        # 2. Check CLI config file
        api_keys_cfg = self.config.get("api_keys", {})
        if self.provider in api_keys_cfg and api_keys_cfg[self.provider]:
            return api_keys_cfg[self.provider]
        if norm_prov in api_keys_cfg and api_keys_cfg[norm_prov]:
            return api_keys_cfg[norm_prov]

        # 3. Check SQLite Database Vault (Synchronized with Web Dashboard)
        try:
            from alfa.core import database

            db_candidates = [self.provider, norm_prov]
            if norm_prov == "google":
                db_candidates.append("gemini")
            elif norm_prov == "nvidia":
                db_candidates.append("nim")
            elif norm_prov == "qwen":
                db_candidates.append("dashscope")
            elif norm_prov == "moonshot":
                db_candidates.append("kimi")

            for cand in db_candidates:
                key_row = database.get_active_api_key_sync(cand)
                if key_row and key_row.get("api_key"):
                    return key_row["api_key"].strip()
        except Exception:
            pass

        # 4. 9Router Auto-Discovery from local SQLite (~/.9router/db/data.sqlite)
        if norm_prov == "9router":
            try:
                import glob
                import sqlite3

                paths = glob.glob(os.path.expanduser("~/.9router/db/data.sqlite")) + glob.glob(
                    os.path.expandvars(r"%APPDATA%\9router\db\data.sqlite")
                )
                for dbp in paths:
                    if os.path.exists(dbp):
                        with sqlite3.connect(dbp) as conn:
                            # Try active key first
                            try:
                                rk = conn.execute(
                                    "SELECT key FROM apiKeys WHERE isActive = 1 LIMIT 1"
                                ).fetchone()
                                if rk and rk[0]:
                                    return rk[0].strip()
                            except Exception:
                                pass
                            # Otherwise first key
                            rk = conn.execute("SELECT key FROM apiKeys LIMIT 1").fetchone()
                            if rk and rk[0]:
                                return rk[0].strip()
            except Exception:
                pass
            # Fallback dummy key for local 9router proxy
            return "sk-9router-local"

        # 5. Antigravity local gateway fallback
        if norm_prov == "antigravity":
            return "oauth-antigravity-local"

        return ""

    def set_provider(self, provider: str, model: str | None = None) -> bool:
        """Switch active provider and model, checking catalog and web sync."""
        norm = normalize_provider(provider)
        if norm not in PROVIDERS_CATALOG:
            return False
        self.provider = norm
        cat = PROVIDERS_CATALOG[norm]
        self.base_url = cat["default_url"]

        # If model is not explicitly provided, check database default_model
        if not model:
            try:
                from alfa.core import database

                key_row = database.get_active_api_key_sync(norm)
                if key_row and key_row.get("default_model"):
                    model = key_row["default_model"]
            except Exception:
                pass

        self.model = model or cat["default_model"]
        return True

    def apply_preset(self, preset_name: str) -> bool:
        name = preset_name.lower()
        if name not in PRESETS:
            return False
        p = PRESETS[name]
        self.temperature = p["temperature"]
        self.max_tokens = p["max_tokens"]
        return True

    def read_file_content(self, filepath: str) -> str:
        """Read content of a single file safely with size boundary."""
        p = Path(filepath)
        if not p.is_absolute():
            p = Path.cwd() / p
        if not p.exists():
            return f"[Peringatan: File '{filepath}' tidak ditemukan]"
        if not p.is_file():
            return f"[Peringatan: '{filepath}' bukan sebuah file]"
        try:
            # Limit to 200KB per file
            if p.stat().st_size > 200 * 1024:
                content = p.read_text(encoding="utf-8", errors="replace")[:100000]
                return f"--- File: {filepath} (Dipotong karena terlalu besar) ---\n{content}\n... [TRUNCATED] ..."
            content = p.read_text(encoding="utf-8", errors="replace")
            return f"--- File: {filepath} ---\n{content}"
        except Exception as e:
            return f"[Error membaca file '{filepath}': {e}]"

    def scan_file_mentions(self, text: str) -> tuple[str, list[str]]:
        """Extract @path/to/file mentions in prompt text and return loaded file contexts."""
        pattern = r"(?:^|\s)@([a-zA-Z0-9_\-./\\]+\.[a-zA-Z0-9_\-]+)"
        matches = re.findall(pattern, text)
        found_files = []
        for m in matches:
            p = Path(m)
            if not p.is_absolute():
                p = Path.cwd() / p
            if p.exists() and p.is_file():
                found_files.append(m)
        return text, list(dict.fromkeys(found_files))

    def build_prompt_with_context(
        self, prompt: str, context_files: list[str] | None = None
    ) -> str:
        """Combine user prompt with attached files and @mentioned files."""
        all_files = list(self.attached_files)
        if context_files:
            all_files.extend(context_files)

        # Scan prompt for @file mentions
        _, mentioned = self.scan_file_mentions(prompt)
        all_files.extend(mentioned)

        # Deduplicate preserving order
        unique_files = list(dict.fromkeys(all_files))

        if not unique_files:
            return prompt

        contexts = [self.read_file_content(f) for f in unique_files]
        context_block = "\n\n".join(contexts)
        return f"=== KONTEKS FILE PROYEK ===\n{context_block}\n\n=== PERTANYAAN/PERINTAH USER ===\n{prompt}"

    def generate(
        self,
        prompt: str,
        context_files: list[str] | None = None,
        stream: bool = False,
        stream_callback: Callable[[str], None] | None = None,
    ) -> str:
        """Generate response directly from the active provider."""
        final_prompt = self.build_prompt_with_context(prompt, context_files)

        norm = normalize_provider(self.provider)
        if norm in ("google", "gemini"):
            return self._call_google(final_prompt, stream, stream_callback)
        elif norm == "anthropic":
            return self._call_anthropic(final_prompt, stream, stream_callback)
        elif norm == "ollama":
            return self._call_ollama(final_prompt, stream, stream_callback)
        else:
            # 9router, nvidia, deepseek, qwen, minimax, moonshot, openrouter, antigravity, openai, groq
            return self._call_openai_compatible(final_prompt, stream, stream_callback)

    # --- Provider Implementations ---

    def _call_google(
        self,
        prompt: str,
        stream: bool,
        callback: Callable[[str], None] | None,
    ) -> str:
        api_key = self.get_api_key()
        if not api_key:
            raise ValueError(
                "GEMINI_API_KEY / GOOGLE_API_KEY tidak ditemukan. "
                "Set environment variable, simpan di Web Dashboard, atau jalankan '/menu' -> 'Kelola API Keys'."
            )

        # Try google.genai first if available
        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=api_key)
            config = types.GenerateContentConfig(
                system_instruction=self.system_prompt,
                temperature=self.temperature,
                max_output_tokens=self.max_tokens,
            )

            # Build conversation history
            contents = []
            for h in self.history[-10:]:
                role = "user" if h["role"] == "user" else "model"
                contents.append(
                    types.Content(
                        role=role,
                        parts=[types.Part.from_text(text=h["content"])],
                    )
                )
            contents.append(
                types.Content(
                    role="user",
                    parts=[types.Part.from_text(text=prompt)],
                )
            )

            if stream and callback:
                full_text = ""
                for chunk in client.models.generate_content_stream(
                    model=self.model, contents=contents, config=config
                ):
                    if chunk.text:
                        callback(chunk.text)
                        full_text += chunk.text
                self._record_history(prompt, full_text)
                return full_text
            else:
                response = client.models.generate_content(
                    model=self.model, contents=contents, config=config
                )
                text = response.text or ""
                self._record_history(prompt, text)
                return text
        except Exception:
            # REST Fallback via HTTP
            url = f"{self.base_url}/models/{self.model}:generateContent?key={api_key}"
            headers = {"Content-Type": "application/json"}
            payload = {
                "system_instruction": {
                    "parts": [{"text": self.system_prompt}]
                },
                "contents": [
                    {"role": "user", "parts": [{"text": prompt}]}
                ],
                "generationConfig": {
                    "temperature": self.temperature,
                    "maxOutputTokens": self.max_tokens,
                },
            }
            res = requests.post(url, headers=headers, json=payload, timeout=120)
            if res.status_code != 200:
                raise RuntimeError(f"Google API Error ({res.status_code}): {res.text}")
            data = res.json()
            candidates = data.get("candidates", [])
            if candidates and "content" in candidates[0]:
                parts = candidates[0]["content"].get("parts", [])
                text = "".join(p.get("text", "") for p in parts)
                if callback:
                    callback(text)
                self._record_history(prompt, text)
                return text
            return ""

    def _call_openai_compatible(
        self,
        prompt: str,
        stream: bool,
        callback: Callable[[str], None] | None,
    ) -> str:
        api_key = self.get_api_key()
        if not api_key:
            raise ValueError(
                f"API Key untuk provider '{self.provider}' tidak ditemukan.\n"
                f"Masukkan API Key di Web Dashboard atau jalankan '/menu' -> 'Kelola API Keys'."
            )

        messages = [{"role": "system", "content": self.system_prompt}]
        for h in self.history[-10:]:
            messages.append({"role": h["role"], "content": h["content"]})
        messages.append({"role": "user", "content": prompt})

        extra_headers = {}
        if self.provider == "openrouter":
            extra_headers["HTTP-Referer"] = "https://alfa-agent.local"
            extra_headers["X-Title"] = "ALFA Sovereign CLI"

        # Try using openai client if installed
        try:
            from openai import OpenAI

            client = OpenAI(
                api_key=api_key,
                base_url=self.base_url,
                default_headers=extra_headers or None,
            )
            if stream and callback:
                response = client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                    stream=True,
                )
                full_text = ""
                for chunk in response:
                    if chunk.choices and chunk.choices[0].delta:
                        delta = chunk.choices[0].delta.content or ""
                        if delta:
                            callback(delta)
                            full_text += delta
                self._record_history(prompt, full_text)
                return full_text
            else:
                resp = client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                    stream=False,
                )
                text = resp.choices[0].message.content or ""
                self._record_history(prompt, text)
                return text
        except Exception:
            # REST Fallback
            url = f"{self.base_url.rstrip('/')}/chat/completions"
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
                **extra_headers,
            }
            body = {
                "model": self.model,
                "messages": messages,
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
                "stream": stream and callback is not None,
            }

            if stream and callback:
                res = requests.post(url, headers=headers, json=body, stream=True, timeout=120)
                if res.status_code != 200:
                    raise RuntimeError(
                        f"{self.provider.upper()} API Error ({res.status_code}): {res.text}"
                    )
                full_text = ""
                for line in res.iter_lines():
                    if line:
                        line_str = line.decode("utf-8")
                        if line_str.startswith("data: "):
                            raw_chunk = line_str[6:].strip()
                            if raw_chunk == "[DONE]":
                                break
                            try:
                                chunk_json = json.loads(raw_chunk)
                                delta = (
                                    chunk_json.get("choices", [{}])[0]
                                    .get("delta", {})
                                    .get("content", "")
                                )
                                if delta:
                                    callback(delta)
                                    full_text += delta
                            except Exception:
                                pass
                self._record_history(prompt, full_text)
                return full_text
            else:
                body["stream"] = False
                res = requests.post(url, headers=headers, json=body, timeout=120)
                if res.status_code != 200:
                    raise RuntimeError(
                        f"{self.provider.upper()} API Error ({res.status_code}): {res.text}"
                    )
                data = res.json()
                text = data["choices"][0]["message"]["content"]
                if callback:
                    callback(text)
                self._record_history(prompt, text)
                return text

    def _call_anthropic(
        self,
        prompt: str,
        stream: bool,
        callback: Callable[[str], None] | None,
    ) -> str:
        api_key = self.get_api_key()
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY tidak ditemukan.")

        chat_messages = []
        for h in self.history[-10:]:
            chat_messages.append({"role": h["role"], "content": h["content"]})
        chat_messages.append({"role": "user", "content": prompt})

        try:
            import anthropic

            client = anthropic.Anthropic(api_key=api_key)
            if stream and callback:
                with client.messages.stream(
                    max_tokens=self.max_tokens,
                    system=self.system_prompt,
                    messages=chat_messages,
                    model=self.model,
                    temperature=self.temperature,
                ) as stream_resp:
                    full_text = ""
                    for delta in stream_resp.text_stream:
                        callback(delta)
                        full_text += delta
                self._record_history(prompt, full_text)
                return full_text
            else:
                resp = client.messages.create(
                    max_tokens=self.max_tokens,
                    system=self.system_prompt,
                    messages=chat_messages,
                    model=self.model,
                    temperature=self.temperature,
                )
                text = resp.content[0].text
                self._record_history(prompt, text)
                return text
        except Exception:
            # REST Fallback
            url = f"{self.base_url.rstrip('/')}/v1/messages"
            headers = {
                "Content-Type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            }
            body = {
                "model": self.model,
                "max_tokens": self.max_tokens,
                "system": self.system_prompt,
                "messages": chat_messages,
                "temperature": self.temperature,
            }
            res = requests.post(url, headers=headers, json=body, timeout=120)
            if res.status_code != 200:
                raise RuntimeError(
                    f"Anthropic API Error ({res.status_code}): {res.text}"
                )
            data = res.json()
            text = data["content"][0]["text"]
            if callback:
                callback(text)
            self._record_history(prompt, text)
            return text

    def _call_ollama(
        self,
        prompt: str,
        stream: bool,
        callback: Callable[[str], None] | None,
    ) -> str:
        messages = [{"role": "system", "content": self.system_prompt}]
        for h in self.history[-10:]:
            messages.append({"role": h["role"], "content": h["content"]})
        messages.append({"role": "user", "content": prompt})

        url = f"{self.base_url.rstrip('/')}/api/chat"
        headers = {"Content-Type": "application/json"}
        body = {
            "model": self.model,
            "messages": messages,
            "stream": stream and callback is not None,
            "options": {"temperature": self.temperature},
        }

        try:
            if stream and callback:
                res = requests.post(
                    url, headers=headers, json=body, stream=True, timeout=120
                )
                if res.status_code != 200:
                    raise RuntimeError(
                        f"Ollama Error ({res.status_code}): {res.text}"
                    )
                full_text = ""
                for line in res.iter_lines():
                    if line:
                        chunk = json.loads(line.decode("utf-8"))
                        piece = chunk.get("message", {}).get("content", "")
                        callback(piece)
                        full_text += piece
                self._record_history(prompt, full_text)
                return full_text
            else:
                res = requests.post(url, headers=headers, json=body, timeout=120)
                if res.status_code != 200:
                    raise RuntimeError(
                        f"Ollama Error ({res.status_code}): {res.text}"
                    )
                data = res.json()
                text = data.get("message", {}).get("content", "")
                self._record_history(prompt, text)
                return text
        except requests.exceptions.ConnectionError:
            raise ConnectionError(
                f"Tidak dapat terhubung ke Ollama di {self.base_url}. "
                "Pastikan service Ollama aktif ('ollama serve')."
            )

    def _record_history(self, prompt: str, response: str) -> None:
        self.history.append({"role": "user", "content": prompt})
        self.history.append({"role": "assistant", "content": response})
        if len(self.history) > 20:
            self.history = self.history[-20:]
