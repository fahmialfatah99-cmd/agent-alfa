"""Python-tool -> OpenAI function-schema conversion + safe registry.

Implementasi pemetaan tipe & parsing docstring berada di
``alfa.core.schema_types`` — satu sumber kebenaran yang juga dipakai
``alfa.tools.registry`` (sebelumnya keduanya diduplikasi dan bisa
menghasilkan schema berbeda).
"""

import inspect
import logging
from typing import Any

from alfa.core.schema_types import (
    JSON_TYPES,
    annotation_for,
    json_type_for,
    parse_docstring_params,
)

logger = logging.getLogger("MainBrain")

#: Alias kompatibilitas (dipakai modul lain & test).
_json_type_for = json_type_for
_parse_args_docstring = parse_docstring_params
_JSON_TYPES = JSON_TYPES


def _fn_to_openai_tool(fn) -> dict[str, Any]:
    sig = inspect.signature(fn)
    doc = inspect.getdoc(fn) or ""
    desc_line = doc.split("\n")[0][:300] if doc else fn.__name__
    argdocs = parse_docstring_params(doc)

    props: dict[str, Any] = {}
    required: list[str] = []
    for pname, p in sig.parameters.items():
        if p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
            continue
        # Anotasi string (PEP 563) diresolusi agar tipe JSON benar.
        ann = annotation_for(fn, pname, p.annotation)
        jtype = json_type_for(ann)
        props[pname] = {"type": jtype, "description": argdocs.get(pname, pname)}
        if p.default is inspect.Parameter.empty:
            required.append(pname)

    return {
        "type": "function",
        "function": {
            "name": fn.__name__,
            "description": desc_line,
            "parameters": {
                "type": "object",
                "properties": props,
                ("required"): required,
            },
        },
    }


def build_openai_tools(safe_only: bool = False) -> list[dict[str, Any]]:
    """Konversi AVAILABLE_TOOLS ke skema tools OpenAI.

    safe_only=True membatasi ke subset aman utk agen swarm: riset web, baca
    file, sandbox eksekusi, dan memori — tanpa vault rahasia & kontrol desktop.
    """
    try:
        from alfa import tools as t

        fns = [f for f in t.AVAILABLE_TOOLS if callable(f)]
    except (ImportError, AttributeError, TypeError) as e:
        logger.error(f"build_openai_tools gagal: {e}")
        return []
    if safe_only:
        fns = [f for f in fns if getattr(f, "__name__", "") in SAFE_TOOL_NAMES]
    converted = []
    for fn in fns:
        try:
            converted.append(_fn_to_openai_tool(fn))
        except (ValueError, TypeError, AttributeError):
            continue
    return converted


# Subset aman utk agen swarm: cukup kuat utk riset/koding, minim risiko.
SAFE_TOOL_NAMES = {
    "web_search",
    "fetch_web_page_content",
    "deep_research_topic",
    "read_local_file",
    "search_workspace_files",
    "grep_workspace",
    "find_user_files",
    "index_codebase",
    "search_codebase",
    "execute_python_sandbox",
    "execute_bash_command",
    "save_knowledge_memory",
    "search_knowledge_memory",
    "get_system_stats",
}


def _find_tool(name: str):
    try:
        from alfa import tools as t

        for f in t.AVAILABLE_TOOLS:
            if getattr(f, "__name__", "") == name:
                return f
    except (ImportError, AttributeError, TypeError):
        pass
    return None
