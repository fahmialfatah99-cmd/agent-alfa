"""
Autonomous Multi-Agent Swarm & Meeting Engine for ALFA Ecosystem.
Enables round-table AI meetings, inter-agent dialogue, debate, consensus building,
and live autonomous collaborative execution (Swarm Work Mode with REAL tools, files, and scraping).
"""

import asyncio
import collections
import itertools
import json
import logging
import os
import re
import shutil
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

load_dotenv()

from google import genai
from google.genai import types

import database
import token_usage
import tools

# Checkpoint & tracing: opsional — bot tetap berjalan tanpa keduanya
try:
    from swarm_checkpoint import SwarmCheckpoint as _SwarmCheckpoint
    _CHECKPOINT_AVAILABLE = True
except ImportError:
    _CHECKPOINT_AVAILABLE = False
    _SwarmCheckpoint = None

try:
    import tracing as _tracing
    _TRACING_AVAILABLE = True
except ImportError:
    _TRACING_AVAILABLE = False
    _tracing = None

logger = logging.getLogger(__name__)

# Provider bawaan yang URL-nya sudah dipetakan otomatis. Provider di luar daftar
# ini (misal 'custom'/'tokenra'/'oxalpha') tetap didukung selama kuncinya punya
# Base URL OpenAI-compatible di vault.
KNOWN_OPENAI_PROVIDERS = {
    "openai", "groq", "openrouter", "9router", "ollama", "nvidia", "nim",
    "deepseek", "minimax", "moonshot", "kimi", "qwen", "dashscope",
}

SWARM_OUTPUT_DIR = os.path.expanduser("~/Dokumen/ALFA_SWARM_OUTPUTS")
# Batas maksimal agen yang dieksekusi dalam satu sesi swarm (mode otomatis
# tanpa pilihan peserta). Naikkan via .env: ALFA_SWARM_MAX_AGENTS=15
MAX_SWARM_AGENTS = max(1, int(os.getenv("ALFA_SWARM_MAX_AGENTS", "15")))
# Jumlah maksimal putaran uji QA (Sentinel QA) sampai zero bug. 0 = matikan.
MAX_QA_ROUNDS = max(0, int(os.getenv("ALFA_SWARM_QA_ROUNDS", "3")))
os.makedirs(SWARM_OUTPUT_DIR, exist_ok=True)

# ── AUTO-HARVESTER: arsipkan proyek baru dari sandbox di akhir rapat ────────
# Folder fullstack multi-file yang dibangun agen lewat bash bebas hidup di
# RAM disk (/dev/shm) dan TIDAK ikut salinan deliverable standar (CSV/HTML).
# Snapshot diambil saat rapat mulai; di akhir rapat folder baru diarsipkan
# otomatis ke ALFA_SWARM_OUTPUTS/projects tanpa node_modules & sejenisnya.
_HARVEST_EXCLUDE = {"node_modules", ".next", ".git", ".toolchain",
                    "__pycache__", ".cache", ".local", ".venv", "venv"}
_SANDBOX_SNAPSHOT: set = set()
# Folder target kerja agen saat sesi eksekusi berjalan ("" = bebas).
_TARGET_FOLDER: str = ""
# Ground-truth filesystem utk verifikasi anti-bohong (execute mode):
# {path_file: "size:mtime_ns"} dari seluruh folder proyek sandbox.
_EXEC_FS_SNAPSHOT: Dict[str, str] = {}


def _hash_sandbox_projects() -> Dict[str, str]:
    out: Dict[str, str] = {}
    try:
        if _TARGET_FOLDER and os.path.isdir(_TARGET_FOLDER):
            roots = [_TARGET_FOLDER]
        else:
            sb = tools.SANDBOX_DIR
            roots = [os.path.join(sb, d) for d in os.listdir(sb)
                     if os.path.isdir(os.path.join(sb, d)) and not d.startswith(".")]
        for pdir in roots:
            for root, dirs, files in os.walk(pdir):
                dirs[:] = [x for x in dirs if x not in _HARVEST_EXCLUDE]
                for f in files:
                    fp = os.path.join(root, f)
                    try:
                        st = os.stat(fp)
                        out[fp] = f"{st.st_size}:{st.st_mtime_ns}"
                    except OSError:
                        pass
    except Exception:
        pass
    return out


def _fs_changed_since_snapshot() -> bool:
    if not _EXEC_FS_SNAPSHOT:
        return True  # tanpa snapshot: jangan blokir
    return _hash_sandbox_projects() != _EXEC_FS_SNAPSHOT


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
        # Folder target (mis. dibuat otomatis sebelum snapshot) tetap
        # di-harvest walau sudah ada di snapshot awal.
        if _TARGET_FOLDER and os.path.isdir(_TARGET_FOLDER):
            new_dirs.add(os.path.basename(_TARGET_FOLDER.rstrip("/")))
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
            if total < 512:
                log_live("HARVEST", f"⏭️ '{d}' dilewati (folder kosong/tanpa karya)")
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
# Flag cancel berbasis file: eksekusi swarm bisa berjalan di proses bot ATAU
# dashboard, jadi sinyal batalkan harus lintas proses.
CANCEL_FLAG_FILE = os.path.join(SWARM_OUTPUT_DIR, "swarm_cancel.flag")
LIVE_LOG: "collections.deque" = collections.deque(maxlen=400)
MEETING_RUNNING = False


def request_cancel_swarm() -> bool:
    """Minta pembatalan eksekusi swarm yang sedang berjalan.
    Return True bila memang ada sesi aktif untuk dibatalkan."""
    if not MEETING_RUNNING:
        return False
    try:
        os.makedirs(SWARM_OUTPUT_DIR, exist_ok=True)
        with open(CANCEL_FLAG_FILE, "w", encoding="utf-8") as f:
            f.write(str(time.time()))
    except OSError:
        pass
    log_live("CANCEL", "⏹ Permintaan pembatalan diterima — menghentikan setelah langkah berjalan selesai...")
    return True


def _cancel_requested() -> bool:
    return os.path.exists(CANCEL_FLAG_FILE)


def _clear_cancel_flag() -> None:
    try:
        if os.path.exists(CANCEL_FLAG_FILE):
            os.remove(CANCEL_FLAG_FILE)
    except OSError:
        pass


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


def log_tool_live(text: str) -> None:
    """Jembatan aktivitas tool dari jalur MainBrain -> live feed UI.
    Hanya menulis saat ada rapat berjalan; aman dipanggil lintas modul."""
    if not MEETING_RUNNING:
        return
    log_live("TOOL", text)


# ── ERROR PROPAGATION ────────────────────────────────────────────────────────
# Structured error record per step, dikumpulkan selama sesi berlangsung
# dan dikirim ke agen berikutnya sebagai konteks agar pipeline tidak buta.

def _build_error_context(failed_steps: list) -> str:
    """Format daftar kegagalan agen menjadi blok konteks untuk agen berikutnya.

    Dipanggil setiap kali ada agen yang gagal verifikasi, sehingga agen
    selanjutnya dalam pipeline mengetahui apa yang sudah TIDAK berhasil
    dan tidak mengulangi pekerjaan yang sama.
    """
    if not failed_steps:
        return ""
    lines = ["⚠️ KEGAGALAN AGEN SEBELUMNYA (jangan ulangi — selesaikan yang belum):"]
    for fs in failed_steps[-3:]:  # hanya 3 terakhir agar tidak overflow
        lines.append(
            f"  • {fs.get('agent_name','?')} [{fs.get('tool_used','?')}]: "
            f"{(fs.get('feedback') or fs.get('execution_summary',''))[:120]}"
        )
    return "\n".join(lines)


def _record_step_error(session_id: str, step_result: dict, feedback: str) -> None:
    """Catat kegagalan satu step ke checkpoint jika tersedia."""
    if _CHECKPOINT_AVAILABLE and session_id:
        try:
            _SwarmCheckpoint.add_error(
                session_id=session_id,
                step_name=step_result.get("task_assigned", "")[:80],
                agent_name=step_result.get("agent_name", "?"),
                error=feedback or step_result.get("execution_summary", "")
            )
        except Exception:
            pass


def qa_verdict_passed(text: str) -> bool:
    """True bila teks laporan QA memuat verdict LULUS (QA_VERDICT: PASS).

    Fungsi murni sengaja dipisah agar keputusan zero-bug bisa diuji unit
    tanpa menjalankan seluruh sesi swarm. Toleran terhadap varian spasi
    dan huruf besar-kecil dari keluaran model.
    """
    return bool(re.search(r"QA_VERDICT\s*:\s*PASS", text or "", re.IGNORECASE))


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


def _default_gemini_model() -> str:
    """Model Gemini default yang SELALU hidup: ikut otak utama vault,
    lalu default kunci gemini aktif, terakhir generik terbaru."""
    try:
        m = (database.get_main_brain_model() or "").strip()
        if m:
            return m
    except Exception:
        pass
    try:
        k = database.get_active_api_key_sync("gemini")
        m = ((k or {}).get("default_model") or "").strip()
        if m:
            return m
    except Exception:
        pass
    return "gemini-flash-latest"


def get_agent_api_client(agent: Dict[str, Any]) -> tuple[str, str, str, Optional[str], Optional[int]]:
    """Resolve (provider, api_key, model, base_url, key_id) for a specific agent."""
    provider = (agent.get("provider") or "gemini").lower()
    model = agent.get("model") or (_default_gemini_model()
                                   if provider == "gemini" else "")
    api_key = ""
    base_url = ""
    key_id = None

    if agent.get("api_key_id"):
        with database.get_sync_db() as conn:
            row = conn.execute("SELECT id, provider, api_key, default_model, base_url FROM api_keys WHERE id = ?", (agent["api_key_id"],)).fetchone()
            if row:
                provider = row["provider"]
                api_key = database.decrypt_key(row["api_key"])
                base_url = row["base_url"] or ""
                key_id = row["id"]
                if not agent.get("model"):
                    model = row["default_model"]

    if not api_key:
        active_key = database.get_active_api_key_sync(provider)
        if active_key:
            api_key = active_key["api_key"]
            base_url = active_key.get("base_url") or ""
            key_id = active_key.get("id")

    if not api_key:
        if provider == "gemini":
            api_key = os.getenv("GEMINI_API_KEY", "")
        elif provider == "openai":
            api_key = os.getenv("OPENAI_API_KEY", "")
        elif provider == "groq":
            api_key = os.getenv("GROQ_API_KEY", "")
        elif provider in ["nvidia", "nim"]:
            api_key = os.getenv("NVIDIA_API_KEY", "")
        elif provider == "9router":
            api_key = os.getenv("NINEROUTER_API_KEY", os.getenv("ROUTER_API_KEY", ""))

    if provider == "9router":
        if not base_url:
            base_url = "http://127.0.0.1:20128/v1"
        if not model:
            model = "all"
        if not api_key:
            try:
                import glob as _glob, sqlite3 as _sq
                db_paths = _glob.glob(os.path.expanduser("~/.9router/db/data.sqlite")) + \
                           _glob.glob(os.path.expandvars(r"%APPDATA%\9router\db\data.sqlite"))
                for dbp in db_paths:
                    if os.path.exists(dbp):
                        with _sq.connect(dbp) as _c:
                            rk = _c.execute("SELECT key FROM apiKeys WHERE isActive=1 LIMIT 1").fetchone()
                            if rk and rk[0]:
                                api_key = rk[0]
                                break
            except Exception:
                pass

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
        "gemini-3.6-flash,gemini-3.7-flash,gemini-flash-latest"
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
                url = "http://127.0.0.1:20128/v1"
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
            "max_tokens": max_tokens,
            "stream": False
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
                try:
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
                except Exception as parse_err:
                    # Fallback untuk SSE streaming chunk jika respons berupa data: {...}
                    logger.warning(f"[{provider}] JSON parse fallback ({parse_err!r}) -> mencoba parsing SSE chunks")
                    content_parts = []
                    for line in res.text.splitlines():
                        line_str = line.strip()
                        if line_str.startswith("data: ") and line_str != "data: [DONE]":
                            try:
                                import json as _json
                                chunk = _json.loads(line_str[6:].strip())
                                delta = (chunk.get("choices") or [{}])[0].get("delta", {})
                                c = delta.get("content") or delta.get("reasoning_content") or ""
                                if c:
                                    content_parts.append(c)
                            except Exception:
                                pass
                    if content_parts:
                        return "".join(content_parts).strip()
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
                        res = await http_client.post(f"{url.rstrip('/')}/chat/completions",
                                                     headers=headers, json=payload)
                    except Exception as retry_err:
                        logger.error(
                            f"[{provider}] retry 402 gagal: {type(retry_err).__name__}: {retry_err}")
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

            if res.status_code == 429:
                retry_after_str = res.headers.get("Retry-After", "2")
                try:
                    delay = min(max(float(retry_after_str), 1.0), 5.0)
                except ValueError:
                    delay = 2.0
                logger.warning(f"[{provider}] HTTP 429 Rate Limit for '{agent_name}'. Backing off {delay}s...")
                await asyncio.sleep(delay)
                try:
                    res = await http_client.post(f"{url.rstrip('/')}/chat/completions",
                                                 headers=headers, json=payload)
                    if res.status_code == 200:
                        data = res.json()
                        token_usage.from_openai_json(data, provider=provider, model=model,
                                                     key_id=key_id, key_label=key_label,
                                                     context=context)
                        msg0 = (data.get("choices") or [{}])[0].get("message") or {}
                        content = (msg0.get("content") or "").strip()
                        if content:
                            return content
                except Exception as retry_err:
                    logger.error(f"[{provider}] retry 429 failed: {retry_err}")

            err_detail = res.text[:200] or "(empty body)"
            logger.error(f"{provider} HTTP {res.status_code} for agent '{agent_name}' (model={model}): {err_detail}")
            return None
    except Exception as e:
        logger.error(f"Error in {provider} agent '{agent_name}': {e!r}")
        return None


async def generate_agent_response(agent: Dict[str, Any], prompt: str, system_instruction: str,
                                  max_tokens: Optional[int] = None,
                                  timeout_s: float = 180.0,
                                  thinking_budget: Optional[int] = None) -> Optional[str]:
    """Generate response for a specific agent using its configured provider and key.

    If the agent's primary provider fails (timeout, bad key, quota, etc.), it
    automatically falls back to Gemini so the swarm conversation never loses
    a participant silently.

    Return None saat SEMUA provider & fallback gagal — pemanggil WAJIB
    memeriksa None; jangan pernah mengembalikan teks error sebagai
    respons sukses (dulu penyebab teks '[Error: ...]' tercatat sebagai
    hasil kerja dan terlanjur tertulis ke file deliverable).
    """
    provider, api_key, model, base_url, key_id = get_agent_api_client(agent)
    agent_name = agent.get("name", "Agent")
    enable_tools = bool(agent.get("enable_tools"))
    # Agen ber-tool butuh budget jauh lebih besar: siklus thinking ->
    # function call -> eksekusi -> ringkasan tak muat di 500 token
    # (dulu penyebab model halusinasi 'file berhasil dibuat' tanpa file).
    eff_max_tokens = max_tokens or (4000 if enable_tools else 500)

    tone_directive = (
        "\n\n[PANDUAN OUTPUT & GAYA BICARA]:"
        "\n1. BICARA SANTAI & GAUL: Gunakan gaya bahasa santai, luwes, natural ala software engineer/tech specialist di war room (jangan kaku, hindari basa-basi robot seperti 'Sebagai AI...', 'Tentu saja...')."
        "\n2. ON-POINT & REALISTIS: Langsung sebutkan fakta teknis nyata dan aksi nyata yang dilakukan tanpa bertele-tele. Maksimal 2-4 kalimat."
    )
    if enable_tools:
        # Agen ber-tool: disiplin kerja ketat. Tone santai membuat model
        # menjawab singkat TANPA memanggil tool (hallusinasi sukses).
        final_instruction = (
            (system_instruction or "Kamu adalah engineer spesialis di AI Swarm.")
            + "\n\n[DISIPLIN EKSEKUSI]:\n"
            "1. Setiap giliran WAJIB memuat panggilan function call.\n"
            "2. Kerjakan sendiri lewat tool — jangan memberi instruksi ke orang lain.\n"
            "3. Sebelum melapor selesai, pastikan file benar-benar ditulis via tool."
        )
    else:
        final_instruction = (system_instruction or "Kamu adalah engineer spesialis di AI Swarm.") + tone_directive

    key_label = f"agent:{agent_name}"

    def gemini_like_tools() -> List[Any]:
        """Subset aman tool swarm (identik dgn jalur gemini enable_tools)."""
        try:
            import main_brain as _mb
            import tools as _t
            return [getattr(_t, n) for n in sorted(_mb.SAFE_TOOL_NAMES)
                    if hasattr(_t, n) and callable(getattr(_t, n))]
        except Exception:
            return []

    result = None
    if provider == "gemini":
        gemini_tools = None
        if enable_tools:
            gemini_tools = gemini_like_tools() or None
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
            max_tokens=eff_max_tokens,
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
            # Sentinel kegagalan senyap: provider balas 200 tapi kosong
            # (terlihat di ox-alpha). Perlakukan sebagai gagal agar
            # fallback gemini-agentic ber-tool yang mengambil alih.
            if isinstance(result, str) and (
                result.startswith("(provider tidak mengirim teks)")
                or not result.strip()
            ):
                logger.warning(
                    f"Agentic turn '{agent_name}' balas kosong -> paksa fallback.")
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
            max_tokens=eff_max_tokens,
            timeout_s=timeout_s,
        )
        if result is None and enable_tools:
            # Agen ber-tool TIDAK boleh jatuh ke jalur tanpa tool (sumber
            # hallusinasi 'berhasil' kosong). Fallback: agen Gemini dengan
            # disiplin & tool identik — coba SEMUA kunci gemini aktif
            # KECUALI kunci yang baru saja gagal (kunci bermasalah, mis.
            # kuota habis, tak akan menyembuhkan dirinya sendiri).
            try:
                gem_keys = [k for k in database.list_active_keys_sync()
                            if (k.get("provider") or "").lower() == "gemini"
                            and k.get("id") != key_id]
            except Exception:
                gem_keys = []
            for gk in gem_keys:
                try:
                    logger.warning(
                        f"Agen ber-tool '{agent_name}' gagal via {provider} "
                        f"-> fallback Gemini agentic k#{gk.get('id')} (tools tetap aktif).")
                    gagent = {
                        "name": agent_name,
                        "provider": "gemini",
                        "model": (gk.get("default_model") or "gemini-flash-latest").strip(),
                        "api_key_id": gk.get("id"),
                        "enable_tools": 1,
                    }
                    result = await generate_agent_response(
                        gagent,
                        prompt,
                        "Kamu agen pelaksana swarm. KERJA MENGGUNAKAN TOOL: setiap "
                        "giliran WAJIB memuat panggilan function call "
                        "(write_local_file / edit_file_precise / execute_bash_command). "
                        "Membalas teks saja = GAGAL.",
                        max_tokens=eff_max_tokens,
                        timeout_s=timeout_s,
                        thinking_budget=thinking_budget,
                    )
                    if result is not None:
                        break
                except Exception as fb_err:
                    logger.warning(f"Gemini agentic fallback gagal: {fb_err!r}")

        if result is None and os.getenv("GEMINI_API_KEY"):
            logger.warning(f"Provider '{provider}' gagal untuk '{agent_name}' - fallback ke Gemini.")
            result = await _generate_with_gemini(
                agent_name=f"{agent_name} (fallback)",
                api_key=os.getenv("GEMINI_API_KEY", ""),
                models=["gemini-3.6-flash"],
                prompt=prompt,
                final_instruction=final_instruction,
                key_id=None,
                key_label="gemini-fallback",
                context="swarm",
                thinking_budget=thinking_budget,
            )

    if result is None:
        logger.error(
            f"[Swarm] '{agent_name}': semua provider & fallback gagal "
            f"(primary: {provider}) — langkah ini dilaporkan GAGAL.")
        return None
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
        m = re.search(r"\[.*\]", raw or "", re.DOTALL)
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
    # ── GROUND-TRUTH FILESYSTEM CHECK ──
    # Untuk tugas yang mengklaim membangun/mengubah kode: pakai bukti
    # perubahan file tingkat-langkah (pre/post hash) bila tersedia;
    # fallback ke snapshot global untuk data lama.
    low_task = (task or "").lower()
    claims_file_work = any(k in low_task for k in (
        "bangun", "buat", "perbaiki", "sempurnakan", "refactor", "tulis",
        "kode", "website", "aplikasi", "file", "deploy", "komponen", "halaman"))
    # Inisialisasi dulu: langkah berstatus gagal (error) tidak boleh
    # memunculkan NameError saat variabel ini dirujuk di bawah.
    fs_changed = None
    changed_sample: List[str] = []
    if claims_file_work and step_result.get("status") == "success":
        fs_changed = step_result.get("fs_changed")
        if fs_changed is None and _EXEC_FS_SNAPSHOT:
            fs_changed = len(_hash_sandbox_projects()) != len(_EXEC_FS_SNAPSHOT) or \
                         bool(set(_hash_sandbox_projects()) ^ set(_EXEC_FS_SNAPSHOT))
        if fs_changed == 0:
            log_live("VERIFY",
                     "🚫 GROUND-TRUTH: tidak ada file proyek berubah -> klaim eksekusi ditolak mekanis")
            return False, ("FAIL: GROUND-TRUTH FILESYSTEM - tidak ada satu pun file proyek "
                           "yang berubah. Kerjakan nyata dan tulis perubahan ke folder kerja.")
        changed_sample = step_result.get("changed_sample") or []

    summary = (step_result.get("execution_summary") or "")[:600]
    fs_evidence = ""
    if claims_file_work and fs_changed is not None:
        samp = "; ".join(changed_sample[:4]) if changed_sample else "(detail tak tersedia)"
        fs_evidence = f"\n- BUKTI FILESYSTEM: {fs_changed} file berubah ({samp})\n"
    prompt = (
        f"TUGAS YANG DIMINTA: {task[:300]}\n\n"
        f"HASIL EKSEKUSI:\n- Tool: {step_result.get('tool_used')}\n"
        f"- Status: {step_result.get('status')}\n{fs_evidence}- Output: {summary}\n\n"
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




async def _single_shot_edit_fallback(agent: Dict[str, Any], task_instruction: str,
                                     target_folder: str) -> str:
    """Penyelesai pamungkas: minta KONTEN PENUH satu file utama dari model,
    lalu engine menulisnya sendiri (tanpa bergantung tool-call model)."""
    import glob as _glob
    cands = []
    for pat in ("index.html", "page.html", "*.html", "*.htm",
                "main.py", "app.py", "*.py", "*.md"):
        cands += [p for p in _glob.glob(os.path.join(target_folder, "**", pat),
                                        recursive=True)
                  if "node_modules" not in p]
    cands = sorted(set(cands), key=lambda p: os.path.getmtime(p), reverse=True)
    main_file = cands[0] if cands else os.path.join(
        target_folder,
        re.sub(r"[^a-z0-9]+", "-", task_instruction.lower())[:30].strip("-") + ".html")
    ext = os.path.splitext(main_file)[1].lower()
    fmt_hint = ("Dokumen HTML5 utuh mulai <!DOCTYPE html>." if ext.startswith(".h")
                else "Kode sumber lengkap tanpa penjelasan.")
    prompt = (
        f"Tugas: {task_instruction[:400]}\n\n"
        f"Kembalikan HANYA isi penuh TERBARU untuk file `{main_file}` "
        f"setelah tugas diterapkan. {fmt_hint} "
        f"Tanpa penjelasan, tanpa fence markdown."
    )
    content = await generate_agent_response(
        agent, prompt,
        "Kamu code generator. Output = isi file mentah saja.",
        max_tokens=8000, timeout_s=300.0)
    if not content or len(content.strip()) < 20:
        return "(single-shot) konten kosong dari model"
    content = content.strip()
    if content.startswith("```"):
        content = re.sub(r"^```[a-zA-Z]*\n?", "", content)
        content = re.sub("\n?```$", "", content)
    try:
        res = tools.write_local_file(file_path=main_file, content=content)
        st = (res or {}).get("status", "?") if isinstance(res, dict) else "?"
        log_live("FILE", f"📝 single-shot write {os.path.basename(main_file)} -> {st}")
        return f"(single-shot) {main_file} diperbarui ({len(content)} char)"
    except Exception as w_err:
        return f"(single-shot) gagal tulis: {w_err}"


async def _forced_json_execution(agent: Dict[str, Any], task_instruction: str) -> str:
    """Eksekusi deterministik: model hanya menyusun rencana JSON aksi tool,
    engine-lah yang menjalankannya. Menutup kelemahan model yang menolak
    memanggil function call sendiri."""
    plan_sys = (
        "Kamu execution planner. Output HANYA array JSON murni (tanpa teks lain) "
        'berisi aksi tool berurutan untuk menyelesaikan tugas. Skema aksi:\n'
        '[{"tool":"write_local_file","path":"/abs/file","content":"isi file"},\n'
        ' {"tool":"edit_file_precise","path":"/abs/file","old_text":"...","new_text":"..."},\n'
        ' {"tool":"execute_bash_command","command":"...","working_dir":"/abs/folder"}]\n'
        "Gunakan path ABSOLUT folder kerja. Konten file ditulis penuh di JSON."
    )
    raw = await generate_agent_response(
        agent, "TUGAS:\n" + task_instruction[:1500], plan_sys,
        max_tokens=4000, timeout_s=240.0)
    if not raw:
        return "(forced-exec) planner tidak merespons"

    m = re.search(r"\[.*\]", raw, re.DOTALL)
    if not m:
        return f"(forced-exec) rencana tidak valid: {raw[:120]}"

    import json as _json
    try:
        actions = _json.loads(m.group(0))
    except Exception as je:
        return f"(forced-exec) JSON rusak: {je}"

    allowed = {
        "write_local_file": tools.write_local_file,
        "edit_file_precise": tools.edit_file_precise,
        "execute_bash_command": tools.execute_bash_command,
    }
    logs = []
    for i, act in enumerate(actions[:8]):
        if not isinstance(act, dict):
            continue
        tool_nm = act.get("tool", "")
        fn = allowed.get(tool_nm)
        if not fn:
            continue
        # Normalisasi nama argumen skema-planner -> signature fungsi asli
        kwargs = {k: v for k, v in act.items() if k != "tool"}
        if tool_nm in ("write_local_file", "edit_file_precise") and "path" in kwargs:
            kwargs["file_path"] = kwargs.pop("path")
        if tool_nm == "edit_file_precise":
            kwargs.setdefault("replace_all", False)
        try:
            res = fn(**kwargs)
            st = (res or {}).get("status", "?") if isinstance(res, dict) else "?"
            hint = str(act.get("command") or act.get("path") or "")[:80]
            logs.append(f"{i+1}. {tool_nm} -> {st}")
            log_live("TOOL", f"⚙️ forced-exec {tool_nm} -> {st} | {hint}")
        except Exception as ex:
            logs.append(f"{i+1}. {tool_nm} -> EXC {str(ex)[:80]}")
            log_live("TOOL", f"⚠️ forced-exec {tool_nm} error: {str(ex)[:80]}")
    return "Hasil eksekusi deterministik (forced-JSON):\n" + "\n".join(logs)


async def execute_swarm_task_step(agent: Dict[str, Any], task_instruction: str, topic: str, intent_info: Dict[str, Any]) -> Dict[str, Any]:
    """
    Executes a real action for an agent in Swarm Live Execution mode.
    Calls appropriate system tools, writes files, scrapes data, or tests code.
    """
    t0 = time.time()
    agent_name = agent.get("name", "Agent")
    role = agent.get("role", "Specialist")
    agent_id = agent.get("id", 1)
    
    # Snapshot hash utk bukti perubahan file tingkat-langkah
    pre_hash = _hash_sandbox_projects()
    step_fs_changed = None
    changed_files = []
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

    # 2. EKSEKUSI AGENTIK UMUM — semua agen memakai tool sesuai subtasknya.
    #    (Routing kaku per-peran dihapus; hasil dekomposisi kini dihormati.)
    else:
        tool_name = "agentic_autonomous"
        work_agent = {**agent, "enable_tools": 1}
        folder_rule = ""
        if _TARGET_FOLDER and os.path.isdir(_TARGET_FOLDER):
            folder_rule = (
                f"\nFOLDER KERJA WAJIB: {_TARGET_FOLDER}\n"
                f"PADA execute_bash_command: WAJIB working_dir='{_TARGET_FOLDER}' "
                f"dan gunakan PATH RELATIF (mis. 'cat index.html') — JANGAN path absolut, "
                f"karena folder dimount sebagai /workspace di dalam sandbox.\n"
                f"PREFERSIKAN edit_file_precise / write_local_file untuk ubah file "
                f"(tool ini langsung menyentuh disk host dengan path lengkap)."
            )
        exec_prompt = (
            f"=== TUGAS EKSEKUSI NYATA (SWARM) ===\n{task_instruction}\n"
            f"{folder_rule}\n"
            f"=== ATURAN EKSEKUSI (WAJIB) ===\n"
            f"1. KAMU WAJIB MEMANGGIL TOOL — jawaban teks tanpa panggilan tool = TUGAS GAGAL.\n"
            f"2. Langkah pertama: baca file terkait dengan `read_local_file`.\n"
            f"3. Lakukan perubahan dengan `edit_file_precise` / `write_local_file` "
            f"/ `execute_bash_command`.\n"
            f"4. Setiap hasil WAJIB berupa file nyata di folder kerja.\n"
            f"5. Akhiri dengan daftar path file yang kamu buat/ubah.\n"
            f"DILARANG memberi rencana/koordinasi/instruksi ke orang lain — "
            f"kamu sendiri yang mengeksekusi lewat tool."
        )
        generated_content = await generate_agent_response(
            work_agent, exec_prompt,
            "Kamu agen pelaksana swarm. KERJA MENGGUNAKAN TOOL: setiap giliranmu WAJIB "
            "memuat panggilan function call (read_local_file / edit_file_precise / "
            "write_local_file / execute_bash_command / web_search). Membalas teks saja "
            "tanpa memanggil tool dianggap GAGAL.",
            max_tokens=3000,
            timeout_s=300.0,
        )

        # Gagal total semua provider: tandai step ERROR agar tidak dianggap
        # sukses, tidak di-retry paksa, dan tidak ditulis ke deliverable.
        if generated_content is None or str(generated_content).startswith("[Error:"):
            status = "error"
            tool_output = "SEMUA provider gagal (kuota/kunci/jaringan) — langkah dibatalkan"
            generated_content = "(gagal: tidak ada respons dari provider mana pun)"

        # Bukti filesystem tingkat-langkah (anti klaim kosong)
        post_hash = _hash_sandbox_projects()
        changed_files = [p for p in set(pre_hash) | set(post_hash)
                         if pre_hash.get(p) != post_hash.get(p)]
        step_fs_changed = len(changed_files)
        if step_fs_changed == 0 and status == "success":
            log_live("EXEC", "🔄 Tidak ada file berubah -> beralih ke forced-JSON execution...")
            generated_content = await _forced_json_execution(
                work_agent, task_instruction)
            post_hash = _hash_sandbox_projects()
            changed_files = [p for p in set(pre_hash) | set(post_hash)
                             if pre_hash.get(p) != post_hash.get(p)]
            step_fs_changed = len(changed_files)
        if step_fs_changed == 0 and status == "success":
            if _TARGET_FOLDER and os.path.isdir(_TARGET_FOLDER):
                log_live("EXEC", "🛟 Single-shot edit fallback dijalankan...")
                generated_content = await _single_shot_edit_fallback(
                    work_agent, task_instruction, _TARGET_FOLDER)
                post_hash = _hash_sandbox_projects()
                changed_files = [p for p in set(pre_hash) | set(post_hash)
                                 if pre_hash.get(p) != post_hash.get(p)]
                step_fs_changed = len(changed_files)
            else:
                generated_content = await _forced_json_execution(
                    work_agent, task_instruction)
        if changed_files:
            sample = "; ".join(os.path.basename(p) for p in changed_files[:3])
            tool_output = (f"{len(generated_content or '')} char respons; "
                           f"{step_fs_changed} file berubah: {sample}")
        else:
            tool_output = f"{len(generated_content or '')} char respons; TIDAK ada file berubah"

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
        "fs_changed": step_fs_changed,
        "changed_sample": [os.path.basename(p) for p in changed_files[:5]],
        "timestamp": datetime.now().strftime("%H:%M:%S")
    }


async def conduct_multi_agent_meeting(
    topic: str, 
    participant_names: Optional[List[str]] = None, 
    rounds: int = 2,
    mode: str = "execute",
    target_folder: str = "",
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    SWARM EKSEKUSI LANGSUNG — tanpa mode rapat/diskusi lagi.

    Agen langsung dibagi tugas, mengeksekusi tool nyata, lalu diverifikasi
    ground-truth filesystem. Jika `target_folder` diisi (path lokal yang
    valid), SEMUA agen wajib mengedit di dalam folder tersebut.
    Riwayat/keputusan TIDAK lagi disimpan ke database (arsip dihapus).
    """
    mode = "execute"
    session_id = session_id or f"swarm_{int(time.time())}_{uuid.uuid4().hex[:6]}"

    # ── Folder target kerja agen (opsional tapi divalidasi keras) ──
    global _TARGET_FOLDER
    _TARGET_FOLDER = ""
    if target_folder and str(target_folder).strip():
        tf = os.path.realpath(os.path.expanduser(str(target_folder).strip()))
        if os.path.isdir(tf):
            _TARGET_FOLDER = tf
            log_live("TARGET", f"📁 Folder kerja agen: {_TARGET_FOLDER}")
        else:
            log_live("TARGET", f"⚠️ Folder '{target_folder}' tidak ada — agen bebas memilih lokasi.")

    # ── AUTO-CREATE: prompt bertema membangun tapi tanpa folder pilihan ──
    # Engine membuatkan folder baru bernama rapi dari topik, supaya hasil
    # rapat terorganisir (tidak berserakan) dan mudah dipilih lagi nanti.
    if not _TARGET_FOLDER:
        build_kw = ("buat", "bangun", "rancang", "bikin", "website", "web ",
                    "aplikasi", "landing", "dashboard", "desain", "design",
                    "script", "skrip", "program", "refactor", "perbaiki tampilan")
        if any(k in topic.lower() for k in build_kw):
            slug = re.sub(r"[^a-z0-9]+", "-", topic.lower())[:42].strip("-") or "proyek-baru"
            nf = os.path.join(tools.SANDBOX_DIR, f"{slug}_{int(time.time()) % 100000}")
            try:
                os.makedirs(nf, exist_ok=True)
                _TARGET_FOLDER = nf
                log_live("TARGET", f"📁 Folder proyek baru dibuat otomatis: {nf}")
            except OSError as mk_err:
                log_live("TARGET", f"⚠️ Gagal buat folder otomatis: {mk_err}")

    intent_info = detect_task_intent(topic)

    all_agents = database.list_custom_agents_sync()
    if not all_agents:
        database.init_db_sync()
        all_agents = database.list_custom_agents_sync()

    if participant_names:
        participants = [a for a in all_agents if a["name"] in participant_names and a.get("is_enabled", 1)]
    else:
        participants = [a for a in all_agents if a.get("is_enabled", 1)][:MAX_SWARM_AGENTS]

    if not participants:
        participants = all_agents[:3]

    if _CHECKPOINT_AVAILABLE:
        try:
            _SwarmCheckpoint.save(
                session_id=session_id,
                topic=topic,
                mode=mode,
                participants=participants,
                steps=[],
                steps_done=0,
                status="running"
            )
        except Exception:
            pass

    dialogue_transcript = []
    history_summary = []
    execution_steps = []

    meeting_type_label = "⚡ SWARM EKSEKUSI LANGSUNG" if mode in ["execute", "plan_and_execute"] else "📋 RAPAT STRATEGIS & PLAN"
    meeting_title = f"{meeting_type_label}: {topic[:60]}"

    logger.info(f"🏛️ Starting AI Session [{mode.upper()}] on topic: '{topic}' with {len(participants)} agents (session: {session_id}).")
    global MEETING_RUNNING
    MEETING_RUNNING = True
    _clear_cancel_flag()  # sesi baru = reset sinyal cancel lama
    log_live("SESSION", f"Sesi {mode.upper()} dimulai — topik: {topic[:80]} ({len(participants)} agen)")
    # Snapshot folder sandbox utk auto-harvester di akhir rapat
    _SANDBOX_SNAPSHOT.clear()
    _SANDBOX_SNAPSHOT.update(_sandbox_project_dirs())
    # Ground-truth filesystem utk verifikasi anti-bohong (execute mode)
    if mode == "execute":
        _EXEC_FS_SNAPSHOT.clear()
        _EXEC_FS_SNAPSHOT.update(_hash_sandbox_projects())
        # Publikasikan folder target ke tool sandbox agar dimount dengan
        # path identik di dalam kontainer (path absolut agen jadi valid).
        import os as _os
        if _TARGET_FOLDER:
            _os.environ["ALFA_TARGET_FOLDER"] = _TARGET_FOLDER
        else:
            _os.environ.pop("ALFA_TARGET_FOLDER", None)

    # --- MODE EKSEKUSI LANGSUNG MURNI: tanpa putaran dialog/diskusi ---
    actual_rounds = 0

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
            ) or "(tidak merespons — semua provider gagal)"

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
    swarm_cancelled = False
    if mode in ["execute", "plan_and_execute"]:
        logger.info(f"⚡ Launching Live Autonomous Swarm Execution for {len(participants)} agents...")

        # Dynamic task decomposition: lead breaks the topic into one concrete
        # subtask per agent instead of generic role assignments.
        subtask_map = await _decompose_task(topic, participants)
        if subtask_map:
            logger.info("Task decomposition OK: %s", list(subtask_map.keys()))
            for _n, _t in subtask_map.items():
                log_live("PLAN", f"🗂️ {_n}: {_t[:90]}")

        failed_steps: List[Dict[str, Any]] = []
        ctx_lines: List[str] = []

        # ── PARALLEL FAN-OUT / FAN-IN ──────────────────────────────
        # Agen dieksekusi per gelombang (wave) secara bersamaan, hasilnya
        # di-merge ke konteks agen gelombang berikutnya (Map-Reduce ringan).
        # ALFA_SWARM_PARALLEL=off  -> mode sekuensial klasik.
        # ALFA_SWARM_MAX_CONCURRENT -> batas beban paralel (default 3).
        _parallel = os.getenv("ALFA_SWARM_PARALLEL", "on").strip().lower() != "off"
        try:
            _wave_size = max(1, int(os.getenv("ALFA_SWARM_MAX_CONCURRENT", "3")))
        except ValueError:
            _wave_size = 3
        if not _parallel:
            _wave_size = 1

        def _build_task_desc(agent: Dict[str, Any], err_ctx: str) -> str:
            td = subtask_map.get(agent["name"]) or \
                f"Eksekusi modul {agent['role']} untuk '{topic[:60]}'"
            if err_ctx:
                td += f"\n\n{err_ctx}"
            if _TARGET_FOLDER:
                td += (
                    f"\n\nFOLDER KERJA WAJIB: {_TARGET_FOLDER}\n"
                    f"SEMUA file yang dibaca/ditulis WAJIB di dalam folder ini. "
                    f"Pada execute_bash_command: sertakan working_dir='{_TARGET_FOLDER}' "
                    f"dan gunakan PATH RELATIF (folder ter-mount sebagai /workspace). "
                    f"Untuk mengubah isi file, PAKAI edit_file_precise/write_local_file "
                    f"dengan path lengkap '{_TARGET_FOLDER}/<nama>'. "
                    f"DILARANG membuat proyek di lokasi lain."
                )
            if ctx_lines:
                td += (
                    "\n\nKONTEKS HASIL AGEN GELOMBANG SEBELUMNYA (gunakan bila relevan):\n- "
                    + "\n- ".join(ctx_lines[-3:])
                )
            return td

        async def _execute_agent_step(agent: Dict[str, Any], task_desc: str):
            log_live("EXEC", f"⚙️ {agent['name']} mulai eksekusi: {task_desc[:90]}")
            step_result = await execute_swarm_task_step(agent, task_desc, topic, intent_info)
            if step_result.get("deliverable_file"):
                log_live("FILE", f"📁 {agent['name']} menghasilkan berkas: {os.path.basename(step_result['deliverable_file'])}")

            passed, feedback = await _verify_step_result(task_desc, step_result)
            attempts = 0
            while (
                not passed
                and attempts < 1
                and step_result.get("tool_used") != "strategic_orchestration"
                and not _cancel_requested()
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
            return step_result, passed, feedback

        for wave_start in range(0, len(participants), _wave_size):
            wave = participants[wave_start:wave_start + _wave_size]
            if _cancel_requested():
                log_live("CANCEL", f"⏹ Eksekusi dihentikan pengguna sebelum gelombang {wave_start // _wave_size + 1}.")
                swarm_cancelled = True
                if _CHECKPOINT_AVAILABLE:
                    try:
                        _SwarmCheckpoint.mark_cancelled(session_id)
                    except Exception:
                        pass
                break

            # Error propagation: kegagalan gelombang sebelumnya disuntikkan
            # ke seluruh agen gelombang ini (dalam-wave tidak bisa, by design).
            err_ctx_snapshot = _build_error_context(failed_steps)

            try:
                wave_results = await asyncio.gather(
                    *[_execute_agent_step(a, _build_task_desc(a, err_ctx_snapshot)) for a in wave],
                    return_exceptions=True,
                )
            except Exception as wave_err:  # safety net; gather rarely raises dgn return_exceptions
                logger.error(f"Wave execution error: {wave_err}")
                wave_results = [wave_err] * len(wave)

            for agent, res in zip(wave, wave_results):
                if isinstance(res, Exception):
                    step_result = {
                        "agent_name": agent["name"],
                        "tool_used": None,
                        "execution_summary": f"[EXCEPTION] {res}",
                        "deliverable_file": None,
                    }
                    passed, feedback = False, str(res)
                else:
                    step_result, passed, feedback = res

                if not passed and step_result.get("tool_used") != "strategic_orchestration":
                    failed_steps.append({
                        "agent_name": agent["name"],
                        "tool_used": step_result.get("tool_used"),
                        "feedback": feedback,
                        "execution_summary": step_result.get("execution_summary", ""),
                    })
                    _record_step_error(session_id, step_result, feedback)

                step_result["verification"] = "PASS" if passed else ("FAIL" if step_result.get("tool_used") != "strategic_orchestration" else "N/A")
                log_live("VERIFY", f"{'✅ PASS' if passed else '❌ FAIL'} — {agent['name']} ({step_result.get('tool_used')}){(': ' + feedback[:80]) if not passed and feedback else ''}")
                execution_steps.append(step_result)

                # Simpan progress checkpoint setelah setiap langkah selesai
                if _CHECKPOINT_AVAILABLE:
                    try:
                        _SwarmCheckpoint.save(
                            session_id=session_id,
                            topic=topic,
                            mode=mode,
                            participants=participants,
                            steps=execution_steps,
                            steps_done=len(execution_steps),
                            status="cancelled" if swarm_cancelled else "running"
                        )
                    except Exception:
                        pass

                brief = (step_result.get("execution_summary") or "")[:180].replace("\n", " ")
                ctx_lines.append(f"{step_result['agent_name']} -> {brief}")

    # --- PHASE 2.5: SENTINEL QA — LOOP ZERO BUG ---
    # Setelah semua agen selesai, Sentinel QA menguji hasil kerja secara
    # independen (menjalankan kode/file sendiri). Bila ditemukan bug, tugas
    # perbaikan dikembalikan ke agen pelaku, lalu diuji ulang — sampai
    # QA_VERDICT: PASS atau batas putaran habis.
    if mode == "execute" and not swarm_cancelled and not _cancel_requested() \
            and execution_steps and MAX_QA_ROUNDS > 0:
        qa_agent = next(
            (a for a in all_agents
             if a.get("name") == "Sentinel QA" and a.get("is_enabled", 1)),
            None)
        if not qa_agent:
            # Fallback: pakai agen baku yang memang berperan QA/audit
            # (instalasi default tidak punya agen bernama "Sentinel QA").
            _qa_kw = ("qa", "audit", "sentinel", "quality", "tester", "uji")
            qa_agent = next(
                (a for a in all_agents
                 if a.get("is_enabled", 1) and (
                     any(k in a.get("name", "").lower() for k in _qa_kw)
                     or any(k in a.get("role", "").lower() for k in _qa_kw))),
                None)
        if qa_agent:
            fix_feedback = ""
            zero_bug = False
            for qa_round in range(1, MAX_QA_ROUNDS + 1):
                if _cancel_requested():
                    break
                # Snapshot hasil kerja TERKINI tiap putaran: setelah putaran
                # perbaikan, file baru dari fixer ikut diuji ulang.
                deliverables = [s["deliverable_file"] for s in execution_steps if s.get("deliverable_file")]
                work_summary = "\n".join(
                    f"- {s['agent_name']} ({s.get('tool_used','?')}): {(s.get('execution_summary') or '')[:220]}"
                    for s in execution_steps)
                log_live("QA", f"🛡️ Sentinel QA putaran {qa_round}/{MAX_QA_ROUNDS}: menguji hasil kerja tim...")
                qa_task = (
                    f"=== MISI TIM YANG HARUS KAMU UJI ===\n{topic[:120]}\n\n"
                    f"=== HASIL KERJA AGEN (JANGAN DIPERCAYA — BUKTIKAN SENDIRI) ===\n{work_summary}\n"
                    + (f"=== FILE DELIVERABLE ===\n{chr(10).join(deliverables)}\n" if deliverables else "")
                    + (f"\nFOLDER KERJA: {_TARGET_FOLDER} — jalankan file/kode dari sini.\n" if _TARGET_FOLDER else "")
                    + (f"\n=== BUG PUTARAN SEBELUMNYA (diklaim sudah diperbaiki — VERIFIKASI ULANG) ===\n{fix_feedback}\n" if fix_feedback else "")
                    + "\n=== ATURAN QA ===\n"
                    "1. JALANKAN sendiri kode/file hasil tim via tool (execute_bash_command / read_local_file / sandbox).\n"
                    "2. Catat tiap bug dengan bukti: command + output error.\n"
                    "3. Akhiri respons dengan TEPAT satu baris:\n"
                    "   QA_VERDICT: PASS   (terbukti nol bug)\n"
                    "   QA_VERDICT: FAIL - <daftar bug bernomor + file penyebab>"
                )
                qa_step = await execute_swarm_task_step(qa_agent, qa_task, topic, intent_info)
                qa_step["phase"] = f"qa_round_{qa_round}"
                execution_steps.append(qa_step)
                # Verdict ada di teks jawaban model (generated_content), bukan
                # execution_summary (hanya ringkasan jumlah karakter/file).
                qa_text = str(qa_step.get("generated_content")
                              or qa_step.get("execution_summary") or "")
                if qa_verdict_passed(qa_text):
                    zero_bug = True
                    log_live("QA", f"✅ ZERO BUG terverifikasi pada putaran {qa_round}.")
                    break

                fix_feedback = qa_text[-1500:]
                log_live("QA", f"🐞 Bug terdeteksi (putaran {qa_round}) — dikembalikan ke tim pelaksana.")
                fixers = [a for a in participants if a.get("name") != qa_agent.get("name")] or participants
                for fa in fixers:
                    if _cancel_requested():
                        break
                    fix_task = (
                        f"QA MENEMUKAN BUG PADA HASIL KERJA TIM — PERBAIKI BAGIANMU SEKARANG SAMPAI BENAR.\n\n"
                        f"MISI ASLI: {topic[:120]}\n"
                        f"LAPORAN QA (bukti + daftar bug):\n{fix_feedback}\n\n"
                        f"ATURAN PERBAIKAN:\n"
                        f"1. Perbaiki HANYA file/kode yang kamu buat"
                        + (f" (folder {_TARGET_FOLDER})." if _TARGET_FOLDER else ".") + "\n"
                        "2. Jalankan ulang untuk MEMBUKTIKAN fix bekerja.\n"
                        "3. Laporkan apa yang diubah + bukti hasil uji ulang."
                    )
                    fix_step = await execute_swarm_task_step(fa, fix_task, topic, intent_info)
                    fix_step["phase"] = f"qa_fix_round_{qa_round}"
                    execution_steps.append(fix_step)
                    ctx_lines.append(
                        f"[QA-FIX r{qa_round}] {fa['name']} -> {(fix_step.get('execution_summary') or '')[:150]}")
            if not zero_bug:
                log_live("QA", "⚠️ Batas putaran QA habis sebelum zero bug — status dilaporkan apa adanya.")

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

    # --- PEMBATALAN: kembalikan hasil parsial tanpa sintesis konsensus ---
    if swarm_cancelled or _cancel_requested():
        MEETING_RUNNING = False
        _clear_cancel_flag()
        log_live("DONE", f"🏁 Eksekusi swarm DIBATALKAN — {len(execution_steps)} langkah tuntas sebelum berhenti.")
        return {
            "status": "cancelled",
            "meeting_id": None,
            "title": meeting_title,
            "topic": topic,
            "mode": mode,
            "target_folder": _TARGET_FOLDER,
            "participants": [a["name"] for a in participants],
            "dialogue_transcript": dialogue_transcript,
            "execution_results": execution_steps,
            "consensus": (
                f"⏹ **Eksekusi dibatalkan pengguna.** {len(execution_steps)} dari "
                f"{len(participants)} agen tuntas dieksekusi sebelum berhenti. "
                "File/hasil yang sudah dibuat tetap tersimpan."
            ),
            "action_plan": ""
        }

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
    ) or "(laporan gagal: semua provider tidak merespons)"

    action_plan_text = ""
    marker = "ACTION PLAN"
    marker_idx = consensus_text.upper().find(marker)
    if marker_idx != -1:
        # Case-insensitive split: the model may write "Action Plan" etc.
        consensus_text_clean = consensus_text[:marker_idx].strip()
        action_plan_text = marker + consensus_text[marker_idx + len(marker):]
    else:
        consensus_text_clean = consensus_text

    # Riwayat & keputusan rapat TIDAK lagi disimpan ke database
    # (fitur arsip dihapus atas permintaan pemilik).
    MEETING_RUNNING = False
    # Auto-harvester: arsipkan proyek baru yang dibangun agen ke outputs
    _harvest_new_sandbox_projects(topic)

    # Tandai checkpoint selesai
    if _CHECKPOINT_AVAILABLE:
        try:
            _deliverables = [s["deliverable_file"] for s in execution_steps if s.get("deliverable_file")]
            _SwarmCheckpoint.mark_completed(session_id, deliverables=_deliverables)
        except Exception:
            pass

    log_live("DONE", "🏁 Eksekusi swarm selesai.")

    return {
        "status": "success",
        "session_id": session_id,
        "meeting_id": None,
        "title": meeting_title,
        "topic": topic,
        "mode": mode,
        "target_folder": _TARGET_FOLDER,
        "participants": [a["name"] for a in participants],
        "dialogue_transcript": dialogue_transcript,
        "execution_results": execution_steps,
        "consensus": consensus_text_clean,
        "action_plan": action_plan_text
    }


async def resume_swarm_session(session_id: str) -> Dict[str, Any]:
    """
    Melanjutkan sesi swarm yang sebelumnya dibatalkan atau tertunda berdasarkan checkpoint.
    """
    if not _CHECKPOINT_AVAILABLE or not _SwarmCheckpoint:
        return {"status": "error", "message": "Checkpoint system tidak tersedia."}

    ckpt = _SwarmCheckpoint.load(session_id)
    if not ckpt:
        return {"status": "error", "message": f"Checkpoint untuk session '{session_id}' tidak ditemukan."}

    topic = ckpt.get("topic", "")
    mode = ckpt.get("mode", "execute")
    participant_names = [a["name"] for a in ckpt.get("participants", []) if isinstance(a, dict) and "name" in a]

    log_live("RESUME", f"🔄 Melanjutkan sesi {session_id} (Topik: {topic[:60]})...")

    return await conduct_multi_agent_meeting(
        topic=topic,
        participant_names=participant_names or None,
        mode=mode,
        session_id=session_id,
    )

