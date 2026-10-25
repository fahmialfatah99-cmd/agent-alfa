"""Tool registry, decorator, catalog container, and schema inspection helpers.

Provides @register_tool for registering tools into a central catalog with
metadata and JSON/OpenAI schema inspection, plus backward-compatible domain
lookups and global AVAILABLE_TOOLS list.
"""

import inspect
import logging
import typing
from collections.abc import Callable
from typing import Any, ParamSpec, TypeVar

_P = ParamSpec("_P")
_R = TypeVar("_R")

logger = logging.getLogger("AgentTools.Registry")

# Registry catalog mapping tool name -> metadata dict
TOOL_REGISTRY: dict[str, dict[str, Any]] = {}

# Canonical list of all available tool callables
AVAILABLE_TOOLS: list[Callable] = []

# Canonical domain grouping
TOOL_DOMAINS: dict[str, list[str]] = {
    "system": [
        "get_system_stats",
        "execute_bash_command",
        "execute_python_sandbox",
        "control_linux_hardware",
        "scan_local_network",
        "ssh_execute_command",
        "wa_relay_send_from_telegram",
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
        "install_or_update_desktop_app",
        "artcraft_get_capabilities",
        "artcraft_run_cli",
        "artcraft_launch_gui",
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
        "schedule_daily_briefing_task",
    ],
    "office": [
        "generate_excel_spreadsheet",
        "generate_presentation_pptx",
        "record_material_to_sheets",
        "boq_consolidate_master_workbook",
        "boq_compare_and_diff",
        "boq_reconcile_with_field_reports",
        "boq_check_project_anomalies",
        "render_cluster_kml_map",
        "generate_daily_executive_briefing",
        "transcribe_field_voice_note",
        "parse_delivery_order_document",
        "consolidate_delivery_orders_to_stock_ledger",
        "calculate_material_return_and_scrap",
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

ALL_TOOL_NAMES: list[str] = sorted(
    {name for names in TOOL_DOMAINS.values() for name in names}
)

TOOL_DOMAIN_MAP: dict[str, str] = {
    name: domain for domain, names in TOOL_DOMAINS.items() for name in names
}


def get_tools_by_domain(domain: str) -> list[str]:
    """Mengembalikan daftar tool untuk domain tertentu."""
    return list(TOOL_DOMAINS.get(domain, []))


def get_domain_for_tool(tool_name: str) -> str | None:
    """Return domain/category for a given tool.

    Peta statis ``TOOL_DOMAINS`` adalah sumber kebenaran untuk domain;
    ``sync_domains_from_registry()`` menjaganya sinkron dengan registry.
    """
    return TOOL_DOMAIN_MAP.get(tool_name)


def sync_domains_from_registry() -> int:
    """Selaraskan peta domain statis dengan TOOL_REGISTRY.

    Registry adalah sumber kebenaran; peta statis (``TOOL_DOMAINS`` /
    ``TOOL_DOMAIN_MAP``) sebelumnya bisa stale sehingga tool muncul di
    domain yang salah. Tool yang ter-register dipindahkan ke kategori
    registry-nya, dan kategori itu ikut ditulis ke ``TOOL_DOMAIN_MAP``.

    Return jumlah tool yang dipindahkan.
    """
    moved = 0
    for tool_name, entry in list(TOOL_REGISTRY.items()):
        cat = entry.get("category")
        if not cat:
            continue
        for domain, tool_list in list(TOOL_DOMAINS.items()):
            if domain == cat:
                continue
            if tool_name in tool_list:
                tool_list.remove(tool_name)
                moved += 1
        target = TOOL_DOMAINS.setdefault(cat, [])
        if tool_name not in target:
            target.append(tool_name)
        TOOL_DOMAIN_MAP[tool_name] = cat
    for tool_list in TOOL_DOMAINS.values():
        tool_list.sort()
    # Buang domain yang jadi kosong setelah sinkronisasi (tool-nya pindah ke
    # kategori registry-nya) supaya tidak ada domain hantu.
    for domain in [d for d, lst in TOOL_DOMAINS.items() if not lst]:
        del TOOL_DOMAINS[domain]
    return moved


_JSON_TYPES = {int: "integer", float: "number", bool: "boolean", str: "string"}


def _json_type_for(annotation: Any) -> str:
    """Petakan anotasi Python ke tipe JSON Schema.

    Versi lama hanya memetakan `int/float/bool`; `list[str]`, `dict[str, Any]`
    dan `str | None` semuanya jatuh ke "string" — sehingga model mengirim
    "a,b,c" untuk parameter list dan tool gagal dengan TypeError.
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
        return "string"
    if origin is not None:
        if origin in (list, set, frozenset, tuple):
            return "array"
        if origin is dict:
            return "object"
        if origin is typing.Union or str(origin) == "types.UnionType":
            non_none = [a for a in args if a is not type(None)]
            if len(non_none) == 1:
                return _json_type_for(non_none[0])
            return "string"
        if isinstance(origin, type):
            return _JSON_TYPES.get(origin, "string")
    return "string"


def _parse_docstring_params(doc: str) -> dict[str, str]:
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


def _fn_to_schema(fn: Callable) -> dict[str, Any]:
    sig = inspect.signature(fn)
    doc = (inspect.getdoc(fn) or "").strip()
    desc_line = doc.splitlines()[0][:300] if doc else getattr(fn, "__name__", "tool")
    argdocs = _parse_docstring_params(doc)

    props: dict[str, Any] = {}
    required: list[str] = []
    parameters: list[dict[str, Any]] = []

    for pname, p in sig.parameters.items():
        if p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
            continue
        ann = p.annotation
        jtype = _json_type_for(ann)
        pdesc = argdocs.get(pname, pname)
        props[pname] = {"type": jtype, "description": pdesc}
        is_req = p.default is inspect.Parameter.empty
        if is_req:
            required.append(pname)
        parameters.append(
            {
                "name": pname,
                "type": str(ann) if ann != inspect.Parameter.empty else "Any",
                "default": str(p.default) if not is_req else None,
                "required": is_req,
                "description": pdesc,
            }
        )

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


def _register_entry(
    fn: Callable,
    *,
    name: str | None = None,
    category: str | None = None,
    description: str | None = None,
    tags: list[str] | None = None,
) -> str:
    """Daftarkan satu tool ke ``TOOL_REGISTRY`` + ``AVAILABLE_TOOLS``.

    Dipakai oleh dekorator :func:`register_tool` maupun
    :func:`sync_registry_from_available` (sinkronisasi daftar legacy).
    """
    actual_name = str(
        (name if isinstance(name, str) else None) or getattr(fn, "__name__", "")
    )
    actual_cat = category or get_domain_for_tool(actual_name) or "general"
    try:
        schema = _fn_to_schema(fn)
    except Exception:
        schema = {
            "name": actual_name,
            "short_description": (
                (fn.__doc__ or "").strip().splitlines()[0]
                if fn.__doc__
                else actual_name
            ),
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

    setattr(fn, "_tool_name", actual_name)  # noqa: B010
    setattr(fn, "_tool_category", actual_cat)  # noqa: B010
    setattr(fn, "_tool_description", actual_desc)  # noqa: B010
    setattr(fn, "_tool_tags", tags or [])  # noqa: B010

    # Add to AVAILABLE_TOOLS if not present
    if all(getattr(t, "__name__", None) != actual_name for t in AVAILABLE_TOOLS):
        AVAILABLE_TOOLS.append(fn)

    return actual_name


def register_tool(
    name: Any | None = None,
    category: str | None = None,
    description: str | None = None,
    tags: list[str] | None = None,
) -> Callable[[Callable[_P, _R]], Callable[_P, _R]]:
    """Decorator to register a tool function into TOOL_REGISTRY and AVAILABLE_TOOLS.

    Can be used with or without arguments:
        @register_tool
        def my_tool(...): ...

        @register_tool(category="system", tags=["os", "bash"])
        def my_tool(...): ...
    """

    def decorator(fn: Callable[_P, _R]) -> Callable[_P, _R]:
        _register_entry(
            fn,
            name=name if isinstance(name, str) else None,
            category=category,
            description=description,
            tags=tags,
        )
        return fn

    if callable(name):
        fn = name
        name = None
        return decorator(fn)
    return decorator


def sync_registry_from_available(tools: list[Callable]) -> list[str]:
    """Daftarkan tool yang ada di daftar legacy tapi belum ada di registry.

    ``TOOL_REGISTRY`` adalah sumber kebenaran tunggal. Tanpa sinkronisasi ini
    ada tool yang punya callable tapi tidak punya metadata (kategori, tags,
    schema) — sehingga tidak pernah muncul di ``get_tool_definitions()``.

    Return daftar nama tool yang baru terdaftar.
    """
    newly: list[str] = []
    for t in tools:
        fn_name = getattr(t, "__name__", None)
        if not fn_name or fn_name in TOOL_REGISTRY:
            continue
        _register_entry(t, name=fn_name)
        newly.append(fn_name)
    return newly


def sync_available_from_registry() -> list[str]:
    """Tambahkan tool yang sudah ter-register tapi belum ada di AVAILABLE_TOOLS.

    Tanpa ini, tool yang diregistrasi lewat dekorator (mis. seluruh layer
    RAG/vector) hilang dari daftar tool yang dilihat model.

    Return daftar nama tool yang ditambahkan.
    """
    present = {getattr(t, "__name__", None) for t in AVAILABLE_TOOLS}
    added: list[str] = []
    for tool_name, entry in TOOL_REGISTRY.items():
        if tool_name in present:
            continue
        fn = entry.get("func")
        if callable(fn):
            AVAILABLE_TOOLS.append(fn)
            present.add(tool_name)
            added.append(tool_name)
    return added


def get_tool(name: str) -> Callable | None:
    """Retrieve a tool callable by name from TOOL_REGISTRY or AVAILABLE_TOOLS."""
    if name in TOOL_REGISTRY:
        func = TOOL_REGISTRY[name]["func"]
        # `assert` dihapus saat python -O — gunakan pemeriksaan eksplisit.
        if not callable(func):
            return None
        return func  # type: ignore[no-any-return]
    for t in AVAILABLE_TOOLS:
        if getattr(t, "__name__", None) == name:
            return t
    return None


def get_tool_definitions(
    category: str | None = None, format: str = "dict"
) -> list[dict[str, Any]]:
    """Return tool definitions, optionally filtered by category.

    format: 'dict' (rich metadata dicts) or 'openai' (OpenAI function calling schemas).
    """
    results = []
    for _t_name, info in TOOL_REGISTRY.items():
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
