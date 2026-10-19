"""Tests for ModelCircuitBreaker and ModelRouter."""

import pytest

from alfa.core.brain.circuit_breaker import (
    DEFAULT_COOLDOWN_SECONDS,
    get_available_models,
    is_model_available,
    mark_model_exhausted,
    parse_retry_delay,
    reset_circuit_breaker,
)
from alfa.core.brain.model_router import (
    classify_prompt_intent,
    route_candidate_models,
)


@pytest.fixture(autouse=True)
def clean_circuit():
    reset_circuit_breaker()
    yield
    reset_circuit_breaker()


def test_circuit_breaker_mark_and_check():
    assert is_model_available("gemini-3.8-flash")
    mark_model_exhausted("gemini-3.8-flash", cooldown_seconds=100.0, reason="429 Resource Exhausted")
    assert not is_model_available("gemini-3.8-flash")

    # Other models are unaffected
    assert is_model_available("gemini-flash-lite-latest")


def test_circuit_breaker_filter_models():
    models = ["gemini-3.8-flash", "gemini-3.5-flash", "gemini-flash-lite-latest"]
    mark_model_exhausted("gemini-3.8-flash", cooldown_seconds=300.0)

    avail = get_available_models(models)
    assert "gemini-3.8-flash" not in avail
    assert "gemini-3.5-flash" in avail
    assert "gemini-flash-lite-latest" in avail


def test_circuit_breaker_fail_open_when_all_exhausted():
    models = ["gemini-3.8-flash", "gemini-3.5-flash"]
    mark_model_exhausted("gemini-3.8-flash", cooldown_seconds=300.0)
    mark_model_exhausted("gemini-3.5-flash", cooldown_seconds=300.0)

    # All exhausted -> fail-open should return the models and clear cooldown
    avail = get_available_models(models)
    assert avail == models
    assert is_model_available("gemini-3.8-flash")


def test_parse_retry_delay():
    err1 = "{'error': {'code': 429, 'details': [{'retryDelay': '62514s'}]}}"
    assert parse_retry_delay(err1) == 43200.0  # Capped at MAX_COOLDOWN_SECONDS (12h)

    err2 = "Rate limit exceeded. Please retry in 1h30m00s."
    assert parse_retry_delay(err2) == 5400.0  # 1.5h = 5400s

    err3 = "Generic 503 error"
    assert parse_retry_delay(err3) == DEFAULT_COOLDOWN_SECONDS


def test_classify_prompt_intent():
    assert classify_prompt_intent("halo selamat pagi") == "LIGHT"
    assert classify_prompt_intent("baca dokumen excel ini dan ringkas isinya") == "LIGHT"
    assert classify_prompt_intent("apa isi file ini?") == "LIGHT"

    assert classify_prompt_intent("tuliskan skrip python untuk scraping") == "HEAVY"
    assert classify_prompt_intent("jalankan perintah bash di terminal") == "HEAVY"
    assert classify_prompt_intent("lakukan analisis mendalam dan hitung rumus") == "HEAVY"


def test_route_candidate_models_light():
    candidates = route_candidate_models(
        user_prompt="halo apa kabar",
        base_model="gemini-3.8-flash",
        fallback_chain=["gemini-3.5-flash"],
    )
    # Light task routes to lite model first
    assert "lite" in candidates[0].lower()


def test_route_candidate_models_heavy():
    candidates = route_candidate_models(
        user_prompt="tulis kode python dengan library pandas",
        base_model="gemini-3.8-flash",
        fallback_chain=["gemini-3.5-flash"],
    )
    # Heavy task routes to base/reasoning model first
    assert candidates[0] == "gemini-3.8-flash"


def test_route_candidate_models_with_circuit_breaker():
    mark_model_exhausted("gemini-3.8-flash", cooldown_seconds=600.0)
    candidates = route_candidate_models(
        user_prompt="tulis kode python",
        base_model="gemini-3.8-flash",
        fallback_chain=["gemini-3.5-flash", "gemini-flash-lite-latest"],
    )
    # 3.8-flash must be skipped
    assert "gemini-3.8-flash" not in candidates
    assert candidates[0] == "gemini-3.5-flash"
