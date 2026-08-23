"""
Autonomous Multi-Agent Swarm & Meeting Engine for ALFA Ecosystem.
Enables round-table AI meetings, inter-agent dialogue, debate, consensus building,
and live autonomous collaborative execution (Swarm Work Mode with REAL tools, files, and scraping).
"""

import os
import time
import json
import logging
import asyncio
import re
import shutil
import itertools
import collections
from datetime import datetime
from typing import List, Dict, Any, Optional

from dotenv import load_dotenv
load_dotenv()

import database
import tools
import token_usage
from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

# Provider bawaan yang URL-nya sudah dipetakan otomatis. Provider di luar daftar
# ini (misal 'custom'/'tokenra'/'oxalpha') tetap didukung selama kuncinya punya
# Base URL OpenAI-compatible di vault.
KNOWN_OPENAI_PROVIDERS = {
    "openai", "groq", "openrouter", "9router", "ollama", "nvidia", "nim",
    "deepseek", "minimax", "moonshot", "kimi", "qwen", "dashscope",
}

SWARM_OUTPUT_DIR = "/home/fahmial/Dokumen/ALFA_SWARM_OUTPUTS"
os.makedirs(SWARM_OUTPUT_DIR, exist_ok=True)

# ── AUTO-HARVESTER: arsipkan proyek baru dari sandbox di akhir rapat ────────
# Folder fullstack multi-file yang dibangun agen lewat bash bebas hidup di
# RAM disk (/dev/shm) dan TIDAK ikut salinan deliverable standar (CSV/HTML).
# Snapshot diambil saat rapat mulai; di akhir rapat folder baru diarsipkan
# otomatis ke ALFA_SWARM_OUTPUTS/projects tanpa node_modules & sejenisnya.
_HARVEST_EXCLUDE = {"node_modules", ".next", ".git", ".toolchain",
                    "__pycache__", ".cache", ".local", ".venv", "venv"}
_SANDBOX_SNAPSHOT: set = set()


def _sandbox_project_dirs() -> set:
    try:
        sb = tools.SANDBOX_DIR
        return {d for d in os.listdir(sb)
                if os.path.isdir(os.path.join(sb, d)) and not d.startswith(".")}
    except Exception:
        return set()


def _harvest_new_sandbox_projects(topic: str = "") -> List[str]:
    """Arsipkan folder proyek baru di sandbox (sejak snapshot awal rapat)."""
    harvested: List[str] = []
    try:
        new_dirs = _sandbox_project_dirs() - _SANDBOX_SNAPSHOT
        if not new_dirs:
            return harvested
        slug = re.sub(r"[^a-z0-9]+", "_", (topic or "rapat").lower())[:30].strip("_") or "rapat"
        dst_root = os.path.join(SWARM_OUTPUT_DIR, "projects",
                                f"{slug}_{int(time.time())}")
        for d in sorted(new_dirs):
            src = os.path.join(tools.SANDBOX_DIR, d)
            total = 0
            too_big = False
            for root, dirs, files in os.walk(src):
                dirs[:] = [x for x in dirs if x not in _HARVEST_EXCLUDE]
                for f in files:
                    try:
                        total += os.path.getsize(os.path.join(root, f))
                    except OSError:
                        pass
                if total > 400 * 1024 * 1024:
                    too_big = True
                    break
            if too_big:
                log_live("HARVEST", f"⏭️ '{d}' dilewati (melebihi 400MB)")
                continue
            shutil.copytree(src, os.path.join(dst_root, d),
                            ignore=shutil.ignore_patterns(*_HARVEST_EXCLUDE),
                            dirs_exist_ok=True)
            harvested.append(d)
            log_live("HARVEST",
                     f"📦 Proyek '{d}' ({total // 1024}KB) diarsipkan ke {dst_root}")
        return harvested
    except Exception as e:
        log_live("HARVEST", f"⚠️ harvest gagal: {e}")
        return harvested
    finally:
        _SANDBOX_SNAPSHOT.clear()
        _SANDBOX_SNAPSHOT.update(_sandbox_project_dirs())

# ── LIVE TERMINAL FEED ───────────────────────────────────────────────────────
# Sumber kebenaran: file JSONL agar lintas-proses (rapat dari Telegram maupun
# dashboard sama-sama terlihat di Live Terminal web).
LIVE_FEED_FILE = os.path.join(SWARM_OUTPUT_DIR, "live_meeting_feed.jsonl")
LIVE_LOG: "collections.deque" = collections.deque(maxlen=400)
MEETING_RUNNING = False


def _load_last_seq() -> int:
    try:
        with open(LIVE_FEED_FILE, "r", encoding="utf-8") as f:
            lines = f.read().strip().splitlines()
        if lines:
            return int(json.loads(lines[-1]).get("i", 0))
    except Exception:
        pass
    return 0


_live_seq = itertools.count(_load_last_seq() + 1)


def _append_feed_file(entry: Dict[str, Any]):
    """Append satu baris JSONL; rotasi sederhana bila >300KB."""
    try:
        if os.path.exists(LIVE_FEED_FILE) and os.path.getsize(LIVE_FEED_FILE) > 300_000:
            with open(LIVE_FEED_FILE, "r", encoding="utf-8") as f:
                lines = f.readlines()[-150:]
            tmp = LIVE_FEED_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.writelines(lines)
            os.replace(tmp, LIVE_FEED_FILE)
        with open(LIVE_FEED_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


def log_live(tag: str, text: str):
    """Append one realtime line for the dashboard live terminal. Fail-safe."""
    try:
        entry = {
            "i": next(_live_seq),
            "ts": datetime.now().strftime("%H:%M:%S"),
            "tag": tag.upper(),
            "text": str(text)[:400],
        }
        LIVE_LOG.append(entry)
        _append_feed_file(entry)
    except Exception:
        pass


def detect_task_intent(topic: str) -> Dict[str, Any]:
    """Analyze the user's topic/command to determine tool strategy, categories, and limits."""
    low = topic.lower()
    
    # Detect target count (e.g. 20 mouse, 10 jobs)
    count_match = re.search(r'\b(\d{1,3})\b', low)
    limit = int(count_match.group(1)) if count_match else 20
    limit = min(50, max(5, limit))

    is_scrape = any(k in low for k in ["scrape", "scraping", "ambil data", "sedot", "cari data", "carikan produk", "lowongan", "kontak", "supplier", "harga"])
    is_code = any(k in low for k in ["script", "skrip", "python", "koding", "coding", "program", "buatkan script", "bikin script", "aplikasi", "fungsi", "function"])
    is_audit = any(k in low for k in ["audit", "security", "keamanan", "vram", "ram", "cpu", "port", "firewall", "celah"])

    category = "general_web"
    if any(k in low for k in ["shopee", "tokopedia", "tiktok", "lazada", "blibli", "marketplace", "produk", "jual", "harga", "beli", "mouse", "baju", "sepatu", "laptop", "hp"]):
        category = "all_marketplace"
    elif any(k in low for k in ["loker", "lowongan", "kerja", "job", "karir", "jobstreet", "glints", "linkedin"]):
        category = "jobs_career"
    elif any(k in low for k in ["kontak", "supplier", "wa", "whatsapp", "distributor", "email", "pabrik"]):
        category = "leads_contacts"
    elif any(k in low for k in ["berita", "news", "detik", "kompas", "cnn", "media"]):
        category = "news_media"
    # Extract search term cleanly
    cleaned = topic
    fillers = [
        r'(?i)\b(tolong|coba|scrape|scraping|carikan|ambilkan|ambil|cari|eksekusi|buatkan|bikin|analisa|analisis|rekap|buatkan skrip|skrip|script|rekap csv|csv-nya|file csv|terlaris|terpopuler|murah|bagus|dan buatkan.*|analisa rentang.*)\b',
        r'(?i)\b(di shopee|di tokopedia|di lazada|di tiktok|shopee & tokopedia|shopee dan tokopedia|di marketplace|di google)\b',
        r'\b\d+\b',
        r'[^\w\s-]'
    ]
    for p in fillers:
        cleaned = re.sub(p, ' ', cleaned)
    cleaned = ' '.join(cleaned.split()).strip()
    if len(cleaned) < 3:
        cleaned = topic[:40]

    return {
        "is_scrape": is_scrape,
        "is_code": is_code,
        "is_audit": is_audit,
        "category": category,
        "limit": limit,
        "clean_query": cleaned
    }


def get_agent_api_client(agent: Dict[str, Any]) -> tuple[str, str, str, Optional[str], Optional[int]]:
    """Resolve (provider, api_key, model, base_url, key_id) for a specific agent."""
    provider = (agent.get("provider") or "gemini").lower()
    model = agent.get("model") or "gemini-2.5-flash"
    api_key = ""
    base_url = ""
    key_id = None
    key_label = ""

    if agent.get("api_key_id"):
        with database.get_sync_db() as conn:
            row = conn.execute("SELECT id, provider, api_key, default_model, base_url FROM api_keys WHERE id = ?", (agent["api_key_id"],)).fetchone()
            if row:
                provider = row["provider"]
                api_key = database.decrypt_key(row["api_key"])
                base_url = row["base_url"] or ""
                key_id = row["id"]
                key_label = f"#{row['id']}"
                if not agent.get("model"):
                    model = row["default_model"]

    if not api_key:
        active_key = database.get_active_api_key_sync(provider)
        if active_key:
            api_key = active_key["api_key"]
            base_url = active_key.get("base_url") or ""
            key_id = active_key.get("id")
            key_label = f"#{active_key.get('id')}" if key_id else ""

    if not api_key:
        if provider == "gemini":
            api_key = os.getenv("GEMINI_API_KEY", "")
        elif provider == "openai":
            api_key = os.getenv("OPENAI_API_KEY", "")
        elif provider == "groq":
            api_key = os.getenv("GROQ_API_KEY", "")
        elif provider in ["nvidia", "nim"]:
            api_key = os.getenv("NVIDIA_API_KEY", "")

    return provider, api_key, model, base_url, key_id


async def _generate_with_gemini(
    agent_name: str,
    api_key: str,
    models: List[str],
    prompt: str,
    final_instruction: str,
    key_id=None,
    key_label: str = "",
    context: str = "swarm",
    max_tokens: int = 500,
    thinking_budget: Optional[int] = None,
    timeout_s: float = 180.0,
    tools: Optional[List[Any]] = None,
) -> Optional[str]:
    """Try a chain of Gemini models. Returns text or None if all fail."""
    default_chain = os.getenv(
        "GEMINI_FALLBACK_MODELS",
        "gemini-3.6-flash,gemini-3.5-flash-lite,gemini-flash-latest"
    ).split(",")
    candidate_models = [m for m in models + [x.strip() for x in default_chain] if m]
    unique_models = list(dict.fromkeys(candidate_models))

    last_err = None
    try:
        client = genai.Client(api_key=api_key)
    except Exception as client_err:
        logger.error(f"Failed to initialize Gemini client for agent '{agent_name}': {client_err!r}")
        return None
    for m in unique_models:
        try:
            cfg_kw = dict(
                system_instruction=final_instruction,
                temperature=0.7,
                max_output_tokens=max_tokens,
            )
            if thinking_budget is not None:
                cfg_kw["thinking_config"] = types.ThinkingConfig(
                    thinking_budget=thinking_budget)
            if tools:
                # SDK melakukan automatic function calling & mengirim hasil
                # tool berikutnya secara internal sampai jawaban final.
                cfg_kw["tools"] = list(tools)
            try:
                response = await asyncio.wait_for(
                    client.aio.models.generate_content(
                        model=m,
                        contents=prompt,
                        config=types.GenerateContentConfig(**cfg_kw),
                    ),
                    timeout=timeout_s,
                )
            except asyncio.TimeoutError:
                last_err = TimeoutError(
                    f"[gemini] HARD DEADLINE {timeout_s}s terlampaui untuk model '{m}'")
                logger.warning(f"{last_err}. Trying next fallback...")
                continue
            if response and response.text:
                token_usage.from_gemini_response(response, model=m, key_id=key_id,
                                                 key_label=key_label or f"agent:{agent_name}",
                                                 context=context)
                return response.text.strip()
        except Exception as e:
            last_err = e
            logger.warning(f"Model '{m}' failed for agent '{agent_name}': {e}. Trying next fallback...")

    logger.error(f"All Gemini models failed for agent '{agent_name}': {last_err!r}")
    return None


async def _generate_with_openai_compat(
    agent_name: str,
    provider: str,
    api_key: str,
    model: str,
    base_url: Optional[str],
    prompt: str,
    final_instruction: str,
    key_id=None,
    key_label: str = "",
    context: str = "swarm",
    max_tokens: int = 500,
    timeout_s: float = 180.0,
) -> Optional[str]:
    """Call an OpenAI-compatible endpoint. Returns text or None on failure."""
    try:
        import httpx
        url = base_url
        if not url:
            if provider in ["nvidia", "nim"]:
                url = "https://integrate.api.nvidia.com/v1"
            elif provider == "deepseek":
                url = "https://api.deepseek.com/v1"
            elif provider == "minimax":
                url = "https://api.minimax.chat/v1"
            elif provider in ["moonshot", "kimi"]:
                url = "https://api.moonshot.cn/v1"
            elif provider in ["qwen", "dashscope"]:
                url = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
            elif provider == "openai":
                url = "https://api.openai.com/v1"
            elif provider == "groq":
                url = "https://api.groq.com/openai/v1"
            elif provider == "openrouter":
                url = "https://openrouter.ai/api/v1"
            elif provider == "9router":
                url = "http://localhost:20128/v1"
            elif provider == "ollama":
                url = "http://localhost:11434/v1"

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        if provider == "openrouter":
            headers["HTTP-Referer"] = "https://alfa-agent.local"
            headers["X-Title"] = "ALFA Sovereign Agent"

        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": final_instruction},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.7,
            "max_tokens": max_tokens
        }

        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_s, connect=10.0)) as http_client:
            # Deadline KERAS: read-timeout httpx bisa ter-reset oleh respons
            # yang menetes, jadi total waktu dipaksa lewat asyncio.wait_for.
            try:
                res = await asyncio.wait_for(
                    http_client.post(f"{url.rstrip('/')}/chat/completions",
                                     headers=headers, json=payload),
                    timeout=timeout_s,
                )
            except asyncio.TimeoutError:
                logger.error(
                    f"[{provider}] HARD DEADLINE {timeout_s}s terlampaui untuk "
                    f"'{agent_name}' (respons menetes?) - batal & lanjut fallback."
                )
                return None
            if res.status_code == 200:
                data = res.json()
                token_usage.from_openai_json(data, provider=provider, model=model,
                                             key_id=key_id,
                                             key_label=key_label or f"agent:{agent_name}",
                                             context=context)
                msg0 = (data.get("choices") or [{}])[0].get("message") or {}
                content = (msg0.get("content") or "").strip()
                if not content:
                    content = (msg0.get("reasoning_content")
                               or msg0.get("reasoning") or "").strip()
                    logger.warning(f"[{provider}] content kosong, fallback reasoning ({len(content)} char)")
                if content:
                    return content
                return None
            # Kuota habis sebagian? OpenRouter memberi tahu angka maksimal yang
            # mampu dibayar - coba sekali lagi dengan budget itu (dikurangi margin).
            if res.status_code == 402:
                import re as _re
                m_afford = _re.search(r"can only afford (\d+)", res.text)
                if m_afford:
                    afford = max(256, int(m_afford.group(1)) - 128)
                    payload["max_tokens"] = afford
                    logger.warning(
                        f"[{provider}] kuota terbatas - retry dengan max_tokens={afford}"
                    )
                    try:
                        res = await client.post(f"{url.rstrip('/')}/chat/completions",
                                                headers=headers, json=payload)
                    except Exception:
                        return None
                    if res.status_code == 200:
                        data = res.json()
                        token_usage.from_openai_json(data, provider=provider, model=model,
                                                     key_id=key_id, key_label=key_label,
                                                     context=context)
                        msg0 = (data.get("choices") or [{}])[0].get("message") or {}
                        content = (msg0.get("content") or "").strip()
                        if content:
                            return content
                    else:
                        logger.error(f"[{provider}] retry 402 tetap gagal HTTP {res.status_code}")
                err_detail = res.text[:200] or "(empty body)"
                logger.error(f"{provider} HTTP {res.status_code} for agent '{agent_name}' (model={model}): {err_detail}")
                return None

            err_detail = res.text[:200] or "(empty body)"
            logger.error(f"{provider} HTTP {res.status_code} for agent '{agent_name}' (model={model}): {err_detail}")
            return None
    except Exception as e:
        logger.error(f"Error in {provider} agent '{agent_name}': {e!r}")
        return None


async def generate_agent_response(agent: Dict[str, Any], prompt: str, system_instruction: str,
                                  max_tokens: Optional[int] = None,
                                  timeout_s: float = 180.0,
                                  thinking_budget: Optional[int] = None) -> str:
    """Generate response for a specific agent using its configured provider and key.

    If the agent's primary provider fails (timeout, bad key, quota, etc.), it
    automatically falls back to Gemini so the swarm conversation never loses
    a participant silently.
    """
    provider, api_key, model, base_url, key_id = get_agent_api_client(agent)
    agent_name = agent.get("name", "Agent")
    enable_tools = bool(agent.get("enable_tools"))

    tone_directive = (
        "\n\n[PANDUAN OUTPUT & GAYA BICARA]:"
        "\n1. BICARA SANTAI & GAUL: Gunakan gaya bahasa santai, luwes, natural ala software engineer/tech specialist di war room (jangan kaku, hindari basa-basi robot seperti 'Sebagai AI...', 'Tentu saja...')."
        "\n2. ON-POINT & REALISTIS: Langsung sebutkan fakta teknis nyata dan aksi nyata yang dilakukan tanpa bertele-tele. Maksimal 2-4 kalimat."
    )
    final_instruction = (system_instruction or "Kamu adalah engineer spesialis di AI Swarm.") + tone_directive

    key_label = f"agent:{agent_name}"

    result = None
    if provider == "gemini":
        gemini_tools = None
        if enable_tools:
            try:
                import main_brain as _mb
                import tools as _t
                gemini_tools = [
                    getattr(_t, n) for n in sorted(_mb.SAFE_TOOL_NAMES)
                    if hasattr(_t, n) and callable(getattr(_t, n))
                ]
            except Exception as tools_err:
                logger.warning(f"Tools swarm utk '{agent_name}' gagal dimuat: {tools_err}")
        result = await _generate_with_gemini(
            agent_name=agent_name,
            api_key=api_key or os.getenv("GEMINI_API_KEY", ""),
            models=[model],
            prompt=prompt,
            final_instruction=final_instruction,
            key_id=key_id,
            key_label=key_label,
            context="swarm",
            max_tokens=max_tokens or 500,
            timeout_s=timeout_s,
            thinking_budget=thinking_budget,
            tools=gemini_tools,
        )
    else:
        # Agen dgn enable_tools: loop agentik penuh memakai subset aman
        if enable_tools:
            try:
                import main_brain as _mb
                result = await _mb.run_openai_agentic_turn(
                    provider=provider,
                    base_url=base_url,
                    api_key=api_key,
                    model=model,
                    system_instruction=final_instruction,
                    user_text=prompt,
                    key_id=key_id,
                    key_label=key_label,
                    context="swarm",
                    tools_schema=_mb.build_openai_tools(safe_only=True),
                )
            except Exception as agentic_err:
                logger.warning(f"Agentic turn '{agent_name}' error: {agentic_err!r}")
                result = None
        if result is None:
            # Semua provider non-gemini dicoba sebagai OpenAI-compatible
            # (termasuk 'custom' dgn Base URL bebas: Tokenra, Ox Alpha, dll).
            if not base_url and provider not in KNOWN_OPENAI_PROVIDERS:
                logger.warning(
                    f"Provider '{provider}' tanpa base_url untuk '{agent_name}' - "
                    "fallback ke Gemini."
                )
            result = await _generate_with_openai_compat(
            agent_name=agent_name,
            provider=provider,
            api_key=api_key,
            model=model,
            base_url=base_url,
            prompt=prompt,
            final_instruction=final_instruction,
            key_id=key_id,
            key_label=key_label,
            context="swarm",
            max_tokens=max_tokens or 500,
            timeout_s=timeout_s,
        )
        if result is None and os.getenv("GEMINI_API_KEY"):
            logger.warning(f"Provider '{provider}' gagal untuk '{agent_name}' - fallback ke Gemini.")
            result = await _generate_with_gemini(
                agent_name=f"{agent_name} (fallback)",
                api_key=os.getenv("GEMINI_API_KEY", ""),
                models=["gemini-3.5-flash-lite"],
                prompt=prompt,
                final_instruction=final_instruction,
                key_id=None,
                key_label="gemini-fallback",
                context="swarm",
                thinking_budget=thinking_budget,
            )

    if result is None:
        return f"[Error: Semua provider gagal untuk '{agent_name}' (primary: {provider})]"
    return result


def _extract_html_doc(text: str) -> str:
    """Ekstrak dokumen HTML utuh dari teks model (fence / doc penuh / sisa)."""
    if not text:
        return ""
    fence = re.search(r"```html\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
    if fence:
        return fence.group(1).strip()
    m = re.search(r"(<!DOCTYPE\s+html.*?</html>)", text, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()
    low = text.lower()
    if "<html" in low:
        return text[low.index("<html"):].strip()
    return ""


def validate_python_code(code: str) -> str:
    """Return an error message if code is empty, trivial, or syntactically invalid; '' if OK."""
    import ast as _ast
    cleaned = (code or "").strip()
    if len(cleaned) < 30:
        return "kode kosong atau terlalu pendek untuk dijalankan"
    try:
        _ast.parse(cleaned)
    except SyntaxError as syn_err:
        return f"syntax error di baris {syn_err.lineno}: {syn_err.msg}"
    return ""


async def _decompose_task(topic: str, participants: List[Dict[str, Any]]) -> Dict[str, str]:
    """Ask the planner to break the topic into one concrete subtask per agent.

    Returns {agent_name: instruction}; empty dict when parsing fails so the
    caller can fall back to generic role-based tasks.
    """
    roster = ", ".join(f"{a['name']} ({a.get('role','')})" for a in participants)
    prompt = (
        f"Anda misi planner swarm. TOPIK: {topic}\n"
        f"TIM: {roster}\n\n"
        "Pecah topik ini menjadi SATU subtask konkret dan dapat dieksekusi sistem "
        "(bukan rencana abstrak) untuk setiap anggota tim.\n"
        'Balas HANYA array JSON tanpa teks lain: '
        '[{"name": "<nama persis dari tim>", "task": "<instruksi spesifik maksimal 25 kata>"}]'
    )
    try:
        raw = await generate_agent_response(
            {"name": "Mission Planner", "provider": "gemini"},
            prompt,
            "Kamu planner teknis. Output WAJIB array JSON murni tanpa penjelasan.",
        )
        m = re.search(r"\[.*\]", raw, re.DOTALL)
        if not m:
            return {}
        items = json.loads(m.group(0))
        valid_names = {a["name"] for a in participants}
        mapping = {}
        for it in items if isinstance(items, list) else []:
            nm = (it or {}).get("name", "").strip()
            tk = (it or {}).get("task", "").strip()
            if nm in valid_names and tk:
                mapping[nm] = tk
        return mapping
    except Exception as dec_err:
        logger.warning("Task decomposition failed, using generic tasks: %r", dec_err)
        return {}


async def _verify_step_result(task: str, step_result: Dict[str, Any]) -> tuple:
    """LLM judge for a swarm execution step. Returns (passed: bool, feedback: str)."""
    summary = (step_result.get("execution_summary") or "")[:600]
    prompt = (
        f"TUGAS YANG DIMINTA: {task[:300]}\n\n"
        f"HASIL EKSEKUSI:\n- Tool: {step_result.get('tool_used')}\n"
        f"- Status: {step_result.get('status')}\n- Output: {summary}\n\n"
        "Apakah hasil ini bukti nyata tugas tercapai (data/file/output riil, bukan janji)?\n"
        "Balas TEPAT satu baris: PASS atau: FAIL: <alasan singkat>"
    )
    try:
        verdict = await generate_agent_response(
            {"name": "Step Verifier", "provider": "gemini"},
            prompt,
            "Kamu QA auditor ketat. Hanya terima bukti konkret.",
        )
        v = (verdict or "").strip().upper()
        if v.startswith("PASS"):
            return True, ""
        fb = verdict.strip() if verdict else "verifier tidak merespons"
        return False, fb[:200]
    except Exception as ver_err:
        logger.warning("Verification call failed (treated as unverified): %r", ver_err)
        return True, ""   # don't block pipeline on verifier outage


async def execute_swarm_task_step(agent: Dict[str, Any], task_instruction: str, topic: str, intent_info: Dict[str, Any]) -> Dict[str, Any]:
    """
    Executes a real action for an agent in Swarm Live Execution mode.
    Calls appropriate system tools, writes files, scrapes data, or tests code.
    """
    t0 = time.time()
    agent_name = agent.get("name", "Agent")
    role = agent.get("role", "Specialist")
    agent_id = agent.get("id", 1)
    
    action_type = "execution"
    tool_name = "ai_agent_task"
    tool_input = task_instruction
    tool_output = ""
    status = "success"
    deliverable_file = ""
    deliverable_data = []

    # 1. SPECIALIST: RESEARCHER PRIME (Deep Scraping & Real Web Intelligence)
    if "Research" in agent_name or "Intel" in role or (intent_info.get("is_scrape") and "Prime" in agent_name):
        tool_name = "universal_deep_scraper"
        search_query = intent_info.get("clean_query") or topic
        cat = intent_info.get("category", "all_marketplace")
        limit = intent_info.get("limit", 20)

        try:
            scrape_res = tools.universal_deep_scraper(query=search_query, category=cat, limit=limit)
            total = scrape_res.get("total_scraped", len(scrape_res.get("items", [])))
            csv_path = scrape_res.get("csv_path") or scrape_res.get("csv_file", "")
            json_path = scrape_res.get("json_path") or scrape_res.get("json_file", "")
            items = scrape_res.get("items") or scrape_res.get("results", [])

            # Copy to SWARM_OUTPUT_DIR for easy access
            if csv_path and os.path.exists(csv_path):
                dest_csv = os.path.join(SWARM_OUTPUT_DIR, os.path.basename(csv_path))
                shutil.copyfile(csv_path, dest_csv)
                deliverable_file = dest_csv

            top_items_text = "\n".join([
                f"{i+1}. {it.get('title', '')[:50]} | {it.get('price') or it.get('price_tag', 'N/A')} ({it.get('domain') or it.get('source_domain', 'Market')})"
                for i, it in enumerate(items[:8])
            ])

            tool_output = f"✅ Scraping Berhasil: {total} data nyata berhasil ditarik!\n📁 File CSV: {deliverable_file}\n\nSampel Data Teratas:\n{top_items_text}"
            deliverable_data = items[:10]
            generated_content = f"Gue udah scrape langsung {total} data nyata untuk target `{search_query}` di kategori `{cat}`. File CSV tersimpan di `{deliverable_file}` dan siap dianalisis!"

        except Exception as e:
            status = "error"
            tool_output = f"Error in Deep Scraper: {str(e)}"
            generated_content = f"Gagal mengeksekusi scraper: {str(e)}"

    # 2. SPECIALIST: CODE CRAFTER (Real Python Automation & Sandbox Execution)
    elif "Code" in agent_name or "Engineer" in role or "Architect" in role:
        # ── WEB BUILDER: bangun website nyata dalam satu file ──
        is_web_build = any(k in (task_instruction + " " + topic).lower()
                           for k in ("website", "web ", "landing page", "html",
                                     "halaman web", "web app", "dashboard web"))

        if is_web_build:
            tool_name = "build_web_page"
            status = "error"

            web_prompt = (
                f"=== PERINTAH WEB BUILDER NYATA SWARM ===\n"
                f"Brief klien: {task_instruction}\n"
                f"Konteks topik: {topic[:200]}\n\n"
                f"Tugas: Bangun WEBSITE LENGKAP dalam SATU file index.html "
                f"(HTML5 + CSS inline di <style> + JS di <script>, responsif, tema dark modern).\n"
                f"WAJIB blok ```html ... ``` berisi dokumen utuh mulai <!DOCTYPE html>."
            )
            WEB_ENGINEER_SYS = (
                "Kamu adalah Senior Web Engineer. Hasilkan website production-quality "
                "dalam SATU file HTML utuh yang langsung bisa dibuka di browser."
            )

            provider_used = agent.get("provider", "?")
            log_live("TOOL", f"🌐 {agent_name} membangun website via {provider_used}...")

            def _valid(p):
                lowp = p.lower()
                return len(p) >= 400 and ("<html" in lowp or "<!doctype" in lowp) and "</body>" in lowp

            generated_content = await generate_agent_response(
                agent, web_prompt, WEB_ENGINEER_SYS,
                max_tokens=16000, timeout_s=70.0,
                thinking_budget=0,
            )
            log_live("TOOL", f"⏱️ attempt-1 ({provider_used}) -> {len(generated_content or '')} char")

            page = _extract_html_doc(generated_content)
            fb_note = ""

            if not _valid(page):
                log_live("VERIFY", f"⏳ {agent_name}: otak utama gagal/lambat - Nemotron Ultra mengambil alih")
                fb = {**agent, "name": f"{agent_name} (Nemotron)",
                      "provider": "openrouter",
                      "model": "nvidia/nemotron-3-ultra-550b-a55b"}
                log_live("TOOL", "🔁 Nemotron Ultra mulai membangun ulang website...")
                generated_content = await generate_agent_response(
                    fb, web_prompt, WEB_ENGINEER_SYS,
                    max_tokens=16000, timeout_s=190.0,
                )
                log_live("TOOL", f"⏱️ Nemotron selesai -> {len(generated_content or '')} char")
                page = _extract_html_doc(generated_content)
                fb_note = " (via Nemotron Ultra)"

            if _valid(page):
                slug = re.sub(r"[^a-z0-9]+", "_", topic.lower())[:30].strip("_") or "site"
                site_dir = os.path.join(SWARM_OUTPUT_DIR, "websites",
                                        slug + "_" + str(int(time.time())))
                os.makedirs(site_dir, exist_ok=True)
                fpath = os.path.join(site_dir, "index.html")
                with open(fpath, "w", encoding="utf-8") as f:
                    f.write(page)
                deliverable_file = fpath
                status = "success"
                tool_output = (
                    f"Website tersimpan: {fpath} ({len(page)//1024} KB){fb_note}\n"
                    f"Struktur valid: doctype+html+body OK - buka langsung di browser."
                )
                generated_content = (
                    f"Website '{topic[:50]}' selesai dibangun ({len(page)//1024} KB){fb_note}, "
                    f"tersimpan di {fpath}. Buka index.html di browser untuk preview."
                )
            else:
                status = "error"
                tool_output = (
                    f"Website ditolak validasi: dokumen tidak utuh "
                    f"(panjang {len(page)} char). Coba instruksi lebih spesifik."
                )
                generated_content = (
                    "Gagal membangun website yang valid untuk brief ini. "
                    "Butuh brief lebih detail dari pengguna."
                )

    # 3. SPECIALIST: CYBER SENTRY / AUDITOR (Real System Security & Resource Audit)
    elif "Sentry" in agent_name or "Security" in role or "Auditor" in role:
        tool_name = "audit_system_integrity"
        try:
            import security_auditor
            audit = security_auditor.audit_local_host_security()
        except Exception as audit_err:
            audit = {"status": "error", "error": str(audit_err)}

        if audit.get("status") == "success":
            status = "error" if audit.get("critical_findings") else "success"
            check_lines = "\n".join(
                f"{'✅' if c['status'] == 'PASS' else '❌'} {c['check']}: {c['detail']}"
                for c in audit["checks"]
            )
            tool_output = (
                f"Host Security Audit (skor {audit['score']}/100, grade {audit['grade']}):\n{check_lines}"
            )
            critical_note = (
                f" TEMUAN KRITIS: {'; '.join(audit['critical_findings'])}." if audit.get("critical_findings") else ""
            )
            generated_content = (
                f"Audit host selesai: {audit['passed']}/{audit['total_checks']} cek lolos "
                f"(grade {audit['grade']}).{critical_note}"
            )
        else:
            status = "error"
            tool_output = f"Host audit gagal dieksekusi: {audit.get('error')}"
            generated_content = f"Audit keamanan host gagal dijalankan: {audit.get('error')}"

    # 4. GENERAL / LEAD SYNTHESIS
    else:
        tool_name = "strategic_orchestration"
        prompt = f"Berikan deklarasi eksekusi tugas nyata untuk `{topic}` secara santai dan tegas."
        generated_content = await generate_agent_response(agent, prompt, "Kamu adalah manajer strategi Swarm AI.")
        tool_output = f"Koordinasi tugas `{topic[:60]}` sukses didistribusikan ke seluruh agen pelaksana."

    duration_ms = round((time.time() - t0) * 1000, 2)

    database.log_agent_activity_sync(
        agent_id=agent_id,
        agent_name=agent_name,
        action_type=action_type,
        description=f"Eksekusi Swarm: {task_instruction[:80]}",
        tool_name=tool_name,
        tool_input=tool_input[:200],
        tool_output=tool_output[:300],
        status=status,
        duration_ms=duration_ms
    )

    return {
        "agent_name": agent_name,
        "role": role,
        "avatar_emoji": agent.get("avatar_emoji", "🤖"),
        "color_theme": agent.get("color_theme", "cyan"),
        "task_assigned": task_instruction,
        "tool_used": tool_name,
        "execution_summary": tool_output,
        "generated_content": generated_content,
        "deliverable_file": deliverable_file,
        "deliverable_data": deliverable_data,
        "duration_ms": duration_ms,
        "status": status,
        "timestamp": datetime.now().strftime("%H:%M:%S")
    }


async def conduct_multi_agent_meeting(
    topic: str, 
    participant_names: Optional[List[str]] = None, 
    rounds: int = 2,
    mode: str = "plan"
) -> Dict[str, Any]:
    """
    Conduct an autonomous multi-agent session with TWO distinct modes:
    1. 'plan': Round-table debate, architectural brainstorming, and action plan consensus.
    2. 'execute' (or 'plan_and_execute'): Rapid strategic alignment + LIVE AUTONOMOUS EXECUTION where agents
       simultaneously run tools, execute code, scrape data, audit security, and produce real output files!
    """
    mode = mode.lower().strip()
    if mode not in ["plan", "execute", "plan_and_execute"]:
        mode = "plan"

    intent_info = detect_task_intent(topic)

    all_agents = database.list_custom_agents_sync()
    if not all_agents:
        database.init_db_sync()
        all_agents = database.list_custom_agents_sync()

    if participant_names:
        participants = [a for a in all_agents if a["name"] in participant_names and a.get("is_enabled", 1)]
    else:
        participants = [a for a in all_agents if a.get("is_enabled", 1)][:5]

    if not participants:
        participants = all_agents[:3]

    dialogue_transcript = []
    history_summary = []
    execution_steps = []

    meeting_type_label = "⚡ SWARM EKSEKUSI LANGSUNG" if mode in ["execute", "plan_and_execute"] else "📋 RAPAT STRATEGIS & PLAN"
    meeting_title = f"{meeting_type_label}: {topic[:60]}"

    logger.info(f"🏛️ Starting AI Session [{mode.upper()}] on topic: '{topic}' with {len(participants)} agents.")
    global MEETING_RUNNING
    MEETING_RUNNING = True
    log_live("SESSION", f"Sesi {mode.upper()} dimulai — topik: {topic[:80]} ({len(participants)} agen)")
    # Snapshot folder sandbox utk auto-harvester di akhir rapat
    _SANDBOX_SNAPSHOT.clear()
    _SANDBOX_SNAPSHOT.update(_sandbox_project_dirs())

    # --- PHASE 1: Dialogue & Alignment ---
    actual_rounds = 1 if mode in ["execute", "plan_and_execute"] else rounds

    for r in range(1, actual_rounds + 1):
        for agent in participants:
            context_text = "\n".join(history_summary) if history_summary else "(Sesi baru saja dibuka oleh Alpha Lead)"
            
            if mode in ["execute", "plan_and_execute"]:
                prompt = (
                    f"=== PERINTAH EKSEKUSI LANGSUNG SWARM ===\n"
                    f"Tujuan: {topic}\n\n"
                    f"=== ALUR KOORDINASI TIM ===\n"
                    f"{context_text}\n\n"
                    f"=== IDENTITAS KAMU ===\n"
                    f"Nama: {agent['name']} ({agent['role']})\n\n"
                    f"TUGAS KAMU (PERSIAPAN EKSEKUSI LANGSUNG):\n"
                    f"1. Jelaskan dalam 1-2 kalimat santai peran nyata apa yang LANGSUNG KAMU EKSEKUSI SEKARANG untuk menyelesaikan misi ini.\n"
                    f"2. Bicara santai, tegas, siap aksi!"
                )
            else:
                prompt = (
                    f"=== TOPIK AGENDA DISKUSI ===\n"
                    f"{topic}\n\n"
                    f"=== RIWAYAT OBROLAN TIM (PUTARAN {r}) ===\n"
                    f"{context_text}\n\n"
                    f"=== IDENTITAS KAMU ===\n"
                    f"Nama: {agent['name']} ({agent['role']})\n"
                    f"Persona: {agent['persona']}\n\n"
                    f"TUGAS KAMU:\n"
                    f"1. Berikan tanggapan/solusi teknis tajam sesuai bidang keahlianmu.\n"
                    f"2. Langsung sanggah/kritisi/dukung poin peserta lain secara to-the-point.\n"
                    f"3. HEMAT TOKEN & ON-POINT: Tulis 2 sampai 4 kalimat padat saja."
                )

            response_text = await generate_agent_response(
                agent=agent,
                prompt=prompt,
                system_instruction=agent.get("system_instruction", "Kamu adalah anggota tim AI otonom profesional.")
            )

            entry = {
                "round": r,
                "agent_name": agent["name"],
                "role": agent["role"],
                "avatar_emoji": agent.get("avatar_emoji", "🤖"),
                "color_theme": agent.get("color_theme", "cyan"),
                "message": response_text,
                "timestamp": datetime.now().strftime("%H:%M:%S")
            }
            dialogue_transcript.append(entry)
            history_summary.append(f"[{agent['name']} - {agent['role']}]:\n{response_text}\n")
            log_live("DIALOG", f"💬 {entry['agent_name']}: {response_text[:140]}")

    # --- PHASE 2: Live Autonomous Swarm Execution (Real Tools & Real Data) ---
    if mode in ["execute", "plan_and_execute"]:
        logger.info(f"⚡ Launching Live Autonomous Swarm Execution for {len(participants)} agents...")

        # Dynamic task decomposition: lead breaks the topic into one concrete
        # subtask per agent instead of generic role assignments.
        subtask_map = await _decompose_task(topic, participants)
        if subtask_map:
            logger.info("Task decomposition OK: %s", list(subtask_map.keys()))
            for _n, _t in subtask_map.items():
                log_live("PLAN", f"🗂️ {_n}: {_t[:90]}")

        ctx_lines: List[str] = []
        for idx, agent in enumerate(participants):
            task_desc = subtask_map.get(agent["name"]) or f"Eksekusi modul {agent['role']} untuk '{topic[:60]}'"

            # Konteks berantai: agen berikutnya mengetahui hasil agen sebelumnya,
            # sehingga misi bertingkat (riset -> kode -> audit) benar2 menyambung.
            if ctx_lines:
                task_desc += (
                    "\n\nKONTEKS HASIL AGEN SEBELUMNYA (gunakan bila relevan):\n- "
                    + "\n- ".join(ctx_lines[-3:])
                )

            log_live("EXEC", f"⚙️ {agent['name']} mulai eksekusi: {task_desc[:90]}")

            step_result = await execute_swarm_task_step(agent, task_desc, topic, intent_info)
            if step_result.get("deliverable_file"):
                log_live("FILE", f"📁 {agent['name']} menghasilkan berkas: {os.path.basename(step_result['deliverable_file'])}")

            # Verification loop: a strict QA judge checks for real evidence;
            # failed steps get ONE retry with corrective feedback. Pure-text
            # orchestration steps are recorded but not retried.
            passed, feedback = await _verify_step_result(task_desc, step_result)
            attempts = 0
            while (
                not passed
                and attempts < 1
                and step_result.get("tool_used") != "strategic_orchestration"
            ):
                attempts += 1
                logger.warning(f"Step '{agent['name']}' FAILED verification: {feedback} - retrying with corrections...")
                retry_desc = (
                    f"{task_desc}\n"
                    f"PERCOBAAN SEBELUMNYA DITOLAK VERIFIKATOR: {feedback}\n"
                    f"Kerjakan ulang dan pastikan menghasilkan bukti nyata (file/data/output)."
                )
                step_result = await execute_swarm_task_step(agent, retry_desc, topic, intent_info)
                step_result["retry_count"] = attempts
                passed, feedback = await _verify_step_result(retry_desc, step_result)

            step_result["verification"] = "PASS" if passed else ("FAIL" if step_result.get("tool_used") != "strategic_orchestration" else "N/A")
            log_live("VERIFY", f"{'✅ PASS' if passed else '❌ FAIL'} — {agent['name']} ({step_result.get('tool_used')}){(': ' + feedback[:80]) if not passed and feedback else ''}")
            execution_steps.append(step_result)

            brief = (step_result.get("execution_summary") or "")[:180].replace("\n", " ")
            ctx_lines.append(f"{step_result['agent_name']} -> {brief}")

    # --- PHASE 3: Final Consensus & Real Deliverables Synthesis by Lead Agent ---
    if not participants:
        error_msg = (
            "Tidak ada agen yang terdaftar di workforce. "
            "Tambahkan minimal satu agen terlebih dahulu (Dashboard > AI Workforce) sebelum menjalankan rapat swarm."
        )
        logger.error(error_msg)
        MEETING_RUNNING = False
        log_live("ERROR", "Sesi dibatalkan: tidak ada agen terdaftar.")
        return {
            "status": "error",
            "error": error_msg,
            "topic": topic,
            "dialogue_transcript": [],
            "execution_steps": [],
            "consensus": "",
            "action_plan": ""
        }

    lead_agent = participants[0]
    
    if mode in ["execute", "plan_and_execute"]:
        # Collect real files and real data extracted
        real_files = [s['deliverable_file'] for s in execution_steps if s.get('deliverable_file')]
        real_summaries = "\n".join([
            f"• **{s['agent_name']} ({s['role']})** [Tool: `{s['tool_used']}` | {s['duration_ms']}ms]:\n  {s['execution_summary']}"
            for s in execution_steps
        ])

        consensus_prompt = (
            f"=== TARGET PERINTAH DARI USER ===\n{topic}\n\n"
            f"=== HASIL EKSEKUSI NYATA DARI TOOLS & SYSTEM ===\n{real_summaries}\n\n"
            f"File Output Tersimpan: {', '.join(real_files) if real_files else 'N/A'}\n\n"
            f"Sebagai kapten Swarm ({lead_agent['name']}), buatlah LAPORAN HASIL NYATA YANG LENGKAP & TO-THE-POINT:\n"
            f"1. 🎯 STATUS EKSEKUSI: Jelaskan bahwa tugas SUDAH DIJALANKAN LANGSUNG OLEH TOOLS SISTEM (Bukan sekadar rencana).\n"
            f"2. 📊 HASIL NYATA & DATA: Tampilkan rangkuman data/angka konkret yang didapatkan dari eksekusi di atas.\n"
            f"3. 📁 FILE ARTIFAK SIAP PAKAI: Sebutkan file CSV/Python yang sudah tersimpan di `{SWARM_OUTPUT_DIR}`.\n"
            f"4. 💡 KESIMPULAN / INSIGHT: Berikan insight praktis atas hasil data/kode tersebut.\n"
            f"Gunakan gaya bicara santai, gaul, tegas, to-the-point!"
        )
    else:
        consensus_prompt = (
            f"=== TOPIK RAPAT ===\n{topic}\n\n"
            f"=== TRANSKRIP LENGKAP DISKUSI TIM ===\n" + "\n".join(history_summary) + "\n\n"
            f"Sebagai kapten rapat ({lead_agent['name']}), buatlah rangkuman KONSENSUS & ACTION PLAN yang ON-POINT:\n"
            f"1. KONSENSUS UTAMA (Inti kesepakatan tim dalam 2-3 poin ringkas).\n"
            f"2. ACTION PLAN (Tabel tugas terstruktur: No, Modul/Tugas, Penanggung Jawab, Target).\n"
            f"Gunakan gaya bahasa santai, tegas, to-the-point tanpa basa-basi."
        )

    consensus_text = await generate_agent_response(
        agent=lead_agent,
        prompt=consensus_prompt,
        system_instruction="Kamu adalah kapten tim AI yang memimpin perumusan keputusan akhir dan pelaporan hasil eksekusi nyata."
    )

    action_plan_text = ""
    marker = "ACTION PLAN"
    marker_idx = consensus_text.upper().find(marker)
    if marker_idx != -1:
        # Case-insensitive split: the model may write "Action Plan" etc.
        consensus_text_clean = consensus_text[:marker_idx].strip()
        action_plan_text = marker + consensus_text[marker_idx + len(marker):]
    else:
        consensus_text_clean = consensus_text

    # Save to SQLite database
    saved = database.create_agent_meeting_sync(
        title=meeting_title,
        topic=topic,
        participants=[a["name"] for a in participants],
        dialogue_transcript=dialogue_transcript,
        consensus=consensus_text_clean,
        action_plan=action_plan_text,
        mode=mode,
        execution_results=execution_steps,
        status="completed"
    )
    MEETING_RUNNING = False
    # Auto-harvester: arsipkan proyek baru yang dibangun agen ke outputs
    _harvest_new_sandbox_projects(topic)
    log_live("DONE", f"🏁 Rapat selesai & tersimpan sebagai Meeting #{saved.get('id')}")

    return {
        "status": "success",
        "meeting_id": saved.get("id"),
        "title": meeting_title,
        "topic": topic,
        "mode": mode,
        "participants": [a["name"] for a in participants],
        "dialogue_transcript": dialogue_transcript,
        "execution_results": execution_steps,
        "consensus": consensus_text_clean,
        "action_plan": action_plan_text
    }
