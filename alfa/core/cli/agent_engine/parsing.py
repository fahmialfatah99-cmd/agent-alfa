"""Tool-call extraction from LLM text (fences, raw JSON, fn syntax, repair)."""

from __future__ import annotations

import ast
import json
import re
from typing import Any


class ToolCallParserMixin:
    """Parse ```tool_call blocks and function-syntax calls into tool requests."""

    @staticmethod
    def _parse_relaxed_json(raw: str) -> dict[str, Any] | None:
        """Parse JSON with error tolerance for single quotes, trailing commas, and unescaped newlines."""
        cleaned = raw.strip()
        try:
            val = json.loads(cleaned)
            if isinstance(val, dict):
                return val
        except Exception:
            pass

        # Cleanup trailing commas
        cleaned_no_trailing = re.sub(r",\s*([}\]])", r"\1", cleaned)
        try:
            val = json.loads(cleaned_no_trailing)
            if isinstance(val, dict):
                return val
        except Exception:
            pass

        # Try ast.literal_eval for Python dictionary literals with single quotes
        try:
            val = ast.literal_eval(cleaned)
            if isinstance(val, dict):
                return val
        except Exception:
            pass

        # Convert single quotes around keys and values
        try:
            sq_fixed = re.sub(
                r"(?<=[{,\s])'([^']+)'(?=\s*:)", r'"\1"', cleaned_no_trailing
            )
            sq_fixed = re.sub(r":\s*'([^']*)'(?=[,}\s])", r': "\1"', sq_fixed)
            val = json.loads(sq_fixed)
            if isinstance(val, dict):
                return val
        except Exception:
            pass

        return None

    @staticmethod
    def _repair_truncated_json(text: str) -> str | None:
        """Attempt to repair a TRUNCATED trailing JSON object (unclosed fence).

        Closes an unterminated string, then appends missing `}`/`]` closers.
        Returns the repaired candidate, or None if nothing was truncated.
        """
        start = text.find("{")
        if start < 0:
            return None
        frag = text[start:]
        out: list[str] = []
        depth_brace = 0
        depth_brack = 0
        in_str = False
        str_char = ""
        escape = False
        truncated = False
        for c in frag:
            out.append(c)
            if in_str:
                if escape:
                    escape = False
                elif c == "\\":
                    escape = True
                elif c == str_char:
                    in_str = False
            elif c in ("'", '"'):
                in_str = True
                str_char = c
            elif c == "{":
                depth_brace += 1
            elif c == "}":
                depth_brace -= 1
            elif c == "[":
                depth_brack += 1
            elif c == "]":
                depth_brack -= 1
            if depth_brace < 0 or depth_brack < 0:
                return None
        if in_str:
            out.append(str_char)
            truncated = True
        if depth_brace > 0 or depth_brack > 0:
            truncated = True
        if not truncated:
            return None
        out.append("]" * depth_brack)
        out.append("}" * depth_brace)
        return "".join(out)

    @staticmethod
    def _find_balanced_json_blocks(text: str) -> list[str]:
        """Find all top-level balanced JSON { ... } blocks in text, properly respecting strings."""
        blocks: list[str] = []
        i = 0
        n = len(text)
        while i < n:
            if text[i] == "{":
                start = i
                depth = 0
                in_str = False
                str_char = ""
                escape = False
                while i < n:
                    c = text[i]
                    if in_str:
                        if escape:
                            escape = False
                        elif c == "\\":
                            escape = True
                        elif c == str_char:
                            in_str = False
                    else:
                        if c in ('"', "'"):
                            in_str = True
                            str_char = c
                        elif c == "{":
                            depth += 1
                        elif c == "}":
                            depth -= 1
                            if depth == 0:
                                blocks.append(text[start : i + 1])
                                break
                    i += 1
            i += 1
        return blocks

    def _extract_tool_calls(self, text: str) -> list[dict[str, Any]]:
        """Extract tool call requests from LLM text with resilient balanced-braces & relaxed parsing."""
        calls: list[dict[str, Any]] = []

        # If LLM provided Final Answer, only parse tool calls before the final answer text
        search_text = text
        if "Final Answer:" in text:
            search_text = text.split("Final Answer:", 1)[0]
            if not search_text.strip():
                return []

        # 1. Search in code blocks ```tool_call ... ```, ```json ... ```, or <tool_call> ... </tool_call>
        code_block_patterns = [
            r"```(?:tool_call|json)?\s*([\s\S]*?)\s*```",
            r"<tool_call>\s*([\s\S]*?)\s*</tool_call>",
        ]
        for pat in code_block_patterns:
            for m in re.finditer(pat, search_text, re.DOTALL):
                block_text = m.group(1).strip()
                for json_candidate in self._find_balanced_json_blocks(block_text):
                    parsed = self._parse_relaxed_json(json_candidate)
                    if parsed and "tool" in parsed:
                        if not any(
                            c.get("tool") == parsed.get("tool")
                            and c.get("args") == parsed.get("args")
                            for c in calls
                        ):
                            calls.append(parsed)

        # 2. Raw balanced JSON blocks anywhere in search_text
        if not calls:
            for json_candidate in self._find_balanced_json_blocks(search_text):
                parsed = self._parse_relaxed_json(json_candidate)
                if parsed and "tool" in parsed:
                    if not any(
                        c.get("tool") == parsed.get("tool")
                        and c.get("args") == parsed.get("args")
                        for c in calls
                    ):
                        calls.append(parsed)

        # 3. Function call syntax: tool_name(arg1=val1, ...) or tool_name("arg1")
        if not calls:
            fn_pat = r"\b([a-zA-Z0-9_]+)\s*\(([\s\S]*?)\)"
            known_simple = {
                "list_directory",
                "read_file",
                "find_files",
                "search_code",
                "write_file",
                "patch_file",
                "run_command",
                "web_search",
                "fetch_web_page_content",
                "universal_deep_scraper",
                "audit_website_security",
                "get_system_stats",
                "vault_get_secret",
                "vault_store_secret",
                "vault_list_secrets",
                "edit_file_precise",
                "apply_unified_diff",
                "grep_workspace",
                "search_workspace_files",
                "index_codebase",
                "search_codebase",
                "lsp_find_symbol_definition",
                "lsp_find_symbol_references",
                "lsp_analyze_module_hierarchy",
                "git_operations",
                "read_local_file",
                "write_local_file",
                "todo_add",
                "todo_list",
                "todo_done",
            }
            for m in re.finditer(fn_pat, search_text):
                t_name = m.group(1)
                if t_name not in known_simple:
                    continue
                raw_args = m.group(2).strip()

                parsed_args: dict[str, Any] = {}
                kw_matches = re.findall(
                    r'([a-zA-Z0-9_]+)\s*=\s*([^\s,]+|"[^"]*"|\'[^\']*\')', raw_args
                )
                if kw_matches:
                    for k, v in kw_matches:
                        clean_v = v.strip().strip("'\"")
                        if clean_v.isdigit():
                            parsed_args[k] = int(clean_v)
                        else:
                            parsed_args[k] = clean_v
                else:
                    clean_single = raw_args.strip().strip("'\"")
                    if t_name == "list_directory":
                        parsed_args = {"path": clean_single or "."}
                    elif t_name == "read_file":
                        parsed_args = {
                            "path": clean_single,
                            "start_line": 1,
                            "end_line": 200,
                        }
                    elif t_name == "find_files":
                        parsed_args = {"pattern": clean_single or "*"}
                    elif t_name == "search_code":
                        parsed_args = {"query": clean_single}
                    elif t_name == "run_command":
                        parsed_args = {"command": clean_single}
                    elif t_name == "grep_workspace":
                        parsed_args = {"query": clean_single}
                    elif t_name == "search_workspace_files":
                        parsed_args = {"pattern": clean_single}
                    elif t_name == "search_codebase":
                        parsed_args = {"query": clean_single}
                    elif t_name == "index_codebase":
                        parsed_args = {"repo_path": clean_single or "."}
                    elif t_name in (
                        "lsp_find_symbol_definition",
                        "lsp_find_symbol_references",
                    ):
                        parsed_args = {"symbol_name": clean_single}
                    elif t_name == "lsp_analyze_module_hierarchy":
                        parsed_args = {"target_file": clean_single}
                    elif t_name == "read_local_file":
                        parsed_args = {"file_path": clean_single}
                    elif t_name == "todo_add":
                        parsed_args = {"task": clean_single}
                    elif t_name == "todo_done":
                        parsed_args = (
                            {"todo_id": int(clean_single)}
                            if clean_single.isdigit()
                            else {}
                        )
                    elif t_name == "todo_list":
                        parsed_args = {}
                    elif t_name == "web_search":
                        parsed_args = {"query": clean_single}
                    elif t_name == "fetch_web_page_content":
                        parsed_args = {"url": clean_single}
                    elif t_name == "audit_website_security":
                        parsed_args = {"url": clean_single}
                    elif t_name == "vault_get_secret":
                        parsed_args = {"secret_name": clean_single}
                    elif t_name in ("get_system_stats", "vault_list_secrets"):
                        parsed_args = {}

                if t_name:
                    calls.append({"tool": t_name, "args": parsed_args})

        # 4. Truncated tool call (unclosed ```tool_call fence, cut off mid-JSON):
        # repair trailing fragment and accept it if it parses to a tool call.
        if not calls:
            tail = search_text
            for opener in ("```tool_call", "<tool_call>"):
                if opener in search_text:
                    tail = search_text.rsplit(opener, 1)[1]
                    break
            repaired = self._repair_truncated_json(tail)
            if repaired:
                parsed = self._parse_relaxed_json(repaired)
                if parsed and "tool" in parsed:
                    calls.append(parsed)

        return calls
