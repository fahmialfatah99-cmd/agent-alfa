"""Jembatan tool MCP remote -> skema tool agent (opt-in, cache lokal).

Tool MCP tidak pernah diimpor otomatis saat startup: daftar tool diambil
hanya ketika operator memanggil ``mcp_list_tools``/``mcp_refresh_tools``,
lalu disimpan di cache JSON berizin 0600. Giliran agent hanya membaca cache
(tanpa network), sehingga latensi dan prompt bloat tetap terkendali.

Aktifkan injeksi skema dengan ``ALFA_MCP_DYNAMIC_TOOLS=true``. Eksekusi tetap
melewati permission gate yang sama; nama dinamis tidak terklasifikasi sehingga
dianggap HIGH (fail-closed).
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import time
from typing import Any

logger = logging.getLogger("MCPBridge")

STATE_DIR = os.path.join(os.path.expanduser("~"), ".alfa")
CACHE_FILE = os.path.join(STATE_DIR, "mcp_tools_cache.json")
_PREFIX = "mcp__"
_NAME_RE = re.compile(r"[^a-zA-Z0-9_-]+")
_ERR = (
    OSError,
    ValueError,
    TypeError,
    KeyError,
    IndexError,
    AttributeError,
    RuntimeError,
    TimeoutError,
    ConnectionError,
)


def enabled() -> bool:
    """True bila operator mengaktifkan injeksi tool MCP dinamis."""
    return os.getenv("ALFA_MCP_DYNAMIC_TOOLS", "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _load_cache() -> dict[str, Any]:
    try:
        with open(CACHE_FILE, encoding="utf-8") as handle:
            data = json.load(handle)
            return data if isinstance(data, dict) else {}
    except _ERR:
        return {}


def _save_cache(cache: dict[str, Any]) -> None:
    os.makedirs(STATE_DIR, exist_ok=True)
    payload = json.dumps(cache, indent=2, ensure_ascii=False)
    fd = -1
    tmp_path: str | None = None
    try:
        fd, tmp_path = tempfile.mkstemp(
            dir=STATE_DIR, prefix=".mcp_tools-", suffix=".tmp"
        )
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            try:
                os.fsync(handle.fileno())
            except OSError:
                pass
        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, CACHE_FILE)
        tmp_path = None
    finally:
        if tmp_path is not None:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def _clean_part(value: str, limit: int = 28) -> str:
    cleaned = _NAME_RE.sub("_", str(value or "").strip()).strip("_")
    return (cleaned or "tool")[:limit]


def dynamic_name(server: str, tool: str) -> str:
    """Nama tool global yang aman untuk OpenAI/Anthropic (<=64 char)."""
    name = f"{_PREFIX}{_clean_part(server)}__{_clean_part(tool, 32)}"
    return name[:64]


def refresh_tools(server_id: str, timeout: float = 20.0) -> dict[str, Any]:
    """Ambil daftar tool dari satu server MCP dan simpan ke cache."""
    sid = str(server_id or "").strip().lower()
    if not sid:
        return {"status": "error", "message": "server wajib diisi"}
    try:
        from alfa.mcp import client as mcp_client

        listed = mcp_client.list_tools_sync(sid, timeout=timeout)
    except _ERR as exc:
        return {"status": "error", "message": f"{type(exc).__name__}: {exc}"}
    if listed.get("status") != "success":
        return listed

    used: set[str] = set()
    tools: list[dict[str, Any]] = []
    for item in listed.get("tools") or []:
        original = str((item or {}).get("name") or "").strip()
        if not original:
            continue
        name = dynamic_name(sid, original)
        base = name
        suffix = 2
        while name in used:
            name = f"{base[:58]}_{suffix}"
            suffix += 1
        used.add(name)
        schema = item.get("input")
        if not isinstance(schema, dict) or schema.get("type") != "object":
            schema = {"type": "object", "properties": {}}
        tools.append(
            {
                "name": original,
                "dynamic_name": name,
                "description": str(item.get("description") or original)[:300],
                "input": schema,
            }
        )

    cache = _load_cache()
    cache[sid] = {"updated_at": time.time(), "tools": tools}
    try:
        _save_cache(cache)
    except _ERR as exc:
        logger.warning("[MCPBridge] cache gagal disimpan: %s", exc)
        return {"status": "error", "message": f"cache gagal disimpan: {exc}"}

    return {
        "status": "success",
        "server": sid,
        "total_tools": len(tools),
        "tools": [
            {
                "name": tool["name"],
                "dynamic_name": tool["dynamic_name"],
                "description": tool["description"],
            }
            for tool in tools
        ],
    }


def refresh_connected() -> dict[str, Any]:
    """Refresh seluruh server MCP yang berstatus connected."""
    try:
        from alfa.mcp import client as mcp_client

        status = mcp_client.connection_status()
    except _ERR as exc:
        return {"status": "error", "message": f"{type(exc).__name__}: {exc}"}

    results: list[dict[str, Any]] = []
    for entry in status.get("servers") or []:
        if not entry.get("connected"):
            continue
        results.append(refresh_tools(str(entry.get("server") or "")))
    return {
        "status": "success",
        "refreshed": len(results),
        "servers": results,
    }


def cached_tools(server_id: str = "") -> list[dict[str, Any]]:
    """Baca cache saja (tanpa network)."""
    cache = _load_cache()
    sid = str(server_id or "").strip().lower()
    if sid:
        entry = cache.get(sid) or {}
        return list(entry.get("tools") or [])
    tools: list[dict[str, Any]] = []
    for entry in cache.values():
        if isinstance(entry, dict):
            tools.extend(entry.get("tools") or [])
    return tools


def build_tool_schemas(server_id: str = "") -> list[dict[str, Any]]:
    """Skema tool OpenAI untuk seluruh tool MCP yang tercache."""
    if not enabled():
        return []
    try:
        max_tools = max(1, int(os.getenv("ALFA_MCP_MAX_TOOLS", "32")))
    except (TypeError, ValueError):
        max_tools = 32

    schemas: list[dict[str, Any]] = []
    seen: set[str] = set()
    for tool in cached_tools(server_id):
        if len(schemas) >= max_tools:
            break
        name = str(tool.get("dynamic_name") or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        params = tool.get("input")
        if not isinstance(params, dict):
            params = {"type": "object", "properties": {}}
        try:
            # Skema raksasa dari server pihak ketiga tidak boleh membanjiri
            # prompt; jatuh ke skema kosong (tool tetap bisa dipanggil).
            if len(json.dumps(params, ensure_ascii=False, default=str)) > 6000:
                params = {"type": "object", "properties": {}}
        except (TypeError, ValueError):
            params = {"type": "object", "properties": {}}
        schemas.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": (
                        f"[MCP] {tool.get('description') or tool.get('name') or name}"
                    )[:300],
                    "parameters": params,
                },
            }
        )
    return schemas


def split_dynamic_name(name: str) -> tuple[str, str] | None:
    """Pecah ``mcp__server__tool`` -> ``(server, dynamic_tool_part)``."""
    if not str(name or "").startswith(_PREFIX):
        return None
    parts = str(name).split("__", 2)
    if len(parts) != 3 or not parts[1] or not parts[2]:
        return None
    return parts[1], parts[2]


def _original_tool(server: str, name: str) -> str | None:
    for tool in cached_tools(server):
        if str(tool.get("dynamic_name") or "") == name:
            return str(tool.get("name") or "")
    return None


def call_dynamic(name: str, args: dict[str, Any] | None = None, timeout: float = 45.0) -> str:
    """Eksekusi tool MCP dinamis dan kembalikan JSON string untuk agent."""
    parsed = split_dynamic_name(name)
    if parsed is None:
        return json.dumps(
            {"status": "error", "message": f"nama tool dinamis tidak valid: {name}"},
            ensure_ascii=False,
        )
    if not enabled():
        return json.dumps(
            {
                "status": "error",
                "message": (
                    "Tool MCP dinamis nonaktif. Set ALFA_MCP_DYNAMIC_TOOLS=true "
                    "lalu jalankan mcp_refresh_tools."
                ),
            },
            ensure_ascii=False,
        )
    server, _dynamic_part = parsed
    original = _original_tool(server, name)
    if not original:
        return json.dumps(
            {
                "status": "error",
                "message": (
                    f"Tool dinamis '{name}' tidak ada di cache. Jalankan "
                    "mcp_refresh_tools untuk menyegarkan daftar tool."
                ),
            },
            ensure_ascii=False,
        )
    try:
        from alfa.mcp import client as mcp_client

        result = mcp_client.call_tool_sync(
            server, original, args or {}, timeout=timeout
        )
    except _ERR as exc:
        result = {"status": "error", "message": f"{type(exc).__name__}: {exc}"}
    return json.dumps(result, ensure_ascii=False, default=str)


__all__ = [
    "build_tool_schemas",
    "call_dynamic",
    "cached_tools",
    "dynamic_name",
    "enabled",
    "refresh_connected",
    "refresh_tools",
    "split_dynamic_name",
]
