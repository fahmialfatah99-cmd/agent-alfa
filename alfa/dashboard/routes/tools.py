"""Tool explorer, dynamic plugins, superpowers, and UI/UX Pro Max routes for ALFA Dashboard."""

import inspect
import os
import re
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, HTTPException, UploadFile

import tools
from alfa.dashboard.common import REPO_ROOT, get_primary_user_id, logger

tools_router = APIRouter(tags=["tools"])


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


@tools_router.get("/api/tools")
async def get_tools_list():
    """Get list of all registered tools with descriptions, args, and categories."""
    try:
        import plugins
        plugins.load_all_plugin_tools()
    except Exception as e:
        logger.warning(f"Failed to load dynamic plugins for API: {e}")

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

    # Add dynamic plugins from registry
    try:
        import plugins as pl_mod
        for tool_name, tool_fn in pl_mod._RUNTIME_PLUGIN_REGISTRY.items():
            if not any(t["name"] == tool_name for t in tools_list):
                sig = inspect.signature(tool_fn)
                doc = (tool_fn.__doc__ or "Dynamic plugin tool.").strip()
                doc_lines = doc.split("\n")
                short_desc = doc_lines[0].strip() if doc_lines else "Dynamic plugin."

                params = []
                for p_name, param in sig.parameters.items():
                    params.append({
                        "name": p_name,
                        "default": str(param.default) if param.default != inspect.Parameter.empty else None,
                        "required": param.default == inspect.Parameter.empty,
                        "type": str(param.annotation) if param.annotation != inspect.Parameter.empty else "Any"
                    })

                tools_list.append({
                    "name": tool_name,
                    "short_description": short_desc,
                    "full_docstring": doc,
                    "category": "Dynamic Plugins",
                    "signature": f"{tool_name}{str(sig)}",
                    "parameters": params
                })
    except Exception as e:
        logger.warning(f"Failed to add dynamic plugins to list: {e}")

    return {
        "status": "success",
        "total_tools": len(tools_list),
        "tools": sorted(tools_list, key=lambda x: (x["category"], x["name"]))
    }


@tools_router.post("/api/tools/execute")
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


@tools_router.post("/api/tools/upload")
async def upload_files_for_tools(files: List[UploadFile] = File(...)):
    """Upload one or more files from user computer for tool processing."""
    upload_dir = tools.get_pdf_output_dir("Uploads")
    saved_files = []

    for f in files:
        safe_name = os.path.basename(f.filename or "upload_file")
        target_path = os.path.join(upload_dir, safe_name)

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


# ==================== DYNAMIC SELF-EVOLUTION PLUGINS ENDPOINTS ====================

@tools_router.get("/api/plugins/list")
async def api_plugins_list():
    """List all active self-evolved dynamic plugin tools."""
    import plugins
    plugins_list = plugins.list_all_plugins()
    return {
        "status": "success",
        "total_plugins": len(plugins_list),
        "plugins": plugins_list
    }


@tools_router.post("/api/plugins/create")
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


@tools_router.post("/api/plugins/delete")
async def api_plugins_delete(payload: Dict[str, Any]):
    """Permanently remove a dynamic plugin tool."""
    import plugins
    tool_name = payload.get("tool_name", "").strip()
    if not tool_name:
        raise HTTPException(status_code=400, detail="tool_name is required")
    return plugins.delete_plugin(tool_name)


@tools_router.post("/api/plugins/execute")
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


# ==================== SUPERPOWERS AGENTIC SKILLS ENDPOINTS ====================

@tools_router.get("/api/skills/superpowers")
async def api_superpowers_list():
    """List all integrated Superpowers Agentic Skills active across all ALFA units."""
    skills_dir = os.path.join(REPO_ROOT, "skills", "superpowers")
    if not os.path.isdir(skills_dir):
        skills_dir = os.path.expanduser("~/.alfa/skills/superpowers")
    if not os.path.isdir(skills_dir):
        skills_dir = r"C:\Users\mj9\.gemini\config\skills"

    icons_map = {
        "brainstorming": ("🧠", "Explores user intent, requirements and design before implementation", "Planning & Design"),
        "systematic-debugging": ("🔍", "Iron Law: 4-phase root-cause investigation before proposing any fix", "Debugging & Health"),
        "writing-plans": ("📝", "Generates rigorous implementation plans with dependencies and verification steps", "Planning & Design"),
        "executing-plans": ("⚡", "Step-by-step plan execution with human review checkpoints", "Execution & Swarm"),
        "test-driven-development": ("🧪", "TDD: Write failing automated tests first before code implementation", "Quality & Testing"),
        "verification-before-completion": ("✅", "Zero Hallucination: Verifies terminal output before claiming done", "Quality & Testing"),
        "subagent-driven-development": ("🤖", "Dispatches independent task subagents in current session", "Execution & Swarm"),
        "dispatching-parallel-agents": ("🔀", "Executes 2+ independent tasks concurrently without state collision", "Execution & Swarm"),
        "using-git-worktrees": ("🌲", "Devin-style isolated git worktrees/sandboxes for safe coding", "Architecture & Sandbox"),
        "requesting-code-review": ("🛡️", "Validates work against strict requirements before merge", "Quality & Testing"),
        "receiving-code-review": ("🧐", "Rigorously verifies feedback without performative agreement", "Quality & Testing"),
        "using-superpowers": ("🚀", "Master skill dispatcher and routing across all agents", "Core Framework"),
        "finishing-a-development-branch": ("🏁", "Systematic merge, verification, and branch cleanup", "Architecture & Sandbox"),
        "writing-skills": ("✍️", "Creates, tests, and validates new dynamic skills", "Core Framework"),
    }

    result = []
    if os.path.isdir(skills_dir):
        for item in sorted(os.listdir(skills_dir)):
            skill_path = os.path.join(skills_dir, item)
            if not os.path.isdir(skill_path) or item.startswith("."):
                continue
            skill_md = os.path.join(skill_path, "SKILL.md")
            desc = ""
            if os.path.isfile(skill_md):
                try:
                    with open(skill_md, "r", encoding="utf-8", errors="ignore") as f:
                        text = f.read(1500)
                    m = re.search(r"description:\s*([^\n]+)", text)
                    if m:
                        desc = m.group(1).strip()
                except Exception:
                    pass

            icon, default_desc, category = icons_map.get(item, ("🦸", desc or "Superpowers agentic skill", "Specialist Skill"))
            file_count = sum(len(files) for _, _, files in os.walk(skill_path))
            result.append({
                "id": item,
                "name": item.replace("-", " ").title(),
                "icon": icon,
                "category": category,
                "description": desc or default_desc,
                "file_count": file_count,
                "is_active_all_agents": True,
                "enforcement": "Main Agent, Swarm 6 Specialists, Background Subagents"
            })

    return {
        "status": "success",
        "total_skills": len(result),
        "applied_units": ["Main Brain (bot.py)", "Swarm 6 Personas (swarm_personas.py)", "Background Subagents (subagents.py)", "Auto-RAG Vector Brain"],
        "skills": result
    }


@tools_router.get("/api/skills/superpowers/{skill_id}")
async def api_superpowers_detail(skill_id: str):
    """Get full SKILL.md documentation and reference guidelines for a specific Superpowers skill."""
    skills_dir = os.path.join(REPO_ROOT, "skills", "superpowers")
    if not os.path.isdir(skills_dir):
        skills_dir = os.path.expanduser("~/.alfa/skills/superpowers")
    if not os.path.isdir(skills_dir):
        skills_dir = r"C:\Users\mj9\.gemini\config\skills"

    target_skill = os.path.join(skills_dir, skill_id.strip())
    if not os.path.isdir(target_skill):
        raise HTTPException(status_code=404, detail=f"Superpower skill '{skill_id}' not found")

    skill_md = os.path.join(target_skill, "SKILL.md")
    content = ""
    if os.path.isfile(skill_md):
        with open(skill_md, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()

    ref_files = []
    for root, _, files in os.walk(target_skill):
        for fl in files:
            rel = os.path.relpath(os.path.join(root, fl), target_skill)
            if rel != "SKILL.md":
                ref_files.append(rel)

    return {
        "status": "success",
        "skill_id": skill_id,
        "name": skill_id.replace("-", " ").title(),
        "content": content,
        "reference_files": ref_files,
        "applied_to_all_agents": True
    }


# ==================== UI/UX PRO MAX DESIGN INTELLIGENCE ENDPOINTS ====================

@tools_router.get("/api/skills/ui-ux-pro-max/search")
def api_ui_ux_search(q: str = "", domain: str = "auto"):
    """Search UI/UX Pro Max intelligence engine."""
    from plugins.ui_ux_pro_max import ui_ux_pro_max_search
    if not q:
        return {"status": "error", "message": "Parameter q (query) is required."}
    return ui_ux_pro_max_search(query=q, domain=domain, action="search")


@tools_router.post("/api/skills/ui-ux-pro-max/design-system")
def api_ui_ux_design_system(payload: Dict[str, Any]):
    """Generate comprehensive Design System for any product or niche."""
    from plugins.ui_ux_pro_max import ui_ux_pro_max_search
    query = payload.get("query", "").strip()
    project_name = payload.get("project_name", "My Project").strip()
    if not query:
        raise HTTPException(status_code=400, detail="query is required")
    return ui_ux_pro_max_search(query=query, action="generate_design_system", project_name=project_name)


@tools_router.get("/api/skills/ui-ux-pro-max/catalog")
def api_ui_ux_catalog():
    """Get summarized catalog of UI/UX Pro Max styles, colors, and typography."""
    summary = {
        "status": "success",
        "total_styles": 67,
        "total_rules": 192,
        "domains": ["product", "style", "color", "typography", "landing", "motion", "chart", "icon", "ux-guidelines"],
        "popular_styles": [
            {"name": "Glassmorphism", "desc": "Frosted glass depth with backdrop blur and subtle borders"},
            {"name": "Bento Grid", "desc": "Asymmetric modular card containers popular in Apple & SaaS"},
            {"name": "Dark Mode (OLED)", "desc": "High contrast true black backgrounds with vivid accents"},
            {"name": "Minimalism & Swiss", "desc": "Grid-based typographic precision, generous whitespace"},
            {"name": "Neubrutalism", "desc": "High contrast bold black borders, vibrant pop colors, sharp shadows"},
            {"name": "Cyberpunk / Sci-Fi", "desc": "Neon glow accents, dark metallic grids, futuristic HUD"}
        ],
        "checklist": [
            "No raw emojis as UI icons (Use Lucide / SVG)",
            "cursor-pointer on interactive elements",
            "Responsive breakpoints (375, 768, 1024, 1440)",
            "Minimum 4.5:1 text color contrast ratio",
            "Visible focus outline for accessibility",
            "Smooth transition easing (150-250ms)"
        ]
    }
    return summary
