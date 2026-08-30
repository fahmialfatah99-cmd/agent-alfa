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

import inspect
import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("MainBrain")

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
# Batas putaran tool-call per turn. Naik dari 8 -> 24 agar tugas kompleks
# multi-langkah tidak kehabisan "napas". Bisa dioverride via env.
MAX_ITERATIONS = int(os.getenv("ALFA_MAX_TOOL_ITERATIONS", "24"))
MAX_TOOL_OUTPUT = 4000      # potong output tool agar konteks efisien
TOOL_EXEC_TIMEOUT = 300     # rapat/swarm bisa berjalan beberapa menit
# Budget total karakter konteks percakapan; dilewabi -> kompaksi otomatis.
TOOL_CONTEXT_BUDGET = int(os.getenv("ALFA_TOOL_CONTEXT_BUDGET", "120000"))
_TOOL_KEEP_RECENT = 6       # jumlah pesan tool terakhir yang dijaga utuh


# ── Resolusi otak utama ──────────────────────────────────────────────────────
def get_main_brain(override_key_id: Optional[int] = None, override_model: Optional[str] = None) -> Dict[str, Any]:
    """
    Return dict: {provider, api_key, model, base_url, key_id, label}
    Prioritas: override_key_id -> pointer main_brain_key_id -> kunci aktif di vault -> .env
    """
    import database
    kid = override_key_id or database.get_main_brain_key_id()
    if kid:
        try:
            with database.get_sync_db() as conn:
                row = conn.execute(
                    "SELECT id, provider, api_key, default_model, base_url "
                    "FROM api_keys WHERE id = ?", (kid,)
                ).fetchone()
            if row:
                model = override_model or row["default_model"]
                if not override_model:
                    override = database.get_main_brain_model()
                    if override:
                        model = override
                return {
                    "provider": row["provider"].lower(),
                    "api_key": database.decrypt_key(row["api_key"]),
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
            "model": override_model or gk.get("default_model") or "",
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
        "model": override_model or os.getenv("GEMINI_MODEL", ""),
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


def build_openai_tools(safe_only: bool = False) -> List[Dict[str, Any]]:
    """Konversi AVAILABLE_TOOLS ke skema tools OpenAI.

    safe_only=True membatasi ke subset aman utk agen swarm: riset web, baca
    file, sandbox eksekusi, dan memori — tanpa vault rahasia & kontrol desktop.
    """
    try:
        import tools as t
        fns = [f for f in t.AVAILABLE_TOOLS if callable(f)]
    except Exception as e:
        logger.error(f"build_openai_tools gagal: {e}")
        return []
    if safe_only:
        fns = [f for f in fns if getattr(f, "__name__", "") in SAFE_TOOL_NAMES]
    converted = []
    for fn in fns:
        try:
            converted.append(_fn_to_openai_tool(fn))
        except Exception:
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
        import tools as t
        for f in t.AVAILABLE_TOOLS:
            if getattr(f, "__name__", "") == name:
                return f
    except Exception:
        pass
    return None


def _execute_tool(name: str, arguments_json: str) -> str:
    fn = _find_tool(name)
    if fn is None:
        return f"[ERROR] Tool '{name}' tidak ditemukan."
    try:
        args = json.loads(arguments_json or "{}")
    except Exception:
        return "[ERROR] Argumen tool bukan JSON valid."

    # Streaming aktivitas tool ke live feed rapat (jika sedang berjalan)
    try:
        import swarm_engine as _se
        if getattr(_se, "MEETING_RUNNING", False):
            arg_hint = ", ".join(f"{k}={str(v)[:40]}" for k, v in
                                 list(args.items())[:2]) or "-"
            _se.log_tool_live(f"⚙️ menjalankan `{name}` ({arg_hint}) ...")
    except Exception:
        pass

    try:
        import tracing as _tr
        _span = _tr.new_span(f"tool:{name}", tool=name)
    except Exception:
        _span = None

    def _call():
        try:
            return fn(**args)
        except Exception as e:
            # Record failure untuk self-correction learning
            try:
                from main_brain import get_self_correction_memory
                mem = get_self_correction_memory()
                mem.record_failure(name, args, str(e))
            except Exception:
                pass  # Jangan biarkan logging error mengganggu eksekusi utama
            return f"[ERROR tool] {e}"

    try:
        # Jalankan di thread terpisah agar event loop tetap hidup
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            fut = pool.submit(_call)
            raw = fut.result(timeout=TOOL_EXEC_TIMEOUT)
    except Exception as e:
        if _span:
            _span.finish(status="error", error=str(e))
        # Record timeout/execution failure juga
        try:
            from main_brain import get_self_correction_memory
            mem = get_self_correction_memory()
            mem.record_failure(name, args, f"Execution timeout/failure: {e}")
        except Exception:
            pass
        return f"[ERROR eksekusi] {e}"

    if not isinstance(raw, str):
        raw = json.dumps(raw, ensure_ascii=False, default=str)

    if _span:
        _status = "error" if raw.startswith("[ERROR") else "success"
        _span.finish(status=_status)
    
    # Record success jika sebelumnya ada failure pattern serupa
    if not raw.startswith("[ERROR"):
        try:
            # Cek apakah ini adalah retry yang berhasil setelah failure
            mem = get_self_correction_memory()
            # Di masa depan bisa track explicit retry flag
        except Exception:
            pass

    # Laporkan hasil ke live feed juga
    try:
        import swarm_engine as _se
        if getattr(_se, "MEETING_RUNNING", False):
            _se.log_tool_live(f"✅ `{name}` selesai -> {raw[:90]}")
    except Exception:
        pass

    return raw[:MAX_TOOL_OUTPUT]


# ── SELF-CORRECTION LOOP ──────────────────────────────────────────────────────
class SelfCorrectionMemory:
    """
    Menyimpan history kesalahan tool dan solusinya untuk pembelajaran agent.
    Format: {(tool_name, error_pattern): [solution_examples]}
    """
    
    def __init__(self, max_entries: int = 50):
        self.memory: Dict[tuple, List[Dict]] = {}
        self.max_entries = max_entries
    
    def record_failure(self, tool_name: str, args: Dict, error_msg: str, 
                       context_hint: str = "") -> None:
        """Catat kegagalan eksekusi tool."""
        # Ekstrak pattern error (abaikan detail spesifik seperti path/file line)
        error_pattern = re.sub(r'\d+', 'N', error_msg)[:100]  # Normalisasi angka
        error_pattern = re.sub(r'[/\\][^\s/\\]+', '/PATH', error_pattern)  # Normalisasi path
        
        key = (tool_name, error_pattern[:80])
        
        if key not in self.memory:
            self.memory[key] = []
        
        self.memory[key].append({
            "args": args,
            "error": error_msg,
            "context": context_hint,
            "timestamp": time.time()
        })
        
        # Trim memory jika terlalu besar
        if len(self.memory[key]) > 10:
            self.memory[key] = self.memory[key][-10:]
        
        # Trim global entries
        while len(self.memory) > self.max_entries:
            oldest_key = min(self.memory.keys(), 
                           key=lambda k: min(e["timestamp"] for e in self.memory[k]))
            del self.memory[oldest_key]
    
    def get_suggestion(self, tool_name: str, args: Dict, error_msg: str) -> Optional[Dict]:
        """
        Cari solusi berdasarkan pola error serupa di masa lalu.
        Return suggestion berupa argumen yang dimodifikasi atau None.
        """
        error_pattern = re.sub(r'\d+', 'N', error_msg)[:100]
        error_pattern = re.sub(r'[/\\][^\s/\\]+', '/PATH', error_pattern)
        
        key = (tool_name, error_pattern[:80])
        
        # Coba exact match dulu
        if key in self.memory and len(self.memory[key]) > 0:
            # Ambil contoh terbaru
            latest = self.memory[key][-1]
            logger.info(f"[SelfCorrect] Found similar failure for {tool_name}, "
                       f"trying alternative approach")
            # Di masa depan bisa diperbaiki dengan menyimpan 'fixed_args'
            return {"retry_with_caution": True, "similar_error_count": len(self.memory[key])}
        
        # Coba partial match (fuzzy matching pada error pattern)
        for (t_name, e_pattern), examples in self.memory.items():
            if t_name == tool_name and e_pattern in error_pattern or error_pattern in e_pattern:
                logger.info(f"[SelfCorrect] Partial match found for {tool_name}")
                return {"retry_with_caution": True, "pattern_matched": True}
        
        return None
    
    def record_success_after_retry(self, tool_name: str, original_args: Dict,
                                   fixed_args: Dict, initial_error: str) -> None:
        """
        Catat keberhasilan setelah retry dengan argumen yang diperbaiki.
        Ini menjadi data pembelajaran untuk kasus serupa di masa depan.
        """
        error_pattern = re.sub(r'\d+', 'N', initial_error)[:100]
        error_pattern = re.sub(r'[/\\][^\s/\\]+', '/PATH', error_pattern)
        key = (tool_name, error_pattern[:80])
        
        if key not in self.memory:
            self.memory[key] = []
        
        self.memory[key].append({
            "original_args": original_args,
            "fixed_args": fixed_args,
            "success": True,
            "timestamp": time.time()
        })


# Global instance untuk shared learning across sessions
_self_correction_memory = SelfCorrectionMemory()


def get_self_correction_memory() -> SelfCorrectionMemory:
    """Accessor untuk global self-correction memory."""
    return _self_correction_memory


# ── Kompaksi konteks agentic loop ────────────────────────────────────────────
def _convo_size(convo: List[Dict[str, Any]]) -> int:
    return sum(
        len(m.get("content") or "") + len(str(m.get("tool_calls") or ""))
        for m in convo
    )


def _compact_convo(convo: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Pangkas output tool LAMA saat total konteks melewati budget.

    Pesan 'tool' terakhir dijaga utuh; yang lebih tua dipotong menjadi
    penanda ringkas agar loop panjang tetap muat dalam jendela konteks.
    Mutasi in-place; mengembalikan convo yang sama.
    """
    try:
        if _convo_size(convo) <= TOOL_CONTEXT_BUDGET:
            return convo
        tool_idx = [i for i, m in enumerate(convo) if m.get("role") == "tool"]
        if len(tool_idx) <= _TOOL_KEEP_RECENT:
            return convo
        for i in tool_idx[:-_TOOL_KEEP_RECENT]:
            c = convo[i].get("content") or ""
            if len(c) > 220:
                convo[i]["content"] = (
                    "[output tool dipangkas utk hemat konteks] " + c[:180] + " ...")
        logger.debug(f"[MainBrain] kompaksi konteks: ukuran sekarang {_convo_size(convo)}")
    except Exception as e:
        logger.warning(f"[MainBrain] kompaksi gagal (abaikan): {e!r}")
    return convo


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
    tools_schema: Optional[List[Dict[str, Any]]] = None,
    approval_gate=None,
) -> Optional[str]:
    """
    Satu turn agentik penuh di provider OpenAI-compatible:
    kirim pesan + tools -> eksekusi tool_calls -> ulangi sampai jawaban final.
    tools_schema=None memakai set lengkap; list kosong = tanpa tools (chat polos).
    approval_gate: callable async (tool_name, args_json)->Optional[str];
    None = boleh, str = tolak dan pakai teks itu sbg hasil tool.
    Return teks jawaban, atau None bila gagal total (pemanggil bisa fallback).
    """
    try:
        import httpx

        import token_usage
        if tools_schema is None:
            tools_schema = build_openai_tools()
            # TOOL-RAG: suntikkan hanya tool relevan (hemat token, cegah confusion)
            try:
                from tool_rag import select_relevant_tools
                tools_schema = select_relevant_tools(tools_schema, user_text, history=history)
            except Exception:
                pass  # fail-open: set lengkap

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
                _compact_convo(convo)
                payload = dict(payload_base, messages=convo)
                if tools_schema:
                    payload["tools"] = tools_schema
                res = await client.post(url, headers=headers, json=payload)
                if res.status_code != 200:
                    err_text = res.text[:300]
                    logger.error(f"[MainBrain:{provider}] HTTP {res.status_code}: {err_text}")
                    if res.status_code == 402:
                        return (
                            f"⚠️ **Gagal memanggil `{model}` via {provider.upper()} (HTTP 402: Saldo / Credit Habis).**\n\n"
                            f"Kredit di akun {provider.upper()} kamu kosong/tidak mencukupi untuk menjalankan model ini. "
                            f"Silakan top up kredit di dashboard provider atau beralih ke model Gemini / model gratis di menu dropdown."
                        )
                    if res.status_code == 404:
                        return (
                            f"⚠️ **Model `{model}` tidak ditemukan di gateway {provider.upper()} (HTTP 404).**\n\n"
                            f"Silakan gunakan model lain yang aktif di daftar dropdown pemilih model."
                        )
                    if res.status_code == 429:
                        return (
                            f"⚠️ **Rate Limit Terlampaui ({provider.upper()} HTTP 429).**\n\n"
                            f"Batas kuota/request per menit untuk model ini telah tercapai. Coba beberapa saat lagi."
                        )
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
                    raw_args = fn.get("arguments", "{}")
                    out = None
                    if approval_gate is not None:
                        try:
                            denial = await approval_gate(name, raw_args)
                            if denial:
                                out = denial
                        except Exception as gate_err:
                            logger.warning(f"[Gate] error (fail-open): {gate_err!r}")
                    if out is None:
                        out = _execute_tool(name, raw_args)
                    logger.info(f"[MainBrain] tool {name} -> {out[:80]}")
                    convo.append({
                        "role": "tool",
                        "tool_call_id": tc.get("id", ""),
                        "content": out,
                    })

            # Batas iterasi tercapai: jangan buang seluruh progres.
            # Minta ringkasan akhir TANPA tools agar hasil tetap berguna.
            logger.warning(f"[MainBrain] batas {MAX_ITERATIONS} iterasi tercapai -> minta wrap-up.")
            convo.append({
                "role": "user",
                "content": ("[SISTEM] Batas putaran tool tercapai. STOP memanggil tool. "
                            "Ringkas apa yang SUDAH berhasil dikerjakan, hasil/data penting "
                            "yang sudah didapat, dan langkah tersisa yang perlu "
                            "dilanjutkan di giliran berikutnya."),
            })
            try:
                wrap_payload = dict(payload_base, messages=_compact_convo(convo))
                res2 = await client.post(url, headers=headers, json=wrap_payload)
                if res2.status_code == 200:
                    token_usage.from_openai_json(res2.json(), provider=provider,
                                                 model=model, key_id=key_id,
                                                 key_label=key_label,
                                                 context=f"{context}:wrapup")
                    wrap = (res2.json().get("choices", [{}])[0].get("message", {})
                            .get("content") or "").strip()
                    if wrap:
                        return f"⏳ *Progres parsial (batas iterasi tercapai):*\n\n{wrap}"
            except Exception as wrap_err:
                logger.warning(f"[MainBrain] wrap-up gagal: {wrap_err!r}")
            return None
    except Exception as e:
        logger.error(f"[MainBrain:{provider}] error: {e!r}")
        return None
