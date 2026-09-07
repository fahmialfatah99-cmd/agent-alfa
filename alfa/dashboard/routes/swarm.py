"""Autonomous multi-agent swarm operations, custom agent workforce, meetings, and affiliate marketing for ALFA Dashboard."""

import asyncio
import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException

import database
from alfa.dashboard.common import logger, safe_int

swarm_router = APIRouter(tags=["swarm"])


def _parse_ai_sections(text: str) -> Dict[str, str]:
    """Pecah output AI bertanda ===NAMA_SEKSI=== menjadi dict."""
    out: Dict[str, str] = {}
    parts = re.split(r"={3,}\s*([A-Za-z_]+)\s*={3,}", text or "")
    for i in range(1, len(parts) - 1, 2):
        out[parts[i].strip().lower()] = parts[i + 1].strip()
    return out


# --- Affiliate Sales Swarm API Endpoints ---

@swarm_router.get("/api/affiliate/campaigns")
async def get_affiliate_campaigns(limit: int = 20):
    """Get list of active affiliate campaigns and scripts."""
    import affiliate_engine
    campaigns = affiliate_engine.list_affiliate_campaigns(limit=limit)
    return {
        "status": "success",
        "total": len(campaigns),
        "campaigns": campaigns
    }


@swarm_router.get("/api/affiliate/campaigns/{campaign_id}")
async def get_affiliate_campaign_detail(campaign_id: int):
    """Get full details of a specific affiliate campaign."""
    import affiliate_engine
    data = affiliate_engine.get_affiliate_campaign_detail(campaign_id)
    if not data:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return {"status": "success", "campaign": data}


@swarm_router.post("/api/affiliate/generate")
async def generate_affiliate_campaign(payload: Dict[str, Any]):
    """Generate viral affiliate campaign: template engine + personalisasi AI oleh agen Content Alchemist."""
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

    res["ai_enriched"] = False
    try:
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
            enriched = await asyncio.wait_for(
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
        logger.warning(
            f"Enrichment affiliate AI gagal — pakai template: "
            f"{type(aff_ai_err).__name__}: {aff_ai_err}\n{_tb.format_exc()[-600:]}")

    return {"status": "success", "result": res}


@swarm_router.post("/api/affiliate/broadcast")
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


@swarm_router.post("/api/video/generate")
async def generate_promo_video(payload: Dict[str, Any]):
    """Generate 9:16 vertical promo video from images and script."""
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

    res = await asyncio.to_thread(_render)
    return res


# --- Autonomous AI Workforce & Custom Agent Endpoints ---

@swarm_router.get("/api/agents")
async def get_custom_agents():
    """List all custom agents in the workforce."""
    agents = database.list_custom_agents_sync()
    return {"status": "success", "total": len(agents), "agents": agents}


@swarm_router.post("/api/agents")
async def create_custom_agent(payload: Dict[str, Any]):
    """Create a new specialized AI agent."""
    name = payload.get("name")
    role = payload.get("role")
    persona = payload.get("persona", "")
    system_instruction = payload.get("system_instruction", "")
    provider = payload.get("provider", "gemini")
    model = payload.get("model", "gemini-3.6-flash")
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


@swarm_router.put("/api/agents/{agent_id}")
async def update_custom_agent_endpoint(agent_id: int, payload: Dict[str, Any]):
    """Update custom agent configuration."""
    res = database.update_custom_agent_sync(agent_id, payload)
    return res


@swarm_router.delete("/api/agents/{agent_id}")
async def delete_custom_agent_endpoint(agent_id: int):
    """Delete a custom agent."""
    res = database.delete_custom_agent_sync(agent_id)
    return res


@swarm_router.post("/api/agents/{agent_id}/chat")
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

@swarm_router.post("/api/meetings/start")
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


@swarm_router.post("/api/meetings/cancel")
async def cancel_agent_meeting():
    """Minta pembatalan eksekusi swarm yang sedang berjalan (lintas proses)."""
    import swarm_engine
    ok = swarm_engine.request_cancel_swarm()
    if ok:
        return {"status": "success", "message": "Sinyal pembatalan terkirim — swarm berhenti setelah langkah berjalan selesai."}
    return {"status": "error", "message": "Tidak ada sesi swarm yang sedang berjalan."}


@swarm_router.get("/api/swarm/live")
async def swarm_live_feed(since: int = 0):
    """Realtime terminal feed of what the swarm agents are doing right now."""
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
                        e = json.loads(line)
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


@swarm_router.get("/api/swarm/folders")
async def swarm_list_folders():
    """Daftar folder proyek yang bisa dipilih sebagai target edit agen."""
    candidates = []

    def _add(root: str, label_prefix: str):
        try:
            if not os.path.isdir(root):
                return
            for d in sorted(os.listdir(root)):
                p = os.path.join(root, d)
                if os.path.isdir(p) and not d.startswith("."):
                    candidates.append({"path": p, "label": f"{label_prefix}/{d}"})
        except Exception:
            pass

    _add("/dev/shm/alfa_sandbox", "sandbox")
    _add(os.path.expanduser("~/Dokumen/ALFA_SWARM_OUTPUTS/websites"), "outputs/websites")
    _add(os.path.expanduser("~/alfa_projects"), "alfa_projects")
    return {"folders": candidates}


@swarm_router.get("/api/meetings")
async def list_meetings(limit: int = 50):
    """List recent multi-agent meetings."""
    meetings = database.list_agent_meetings_sync(limit=limit)
    return {"status": "success", "total": len(meetings), "meetings": meetings}


@swarm_router.get("/api/meetings/{meeting_id}")
async def get_meeting_details(meeting_id: int):
    """Fetch complete transcript, consensus, and action plan of a meeting."""
    details = database.get_agent_meeting_sync(meeting_id)
    if not details:
        raise HTTPException(status_code=404, detail="Meeting not found")
    return {"status": "success", "meeting": details}


@swarm_router.get("/api/meeting/history")
async def get_meeting_history(limit: int = 50):
    """Get AI agent meeting history from SQLite (real data)."""
    try:
        with database.get_sync_db() as conn:
            rows = conn.execute(
                """SELECT id, title, topic, mode, status, participants,
                          consensus, action_plan, created_at
                   FROM agent_meetings ORDER BY id DESC LIMIT ?""",
                (limit,)
            ).fetchall()
        meetings = []
        for r in rows:
            m = dict(r)
            try:
                m["participants"] = json.loads(m.get("participants") or "[]")
            except Exception:
                pass
            meetings.append(m)
        return {"status": "success", "total": len(meetings), "meetings": meetings}
    except Exception as e:
        return {"status": "error", "message": str(e), "meetings": []}


# --- Live Agent Activity & Real-Time Autonomous Execution ---

@swarm_router.get("/api/agent-activity")
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


@swarm_router.post("/api/agents/{agent_id}/execute")
async def execute_agent_task(agent_id: int, payload: Dict[str, Any]):
    """Directly dispatch an autonomous task to a specialized agent with real tool execution."""
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
        if any(kw in instruction.lower() for kw in ["git", "ps", "top", "ram", "cpu", "disk", "ls", "systemctl", "curl", "free"]):
            tool_called = "execute_bash_command"
            tool_input = instruction
            action_type = "bash_exec"
            res = tools.execute_bash_command(instruction)
            tool_output_str = res.get("stdout") or res.get("output") or res.get("message") or res.get("stderr") or "Done (exit code 0)"

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
