"""Tes untuk `alfa/bot/cloud_menu.py` & `alfa/core/brain/agentic.py`.

Fokus: helper murni (format, cache, escape, ikon) + **jalur fail-closed**
permission gate pada agentic — bagian yang paling berbahaya bila salah.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

_GATE_ERR = "gate internal error"

# ── cloud_menu: helper murni ────────────────────────────────────────────────


class TestCloudMenuHelpers:
    def test_sticky_keys(self):
        from alfa.bot import cloud_menu as cm

        assert cm._is_sticky("folder_cache") is True
        assert cm._is_sticky("mount_cache_sdrive") is True
        assert cm._is_sticky("sheet_cache") is False

    def test_fmt_size(self):
        from alfa.bot import cloud_menu as cm

        assert cm._fmt_size(0) == "0 B"
        assert cm._fmt_size(512) == "512 B"
        assert cm._fmt_size(2048) == "2.0 KB"
        assert cm._fmt_size(1024**3) == "1.0 GB"
        assert cm._fmt_size(1024**4) == "1.0 TB"

    def test_fmt_time(self):
        from alfa.bot import cloud_menu as cm

        assert cm._fmt_time("") == "-"
        assert cm._fmt_time("2026-10-20T19:01:24.957Z") == "20/10/26 19:01"
        # format tak dikenal -> potong, bukan exception
        assert cm._fmt_time("bukan tanggal") == "bukan tanggal"

    def test_esc_escapes_markdown(self):
        from alfa.bot import cloud_menu as cm

        assert cm._esc("") == ""
        assert "\\" in cm._esc("a_b*c")

    def test_cache_roundtrip_and_expiry(self, monkeypatch):
        from alfa.bot import cloud_menu as cm

        cm._CACHE.clear()
        cm._cache_put(1, "sheet_cache", ["a"])
        assert cm._cache_get(1, "sheet_cache") == ["a"]

        # kunci non-sticky kedaluwarsa
        cm._CACHE[1]["ts"] = cm.time.monotonic() - cm._CACHE_TTL - 5
        assert cm._cache_get(1, "sheet_cache") == []

        # kunci sticky tetap hidup meski kedaluwarsa
        cm._cache_put(1, "folder_cache", "/path")
        cm._CACHE[1]["ts"] = cm.time.monotonic() - cm._CACHE_TTL - 5
        assert cm._cache_get(1, "folder_cache") == "/path"
        cm._CACHE.clear()

    def test_nav_row_has_prev_next(self):
        from alfa.bot import cloud_menu as cm

        row = cm._nav_row("sheets", 1, 3)
        assert len(row) == 3
        assert "2/3" in row[1].text  # halaman 1 (0-based) -> tampil "2/3"
        first = cm._nav_row("sheets", 0, 3)
        assert len(first) == 2

    def test_file_icons(self):
        from alfa.bot import cloud_menu as cm

        assert cm._get_file_icon("application/vnd.google-apps.folder") == "📁"
        assert cm._get_file_icon("image/png") == "🖼️"
        assert cm._get_file_icon("", name="laporan.pdf") == "📄"
        assert cm._get_file_icon("", name="data.xlsx") == "📊"
        assert cm._get_file_icon("", is_dir=True) == "📁"


# ── agentic: fail-closed permission gate ───────────────────────────────────


class TestAgenticGateFailClosed:
    async def test_missing_gate_denies_tool(self):
        from alfa.core.brain import agentic

        out = await agentic._resolve_tool_outcome(None, "execute_bash_command", "{}")
        assert "ditolak" in out.lower()

    async def test_gate_error_denies_tool(self):
        from alfa.core.brain import agentic

        async def _boom(name, args):
            raise RuntimeError(_GATE_ERR)

        out = await agentic._resolve_tool_outcome(_boom, "execute_bash_command", "{}")
        assert "tidak dieksekusi" in out.lower()
        assert "gate internal error" in out

    async def test_gate_denial_is_returned_verbatim(self):
        from alfa.core.brain import agentic

        async def _deny(name, args):
            return "[DITOLAK] nope"

        out = await agentic._resolve_tool_outcome(_deny, "web_search", "{}")
        assert out == "[DITOLAK] nope"

    async def test_allowed_gate_executes_tool(self):
        from alfa.core.brain import agentic

        async def _allow(name, args):
            return None

        with patch.object(agentic, "_execute_tool", return_value="hasil ok") as ex:
            out = await agentic._resolve_tool_outcome(_allow, "web_search", "{}")
        assert out == "hasil ok"
        assert ex.called

    async def test_run_tool_calls_preserves_order(self):
        from alfa.core.brain import agentic
        from alfa.core.runtime_ctx import (
            get_current_executed_tool_calls,
            reset_turn_context,
        )

        async def _allow(name, args):
            return None

        reset_turn_context()
        calls = [
            {"function": {"name": "a", "arguments": "{}"}},
            {"function": {"name": "b", "arguments": "{}"}},
        ]
        with patch.object(agentic, "_execute_tool", side_effect=lambda n, a: f"out-{n}"):
            out = await agentic._run_tool_calls(_allow, calls)
        assert out == ["out-a", "out-b"]
        assert get_current_executed_tool_calls() == [
            {"tool": "a", "args": "{}"},
            {"tool": "b", "args": "{}"},
        ]


class TestAgenticHelpers:
    def test_temperature_only_when_configured(self, monkeypatch):
        from alfa.core.brain import agentic

        monkeypatch.setattr(agentic, "tool_temperature", lambda model: 0.42)
        payload = agentic._with_temperature({}, "gemini-3.5-pro")
        assert payload["temperature"] == 0.42

        monkeypatch.setattr(agentic, "tool_temperature", lambda model: None)
        payload = agentic._with_temperature({}, "gemini-3.5-pro")
        assert "temperature" not in payload

    def test_parallel_tools_disabled_by_env(self, monkeypatch):
        from alfa.core.brain import agentic

        monkeypatch.setenv("ALFA_PARALLEL_TOOLS", "false")
        assert agentic._parallel_tools_allowed(object()) is False

    def test_parallel_tools_requires_gate(self, monkeypatch):
        from alfa.core.brain import agentic

        monkeypatch.setenv("ALFA_PARALLEL_TOOLS", "true")
        assert agentic._parallel_tools_allowed(None) is False

    def test_parallel_tools_blocked_for_interactive_gate(self, monkeypatch):
        from alfa.core.brain import agentic

        monkeypatch.setenv("ALFA_PARALLEL_TOOLS", "true")
        gate = AsyncMock()
        with patch("alfa.core.perm.gate.gate_is_interactive", return_value=True):
            assert agentic._parallel_tools_allowed(gate) is False
        with patch("alfa.core.perm.gate.gate_is_interactive", return_value=False):
            assert agentic._parallel_tools_allowed(gate) is True


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__])
