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
) -> dict[str, Any]:
    """Ask the planner to break the topic into one concrete subtask per agent with dependencies."""
    roster = ", ".join(f"{a['name']} ({a.get('role', '')})" for a in participants)
    prompt = (
        f"Anda misi planner swarm. TOPIK: {topic}\n"
        f"TIM: {roster}\n\n"
        "Pecah topik ini menjadi SATU subtask konkret dan dapat dieksekusi sistem "
        "(bukan rencana abstrak) untuk setiap anggota tim.\n"
        "Setiap subtask WAJIB diakhiri deliverable file konkret "
        "(mis. '... dan tulis hasilnya ke LAPORAN-<TOPIK>.md').\n"
        "Tentukan juga 'depends_on', yaitu daftar nama anggota tim lain yang tugasnya harus selesai SEBELUM tugas ini bisa dimulai (boleh kosong jika bisa paralel).\n"
        "Balas HANYA array JSON tanpa teks lain: "
        '[{"name": "<nama persis dari tim>", "task": "<instruksi spesifik maksimal 25 kata>", "depends_on": ["<nama_agen_lain>"]}]'
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
            deps = (it or {}).get("depends_on", [])
            if not isinstance(deps, list):
                deps = []
            deps = [d.strip() for d in deps if d.strip() in valid_names and d.strip() != nm]
            if nm in valid_names and tk:
                mapping[nm] = {"task": tk, "depends_on": deps}
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

    # Judge terkonfigurasi: ALFA_SWARM_JUDGE=mechanical melewati panggilan LLM
    # dan hanya memakai bukti mekanis (hemat kuota, deterministik, offline-safe).
    if os.getenv("ALFA_SWARM_JUDGE", "auto").strip().lower() == "mechanical":
        if claims_file_work and fs_changed:
            return True, ""
        if step_result.get("status") == "success" and step_result.get("tool_used"):
            return True, ""
        return False, "FAIL: mechanical judge — tidak ada bukti eksekusi nyata"

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
        # Terima "PASS" walau diawali teks pendek, TOLAK bila ada "FAIL".
        if "PASS" in v and "FAIL" not in v:
            return True, ""
        fb = verdict.strip() if verdict else "verifier tidak merespons"
        return False, fb[:200]
    except Exception as ver_err:
        # Judge tidak bisa dihubungi. Dulu selalu return True (fail-open) sehingga
        # step gagal pun lolos begitu saja. Sekarang pakai bukti mekanis yang sudah
        # dikumpulkan di atas, dan hanya PASS bila memang ada tanda eksekusi nyata.
        logger.warning(
            "Verification call failed (using mechanical fallback): %r", ver_err
        )
        if claims_file_work and fs_changed:
            return True, ""
        status_ok = step_result.get("status") == "success"
        has_tool = bool(step_result.get("tool_used"))
        if status_ok and has_tool:
            return True, ""
        return False, "verifier offline dan tidak ada bukti eksekusi nyata"


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

    allowed: dict[str, Any] = {
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
            logs.append(f"{i + 1}. {tool_nm} -> {st}")
            log_live("TOOL", f"⚙️ forced-exec {tool_nm} -> {st} | {hint}")
        except Exception as ex:
            logs.append(f"{i + 1}. {tool_nm} -> EXC {str(ex)[:80]}")
            log_live("TOOL", f"⚠️ forced-exec {tool_nm} error: {str(ex)[:80]}")
    return "Hasil eksekusi deterministik (forced-JSON):\n" + "\n".join(logs)


# ── Gate deep scraping (hindari scrape tiap langkah bila tidak diperlukan) ────
#
# Sebelum: agent bernama "Research"/role "Intel"/(is_scrape & Prime) SELALU
# memanggil `universal_deep_scraper` — termasuk langkah tulis-ringkasan /
# analisa, dan berulang tiap langkah Prime dalam satu run (hit jaringan
# berulang + lambat).
#
# Sekarang: scraping hanya bila langkah (atau intent turn) benar-benar minta
# data eksternal, dan maksimal sekali per (topic, agent) untuk sinyal intent
# — sinyal eksplisit di instruksi langkah ("scrape", "csv", dst.) selalu
# diizinkan menembus dedupe.

_SCRAPE_TASK_RE = re.compile(
    r"(?i)\b(scrap\w+|grab\w+|sedot|csv|kumpulk\w+|gather\w*|collect\w+|carik\w+|"
    r"ambil\s+data|cari\s+data|daftar\s+(produk|harga|supplier|kontak|lowongan)|"
    r"list\s+(products?|prices?|suppliers?|contacts?|vacanc\w+)|terlaris|terpopuler|"
    r"top\s+\d+|marketplace|shopee|tokopedia|tokped|lazada|tik\s?tok\s?shop|"
    r"e-?commerce|lowongan|supplier|leads)\b"
)

_scraped_once_keys: set[tuple[str, str]] = set()


def _reset_scrape_state() -> None:
    """Pembersih state dedupe (dipakai test & run baru)."""
    _scraped_once_keys.clear()


def _step_needs_deep_scrape(
    agent_name: str,
    role: str,
    task_instruction: str,
    intent_info: dict[str, Any] | None,
) -> tuple[bool, str]:
    """Keputusan: langkah ini perlu deep scraper atau tidak.

    Returns:
        (perlu_scrape, alasan_skip) — ``alasan_skip`` hanya diisi bila agent
        tipe riset tapi TIDAK jalan scraper (untuk log/transparansi).
    """
    intent_info = intent_info or {}
    can_scrape = (
        "Research" in agent_name or "Intel" in role or "Prime" in agent_name
    )
    if not can_scrape:
        return False, ""

    task_l = (task_instruction or "").lower()
    task_signal = bool(_SCRAPE_TASK_RE.search(task_l))
    intent_signal = bool(intent_info.get("is_scrape"))

    if not task_signal and not intent_signal:
        return (
            False,
            "agent riset ada, tapi langkah ini tidak meminta pengambilan "
            "data eksternal → jalur agentic biasa",
        )

    if task_signal:
        # instruksi eksplisit selalu boleh scrape; tetap tandai run ini sudah
        # melakukan scraping agar langkah intent-only berikutnya skip
        clean_query = str(intent_info.get("clean_query") or "")[:64]
        _scraped_once_keys.add((clean_query, agent_name))
        return True, ""

    # sinyal intent-only: scrape maksimal SEKALI per (topic, agent) dalam run
    clean_query = str(intent_info.get("clean_query") or "")[:64]
    key = (clean_query, agent_name)
    if key in _scraped_once_keys:
        return False, "deep scraping sudah dilakukan untuk run ini → skip"
    _scraped_once_keys.add(key)
    return True, ""


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
    generated_content: str | None = ""

    swarm_out_dir = _get_swarm_output_dir()
    target_folder = _get_target_folder()

    # 1. SPECIALIST: RESEARCHER PRIME (Deep Scraping & Real Web Intelligence)
    #    Gate dulu: hanya bila langkah/intent benar-benar butuh data eksternal,
    #    dan maksimal sekali per run utk sinyal intent (lihat helper).
    scrape_ok, scrape_skip_reason = _step_needs_deep_scrape(
        agent_name, role, task_instruction, intent_info
    )
    if scrape_skip_reason:
        log_live(
            "PLAN",
            f"⏭️ {agent_name} skip deep scraping — {scrape_skip_reason}",
        )
    if scrape_ok:
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
                    f"{i + 1}. {it.get('title', '')[:50]} | {it.get('price') or it.get('price_tag', 'N/A')} ({it.get('domain') or it.get('source_domain', 'Market')})"
                    for i, it in enumerate(items[:8])
                ]
            )

            tool_output = f"✅ Scraping Berhasil: {total} data nyata berhasil ditarik!\n📁 File CSV: {deliverable_file}\n\nSampel Data Teratas:\n{top_items_text}"
            deliverable_data = items[:10]
            generated_content = f"Gue udah scrape langsung {total} data nyata untuk target `{search_query}` di kategori `{cat}`. File CSV tersimpan di `{deliverable_file}` dan siap dianalisis!"

            if total == 0 or not items:
                # Scraper/Bencana koneksi mengembalikan NOL — fallback jujur via web_search + tulis laporan.
                log_live("EXEC", "🔄 Scraper 0 hasil -> fallback web_search + LAPORAN-Riset.md...")
                fb_lines, fb_n = [], 0
                try:
                    for q in (search_query, f"{search_query} rekomendasi terbaik"):
                        try:
                            ws = tools.web_search(query=q, max_results=8)
                        except TypeError:
                            ws = tools.web_search(q)
                        found = (ws.get("results") or ws.get("items") or []) if isinstance(ws, dict) else []
                        for it in found[:8]:
                            if isinstance(it, dict):
                                fb_lines.append(f"- {(it.get('title') or '?')[:80]} | {(it.get('url') or it.get('link') or '')[:80]}")
                        fb_n += len(found)
                        if fb_n >= 8:
                            break
                except Exception as ws_err:
                    logger.warning(f"[research-fallback] web_search gagal: {ws_err}")
                rep_path = os.path.join(swarm_out_dir, "LAPORAN-Riset.md")
                try:
                    with open(rep_path, "w") as rf:
                        rf.write(f"# Laporan Riset: {search_query}\n\nSumber: web_search (fallback scraper, {fb_n} hasil)\n\n" + ("\n".join(fb_lines) if fb_lines else "Tidak ada hasil dari semua sumber.") + "\n")
                    deliverable_file = rep_path
                except OSError as w_err:
                    logger.warning(f"[research-fallback] tulis laporan gagal: {w_err}")
                if fb_n:
                    tool_output = f"⚠️ Scraper 0 hasil — fallback web_search: {fb_n} hasil nyata tersimpan di {deliverable_file}"
                    generated_content = f"Scraper buntu (koneksi), gue ambil {fb_n} hasil via web_search dan tulis ke `{deliverable_file}`."
                else:
                    status = "error"
                    tool_output = "SEMUA sumber riset gagal (scraper 0 + web_search 0) — dilaporkan GAGAL jujur"
                    generated_content = "(gagal: tidak ada data dari sumber mana pun)"

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
            f"=== ATURAN JUJUR (WAJIB) ===\n"
            f"1. Akhiri dengan label SELESAI / SEBAGIAN / GAGAL sesuai bukti — dilarang klaim SELESAI bila sebagian.\n"
            f"2. Dilarang label neural/AI/teruji/production-ready/tanpa bug tanpa bukti (hasil tes, file nyata). Pola regex/AST = sebut heuristik, bukan neural.\n"
            f"3. Dilarang dummy sebagai hasil asli. Angka hanya dari output tool.\n"
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
