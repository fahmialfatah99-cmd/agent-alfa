import sys
from pathlib import Path
import os
import json
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tool_rag
import tools
import main_brain


def test_tool_rag_synonyms_and_intent():
    """Verify tool_rag expands Indonesian queries and boosts relevant tools."""
    pdf_query = "Tolong gabungkan berkas pdf ini dan beri sandi"
    ranked_pdf = tool_rag._rank_names(
        docs=["pdf_merge_documents combine pdf", "execute_bash_command run bash", "edit_image crop photo"],
        names=["pdf_merge_documents", "execute_bash_command", "edit_image"],
        user_text=pdf_query
    )
    assert "pdf_merge_documents" in ranked_pdf
    assert ranked_pdf[0] == "pdf_merge_documents"

    sys_query = "Cek penggunaan cpu dan matikan proses yang boros ram"
    ranked_sys = tool_rag._rank_names(
        docs=["get_system_stats check cpu ram", "kill_process terminate pid", "pdf_merge_documents combine pdf"],
        names=["get_system_stats", "kill_process", "pdf_merge_documents"],
        user_text=sys_query
    )
    assert "get_system_stats" in ranked_sys or "kill_process" in ranked_sys


def test_tool_rag_core_always():
    """Verify CORE_ALWAYS tools are never dropped even for unrelated queries."""
    unrelated_query = "Halo apa kabar?"
    selected = tool_rag._rank_names(
        docs=["some_special_tool special operation"],
        names=["some_special_tool"],
        user_text=unrelated_query
    )
    for core in tool_rag.CORE_ALWAYS:
        assert core in selected


def test_self_heal_hint_generation():
    """Verify generate_self_heal_hint produces appropriate guidance."""
    hint1 = tools.generate_self_heal_hint("execute_bash_command", "", stderr="bash: foobar_cmd: command not found")
    assert hint1 is not None
    assert "[SELF_HEAL_HINT]" in hint1
    assert "tidak ditemukan" in hint1

    hint2 = tools.generate_self_heal_hint("execute_python_sandbox", "", stderr="ModuleNotFoundError: No module named 'scipy'")
    assert hint2 is not None
    assert "[SELF_HEAL_HINT]" in hint2
    assert "scipy" in hint2

    hint3 = tools.generate_self_heal_hint("execute_python_sandbox", "", stderr="SyntaxError: invalid syntax")
    assert hint3 is not None
    assert "sintaks" in hint3


def test_execute_bash_self_heal_integration(monkeypatch):
    """Verify execute_bash_command includes self_heal_hint on failure."""
    monkeypatch.setenv("ALFA_ALLOW_HOST_EXEC", "true")
    res = tools.execute_bash_command("this_non_existent_binary_xyz_123", backend="host")
    assert res["status"] == "failed"
    assert res.get("self_heal_hint") is not None
    assert "[SELF_HEAL_HINT]" in res["self_heal_hint"]


def test_read_local_file_self_heal_integration():
    """Verify read_local_file includes self_heal_hint when file is missing."""
    res = tools.read_local_file("/non_existent_path_xyz_987654.txt")
    assert res["status"] == "error"
    assert res.get("self_heal_hint") is not None
    assert "search_workspace_files" in res["self_heal_hint"]


def test_main_brain_clean_json_args():
    """Verify _clean_json_args handles malformed and wrapped JSON correctly."""
    assert main_brain._clean_json_args('{"a": 1}') == {"a": 1}
    
    wrapped = "```json\n{\"command\": \"ls -la\"}\n```"
    assert main_brain._clean_json_args(wrapped) == {"command": "ls -la"}
    
    trailing = '{"items": [1, 2, ], "name": "test", }'
    assert main_brain._clean_json_args(trailing) == {"items": [1, 2], "name": "test"}
