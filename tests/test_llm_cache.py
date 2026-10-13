"""Unit test cache LLM opt-in (tanpa jaringan, tanpa LLM)."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from alfa.core.brain import cache as llm_cache


def test_mati_default(monkeypatch, tmp_path):
    monkeypatch.delenv("ALFA_LLM_CACHE", raising=False)
    monkeypatch.setenv("ALFA_LLM_CACHE_DIR", str(tmp_path))
    assert llm_cache.enabled() is False
    assert llm_cache.store_for("p", "m", "s", "q", "teks") is False
    assert llm_cache.lookup_for("p", "m", "s", "q") is None


def test_roundtrip(monkeypatch, tmp_path):
    monkeypatch.setenv("ALFA_LLM_CACHE", "on")
    monkeypatch.setenv("ALFA_LLM_CACHE_DIR", str(tmp_path))
    assert llm_cache.store_for("gemini", "m1", "sys", "halo", "HAI") is True
    assert llm_cache.lookup_for("gemini", "m1", "sys", "halo") == "HAI"
    assert llm_cache.lookup_for("gemini", "m1", "sys", "halo?") is None


def test_key_stabil_dan_provider_case_insensitive(monkeypatch, tmp_path):
    monkeypatch.setenv("ALFA_LLM_CACHE", "on")
    monkeypatch.setenv("ALFA_LLM_CACHE_DIR", str(tmp_path))
    k1 = llm_cache.make_key("Gemini", "m", "s", "p")
    k2 = llm_cache.make_key("gemini", "m", "s", "p")
    assert k1 == k2
    assert llm_cache.make_key("gemini", "m", "s", "p2") != k1


def test_hook_tidak_panggil_provider_saat_hit(monkeypatch, tmp_path):
    from alfa.swarm import llm_client

    monkeypatch.setenv("ALFA_LLM_CACHE", "on")
    monkeypatch.setenv("ALFA_LLM_CACHE_DIR", str(tmp_path))
    llm_cache.store_for("gemini", "mm", "SYS", "PROMPT-Q", "CACHED-ANSWER", 500)

    monkeypatch.setattr(
        llm_client,
        "get_agent_api_client",
        lambda agent: ("gemini", "k", "mm", "", None),
    )

    async def _boom(*a, **k):
        raise AssertionError("provider tidak boleh dipanggil saat cache hit")

    monkeypatch.setattr(llm_client, "_generate_with_gemini", _boom)
    out = asyncio.run(
        llm_client.generate_agent_response(
            {"name": "T", "provider": "gemini"}, "PROMPT-Q", "SYS"
        )
    )
    assert out == "CACHED-ANSWER"


def test_hook_lewati_agentic_ber_tool(monkeypatch, tmp_path):
    from alfa.swarm import llm_client

    monkeypatch.setenv("ALFA_LLM_CACHE", "on")
    monkeypatch.setenv("ALFA_LLM_CACHE_DIR", str(tmp_path))
    # Seed cache untuk prompt yang sama — agen ber-tool TIDAK boleh hit.
    llm_cache.store_for("gemini", "mm", "SYS", "PROMPT-W", "CACHED-W")

    async def _fake_gemini(*a, **k):
        return "FRESH"

    monkeypatch.setattr(llm_client, "_generate_with_gemini", _fake_gemini)
    out = asyncio.run(
        llm_client.generate_agent_response(
            {"name": "T", "provider": "gemini", "enable_tools": 1},
            "PROMPT-W",
            "SYS",
            max_tokens=10,
        )
    )
    assert out == "FRESH"
