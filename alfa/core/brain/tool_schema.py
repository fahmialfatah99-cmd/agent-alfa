"""Python-tool -> OpenAI function-schema conversion + safe registry."""

import inspect
import logging
import types
import typing
from typing import Any

logger = logging.getLogger("MainBrain")

# Mapping tipe Python -> tipe JSON Schema.
#
# Hanya `int/float/bool` yang dipetakan versi lama; `list[str]`, `dict[str, Any]`
# dan `str | None` semuanya jatuh ke "string". Akibatnya model mengirim
# "a,b,c" untuk parameter list → TypeError → tool gagal.
_JSON_TYPES = {int: "integer", float: "number", bool: "boolean", str: "string"}


def _json_type_for(annotation: Any) -> str:
    """Petakan anotasi Python ke tipe JSON Schema.

    Menangani ``list``/``dict``/``Optional``/``Union``/``Literal``.
    """
    if annotation is inspect.Parameter.empty or annotation is None:
        return "string"

    if isinstance(annotation, type):
        if annotation is bool:
            return "boolean"
        if annotation is int:
            return "integer"
        if annotation is float:
            return "number"
        if annotation is str:
            return "string"
        if annotation is list:
            return "array"
        if annotation is dict:
            return "object"
        return "string"

    origin = typing.get_origin(annotation)
    args = typing.get_args(annotation)

    if origin is typing.Literal:
        # Enum literal → string (nilai spesifik diteruskan via description).
        return "string"
    if origin is not None:
        if origin in (list, set, frozenset, tuple):
            return "array"
        if origin is dict:
            return "object"
        if origin is typing.Union or origin is types.UnionType:
            # Optional[X] / X | None → pakai tipe non-None-nya.
            non_none = [a for a in args if a is not type(None)]
            if len(non_none) == 1:
                return _json_type_for(non_none[0])
            return "string"
        if isinstance(origin, type):
            return _JSON_TYPES.get(origin, "string")
    return "string"


def _parse_args_docstring(doc: str) -> dict[str, str]:
    """Ambil deskripsi argumen dari bagian 'Args:' docstring."""
    out: dict[str, str] = {}
    in_args = False
    for line in (doc or "").splitlines():
        stripped = line.strip()
        if stripped.rstrip(":").lower() in ("args", "parameters", "arguments"):
            in_args = True
            continue
        if in_args:
            if not stripped:
                continue
            if stripped.endswith(":") or stripped.split(":")[0].lower() in (
                "returns",
                "raises",
                "yields",
                "example",
                "examples",
            ):
                break
            if ":" in stripped:
                nm, desc = stripped.split(":", 1)
                out[nm.strip().split(" ")[0]] = desc.strip()
    return out


def _fn_to_openai_tool(fn) -> dict[str, Any]:
    sig = inspect.signature(fn)
    doc = inspect.getdoc(fn) or ""
    desc_line = doc.split("\n")[0][:300] if doc else fn.__name__
    argdocs = _parse_args_docstring(doc)

    props: dict[str, Any] = {}
    required: list[str] = []
    for pname, p in sig.parameters.items():
        if p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
            continue
        ann = p.annotation
        jtype = _json_type_for(ann)
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
