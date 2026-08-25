"""
ALFA SOVEREIGN COMMAND CENTER - Web Dashboard (PRO-MAX Edition)
High-performance FastAPI web dashboard with luxury dark glassmorphic UI,
live telemetry timeline, 72+ tools explorer, service orchestrator,
artifact gallery, and second brain visualizer.
"""

import asyncio
import base64
import inspect
import json
import logging
import os
import secrets
import shutil
import subprocess
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import psutil
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware

load_dotenv()

logger = logging.getLogger("Dashboard")

# Import project modules
import bot
import database
import tools

app = FastAPI(title="ALFA Sovereign Command Center Pro-Max", version="2.5.0")

# Optional authentication: set DASHBOARD_AUTH_TOKEN in .env to require a password.
# Browsers will show a native login prompt; API clients may use
# "Authorization: Bearer <token>" as well.
DASHBOARD_AUTH_TOKEN = os.getenv("DASHBOARD_AUTH_TOKEN", "").strip()


class DashboardAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method == "OPTIONS":
            return await call_next(request)
        if DASHBOARD_AUTH_TOKEN:
            authorized = False
            auth_header = request.headers.get("Authorization", "")
            if auth_header == f"Bearer {DASHBOARD_AUTH_TOKEN}":
                authorized = True
            elif auth_header.startswith("Basic "):
                try:
                    decoded = base64.b64decode(auth_header[6:]).decode("utf-8")
                    _, _, pwd = decoded.partition(":")
                    authorized = secrets.compare_digest(pwd, DASHBOARD_AUTH_TOKEN)
                except Exception:
                    authorized = False
            if not authorized:
                return Response(
                    content='{"detail":"Unauthorized: password required"}',
                    status_code=401,
                    media_type="application/json",
                    headers={"WWW-Authenticate": 'Basic realm="ALFA Dashboard"'},
                )
        return await call_next(request)


app.add_middleware(DashboardAuthMiddleware)

if not DASHBOARD_AUTH_TOKEN:
    logging.getLogger("Dashboard").warning(
        "DASHBOARD_AUTH_TOKEN tidak diset di .env - dashboard TANPA autentikasi. "
        "Semua endpoint /api/* dapat diakses siapa pun yang bisa mencapai port ini."
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")


def get_primary_user_id() -> int:
    """Safely get primary telegram user id from ALLOWED_USER_IDS env var."""
    allowed_env = os.getenv("ALLOWED_USER_IDS", "").strip()
    if allowed_env:
        try:
            return int(allowed_env.split(",")[0].strip())
        except (ValueError, IndexError):
            pass
    return 0


def safe_int(value, default: int, minimum: int = None, maximum: int = None) -> int:
    """Convert payload value to int with fallback and optional bounds."""
    try:
        result = int(value)
    except (TypeError, ValueError):
        return default
    if minimum is not None:
        result = max(minimum, result)
    if maximum is not None:
        result = min(maximum, result)
    return result



def categorize_tool(name: str) -> str:
    """Categorize tool by its functional domain."""
    name_lower = name.lower()
    if "affiliate" in name_lower or "scrape" in name_lower or "marketplace" in name_lower:
        return "Affiliate Sales & Product Scraper (Camoufox)"
    elif name_lower.startswith("pdf_") or "pdf" in name_lower:
        return "PDF Tools Suite (Offline & Online)"
    elif name_lower.startswith("browser_"):
        return "Browser Automation"
    elif name_lower.startswith("desktop_") or name_lower.startswith("vision_") or "screenshot" in name_lower or "webcam" in name_lower:
        return "OS & Vision Control"
    elif name_lower.startswith("libreoffice_"):
        return "LibreOffice Suite"
    elif "excel" in name_lower or "presentation" in name_lower or "media" in name_lower or "audio" in name_lower or "image" in name_lower:
        return "Media & Documents"
    elif "security" in name_lower or "network" in name_lower or "ssh" in name_lower or "password" in name_lower:
        return "Security & Network"
    elif "knowledge" in name_lower or "memory" in name_lower or "brain" in name_lower:
        return "Memory & Second Brain"
    elif "guardian" in name_lower or "heal" in name_lower or "service" in name_lower or "cron" in name_lower or "clean" in name_lower or "storage" in name_lower:
        return "System & Healing"
    elif "subagent" in name_lower or "research" in name_lower or "search" in name_lower or "translate" in name_lower or "dataset" in name_lower:
        return "AI & Intelligence"
    elif "wa_" in name_lower or "sheets" in name_lower:
        return "Ecosystem & Bots"
    else:
        return "Core Utilities"


# --- API Routes ---

@app.get("/", response_class=HTMLResponse)
async def serve_index():
    """Serve the single-page luxury glassmorphic dashboard."""
    index_path = os.path.join(TEMPLATES_DIR, "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            return HTMLResponse(
                content=f.read(),
                headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
            )
    return HTMLResponse("<h2>Dashboard template not found. Please create templates/index.html</h2>")


@app.get("/api/stats")
async def get_stats():
    """Live Linux system telemetry."""
    try:
        raw_stats = tools.get_system_stats()
        cpu_pct = psutil.cpu_percent(interval=None)
        cpu_count = psutil.cpu_count(logical=True)
        ram = psutil.virtual_memory()
        swap = psutil.swap_memory()
        disk = psutil.disk_usage(os.path.abspath(os.sep))
        battery = psutil.sensors_battery()
        
        uptime_secs = int(time.time() - psutil.boot_time())
        hours, remainder = divmod(uptime_secs, 3600)
        minutes, seconds = divmod(remainder, 60)
        
        # Check active background services (cross-platform: systemctl on Linux, psutil elsewhere)
        if os.name == "nt":
            def _svc_active(script_hint):
                for p in psutil.process_iter(['cmdline']):
                    try:
                        cl = p.info.get('cmdline') or []
                        if any(script_hint in str(c) for c in cl):
                            return True
                    except Exception:
                        continue
                return False
            tb_active = _svc_active("bot.py")
            wa_active = _svc_active("wa_sheets")
            dash_active = _svc_active("web_dashboard.py")
        else:
            tb_res = subprocess.run(["systemctl", "--user", "is-active", "telegram-ai-bot.service"], capture_output=True, text=True)
            wa_res = subprocess.run(["systemctl", "--user", "is-active", "wa-sheets-bot.service"], capture_output=True, text=True)
            dash_res = subprocess.run(["systemctl", "--user", "is-active", "alfa-dashboard.service"], capture_output=True, text=True)
            tb_active = tb_res.stdout.strip() == "active"
            wa_active = wa_res.stdout.strip() == "active"
            dash_active = dash_res.stdout.strip() == "active"

        return {
            "status": "success",
            "timestamp": datetime.now().isoformat(),
            "uptime": f"{hours}j {minutes}m {seconds}d",
            "uptime_seconds": uptime_secs,
            "cpu": {
                "percent": cpu_pct,
                "cores": cpu_count,
                "freq_mhz": round(psutil.cpu_freq().current if psutil.cpu_freq() else 0, 1)
            },
            "ram": {
                "percent": ram.percent,
                "used_gb": round(ram.used / (1024**3), 2),
                "total_gb": round(ram.total / (1024**3), 2),
                "free_gb": round(ram.available / (1024**3), 2)
            },
            "swap": {
                "percent": swap.percent,
                "used_mb": round(swap.used / (1024**2), 1),
                "total_mb": round(swap.total / (1024**2), 1)
            },
            "disk": {
                "percent": disk.percent,
                "used_gb": round(disk.used / (1024**3), 1),
                "total_gb": round(disk.total / (1024**3), 1),
                "free_gb": round(disk.free / (1024**3), 1)
            },
            "battery": {
                "percent": battery.percent if battery else 100,
                "plugged": battery.power_plugged if battery else True,
                "status": "Charging ⚡" if (battery and battery.power_plugged) else "Discharging 🔋"
            },
            "services": {
                "telegram_bot": tb_active,
                "wa_sheets_bot": wa_active,
                "dashboard": dash_active
            },
            "top_ram_processes": raw_stats.get("top_ram_processes", [])[:8]
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/api/tools")
async def get_tools_list():
    """Get list of all registered tools with descriptions, args, and categories."""
    tools_list = []
    for t in tools.AVAILABLE_TOOLS:
        name = t.__name__
        sig = inspect.signature(t)
        doc = (t.__doc__ or "No documentation provided.").strip()
        doc_lines = doc.split("\n")
        short_desc = doc_lines[0].strip() if doc_lines else "No description."
        
        params = []
        for p_name, param in sig.parameters.items():
            params.append({
                "name": p_name,
                "default": str(param.default) if param.default != inspect.Parameter.empty else None,
                "required": param.default == inspect.Parameter.empty,
                "type": str(param.annotation) if param.annotation != inspect.Parameter.empty else "Any"
            })
            
        tools_list.append({
            "name": name,
            "short_description": short_desc,
            "full_docstring": doc,
            "category": categorize_tool(name),
            "signature": f"{name}{str(sig)}",
            "parameters": params
        })
        
    return {
        "status": "success",
        "total_tools": len(tools_list),
        "tools": sorted(tools_list, key=lambda x: (x["category"], x["name"]))
    }


@app.post("/api/tools/execute")
async def execute_tool(payload: Dict[str, Any]):
    """Execute any tool directly with supplied arguments."""
    tool_name = payload.get("tool_name")
    args = payload.get("args", {})
    
    if not tool_name:
        raise HTTPException(status_code=400, detail="tool_name is required")
        
    target_fn = getattr(tools, tool_name, None)
    if not target_fn or not callable(target_fn):
        import plugins
        target_fn = plugins._RUNTIME_PLUGIN_REGISTRY.get(tool_name)
        
    if not target_fn or not callable(target_fn):
        raise HTTPException(status_code=404, detail=f"Tool '{tool_name}' not found")
        
    try:
        # Set primary user context
        uid = get_primary_user_id()
        tools.current_user_id_var.set(uid)
        tools.current_chat_id_var.set(uid)
        
        start_t = time.time()
        result = target_fn(**args)
        duration_ms = round((time.time() - start_t) * 1000, 1)
        
        return {
            "status": "success",
            "tool": tool_name,
            "duration_ms": duration_ms,
            "result": result
        }
    except Exception as e:
        return {
            "status": "error",
            "tool": tool_name,
            "message": str(e)
        }


@app.post("/api/tools/upload")
async def upload_files_for_tools(files: List[UploadFile] = File(...)):
    """Upload one or more files from user computer for tool processing."""
    upload_dir = tools.get_pdf_output_dir("Uploads")
    saved_files = []
    
    for f in files:
        safe_name = os.path.basename(f.filename or "upload_file")
        target_path = os.path.join(upload_dir, safe_name)
        
        # If already exists, create a unique timestamped name
        if os.path.exists(target_path):
            stem, ext = os.path.splitext(safe_name)
            safe_name = f"{stem}_{int(time.time())}{ext}"
            target_path = os.path.join(upload_dir, safe_name)
            
        content = await f.read()
        with open(target_path, "wb") as out_f:
            out_f.write(content)
            
        saved_files.append({
            "filename": safe_name,
            "original_name": f.filename,
            "file_path": target_path,
            "size_bytes": len(content),
            "size_kb": round(len(content) / 1024, 2)
        })
        
    return {
        "status": "success",
        "message": f"Berhasil mengunggah {len(saved_files)} file ke {upload_dir}",
        "upload_dir": upload_dir,
        "files": saved_files,
        "primary_file_path": saved_files[0]["file_path"] if saved_files else None,
        "all_file_paths": [sf["file_path"] for sf in saved_files]
    }


# --- Affiliate Sales Swarm API Endpoints ---

@app.get("/api/affiliate/campaigns")
async def get_affiliate_campaigns(limit: int = 20):
    """Get list of active affiliate campaigns and scripts."""
    import affiliate_engine
    campaigns = affiliate_engine.list_affiliate_campaigns(limit=limit)
    return {
        "status": "success",
        "total": len(campaigns),
        "campaigns": campaigns
    }


@app.get("/api/affiliate/campaigns/{campaign_id}")
async def get_affiliate_campaign_detail(campaign_id: int):
    """Get full details of a specific affiliate campaign."""
    import affiliate_engine
    data = affiliate_engine.get_affiliate_campaign_detail(campaign_id)
    if not data:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return {"status": "success", "campaign": data}


def _parse_ai_sections(text: str) -> Dict[str, str]:
    """Pecah output AI bertanda ===NAMA_SEKSI=== menjadi dict."""
    import re as _re
    out: Dict[str, str] = {}
    parts = _re.split(r"={3,}\s*([A-Za-z_]+)\s*={3,}", text or "")
    for i in range(1, len(parts) - 1, 2):
        out[parts[i].strip().lower()] = parts[i + 1].strip()
    return out


@app.post("/api/affiliate/generate")
async def generate_affiliate_campaign(payload: Dict[str, Any]):
    """Generate viral affiliate campaign: template engine + personalisasi AI
    oleh agen Content Alchemist (fail-safe: bila AI gagal/timeout, hasil
    template murni tetap dikembalikan)."""
    import affiliate_engine
    product_name = payload.get("product_name", "").strip()
    key_features = payload.get("key_features", "").strip()
    original_price = payload.get("original_price", "Rp 100.000").strip()
    discount_price = payload.get("discount_price", "Rp 49.000").strip()
    affiliate_link = payload.get("affiliate_link", "https://shopee.co.id").strip()
    target_audience = payload.get("target_audience", "Pemburu Diskon & Gadget").strip()
    platform = payload.get("platform", "shopee_tiktok").strip()
    
    if not product_name or not affiliate_link:
        raise HTTPException(status_code=400, detail="product_name and affiliate_link are required")
        
    res = affiliate_engine.generate_affiliate_campaign_content(
        product_name=product_name,
        key_features=key_features,
        original_price=original_price,
        discount_price=discount_price,
        affiliate_link=affiliate_link,
        target_audience=target_audience,
        platform=platform
    )

    # ── ENRICHMENT AI: Content Alchemist mempersonalisasi konten template ──
    res["ai_enriched"] = False
    try:
        import asyncio as _asyncio

        import swarm_engine
        alchemist = next(
            (a for a in database.list_custom_agents_sync()
             if a.get("name") == "Content Alchemist" and a.get("is_enabled", 1)),
            None)
        if alchemist:
            prompt = (
                f"Personalisasi konten jualan affiliate berikut agar UNIK dan berbasis data.\n\n"
                f"DATA PRODUK:\n"
                f"- Nama: {product_name}\n- Fitur: {key_features}\n"
                f"- Harga normal: {original_price} -> Flash sale: {discount_price}\n"
                f"- Target: {target_audience} | Platform: {platform}\n"
                f"- Link WAJIB dipertahankan di CTA: {affiliate_link}\n\n"
                f"DRAF TEMPLATE (bahan mentah — boleh rombak struktur & hook):\n"
                f"[SCRIPT DASAR]\n{res['tiktok_script'][:1500]}\n\n"
                f"ATURAN:\n"
                f"1. Hook 3 detik yang spesifik produk (sebut angka/masalah nyata dari fitur).\n"
                f"2. Script 25-40 detik, gaya anak TikTok Indonesia, ada timestamp.\n"
                f"3. Telegram card & WA broadcast dengan urgensi FOMO yang tidak klise.\n\n"
                f"KELUARAN WAJIB PERSIS FORMAT INI (tanpa teks lain):\n"
                f"===TIKTOK_SCRIPT===\n<script lengkap>\n"
                f"===TELEGRAM_CARD===\n<kartu diskon>\n"
                f"===WA_BROADCAST===\n<pesan broadcast>"
            )
            enriched = await _asyncio.wait_for(
                swarm_engine.generate_agent_response(
                    agent=alchemist, prompt=prompt,
                    system_instruction=alchemist.get("system_instruction")
                    or "Kamu adalah copywriter viral Indonesia.",
                    timeout_s=110.0),
                timeout=120.0)
            sections = _parse_ai_sections(enriched)
            replaced = 0
            for key_src, key_out in (("tiktok_script", "tiktok_script"),
                                     ("telegram_card", "telegram_card"),
                                     ("wa_broadcast", "wa_broadcast")):
                val = sections.get(key_src)
                if val and len(val) > 80:
                    res[f"{key_out}_template"] = res[key_out]
                    res[key_out] = val
                    replaced += 1
            if replaced:
                res["ai_enriched"] = True
    except Exception as aff_ai_err:
        import traceback as _tb
        logging.getLogger("Dashboard").warning(
            f"Enrichment affiliate AI gagal — pakai template: "
            f"{type(aff_ai_err).__name__}: {aff_ai_err}\n{_tb.format_exc()[-600:]}")

    return {"status": "success", "result": res}


@app.post("/api/affiliate/broadcast")
async def broadcast_affiliate_campaign(payload: Dict[str, Any]):
    """Broadcast an affiliate deal to Telegram / WhatsApp."""
    import affiliate_engine
    product_name = payload.get("product_name", "")
    message_text = payload.get("message_text", "")
    affiliate_link = payload.get("affiliate_link", "")
    channels = payload.get("channels", ["telegram", "whatsapp"])
    
    res = affiliate_engine.broadcast_affiliate_deal(
        product_name=product_name,
        message_text=message_text,
        affiliate_link=affiliate_link,
        channels=channels
    )
    return res


@app.post("/api/video/generate")
async def generate_promo_video(payload: Dict[str, Any]):
    """Generate 9:16 vertical promo video from images and script."""
    import asyncio

    import video_generator
    image_paths = payload.get("image_paths", [])
    product_name = payload.get("product_name", "Produk Pilihan").strip()
    voiceover_text = payload.get("voiceover_text", "").strip()
    orig_price = payload.get("orig_price", "Rp 149.000").strip()
    disc_price = payload.get("disc_price", "Rp 49.900").strip()
    voice = payload.get("voice", "id-ID-GadisNeural")
    theme = payload.get("theme", "viral_tiktok")
    motion_style = payload.get("motion_style", "zoom_in")
    call_to_action = payload.get("call_to_action", "KLIK KERANJANG KUNING / BIO SEBELUM HABIS")
    visual_prompt = payload.get("visual_prompt", "")
    engine = payload.get("engine", "local_pro")
    api_key = payload.get("api_key", None)
    output_filename = payload.get("output_filename", None)
    badge_text = payload.get("badge_text", "GRATIS ONGKIR")

    if not voiceover_text:
        voiceover_text = f"Promo spesial {product_name}, harga normal {orig_price} sekarang lagi drop cuma {disc_price}! Jangan sampai kehabisan, langsung klik link sekarang!"

    # Google Veo: auto-pakai kunci Gemini dari vault bila API key kosong
    if engine in ("kling", "luma", "runway", "fal_ai", "replicate"):
        return {"status": "error",
                "message": f"Engine '{engine}' belum terimplementasi. Gunakan 'local_pro' atau 'google_veo*'."}
    if (engine in video_generator.VEO_MODEL_MAP
            or engine in getattr(video_generator, "OMNI_MODEL_MAP", {})) \
            and not (api_key or "").strip():
        try:
            with database.get_sync_db() as conn:
                r = conn.execute(
                    "SELECT api_key FROM api_keys WHERE provider = 'gemini' ORDER BY id LIMIT 1")
                row = r.fetchone()
            if row and row["api_key"]:
                api_key = database.decrypt_key(row["api_key"])
        except Exception:
            pass
        if not (api_key or "").strip():
            return {"status": "error",
                    "message": "Google Veo butuh Gemini API Key. Isi manual atau tambahkan kunci 'gemini' di Vault."}

    def _render():
        return video_generator.generate_video_from_images(
            image_paths=image_paths,
            product_name=product_name,
            voiceover_text=voiceover_text,
            orig_price=orig_price,
            disc_price=disc_price,
            voice=voice,
            theme=theme,
            motion_style=motion_style,
            badge_text=badge_text,
            call_to_action=call_to_action,
            visual_prompt=visual_prompt,
            engine=engine,
            api_key=api_key,
            output_filename=output_filename
        )

    # Render berat di worker thread supaya event loop tidak terblokir
    res = await asyncio.to_thread(_render)
    return res


# ══════════════════════════════════════════════════════════════════════════════
#  ALFA SECURE VAULT & CYBER SENTRY API ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/vault/list")
async def list_vault_secrets(category: str = "all"):
    """List metadata for secrets stored in the AES-256-GCM vault."""
    import vault_engine
    return {
        "status": "success",
        "items": vault_engine.vault.list_secrets(category=category)
    }


@app.post("/api/vault/store")
async def store_vault_secret(payload: Dict[str, Any]):
    """Encrypt and store secret into AES-256-GCM vault."""
    import vault_engine
    name = payload.get("name", "").strip()
    value = payload.get("value", "").strip()
    category = payload.get("category", "api_key").strip()
    notes = payload.get("notes", "").strip()
    
    if not name or not value:
        return {"status": "error", "message": "Nama dan nilai secret wajib diisi."}
        
    res = vault_engine.vault.store_secret(name=name, value=value, category=category, notes=notes)
    return res


@app.post("/api/vault/reveal")
async def reveal_vault_secret(payload: Dict[str, Any]):
    """Decrypt and reveal a secret value for authorized viewing."""
    import vault_engine
    secret_id = payload.get("id") or payload.get("name")
    if not secret_id:
        return {"status": "error", "message": "Secret ID atau nama diperlukan."}
        
    sec = vault_engine.vault.get_secret(str(secret_id))
    if not sec:
        return {"status": "error", "message": "Secret tidak ditemukan di dalam vault."}
        
    return {
        "status": "success",
        "name": sec["name"],
        "category": sec["category"],
        "value": sec["value"]
    }


@app.delete("/api/vault/{secret_id}")
async def delete_vault_secret(secret_id: int):
    """Delete a secret permanently from the vault."""
    import vault_engine
    deleted = vault_engine.vault.delete_secret(int(secret_id))
    if deleted:
        return {"status": "success", "message": f"Secret ID {secret_id} berhasil dihapus dari vault."}
    return {"status": "error", "message": f"Secret ID {secret_id} tidak ditemukan."}


@app.post("/api/security/audit")
async def audit_target_security(payload: Dict[str, Any]):
    """Perform comprehensive defensive cybersecurity audit on a target URL."""
    import security_auditor
    target_url = payload.get("url", "").strip()
    if not target_url:
        return {"status": "error", "message": "URL target wajib dimasukkan."}
        
    res = security_auditor.audit_website_security(target_url)
    return res


@app.get("/api/vault/passkey/status")
async def get_passkey_status():
    """Get status of biometric/passkey lock."""
    with database.get_sync_db() as conn:
        c = conn.cursor()
        c.execute("CREATE TABLE IF NOT EXISTS system_settings (key TEXT PRIMARY KEY, value TEXT)")
        c.execute("SELECT value FROM system_settings WHERE key = 'passkey_lock_enabled'")
        row = c.fetchone()
        enabled = row[0] == "true" if row else False
        return {"enabled": enabled}


@app.post("/api/vault/passkey/toggle")
async def toggle_passkey_lock(payload: Dict[str, Any]):
    """Toggle biometric/passkey lock for the dashboard."""
    enabled = bool(payload.get("enabled", False))
    with database.get_sync_db() as conn:
        c = conn.cursor()
        c.execute("CREATE TABLE IF NOT EXISTS system_settings (key TEXT PRIMARY KEY, value TEXT)")
        c.execute("INSERT OR REPLACE INTO system_settings (key, value) VALUES ('passkey_lock_enabled', ?)", ("true" if enabled else "false",))
        conn.commit()
        return {"status": "success", "enabled": enabled, "message": f"Kunci Passkey Biometrik {'diaktifkan' if enabled else 'dinonaktifkan'}."}


# ==================== SYSTEM SETTINGS ENDPOINTS ====================

@app.get("/api/settings")
async def get_system_settings():
    """Retrieve current system configuration (.env and database settings)."""
    import os

    from dotenv import dotenv_values
    
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    env_vals = dotenv_values(env_path) if os.path.exists(env_path) else {}
    
    bot_token = env_vals.get("TELEGRAM_BOT_TOKEN", "")
    masked_bot_token = (bot_token[:6] + "..." + bot_token[-4:]) if len(bot_token) > 10 else ("***" if bot_token else "")
    
    gemini_key = env_vals.get("GEMINI_API_KEY", "")
    masked_gemini_key = (gemini_key[:6] + "..." + gemini_key[-4:]) if len(gemini_key) > 10 else ("***" if gemini_key else "")
    
    with database.get_sync_db() as conn:
        c = conn.cursor()
        c.execute("SELECT key, value FROM system_settings")
        db_settings = {row[0]: row[1] for row in c.fetchall()}
        
    # The active personality source is ~/.alfa/system_prompt.txt (it overrides
    # .env SYSTEM_INSTRUCTION inside run_agent_turn). Show the user what is
    # actually governing the agent, not the silently-ignored env value.
    alfa_prompt_path = os.path.expanduser("~/.alfa/system_prompt.txt")
    prompt_source = "env"
    active_instruction = env_vals.get("SYSTEM_INSTRUCTION", "")
    if os.path.exists(alfa_prompt_path):
        try:
            with open(alfa_prompt_path, "r", encoding="utf-8") as f:
                active_instruction = f.read().strip()
            prompt_source = "file"
        except Exception:
            pass
        
    # Main brain info + pilihan kunci dari vault utk pengaturan System Settings
    try:
        import main_brain as _mb
        brain = _mb.get_main_brain()
        main_brain_info = {
            "provider": brain["provider"],
            "model": brain["model"],
            "key_id": brain["key_id"],
            "label": brain["label"],
        }
    except Exception:
        main_brain_info = {"provider": "?", "model": "", "key_id": None, "label": ""}

    vault_keys = database.list_api_keys_sync()

    return {
        "status": "success",
        "main_brain": main_brain_info,
        "vault_keys": [
            {
                "id": k["id"], "name": k["name"], "provider": k["provider"],
                "model": k["default_model"], "masked_key": k["masked_key"],
                "is_active": bool(k.get("is_active")),
            } for k in vault_keys
        ],
        "env": {
            "has_bot_token": bool(bot_token and bot_token != "your_telegram_bot_token_here"),
            "masked_bot_token": masked_bot_token,
            "has_gemini_key": bool(gemini_key and gemini_key != "your_gemini_api_key_here"),
            "masked_gemini_key": masked_gemini_key,
            "gemini_model": env_vals.get("GEMINI_MODEL", "gemini-2.5-flash"),
            "allowed_user_ids": env_vals.get("ALLOWED_USER_IDS", ""),
            "system_instruction": active_instruction,
            "system_instruction_source": prompt_source,
            "system_instruction_path": alfa_prompt_path,
        },
        "db_settings": db_settings
    }


# ── Daftar model utk kunci terpilih (dipakai kartu Otak Utama) ──
_models_cache: Dict[int, tuple] = {}


@app.get("/api/models-for-key")
async def models_for_key(key_id: int):
    """Fetch live model list dari provider kunci terpilih (60s cache)."""
    import time as _t

    import httpx
    key_id = safe_int(key_id, 0)
    cached = _models_cache.get(key_id)
    if cached and (_t.time() - cached[0]) < 60:
        return {"status": "success", "provider": cached[1], "models": cached[2]}

    row = None
    with database.get_sync_db() as conn:
        r = conn.execute(
            "SELECT provider, api_key, base_url FROM api_keys WHERE id = ?",
            (key_id,))
        row = r.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Key tidak ditemukan")

    provider = (row["provider"] or "").lower()
    api_key = database.decrypt_key(row["api_key"] or "")
    base_url = (row["base_url"] or "").strip()
    models: List[str] = []
    try:
        if provider == "gemini":
            # Live discovery dari Google ListModels (selaras dgn AI Studio).
            # Hanya model yg mendukung generateContent yg ditampilkan.
            try:
                async with httpx.AsyncClient(timeout=15) as cli:
                    res = await cli.get(
                        "https://generativelanguage.googleapis.com/v1beta/models",
                        params={"key": api_key, "pageSize": 1000})
                if res.status_code == 200:
                    for m in res.json().get("models", []):
                        methods = m.get("supportedGenerationMethods") or []
                        if "generateContent" not in methods:
                            continue
                        mid = (m.get("name") or "").replace("models/", "")
                        if mid:
                            models.append(mid)
            except Exception:
                pass
            if not models:
                # Fallback kurasi bila panggilan live gagal
                models = [
                    "gemini-3.7-flash",
                    "gemini-3.6-flash",
                    "gemini-3.5-flash",
                    "gemini-3.5-flash-lite",
                    "gemini-3.1-pro-preview",
                    "gemini-3.1-flash-lite",
                    "gemini-3-flash-preview",
                    "gemini-flash-latest",
                    "gemini-pro-latest",
                    "gemini-2.5-pro",
                    "gemini-2.5-flash",
                    "gemini-2.5-flash-lite",
                ]
        else:
            base = base_url or {
                "openrouter": "https://openrouter.ai/api/v1",
                "nvidia": "https://integrate.api.nvidia.com/v1",
                "deepseek": "https://api.deepseek.com/v1",
                "openai": "https://api.openai.com/v1",
                "groq": "https://api.groq.com/openai/v1",
            }.get(provider, "")
            if base:
                async with httpx.AsyncClient(timeout=30) as cli:
                    res = await cli.get(f"{base.rstrip('/')}/models",
                                        headers={"Authorization": f"Bearer {api_key}"})
                if res.status_code == 200:
                    for m in res.json().get("data", []):
                        mid = m.get("id")
                        if mid:
                            models.append(mid)
        models = sorted(set(models))
        _models_cache.clear()
        _models_cache[key_id] = (_t.time(), provider, models)
        return {"status": "success", "provider": provider, "models": models}
    except Exception as e:
        return {"status": "error", "message": str(e), "provider": provider,
                "models": []}


@app.post("/api/antigravity/apply")
async def antigravity_apply_model(payload: Dict[str, Any]):
    """Terapkan model Antigravity sebagai KUNCI CADANGAN (+ opsional semua agen).
    TIDAK mengubah otak utama — itu tetap dikendalikan lewat kartu Otak Utama."""
    import database as _db
    model = str(payload.get("model", "")).strip()
    apply_all = bool(payload.get("apply_all_agents", True))
    as_main_brain = bool(payload.get("as_main_brain", False))   # default: cadangan saja

    # 1. Cari kunci vault Antigravity (base_url 8890) — buat bila belum ada
    target_key = None
    for k in _db.list_api_keys_sync():
        if "8890" in (k.get("base_url") or ""):
            target_key = k
            break
    if not target_key:
        r = _db.add_api_key_sync(name="Antigravity Multi-Account", provider="custom",
                                 api_key="antigravity",
                                 default_model=model or "gemini-3.5-flash",
                                 base_url="http://127.0.0.1:8890/v1",
                                 set_active=False)
        key_id = r.get("id")
    else:
        key_id = target_key["id"]
        _db.update_api_key_model(key_id, model or "gemini-3.5-flash")

    updated = []

    # 2. Terapkan ke semua agen swarm aktif
    if apply_all:
        for a in _db.list_custom_agents_sync():
            if a.get("is_enabled", 1):
                _db.update_custom_agent_sync(a["id"], {
                    "provider": "custom",
                    "model": model or "gemini-3.5-flash",
                    "api_key_id": key_id,
                })
                updated.append(a["name"])

    brain_note = ""
    main_brain_info = None

    # 3. Hanya jadi otak utama jika user EXPLISIT memintanya
    if as_main_brain:
        brain_res = await antigravity_set_main_brain_impl(key_id, model or "gemini-3.5-flash")
        main_brain_info = brain_res.get("main_brain")
        brain_note = " Otak utama dialihkan ke Antigravity."
    else:
        brain_note = (" Mode cadangan: otak utama tidak berubah "
                      "(aktifkan via kartu Otak Utama bila diperlukan).")

    return {
        "status": "success",
        "key_id": key_id,
        "model": model,
        "agents_updated": updated,
        "agents_count": len(updated),
        "as_main_brain": as_main_brain,
        "main_brain": main_brain_info,
        "message": (f"Kunci cadangan '{model}' siap ({len(updated)} agen swarm ikut memakai)."
                    f"{brain_note}")
    }


async def antigravity_set_main_brain_impl(key_id: int, model: str):

    import database as _db
    with _db.get_sync_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO system_settings (key, value) VALUES ('main_brain_key_id', ?)",
            (str(key_id),))
        conn.execute(
            "INSERT OR REPLACE INTO system_settings (key, value) VALUES ('main_brain_model', ?)",
            (model,))
        conn.commit()
    import main_brain as _mb
    brain = _mb.get_main_brain()
    return {"main_brain": {"provider": brain["provider"], "model": brain["model"],
                           "key_id": brain["key_id"], "label": brain["label"]}}

@app.post("/api/main-brain/test")
async def test_main_brain_combo(payload: Dict[str, Any]):
    """Tes koneksi kombinasi kunci + model sebelum diterapkan."""
    import httpx as _hx

    try:
        key_id = int(payload.get("key_id", 0))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="key_id wajib angka")
    model = str(payload.get("model", "")).strip()
    row = None
    with database.get_sync_db() as conn:
        r = conn.execute(
            "SELECT provider, api_key, base_url FROM api_keys WHERE id=?",
            (key_id,)).fetchone()
        row = dict(r) if r else None
    if not row:
        return {"status": "error", "message": "Key tidak ditemukan"}
    row["api_key"] = database.decrypt_key(row.get("api_key") or "")

    provider = (row["provider"] or "").lower()
    t0 = time.time()
    try:
        if provider == "gemini":
            from google import genai as _genai
            from google.genai import types as _types
            client = _genai.Client(api_key=row["api_key"])
            resp = await client.aio.models.generate_content(
                model=model or "gemini-3.5-flash-lite",
                contents="Balas satu kata: SIAP",
                config=_types.GenerateContentConfig(max_output_tokens=100))
            text = (resp.text or "").strip()
            ok = bool(text)
            snippet = text[:80]
        else:
            base = (row["base_url"] or "").rstrip("/")
            async with _hx.AsyncClient(timeout=_hx.Timeout(60.0, connect=10.0)) as cli:
                r2 = await cli.post(f"{base}/chat/completions",
                    headers={"Authorization": f"Bearer {row['api_key']}",
                             "Content-Type": "application/json"},
                    json={"model": model, "messages":
                          [{"role":"user","content":"Balas satu kata: SIAP"}],
                          "max_tokens": 50})
            ok = r2.status_code == 200
            if ok:
                snippet = (r2.json().get("choices",[{}])[0].get("message",{})
                           .get("content","") or "")[:80]
            else:
                snippet = f"HTTP {r2.status_code}: {r2.text[:120]}"
        ms = round((time.time()-t0)*1000)
        return {"status": "success" if ok else "error", "latency_ms": ms,
                "snippet": snippet,
                "message": ("Koneksi OK" if ok else f"Gagal: {snippet}")}
    except Exception as e:
        return {"status": "error",
                "message": f"Error: {str(e)[:200]}"}



@app.post("/api/settings/main-brain")


@app.post("/api/settings/main-brain")
async def set_main_brain_endpoint(payload: Dict[str, Any]):
    """Set the agent's MAIN BRAIN by activating a specific vault key.
    Optional 'model' overrides the key's default model. Applies instantly to
    both Telegram and Web chat (no restart)."""
    key_id = payload.get("key_id")
    model_override = str(payload.get("model", "") or "").strip()
    try:
        key_id = int(key_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="key_id wajib berupa angka.")
    res = database.activate_api_key_sync(key_id)
    database.set_main_brain_model(model_override)   # '' = ikuti default kunci
    if res.get("status") == "success":
        # ── SINKRON: semua agen swarm mengikuti otak utama ──
        key_row = None
        with database.get_sync_db() as conn:
            kr = conn.execute(
                "SELECT provider, default_model FROM api_keys WHERE id = ?",
                (key_id,)).fetchone()
            key_row = dict(kr) if kr else None
        # Sinkron HANYA Alpha Lead (kembaran persona agent Telegram).
        # Agen lain punya jalur spesialis masing-masing & tidak disentuh.
        if key_row:
            for a in database.list_custom_agents_sync():
                if a["name"] == "Alpha Lead":
                    database.update_custom_agent_sync(a["id"], {
                        "provider": key_row["provider"],
                        "model": model_override or key_row["default_model"],
                        "api_key_id": key_id,
                    })
                    res["synced_agents"] = ["Alpha Lead"]
                    res["message"] += " Alpha Lead ikut tersinkron."
                    break

        import main_brain as _mb
        brain = _mb.get_main_brain()
        res["main_brain"] = {
            "provider": brain["provider"],
            "model": brain["model"],
            "key_id": brain["key_id"],
            "label": brain["label"],
        }
        res["message"] += f" Model: {brain['model']}"
    return res


@app.post("/api/settings")
async def update_system_settings(payload: Dict[str, Any]):
    """Update system configuration (.env and database settings).

    Only fields explicitly present in the payload are modified; absent
    fields keep their existing .env values untouched.
    """
    import os
    env_path = os.path.join(os.path.dirname(__file__), ".env")

    def _get(field: str) -> Optional[str]:
        """Return stripped payload value only if the client explicitly sent it."""
        if field in payload and isinstance(payload[field], str):
            return payload[field].strip()
        return None

    bot_token = _get("telegram_bot_token")
    gemini_key = _get("gemini_api_key")
    gemini_model = _get("gemini_model")
    allowed_ids = _get("allowed_user_ids")
    system_instruction = _get("system_instruction")
    
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    else:
        lines = []
        
    new_lines = []
    keys_seen = set()
    
    for line in lines:
        if line.startswith("TELEGRAM_BOT_TOKEN="):
            keys_seen.add("TELEGRAM_BOT_TOKEN")
            if bot_token is not None and bot_token and not bot_token.startswith("***") and "..." not in bot_token:
                new_lines.append(f"TELEGRAM_BOT_TOKEN={bot_token}\n")
            else:
                new_lines.append(line)
        elif line.startswith("GEMINI_API_KEY="):
            keys_seen.add("GEMINI_API_KEY")
            if gemini_key is not None and gemini_key and not gemini_key.startswith("***") and "..." not in gemini_key:
                new_lines.append(f"GEMINI_API_KEY={gemini_key}\n")
            else:
                new_lines.append(line)
        elif line.startswith("GEMINI_MODEL="):
            keys_seen.add("GEMINI_MODEL")
            if gemini_model is not None and gemini_model:
                new_lines.append(f"GEMINI_MODEL={gemini_model}\n")
            else:
                new_lines.append(line)
        elif line.startswith("ALLOWED_USER_IDS="):
            keys_seen.add("ALLOWED_USER_IDS")
            if allowed_ids is not None:
                new_lines.append(f"ALLOWED_USER_IDS={allowed_ids}\n")
            else:
                new_lines.append(line)
        elif line.startswith("SYSTEM_INSTRUCTION="):
            keys_seen.add("SYSTEM_INSTRUCTION")
            if system_instruction is not None and system_instruction:
                escaped_instr = system_instruction.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
                new_lines.append(f'SYSTEM_INSTRUCTION="{escaped_instr}"\n')
            else:
                new_lines.append(line)
        else:
            new_lines.append(line)
            
    # Append any settings whose key was not present in the file yet
    # (only for fields the client explicitly sent).
    pending = []
    if "TELEGRAM_BOT_TOKEN" not in keys_seen and bot_token and not bot_token.startswith("***") and "..." not in bot_token:
        pending.append(f"TELEGRAM_BOT_TOKEN={bot_token}\n")
    if "GEMINI_API_KEY" not in keys_seen and gemini_key and not gemini_key.startswith("***") and "..." not in gemini_key:
        pending.append(f"GEMINI_API_KEY={gemini_key}\n")
    if "GEMINI_MODEL" not in keys_seen and gemini_model:
        pending.append(f"GEMINI_MODEL={gemini_model}\n")
    if "ALLOWED_USER_IDS" not in keys_seen and allowed_ids is not None:
        pending.append(f"ALLOWED_USER_IDS={allowed_ids}\n")
    if "SYSTEM_INSTRUCTION" not in keys_seen and system_instruction:
        escaped_instr = system_instruction.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        pending.append(f'SYSTEM_INSTRUCTION="{escaped_instr}"\n')
    
    if pending or new_lines != lines:
        with open(env_path, "w", encoding="utf-8") as f:
            f.writelines(new_lines + pending)
            
    # Write the personality to its authoritative location. run_agent_turn
    # re-reads this file on EVERY message, so changes take effect immediately
    # for both Telegram and the web chat - no restart needed.
    # Empty string means "clear the file"; absent key means untouched.
    if system_instruction is not None:
        alfa_dir = os.path.expanduser("~/.alfa")
        alfa_prompt_path = os.path.join(alfa_dir, "system_prompt.txt")
        try:
            os.makedirs(alfa_dir, exist_ok=True)
            # Keep one-step backup so a bad save can always be rolled back
            if os.path.exists(alfa_prompt_path):
                shutil.copyfile(alfa_prompt_path, alfa_prompt_path + ".bak")
            with open(alfa_prompt_path, "w", encoding="utf-8") as f:
                f.write(system_instruction + "\n")
        except Exception as prompt_err:
            return {"status": "error", "message": f"Gagal menulis {alfa_prompt_path}: {prompt_err}"}
            
    db_updates = payload.get("db_settings", {})
    if db_updates:
        with database.get_sync_db() as conn:
            c = conn.cursor()
            c.execute("CREATE TABLE IF NOT EXISTS system_settings (key TEXT PRIMARY KEY, value TEXT)")
            for k, v in db_updates.items():
                c.execute("INSERT OR REPLACE INTO system_settings (key, value) VALUES (?, ?)", (str(k), str(v)))
            conn.commit()
            
    return {"status": "success", "message": "Konfigurasi tersimpan. Kepribadian agent langsung aktif (Telegram & Web) tanpa restart."}


# ==================== UNIVERSAL PRO SCRAPER ENDPOINTS ====================

@app.post("/api/scraper/universal")
async def api_universal_scrape(payload: Dict[str, Any]):
    """Execute high-yield universal keyword scraper across specialized platforms."""
    import universal_scraper
    query = payload.get("query", "").strip()
    category = payload.get("category", "all_marketplace")
    limit = safe_int(payload.get("limit", 50), 50, minimum=1, maximum=200)
    if not query:
        return {"status": "error", "message": "Query pencarian wajib diisi."}
    
    res = universal_scraper.scrape_universal_keyword(query=query, category=category, limit=limit)
    return res


@app.post("/api/scraper/custom-batch")
async def api_custom_batch_scrape(payload: Dict[str, Any]):
    """Execute custom multi-URL batch scraper."""
    import universal_scraper
    urls = payload.get("urls", [])
    concurrency = safe_int(payload.get("concurrency", 15), 15, minimum=1, maximum=50)
    use_camoufox = bool(payload.get("use_camoufox", False))
    if not urls:
        return {"status": "error", "message": "Daftar URL wajib diisi."}
    
    res = universal_scraper.scrape_custom_urls_or_selectors(urls=urls, concurrency=concurrency, use_camoufox=use_camoufox)
    return res


@app.get("/api/scraper/batches")
async def api_list_scraper_batches(limit: int = 15):
    """List recent master scraper batches."""
    import universal_scraper
    batches = universal_scraper.list_all_scrape_batches(limit=limit)
    return {"status": "success", "batches": batches}


@app.post("/api/scraper/modern-lab")
async def api_modern_scraper_lab(payload: Dict[str, Any]):
    """
    Unified Next-Gen Scraper Lab combining:
    Crawl4AI, Scrapling Anti-Bot, Microsoft MarkItDown, Scrapy Parsel, Apify Crawlee, and Firecrawl.
    """
    url = payload.get("url", "").strip()
    engine = payload.get("engine", "auto_hybrid")
    css_selector = payload.get("css_selector", "").strip()
    extract_type = payload.get("extract_type", "markdown")
    max_pages = safe_int(payload.get("max_pages", 3), 3, minimum=1, maximum=50)
    auto_ingest = bool(payload.get("auto_ingest_vector", False))
    
    if not url:
        return {"status": "error", "message": "URL target wajib diisi."}
        
    start_t = time.time()
    extracted_text = ""
    markdown_output = ""
    raw_data = None
    engine_used = engine
    
    try:
        if engine == "crawl4ai":
            res = tools.crawl4ai_web_crawler(url=url)
            markdown_output = res.get("markdown", "")
            extracted_text = markdown_output
            raw_data = res
            
        elif engine == "scrapling":
            res = tools.scrapling_stealth_fetch(url=url, css_selector=css_selector, extract_type=extract_type)
            raw_data = res
            if isinstance(res.get("data"), list):
                extracted_text = "\n".join(str(x) for x in res["data"])
            else:
                extracted_text = str(res.get("data", ""))
            markdown_output = f"# Scraped from {url}\n\n" + extracted_text
            
        elif engine == "markitdown":
            res = tools.markitdown_convert_document(source_path_or_url=url)
            markdown_output = res.get("markdown_snippet", "")
            extracted_text = markdown_output
            raw_data = res
            
        elif engine == "scrapy":
            item_json = json.dumps({"selected": css_selector}) if css_selector else "{}"
            res = tools.scrapy_spider_quick_scrape(url=url, item_selectors_json=item_json)
            raw_data = res
            extracted_text = json.dumps(res.get("extracted_fields", {}), indent=2)
            markdown_output = f"# Scrapy Parsel Result for {url}\n\n```json\n{extracted_text}\n```"
            
        elif engine == "crawlee":
            res = tools.crawlee_web_scraper(start_urls=url, max_requests=max_pages)
            raw_data = res
            pages = res.get("pages", [])
            extracted_text = "\n\n".join([f"### {p.get('title')}\nURL: {p.get('url')}\n{p.get('text_summary')}" for p in pages])
            markdown_output = f"# Crawlee Multi-Page Result ({len(pages)} pages)\n\n" + extracted_text
            
        elif engine == "firecrawl":
            res = tools.firecrawl_scrape_and_crawl(url=url)
            raw_data = res
            markdown_output = res.get("markdown", "")
            extracted_text = markdown_output
            
        else:  # auto_hybrid
            engine_used = "auto_hybrid (Scrapling -> Crawl4AI -> MarkItDown)"
            res = tools.scrapling_stealth_fetch(url=url, css_selector=css_selector, extract_type="text")
            if res.get("status") == "success" and res.get("data"):
                data_val = res.get("data")
                extracted_text = "\n".join(data_val) if isinstance(data_val, list) else str(data_val)
                markdown_output = f"# Extracted Content: {url}\n\n" + extracted_text
                raw_data = res
            else:
                res2 = tools.crawl4ai_web_crawler(url=url)
                if res2.get("status") == "success" and res2.get("markdown"):
                    markdown_output = res2.get("markdown", "")
                    extracted_text = markdown_output
                    raw_data = res2
                else:
                    res3 = tools.markitdown_convert_document(source_path_or_url=url)
                    markdown_output = res3.get("markdown_snippet", "")
                    extracted_text = markdown_output
                    raw_data = res3

        duration_ms = round((time.time() - start_t) * 1000, 1)
        
        vector_status = None
        if auto_ingest and extracted_text.strip():
            import vector_memory
            uid = get_primary_user_id()
            v_res = vector_memory.ingest_document(
                user_id=uid,
                title=f"Web Scrape: {url[:50]}",
                content_or_path=extracted_text,
                category="Scraped Web Lab"
            )
            vector_status = v_res
            
        return {
            "status": "success",
            "url": url,
            "engine": engine_used,
            "duration_ms": duration_ms,
            "markdown": markdown_output,
            "extracted_text": extracted_text[:5000],
            "raw_data": raw_data,
            "vector_ingest": vector_status
        }
    except Exception as e:
        return {"status": "error", "message": f"Scraper Lab error: {str(e)}"}



@app.get("/api/services")
async def get_services_status():
    """Get detailed status of all ecosystem services."""
    services = [
        {"name": "telegram-ai-bot.service", "title": "ALFA Telegram AI Agent (God Mode)"},
        {"name": "wa-sheets-bot.service", "title": "WhatsApp Google Sheets Bot"},
        {"name": "alfa-dashboard.service", "title": "ALFA Web Command Center (Port 8080)"}
    ]
    results = []
    for s in services:
        svc = s["name"]
        if os.name == "nt":
            def _svc_active(hint):
                for p in psutil.process_iter(['cmdline']):
                    try:
                        cl = p.info.get('cmdline') or []
                        if any(hint in str(c) for c in cl):
                            return True
                    except Exception:
                        continue
                return False
            hint_map = {
                "telegram-ai-bot.service": "bot.py",
                "wa-sheets-bot.service": "wa_sheets",
                "alfa-dashboard.service": "web_dashboard.py"
            }
            active = _svc_active(hint_map.get(svc, ""))
            results.append({
                "name": svc,
                "title": s["title"],
                "is_active": active,
                "state": "active (process)" if active else "inactive",
                "is_enabled": active,
                "details": "systemd tidak tersedia di Windows; status dideteksi dari proses berjalan."
            })
            continue
        res_act = subprocess.run(["systemctl", "--user", "is-active", svc], capture_output=True, text=True)
        res_enb = subprocess.run(["systemctl", "--user", "is-enabled", svc], capture_output=True, text=True)
        res_stat = subprocess.run(["systemctl", "--user", "status", svc, "--no-pager", "-n", "8"], capture_output=True, text=True)
        
        results.append({
            "name": svc,
            "title": s["title"],
            "is_active": res_act.stdout.strip() == "active",
            "state": res_act.stdout.strip(),
            "is_enabled": res_enb.stdout.strip() == "enabled",
            "details": res_stat.stdout.strip()
        })
    return {"status": "success", "services": results}


@app.get("/api/wa/qr")
async def get_wa_qr():
    """Fetch live WhatsApp QR code and authentication status."""
    try:
        import httpx
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get("http://localhost:3000/api/qr")
            if resp.status_code == 200:
                return resp.json()
    except Exception:
        pass
        
    # Fallback to local sync file
    status_file = os.path.expanduser("~/.alfa/wa_status.json")
    if os.path.exists(status_file):
        try:
            with open(status_file, "r") as f:
                data = json.load(f)
            qr_str = data.get("qr", "")
            qr_data_url = None
            if qr_str:
                import base64
                import io

                import qrcode
                img = qrcode.make(qr_str)
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                b64 = base64.b64encode(buf.getvalue()).decode()
                qr_data_url = f"data:image/png;base64,{b64}"
            return {
                "status": data.get("status", "UNKNOWN"),
                "is_ready": data.get("status") == "READY",
                "qr_available": bool(qr_str),
                "qr_string": qr_str,
                "qr_data_url": qr_data_url,
                "timestamp": data.get("updated_at", "")
            }
        except Exception:
            pass
            
    return {
        "status": "DISCONNECTED",
        "is_ready": False,
        "qr_available": False,
        "qr_string": "",
        "qr_data_url": None,
        "timestamp": datetime.now().isoformat()
    }


@app.post("/api/wa/logout")
async def logout_wa():
    """Trigger WhatsApp logout to force new QR generation."""
    try:
        import httpx
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post("http://localhost:3000/api/logout")
            if resp.status_code == 200:
                return resp.json()
    except Exception:
        pass
    return {"status": "error", "message": "Failed to connect to WhatsApp bot server on port 3000"}


@app.get("/api/wa/reports")
async def get_wa_reports():
    """Fetch recorded WhatsApp Google Sheets reports and format definitions."""
    try:
        import httpx
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get("http://localhost:3000/api/reports")
            if resp.status_code == 200:
                return resp.json()
    except Exception:
        pass

    reports_file = os.path.expanduser("~/wa-sheets-bot/recorded_reports.json")
    formats_file = os.path.expanduser("~/wa-sheets-bot/formats.json")
    reports_data = []
    formats_data = []
    if os.path.exists(reports_file):
        try:
            with open(reports_file, "r") as f:
                reports_data = json.load(f)
        except Exception:
            pass
    if os.path.exists(formats_file):
        try:
            with open(formats_file, "r") as f:
                formats_data = json.load(f).get("formats", [])
        except Exception:
            pass

    return {
        "status": "success",
        "spreadsheet_id": "1d9Mr1IZszP1Cq34VN1_OTHtWokxDdV4prywsgVxN0RQ",
        "formats": formats_data,
        "total_recorded": len(reports_data),
        "pending_queue_count": 0,
        "reports": reports_data
    }


WA_BOT_FORMATS_FILE = os.path.expanduser("~/wa-sheets-bot/formats.json")
WA_BOT_MEDIA_RULES_FILE = os.path.expanduser("~/wa-sheets-bot/media_rules.json")
_WA_DYNAMIC_SOURCES = {"timestamp", "sender", "group", "body"}
_WA_MEDIA_TYPES = {"foto", "video", "pdf", "excel", "dokumen", "audio"}


def _validate_media_rules(rules: Any) -> List[str]:
    errs = []
    if not isinstance(rules, list):
        return ["Field 'rules' harus berupa array."]
    if len(rules) > 30:
        return ["Maksimal 30 aturan."]
    seen = set()
    for i, r in enumerate(rules, 1):
        tag = f"Aturan #{i}"
        if not isinstance(r, dict):
            errs.append(f"{tag}: bukan objek.")
            continue
        name = str(r.get("name", "")).strip()
        if not name:
            errs.append(f"{tag}: nama kosong.")
        elif name.lower() in seen:
            errs.append(f"{tag}: nama '{name}' duplikat.")
        seen.add(name.lower())
        types = r.get("types")
        if not isinstance(types, list) or not types or not all(t in _WA_MEDIA_TYPES for t in types):
            errs.append(f"{tag} '{name}': pilih minimal satu jenis file ({', '.join(sorted(_WA_MEDIA_TYPES))}).")
        pattern = str(r.get("naming", "")).strip()
        if not pattern:
            errs.append(f"{tag} '{name}': pola nama file kosong.")
    return errs


@app.get("/api/wa/media-rules")
async def get_wa_media_rules():
    """Read automatic media-saving rules for the Drive side of wa-sheets-bot."""
    result = {"status": "success", "exists": False, "rules": [], "path": WA_BOT_MEDIA_RULES_FILE}
    try:
        if os.path.exists(WA_BOT_MEDIA_RULES_FILE):
            with open(WA_BOT_MEDIA_RULES_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            result["exists"] = True
            result["rules"] = data.get("rules", []) if isinstance(data, dict) else []
    except Exception as e:
        result["status"] = "error"
        result["message"] = f"Gagal membaca media_rules.json: {e}"
    return result


@app.post("/api/wa/media-rules")
async def save_wa_media_rules(payload: Dict[str, Any]):
    """Save media auto-save rules. Backed up + atomic write, live effect."""
    rules = payload.get("rules")
    errors = _validate_media_rules(rules)
    if errors:
        return {"status": "error", "validation_errors": errors,
                "message": "; ".join(errors[:4])}

    clean = []
    for r in rules:
        clean.append({
            "name": str(r["name"]).strip(),
            "enabled": bool(r.get("enabled", True)),
            "types": [str(t).strip() for t in r["types"]],
            "keyword": str(r.get("keyword", "")).strip(),
            "folder": str(r.get("folder", "")).strip() or "Umum",
            "naming": str(r["naming"]).strip(),
        })

    try:
        os.makedirs(os.path.dirname(WA_BOT_MEDIA_RULES_FILE), exist_ok=True)
        if os.path.exists(WA_BOT_MEDIA_RULES_FILE):
            shutil.copyfile(WA_BOT_MEDIA_RULES_FILE, WA_BOT_MEDIA_RULES_FILE + ".bak")
        tmp_path = WA_BOT_MEDIA_RULES_FILE + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump({"rules": clean}, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp_path, WA_BOT_MEDIA_RULES_FILE)
        return {"status": "success", "saved": len(clean),
                "message": f"{len(clean)} aturan media tersimpan. Bot langsung memakainya."}
    except Exception as e:
        return {"status": "error", "message": f"Gagal menyimpan media_rules.json: {str(e)}"}


def _gdrive_ensure_subfolder(folder_name: str) -> str:
    """Find or create a subfolder inside the default Drive folder; return its id."""
    import tools as _t
    parent = _t._get_default_gdrive_folder_id()
    service = _t._get_gdrive_service()
    q = f"name = '{folder_name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    if parent:
        q += f" and '{parent}' in parents"
    found = service.files().list(q=q, fields="files(id, name)", spaces="drive",
                                 supportsAllDrives=True, pageSize=5).execute()
    files = found.get("files", [])
    if files:
        return files[0]["id"]
    meta = {"name": folder_name, "mimeType": "application/vnd.google-apps.folder"}
    if parent:
        meta["parents"] = [parent]
    created = service.files().create(body=meta, fields="id", supportsAllDrives=True).execute()
    return created["id"]


WA_DRIVE_UPLOADS_FILE = os.path.expanduser("~/wa-sheets-bot/drive_uploads.json")


def _log_wa_drive_upload(entry: Dict[str, Any]):
    """Prepend entry to drive_uploads.json (cap 200), atomic write."""
    try:
        data = {"uploads": []}
        if os.path.exists(WA_DRIVE_UPLOADS_FILE):
            try:
                with open(WA_DRIVE_UPLOADS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f) or data
            except Exception:
                pass
        uploads = data.get("uploads", [])
        uploads.insert(0, entry)
        data["uploads"] = uploads[:200]
        tmp = WA_DRIVE_UPLOADS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, WA_DRIVE_UPLOADS_FILE)
    except Exception as e:
        logger.warning(f"Could not log wa drive upload: {e}")


@app.get("/api/wa/drive-uploads")
async def get_wa_drive_uploads():
    """Recent files auto-uploaded from WhatsApp to Google Drive."""
    result = {"status": "success", "uploads": [], "total": 0}
    try:
        if os.path.exists(WA_DRIVE_UPLOADS_FILE):
            with open(WA_DRIVE_UPLOADS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            ups = data.get("uploads", []) if isinstance(data, dict) else []
            result["uploads"] = ups
            result["total"] = len(ups)
    except Exception as e:
        result["status"] = "error"
        result["message"] = str(e)
    return result


@app.post("/api/wa/media-upload")
async def wa_media_upload(
    file: UploadFile = File(...),
    format_name: str = Form("Lainnya"),
    subfolder: str = Form(""),
    sender: str = Form(""),
    group: str = Form(""),
    caption: str = Form(""),
):
    """Receive media from wa-sheets-bot (localhost) and upload it to Google Drive
    under 'WA Media/<subfolder|format_name>' using the active OAuth account."""
    try:
        upload_dir = os.path.join("/dev/shm", "alfa_wa_media")
        os.makedirs(upload_dir, exist_ok=True)
        safe_name = os.path.basename(file.filename or "media.bin") or "media.bin"
        tmp_path = os.path.join(upload_dir, f"{int(time.time()*1000)}_{safe_name}")
        with open(tmp_path, "wb") as out:
            out.write(await file.read())

        target_sub = (subfolder.strip() or f"{(format_name or 'Lainnya').strip()[:40]}")
        subfolder_id = _gdrive_ensure_subfolder(f"WA Media / {target_sub}")
        res = tools.gdrive_upload_file(filepath=tmp_path, folder_id=subfolder_id,
                                       custom_filename=safe_name)
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        if res.get("status") == "success":
            _log_wa_drive_upload({
                "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "file_name": res.get("file_name"),
                "web_link": res.get("web_link"),
                "folder": f"WA Media / {target_sub}",
                "format_name": format_name or "",
                "sender": sender or "",
                "group": group or "",
                "caption": (caption or "")[:300],
            })
            return {"status": "success", "web_link": res.get("web_link"),
                    "file_name": res.get("file_name"), "folder": f"WA Media / {target_sub}"}
        return res
    except Exception as e:
        return {"status": "error", "message": str(e)}


def _validate_wa_formats(formats: Any) -> List[str]:
    """Return list of validation error strings (empty = valid)."""
    errs = []
    if not isinstance(formats, list):
        return ["Field 'formats' harus berupa array."]
    if len(formats) > 50:
        return ["Maksimal 50 format."]
    seen_names, seen_tabs = set(), set()
    for i, f in enumerate(formats, 1):
        tag = f"Format #{i}"
        if not isinstance(f, dict):
            errs.append(f"{tag}: bukan objek.")
            continue
        name = str(f.get("name", "")).strip()
        tab = str(f.get("tab", "")).strip()
        keywords = f.get("keywords")
        columns = f.get("columns")
        if not name:
            errs.append(f"{tag}: nama kosong.")
        if name.lower() in seen_names:
            errs.append(f"{tag}: nama '{name}' duplikat.")
        seen_names.add(name.lower())
        if not tab:
            errs.append(f"{tag} '{name}': tab Sheets kosong.")
        if tab in seen_tabs:
            errs.append(f"{tag}: tab '{tab}' dipakai lebih dari satu format.")
        seen_tabs.add(tab)
        if not isinstance(keywords, list) or not keywords or not all(
            isinstance(k, str) and k.strip() for k in keywords
        ):
            errs.append(f"{tag} '{name}': keywords wajib minimal 1 kata pemicu.")
        if not isinstance(columns, list) or not columns:
            errs.append(f"{tag} '{name}': minimal 1 kolom.")
            continue
        if len(columns) > 30:
            errs.append(f"{tag} '{name}': maksimal 30 kolom.")
        for j, c in enumerate(columns, 1):
            title = str((c or {}).get("title", "")).strip()
            source = str((c or {}).get("source", (c or {}).get("value", ""))).strip()
            if not title:
                errs.append(f"{tag} '{name}' kolom {j}: judul kosong.")
            if not source:
                errs.append(f"{tag} '{name}' kolom {j} '{title}': sumber kosong.")
    return errs


@app.get("/api/wa/formats")
async def get_wa_formats():
    """Read the WhatsApp report format definitions consumed by wa-sheets-bot."""
    result = {"status": "success", "exists": False, "formats": [], "path": WA_BOT_FORMATS_FILE}
    try:
        if os.path.exists(WA_BOT_FORMATS_FILE):
            with open(WA_BOT_FORMATS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            result["exists"] = True
            result["formats"] = data.get("formats", []) if isinstance(data, dict) else []
    except Exception as e:
        result["status"] = "error"
        result["message"] = f"Gagal membaca formats.json: {e}"
    return result


@app.post("/api/wa/formats")
async def save_wa_formats(payload: Dict[str, Any]):
    """
    Save report formats. wa-sheets-bot auto-reloads formats.json on change
    (mtime check), so edits take effect immediately - no restart needed.
    A one-step backup (formats.json.bak) is kept before every save.
    """
    formats = payload.get("formats")
    errors = _validate_wa_formats(formats)
    if errors:
        return {"status": "error", "validation_errors": errors,
                "message": "; ".join(errors[:4])}

    # Normalise: strip whitespace everywhere, keep only needed keys
    clean = []
    for f in formats:
        cols = [{"title": str(c["title"]).strip(), "source": str(c["source"]).strip()}
                for c in f["columns"]]
        clean.append({
            "name": str(f["name"]).strip(),
            "keywords": [str(k).strip() for k in f["keywords"]],
            "tab": str(f["tab"]).strip(),
            "columns": cols,
        })

    try:
        os.makedirs(os.path.dirname(WA_BOT_FORMATS_FILE), exist_ok=True)
        # Backup previous version once
        if os.path.exists(WA_BOT_FORMATS_FILE):
            shutil.copyfile(WA_BOT_FORMATS_FILE, WA_BOT_FORMATS_FILE + ".bak")

        tmp_path = WA_BOT_FORMATS_FILE + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump({"formats": clean}, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp_path, WA_BOT_FORMATS_FILE)
        return {
            "status": "success",
            "saved": len(clean),
            "backup": WA_BOT_FORMATS_FILE + ".bak",
            "message": f"{len(clean)} format laporan tersimpan. Bot WhatsApp langsung memakainya (tanpa restart)."
        }
    except Exception as e:
        return {"status": "error", "message": f"Gagal menyimpan formats.json: {str(e)}"}


@app.post("/api/services/action")
async def service_action(payload: Dict[str, Any]):
    """Start, stop, or restart a systemd user service."""
    service_name = payload.get("service")
    action = payload.get("action", "status")
    
    if action not in ["start", "stop", "restart", "enable", "disable"]:
        raise HTTPException(status_code=400, detail="Invalid action")
        
    allowed_services = ["telegram-ai-bot.service", "wa-sheets-bot.service", "alfa-dashboard.service"]
    if service_name not in allowed_services:
        raise HTTPException(status_code=403, detail="Unauthorized service management")
        
    res = subprocess.run(["systemctl", "--user", action, service_name], capture_output=True, text=True)
    time.sleep(1)
    res_act = subprocess.run(["systemctl", "--user", "is-active", service_name], capture_output=True, text=True)
    
    return {
        "status": "success" if res.returncode == 0 else "error",
        "service": service_name,
        "action": action,
        "current_state": res_act.stdout.strip(),
        "output": res.stderr or res.stdout
    }


@app.get("/api/services/logs")
async def get_service_logs(service: str = "telegram-ai-bot.service", lines: int = 50):
    """Fetch live service logs (journalctl di Linux, file log lokal di Windows)."""
    lines = max(10, min(int(lines), 500))
    if os.name == "nt":
        log_file = "bot_err.log" if "telegram" in service else (
            "dash_err.log" if "dashboard" in service else "wa_bot.log")
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), log_file)
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                tail = f.readlines()[-lines:]
            return {"status": "success", "service": service, "logs": "".join(tail).strip()}
        except FileNotFoundError:
            return {"status": "success", "service": service,
                    "logs": f"(file log '{log_file}' belum ada)"}
    res = subprocess.run(["journalctl", "--user", "-u", service, "-n", str(lines), "--no-pager"], capture_output=True, text=True)
    return {
        "status": "success",
        "service": service,
        "logs": res.stdout.strip()
    }


@app.get("/api/memory")
async def get_memory_data():
    """Fetch all permanent memory facts and knowledge graph relations."""
    uid = get_primary_user_id()
    memories = await database.get_all_memories(uid)
    kg = database.get_all_knowledge_graph_sync(uid)
    
    return {
        "status": "success",
        "user_id": uid,
        "total_memories": len(memories),
        "total_kg_relations": len(kg),
        "memories": memories,
        "knowledge_graph": kg
    }


@app.post("/api/memory/add")
async def add_memory(payload: Dict[str, Any]):
    """Add a new memory fact or knowledge graph relation."""
    uid = get_primary_user_id()
    m_type = payload.get("type", "fact")
    
    if m_type == "fact":
        key = payload.get("key_topic")
        content = payload.get("content")
        cat = payload.get("category", "general")
        if not key or not content:
            raise HTTPException(status_code=400, detail="key_topic and content required")
        res = database.save_memory_fact_sync(uid, key, content, cat)
        return {"status": "success", "result": res}
    else:
        entity = payload.get("entity")
        relation = payload.get("relation")
        target = payload.get("target_value")
        cat = payload.get("category", "general")
        tags = payload.get("tags", "")
        if not entity or not relation or not target:
            raise HTTPException(status_code=400, detail="entity, relation, and target_value required")
        res = database.add_knowledge_relation_sync(uid, entity, relation, target, cat, tags)
        return {"status": "success", "result": res}


@app.post("/api/memory/delete")
async def delete_memory(payload: Dict[str, Any]):
    """Delete a memory fact by key."""
    uid = get_primary_user_id()
    key_topic = payload.get("key_topic")
    if not key_topic:
        raise HTTPException(status_code=400, detail="key_topic is required")
        
    import aiosqlite
    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent_data.db")
    async with aiosqlite.connect(db_path) as db:
        await db.execute("DELETE FROM knowledge_memory WHERE user_id = ? AND key_topic = ?", (uid, key_topic))
        await db.commit()
        
    return {"status": "success", "message": f"Fakta '{key_topic}' berhasil dihapus."}


@app.get("/api/brain/export")
async def export_brain():
    """Export complete Second Brain knowledge as Markdown and JSON."""
    uid = get_primary_user_id()
    memories = await database.get_all_memories(uid)
    kg = database.get_all_knowledge_graph_sync(uid)
    
    md_lines = ["# 🧠 ALFA SECOND BRAIN KNOWLEDGE EXPORT\n", f"Exported: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n## 📝 Permanent Facts & Memories\n"]
    for m in memories:
        md_lines.append(f"- **[{m['category'].upper()}] {m['key_topic']}**: {m['content']}")
        
    md_lines.append("\n## 🕸️ Semantic Knowledge Graph\n")
    for k in kg:
        md_lines.append(f"- `{k['entity']}` ──*({k['relation']})*──> `{k['target_value']}` [{k['category']}]")
        
    return {
        "status": "success",
        "markdown": "\n".join(md_lines),
        "json": {
            "user_id": uid,
            "exported_at": datetime.now().isoformat(),
            "memories": memories,
            "knowledge_graph": kg
        }
    }


# ==================== NEURAL VECTOR BRAIN & SEMANTIC RAG ENDPOINTS ====================

@app.post("/api/brain/vector/search")
async def api_vector_search(payload: Dict[str, Any]):
    """Execute cosine semantic similarity search on permanent Vector Brain embeddings."""
    import vector_memory
    query = payload.get("query", "").strip()
    top_k = safe_int(payload.get("top_k", 5), 5, minimum=1, maximum=50)
    category = payload.get("category", "")
    uid = get_primary_user_id()
    
    if not query:
        return {"status": "error", "message": "Search query is required"}
        
    matches = vector_memory.semantic_search(user_id=uid, query=query, top_k=top_k, category=category or None)
    return {
        "status": "success",
        "query": query,
        "total_matches": len(matches),
        "matches": matches
    }


@app.post("/api/brain/vector/ingest")
async def api_vector_ingest(payload: Dict[str, Any]):
    """Ingest, chunk, and embed a document or file into permanent Vector Brain."""
    import vector_memory
    title = payload.get("title", "").strip()
    content = payload.get("content", "").strip()
    category = payload.get("category", "general").strip()
    uid = get_primary_user_id()
    
    if not title or not content:
        raise HTTPException(status_code=400, detail="title and content are required")
        
    res = vector_memory.ingest_document(user_id=uid, title=title, content_or_path=content, category=category)
    return res



@app.get("/api/meeting/history")
async def get_meeting_history():
    """Get AI agent meeting history logs."""
    history_path = os.path.expanduser("~/my-agent-workspace/logs/meeting_history.json")
    if os.path.exists(history_path):
        try:
            with open(history_path, "r") as f:
                return json.load(f)
        except Exception:
            return []
    return []


@app.get("/api/brain/vector/list")
async def api_vector_list():
    """List all ingested documents currently in Vector Brain."""
    import vector_memory
    uid = get_primary_user_id()
    docs = vector_memory.list_ingested_documents(user_id=uid)
    return {
        "status": "success",
        "total_documents": len(docs),
        "documents": docs
    }


@app.post("/api/brain/vector/delete")
async def api_vector_delete(payload: Dict[str, Any]):
    """Delete a document and its embedding chunks from Vector Brain."""
    import vector_memory
    doc_title = payload.get("doc_title", "").strip()
    uid = get_primary_user_id()
    if not doc_title:
        raise HTTPException(status_code=400, detail="doc_title is required")
        
    return vector_memory.delete_document(user_id=uid, doc_title=doc_title)


# ==================== DYNAMIC SELF-EVOLUTION PLUGINS ENDPOINTS ====================

@app.get("/api/plugins/list")
async def api_plugins_list():
    """List all active self-evolved dynamic plugin tools."""
    import plugins
    plugins_list = plugins.list_all_plugins()
    return {
        "status": "success",
        "total_plugins": len(plugins_list),
        "plugins": plugins_list
    }


@app.post("/api/plugins/create")
async def api_plugins_create(payload: Dict[str, Any]):
    """Compile, sandbox-test, and hot-load a new dynamic plugin tool."""
    import plugins
    tool_name = payload.get("tool_name", "").strip()
    tool_description = payload.get("tool_description", "").strip()
    tool_code = payload.get("tool_code", "").strip()
    test_kwargs = payload.get("test_kwargs", {})
    
    if not tool_name or not tool_code:
        raise HTTPException(status_code=400, detail="tool_name and tool_code are required")
        
    res = plugins.create_and_register_plugin(tool_name, tool_description, tool_code, test_kwargs=test_kwargs)
    return res


@app.post("/api/plugins/delete")
async def api_plugins_delete(payload: Dict[str, Any]):
    """Permanently remove a dynamic plugin tool."""
    import plugins
    tool_name = payload.get("tool_name", "").strip()
    if not tool_name:
        raise HTTPException(status_code=400, detail="tool_name is required")
    return plugins.delete_plugin(tool_name)


@app.post("/api/plugins/execute")
async def api_plugins_execute(payload: Dict[str, Any]):
    """Execute a dynamic plugin tool directly."""
    import plugins
    tool_name = payload.get("tool_name", "").strip()
    kwargs = payload.get("kwargs", {})
    if not tool_name:
        raise HTTPException(status_code=400, detail="tool_name is required")
        
    try:
        start_t = time.time()
        result = plugins.execute_plugin_direct(tool_name, **kwargs)
        duration_ms = round((time.time() - start_t) * 1000, 1)
        return {
            "status": "success",
            "tool_name": tool_name,
            "duration_ms": duration_ms,
            "result": result
        }
    except Exception as e:
        return {"status": "error", "message": f"Plugin execution error: {str(e)}"}


@app.get("/api/artifacts")
async def list_artifacts():
    """List recent artifacts (images, PDFs, documents, audio) generated by tools."""
    search_dirs = [
        "/dev/shm/alfa_sandbox",
        os.path.expanduser("~/output"),
        os.path.expanduser("~/.alfa")
    ]
    artifacts = []
    valid_exts = {".png", ".jpg", ".jpeg", ".pdf", ".odt", ".ods", ".odp", ".docx", ".xlsx", ".pptx", ".mp3", ".mp4", ".csv", ".json", ".zip"}
    
    for s_dir in search_dirs:
        if os.path.exists(s_dir):
            for root, _, files in os.walk(s_dir):
                for f in files:
                    ext = os.path.splitext(f)[1].lower()
                    if ext in valid_exts:
                        full_p = os.path.join(root, f)
                        st = os.stat(full_p)
                        artifacts.append({
                            "name": f,
                            "path": full_p,
                            "size_kb": round(st.st_size / 1024, 1),
                            "modified": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                            "extension": ext[1:].upper(),
                            "is_image": ext in [".png", ".jpg", ".jpeg"]
                        })
                        
    artifacts = sorted(artifacts, key=lambda x: x["modified"], reverse=True)[:30]
    return {"status": "success", "total": len(artifacts), "artifacts": artifacts}


# ══════════════════════════════════════════════════════════════════════════════
#  📁 WORKSPACE EXPLORER — jelajahi struktur proyek & baca isi file dari web
# ══════════════════════════════════════════════════════════════════════════════

WORKSPACE_ROOTS = [
    {"id": "workspace", "label": "🏠 ALFA Workspace (proyek agen)", "path": "~/ALFA_WORKSPACE"},
    {"id": "swarm", "label": "🤖 Output Swarm", "path": os.path.expanduser("~/Dokumen/ALFA_SWARM_OUTPUTS")},
    {"id": "videos", "label": "🎬 Video Generator", "path": os.path.expanduser("~/Dokumen/ALFA_GENERATED_VIDEOS")},
    {"id": "output", "label": "📦 Folder Output", "path": os.path.expanduser("~/output")},
    {"id": "sandbox", "label": "⚡ Sandbox", "path": "/dev/shm/alfa_sandbox"},
]

_WS_SKIP_DIRS = {".git", "venv", ".venv", "node_modules", "__pycache__",
                 ".mypy_cache", ".pytest_cache", "dist", "build", ".next", "target"}
_WS_MAX_FILE_BYTES = 300_000  # batas baca isi file (teks)


def _ws_real_path(path: str) -> Optional[str]:
    """Resolve path & pastikan berada di dalam salah satu workspace root."""
    real = os.path.realpath(os.path.expanduser(path))
    for r in WORKSPACE_ROOTS:
        rp = os.path.realpath(os.path.expanduser(r["path"]))
        if real == rp or real.startswith(rp + os.sep):
            return real
    return None


def _safe_workspace_path(path: str) -> str:
    real = _ws_real_path(path)
    if not real:
        allowed = ", ".join(os.path.expanduser(r["path"]) for r in WORKSPACE_ROOTS)
        raise HTTPException(
            status_code=403,
            detail=(f"Akses ditolak: '{path or '(kosong)'}' di luar workspace yang diizinkan. "
                    f"Root tersedia: {allowed}. "
                    "Proyek di luar folder ini bisa dipindahkan ke ~/ALFA_WORKSPACE."))
    return real


@app.get("/api/workspace/roots")
async def workspace_roots():
    """Daftar root proyek yang bisa dijelajahi."""
    roots = []
    for r in WORKSPACE_ROOTS:
        p = os.path.realpath(os.path.expanduser(r["path"]))
        roots.append({**r, "exists": os.path.isdir(p)})
    return {"status": "success", "roots": roots}


@app.get("/api/workspace/tree")
async def workspace_tree(path: str):
    """List satu level isi folder (lazy-load per folder klik)."""
    real = _safe_workspace_path(path)
    if not os.path.isdir(real):
        raise HTTPException(status_code=404, detail="Bukan direktori")
    items = []
    try:
        entries = sorted(os.scandir(real),
                         key=lambda e: (not e.is_dir(), e.name.lower()))
    except PermissionError:
        raise HTTPException(status_code=403, detail="Izin dibatalkan")
    for e in entries[:400]:
        if e.name in _WS_SKIP_DIRS or e.name.startswith("."):
            continue
        try:
            st = e.stat()
            items.append({
                "name": e.name,
                "type": "dir" if e.is_dir() else "file",
                "size": st.st_size if e.is_file() else None,
                "modified": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M"),
            })
        except OSError:
            continue
    return {"status": "success", "path": real, "items": items}


@app.get("/api/workspace/file")
async def workspace_read_file(path: str):
    """Baca isi file teks utk dilihat di browser (dengan deteksi biner)."""
    real = _safe_workspace_path(path)
    if not os.path.isfile(real):
        raise HTTPException(status_code=404, detail="File tidak ditemukan")
    size = os.path.getsize(real)
    with open(real, "rb") as f:
        head = f.read(4096)
    is_binary = b"\x00" in head
    if is_binary:
        return {"status": "binary", "name": os.path.basename(real), "size": size,
                "message": "File biner — gunakan tombol Download.",
                "download_url": f"/api/artifacts/download?path={real}"}
    truncated = size > _WS_MAX_FILE_BYTES
    with open(real, "rb") as f:
        data = f.read(_WS_MAX_FILE_BYTES)
    return {
        "status": "success",
        "name": os.path.basename(real),
        "size": size,
        "truncated": truncated,
        "content": data.decode("utf-8", errors="replace"),
        "download_url": f"/api/artifacts/download?path={real}",
    }


@app.get("/api/artifacts/download")
async def download_artifact(path: str):
    """Safely download an artifact file (restricted to known artifact directories)."""
    import swarm_engine
    import video_generator
    allowed_dirs = [
        os.path.realpath("/dev/shm/alfa_sandbox"),
        os.path.realpath(os.path.expanduser("~/output")),
        os.path.realpath(os.path.expanduser("~/.alfa")),
        os.path.realpath(video_generator.VIDEO_OUT_DIR),
        os.path.realpath(swarm_engine.SWARM_OUTPUT_DIR),
    ]
    real_path = os.path.realpath(path)
    if not any(real_path == d or real_path.startswith(d + os.sep) for d in allowed_dirs):
        raise HTTPException(status_code=403, detail="Akses ditolak: path di luar direktori artefak yang diizinkan.")
    if not os.path.exists(real_path) or not os.path.isfile(real_path):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(real_path, filename=os.path.basename(real_path))


@app.get("/api/guardian/config")
async def get_guardian_config():
    """Get configuration for System Guardian & Ambient Proactive Agent."""
    g_cfg = tools.proactive_system_guardian_config("status").get("guardian", {})
    p_cfg = tools.proactive_ambient_agent_config("status").get("proactive_config", {})
    return {
        "status": "success",
        "guardian": g_cfg,
        "proactive": p_cfg
    }


@app.post("/api/guardian/config")
async def update_guardian_config(payload: Dict[str, Any]):
    """Update guardian & proactive configurations."""
    if "guardian" in payload:
        g = payload["guardian"]
        tools.proactive_system_guardian_config(
            action="enable" if g.get("enabled", True) else "disable",
            cpu_threshold=g.get("cpu_threshold", 90),
            ram_threshold=g.get("ram_threshold", 85),
            disk_threshold=g.get("disk_threshold", 90),
            battery_critical=g.get("battery_critical", 10),
            auto_kill_ram_hogs=g.get("auto_kill_ram_hogs", False)
        )
    if "proactive" in payload:
        p = payload["proactive"]
        tools.proactive_ambient_agent_config(
            action="enable" if p.get("enabled", True) else "disable",
            min_hours_between_pings=p.get("min_hours_between_pings", 3),
            quiet_hours_start=p.get("quiet_hours_start", 23),
            quiet_hours_end=p.get("quiet_hours_end", 7)
        )
    return {"status": "success", "message": "Konfigurasi Guardian & Proaktif berhasil disimpan!"}


@app.post("/api/chat")
async def chat_with_agent(payload: Dict[str, Any]):
    """Send a message directly to the ALFA Agent and receive real response."""
    message = payload.get("message")
    if not message:
        raise HTTPException(status_code=400, detail="message is required")
        
    uid = get_primary_user_id()
    reply = await bot.run_agent_turn(user_id=uid, user_prompt=message, chat_id=uid)
    return {
        "status": "success",
        "reply": reply,
        "timestamp": datetime.now().isoformat()
    }


# ==================== GOOGLE DRIVE & GOOGLE CLOUD SUITE ENDPOINTS ====================

@app.get("/api/gdrive/status")
async def gdrive_status_endpoint():
    """Check status of Google Drive integration."""
    try:
        res = tools.gdrive_status()
        cred_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gdrive_credentials.json")
        has_file = os.path.exists(cred_file)
        
        account_email = ""
        project_id = ""
        if has_file:
            try:
                with open(cred_file, "r", encoding="utf-8") as f:
                    cdata = json.load(f)
                    account_email = cdata.get("client_email", "")
                    project_id = cdata.get("project_id", "")
            except Exception:
                pass
                
        # Prefer the ACTIVE credential's identity (OAuth account if logged in)
        active_email = (res.get("user") or {}).get("emailAddress", "")
        return {
            "status": "success",
            "connected": res.get("connected", False),
            "auth_mode": res.get("auth_mode", ""),
            "client_email": active_email or account_email,
            "project_id": project_id,
            "storage_quota": res.get("storage_quota", {}),
            "default_folder_id": res.get("default_folder_id", "1WTQuU2lbAQy438Whnhtn95jld-1d17lE"),
            "default_folder_name": res.get("default_folder_name", "alfa agent"),
            "default_folder_url": res.get("default_folder_url", "https://drive.google.com/drive/folders/1WTQuU2lbAQy438Whnhtn95jld-1d17lE"),
            "error": res.get("message", "") if not res.get("connected") else ""
        }
    except Exception as e:
        return {"status": "error", "connected": False, "message": str(e)}


@app.post("/api/gdrive/folder")
async def gdrive_set_default_folder(payload: Dict[str, Any]):
    """Set default Google Drive folder ID and name."""
    folder_id = payload.get("folder_id", "").strip()
    folder_name = payload.get("folder_name", "alfa agent").strip()
    
    if not folder_id:
        raise HTTPException(status_code=400, detail="folder_id wajib diisi.")
        
    with database.get_sync_db() as conn:
        conn.execute(
            "INSERT INTO system_settings (key, value) VALUES ('gdrive_default_folder_id', ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (folder_id,)
        )
        conn.execute(
            "INSERT INTO system_settings (key, value) VALUES ('gdrive_default_folder_name', ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (folder_name,)
        )
        conn.execute(
            "INSERT INTO system_settings (key, value) VALUES ('gdrive_default_folder_url', ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (f"https://drive.google.com/drive/folders/{folder_id}",)
        )
        
    return {
        "status": "success",
        "message": f"Folder default Google Drive berhasil disetel ke '{folder_name}' ({folder_id})",
        "folder_id": folder_id,
        "folder_name": folder_name
    }


@app.post("/api/gdrive/credentials")
async def gdrive_save_credentials(
    file: Optional[UploadFile] = File(None),
    raw_json: Optional[str] = Form(None)
):
    """Upload Service Account JSON file or paste raw JSON for Google Drive / Google Cloud."""
    cred_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gdrive_credentials.json")
    content = ""
    
    if file:
        content_bytes = await file.read()
        content = content_bytes.decode("utf-8")
    elif raw_json:
        content = raw_json.strip()
    else:
        raise HTTPException(status_code=400, detail="File JSON atau teks JSON Service Account wajib disediakan.")
        
    try:
        data = json.loads(content)
        if "type" not in data or data.get("type") != "service_account":
            if "client_email" not in data:
                return {"status": "error", "message": "File JSON bukan merupakan Service Account Key yang valid dari Google Cloud Console."}
                
        with open(cred_file, "w", encoding="utf-8") as f:
            f.write(content)
            
        with database.get_sync_db() as conn:
            conn.execute(
                "INSERT INTO system_settings (key, value) VALUES ('gdrive_credentials_json', ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (content,)
            )
            
        # Test connection immediately
        test_res = tools.gdrive_status()
        return {
            "status": "success",
            "message": "Kredensial Service Account Google Cloud berhasil disimpan dan diverifikasi!",
            "client_email": data.get("client_email", ""),
            "project_id": data.get("project_id", ""),
            "connected": test_res.get("connected", False)
        }
    except Exception as e:
        return {"status": "error", "message": f"Gagal memproses kredensial Google Cloud: {str(e)}"}


@app.delete("/api/gdrive/credentials")
async def gdrive_delete_credentials():
    """Remove stored Google Drive credentials."""
    cred_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gdrive_credentials.json")
    if os.path.exists(cred_file):
        os.remove(cred_file)
    with database.get_sync_db() as conn:
        conn.execute("DELETE FROM system_settings WHERE key = 'gdrive_credentials_json'")
    return {"status": "success", "message": "Kredensial Google Drive berhasil dihapus."}


@app.get("/api/gdrive/oauth/secret-check")
async def gdrive_oauth_secret_check():
    """Check whether the OAuth client secret exists AND is the right kind."""
    import json as _json
    secret_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gdrive_oauth_client_secret.json")
    result = {
        "status": "success",
        "exists": os.path.exists(secret_path),
        "expected_path": secret_path,
        "kind": "",
    }
    if result["exists"]:
        try:
            with open(secret_path, "r", encoding="utf-8") as f:
                probe = _json.load(f)
            if isinstance(probe, dict) and ("installed" in probe or "web" in probe):
                result["kind"] = "oauth_client"
            elif probe.get("type") == "service_account" or "private_key" in probe:
                # Common mistake: renamed service-account key instead of OAuth client ID
                result["kind"] = "service_account"
                result["exists"] = False
        except Exception:
            result["kind"] = "invalid_json"
            result["exists"] = False
    return result


@app.post("/api/gdrive/oauth/start")
async def gdrive_oauth_start():
    """Start the OAuth login flow. Opens a browser on this machine; waits for
    the user's consent, then stores a refreshable token (uploads then use the
    user's own Drive quota instead of the quota-less service account)."""
    import asyncio
    try:
        res = await asyncio.wait_for(
            asyncio.to_thread(tools.gdrive_oauth_login),
            timeout=330,
        )
        return res
    except asyncio.TimeoutError:
        return {"status": "error", "message": "Waktu login habis (5 menit) tanpa konfirmasi dari browser."}
    except Exception as oauth_err:
        return {"status": "error", "message": f"OAuth error: {str(oauth_err)}"}


@app.post("/api/gdrive/oauth/logout")
async def gdrive_oauth_logout_endpoint():
    """Remove OAuth tokens and fall back to service-account auth."""
    return tools.gdrive_oauth_logout()


@app.get("/api/gdrive/files")
async def gdrive_list_files_endpoint(folder_id: str = "", query: str = "", limit: int = 30):
    """List and search files in Google Drive."""
    return tools.gdrive_list_files(folder_id=folder_id, query=query, limit=limit)


@app.post("/api/gdrive/upload")
async def gdrive_upload_endpoint(
    file: Optional[UploadFile] = File(None),
    filepath: Optional[str] = Form(None),
    folder_id: Optional[str] = Form("")
):
    """Upload a file to Google Drive (either from direct browser upload or existing server path)."""
    if file:
        upload_dir = tools.get_pdf_output_dir("Uploads")
        safe_name = os.path.basename(file.filename or "upload.bin") or "upload.bin"
        target_path = os.path.join(upload_dir, safe_name)
        with open(target_path, "wb") as f:
            f.write(await file.read())
        return tools.gdrive_upload_file(filepath=target_path, folder_id=folder_id or "")
    elif filepath:
        return tools.gdrive_upload_file(filepath=filepath, folder_id=folder_id or "")
    else:
        raise HTTPException(status_code=400, detail="File atau path file wajib ditentukan.")


@app.post("/api/gdrive/create-folder")
async def gdrive_create_folder_endpoint(payload: Dict[str, Any]):
    """Create a folder in Google Drive."""
    folder_name = payload.get("name")
    parent_id = payload.get("parent_id", "")
    if not folder_name:
        raise HTTPException(status_code=400, detail="Nama folder wajib diisi.")
    return tools.gdrive_create_folder(folder_name=folder_name, parent_folder_id=parent_id)


@app.post("/api/gdrive/sync-brain")
async def gdrive_sync_brain_endpoint(payload: Dict[str, Any] = None):
    """Sync Google Drive documents to Neural Vector Brain."""
    folder_id = (payload or {}).get("folder_id", "")
    limit = safe_int((payload or {}).get("limit", 10), 10, minimum=1, maximum=100)
    return tools.gdrive_sync_to_second_brain(folder_id=folder_id, limit=limit)


# --- Multi-Provider API Key Vault Endpoints ---
@app.get("/api/keys")
async def get_api_keys():
    """List all API keys with masked values."""
    keys = database.list_api_keys_sync()
    return {"status": "success", "total": len(keys), "keys": keys}


@app.get("/api/keys/usage")
async def get_api_keys_usage(hours: int = 24):
    """Realtime token-usage summary per API key/provider for the dashboard."""
    hours = safe_int(hours, 24, minimum=1, maximum=720)
    keys = database.list_api_keys_sync()
    key_names = {k["id"]: k["name"] for k in keys}
    summary = database.get_api_usage_summary_sync(hours=hours)
    # Attach human-readable vault key names where ids match
    for row in summary.get("per_key", []):
        row["key_name"] = key_names.get(row.get("key_id")) or row.get("key_label") or "(env)"
    return {"status": "success", **summary}


@app.post("/api/keys")
async def add_api_key_endpoint(payload: Dict[str, Any]):
    """Add a new API key to the vault."""
    name = payload.get("name")
    provider = payload.get("provider", "gemini")
    api_key = payload.get("api_key")
    default_model = payload.get("default_model", "gemini-2.5-flash")
    base_url = payload.get("base_url", "")
    set_active = payload.get("set_active", True)
    
    if not api_key:
        raise HTTPException(status_code=400, detail="api_key is required")
        
    res = database.add_api_key_sync(
        name=name or f"{provider.capitalize()} Key",
        provider=provider,
        api_key=api_key,
        default_model=default_model,
        base_url=base_url,
        set_active=set_active
    )
    return res


@app.post("/api/keys/{key_id}/activate")
async def activate_api_key_endpoint(key_id: int):
    """Set an API key as active."""
    res = database.activate_api_key_sync(key_id)
    return res


@app.delete("/api/keys/{key_id}")
async def delete_api_key_endpoint(key_id: int):
    """Delete an API key."""
    res = database.delete_api_key_sync(key_id)
    return res


@app.post("/api/keys/{key_id}/test")
async def test_api_key_endpoint(key_id: int):
    """Test ping connection for a stored API key."""
    with database.get_sync_db() as conn:
        row = conn.execute("SELECT * FROM api_keys WHERE id = ?", (key_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="API Key tidak ditemukan")
        key_data = dict(row)

    import swarm_engine
    dummy_agent = {
        "name": f"Tester-{key_data['provider']}",
        "provider": key_data["provider"],
        "model": key_data["default_model"],
        "api_key_id": key_id
    }
    start_t = time.time()
    resp = await swarm_engine.generate_agent_response(
        agent=dummy_agent,
        prompt="Katakan 'Koneksi Berhasil' dalam 3 kata.",
        system_instruction="Kamu adalah modul health checker. Jawab dengan sangat singkat."
    )
    duration_ms = round((time.time() - start_t) * 1000, 1)
    is_error = "[Error:" in resp or "Gagal memanggil" in resp

    return {
        "status": "error" if is_error else "success",
        "key_id": key_id,
        "provider": key_data["provider"],
        "model": key_data["default_model"],
        "duration_ms": duration_ms,
        "response": resp
    }


PROVIDER_MODELS = {
    "antigravity": [
        {"id": "gemini-3.6-flash", "name": "Gemini 3.6 Flash (Terbaru - Medium Thinking)", "category": "Antigravity OAuth", "pricing": "free_oauth", "pricing_label": "🟢 GRATIS (Kuota Antigravity)"},
        {"id": "gemini-3.5-flash", "name": "Gemini 3.5 Flash (Cepat - Default Antigravity)", "category": "Antigravity OAuth", "pricing": "free_oauth", "pricing_label": "🟢 GRATIS (Kuota Antigravity)"},
        {"id": "gemini-3-flash", "name": "Gemini 3 Flash", "category": "Antigravity OAuth", "pricing": "free_oauth", "pricing_label": "🟢 GRATIS (Kuota Antigravity)"},
        {"id": "gemini-3.1-pro", "name": "Gemini 3.1 Pro (Penalaran Kompleks)", "category": "Antigravity Pro Models", "pricing": "free_oauth", "pricing_label": "🟢 GRATIS (Kuota Antigravity)"},
        {"id": "gemini-2.5-pro", "name": "Gemini 2.5 Pro", "category": "Antigravity Pro Models", "pricing": "free_oauth", "pricing_label": "🟢 GRATIS"},
        {"id": "gemini-2.5-flash", "name": "Gemini 2.5 Flash", "category": "Antigravity OAuth", "pricing": "free_oauth", "pricing_label": "🟢 GRATIS"},
        {"id": "claude-sonnet-4.6", "name": "Claude Sonnet 4.6 (via Antigravity)", "category": "Claude via Antigravity", "pricing": "free_oauth", "pricing_label": "🟢 GRATIS"},
        {"id": "claude-opus-4.6", "name": "Claude Opus 4.6 Thinking (via Antigravity)", "category": "Claude via Antigravity", "pricing": "free_oauth", "pricing_label": "🟢 GRATIS"},
        {"id": "gpt-oss-120b", "name": "GPT-OSS 120B Medium (OpenAI via Antigravity)", "category": "GPT-OSS via Antigravity", "pricing": "free_oauth", "pricing_label": "🟢 GRATIS (Kuota Antigravity)"},
    ],
    "nvidia": [
        # --- NVIDIA Nemotron Suite ---
        {"id": "nvidia/llama-3.1-nemotron-70b-instruct", "name": "NVIDIA Nemotron 70B Ultra Instruct (Model Unggulan NVIDIA)", "category": "NVIDIA Nemotron Ultra", "pricing": "free_credits", "pricing_label": "🟢 GRATIS (1000 NIM Credits)"},
        {"id": "nvidia/nemotron-4-340b-instruct", "name": "NVIDIA Nemotron-4 340B Instruct (Model Raksasa 340B)", "category": "NVIDIA Nemotron Ultra", "pricing": "free_credits", "pricing_label": "🟢 GRATIS (1000 NIM Credits)"},
        {"id": "nvidia/llama-3.1-nemotron-51b-instruct", "name": "NVIDIA Nemotron 51B Instruct (Efisiensi Tinggi)", "category": "NVIDIA Nemotron Ultra", "pricing": "free_credits", "pricing_label": "🟢 GRATIS (1000 NIM Credits)"},
        {"id": "nvidia/nemotron-mini-4b-instruct", "name": "NVIDIA Nemotron Mini 4B Instruct (Ringan & Cepat)", "category": "NVIDIA Nemotron Ultra", "pricing": "free_credits", "pricing_label": "🟢 GRATIS (1000 NIM Credits)"},
        {"id": "nvidia/mistral-nemo-minitron-8b-8k-instruct", "name": "NVIDIA Minitron 8B 8k Instruct (Kompak & Cerdas)", "category": "NVIDIA Nemotron Ultra", "pricing": "free_credits", "pricing_label": "🟢 GRATIS (1000 NIM Credits)"},
        {"id": "nvidia/llama-3.2-11b-vision-instruct", "name": "NVIDIA Llama 3.2 11B Vision Instruct (Multimodal)", "category": "NVIDIA Vision", "pricing": "free_credits", "pricing_label": "🟢 GRATIS (1000 NIM Credits)"},
        {"id": "nvidia/llama-3.2-90b-vision-instruct", "name": "NVIDIA Llama 3.2 90B Vision Instruct (Vision Pro)", "category": "NVIDIA Vision", "pricing": "free_credits", "pricing_label": "🟢 GRATIS (1000 NIM Credits)"},
        {"id": "nvidia/llama-3.2-1b-instruct", "name": "NVIDIA Llama 3.2 1B Instruct (Ultra Ringan)", "category": "NVIDIA Nemotron Ultra", "pricing": "free_credits", "pricing_label": "🟢 GRATIS (1000 NIM Credits)"},
        {"id": "nvidia/llama-3.2-3b-instruct", "name": "NVIDIA Llama 3.2 3B Instruct (Ringan)", "category": "NVIDIA Nemotron Ultra", "pricing": "free_credits", "pricing_label": "🟢 GRATIS (1000 NIM Credits)"},

        # --- DeepSeek on NVIDIA ---
        {"id": "deepseek-ai/deepseek-r1", "name": "DeepSeek R1 671B (Penalaran & Logic Terkuat Dunia)", "category": "DeepSeek Reasoning", "pricing": "free_credits", "pricing_label": "🟢 GRATIS (1000 NIM Credits)"},
        {"id": "deepseek-ai/deepseek-v3", "name": "DeepSeek V3 671B (MoE Cerdas & Sangat Cepat)", "category": "DeepSeek General", "pricing": "free_credits", "pricing_label": "🟢 GRATIS (1000 NIM Credits)"},
        {"id": "deepseek-ai/deepseek-r1-distill-qwen-32b", "name": "DeepSeek R1 Distill Qwen 32B (Reasoning Cepat)", "category": "DeepSeek Reasoning", "pricing": "free_credits", "pricing_label": "🟢 GRATIS (1000 NIM Credits)"},
        {"id": "deepseek-ai/deepseek-r1-distill-qwen-14b", "name": "DeepSeek R1 Distill Qwen 14B (Reasoning Ringan)", "category": "DeepSeek Reasoning", "pricing": "free_credits", "pricing_label": "🟢 GRATIS (1000 NIM Credits)"},
        {"id": "deepseek-ai/deepseek-r1-distill-llama-70b", "name": "DeepSeek R1 Distill Llama 70B (Reasoning Kuat)", "category": "DeepSeek Reasoning", "pricing": "free_credits", "pricing_label": "🟢 GRATIS (1000 NIM Credits)"},
        {"id": "deepseek-ai/deepseek-r1-distill-llama-8b", "name": "DeepSeek R1 Distill Llama 8B (Kilat)", "category": "DeepSeek Reasoning", "pricing": "free_credits", "pricing_label": "🟢 GRATIS (1000 NIM Credits)"},

        # --- Meta Llama on NVIDIA ---
        {"id": "meta/llama-3.3-70b-instruct", "name": "Meta Llama 3.3 70B Instruct (Rekomendasi Utama)", "category": "Meta Flagship", "pricing": "free_credits", "pricing_label": "🟢 GRATIS (1000 NIM Credits)"},
        {"id": "meta/llama-3.1-405b-instruct", "name": "Meta Llama 3.1 405B Instruct (Model Flagship Raksasa)", "category": "Meta Flagship", "pricing": "free_credits", "pricing_label": "🟢 GRATIS (1000 NIM Credits)"},
        {"id": "meta/llama-3.1-70b-instruct", "name": "Meta Llama 3.1 70B Instruct", "category": "Meta General", "pricing": "free_credits", "pricing_label": "🟢 GRATIS (1000 NIM Credits)"},
        {"id": "meta/llama-3.1-8b-instruct", "name": "Meta Llama 3.1 8B Instruct (Super Cepat)", "category": "Meta Fast", "pricing": "free_credits", "pricing_label": "🟢 GRATIS (1000 NIM Credits)"},

        # --- Qwen on NVIDIA ---
        {"id": "qwen/qwen2.5-coder-32b-instruct", "name": "Qwen 2.5 Coder 32B (Spesialis Kode & Programming)", "category": "Qwen Coding", "pricing": "free_credits", "pricing_label": "🟢 GRATIS (1000 NIM Credits)"},
        {"id": "qwen/qwen2.5-coder-7b-instruct", "name": "Qwen 2.5 Coder 7B (Coding Cepat)", "category": "Qwen Coding", "pricing": "free_credits", "pricing_label": "🟢 GRATIS (1000 NIM Credits)"},
        {"id": "qwen/qwen2.5-72b-instruct", "name": "Qwen 2.5 72B Instruct (General Terkuat)", "category": "Qwen General", "pricing": "free_credits", "pricing_label": "🟢 GRATIS (1000 NIM Credits)"},
        {"id": "qwen/qwen2.5-32b-instruct", "name": "Qwen 2.5 32B Instruct", "category": "Qwen General", "pricing": "free_credits", "pricing_label": "🟢 GRATIS (1000 NIM Credits)"},
        {"id": "qwen/qwen2.5-14b-instruct", "name": "Qwen 2.5 14B Instruct", "category": "Qwen General", "pricing": "free_credits", "pricing_label": "🟢 GRATIS (1000 NIM Credits)"},
        {"id": "qwen/qwen2.5-7b-instruct", "name": "Qwen 2.5 7B Instruct", "category": "Qwen Fast", "pricing": "free_credits", "pricing_label": "🟢 GRATIS (1000 NIM Credits)"},

        # --- Mistral on NVIDIA ---
        {"id": "mistralai/mixtral-8x22b-instruct-v0.1", "name": "Mistral Mixtral 8x22B Instruct (MoE Kuat)", "category": "Mistral MoE", "pricing": "free_credits", "pricing_label": "🟢 GRATIS (1000 NIM Credits)"},
        {"id": "mistralai/mixtral-8x7b-instruct-v0.1", "name": "Mistral Mixtral 8x7B Instruct", "category": "Mistral MoE", "pricing": "free_credits", "pricing_label": "🟢 GRATIS (1000 NIM Credits)"},
        {"id": "mistralai/mistral-large-2-instruct", "name": "Mistral Large 2 Instruct (Flagship)", "category": "Mistral Flagship", "pricing": "free_credits", "pricing_label": "🟢 GRATIS (1000 NIM Credits)"},
        {"id": "mistralai/mistral-nemo-12b-instruct", "name": "Mistral NeMo 12B Instruct", "category": "Mistral General", "pricing": "free_credits", "pricing_label": "🟢 GRATIS (1000 NIM Credits)"},
        {"id": "mistralai/codestral-22b-instruct-v0.1", "name": "Mistral Codestral 22B (Coding)", "category": "Mistral Coding", "pricing": "free_credits", "pricing_label": "🟢 GRATIS (1000 NIM Credits)"},

        # --- Microsoft & Google on NVIDIA ---
        {"id": "microsoft/phi-4", "name": "Microsoft Phi 4 (14B Penalaran Akurat)", "category": "Microsoft Phi", "pricing": "free_credits", "pricing_label": "🟢 GRATIS (1000 NIM Credits)"},
        {"id": "microsoft/phi-3.5-moe-instruct", "name": "Microsoft Phi 3.5 MoE Instruct", "category": "Microsoft Phi", "pricing": "free_credits", "pricing_label": "🟢 GRATIS (1000 NIM Credits)"},
        {"id": "microsoft/phi-3.5-mini-instruct", "name": "Microsoft Phi 3.5 Mini Instruct", "category": "Microsoft Phi", "pricing": "free_credits", "pricing_label": "🟢 GRATIS (1000 NIM Credits)"},
        {"id": "google/gemma-2-27b-it", "name": "Google Gemma 2 27B IT", "category": "Google Gemma", "pricing": "free_credits", "pricing_label": "🟢 GRATIS (1000 NIM Credits)"},
        {"id": "google/gemma-2-9b-it", "name": "Google Gemma 2 9B IT", "category": "Google Gemma", "pricing": "free_credits", "pricing_label": "🟢 GRATIS (1000 NIM Credits)"}
    ],
    "deepseek": [
        {"id": "deepseek-chat", "name": "DeepSeek-V3 671B MoE (Sangat Cerdas & Cepat)", "category": "DeepSeek Official", "pricing": "free_tier", "pricing_label": "🟢 SANGAT MURAH ($0.14/1M)"},
        {"id": "deepseek-reasoner", "name": "DeepSeek-R1 671B (Penalaran & Logic Terkuat)", "category": "DeepSeek Official", "pricing": "free_tier", "pricing_label": "🟢 SANGAT MURAH ($0.55/1M)"},
        {"id": "deepseek-coder", "name": "DeepSeek Coder 33B (Spesialis Kode)", "category": "DeepSeek Official", "pricing": "free_tier", "pricing_label": "🟢 SANGAT MURAH ($0.14/1M)"}
    ],
    "minimax": [
        {"id": "MiniMax-Text-01", "name": "MiniMax-01 Flagship (Konteks Raksasa 4 Juta Token)", "category": "MiniMax AI", "pricing": "free_tier", "pricing_label": "🟢 FREE TRIAL / Murah"},
        {"id": "abab6.5s-chat", "name": "MiniMax abab6.5s (Ultra-Fast MoE)", "category": "MiniMax AI", "pricing": "free_tier", "pricing_label": "🟢 FREE TRIAL / Murah"},
        {"id": "abab6.5g-chat", "name": "MiniMax abab6.5g (General Knowledge)", "category": "MiniMax AI", "pricing": "paid", "pricing_label": "💎 BERBAYAR"},
        {"id": "abab6.5t-chat", "name": "MiniMax abab6.5t (Long Context)", "category": "MiniMax AI", "pricing": "paid", "pricing_label": "💎 BERBAYAR"}
    ],
    "moonshot": [
        {"id": "moonshot-v1-8k", "name": "Moonshot Kimi v1 8K (Cerdas & Cepat)", "category": "Moonshot Kimi", "pricing": "free_tier", "pricing_label": "🟢 FREE TRIAL (15 RMB Bonus)"},
        {"id": "moonshot-v1-32k", "name": "Moonshot Kimi v1 32K", "category": "Moonshot Kimi", "pricing": "free_tier", "pricing_label": "🟢 FREE TRIAL"},
        {"id": "moonshot-v1-128k", "name": "Moonshot Kimi v1 128K (Konteks Panjang)", "category": "Moonshot Kimi", "pricing": "paid", "pricing_label": "💎 BERBAYAR"}
    ],
    "qwen": [
        {"id": "qwen-max", "name": "Qwen 2.5 Max (Flagship Alibaba Cloud Terkuat)", "category": "Alibaba Qwen", "pricing": "free_tier", "pricing_label": "🟢 FREE TRIAL / Token"},
        {"id": "qwen-plus", "name": "Qwen 2.5 Plus (Keseimbangan Sempurna)", "category": "Alibaba Qwen", "pricing": "free_tier", "pricing_label": "🟢 SANGAT MURAH"},
        {"id": "qwen-turbo", "name": "Qwen 2.5 Turbo (Kilat & Ringan)", "category": "Alibaba Qwen", "pricing": "free_tier", "pricing_label": "🟢 SANGAT MURAH"},
        {"id": "qwen2.5-coder-32b-instruct", "name": "Qwen 2.5 Coder 32B (Spesialis Kode)", "category": "Alibaba Qwen", "pricing": "free_tier", "pricing_label": "🟢 FREE TRIAL"}
    ],
    "gemini": [
        # --- Gemini 3.7 / 3.6 (Terbaru) ---
        {"id": "gemini-3.7-flash", "name": "Gemini 3.7 Flash (Generasi Termbaru)", "category": "Gemini Terbaru", "pricing": "free_tier", "pricing_label": "🟢 Aktif"},
        {"id": "gemini-3.6-flash", "name": "Gemini 3.6 Flash", "category": "Gemini Terbaru", "pricing": "free_tier", "pricing_label": "🟢 Aktif"},
        # --- Gemini 3.5 ---
        {"id": "gemini-3.5-flash", "name": "Gemini 3.5 Flash (Cepat & Stabil)", "category": "Gemini 3.5", "pricing": "free_tier", "pricing_label": "🟢 Aktif"},
        {"id": "gemini-3.5-flash-lite", "name": "Gemini 3.5 Flash Lite (Ultra Ringan)", "category": "Gemini 3.5", "pricing": "free_tier", "pricing_label": "🟢 Aktif"},
        # --- Gemini 3.1 Pro & Flash ---
        {"id": "gemini-3.1-pro-preview", "name": "Gemini 3.1 Pro Preview (Penalaran Kompleks)", "category": "Gemini 3.1 Pro", "pricing": "free_tier", "pricing_label": "🟢 Aktif"},
        {"id": "gemini-3.1-flash-lite", "name": "Gemini 3.1 Flash Lite", "category": "Gemini 3.1", "pricing": "free_tier", "pricing_label": "🟢 Aktif"},
        {"id": "gemini-3-flash-preview", "name": "Gemini 3 Flash Preview", "category": "Gemini 3.1", "pricing": "free_tier", "pricing_label": "🟢 Aktif"},
        {"id": "gemini-omni-flash-preview", "name": "Gemini Omni Flash Preview (Multimodal)", "category": "Gemini Terbaru", "pricing": "free_tier", "pricing_label": "🟢 Aktif"},
        # --- Alias Selalu-Terbaru ---
        {"id": "gemini-flash-latest", "name": "Gemini Flash Latest (Otomatis Versi Termbaru)", "category": "Latest Alias", "pricing": "free_tier", "pricing_label": "🟢 Aktif"},
        {"id": "gemini-flash-lite-latest", "name": "Gemini Flash Lite Latest", "category": "Latest Alias", "pricing": "free_tier", "pricing_label": "🟢 Aktif"},
        {"id": "gemini-pro-latest", "name": "Gemini Pro Latest (Flagship)", "category": "Latest Alias", "pricing": "free_tier", "pricing_label": "🟢 Aktif"},
        # --- Gemini 2.5 ---
        {"id": "gemini-2.5-pro", "name": "Gemini 2.5 Pro", "category": "Gemini 2.5", "pricing": "free_tier", "pricing_label": "🟢 Aktif"},
        {"id": "gemini-2.5-flash", "name": "Gemini 2.5 Flash", "category": "Gemini 2.5", "pricing": "free_tier", "pricing_label": "🟢 Aktif"},
        {"id": "gemini-2.5-flash-lite", "name": "Gemini 2.5 Flash Lite", "category": "Gemini 2.5", "pricing": "free_tier", "pricing_label": "🟢 Aktif"},
        # --- Image Generation ---
        {"id": "nano-banana-pro-preview", "name": "Nano Banana Pro (Image Gen Flagship)", "category": "Image Generation", "pricing": "free_tier", "pricing_label": "🟢 Aktif"},
        {"id": "gemini-3-pro-image", "name": "Gemini 3 Pro Image", "category": "Image Generation", "pricing": "free_tier", "pricing_label": "🟢 Aktif"},
        {"id": "gemini-3.1-flash-image", "name": "Gemini 3.1 Flash Image", "category": "Image Generation", "pricing": "free_tier", "pricing_label": "🟢 Aktif"},
        {"id": "gemini-2.5-flash-image", "name": "Gemini 2.5 Flash Image", "category": "Image Generation", "pricing": "free_tier", "pricing_label": "🟢 Aktif"},
        # --- Gemma Open Model ---
        {"id": "gemma-4-31b-it", "name": "Gemma 4 31B IT (Open Model)", "category": "Gemma Open", "pricing": "free_tier", "pricing_label": "🟢 Aktif"},
        {"id": "gemma-4-26b-a4b-it", "name": "Gemma 4 26B A4B IT (Open Model Efisien)", "category": "Gemma Open", "pricing": "free_tier", "pricing_label": "🟢 Aktif"},
    ],

    "groq": [
        {"id": "llama-3.3-70b-versatile", "name": "Llama 3.3 70B Versatile (Kecepatan Kilat 300+ T/s)", "category": "Groq Ultra-Fast", "pricing": "free", "pricing_label": "🟢 100% GRATIS (Groq Cloud)"},
        {"id": "llama-3.1-8b-instant", "name": "Llama 3.1 8B Instant (Super Kilat 600+ T/s)", "category": "Groq Ultra-Fast", "pricing": "free", "pricing_label": "🟢 100% GRATIS (Groq Cloud)"},
        {"id": "deepseek-r1-distill-llama-70b", "name": "DeepSeek R1 Distill Llama 70B (Reasoning Cepat)", "category": "Groq Reasoning", "pricing": "free", "pricing_label": "🟢 100% GRATIS (Groq Cloud)"},
        {"id": "deepseek-r1-distill-qwen-32b", "name": "DeepSeek R1 Distill Qwen 32B (Reasoning Cepat)", "category": "Groq Reasoning", "pricing": "free", "pricing_label": "🟢 100% GRATIS (Groq Cloud)"},
        {"id": "mixtral-8x7b-32768", "name": "Mixtral 8x7B 32k Konteks", "category": "Groq MoE", "pricing": "free", "pricing_label": "🟢 100% GRATIS (Groq Cloud)"},
        {"id": "gemma2-9b-it", "name": "Google Gemma 2 9B IT (via Groq)", "category": "Groq Google", "pricing": "free", "pricing_label": "🟢 100% GRATIS (Groq Cloud)"},
        {"id": "qwen-qwq-32b-preview", "name": "Qwen QwQ 32B Reasoning Preview", "category": "Groq Reasoning", "pricing": "free", "pricing_label": "🟢 100% GRATIS (Groq Cloud)"}
    ],
    "openrouter": [
        {"id": "google/gemini-2.0-flash-exp:free", "name": "Gemini 2.0 Flash Exp (Endpoint Gratis)", "category": "OpenRouter Free", "pricing": "free", "pricing_label": "🟢 100% GRATIS (Tanpa Saldo)"},
        {"id": "meta-llama/llama-3.3-70b-instruct:free", "name": "Llama 3.3 70B Instruct (Endpoint Gratis)", "category": "OpenRouter Free", "pricing": "free", "pricing_label": "🟢 100% GRATIS (Tanpa Saldo)"},
        {"id": "deepseek/deepseek-r1:free", "name": "DeepSeek R1 (Endpoint Gratis)", "category": "OpenRouter Free", "pricing": "free", "pricing_label": "🟢 100% GRATIS (Tanpa Saldo)"},
        {"id": "minimax/minimax-01", "name": "MiniMax-01 4M Context (via OpenRouter)", "category": "OpenRouter Paid", "pricing": "paid", "pricing_label": "💎 BERBAYAR ($0.20/1M)"},
        {"id": "deepseek/deepseek-r1", "name": "DeepSeek R1 Full 671B (via OpenRouter)", "category": "OpenRouter Paid", "pricing": "paid", "pricing_label": "💎 BERBAYAR ($0.55/1M)"},
        {"id": "deepseek/deepseek-chat", "name": "DeepSeek V3 Full (via OpenRouter)", "category": "OpenRouter Paid", "pricing": "paid", "pricing_label": "💎 BERBAYAR ($0.14/1M)"},
        {"id": "anthropic/claude-3.5-sonnet", "name": "Claude 3.5 Sonnet (via OpenRouter)", "category": "OpenRouter Paid", "pricing": "paid", "pricing_label": "💎 BERBAYAR (Pay-per-token)"},
        {"id": "openai/gpt-4o", "name": "GPT-4o (via OpenRouter)", "category": "OpenRouter Paid", "pricing": "paid", "pricing_label": "💎 BERBAYAR (Pay-per-token)"}
    ],
    "openai": [
        {"id": "gpt-4o-mini", "name": "GPT-4o Mini (Sangat Murah, Cepat & Cerdas)", "category": "OpenAI Fast", "pricing": "paid", "pricing_label": "💎 BERBAYAR (Murah ~$0.15/1M)"},
        {"id": "gpt-4o", "name": "GPT-4o (Omni Flagship)", "category": "OpenAI Flagship", "pricing": "paid", "pricing_label": "💎 BERBAYAR ($2.50/1M)"},
        {"id": "o3-mini", "name": "OpenAI o3 Mini (Reasoning Model Terbaru)", "category": "OpenAI Reasoning", "pricing": "paid", "pricing_label": "💎 BERBAYAR ($1.10/1M)"},
        {"id": "o1-mini", "name": "OpenAI o1 Mini (Math & Code Reasoning)", "category": "OpenAI Reasoning", "pricing": "paid", "pricing_label": "💎 BERBAYAR ($1.10/1M)"},
        {"id": "o1", "name": "OpenAI o1 (Full Reasoning Flagship)", "category": "OpenAI Reasoning", "pricing": "paid", "pricing_label": "💎 BERBAYAR ($15/1M)"},
        {"id": "gpt-4-turbo", "name": "GPT-4 Turbo", "category": "OpenAI Flagship", "pricing": "paid", "pricing_label": "💎 BERBAYAR ($10/1M)"}
    ],
    "anthropic": [
        {"id": "claude-3-5-haiku-20241022", "name": "Claude 3.5 Haiku (Ringan, Murah & Kilat)", "category": "Anthropic Haiku", "pricing": "paid", "pricing_label": "💎 BERBAYAR (Murah ~$0.80/1M)"},
        {"id": "claude-3-5-sonnet-20241022", "name": "Claude 3.5 Sonnet v2 (Unggulan Coding & Writing)", "category": "Anthropic Sonnet", "pricing": "paid", "pricing_label": "💎 BERBAYAR ($3.00/1M)"},
        {"id": "claude-3-opus-20240229", "name": "Claude 3 Opus (Model Paling Kompleks)", "category": "Anthropic Opus", "pricing": "paid", "pricing_label": "💎 BERBAYAR ($15/1M)"}
    ],
    "9router": [
        {"id": "claude-3-5-sonnet", "name": "Claude 3.5 Sonnet (via 9Router Gateway)", "category": "9Router Gateway", "pricing": "free_tier", "pricing_label": "🟢 9ROUTER ROUTER"},
        {"id": "gpt-4o", "name": "GPT-4o (via 9Router Gateway)", "category": "9Router Gateway", "pricing": "free_tier", "pricing_label": "🟢 9ROUTER ROUTER"},
        {"id": "deepseek-reasoner", "name": "DeepSeek R1 (via 9Router Gateway)", "category": "9Router Gateway", "pricing": "free_tier", "pricing_label": "🟢 9ROUTER ROUTER"},
        {"id": "deepseek-chat", "name": "DeepSeek V3 (via 9Router Gateway)", "category": "9Router Gateway", "pricing": "free_tier", "pricing_label": "🟢 9ROUTER ROUTER"},
        {"id": "llama-3.3-70b", "name": "Llama 3.3 70B (via 9Router Gateway)", "category": "9Router Gateway", "pricing": "free_tier", "pricing_label": "🟢 9ROUTER ROUTER"},
        {"id": "gemini-2.0-flash", "name": "Gemini 2.0 Flash (via 9Router Gateway)", "category": "9Router Gateway", "pricing": "free_tier", "pricing_label": "🟢 9ROUTER ROUTER"},
        {"id": "qwen-2.5-coder-32b", "name": "Qwen 2.5 Coder 32B (via 9Router Gateway)", "category": "9Router Gateway", "pricing": "free_tier", "pricing_label": "🟢 9ROUTER ROUTER"},
        {"id": "auto", "name": "Auto Intelligent Fallback (9Router Best Available)", "category": "9Router Gateway", "pricing": "free_tier", "pricing_label": "🟢 AUTO ROUTE"}
    ],
    "ollama": [
        {"id": "deepseek-r1", "name": "DeepSeek R1 (Lokal PC/Laptop)", "category": "Local Offline", "pricing": "free", "pricing_label": "🟢 100% GRATIS & OFFLINE"},
        {"id": "llama3.3", "name": "Llama 3.3 (Lokal PC/Laptop)", "category": "Local Offline", "pricing": "free", "pricing_label": "🟢 100% GRATIS & OFFLINE"},
        {"id": "llama3.1", "name": "Llama 3.1 (Lokal PC/Laptop)", "category": "Local Offline", "pricing": "free", "pricing_label": "🟢 100% GRATIS & OFFLINE"},
        {"id": "qwen2.5-coder", "name": "Qwen 2.5 Coder (Lokal PC/Laptop)", "category": "Local Offline", "pricing": "free", "pricing_label": "🟢 100% GRATIS & OFFLINE"},
        {"id": "mistral", "name": "Mistral 7B (Lokal PC/Laptop)", "category": "Local Offline", "pricing": "free", "pricing_label": "🟢 100% GRATIS & OFFLINE"},
        {"id": "gemma2", "name": "Google Gemma 2 (Lokal PC/Laptop)", "category": "Local Offline", "pricing": "free", "pricing_label": "🟢 100% GRATIS & OFFLINE"},
        {"id": "phi3", "name": "Microsoft Phi 3 (Lokal PC/Laptop)", "category": "Local Offline", "pricing": "free", "pricing_label": "🟢 100% GRATIS & OFFLINE"}
    ]
}


@app.get("/api/models")
async def get_available_models():
    """Get verified models list per provider with live discovery from NVIDIA & OpenRouter."""
    import httpx
    # 1. Attempt dynamic refresh from NVIDIA NIM
    try:
        async with httpx.AsyncClient(timeout=2.5) as client:
            r = await client.get("https://integrate.api.nvidia.com/v1/models")
            if r.status_code == 200:
                live_data = r.json().get("data", [])
                existing_ids = {m["id"] for m in PROVIDER_MODELS["nvidia"]}
                for item in live_data:
                    mid = item.get("id")
                    if mid and mid not in existing_ids:
                        cat = "NVIDIA Live Models"
                        if "nemotron" in mid:
                            cat = "NVIDIA Nemotron Ultra"
                        elif "llama" in mid:
                            cat = "Meta Llama on NVIDIA"
                        elif "mistral" in mid:
                            cat = "Mistral on NVIDIA"
                        elif "deepseek" in mid:
                            cat = "DeepSeek on NVIDIA"
                        elif "google" in mid or "gemma" in mid:
                            cat = "Google on NVIDIA"
                        
                        PROVIDER_MODELS["nvidia"].append({
                            "id": mid,
                            "name": f"{mid} (Live NVIDIA NIM)",
                            "category": cat,
                            "pricing": "free_credits",
                            "pricing_label": "🟢 GRATIS (1000 NIM Credits)"
                        })
    except Exception:
        pass

    # 2. Attempt dynamic refresh from OpenRouter
    try:
        async with httpx.AsyncClient(timeout=2.5) as client:
            r = await client.get("https://openrouter.ai/api/v1/models")
            if r.status_code == 200:
                live_or = r.json().get("data", [])
                existing_or_ids = {m["id"] for m in PROVIDER_MODELS["openrouter"]}
                for item in live_or:
                    mid = item.get("id")
                    mname = item.get("name", mid)
                    if mid and mid not in existing_or_ids:
                        is_free = ":free" in mid
                        PROVIDER_MODELS["openrouter"].append({
                            "id": mid,
                            "name": f"{mname} ({mid})",
                            "category": "OpenRouter Free" if is_free else "OpenRouter Live Catalog",
                            "pricing": "free" if is_free else "paid",
                            "pricing_label": "🟢 100% GRATIS" if is_free else "💎 BERBAYAR"
                        })
    except Exception:
        pass

    return {"status": "success", "providers": PROVIDER_MODELS}


@app.post("/api/keys/validate")
async def validate_raw_api_key(payload: Dict[str, Any]):
    """Test ping connection for unsaved raw credentials before saving."""
    provider = payload.get("provider", "gemini")
    api_key = payload.get("api_key", "").strip()
    model = payload.get("model", "").strip()
    base_url = payload.get("base_url", "").strip()
    
    if not api_key:
        raise HTTPException(status_code=400, detail="API Key wajib diisi untuk divalidasi")
        
    start_t = time.time()
    if provider in ["nvidia", "nim", "openai", "groq", "openrouter", "9router", "ollama", "deepseek", "minimax", "moonshot", "kimi", "qwen", "dashscope"]:
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
            
            target_model = model
            if not target_model:
                if provider in ["nvidia", "nim"]:
                    target_model = "nvidia/llama-3.1-nemotron-70b-instruct"
                elif provider == "deepseek":
                    target_model = "deepseek-chat"
                elif provider == "minimax":
                    target_model = "MiniMax-Text-01"
                elif provider in ["moonshot", "kimi"]:
                    target_model = "moonshot-v1-8k"
                elif provider in ["qwen", "dashscope"]:
                    target_model = "qwen-plus"
                elif provider == "groq":
                    target_model = "llama-3.3-70b-versatile"
                elif provider == "openrouter":
                    target_model = "deepseek/deepseek-r1:free"
                elif provider == "9router":
                    target_model = "auto"
                else:
                    target_model = "gpt-4o"

            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            if provider == "openrouter":
                headers["HTTP-Referer"] = "https://alfa-agent.local"
                headers["X-Title"] = "ALFA Swarm Validator"

            test_payload = {
                "model": target_model,
                "messages": [{"role": "user", "content": "Tes koneksi. Jawab: OK"}],
                "max_tokens": 10
            }
            async with httpx.AsyncClient(timeout=12.0) as client:
                res = await client.post(f"{url.rstrip('/')}/chat/completions", headers=headers, json=test_payload)
                duration_ms = round((time.time() - start_t) * 1000, 1)
                if res.status_code == 200:
                    return {"status": "success", "duration_ms": duration_ms, "message": f"Koneksi {provider.upper()} ({target_model}) Berhasil ({duration_ms}ms)!"}
                elif res.status_code == 404 and provider in ["nvidia", "nim"]:
                    return {
                        "status": "error",
                        "status_code": 404,
                        "duration_ms": duration_ms,
                        "message": f"Model '{target_model}' memerlukan izin khusus enterprise di NVIDIA NIM. Coba pilih model aktif 'nvidia/llama-3.1-nemotron-70b-instruct' atau 'meta/llama-3.3-70b-instruct' yang 100% aktif untuk akun Free NIM!"
                    }
                elif res.status_code == 401:
                    return {
                        "status": "error",
                        "status_code": 401,
                        "duration_ms": duration_ms,
                        "message": f"API Key {provider.upper()} tidak valid atau tidak memiliki izin akses (HTTP 401 Unauthorized)."
                    }
                else:
                    return {"status": "error", "status_code": res.status_code, "duration_ms": duration_ms, "message": f"HTTP {res.status_code}: {res.text[:200]}"}
        except Exception as e:
            return {"status": "error", "message": f"Error: {str(e)}"}
    else:
        # Gemini
        try:
            from google import genai
            from google.genai import types
            target_model = model or "gemini-3.5-flash-lite"
            client = genai.Client(api_key=api_key)
            await client.aio.models.generate_content(
                model=target_model,
                contents="Tes koneksi",
                config=types.GenerateContentConfig(max_output_tokens=10)
            )
            duration_ms = round((time.time() - start_t) * 1000, 1)
            return {"status": "success", "duration_ms": duration_ms, "message": f"Koneksi GEMINI ({target_model}) Berhasil ({duration_ms}ms)!"}
        except Exception as e:
            return {"status": "error", "message": f"Error: {str(e)}"}


# --- Autonomous AI Workforce & Custom Agent Endpoints ---
@app.get("/api/agents")
async def get_custom_agents():
    """List all custom agents in the workforce."""
    agents = database.list_custom_agents_sync()
    return {"status": "success", "total": len(agents), "agents": agents}


@app.post("/api/agents")
async def create_custom_agent(payload: Dict[str, Any]):
    """Create a new specialized AI agent."""
    name = payload.get("name")
    role = payload.get("role")
    persona = payload.get("persona", "")
    system_instruction = payload.get("system_instruction", "")
    provider = payload.get("provider", "gemini")
    model = payload.get("model", "gemini-2.5-flash")
    api_key_id = payload.get("api_key_id")
    avatar_emoji = payload.get("avatar_emoji", "🤖")
    color_theme = payload.get("color_theme", "cyan")
    
    if not name or not role:
        raise HTTPException(status_code=400, detail="name and role are required")
        
    res = database.add_custom_agent_sync(
        name=name,
        role=role,
        persona=persona or f"Spesialis {role}",
        system_instruction=system_instruction or f"Kamu adalah {name}, {role}.",
        provider=provider,
        model=model,
        api_key_id=api_key_id,
        avatar_emoji=avatar_emoji,
        color_theme=color_theme
    )
    return res


@app.put("/api/agents/{agent_id}")
async def update_custom_agent_endpoint(agent_id: int, payload: Dict[str, Any]):
    """Update custom agent configuration."""
    res = database.update_custom_agent_sync(agent_id, payload)
    return res


@app.delete("/api/agents/{agent_id}")
async def delete_custom_agent_endpoint(agent_id: int):
    """Delete a custom agent."""
    res = database.delete_custom_agent_sync(agent_id)
    return res


@app.post("/api/agents/{agent_id}/chat")
async def chat_with_custom_agent(agent_id: int, payload: Dict[str, Any]):
    """Send a test message directly to a specific custom agent."""
    prompt = payload.get("message")
    if not prompt:
        raise HTTPException(status_code=400, detail="message is required")
        
    with database.get_sync_db() as conn:
        row = conn.execute("SELECT * FROM custom_agents WHERE id = ?", (agent_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Agent tidak ditemukan")
        agent_data = dict(row)
        
    import swarm_engine
    start_t = time.time()
    resp = await swarm_engine.generate_agent_response(
        agent=agent_data,
        prompt=prompt,
        system_instruction=agent_data.get("system_instruction") or f"Kamu adalah {agent_data['name']}, {agent_data['role']}."
    )
    duration_ms = round((time.time() - start_t) * 1000, 1)
    
    return {
        "status": "success",
        "agent_name": agent_data["name"],
        "model": agent_data["model"],
        "provider": agent_data["provider"],
        "duration_ms": duration_ms,
        "reply": resp
    }


# --- Multi-Agent Round-Table Meeting Endpoints ---
@app.post("/api/meetings/start")
async def start_agent_meeting(payload: Dict[str, Any]):
    """Launch direct swarm execution (mode rapat/diskusi sudah dihapus)."""
    topic = payload.get("topic")
    if not topic:
        raise HTTPException(status_code=400, detail="topic is required")
        
    participants = payload.get("participants")
    rounds = payload.get("rounds", 2)
    folder = payload.get("folder", "")

    import swarm_engine
    result = await swarm_engine.conduct_multi_agent_meeting(
        topic=topic,
        participant_names=participants,
        rounds=safe_int(rounds, 2, minimum=1, maximum=3),
        mode="execute",
        target_folder=str(folder or ""),
    )
    return result


@app.post("/api/meetings/cancel")
async def cancel_agent_meeting():
    """Minta pembatalan eksekusi swarm yang sedang berjalan (lintas proses)."""
    import swarm_engine
    ok = swarm_engine.request_cancel_swarm()
    if ok:
        return {"status": "success", "message": "Sinyal pembatalan terkirim — swarm berhenti setelah langkah berjalan selesai."}
    return {"status": "error", "message": "Tidak ada sesi swarm yang sedang berjalan."}


@app.get("/api/swarm/live")
async def swarm_live_feed(since: int = 0):
    """Realtime terminal feed of what the swarm agents are doing right now.
    Sumber: file JSONL bersama (lintas proses bot & dashboard)."""
    import json as _json

    import swarm_engine as _se
    since = safe_int(since, 0, minimum=0)
    entries = []
    try:
        if os.path.exists(_se.LIVE_FEED_FILE):
            with open(_se.LIVE_FEED_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        e = _json.loads(line)
                        if e.get("i", 0) > since:
                            entries.append(e)
                    except Exception:
                        continue
            entries = entries[-150:]
    except Exception as e:
        return {"status": "error", "message": str(e), "entries": [], "running": False}
    return {
        "status": "success",
        "entries": entries,
        "running": bool(getattr(_se, "MEETING_RUNNING", False)),
    }


# ── Antigravity Multi-Account (OAuth login dari website) ──
@app.post("/api/antigravity/login/start")
async def antigravity_login_start(payload: Dict[str, Any]):
    """Mulai sesi login Google utk akun Antigravity baru."""
    import antigravity_login as agy_oauth
    name = payload.get("name", "").strip().lower()
    if not name:
        raise HTTPException(status_code=400, detail="nama wajib diisi")
    res = agy_oauth.start_login(name)
    return res


@app.get("/api/antigravity/login/status")
async def antigravity_login_status(name: str = ""):
    import antigravity_login as agy_oauth
    return agy_oauth.login_status(name)


@app.get("/api/antigravity/accounts")
async def antigravity_accounts():
    import antigravity_login as agy_oauth
    return {"status": "success", "accounts": agy_oauth.list_accounts()}


@app.post("/api/antigravity/logout")
async def antigravity_logout_endpoint(payload: Dict[str, Any]):
    import antigravity_login as agy_oauth
    return agy_oauth.remove_account(payload.get("name", ""))


@app.get("/api/swarm/folders")
async def swarm_list_folders():
    """Daftar folder proyek yang bisa dipilih sebagai target edit agen."""
    import os as _os
    candidates = []

    def _add(root: str, label_prefix: str):
        try:
            if not os.path.isdir(root):
                return
            for d in sorted(_os.listdir(root)):
                p = _os.path.join(root, d)
                if _os.path.isdir(p) and not d.startswith("."):
                    candidates.append({"path": p, "label": f"{label_prefix}/{d}"})
        except Exception:
            pass

    _add("/dev/shm/alfa_sandbox", "sandbox")
    _add(_os.path.expanduser("~/Dokumen/ALFA_SWARM_OUTPUTS/websites"), "outputs/websites")
    _add(_os.path.expanduser("~/alfa_projects"), "alfa_projects")
    return {"folders": candidates}


@app.get("/api/meetings")
async def list_meetings(limit: int = 50):
    """List recent multi-agent meetings."""
    meetings = database.list_agent_meetings_sync(limit=limit)
    return {"status": "success", "total": len(meetings), "meetings": meetings}


@app.get("/api/meetings/{meeting_id}")
async def get_meeting_details(meeting_id: int):
    """Fetch complete transcript, consensus, and action plan of a meeting."""
    details = database.get_agent_meeting_sync(meeting_id)
    if not details:
        raise HTTPException(status_code=404, detail="Meeting not found")
    return {"status": "success", "meeting": details}


# --- Live Agent Activity & Real-Time Autonomous Execution ---
@app.get("/api/agent-activity")
async def get_agent_activity():
    """Fetch live real-time agent activities, subagent background tasks, and agent telemetry."""
    activities = database.list_agent_activities_sync(limit=30)
    subagent_tasks = database.list_subagent_tasks_sync(limit=10)
    agents = database.list_custom_agents_sync()
    
    agent_states = []
    for a in agents:
        last_act = next((act for act in activities if act.get("agent_id") == a["id"] or act.get("agent_name") == a["name"]), None)
        agent_states.append({
            "id": a["id"],
            "name": a["name"],
            "role": a["role"],
            "avatar_emoji": a.get("avatar_emoji", "🤖"),
            "color_theme": a.get("color_theme", "cyan"),
            "provider": a["provider"],
            "model": a["model"],
            "status": "active" if a.get("is_enabled", 1) else "disabled",
            "current_state": "🟢 STANDBY" if not last_act else f"⚙️ {last_act.get('action_type', 'ACTIVE').upper()}",
            "last_action": last_act.get("description", "Menunggu instruksi tugas") if last_act else "Siap eksekusi tugas otonom",
            "last_tool": last_act.get("tool_name") if last_act else None,
            "last_updated": last_act.get("created_at") if last_act else a.get("created_at")
        })

    return {
        "status": "success",
        "total_activities": len(activities),
        "activities": activities,
        "subagent_tasks": subagent_tasks,
        "agent_states": agent_states
    }


@app.post("/api/agents/{agent_id}/execute")
async def execute_agent_task(agent_id: int, payload: Dict[str, Any]):
    """
    Directly dispatch an autonomous task to a specialized agent with real tool execution.
    The agent reasons, executes bash/files/search/metrics tools, and returns the live result.
    """
    instruction = payload.get("instruction")
    if not instruction:
        raise HTTPException(status_code=400, detail="instruction is required")
        
    with database.get_sync_db() as conn:
        row = conn.execute("SELECT * FROM custom_agents WHERE id = ?", (agent_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Agent tidak ditemukan")
        agent_data = dict(row)

    import swarm_engine
    import tools
    start_t = time.time()
    
    # 1. Ask agent to formulate action plan and tool command
    tool_router_prompt = (
        f"USER REQUEST:\n{instruction}\n\n"
        f"Kamu adalah {agent_data['name']} ({agent_data['role']}). Kamu memiliki akses langsung ke Linux Host.\n"
        f"PILIH SALAH SATU TOOL YANG TEPAT UNTUK MENGEKSEKUSI TUGAS DI ATAS:\n"
        f"- BASH: format `TOOL: BASH | <perintah bash>` (misal `TOOL: BASH | git status`, `TOOL: BASH | free -m`, `TOOL: BASH | ps aux --sort=-%mem | head -n 10`)\n"
        f"- SYSTEM_STATS: format `TOOL: SYSTEM_STATS | none`\n"
        f"- READ_FILE: format `TOOL: READ_FILE | <path>`\n"
        f"- WRITE_FILE: format `TOOL: WRITE_FILE | <path> | <isi konten>`\n"
        f"- WEB_SEARCH: format `TOOL: WEB_SEARCH | <query>`\n"
        f"- DIRECT_ANSWER: Jika tidak butuh tool, jawab langsung.\n\n"
        f"Format jawaban baris pertama harus TOOL: <NAMA_TOOL> | <PARAM> jika memanggil tool!"
    )
    
    decision = await swarm_engine.generate_agent_response(
        agent=agent_data,
        prompt=tool_router_prompt,
        system_instruction="Kamu adalah engine otonom yang mengeksekusi tool sistem."
    )
    
    tool_called = None
    tool_input = None
    tool_output_str = ""
    action_type = "tool_call"
    
    # Parse decision
    if "TOOL: BASH |" in decision:
        cmd = decision.split("TOOL: BASH |", 1)[1].strip().split("\n")[0]
        tool_called = "execute_bash_command"
        tool_input = cmd
        action_type = "bash_exec"
        res = tools.execute_bash_command(cmd)
        tool_output_str = res.get("stdout") or res.get("output") or res.get("message") or res.get("stderr") or "Done (exit code 0)"
    elif "TOOL: SYSTEM_STATS" in decision:
        tool_called = "get_system_stats"
        tool_input = "metrics"
        action_type = "audit"
        res = tools.get_system_stats()
        tool_output_str = json.dumps(res, indent=2, default=str)
    elif "TOOL: READ_FILE |" in decision:
        fpath = decision.split("TOOL: READ_FILE |", 1)[1].strip().split("\n")[0]
        tool_called = "read_local_file"
        tool_input = fpath
        action_type = "file_op"
        res = tools.read_local_file(fpath)
        tool_output_str = res.get("content") or res.get("message", "")
    elif "TOOL: WEB_SEARCH |" in decision:
        q = decision.split("TOOL: WEB_SEARCH |", 1)[1].strip().split("\n")[0]
        tool_called = "web_search"
        tool_input = q
        action_type = "web_search"
        res = tools.web_search(q)
        tool_output_str = json.dumps(res, indent=2, default=str)
    else:
        # Fallback to direct bash if instruction looks like a command
        if any(kw in instruction.lower() for kw in ["git", "ps", "top", "ram", "cpu", "disk", "ls", "systemctl", "curl", "free"]):
            tool_called = "execute_bash_command"
            tool_input = instruction
            action_type = "bash_exec"
            res = tools.execute_bash_command(instruction)
            tool_output_str = res.get("stdout") or res.get("output") or res.get("message") or res.get("stderr") or "Done (exit code 0)"

    # 2. Ask agent to synthesize final response based on tool execution
    synth_prompt = (
        f"TUGAS AWAL: {instruction}\n\n"
        f"HASIL EKSEKUSI TOOL ({tool_called or 'Direct Reasoning'}):\n"
        f"Input: {tool_input}\n"
        f"Output:\n{tool_output_str[:3000]}\n\n"
        f"Berikan laporan ringkas, santai, gaul, dan to-the-point mengenai hasil eksekusi di atas!"
    )
    
    final_report = await swarm_engine.generate_agent_response(
        agent=agent_data,
        prompt=synth_prompt,
        system_instruction=agent_data.get("system_instruction") or "Kamu adalah engineer spesialis AI."
    )
    
    duration_ms = round((time.time() - start_t) * 1000, 1)
    
    # Log to SQLite
    database.log_agent_activity_sync(
        agent_id=agent_data["id"],
        agent_name=agent_data["name"],
        action_type=action_type,
        description=f"Eksekusi tugas: {instruction[:80]}",
        tool_name=tool_called,
        tool_input=tool_input,
        tool_output=tool_output_str[:1500] if tool_output_str else None,
        status="success",
        duration_ms=duration_ms
    )
    
    return {
        "status": "success",
        "agent_name": agent_data["name"],
        "role": agent_data["role"],
        "model": agent_data["model"],
        "provider": agent_data["provider"],
        "action_type": action_type,
        "tool_called": tool_called,
        "tool_input": tool_input,
        "tool_output": tool_output_str,
        "agent_report": final_report,
        "duration_ms": duration_ms
    }


# ==================== MEMORY MAINTENANCE (glibc heap trim) ====================
# Endpoint berat (swarm/scrape/index) meninggalkan heap yang tidak dikembalikan
# ke OS oleh glibc -> RSS menetap di puncak pemakaian. malloc_trim berkala
# memulangkan halaman memori kosong tersebut.
_TRIM_INTERVAL_SEC = int(os.getenv("DASHBOARD_MALLOC_TRIM_SEC", "900"))


async def _malloc_trim_loop():
    import ctypes
    try:
        libc = ctypes.CDLL("libc.so.6")
    except OSError:
        return
    while True:
        await asyncio.sleep(_TRIM_INTERVAL_SEC)
        try:
            freed = libc.malloc_trim(0)
            if freed:
                rss_mb = int(open("/proc/self/status").read().split("VmRSS:")[1].split()[0]) // 1024
                logger.debug(f"malloc_trim OK — RSS sekarang {rss_mb} MB")
        except Exception as e:
            logger.debug(f"malloc_trim gagal (abaikan): {e}")


@app.on_event("startup")
async def _start_memory_maintenance():
    asyncio.create_task(_malloc_trim_loop())



if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("DASHBOARD_PORT", "8080"))
    # Default 127.0.0.1: dashboard only reachable from this machine.
    # Set DASHBOARD_HOST=0.0.0.0 in .env to expose it on the LAN (not
    # recommended unless DASHBOARD_AUTH_TOKEN is also set).
    host = os.getenv("DASHBOARD_HOST", "127.0.0.1").strip() or "127.0.0.1"
    print(f"🚀 Launching ALFA Sovereign Command Center Pro-Max on http://{host}:{port}")
    if host in ("0.0.0.0", "::") and not os.getenv("DASHBOARD_AUTH_TOKEN"):
        logging.getLogger("Dashboard").warning(
            "DASHBOARD_HOST terbuka ke jaringan TANPA DASHBOARD_AUTH_TOKEN - "
            "siapa pun di jaringan bisa mengendalikan sistem ini!"
        )
    uvicorn.run("web_dashboard:app", host=host, port=port, reload=False)
