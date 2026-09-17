"""
Step executor, task decomposition, and verification logic for ALFA Swarm agents.
"""

import ast
import glob
import json
import logging
import os
import re
import shutil
import time
from datetime import datetime
from typing import Any

from alfa import tools
from alfa.core import database
from alfa.swarm.live_logger import log_live
from alfa.swarm.llm_client import generate_agent_response
from alfa.swarm.workspace_hygiene import (
    _EXEC_FS_SNAPSHOT,
    _get_swarm_output_dir,
    _get_target_folder,
    _hash_sandbox_projects,
)

logger = logging.getLogger(__name__)


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
        return text[low.index("<html") :].strip()
    return ""


def validate_python_code(code: str) -> str:
    """Return an error message if code is empty, trivial, or syntactically invalid; '' if OK."""
    cleaned = (code or "").strip()
    if len(cleaned) < 30:
        return "kode kosong atau terlalu pendek untuk dijalankan"
    try:
        ast.parse(cleaned)
    except SyntaxError as syn_err:
        return f"syntax error di baris {syn_err.lineno}: {syn_err.msg}"
    return ""


async def _decompose_task(
    topic: str, participants: list[dict[str, Any]]
) -> dict[str, str]:
    """Ask the planner to break the topic into one concrete subtask per agent."""
    roster = ", ".join(f"{a['name']} ({a.get('role','')})" for a in participants)
    prompt = (
        f"Anda misi planner swarm. TOPIK: {topic}\n"
        f"TIM: {roster}\n\n"
        "Pecah topik ini menjadi SATU subtask konkret dan dapat dieksekusi sistem "
        "(bukan rencana abstrak) untuk setiap anggota tim.\n"
        "Balas HANYA array JSON tanpa teks lain: "
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


async def _verify_step_result(task: str, step_result: dict[str, Any]) -> tuple:
    """LLM judge for a swarm execution step. Returns (passed: bool, feedback: str)."""
    low_task = (task or "").lower()
    claims_file_work = any(
        k in low_task
        for k in (
            "bangun",
            "buat",
            "perbaiki",
            "sempurnakan",
            "refactor",
            "tulis",
            "kode",
            "website",
            "aplikasi",
            "file",
            "deploy",
            "komponen",
            "halaman",
        )
    )

    fs_changed = None
    changed_sample: list[str] = []
    if claims_file_work and step_result.get("status") == "success":
        fs_changed = step_result.get("fs_changed")
        if fs_changed is None and _EXEC_FS_SNAPSHOT:
            fs_changed = len(_hash_sandbox_projects()) != len(
                _EXEC_FS_SNAPSHOT
            ) or bool(set(_hash_sandbox_projects()) ^ set(_EXEC_FS_SNAPSHOT))
        if fs_changed == 0:
            log_live(
                "VERIFY",
                "🚫 GROUND-TRUTH: tidak ada file proyek berubah -> klaim eksekusi ditolak mekanis",
            )
            return False, (
                "FAIL: GROUND-TRUTH FILESYSTEM - tidak ada satu pun file proyek "
                "yang berubah. Kerjakan nyata dan tulis perubahan ke folder kerja."
            )
        changed_sample = step_result.get("changed_sample") or []

    summary = (step_result.get("execution_summary") or "")[:600]
    fs_evidence = ""
    if claims_file_work and fs_changed is not None:
        samp = (
            "; ".join(changed_sample[:4]) if changed_sample else "(detail tak tersedia)"
        )
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
        return True, ""


async def _single_shot_edit_fallback(
    agent: dict[str, Any], task_instruction: str, target_folder: str
) -> str:
    """Penyelesai pamungkas: minta KONTEN PENUH satu file utama dari model,
    lalu engine menulisnya sendiri (tanpa bergantung tool-call model)."""
    cands = []
    for pat in (
        "index.html",
        "page.html",
        "*.html",
        "*.htm",
        "main.py",
        "app.py",
        "*.py",
        "*.md",
    ):
        cands += [
            p
            for p in glob.glob(os.path.join(target_folder, "**", pat), recursive=True)
            if "node_modules" not in p
        ]
    cands = sorted(set(cands), key=lambda p: os.path.getmtime(p), reverse=True)
    main_file = (
        cands[0]
        if cands
        else os.path.join(
            target_folder,
            re.sub(r"[^a-z0-9]+", "-", task_instruction.lower())[:30].strip("-")
            + ".html",
        )
    )
    ext = os.path.splitext(main_file)[1].lower()
    fmt_hint = (
        "Dokumen HTML5 utuh mulai <!DOCTYPE html>."
        if ext.startswith(".h")
        else "Kode sumber lengkap tanpa penjelasan."
    )
    prompt = (
        f"Tugas: {task_instruction[:400]}\n\n"
        f"Kembalikan HANYA isi penuh TERBARU untuk file `{main_file}` "
        f"setelah tugas diterapkan. {fmt_hint} "
        f"Tanpa penjelasan, tanpa fence markdown."
    )
    content = await generate_agent_response(
        agent,
        prompt,
        "Kamu code generator. Output = isi file mentah saja.",
        max_tokens=8000,
        timeout_s=300.0,
    )
    if not content or len(content.strip()) < 20:
        return "(single-shot) konten kosong dari model"
    content = content.strip()
    if content.startswith("```"):
        content = re.sub(r"^```[a-zA-Z]*\n?", "", content)
        content = re.sub(r"\n?```$", "", content)
    try:
        res = tools.write_local_file(file_path=main_file, content=content)
        st = (res or {}).get("status", "?") if isinstance(res, dict) else "?"
        log_live("FILE", f"📝 single-shot write {os.path.basename(main_file)} -> {st}")
        return f"(single-shot) {main_file} diperbarui ({len(content)} char)"
    except Exception as w_err:
        return f"(single-shot) gagal tulis: {w_err}"


async def _forced_json_execution(agent: dict[str, Any], task_instruction: str) -> str:
    """Eksekusi deterministik: model hanya menyusun rencana JSON aksi tool,
    engine-lah yang menjalankannya."""
    plan_sys = (
        "Kamu execution planner. Output HANYA array JSON murni (tanpa teks lain) "
        "berisi aksi tool berurutan untuk menyelesaikan tugas. Skema aksi:\n"
        '[{"tool":"write_local_file","path":"/abs/file","content":"isi file"},\n'
        ' {"tool":"edit_file_precise","path":"/abs/file","old_text":"...","new_text":"..."},\n'
        ' {"tool":"execute_bash_command","command":"...","working_dir":"/abs/folder"}]\n'
        "Gunakan path ABSOLUT folder kerja. Konten file ditulis penuh di JSON."
    )
    raw = await generate_agent_response(
        agent,
        "TUGAS:\n" + task_instruction[:1500],
        plan_sys,
        max_tokens=4000,
        timeout_s=240.0,
    )
    if not raw:
        return "(forced-exec) planner tidak merespons"

    m = re.search(r"\[.*\]", raw, re.DOTALL)
    if not m:
        return f"(forced-exec) rencana tidak valid: {raw[:120]}"

    try:
        actions = json.loads(m.group(0))
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


async def execute_swarm_task_step(
    agent: dict[str, Any],
    task_instruction: str,
    topic: str,
    intent_info: dict[str, Any],
) -> dict[str, Any]:
    """
    Executes a real action for an agent in Swarm Live Execution mode.
    Calls appropriate system tools, writes files, scrapes data, or tests code.
    """
    t0 = time.time()
    agent_name = agent.get("name", "Agent")
    role = agent.get("role", "Specialist")
    agent_id = agent.get("id", 1)

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

    swarm_out_dir = _get_swarm_output_dir()
    target_folder = _get_target_folder()

    # 1. SPECIALIST: RESEARCHER PRIME (Deep Scraping & Real Web Intelligence)
    if (
        "Research" in agent_name
        or "Intel" in role
        or (intent_info.get("is_scrape") and "Prime" in agent_name)
    ):
        tool_name = "universal_deep_scraper"
        search_query = intent_info.get("clean_query") or topic
        cat = intent_info.get("category", "all_marketplace")
        limit = intent_info.get("limit", 20)

        try:
            scrape_res = tools.universal_deep_scraper(
                query=search_query, category=cat, limit=limit
            )
            total = scrape_res.get("total_scraped", len(scrape_res.get("items", [])))
            csv_path = scrape_res.get("csv_path") or scrape_res.get("csv_file", "")
            items = scrape_res.get("items") or scrape_res.get("results", [])

            if csv_path and os.path.exists(csv_path):
                dest_csv = os.path.join(swarm_out_dir, os.path.basename(csv_path))
                shutil.copyfile(csv_path, dest_csv)
                deliverable_file = dest_csv

            top_items_text = "\n".join(
                [
                    f"{i+1}. {it.get('title', '')[:50]} | {it.get('price') or it.get('price_tag', 'N/A')} ({it.get('domain') or it.get('source_domain', 'Market')})"
                    for i, it in enumerate(items[:8])
                ]
            )

            tool_output = f"✅ Scraping Berhasil: {total} data nyata berhasil ditarik!\n📁 File CSV: {deliverable_file}\n\nSampel Data Teratas:\n{top_items_text}"
            deliverable_data = items[:10]
            generated_content = f"Gue udah scrape langsung {total} data nyata untuk target `{search_query}` di kategori `{cat}`. File CSV tersimpan di `{deliverable_file}` dan siap dianalisis!"

        except Exception as e:
            status = "error"
            tool_output = f"Error in Deep Scraper: {str(e)}"
            generated_content = f"Gagal mengeksekusi scraper: {str(e)}"

    # 2. EKSEKUSI AGENTIK UMUM — semua agen memakai tool sesuai subtasknya.
    else:
        tool_name = "agentic_autonomous"
        work_agent = {**agent, "enable_tools": 1}
        folder_rule = ""
        if target_folder and os.path.isdir(target_folder):
            folder_rule = (
                f"\nFOLDER KERJA WAJIB: {target_folder}\n"
                f"PADA execute_bash_command: WAJIB working_dir='{target_folder}' "
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
            work_agent,
            exec_prompt,
            "Kamu agen pelaksana swarm. KERJA MENGGUNAKAN TOOL: setiap giliranmu WAJIB "
            "memuat panggilan function call (read_local_file / edit_file_precise / "
            "write_local_file / execute_bash_command / web_search). Membalas teks saja "
            "tanpa memanggil tool dianggap GAGAL.",
            max_tokens=3000,
            timeout_s=300.0,
        )

        if generated_content is None or str(generated_content).startswith("[Error:"):
            status = "error"
            tool_output = (
                "SEMUA provider gagal (kuota/kunci/jaringan) — langkah dibatalkan"
            )
            generated_content = "(gagal: tidak ada respons dari provider mana pun)"

        post_hash = _hash_sandbox_projects()
        changed_files = [
            p
            for p in set(pre_hash) | set(post_hash)
            if pre_hash.get(p) != post_hash.get(p)
        ]
        step_fs_changed = len(changed_files)
        if step_fs_changed == 0 and status == "success":
            log_live(
                "EXEC",
                "🔄 Tidak ada file berubah -> beralih ke forced-JSON execution...",
            )
            generated_content = await _forced_json_execution(
                work_agent, task_instruction
            )
            post_hash = _hash_sandbox_projects()
            changed_files = [
                p
                for p in set(pre_hash) | set(post_hash)
                if pre_hash.get(p) != post_hash.get(p)
            ]
            step_fs_changed = len(changed_files)
        if step_fs_changed == 0 and status == "success":
            if target_folder and os.path.isdir(target_folder):
                log_live("EXEC", "🛟 Single-shot edit fallback dijalankan...")
                generated_content = await _single_shot_edit_fallback(
                    work_agent, task_instruction, target_folder
                )
                post_hash = _hash_sandbox_projects()
                changed_files = [
                    p
                    for p in set(pre_hash) | set(post_hash)
                    if pre_hash.get(p) != post_hash.get(p)
                ]
                step_fs_changed = len(changed_files)
            else:
                generated_content = await _forced_json_execution(
                    work_agent, task_instruction
                )
        if changed_files:
            sample = "; ".join(os.path.basename(p) for p in changed_files[:3])
            tool_output = (
                f"{len(generated_content or '')} char respons; "
                f"{step_fs_changed} file berubah: {sample}"
            )
        else:
            tool_output = (
                f"{len(generated_content or '')} char respons; TIDAK ada file berubah"
            )

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
        duration_ms=duration_ms,
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
        "timestamp": datetime.now().strftime("%H:%M:%S"),
    }
