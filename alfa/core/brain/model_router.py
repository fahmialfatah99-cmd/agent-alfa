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

#: Kapabilitas per prefix model. Urutan penting: prefix paling spesifik dulu.
#: Unknown sengaja optimistis pada ``tools``/``streaming`` tetapi TIDAK pada
#: ``vision`` — model teks yang dipaksa membaca gambar akan gagal total.
_MODEL_CAPABILITY_RULES: tuple[tuple[tuple[str, ...], set[str]], ...] = (
    (
        ("gemini", "gemma-3", "gemma3"),
        {"tools", "vision", "streaming", "long_context"},
    ),
    (("claude",), {"tools", "vision", "streaming", "long_context"}),
    (
        ("gpt-4o", "gpt-4.1", "gpt-5", "o3", "o4"),
        {"tools", "vision", "streaming", "long_context"},
    ),
    (("gpt-3.5",), {"tools", "streaming", "long_context"}),
    (("o1",), {"tools", "streaming", "long_context"}),
    (
        (
            "gemma",
            "codellama",
            "code-llama",
            "deepseek-coder",
            "deepseek-chat",
            "deepseek-reasoner",
            "qwen2.5-coder",
            "qwen-2.5-coder",
            "phi-3",
            "phi3",
            "mistral-7b",
            "llama-2",
            "llama2",
            "llama-3.1-8b",
            "command-r",
        ),
        {"tools", "streaming"},
    ),
)


def model_capabilities(model: str) -> set[str]:
    """Perkiraan kapabilitas model dari nama/prefix-nya (fail-open)."""
    name = (model or "").strip().lower()
    for prefixes, caps in _MODEL_CAPABILITY_RULES:
        if name.startswith(prefixes):
            return set(caps)
    return {"tools", "streaming"}


def required_capabilities(
    user_prompt: str,
    *,
    has_images: bool = False,
    tools_expected: bool = True,
) -> set[str]:
    """Kapabilitas minimum untuk satu giliran.

    Routing hanya MENDAHULUKAN model yang cocok; model lain tetap disimpan
    sebagai fallback terakhir supaya tidak ada model yang hilang dari rantai.
    """
    caps: set[str] = set()
    if tools_expected or (user_prompt or "").strip():
        caps.add("tools")
    if has_images:
        caps.add("vision")
    return caps


def order_models_by_capability(
    models: list[str], required: set[str] | None
) -> list[str]:
    """Stable-partition: model yang memenuhi semua kapabilitas didahulukan."""
    if not required:
        return list(models)
    supported: list[str] = []
    unsupported: list[str] = []
    for model in models:
        if required.issubset(model_capabilities(model)):
            supported.append(model)
        else:
            unsupported.append(model)
    if unsupported:
        logger.info(
            "[ModelRouter] Kapabilitas %s tidak dipenuhi: %s -> fallback terakhir",
            sorted(required),
            unsupported,
        )
    return supported + unsupported


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
    required_capabilities: set[str] | None = None,
) -> list[str]:
    """Dynamically determine the optimal sequence of candidate models.

    Takes into account user intent, override_model, optional capability
    requirements (tools/vision/streaming), and circuit breaker status.
    ``required_capabilities=None`` preserves the legacy ordering exactly.
    """
    if override_model:
        candidates = [override_model] + [m for m in fallback_chain if m != override_model]
        deduped = list(dict.fromkeys(candidates))
        return get_available_models(
            order_models_by_capability(deduped, required_capabilities)
        )

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
    if required_capabilities:
        deduped = order_models_by_capability(deduped, required_capabilities)
    # Filter through Circuit Breaker to avoid dead/exhausted endpoints
    available = get_available_models(deduped)
    logger.info(f"[ModelRouter] Routed models for ({intent}): {available}")
    return available
