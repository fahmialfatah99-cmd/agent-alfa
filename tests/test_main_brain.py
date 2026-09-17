"""
Unit test untuk main_brain router, skema tools OpenAI, dan kompaksi konteks.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main_brain


class TestBuildOpenAITools:
    def test_build_openai_tools_structure(self):
        tools_list = main_brain.build_openai_tools(safe_only=False)
        assert isinstance(tools_list, list)
        assert len(tools_list) > 20
        for t in tools_list:
            assert t.get("type") == "function"
            fn = t.get("function", {})
            assert "name" in fn
            assert "parameters" in fn
            assert "type" in fn["parameters"]

    def test_safe_only_subset(self):
        safe_tools = main_brain.build_openai_tools(safe_only=True)
        assert len(safe_tools) > 0
        assert len(safe_tools) <= len(main_brain.SAFE_TOOL_NAMES)
        for t in safe_tools:
            name = t["function"]["name"]
            assert name in main_brain.SAFE_TOOL_NAMES


class TestConvoCompaction:
    def test_compact_convo_under_budget(self):
        convo = [
            {"role": "user", "content": "Halo bot"},
            {"role": "assistant", "content": "Halo! Ada yang bisa dibantu?"},
        ]
        compacted = main_brain._compact_convo(convo)
        assert len(compacted) == 2
        assert compacted[0]["content"] == "Halo bot"

    def test_compact_convo_prunes_old_tool_messages(self, monkeypatch):
        monkeypatch.setattr(main_brain, "TOOL_CONTEXT_BUDGET", 500)
        monkeypatch.setattr(main_brain, "_TOOL_KEEP_RECENT", 2)

        convo = [
            {"role": "user", "content": "Mulai tugas"},
            {"role": "tool", "content": "X" * 300},  # tool 1 (lama -> dipotong)
            {"role": "tool", "content": "Y" * 300},  # tool 2 (lama -> dipotong)
            {"role": "tool", "content": "Z" * 300},  # tool 3 (recent 1 -> utuh)
            {"role": "tool", "content": "W" * 300},  # tool 4 (recent 2 -> utuh)
        ]

        main_brain._compact_convo(convo)
        assert "[output tool dipangkas" in convo[1]["content"]
        assert "[output tool dipangkas" in convo[2]["content"]
        assert convo[3]["content"] == "Z" * 300
        assert convo[4]["content"] == "W" * 300


class TestDocstringParser:
    def test_parse_args_docstring(self):
        doc = """
        Lakukan sesuatu yang keren.

        Args:
            query: Kata kunci pencarian produk.
            limit: Jumlah maksimal data yang ditarik.
            timeout: Batas waktu dalam detik.
        """
        args_doc = main_brain._parse_args_docstring(doc)
        assert args_doc.get("query") == "Kata kunci pencarian produk."
        assert args_doc.get("limit") == "Jumlah maksimal data yang ditarik."
        assert args_doc.get("timeout") == "Batas waktu dalam detik."
