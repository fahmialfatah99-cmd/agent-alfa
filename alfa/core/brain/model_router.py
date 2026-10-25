"""Smart Intent-Based Model Routing & Token Budget Optimizer for ALFA.

Routes turns to the optimal model based on prompt complexity and token budget:
- Lightweight tasks (conversational, reading, simple summaries) -> Flash-Lite models
- Heavy tasks (coding, complex tools, bash, math, swarm meetings) -> High-reasoning models
- Integrates with ModelCircuitBreaker to automatically skip cooling/exhausted models.
"""

from __future__ import annotations

import logging

from alfa.core.brain.circuit_breaker import get_available_models

logger = logging.getLogger("ModelRouter")

LIGHT_INTENT_MARKERS = (
    "halo",
    "hai",
    "pagi",
    "siang",
    "sore",
    "malam",
    "apa kabar",
    "siapa kamu",
    "terima kasih",
    "makasih",
    "oke",
    "sip",
    "baca",
    "ringkas",
    "ringkasan",
    "rangkum",
    "rangkuman",
    "apa isi",
    "jelaskan singkat",
    "cek data",
)

HEAVY_INTENT_MARKERS = (
    "skrip",
    "script",
    "kode",
    "code",
    "coding",
    "program",
    "python",
    "bash",
    "terminal",
    "debug",
    "analisis mendalam",
    "hitung",
    "rumus",
    "arsitektur",
    "refactor",
    "meeting",
    "rapat",
    "browser_open",
    "crawl",
    "scrape",
    "swarm",
)

# Priority model lists
DEFAULT_LIGHT_MODELS = [
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-3.6-flash",
    "gemini-3.7-flash",
    "gemini-3.8-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.0-flash",
]

DEFAULT_HEAVY_MODELS = [
    "gemini-3.8-flash",
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-2.5-flash",
    "gemini-2.0-flash",
]


def classify_prompt_intent(user_prompt: str) -> str:
    """Classify prompt as 'LIGHT', 'HEAVY', or 'BALANCED'."""
    p_low = (user_prompt or "").lower().strip()
    if not p_low:
        return "LIGHT"

    is_heavy = any(hm in p_low for hm in HEAVY_INTENT_MARKERS) or len(p_low) > 1500
    is_light = any(lm in p_low for lm in LIGHT_INTENT_MARKERS) and not is_heavy

    if is_heavy:
        return "HEAVY"
    if is_light:
        return "LIGHT"
    return "BALANCED"


def route_candidate_models(
    user_prompt: str,
    base_model: str,
    fallback_chain: list[str],
    override_model: str | None = None,
) -> list[str]:
    """Dynamically determine the optimal sequence of candidate models.

    Takes into account user intent, override_model, and circuit breaker status.
    """
    if override_model:
        candidates = [override_model] + [m for m in fallback_chain if m != override_model]
        return get_available_models(list(dict.fromkeys(candidates)))

    intent = classify_prompt_intent(user_prompt)
    logger.debug(f"[ModelRouter] Prompt intent classified as: {intent}")

    ordered: list[str] = []

    if intent == "LIGHT":
        # Prioritize fast, cost-effective light models
        for lm in DEFAULT_LIGHT_MODELS:
            ordered.append(lm)
        if base_model and base_model not in ordered:
            ordered.append(base_model)
        for fb in fallback_chain:
            if fb not in ordered:
                ordered.append(fb)

    elif intent == "HEAVY":
        # Prioritize reasoning / tool-heavy models
        if base_model:
            ordered.append(base_model)
        for fb in fallback_chain:
            if fb not in ordered:
                ordered.append(fb)
        for hm in DEFAULT_HEAVY_MODELS:
            if hm not in ordered:
                ordered.append(hm)

    else:  # BALANCED
        if base_model:
            ordered.append(base_model)
        for fb in fallback_chain:
            if fb not in ordered:
                ordered.append(fb)
        for lm in DEFAULT_LIGHT_MODELS:
            if lm not in ordered:
                ordered.append(lm)

    deduped = list(dict.fromkeys(ordered))
    # Filter through Circuit Breaker to avoid dead/exhausted endpoints
    available = get_available_models(deduped)
    logger.info(f"[ModelRouter] Routed models for ({intent}): {available}")
    return available
