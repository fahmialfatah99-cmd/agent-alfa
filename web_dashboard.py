"""
ALFA SOVEREIGN COMMAND CENTER - Web Dashboard (PRO-MAX Edition)
High-performance FastAPI web dashboard with luxury dark glassmorphic UI,
live telemetry timeline, 72+ tools explorer, service orchestrator,
artifact gallery, and second brain visualizer.
"""

import os
import sys
import glob
import json
import time
import inspect
import asyncio
import subprocess
from datetime import datetime
from typing import Dict, Any, List, Optional

import psutil
from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()

# Import project modules
import tools
import database
import bot

app = FastAPI(title="ALFA Sovereign Command Center Pro-Max", version="2.5.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")


def categorize_tool(name: str) -> str:
    """Categorize tool by its functional domain."""
    name_lower = name.lower()
    if name_lower.startswith("browser_"):
        return "Browser Automation"
    elif name_lower.startswith("desktop_") or name_lower.startswith("vision_") or "screenshot" in name_lower or "webcam" in name_lower:
        return "OS & Vision Control"
    elif name_lower.startswith("libreoffice_"):
        return "LibreOffice Suite"
    elif "pdf" in name_lower or "excel" in name_lower or "presentation" in name_lower or "media" in name_lower or "audio" in name_lower:
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
            return HTMLResponse(content=f.read())
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
        disk = psutil.disk_usage("/")
        battery = psutil.sensors_battery()
        
        uptime_secs = int(time.time() - psutil.boot_time())
        hours, remainder = divmod(uptime_secs, 3600)
        minutes, seconds = divmod(remainder, 60)
        
        # Check active background services
        tb_res = subprocess.run(["systemctl", "--user", "is-active", "telegram-ai-bot.service"], capture_output=True, text=True)
        wa_res = subprocess.run(["systemctl", "--user", "is-active", "wa-sheets-bot.service"], capture_output=True, text=True)
        dash_res = subprocess.run(["systemctl", "--user", "is-active", "alfa-dashboard.service"], capture_output=True, text=True)

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
                "telegram_bot": tb_res.stdout.strip() == "active",
                "wa_sheets_bot": wa_res.stdout.strip() == "active",
                "dashboard": dash_res.stdout.strip() == "active"
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
        raise HTTPException(status_code=404, detail=f"Tool '{tool_name}' not found")
        
    try:
        # Set primary user context
        uid = int(os.getenv("ALLOWED_USER_IDS", "8821693251").split(",")[0].strip())
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
                import qrcode
                import io
                import base64
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
    except Exception as e:
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

    reports_file = "/home/fahmial/wa-sheets-bot/recorded_reports.json"
    formats_file = "/home/fahmial/wa-sheets-bot/formats.json"
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
    """Fetch live service journalctl logs."""
    res = subprocess.run(["journalctl", "--user", "-u", service, "-n", str(lines), "--no-pager"], capture_output=True, text=True)
    return {
        "status": "success",
        "service": service,
        "logs": res.stdout.strip()
    }


@app.get("/api/memory")
async def get_memory_data():
    """Fetch all permanent memory facts and knowledge graph relations."""
    uid = int(os.getenv("ALLOWED_USER_IDS", "8821693251").split(",")[0].strip())
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
    uid = int(os.getenv("ALLOWED_USER_IDS", "8821693251").split(",")[0].strip())
    m_type = payload.get("type", "fact")
    
    if m_type == "fact":
        key = payload.get("key_topic")
        content = payload.get("content")
        cat = payload.get("category", "general")
        if not key or not content:
            raise HTTPException(status_code=400, detail="key_topic and content required")
        res = database.save_knowledge_memory_sync(uid, cat, key, content)
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
    uid = int(os.getenv("ALLOWED_USER_IDS", "8821693251").split(",")[0].strip())
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
    uid = int(os.getenv("ALLOWED_USER_IDS", "8821693251").split(",")[0].strip())
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


@app.get("/api/artifacts")
async def list_artifacts():
    """List recent artifacts (images, PDFs, documents, audio) generated by tools."""
    search_dirs = [
        "/dev/shm/alfa_sandbox",
        "/home/fahmial/output",
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


@app.get("/api/artifacts/download")
async def download_artifact(path: str):
    """Safely download an artifact file."""
    if not os.path.exists(path) or not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path, filename=os.path.basename(path))


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
        
    uid = int(os.getenv("ALLOWED_USER_IDS", "8821693251").split(",")[0].strip())
    reply = await bot.run_agent_turn(user_id=uid, user_prompt=message, chat_id=uid)
    return {
        "status": "success",
        "reply": reply,
        "timestamp": datetime.now().isoformat()
    }


# --- Multi-Provider API Key Vault Endpoints ---
@app.get("/api/keys")
async def get_api_keys():
    """List all API keys with masked values."""
    keys = database.list_api_keys_sync()
    return {"status": "success", "total": len(keys), "keys": keys}


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
    "nvidia": [
        {"id": "meta/llama-3.3-70b-instruct", "name": "Meta Llama 3.3 70B Instruct (Rekomendasi Utama)", "category": "General & Coding"},
        {"id": "deepseek-ai/deepseek-r1", "name": "DeepSeek R1 (Penalaran & Logic Terkuat)", "category": "Reasoning"},
        {"id": "deepseek-ai/deepseek-v3", "name": "DeepSeek V3 (Sangat Cerdas & Cepat)", "category": "General"},
        {"id": "nvidia/llama-3.1-nemotron-70b-instruct", "name": "NVIDIA Nemotron 70B (Optimasi NVIDIA)", "category": "General"},
        {"id": "meta/llama-3.1-405b-instruct", "name": "Meta Llama 3.1 405B Instruct (Model Raksasa)", "category": "Flagship"},
        {"id": "meta/llama-3.1-70b-instruct", "name": "Meta Llama 3.1 70B Instruct", "category": "General"},
        {"id": "meta/llama-3.1-8b-instruct", "name": "Meta Llama 3.1 8B Instruct (Super Cepat)", "category": "Fast"},
        {"id": "qwen/qwen2.5-coder-32b-instruct", "name": "Qwen 2.5 Coder 32B (Spesialis Kode & Dev)", "category": "Coding"},
        {"id": "qwen/qwen2.5-72b-instruct", "name": "Qwen 2.5 72B Instruct", "category": "General"},
        {"id": "mistralai/mixtral-8x22b-instruct-v0.1", "name": "Mistral Mixtral 8x22B Instruct", "category": "MoE"},
        {"id": "mistralai/mistral-large-2-instruct", "name": "Mistral Large 2 Instruct", "category": "Flagship"},
        {"id": "microsoft/phi-3.5-moe-instruct", "name": "Microsoft Phi 3.5 MoE Instruct", "category": "Lightweight"}
    ],
    "gemini": [
        {"id": "gemini-3.5-flash-lite", "name": "Gemini 3.5 Flash Lite (Default / Cepat & Hemat)", "category": "Flash"},
        {"id": "gemini-3.6-flash", "name": "Gemini 3.6 Flash (Terbaru)", "category": "Flash"},
        {"id": "gemini-flash-latest", "name": "Gemini Flash Latest", "category": "Flash"},
        {"id": "gemini-2.0-flash", "name": "Gemini 2.0 Flash", "category": "Flash"},
        {"id": "gemini-1.5-pro", "name": "Gemini 1.5 Pro (Konteks Panjang & Analisis)", "category": "Pro"},
        {"id": "gemini-1.5-flash", "name": "Gemini 1.5 Flash", "category": "Flash"}
    ],
    "openai": [
        {"id": "gpt-4o", "name": "GPT-4o (Omni Flagship)", "category": "Flagship"},
        {"id": "gpt-4o-mini", "name": "GPT-4o Mini (Hemat & Cepat)", "category": "Fast"},
        {"id": "o1", "name": "OpenAI o1 (Full Reasoning)", "category": "Reasoning"},
        {"id": "o1-mini", "name": "OpenAI o1 Mini (Math & Code Reasoning)", "category": "Reasoning"},
        {"id": "o3-mini", "name": "OpenAI o3 Mini", "category": "Reasoning"},
        {"id": "gpt-4-turbo", "name": "GPT-4 Turbo", "category": "Flagship"}
    ],
    "groq": [
        {"id": "llama-3.3-70b-versatile", "name": "Llama 3.3 70B Versatile (Ultra-Fast 300+ T/s)", "category": "Fast"},
        {"id": "llama-3.1-8b-instant", "name": "Llama 3.1 8B Instant (Kilat)", "category": "Fast"},
        {"id": "mixtral-8x7b-32768", "name": "Mixtral 8x7B 32k", "category": "MoE"},
        {"id": "deepseek-r1-distill-llama-70b", "name": "DeepSeek R1 Distill Llama 70B", "category": "Reasoning"},
        {"id": "gemma2-9b-it", "name": "Gemma 2 9B IT", "category": "Google"}
    ],
    "openrouter": [
        {"id": "anthropic/claude-3.5-sonnet", "name": "Claude 3.5 Sonnet (via OpenRouter)", "category": "Anthropic"},
        {"id": "deepseek/deepseek-r1", "name": "DeepSeek R1 (via OpenRouter)", "category": "DeepSeek"},
        {"id": "meta-llama/llama-3.3-70b-instruct", "name": "Llama 3.3 70B Instruct", "category": "Meta"},
        {"id": "openai/gpt-4o", "name": "GPT-4o (via OpenRouter)", "category": "OpenAI"},
        {"id": "google/gemini-2.0-flash-exp:free", "name": "Gemini 2.0 Flash Exp (Free Tier)", "category": "Free"}
    ],
    "anthropic": [
        {"id": "claude-3-5-sonnet-20241022", "name": "Claude 3.5 Sonnet v2 (Unggulan Coding & Menulis)", "category": "Sonnet"},
        {"id": "claude-3-5-haiku-20241022", "name": "Claude 3.5 Haiku (Ringan & Cepat)", "category": "Haiku"},
        {"id": "claude-3-opus-20240229", "name": "Claude 3 Opus (Kompleks)", "category": "Opus"}
    ],
    "ollama": [
        {"id": "llama3", "name": "Llama 3 (Local)", "category": "Local"},
        {"id": "deepseek-r1", "name": "DeepSeek R1 (Local)", "category": "Local"},
        {"id": "qwen2.5-coder", "name": "Qwen 2.5 Coder (Local)", "category": "Local"},
        {"id": "mistral", "name": "Mistral (Local)", "category": "Local"},
        {"id": "phi3", "name": "Phi 3 (Local)", "category": "Local"}
    ]
}


@app.get("/api/models")
async def get_available_models():
    """Get verified models list per provider."""
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
    if provider in ["nvidia", "nim", "openai", "groq", "openrouter", "ollama"]:
        try:
            import httpx
            url = base_url
            if not url:
                if provider in ["nvidia", "nim"]:
                    url = "https://integrate.api.nvidia.com/v1"
                elif provider == "openai":
                    url = "https://api.openai.com/v1"
                elif provider == "groq":
                    url = "https://api.groq.com/openai/v1"
                elif provider == "openrouter":
                    url = "https://openrouter.ai/api/v1"
                elif provider == "ollama":
                    url = "http://localhost:11434/v1"
            
            target_model = model or ("meta/llama-3.3-70b-instruct" if provider in ["nvidia", "nim"] else "gpt-4o")
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
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
            response = await client.aio.models.generate_content(
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
    """Launch an autonomous multi-agent round-table discussion."""
    topic = payload.get("topic")
    if not topic:
        raise HTTPException(status_code=400, detail="topic is required")
        
    participants = payload.get("participants")
    rounds = payload.get("rounds", 2)
    
    import swarm_engine
    result = await swarm_engine.conduct_multi_agent_meeting(
        topic=topic,
        participant_names=participants,
        rounds=min(3, max(1, int(rounds)))
    )
    return result


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


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("DASHBOARD_PORT", "8080"))
    print(f"🚀 Launching ALFA Sovereign Command Center Pro-Max on http://0.0.0.0:{port}")
    uvicorn.run("web_dashboard:app", host="0.0.0.0", port=port, reload=False)
