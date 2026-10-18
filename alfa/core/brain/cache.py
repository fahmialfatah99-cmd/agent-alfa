"""Opt-in cache respons LLM untuk generasi teks sekali-jalan (swarm).

Default MATI — aktifkan dengan `ALFA_LLM_CACHE=on`. Hanya dipakai untuk
panggilan TANPA tools (diskusi, konsensus, judge, planner) sehingga tidak
pernah meng-cache hasil eksekusi tool yang stateful.

Penyimpanan: satu file JSON per key-hash di
`ALFA_LLM_CACHE_DIR` (default `<repo>/.alfa_cache/llm/`).
"""

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def enabled() -> bool:
    return os.getenv("ALFA_LLM_CACHE", "off").strip().lower() == "on"


def cache_dir() -> Path:
    base = os.getenv("ALFA_LLM_CACHE_DIR", "").strip()
    return Path(base) if base else Path(REPO_ROOT) / ".alfa_cache" / "llm"


def make_key(
    provider: str,
    model: str,
    system_instruction: str,
    prompt: str,
    max_tokens: Any = None,
) -> str:
    canonical = json.dumps(
        {
            "provider": (provider or "").lower(),
            "model": model or "",
            "system": system_instruction or "",
            "prompt": prompt or "",
            "max_tokens": max_tokens,
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _path_for(key: str) -> Path:
    return cache_dir() / f"{key}.json"


def lookup(key: str) -> str | None:
    """Kembalikan teks cache bila ada dan valid, else None (tak pernah raise)."""
    try:
        p = _path_for(key)
        if not p.is_file():
            return None
        data = json.loads(p.read_text(encoding="utf-8"))
        text = data.get("text")
        return text if isinstance(text, str) and text else None
    except (OSError, ValueError, TypeError, AttributeError) as e:
        logger.debug(f"LLM cache lookup gagal: {e}")
        return None


def store(key: str, text: str) -> bool:
    """Simpan teks ke cache. Return False bila gagal (tak pernah raise)."""
    try:
        if not isinstance(text, str) or not text.strip():
            return False
        d = cache_dir()
        d.mkdir(parents=True, exist_ok=True)
        _path_for(key).write_text(
            json.dumps({"text": text}, ensure_ascii=False), encoding="utf-8"
        )
        return True
    except (OSError, ValueError, TypeError) as e:
        logger.debug(f"LLM cache store gagal: {e}")
        return False


def lookup_for(
    provider: str,
    model: str,
    system_instruction: str,
    prompt: str,
    max_tokens: Any = None,
) -> str | None:
    if not enabled():
        return None
    return lookup(make_key(provider, model, system_instruction, prompt, max_tokens))


def store_for(
    provider: str,
    model: str,
    system_instruction: str,
    prompt: str,
    text: str,
    max_tokens: Any = None,
) -> bool:
    if not enabled():
        return False
    return store(make_key(provider, model, system_instruction, prompt, max_tokens), text)
