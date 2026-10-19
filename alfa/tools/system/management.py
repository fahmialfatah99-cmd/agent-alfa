"""API keys, agents, meetings, plugins, and task management tools."""

import asyncio
import concurrent.futures
import json
import logging
import sqlite3
import subprocess
from typing import Any

from alfa.core import database
from alfa.core.runtime_ctx import get_current_chat_id, get_current_user_id
from alfa.tools.registry import register_tool

logger = logging.getLogger("AgentTools.System")

_MGMT_ERR = (
    OSError,
    ValueError,
    RuntimeError,
    TypeError,
    KeyError,
    AttributeError,
    ImportError,
    sqlite3.Error,
    subprocess.SubprocessError,
    concurrent.futures.TimeoutError,
)


@register_tool(category="system")
def self_add_new_tool(
    tool_name: str,
    tool_description: str,
    tool_code: str,
    test_arguments_json: str = "{}",
) -> dict[str, Any]:
    """
    GOD MODE: Self-Evolution Engine — dynamically writes, compiles, sandbox-tests, and hot-loads
    a brand new Python tool into the plugins/ directory.
    """
    try:
        import plugins

        test_kwargs = {}
        if test_arguments_json and test_arguments_json.strip():
            try:
                test_kwargs = json.loads(test_arguments_json)
            except (ValueError, TypeError):
                test_kwargs = {}
        return plugins.create_and_register_plugin(
            tool_name, tool_description, tool_code, test_kwargs=test_kwargs
        )
    except _MGMT_ERR as e:
        return {"status": "error", "message": f"Self-evolution error: {str(e)}"}


@register_tool(category="system")
def list_dynamic_plugins() -> dict[str, Any]:
    """
    List all dynamically created and hot-loaded plugin tools currently available in the system.
    """
    try:
        import plugins

        plugins_list = plugins.list_all_plugins()
        return {
            "status": "success",
            "total_plugins": len(plugins_list),
            "plugins": plugins_list,
        }
    except _MGMT_ERR as e:
        return {"status": "error", "message": str(e)}


@register_tool(category="system")
def delete_dynamic_plugin(tool_name: str) -> dict[str, Any]:
    """
    Permanently delete a dynamic plugin tool from disk and unregister from memory.
    """
    try:
        import plugins

        return plugins.delete_plugin(tool_name)
    except _MGMT_ERR as e:
        return {"status": "error", "message": str(e)}


@register_tool(category="system")
def query_token_usage(hours: int = 24) -> dict[str, Any]:
    """
    Laporan pemakaian token AI per API key (realtime dari dashboard vault).
    """
    try:
        summary = database.get_api_usage_summary_sync(hours=hours)
        per_key = [
            {
                k: r.get(k)
                for k in ("key_name", "provider", "total_tokens", "calls", "last_used")
            }
            for r in summary.get("per_key", [])[:15]
        ]
        return {
            "status": "success",
            "window_hours": summary.get("window_hours"),
            "tokens_today": summary.get("tokens_today"),
            "calls_today": summary.get("calls_today"),
            "total_all_time": summary.get("total_all_time"),
            "per_key": per_key,
            "by_context": summary.get("by_context", []),
            "message": f"Pemakaian {hours} jam terakhir: {summary.get('tokens_today')} token hari ini.",
        }
    except _MGMT_ERR as e:
        return {
            "status": "error",
            "message": f"Gagal membaca pemakaian token: {str(e)}",
        }


@register_tool(category="system")
def open_web_dashboard(port: int = 8080) -> dict[str, Any]:
    """
    ALFA OS: Web Command Center Dashboard Controller.
    """
    try:
        res = subprocess.run(
            ["systemctl", "--user", "is-active", "alfa-dashboard.service"],
            capture_output=True,
            text=True,
        )
        if res.stdout.strip() != "active":
            subprocess.run(
                ["systemctl", "--user", "start", "alfa-dashboard.service"],
                capture_output=True,
                text=True,
            )

        import socket

        local_ip = "127.0.0.1"
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
        except OSError:
            pass

        return {
            "status": "success",
            "message": f"🌐 Web Dashboard Command Center aktif! Buka di browser laptop: http://localhost:{port} atau dari HP di WiFi yang sama: http://{local_ip}:{port}",
            "local_url": f"http://localhost:{port}",
            "network_url": f"http://{local_ip}:{port}",
            "dashboard_features": [
                "Live Hardware Telemetry",
                "75+ Tools Arsenal & Runner",
                "Ecosystem Services Hub",
                "Second Brain Memory Visualizer",
                "24/7 Guardian Control",
                "Web Live AI Console",
                "AI Swarm & Rapat Antar Agent",
                "Multi-Provider API Key Vault",
            ],
        }
    except _MGMT_ERR as e:
        return {"status": "error", "message": f"Open web dashboard error: {str(e)}"}


@register_tool(category="system")
def manage_api_keys(
    action: str,
    name: str = "",
    provider: str = "gemini",
    api_key: str = "",
    default_model: str = "gemini-3.5-flash",
    base_url: str = "",
    key_id: int | None = None,
) -> dict[str, Any]:
    """
    Manage API keys and multi-provider endpoints.
    """
    action = action.lower().strip()
    try:
        if action == "list":
            keys = database.list_api_keys_sync()
            return {"status": "success", "total_keys": len(keys), "keys": keys}
        elif action == "add":
            if not api_key:
                return {
                    "status": "error",
                    "message": "Parameter 'api_key' wajib diisi.",
                }
            res = database.add_api_key_sync(
                name=name or f"{provider.capitalize()} Key",
                provider=provider,
                api_key=api_key,
                default_model=default_model,
                base_url=base_url,
                set_active=True,
            )
            return {
                "status": "success",
                "message": f"API Key '{name}' untuk provider '{provider}' berhasil disimpan & diaktifkan!",
                "key_id": res.get("id"),
            }
        elif action == "activate":
            if not key_id:
                return {"status": "error", "message": "Parameter 'key_id' wajib diisi."}
            return database.activate_api_key_sync(key_id)
        elif action == "delete":
            if not key_id:
                return {"status": "error", "message": "Parameter 'key_id' wajib diisi."}
            return database.delete_api_key_sync(key_id)
        else:
            return {"status": "error", "message": f"Action tidak dikenal: {action}."}
    except _MGMT_ERR as e:
        return {"status": "error", "message": f"Manage API keys error: {str(e)}"}


@register_tool(category="system")
def manage_custom_agents(
    action: str,
    name: str = "",
    role: str = "",
    persona: str = "",
    system_instruction: str = "",
    provider: str = "gemini",
    model: str = "gemini-3.5-flash",
    avatar_emoji: str = "🤖",
    color_theme: str = "cyan",
    agent_id: int | None = None,
) -> dict[str, Any]:
    """
    Manage the Autonomous AI Agent Workforce (Society of Agents).
    """
    action = action.lower().strip()
    try:
        if action == "list":
            agents = database.list_custom_agents_sync()
            return {"status": "success", "total_agents": len(agents), "agents": agents}
        elif action == "add":
            if not name or not role:
                return {
                    "status": "error",
                    "message": "Parameter 'name' dan 'role' wajib diisi.",
                }
            res = database.add_custom_agent_sync(
                name=name,
                role=role,
                persona=persona or f"Spesialis dalam {role}",
                system_instruction=system_instruction or f"Kamu adalah {name}, {role}.",
                provider=provider,
                model=model,
                avatar_emoji=avatar_emoji,
                color_theme=color_theme,
            )
            return {
                "status": "success",
                "message": f"Agent '{name}' ({role}) berhasil ditambahkan ke AI Workforce!",
                "agent_id": res.get("id"),
            }
        elif action == "delete":
            if not agent_id:
                return {
                    "status": "error",
                    "message": "Parameter 'agent_id' wajib diisi.",
                }
            return database.delete_custom_agent_sync(agent_id)
        elif action == "toggle":
            if not agent_id:
                return {
                    "status": "error",
                    "message": "Parameter 'agent_id' wajib diisi.",
                }
            cur = database.get_custom_agent_sync(agent_id)
            if not cur:
                return {"status": "error", "message": "Agent tidak ditemukan"}
            new_state = 0 if cur.get("is_enabled", 1) else 1
            return database.update_custom_agent_sync(
                agent_id, {"is_enabled": new_state}
            )
        else:
            return {"status": "error", "message": f"Action tidak dikenal: {action}."}
    except _MGMT_ERR as e:
        return {"status": "error", "message": f"Manage custom agents error: {str(e)}"}


@register_tool(category="system")
def conduct_ai_meeting(
    topic: str,
    participants: str = "",
    rounds: int = 2,
    mode: str = "execute",
    folder: str = "",
) -> dict[str, Any]:
    """Jalankan SWARM EKSEKUSI MULTI-AGEN: HANYA panggil jika pengguna SECARA EKSPLISIT meminta rapat, diskusi tim, atau mode swarm.

    PERINGATAN KERAS: JANGAN memanggil tool ini jika pengguna hanya memberikan tugas biasa
    (coding, riset, analisis, perbaikan file). Selesaikan tugas biasa tersebut sendiri menggunakan
    tools native Anda (write_local_file, execute_bash_command, web_search, dll).
    """
    try:
        from alfa.bot.mode_commands import get_telegram_mode_sync

        current_mode = get_telegram_mode_sync()
        if current_mode == "single":
            topic_lower = (topic or "").lower()
            explicit_swarm_keywords = (
                "rapat",
                "meeting",
                "swarm",
                "tim multi-agen",
                "diskusi tim",
                "musyawarah",
                "war room",
            )
            if not any(k in topic_lower for k in explicit_swarm_keywords):
                return {
                    "status": "skipped",
                    "message": (
                        "Mode Telegram saat ini adalah SINGLE AGENT. Pengguna tidak secara eksplisit meminta rapat/swarm. "
                        "DILARANG meluncurkan swarm! Selesaikan tugas ini sendiri secara langsung menggunakan tools native "
                        "Anda (write_local_file, execute_bash_command, web_search, dll)."
                    ),
                }

        from alfa.swarm import engine as swarm_engine

        part_list = (
            [p.strip() for p in participants.split(",") if p.strip()]
            if participants
            else None
        )
        rounds_clamped = max(1, min(3, int(rounds)))

        def _run_meeting():
            return asyncio.run(
                swarm_engine.conduct_multi_agent_meeting(
                    topic, part_list, rounds_clamped, "execute", target_folder=folder
                )
            )

        try:
            asyncio.get_running_loop()
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                result = pool.submit(_run_meeting).result(timeout=600)
        except RuntimeError:
            result = _run_meeting()

        return {
            "status": "success",
            "meeting_id": result.get("meeting_id"),
            "title": result.get("title"),
            "topic": topic,
            "mode": "execute",
            "target_folder": result.get("target_folder", ""),
            "total_rounds": rounds_clamped,
            "participants": result.get("participants"),
            "total_dialogues": len(result.get("dialogue_transcript", [])),
            "execution_results": result.get("execution_results", []),
            "consensus": result.get("consensus"),
            "action_plan": result.get("action_plan"),
        }
    except _MGMT_ERR as e:
        return {"status": "error", "message": f"AI Meeting error: {str(e)}"}


@register_tool(category="system")
def spawn_background_subagent(
    task_description: str, agent_role: str = "Researcher & Coder"
) -> dict[str, Any]:
    """
    Spawn an autonomous background subagent worker to solve a complex task.
    """
    try:
        from alfa.swarm import subagents

        user_id = get_current_user_id()
        chat_id = get_current_chat_id()
        return subagents.spawn_subagent(
            user_id=user_id,
            chat_id=chat_id,
            role=agent_role,
            task_description=task_description,
        )
    except _MGMT_ERR as e:
        return {"status": "error", "message": str(e)}


@register_tool(category="system")
def check_subagent_status(subagent_id: str) -> dict[str, Any]:
    """
    Check execution status and report of a background subagent by task ID.
    """
    try:
        task = database.get_subagent_task_sync(subagent_id)
        if not task:
            return {
                "status": "error",
                "message": f"Subagent dengan ID '{subagent_id}' tidak ditemukan.",
            }
        return {"status": "success", "task": task}
    except _MGMT_ERR as e:
        return {"status": "error", "message": str(e)}


@register_tool(category="system")
def add_recurring_task(
    title: str, prompt_instruction: str, interval_minutes: int = 60, kind: str = "single"
) -> dict[str, Any]:
    """
    Schedule an autonomous recurring task or proactive watchdog.

    Args:
        title: Nama tugas.
        prompt_instruction: Instruksi/tugas yang dijalankan tiap periode. Untuk
            kind='swarm' boleh nama templat (/swarm template) atau tugas bebas.
        interval_minutes: Periode pengulangan (menit).
        kind: 'single' (1 agen, default) atau 'swarm' (misi tim multi-agen).
    """
    try:
        user_id = get_current_user_id()
        chat_id = get_current_chat_id()
        kind = "swarm" if str(kind).lower() == "swarm" else "single"
        if kind == "swarm":
            try:
                from alfa.core import notification as _notify

                tpl = _notify.get_swarm_templates().get(
                    prompt_instruction.strip().lower()
                )
                if tpl:
                    prompt_instruction = tpl
            except _MGMT_ERR:
                pass
        job_id = database.add_cron_job_sync(
            user_id=user_id,
            chat_id=chat_id,
            title=title,
            prompt_instruction=prompt_instruction,
            interval_minutes=max(1, interval_minutes),
            kind=kind,
        )
        return {
            "status": "success",
            "job_id": job_id,
            "message": f"Tugas berulang #{job_id} '{title}' [{kind}] berhasil dijadwalkan setiap {interval_minutes} menit.",
        }
    except _MGMT_ERR as e:
        return {"status": "error", "message": str(e)}


@register_tool(category="system")
def list_recurring_tasks() -> dict[str, Any]:
    """
    List all active recurring tasks and watchdogs scheduled for the user.
    """
    try:
        user_id = get_current_user_id()
        jobs = database.list_cron_jobs_sync(user_id)
        return {"status": "success", "total_jobs": len(jobs), "tasks": jobs}
    except _MGMT_ERR as e:
        return {"status": "error", "message": str(e)}


@register_tool(category="system")
def cancel_recurring_task(task_id: int) -> dict[str, Any]:
    """
    Cancel and delete a scheduled recurring task or watchdog by its ID.
    """
    try:
        user_id = get_current_user_id()
        success = database.delete_cron_job_sync(user_id, task_id)
        if success:
            return {
                "status": "success",
                "message": f"Tugas berulang #{task_id} berhasil dibatalkan dan dihapus.",
            }
        return {"status": "error", "message": f"Tugas #{task_id} tidak ditemukan."}
    except _MGMT_ERR as e:
        return {"status": "error", "message": str(e)}


@register_tool(category="system")
def audit_project_honesty(path: str = "") -> dict[str, Any]:
    """
    Pindai proyek untuk pola data dummy (mekanis, deterministik).

    Mendeteksi: angka acak di jalur data (Math.random/random di API), database
    mock di memori, teks lorem/placeholder, kredensial contoh, klaim
    'neural/AI' tanpa model. Return daftar tersangka file:baris + verdict.
    Jalankan tiap coding selesai atau on-demand. Bukan bukti mutlak — pola
    kasat mata saja; reviewer manusia putuskan final.
    """
    import os as _os
    import re as _re

    try:
        base = _os.path.realpath(_os.path.expanduser((path or "").strip() or "."))
        if not _os.path.isdir(base):
            return {"status": "error", "message": f"Folder '{path}' tidak ditemukan."}
        patterns = [
            ("random-di-data", _re.compile(r"(Math\.random\(\)|random\.(randint|uniform|choice|random)\(\))"),
             ("route", "api", "endpoint", "database", "osint", "controller", "service")),
            ("mock-database", _re.compile(r"(mockDatabase|mock_data|MOCK_|FakeDB|dummy_?data)", _re.I), ()),
            ("lorem-placeholder", _re.compile(r"(lorem ipsum|placeholder\.|example\.com|test@test\.|TODO|FIXME|XXX)", _re.I), ()),
            ("kredensial-contoh", _re.compile(r"(AKIA[0-9A-Z]{16}|your-supabase-project|sk-test|password\s*=\s*[\"'](123|test|password|abc))"), ()),
            ("klaim-neural-tanpa-model", _re.compile(r"(neural|AI-powered|AI augmented|deep learning|GPT-4 powered)", _re.I), ()),
        ]
        skip_dirs = {"node_modules", ".next", ".git", "__pycache__", "venv", ".venv", "dist", "build", ".turbo"}
        exts = (".ts", ".tsx", ".js", ".jsx", ".py", ".php", ".html", ".md")
        suspects: list[dict[str, Any]] = []
        files_scanned = 0
        for root, dirs, files in _os.walk(base):
            dirs[:] = [d for d in dirs if d not in skip_dirs]
            for fn in files:
                if not fn.endswith(exts):
                    continue
                fp = _os.path.join(root, fn)
                try:
                    if _os.path.getsize(fp) > 500_000:
                        continue
                    with open(fp, errors="ignore") as f:
                        lines = f.readlines()
                except OSError:
                    continue
                files_scanned += 1
                rel = _os.path.relpath(fp, base)
                for lineno, line in enumerate(lines, 1):
                    for label, rx, ctx in patterns:
                        if rx.search(line):
                            if label == "random-di-data" and ctx:
                                blob = "\n".join(lines[max(0, lineno - 6):lineno + 2]).lower()
                                if not any(k in blob for k in ctx):
                                    continue
                            suspects.append({"file": rel, "line": lineno, "pola": label,
                                             "cuplikan": line.strip()[:140]})
                            break
        verdict = "BERSIH" if not suspects else f"{len(suspects)} TEMUAN"
        return {"status": "success", "path": base, "files_scanned": files_scanned,
                "verdict": verdict, "suspects": suspects[:40]}
    except _MGMT_ERR as e:
        return {"status": "error", "message": str(e)}


@register_tool(category="system")
def mcp_connect(server: str = "lottiefiles") -> dict[str, Any]:
    """
    Sambungkan server MCP remote (OAuth): kembalikan URL otorisasi.

    Alur: panggil tool ini -> berikan auth_url ke user untuk dibuka di browser
    laptop -> login + approve -> token tersimpan otomatis -> tool mcp_call aktif.
    """
    try:
        from alfa.mcp import client as _mc

        redirect = "http://127.0.0.1:8080/api/mcp/oauth/callback"
        return _mc.start_connect(server, redirect)
    except _MGMT_ERR as e:
        return {"status": "error", "message": str(e)}


@register_tool(category="system")
def mcp_status(server: str = "") -> dict[str, Any]:
    """Status koneksi server MCP remote (lottiefiles)."""
    try:
        from alfa.mcp import client as _mc

        return {"status": "success", **_mc.connection_status(server)}
    except _MGMT_ERR as e:
        return {"status": "error", "message": str(e)}


@register_tool(category="system")
def mcp_call(server: str, tool: str, args_json: str = "{}") -> dict[str, Any]:
    """
    Panggil tool di server MCP remote yang sudah terhubung.

    Args:
        server: 'lottiefiles'.
        tool: nama tool (lihat mcp_status/list via operations_list).
        args_json: argumen JSON.
    """
    try:
        import json as _json

        from alfa.mcp import client as _mc

        try:
            args = _json.loads(args_json or "{}")
        except (ValueError, TypeError):
            args = {}
        listed = _mc.list_tools_sync(server)
        if listed.get("status") == "success":
            names = [t.get("name") for t in listed.get("tools", [])]
            if tool not in names:
                return {"status": "error",
                        "message": f"Tool '{tool}' tak ada. Tersedia: {names}"}
        return _mc.call_tool_sync(server, tool, args)
    except _MGMT_ERR as e:
        return {"status": "error", "message": str(e)}
