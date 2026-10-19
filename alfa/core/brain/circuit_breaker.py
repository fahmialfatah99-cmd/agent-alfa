"""Model Circuit Breaker for ALFA AI Brain.

Tracks models that returned 429 RESOURCE_EXHAUSTED or 503 UNAVAILABLE,
temporarily cooling them down so subsequent turns skip dead endpoints
instantly instead of wasting 10-15 seconds timing out repeatedly.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any

logger = logging.getLogger("ModelCircuitBreaker")

# {model_name: (cooldown_until_timestamp, reason)}
_COOLDOWN_REGISTRY: dict[str, tuple[float, str]] = {}
DEFAULT_COOLDOWN_SECONDS = 300.0  # 5 minutes default
MAX_COOLDOWN_SECONDS = 43200.0  # Max 12 hours


def parse_retry_delay(error_obj: Any) -> float:
    """Extract retryDelay from error object or string if available."""
    err_str = str(error_obj)
    # Check for retryDelay in seconds: 'retryDelay': '62514s' or '62514.5s'
    match_sec = re.search(r"['\"]?retryDelay['\"]?\s*:\s*['\"]?([0-9.]+)\s*s['\"]?", err_str)
    if match_sec:
        try:
            return min(float(match_sec.group(1)), MAX_COOLDOWN_SECONDS)
        except (ValueError, TypeError):
            pass

    # Check for 'Please retry in 17h21m54s'
    match_human = re.search(r"retry in\s+([0-9]+)h([0-9]+)m([0-9]+)s", err_str, re.IGNORECASE)
    if match_human:
        try:
            h, m, s = map(int, match_human.groups())
            total_sec = h * 3600 + m * 60 + s
            return min(float(total_sec), MAX_COOLDOWN_SECONDS)
        except (ValueError, TypeError):
            pass

    return DEFAULT_COOLDOWN_SECONDS


def mark_model_exhausted(model_name: str, cooldown_seconds: float | None = None, reason: str = "") -> None:
    """Mark a model as temporarily cooling down."""
    if not model_name:
        return
    sec = cooldown_seconds if cooldown_seconds is not None else DEFAULT_COOLDOWN_SECONDS
    sec = max(30.0, min(sec, MAX_COOLDOWN_SECONDS))
    until = time.monotonic() + sec
    _COOLDOWN_REGISTRY[model_name] = (until, reason or "quota/service exhausted")
    logger.warning(
        f"[CircuitBreaker] Model '{model_name}' didinginkan selama {int(sec)}s "
        f"karena: {reason or 'quota/service exhausted'}"
    )


def is_model_available(model_name: str) -> bool:
    """Check if model is currently available (not in cooldown)."""
    if not model_name:
        return False
    entry = _COOLDOWN_REGISTRY.get(model_name)
    if not entry:
        return True
    until, _ = entry
    now = time.monotonic()
    if now >= until:
        _COOLDOWN_REGISTRY.pop(model_name, None)
        return True
    return False


def get_available_models(candidate_models: list[str]) -> list[str]:
    """Filter candidate models, returning available ones first.

    If ALL candidate models are in cooldown, clears cooldown to fail-open
    rather than blocking execution.
    """
    if not candidate_models:
        return []

    available = [m for m in candidate_models if is_model_available(m)]
    if available:
        return available

    # Fail-open: all models were cooling down, reset registry for these models
    logger.info("[CircuitBreaker] Semua kandidat model dalam masa pendinginan. Melakukan fail-open reset.")
    for m in candidate_models:
        _COOLDOWN_REGISTRY.pop(m, None)
    return candidate_models


def reset_circuit_breaker() -> None:
    """Reset all circuit breaker entries (useful for testing or manual reset)."""
    _COOLDOWN_REGISTRY.clear()
