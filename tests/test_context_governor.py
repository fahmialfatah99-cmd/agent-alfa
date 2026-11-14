"""Tes Context & Cost Governor: kompaksi deterministik dan fail-soft."""

from __future__ import annotations

from alfa.core.brain import context_governor as cg


def _size(convo):
    return sum(
        len(str(m.get("content") or "")) + len(str(m.get("tool_calls") or ""))
        for m in convo
    )


def _convo(tool_count: int = 8, size: int = 3000) -> list[dict]:
    messages: list[dict] = [{"role": "user", "content": "Mulai tugas"}]
    for index in range(tool_count):
        messages.append(
            {"role": "tool", "content": f"T{index}-" + ("X" * size)}
        )
    messages.append({"role": "tool", "content": "hasil terbaru"})
    return messages


def test_mode_normalization(monkeypatch):
    monkeypatch.setenv("ALFA_CONTEXT_GOVERNOR", "TRUE")
    assert cg.governor_mode() == "on"
    monkeypatch.setenv("ALFA_CONTEXT_GOVERNOR", "0")
    assert cg.governor_mode() == "off"
    monkeypatch.setenv("ALFA_CONTEXT_GOVERNOR", "ngawur")
    assert cg.governor_mode() == "shadow"


def test_under_budget_is_untouched(monkeypatch):
    monkeypatch.setenv("ALFA_CONTEXT_GOVERNOR", "on")
    convo = _convo(tool_count=1, size=10)
    before = [dict(m) for m in convo]

    stats = cg.govern_convo(convo, _size, 100_000, 2)

    assert stats["saved"] == 0
    assert convo == before


def test_shadow_uses_legacy_marker(monkeypatch):
    monkeypatch.setenv("ALFA_CONTEXT_GOVERNOR", "shadow")
    convo = _convo(tool_count=4, size=1000)

    stats = cg.govern_convo(convo, _size, 2000, 2)

    assert stats["saved"] > 0
    assert convo[1]["content"].startswith("[output tool dipangkas utk hemat konteks]")
    assert convo[-2]["content"].startswith("T3-")
    assert convo[-1]["content"] == "hasil terbaru"


def test_on_mode_keeps_head_and_tail(monkeypatch):
    monkeypatch.setenv("ALFA_CONTEXT_GOVERNOR", "on")
    monkeypatch.setenv("ALFA_CONTEXT_OLD_HEAD", "300")
    monkeypatch.setenv("ALFA_CONTEXT_OLD_TAIL", "120")
    convo = _convo(tool_count=4, size=1000)

    stats = cg.govern_convo(convo, _size, 2000, 2)

    compacted = convo[1]["content"]
    assert stats["saved"] > 0
    assert compacted.startswith("[output tool dipangkas utk hemat konteks]")
    assert compacted.endswith("X" * 120)
    assert " ... " in compacted


def test_hard_budget_compacts_more_aggressively(monkeypatch):
    monkeypatch.setenv("ALFA_CONTEXT_GOVERNOR", "on")
    monkeypatch.setenv("ALFA_CONTEXT_HARD_BUDGET", "10000")
    convo = _convo(tool_count=12, size=4000)

    stats = cg.govern_convo(convo, _size, 5000, 2)

    assert stats["hard_compacted"] >= 1
    assert any(
        "[output tool dipangkas keras oleh context governor]" in m["content"]
        for m in convo
    )


def test_compact_tool_output_only_in_on_mode(monkeypatch):
    text = "HEAD" + ("X" * 20000) + "TAIL"
    monkeypatch.setenv("ALFA_CONTEXT_GOVERNOR", "shadow")
    assert cg.compact_tool_output(text) == text

    monkeypatch.setenv("ALFA_CONTEXT_GOVERNOR", "on")
    monkeypatch.setenv("ALFA_TOOL_OUTPUT_COMPACT_THRESHOLD", "1000")
    compacted = cg.compact_tool_output(text)
    assert len(compacted) < len(text)
    assert compacted.startswith("HEAD")
    assert compacted.endswith("TAIL")
    assert "context governor" in compacted
    # Idempoten: hasil yang sudah kecil tidak berubah lagi.
    assert cg.compact_tool_output(compacted) == compacted


def test_stats_exposed(monkeypatch):
    monkeypatch.setenv("ALFA_CONTEXT_GOVERNOR", "on")
    monkeypatch.setenv("ALFA_CONTEXT_OLD_HEAD", "300")
    monkeypatch.setenv("ALFA_CONTEXT_OLD_TAIL", "120")
    convo = _convo(tool_count=4, size=3000)
    cg.govern_convo(convo, _size, 2000, 2)

    stats = cg.governor_stats()

    assert stats["mode"] == "on"
    assert stats["last_saved_chars"] > 0
    assert stats["last_estimated_tokens"] > 0
    assert stats["limits"]["hard_budget"] >= 10_000


def test_governor_is_fail_soft():
    stats = cg.govern_convo({"bukan": "list"}, _size, 100, 2)  # type: ignore[arg-type]
    assert isinstance(stats, dict)
