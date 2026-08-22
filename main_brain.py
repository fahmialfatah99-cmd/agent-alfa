"""
MAIN BRAIN ENGINE — otak utama lintas-provider untuk ALFA.

Memungkinkan agent Telegram/Web berjalan di provider APA PUN yang kuncinya
diaktivasi di vault (OpenRouter/Ox Alpha, custom gateway seperti Tokenra,
NVIDIA, dll) dengan TETAP memakai 130+ tools yang sama.

Cara kerja:
- Pointer 'main_brain_key_id' di tabel system_settings menentukan kunci mana
  yang menjadi otak utama (disetel otomatis saat mengaktifkan kunci).
- Provider 'gemini'      : jalur native auto function-calling (di bot.py).
- Provider lainnya       : jalur OpenAI-compatible di modul ini, lengkap dengan
                           agentic loop manual (panggil tool -> kirim hasil ->
                           ulangi sampai jawaban final).

Semua fungsi fail-safe: kegagalan mengembalikan None agar pemanggil bisa
fallback ke Gemini.
"""

import os
import json
import inspect
import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger("MainBrain")

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
MAX_ITERATIONS = 8          # batas putaran tool-call per turn
MAX_TOOL_OUTPUT = 4000      # potong output tool agar konteks efisien
TOOL_EXEC_TIMEOUT = 300     # rapat/swarm bisa berjalan beberapa menit


# ── Resolusi otak utama ──────────────────────────────────────────────────────
def get_main_brain() -> Dict[str, Any]:
    """
    Return dict: {provider, api_key, model, base_url, key_id, label}
    Prioritas: pointer main_brain_key_id -> kunci gemini aktif di vault -> .env
    """
    import database
    kid = database.get_main_brain_key_id()
    if kid:
        try:
            with database.get_sync_db() as conn:
                row = conn.execute(
                    "SELECT id, provider, api_key, default_model, base_url "
                    "FROM api_keys WHERE id = ?", (kid,)
                ).fetchone()
            if row:
                model = row["default_model"]
                override = database.get_main_brain_model()
                if override:
                    model = override
                return {
                    "provider": row["provider"].lower(),
                    "api_key": row["api_key"],
                    "model": model,
                    "base_url": row["base_url"] or "",
                    "key_id": row["id"],
                    "label": f"brain#{row['id']}",
                }
        except Exception as e:
            logger.warning(f"main brain pointer unreadable: {e}")

    # Fallback: kunci gemini aktif di vault, lalu .env
    try:
        gk = database.get_active_api_key_sync("gemini")
    except Exception:
        gk = None
    if gk and (gk.get("api_key") or "").strip():
        return {
            "provider": "gemini",
            "api_key": gk["api_key"].strip(),
            "model": gk.get("default_model") or "",
            "base_url": "",
            "key_id": gk.get("id"),
            "label": f"brain#{gk.get('id')}",
        }

    from dotenv import load_dotenv
    load_dotenv(os.path.join(PROJECT_DIR, ".env"))
    env_key = os.getenv("GEMINI_API_KEY", "").strip()
    return {
        "provider": "gemini" if env_key else "none",
        "api_key": env_key,
        "model": os.getenv("GEMINI_MODEL", ""),
        "base_url": "",
        "key_id": None,
        "label": "gemini-env",
    }


# ── Konversi tool Python -> skema OpenAI function ────────────────────────────
_JSON_TYPES = {int: "integer", float: "number", bool: "boolean"}


def _parse_args_docstring(doc: str) -> Dict[str, str]:
    """Ambil deskripsi argumen dari bagian 'Args:' docstring."""
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


def _fn_to_openai_tool(fn) -> Dict[str, Any]:
    sig = inspect.signature(fn)
    doc = inspect.getdoc(fn) or ""
    desc_line = doc.split("\n")[0][:300] if doc else fn.__name__
    argdocs = _parse_args_docstring(doc)

    props: Dict[str, Any] = {}
    required: List[str] = []
    for pname, p in sig.parameters.items():
        if p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
            continue
        ann = p.annotation
        jtype = _JSON_TYPES.get(ann, "string") if isinstance(ann, type) else \
            _JSON_TYPES.get(getattr(ann, "__origin__", None), "string")
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


def build_openai_tools() -> List[Dict[str, Any]]:
    """Konversi seluruh AVAILABLE_TOOLS ke skema tools OpenAI."""
    try:
        import tools as t
        fns = [f for f in t.AVAILABLE_TOOLS if callable(f)]
    except Exception as e:
        logger.error(f"build_openai_tools gagal: {e}")
        return []
    converted = []
    for fn in fns:
        try:
            converted.append(_fn_to_openai_tool(fn))
        except Exception:
            continue
    return converted


def _find_tool(name: str):
    try:
        import tools as t
        for f in t.AVAILABLE_TOOLS:
            if getattr(f, "__name__", "") == name:
                return f
    except Exception:
        pass
    return None


def _execute_tool(name: str, arguments_json: str) -> str:
    import asyncio
    fn = _find_tool(name)
    if fn is None:
        return f"[ERROR] Tool '{name}' tidak ditemukan."
    try:
        args = json.loads(arguments_json or "{}")
    except Exception:
        return "[ERROR] Argumen tool bukan JSON valid."

    def _call():
        try:
            return fn(**args)
        except Exception as e:
            return f"[ERROR tool] {e}"

    try:
        # Jalankan di thread terpisah agar event loop tetap hidup
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            fut = pool.submit(_call)
            raw = fut.result(timeout=TOOL_EXEC_TIMEOUT)
    except Exception as e:
        return f"[ERROR eksekusi] {e}"

    if not isinstance(raw, str):
        raw = json.dumps(raw, ensure_ascii=False, default=str)
    return raw[:MAX_TOOL_OUTPUT]


# ── Agentic loop OpenAI-compatible ───────────────────────────────────────────
async def run_openai_agentic_turn(
    provider: str,
    base_url: str,
    api_key: str,
    model: str,
    system_instruction: str,
    user_text: str,
    history: Optional[List[Dict[str, str]]] = None,
    key_id=None,
    key_label: str = "",
    context: str = "telegram_chat",
) -> Optional[str]:
    """
    Satu turn agentik penuh di provider OpenAI-compatible:
    kirim pesan + 130 tools -> eksekusi tool_calls -> ulangi sampai jawaban final.
    Return teks jawaban, atau None bila gagal total (pemanggil bisa fallback).
    """
    try:
        import httpx
        import token_usage
        tools_schema = build_openai_tools()

        messages: List[Dict[str, Any]] = [{"role": "system", "content": system_instruction}]
        for h in (history or [])[-10:]:
            role = "assistant" if h.get("role") == "model" else "user"
            if h.get("content"):
                messages.append({"role": role, "content": h["content"]})
        messages.append({"role": "user", "content": user_text})

        url = f"{(base_url or '').rstrip('/')}/chat/completions"
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        payload_base = {"model": model, "messages": messages, "temperature": 0.75}

        async with httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=15.0)) as client:
            convo = list(messages)
            for iteration in range(MAX_ITERATIONS):
                payload = dict(payload_base, messages=convo, tools=tools_schema)
                res = await client.post(url, headers=headers, json=payload)
                if res.status_code != 200:
                    logger.error(f"[MainBrain:{provider}] HTTP {res.status_code}: {res.text[:200]}")
                    return None
                data = res.json()
                token_usage.from_openai_json(data, provider=provider, model=model,
                                             key_id=key_id, key_label=key_label,
                                             context=context)
                msg = data["choices"][0]["message"]
                tool_calls = msg.get("tool_calls")

                if not tool_calls:
                    content = (msg.get("content") or "").strip()
                    return content or "(provider tidak mengirim teks)"

                convo.append({"role": "assistant",
                              "content": msg.get("content") or "",
                              "tool_calls": tool_calls})
                for tc in tool_calls:
                    fn = tc.get("function", {})
                    name = fn.get("name", "")
                    out = _execute_tool(name, fn.get("arguments", "{}"))
                    logger.info(f"[MainBrain] tool {name} -> {out[:80]}")
                    convo.append({
                        "role": "tool",
                        "tool_call_id": tc.get("id", ""),
                        "content": out,
                    })
            logger.warning("[MainBrain] capai batas iterasi tool-call.")
            return None
    except Exception as e:
        logger.error(f"[MainBrain:{provider}] error: {e!r}")
        return None
