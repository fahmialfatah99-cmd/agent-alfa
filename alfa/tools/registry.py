"""Tool registry, decorator, catalog container, and schema inspection helpers.

Provides @register_tool for registering tools into a central catalog with
metadata and JSON/OpenAI schema inspection, plus backward-compatible domain
lookups and global AVAILABLE_TOOLS list.
"""

import functools
import inspect
import logging
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("AgentTools.Registry")

# Registry catalog mapping tool name -> metadata dict
TOOL_REGISTRY: Dict[str, Dict[str, Any]] = {}

# Canonical list of all available tool callables
AVAILABLE_TOOLS: List[Callable] = []

# Canonical domain grouping
TOOL_DOMAINS: Dict[str, List[str]] = {
    "system": [
        "get_system_stats",
        "execute_bash_command",
        "execute_python_sandbox",
        "control_linux_hardware",
        "scan_local_network",
        "ssh_execute_command",
    ],
    "file": [
        "read_local_file",
        "write_local_file",
        "edit_file_precise",
        "apply_unified_diff",
        "search_workspace_files",
        "grep_workspace",
        "compress_folder_to_zip",
        "send_file_to_chat",
        "index_codebase",
        "search_codebase",
        "query_database",
    ],
    "web": [
        "web_search",
        "fetch_web_page_content",
        "browser_open_url",
        "browser_click_element",
        "browser_type_text",
        "browser_capture_screenshot",
        "browser_close_tab",
        "scrape_real_product_data",
        "scrape_large_scale_batch",
        "marketplace_search_products",
    ],
    "pdf": [
        "pdf_extract_full_text",
        "pdf_merge_documents",
        "pdf_split_document",
        "pdf_compress_and_optimize",
        "pdf_convert_to_images",
        "pdf_rotate_pages",
        "pdf_encrypt_password",
        "pdf_decrypt_password",
        "pdf_apply_watermark_text",
        "pdf_insert_page_numbers",
        "pdf_inspect_metadata",
        "images_convert_to_pdf",
        "generate_pdf_report",
    ],
    "media": [
        "capture_desktop_screenshot",
        "capture_webcam_frame",
        "record_desktop_screen",
        "desktop_click_coordinate",
        "desktop_launch_app",
        "desktop_type_keys",
        "show_desktop_notification",
        "read_clipboard",
        "write_to_clipboard",
        "generate_promo_video_from_images",
    ],
    "memory": [
        "save_knowledge_memory",
        "search_knowledge_memory",
    ],
    "scheduler": [
        "schedule_reminder",
        "add_recurring_task",
        "cancel_recurring_task",
        "list_recurring_tasks",
    ],
    "office": [
        "generate_excel_spreadsheet",
        "generate_presentation_pptx",
    ],
    "agent": [
        "manage_api_keys",
        "manage_custom_agents",
        "spawn_background_subagent",
        "check_subagent_status",
    ],
    "affiliate": [
        "affiliate_hunt_trending_products",
        "affiliate_generate_viral_content",
        "affiliate_broadcast_deal",
        "affiliate_list_campaigns",
    ],
}

ALL_TOOL_NAMES: List[str] = sorted({name for names in TOOL_DOMAINS.values() for name in names})

TOOL_DOMAIN_MAP: Dict[str, str] = {
    name: domain
    for domain, names in TOOL_DOMAINS.items()
    for name in names
}


def get_tools_by_domain(domain: str) -> List[str]:
    """Mengembalikan daftar tool untuk domain tertentu."""
    return list(TOOL_DOMAINS.get(domain, []))


def get_domain_for_tool(tool_name: str) -> Optional[str]:
    """Mengembalikan domain untuk tool tertentu."""
    return TOOL_DOMAIN_MAP.get(tool_name)


_JSON_TYPES = {int: "integer", float: "number", bool: "boolean"}


def _parse_docstring_params(doc: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
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
                "returns", "raises", "yields", "example", "examples"
            ):
                break
            if ":" in stripped:
                nm, desc = stripped.split(":", 1)
                out[nm.strip().split(" ")[0]] = desc.strip()
    return out


def _fn_to_schema(fn: Callable) -> Dict[str, Any]:
    sig = inspect.signature(fn)
    doc = (inspect.getdoc(fn) or "").strip()
    desc_line = doc.splitlines()[0][:300] if doc else getattr(fn, "__name__", "tool")
    argdocs = _parse_docstring_params(doc)

    props: Dict[str, Any] = {}
    required: List[str] = []
    parameters: List[Dict[str, Any]] = []

    for pname, p in sig.parameters.items():
        if p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
            continue
        ann = p.annotation
        jtype = _JSON_TYPES.get(ann, "string") if isinstance(ann, type) else \
            _JSON_TYPES.get(getattr(ann, "__origin__", None), "string")
        pdesc = argdocs.get(pname, pname)
        props[pname] = {"type": jtype, "description": pdesc}
        is_req = p.default is inspect.Parameter.empty
        if is_req:
            required.append(pname)
        parameters.append({
            "name": pname,
            "type": str(ann) if ann != inspect.Parameter.empty else "Any",
            "default": str(p.default) if not is_req else None,
            "required": is_req,
            "description": pdesc,
        })

    name = getattr(fn, "__name__", str(fn))
    return {
        "name": name,
        "short_description": desc_line,
        "full_docstring": doc,
        "signature": f"{name}{str(sig)}",
        "parameters": parameters,
        "openai_spec": {
            "type": "function",
            "function": {
                "name": name,
                "description": desc_line,
                "parameters": {
                    "type": "object",
                    "properties": props,
                    "required": required,
                },
            },
        },
    }


def register_tool(
    name: Optional[Any] = None,
    category: Optional[str] = None,
    description: Optional[str] = None,
    tags: Optional[List[str]] = None,
):
    """Decorator to register a tool function into TOOL_REGISTRY and AVAILABLE_TOOLS.

    Can be used with or without arguments:
        @register_tool
        def my_tool(...): ...

        @register_tool(category="system", tags=["os", "bash"])
        def my_tool(...): ...
    """
    def decorator(fn: Callable) -> Callable:
        actual_name = (name if isinstance(name, str) else None) or getattr(fn, "__name__", "")
        actual_cat = category or get_domain_for_tool(actual_name) or "general"
        try:
            schema = _fn_to_schema(fn)
        except Exception:
            schema = {
                "name": actual_name,
                "short_description": (fn.__doc__ or "").strip().splitlines()[0] if fn.__doc__ else actual_name,
                "full_docstring": fn.__doc__ or "",
                "signature": f"{actual_name}()",
                "parameters": [],
                "openai_spec": {"type": "function", "function": {"name": actual_name}},
            }
        actual_desc = description or schema["short_description"]

        entry = {
            "name": actual_name,
            "func": fn,
            "category": actual_cat,
            "description": actual_desc,
            "tags": tags or [],
            "schema": schema,
        }
        TOOL_REGISTRY[actual_name] = entry

        setattr(fn, "_tool_name", actual_name)
        setattr(fn, "_tool_category", actual_cat)
        setattr(fn, "_tool_description", actual_desc)
        setattr(fn, "_tool_tags", tags or [])

        # Add to AVAILABLE_TOOLS if not present
        if all(getattr(t, "__name__", None) != actual_name for t in AVAILABLE_TOOLS):
            AVAILABLE_TOOLS.append(fn)

        return fn

    if callable(name):
        fn = name
        name = None
        return decorator(fn)
    return decorator


def get_tool(name: str) -> Optional[Callable]:
    """Retrieve a tool callable by name from TOOL_REGISTRY or AVAILABLE_TOOLS."""
    if name in TOOL_REGISTRY:
        return TOOL_REGISTRY[name]["func"]
    for t in AVAILABLE_TOOLS:
        if getattr(t, "__name__", None) == name:
            return t
    return None


def get_tool_definitions(
    category: Optional[str] = None, format: str = "dict"
) -> List[Dict[str, Any]]:
    """Return tool definitions, optionally filtered by category.

    format: 'dict' (rich metadata dicts) or 'openai' (OpenAI function calling schemas).
    """
    results = []
    for t_name, info in TOOL_REGISTRY.items():
        if category and info.get("category") != category:
            continue
        if format == "openai":
            results.append(info["schema"]["openai_spec"])
        else:
            item = dict(info["schema"])
            item["category"] = info.get("category")
            item["tags"] = info.get("tags", [])
            results.append(item)
    return results


__all__ = [
    "TOOL_REGISTRY",
    "AVAILABLE_TOOLS",
    "TOOL_DOMAINS",
    "ALL_TOOL_NAMES",
    "TOOL_DOMAIN_MAP",
    "get_tools_by_domain",
    "get_domain_for_tool",
    "register_tool",
    "get_tool",
    "get_tool_definitions",
]
