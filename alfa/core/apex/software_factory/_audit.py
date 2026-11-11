"""Audit kualitas kode: AST Python & struktur HTML."""
from __future__ import annotations

import ast
import logging
import os
import re
from typing import Any

from alfa.core.apex.software_factory._heal import (
    _count_script_tags,
    _find_safe_close,
    _read_text_file,
)

logger = logging.getLogger(__name__)

_AST_ERR = (ValueError, TypeError, RecursionError, MemoryError)

def _audit_python_files(root: str, issues: list[str], passed: list[str], score_box: list[int]) -> list[dict[str, Any]]:
    """Recursively AST-check every `.py` file under `root`. Returns structured error locations."""
    locations: list[dict[str, Any]] = []
    for walk_root, _dirs, walk_files in os.walk(root):
        for fname in sorted(walk_files):
            if not fname.endswith(".py"):
                continue
            fpath = os.path.join(walk_root, fname)
            rel_f = os.path.relpath(fpath, root)
            src, decode_err = _read_text_file(fpath)
            if decode_err:
                issues.append(f"Unreadable source in {rel_f}: {decode_err}")
                score_box[0] -= 15
                continue
            try:
                ast.parse(src, filename=rel_f)
                passed.append(f"Backend AST Valid: {rel_f}")
            except SyntaxError as exc:
                issues.append(f"SyntaxError in {rel_f} line {exc.lineno}: {exc.msg}")
                locations.append(
                    {"file": rel_f, "line": exc.lineno or 1, "symbol": "SyntaxError", "lang": "python"}
                )
                score_box[0] -= 40
            except _AST_ERR as exc:
                issues.append(f"Failed to parse {rel_f}: {exc}")
                score_box[0] -= 20
    return locations

def _audit_html_files(
    root: str, issues: list[str], passed: list[str], score_box: list[int]
) -> list[dict[str, Any]]:
    """Recursively audit every `.html`/`.htm` file under `root` (DOM + script balance + primitives)."""
    for walk_root, _dirs, walk_files in os.walk(root):
        for fname in sorted(walk_files):
            if not fname.lower().endswith((".html", ".htm")):
                continue
            fpath = os.path.join(walk_root, fname)
            rel_f = os.path.relpath(fpath, root)
            h_src, decode_err = _read_text_file(fpath)
            if decode_err:
                issues.append(f"Unreadable HTML in {rel_f}: {decode_err}")
                score_box[0] -= 15
                continue
            h_low = h_src.lower()

            if "<html" in h_low and _find_safe_close(h_src, "html") != -1:
                passed.append(f"DOM Structure Valid: {rel_f}")
            else:
                issues.append(f"Incomplete DOM structure in {rel_f}")
                score_box[0] -= 20

            interactive_count = len(re.findall(r"<(button|input|select|textarea|form|a)\b", h_low))
            passed.append(f"Interactive UI Elements in {rel_f}: {interactive_count}")

            opens, closes = _count_script_tags(h_src)
            if opens != closes:
                issues.append(f"Mismatched <script> tags in {rel_f} (open={opens}, close={closes})")
                score_box[0] -= 25

            real_primitives = len(
                re.findall(
                    r"\b(fetch|addEventListener|getElementById|querySelector|localStorage|FileReader|"
                    r"createObjectURL|AudioContext|MediaRecorder|canvas)\b",
                    h_src,
                )
            )
            dummy_alerts = len(re.findall(r"\balert\s*\(", h_src))
            passed.append(
                f"Anti-Mockup Functional Primitives in {rel_f}: {real_primitives} real ops (alerts={dummy_alerts})"
            )
    return []
