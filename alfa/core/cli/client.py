"""Standalone multi-provider LLM client (DirectAI execution engine)."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from alfa.core.cli.backends import ClientBackendsMixin
from alfa.core.cli.constants import CONFIG_FILE
from alfa.core.cli.providers_catalog import (
    DEFAULT_SYSTEM_PROMPT,
    PRESETS,
    PROVIDERS_CATALOG,
    normalize_provider,
)


class DirectAIClient(ClientBackendsMixin):
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
            self.model = str(self.config.get("model"))
        elif os.getenv("AI_MODEL"):
            self.model = str(os.getenv("AI_MODEL"))
        else:
            self.model = str(catalog["default_model"])

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
                    with open(path, encoding="utf-8") as f:
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
                with open(CONFIG_FILE, encoding="utf-8") as f:
                    _data = json.load(f)
                    return _data if isinstance(_data, dict) else {}
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
            return str(api_keys_cfg[self.provider])
        if norm_prov in api_keys_cfg and api_keys_cfg[norm_prov]:
            return str(api_keys_cfg[norm_prov])

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
                    return str(key_row["api_key"]).strip()
        except Exception:
            pass

        # 4. 9Router Auto-Discovery from local SQLite (~/.9router/db/data.sqlite)
        if norm_prov == "9router":
            try:
                import glob
                import sqlite3

                paths = glob.glob(
                    os.path.expanduser("~/.9router/db/data.sqlite")
                ) + glob.glob(os.path.expandvars(r"%APPDATA%\9router\db\data.sqlite"))
                for dbp in paths:
                    if os.path.exists(dbp):
                        with sqlite3.connect(dbp) as conn:
                            # Try active key first
                            try:
                                rk = conn.execute(
                                    "SELECT key FROM apiKeys WHERE isActive = 1 LIMIT 1"
                                ).fetchone()
                                if rk and rk[0]:
                                    return str(rk[0]).strip()
                            except Exception:
                                pass
                            # Otherwise first key
                            rk = conn.execute(
                                "SELECT key FROM apiKeys LIMIT 1"
                            ).fetchone()
                            if rk and rk[0]:
                                return str(rk[0]).strip()
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

        self.model = model or str(cat["default_model"])
        return True

    def apply_preset(self, preset_name: str) -> bool:
        name = preset_name.lower()
        if name not in PRESETS:
            return False
        p = PRESETS[name]
        self.temperature = float(p["temperature"])
        self.max_tokens = int(p["max_tokens"])
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

    def _record_history(self, prompt: str, response: str) -> None:
        self.history.append({"role": "user", "content": prompt})
        self.history.append({"role": "assistant", "content": response})
        if len(self.history) > 20:
            self.history = self.history[-20:]
