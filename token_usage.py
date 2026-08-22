"""
Lightweight token-usage recorder for every LLM call (Gemini & OpenAI-compatible).

All functions are fail-safe: recording problems must never break the main
chat/swarm pipeline, so everything is wrapped in try/except.
"""

import logging

logger = logging.getLogger("TokenUsage")


def record(provider: str, model: str = "", key_id=None, key_label: str = "",
           context: str = "", prompt_tokens: int = 0, completion_tokens: int = 0):
    """Persist one usage record; silently ignore failures."""
    try:
        import database
        database.record_api_usage_sync(
            provider=provider, model=model, key_id=key_id, key_label=key_label,
            context=context, prompt_tokens=prompt_tokens or 0,
            completion_tokens=completion_tokens or 0,
        )
    except Exception as e:
        logger.debug(f"usage record skipped: {e}")


def from_gemini_response(response, provider: str = "gemini", model: str = "",
                         key_id=None, key_label: str = "", context: str = ""):
    """Extract usage_metadata from a google-genai response and record it."""
    try:
        um = getattr(response, "usage_metadata", None)
        if not um:
            return
        record(
            provider=provider, model=model, key_id=key_id, key_label=key_label,
            context=context,
            prompt_tokens=getattr(um, "prompt_token_count", 0) or 0,
            completion_tokens=(getattr(um, "candidates_token_count", 0) or 0)
                              + (getattr(um, "thoughts_token_count", 0) or 0),
        )
    except Exception as e:
        logger.debug(f"from_gemini_response skipped: {e}")


def from_openai_json(data: dict, provider: str = "", model: str = "",
                     key_id=None, key_label: str = "", context: str = ""):
    """Extract `usage` object from an OpenAI-compatible chat.completion JSON."""
    try:
        usage = (data or {}).get("usage") or {}
        if not usage:
            return
        record(
            provider=provider, model=model or data.get("model", ""),
            key_id=key_id, key_label=key_label, context=context,
            prompt_tokens=usage.get("prompt_tokens", 0) or 0,
            completion_tokens=usage.get("completion_tokens", 0) or 0,
        )
    except Exception as e:
        logger.debug(f"from_openai_json skipped: {e}")
