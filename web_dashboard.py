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


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("DASHBOARD_PORT", "8080"))
    print(f"🚀 Launching ALFA Sovereign Command Center Pro-Max on http://0.0.0.0:{port}")
    uvicorn.run("web_dashboard:app", host="0.0.0.0", port=port, reload=False)
