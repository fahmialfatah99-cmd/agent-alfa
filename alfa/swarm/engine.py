# -*- coding: utf-8 -*-
"""
Autonomous Multi-Agent Swarm & Meeting Engine for ALFA Ecosystem.
Enables round-table AI meetings, inter-agent dialogue, debate, consensus building,
and live autonomous collaborative execution (Swarm Work Mode with REAL tools, files, and scraping).

Modularized structure:
- workspace_hygiene: Sandboxing, snapshots, sanitization, harvesting
- live_logger: JSONL feed, terminal logging, intent analysis, QA verdict checking
- llm_client: Multi-provider client (Gemini, OpenAI, 9router, DeepSeek, etc.)
- step_executor: Autonomous task steps, verification, and fallback runners
- engine: Orchestration coordinator (conduct_multi_agent_meeting & resume_swarm_session)
"""

import asyncio
import logging
import os
import re
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from alfa import tools
from alfa.core import database
from alfa.swarm.live_logger import (
    _CHECKPOINT_AVAILABLE,
    _append_feed_file,
    _build_error_context,
    _load_last_seq,
    _record_step_error,
    _SwarmCheckpoint,
    detect_task_intent,
    log_live,
    log_tool_live,
    qa_verdict_passed,
)
from alfa.swarm.llm_client import (
    KNOWN_OPENAI_PROVIDERS,
    _default_gemini_model,
    _generate_with_gemini,
    _generate_with_openai_compat,
    generate_agent_response,
    get_agent_api_client,
)
from alfa.swarm.step_executor import (
    _decompose_task,
    _extract_html_doc,
    _forced_json_execution,
    _single_shot_edit_fallback,
    _verify_step_result,
    execute_swarm_task_step,
    validate_python_code,
)
from alfa.swarm.workspace_hygiene import (
    _EXEC_FS_SNAPSHOT,
    _HARVEST_EXCLUDE,
    _JUNK_FILE_PATTERNS,
    _SANDBOX_SNAPSHOT,
    _TARGET_FOLDER,
    CANCEL_FLAG_FILE,
    LIVE_FEED_FILE,
    LIVE_LOG,
    MAX_QA_ROUNDS,
    MAX_SWARM_AGENTS,
    MEETING_RUNNING,
    SWARM_OUTPUT_DIR,
    _cancel_requested,
    _clear_cancel_flag,
    _fs_changed_since_snapshot,
    _harvest_new_sandbox_projects,
    _hash_sandbox_projects,
    _sandbox_project_dirs,
    request_cancel_swarm,
    sanitize_project_directory,
)

logger = logging.getLogger(__name__)


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
    """
    from alfa.swarm import workspace_hygiene

    mode = "execute"
    session_id = session_id or f"swarm_{int(time.time())}_{uuid.uuid4().hex[:6]}"

    # Folder target kerja agen
    global _TARGET_FOLDER
    _TARGET_FOLDER = ""
    workspace_hygiene._TARGET_FOLDER = ""
    if target_folder and str(target_folder).strip():
        tf = os.path.realpath(os.path.expanduser(str(target_folder).strip()))
        if os.path.isdir(tf):
            _TARGET_FOLDER = tf
            workspace_hygiene._TARGET_FOLDER = tf
            log_live("TARGET", f"📁 Folder kerja agen: {_TARGET_FOLDER}")
        else:
            log_live(
                "TARGET",
                f"⚠️ Folder '{target_folder}' tidak ada — agen bebas memilih lokasi.",
            )

    # AUTO-CREATE: prompt bertema membangun tapi tanpa folder pilihan
    if not _TARGET_FOLDER:
        build_kw = (
            "buat",
            "bangun",
            "rancang",
            "bikin",
            "website",
            "web ",
            "aplikasi",
            "landing",
            "dashboard",
            "desain",
            "design",
            "script",
            "skrip",
            "program",
            "refactor",
            "perbaiki tampilan",
        )
        if any(k in topic.lower() for k in build_kw):
            slug = (
                re.sub(r"[^a-z0-9]+", "-", topic.lower())[:42].strip("-")
                or "proyek-baru"
            )
            nf = os.path.join(tools.SANDBOX_DIR, f"{slug}_{int(time.time()) % 100000}")
            try:
                os.makedirs(nf, exist_ok=True)
                _TARGET_FOLDER = nf
                workspace_hygiene._TARGET_FOLDER = nf
                log_live("TARGET", f"📁 Folder proyek baru dibuat otomatis: {nf}")
            except OSError as mk_err:
                log_live("TARGET", f"⚠️ Gagal buat folder otomatis: {mk_err}")

    intent_info = detect_task_intent(topic)

    all_agents = database.list_custom_agents_sync()
    if not all_agents:
        database.init_db_sync()
        all_agents = database.list_custom_agents_sync()

    if participant_names:
        participants = [
            a
            for a in all_agents
            if a["name"] in participant_names and a.get("is_enabled", 1)
        ]
    else:
        participants = [a for a in all_agents if a.get("is_enabled", 1)][
            :MAX_SWARM_AGENTS
        ]

    if not participants:
        participants = all_agents[:3]

    if _CHECKPOINT_AVAILABLE and _SwarmCheckpoint:
        try:
            _SwarmCheckpoint.save(
                session_id=session_id,
                topic=topic,
                mode=mode,
                participants=participants,
                steps=[],
                steps_done=0,
                status="running",
            )
        except Exception:
            pass

    dialogue_transcript = []
    history_summary = []
    execution_steps = []

    meeting_type_label = (
        "⚡ SWARM EKSEKUSI LANGSUNG"
        if mode in ["execute", "plan_and_execute"]
        else "📋 RAPAT STRATEGIS & PLAN"
    )
    meeting_title = f"{meeting_type_label}: {topic[:60]}"

    logger.info(
        f"🏛️ Starting AI Session [{mode.upper()}] on topic: '{topic}' with {len(participants)} agents (session: {session_id})."
    )
    workspace_hygiene.MEETING_RUNNING = True
    _clear_cancel_flag()
    log_live(
        "SESSION",
        f"Sesi {mode.upper()} dimulai — topik: {topic[:80]} ({len(participants)} agen)",
    )

    _SANDBOX_SNAPSHOT.clear()
    _SANDBOX_SNAPSHOT.update(_sandbox_project_dirs())
    workspace_hygiene._SANDBOX_SNAPSHOT.clear()
    workspace_hygiene._SANDBOX_SNAPSHOT.update(_sandbox_project_dirs())

    if mode == "execute":
        _EXEC_FS_SNAPSHOT.clear()
        _EXEC_FS_SNAPSHOT.update(_hash_sandbox_projects())
        workspace_hygiene._EXEC_FS_SNAPSHOT.clear()
        workspace_hygiene._EXEC_FS_SNAPSHOT.update(_hash_sandbox_projects())
        if _TARGET_FOLDER:
            os.environ["ALFA_TARGET_FOLDER"] = _TARGET_FOLDER
        else:
            os.environ.pop("ALFA_TARGET_FOLDER", None)

    actual_rounds = 0
    for r in range(1, actual_rounds + 1):
        for agent in participants:
            context_text = (
                "\n".join(history_summary)
                if history_summary
                else "(Sesi baru saja dibuka oleh Alpha Lead)"
            )
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

            response_text = (
                await generate_agent_response(
                    agent=agent,
                    prompt=prompt,
                    system_instruction=agent.get(
                        "system_instruction",
                        "Kamu adalah anggota tim AI otonom profesional.",
                    ),
                )
                or "(tidak merespons — semua provider gagal)"
            )

            entry = {
                "round": r,
                "agent_name": agent["name"],
                "role": agent["role"],
                "avatar_emoji": agent.get("avatar_emoji", "🤖"),
                "color_theme": agent.get("color_theme", "cyan"),
                "message": response_text,
                "timestamp": datetime.now().strftime("%H:%M:%S"),
            }
            dialogue_transcript.append(entry)
            history_summary.append(
                f"[{agent['name']} - {agent['role']}]:\n{response_text}\n"
            )
            log_live("DIALOG", f"💬 {entry['agent_name']}: {response_text[:140]}")

    swarm_cancelled = False
    if mode in ["execute", "plan_and_execute"]:
        logger.info(
            f"⚡ Launching Live Autonomous Swarm Execution for {len(participants)} agents..."
        )

        subtask_map = await _decompose_task(topic, participants)
        if subtask_map:
            logger.info("Task decomposition OK: %s", list(subtask_map.keys()))
            for _n, _t in subtask_map.items():
                log_live("PLAN", f"🗂️ {_n}: {_t[:90]}")

        failed_steps: List[Dict[str, Any]] = []
        ctx_lines: List[str] = []

        _parallel = os.getenv("ALFA_SWARM_PARALLEL", "on").strip().lower() != "off"
        try:
            _wave_size = max(1, int(os.getenv("ALFA_SWARM_MAX_CONCURRENT", "3")))
        except ValueError:
            _wave_size = 3
        if not _parallel:
            _wave_size = 1

        def _build_task_desc(agent: Dict[str, Any], err_ctx: str) -> str:
            td = (
                subtask_map.get(agent["name"])
                or f"Eksekusi modul {agent['role']} untuk '{topic[:60]}'"
            )
            if err_ctx:
                td += f"\n\n{err_ctx}"
            target_fol = workspace_hygiene._get_target_folder()
            if target_fol:
                td += (
                    f"\n\nFOLDER KERJA WAJIB: {target_fol}\n"
                    f"SEMUA file yang dibaca/ditulis WAJIB di dalam folder ini. "
                    f"Pada execute_bash_command: sertakan working_dir='{target_fol}' "
                    f"dan gunakan PATH RELATIF (folder ter-mount sebagai /workspace). "
                    f"Untuk mengubah isi file, PAKAI edit_file_precise/write_local_file "
                    f"dengan path lengkap '{target_fol}/<nama>'. "
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
            step_result = await execute_swarm_task_step(
                agent, task_desc, topic, intent_info
            )
            if step_result.get("deliverable_file"):
                log_live(
                    "FILE",
                    f"📁 {agent['name']} menghasilkan berkas: {os.path.basename(step_result['deliverable_file'])}",
                )

            passed, feedback = await _verify_step_result(task_desc, step_result)
            attempts = 0
            while (
                not passed
                and attempts < 1
                and step_result.get("tool_used") != "strategic_orchestration"
                and not _cancel_requested()
            ):
                attempts += 1
                logger.warning(
                    f"Step '{agent['name']}' FAILED verification: {feedback} - retrying with corrections..."
                )
                retry_desc = (
                    f"{task_desc}\n"
                    f"PERCOBAAN SEBELUMNYA DITOLAK VERIFIKATOR: {feedback}\n"
                    f"Kerjakan ulang dan pastikan menghasilkan bukti nyata (file/data/output)."
                )
                step_result = await execute_swarm_task_step(
                    agent, retry_desc, topic, intent_info
                )
                step_result["retry_count"] = attempts
                passed, feedback = await _verify_step_result(retry_desc, step_result)
            return step_result, passed, feedback

        for wave_start in range(0, len(participants), _wave_size):
            wave = participants[wave_start : wave_start + _wave_size]
            if _cancel_requested():
                log_live(
                    "CANCEL",
                    f"⏹ Eksekusi dihentikan pengguna sebelum gelombang {wave_start // _wave_size + 1}.",
                )
                swarm_cancelled = True
                if _CHECKPOINT_AVAILABLE and _SwarmCheckpoint:
                    try:
                        _SwarmCheckpoint.mark_cancelled(session_id)
                    except Exception:
                        pass
                break

            err_ctx_snapshot = _build_error_context(failed_steps)

            try:
                wave_results = await asyncio.gather(
                    *[
                        _execute_agent_step(a, _build_task_desc(a, err_ctx_snapshot))
                        for a in wave
                    ],
                    return_exceptions=True,
                )
            except Exception as wave_err:
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

                if (
                    not passed
                    and step_result.get("tool_used") != "strategic_orchestration"
                ):
                    failed_steps.append(
                        {
                            "agent_name": agent["name"],
                            "tool_used": step_result.get("tool_used"),
                            "feedback": feedback,
                            "execution_summary": step_result.get(
                                "execution_summary", ""
                            ),
                        }
                    )
                    _record_step_error(session_id, step_result, feedback)

                step_result["verification"] = (
                    "PASS"
                    if passed
                    else (
                        "FAIL"
                        if step_result.get("tool_used") != "strategic_orchestration"
                        else "N/A"
                    )
                )
                log_live(
                    "VERIFY",
                    f"{'✅ PASS' if passed else '❌ FAIL'} — {agent['name']} ({step_result.get('tool_used')}){(': ' + feedback[:80]) if not passed and feedback else ''}",
                )
                execution_steps.append(step_result)

                if _CHECKPOINT_AVAILABLE and _SwarmCheckpoint:
                    try:
                        _SwarmCheckpoint.save(
                            session_id=session_id,
                            topic=topic,
                            mode=mode,
                            participants=participants,
                            steps=execution_steps,
                            steps_done=len(execution_steps),
                            status="cancelled" if swarm_cancelled else "running",
                        )
                    except Exception:
                        pass

                brief = (step_result.get("execution_summary") or "")[:180].replace(
                    "\n", " "
                )
                ctx_lines.append(f"{step_result['agent_name']} -> {brief}")

    # Sentinel QA Loop
    if (
        mode == "execute"
        and not swarm_cancelled
        and not _cancel_requested()
        and execution_steps
        and MAX_QA_ROUNDS > 0
    ):
        qa_agent = next(
            (
                a
                for a in all_agents
                if a.get("name") == "Sentinel QA" and a.get("is_enabled", 1)
            ),
            None,
        )
        if not qa_agent:
            _qa_kw = ("qa", "audit", "sentinel", "quality", "tester", "uji")
            qa_agent = next(
                (
                    a
                    for a in all_agents
                    if a.get("is_enabled", 1)
                    and (
                        any(k in a.get("name", "").lower() for k in _qa_kw)
                        or any(k in a.get("role", "").lower() for k in _qa_kw)
                    )
                ),
                None,
            )
        if qa_agent:
            fix_feedback = ""
            zero_bug = False
            for qa_round in range(1, MAX_QA_ROUNDS + 1):
                if _cancel_requested():
                    break
                deliverables = [
                    s["deliverable_file"]
                    for s in execution_steps
                    if s.get("deliverable_file")
                ]
                work_summary = "\n".join(
                    f"- {s['agent_name']} ({s.get('tool_used','?')}): {(s.get('execution_summary') or '')[:220]}"
                    for s in execution_steps
                )
                target_fol = workspace_hygiene._get_target_folder()
                log_live(
                    "QA",
                    f"🛡️ Sentinel QA putaran {qa_round}/{MAX_QA_ROUNDS}: menguji hasil kerja tim...",
                )
                qa_task = (
                    f"=== MISI TIM YANG HARUS KAMU UJI ===\n{topic[:120]}\n\n"
                    f"=== HASIL KERJA AGEN (JANGAN DIPERCAYA — BUKTIKAN SENDIRI) ===\n{work_summary}\n"
                    + (
                        f"=== FILE DELIVERABLE ===\n{chr(10).join(deliverables)}\n"
                        if deliverables
                        else ""
                    )
                    + (
                        f"\nFOLDER KERJA: {target_fol} — jalankan file/kode dari sini.\n"
                        if target_fol
                        else ""
                    )
                    + (
                        f"\n=== BUG PUTARAN SEBELUMNYA (diklaim sudah diperbaiki — VERIFIKASI ULANG) ===\n{fix_feedback}\n"
                        if fix_feedback
                        else ""
                    )
                    + "\n=== ATURAN QA ===\n"
                    "1. JALANKAN sendiri kode/file hasil tim via tool (execute_bash_command / read_local_file / sandbox).\n"
                    "2. Catat tiap bug dengan bukti: command + output error.\n"
                    "3. Akhiri respons dengan TEPAT satu baris:\n"
                    "   QA_VERDICT: PASS   (terbukti nol bug)\n"
                    "   QA_VERDICT: FAIL - <daftar bug bernomor + file penyebab>"
                )
                qa_step = await execute_swarm_task_step(
                    qa_agent, qa_task, topic, intent_info
                )
                qa_step["phase"] = f"qa_round_{qa_round}"
                execution_steps.append(qa_step)
                qa_text = str(
                    qa_step.get("generated_content")
                    or qa_step.get("execution_summary")
                    or ""
                )
                if qa_verdict_passed(qa_text):
                    zero_bug = True
                    log_live(
                        "QA", f"✅ ZERO BUG terverifikasi pada putaran {qa_round}."
                    )
                    break

                fix_feedback = qa_text[-1500:]
                log_live(
                    "QA",
                    f"🐞 Bug terdeteksi (putaran {qa_round}) — dikembalikan ke tim pelaksana.",
                )
                fixers = [
                    a for a in participants if a.get("name") != qa_agent.get("name")
                ] or participants
                for fa in fixers:
                    if _cancel_requested():
                        break
                    fix_task = (
                        f"QA MENEMUKAN BUG PADA HASIL KERJA TIM — PERBAIKI BAGIANMU SEKARANG SAMPAI BENAR.\n\n"
                        f"MISI ASLI: {topic[:120]}\n"
                        f"LAPORAN QA (bukti + daftar bug):\n{fix_feedback}\n\n"
                        f"ATURAN PERBAIKAN:\n"
                        f"1. Perbaiki HANYA file/kode yang kamu buat"
                        + (f" (folder {target_fol})." if target_fol else ".")
                        + "\n"
                        "2. Jalankan ulang untuk MEMBUKTIKAN fix bekerja.\n"
                        "3. Laporkan apa yang diubah + bukti hasil uji ulang."
                    )
                    fix_step = await execute_swarm_task_step(
                        fa, fix_task, topic, intent_info
                    )
                    fix_step["phase"] = f"qa_fix_round_{qa_round}"
                    execution_steps.append(fix_step)
                    ctx_lines.append(
                        f"[QA-FIX r{qa_round}] {fa['name']} -> {(fix_step.get('execution_summary') or '')[:150]}"
                    )
            if not zero_bug:
                log_live(
                    "QA",
                    "⚠️ Batas putaran QA habis sebelum zero bug — status dilaporkan apa adanya.",
                )

    if not participants:
        error_msg = (
            "Tidak ada agen yang terdaftar di workforce. "
            "Tambahkan minimal satu agen terlebih dahulu (Dashboard > AI Workforce) sebelum menjalankan rapat swarm."
        )
        logger.error(error_msg)
        workspace_hygiene.MEETING_RUNNING = False
        log_live("ERROR", "Sesi dibatalkan: tidak ada agen terdaftar.")
        return {
            "status": "error",
            "error": error_msg,
            "topic": topic,
            "dialogue_transcript": [],
            "execution_steps": [],
            "consensus": "",
            "action_plan": "",
        }

    lead_agent = participants[0]

    target_fol = workspace_hygiene._get_target_folder()
    if swarm_cancelled or _cancel_requested():
        workspace_hygiene.MEETING_RUNNING = False
        _clear_cancel_flag()
        log_live(
            "DONE",
            f"🏁 Eksekusi swarm DIBATALKAN — {len(execution_steps)} langkah tuntas sebelum berhenti.",
        )
        return {
            "status": "cancelled",
            "meeting_id": None,
            "title": meeting_title,
            "topic": topic,
            "mode": mode,
            "target_folder": target_fol,
            "participants": [a["name"] for a in participants],
            "dialogue_transcript": dialogue_transcript,
            "execution_results": execution_steps,
            "consensus": (
                f"⏹ **Eksekusi dibatalkan pengguna.** {len(execution_steps)} dari "
                f"{len(participants)} agen tuntas dieksekusi sebelum berhenti. "
                "File/hasil yang sudah dibuat tetap tersimpan."
            ),
            "action_plan": "",
        }

    out_dir = workspace_hygiene._get_swarm_output_dir()
    if mode in ["execute", "plan_and_execute"]:
        real_files = [
            s["deliverable_file"] for s in execution_steps if s.get("deliverable_file")
        ]
        real_summaries = "\n".join(
            [
                f"• **{s['agent_name']} ({s['role']})** [Tool: `{s['tool_used']}` | {s['duration_ms']}ms]:\n  {s['execution_summary']}"
                for s in execution_steps
            ]
        )

        consensus_prompt = (
            f"=== TARGET PERINTAH DARI USER ===\n{topic}\n\n"
            f"=== HASIL EKSEKUSI NYATA DARI TOOLS & SYSTEM ===\n{real_summaries}\n\n"
            f"File Output Tersimpan: {', '.join(real_files) if real_files else 'N/A'}\n\n"
            f"Sebagai kapten Swarm ({lead_agent['name']}), buatlah LAPORAN HASIL NYATA YANG LENGKAP & TO-THE-POINT:\n"
            f"1. 🎯 STATUS EKSEKUSI: Jelaskan bahwa tugas SUDAH DIJALANKAN LANGSUNG OLEH TOOLS SISTEM (Bukan sekadar rencana).\n"
            f"2. 📊 HASIL NYATA & DATA: Tampilkan rangkuman data/angka konkret yang didapatkan dari eksekusi di atas.\n"
            f"3. 📁 FILE ARTIFAK SIAP PAKAI: Sebutkan file CSV/Python yang sudah tersimpan di `{out_dir}`.\n"
            f"4. 💡 KESIMPULAN / INSIGHT: Berikan insight praktis atas hasil data/kode tersebut.\n"
            f"Gunakan gaya bicara santai, gaul, tegas, to-the-point!"
        )
    else:
        consensus_prompt = (
            f"=== TOPIK RAPAT ===\n{topic}\n\n"
            f"=== TRANSKRIP LENGKAP DISKUSI TIM ===\n"
            + "\n".join(history_summary)
            + "\n\n"
            f"Sebagai kapten rapat ({lead_agent['name']}), buatlah rangkuman KONSENSUS & ACTION PLAN yang ON-POINT:\n"
            f"1. KONSENSUS UTAMA (Inti kesepakatan tim dalam 2-3 poin ringkas).\n"
            f"2. ACTION PLAN (Tabel tugas terstruktur: No, Modul/Tugas, Penanggung Jawab, Target).\n"
            f"Gunakan gaya bahasa santai, tegas, to-the-point tanpa basa-basi."
        )

    consensus_text = (
        await generate_agent_response(
            agent=lead_agent,
            prompt=consensus_prompt,
            system_instruction="Kamu adalah kapten tim AI yang memimpin perumusan keputusan akhir dan pelaporan hasil eksekusi nyata.",
        )
        or "(laporan gagal: semua provider tidak merespons)"
    )

    action_plan_text = ""
    marker = "ACTION PLAN"
    marker_idx = consensus_text.upper().find(marker)
    if marker_idx != -1:
        consensus_text_clean = consensus_text[:marker_idx].strip()
        action_plan_text = marker + consensus_text[marker_idx + len(marker) :]
    else:
        consensus_text_clean = consensus_text

    workspace_hygiene.MEETING_RUNNING = False
    harvested_projects = _harvest_new_sandbox_projects(topic)

    if target_fol and os.path.isdir(target_fol):
        sanitize_project_directory(target_fol)

    if _CHECKPOINT_AVAILABLE and _SwarmCheckpoint:
        try:
            _deliverables = [
                s["deliverable_file"]
                for s in execution_steps
                if s.get("deliverable_file")
            ]
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
        "target_folder": target_fol,
        "harvested_projects": harvested_projects,
        "participants": [a["name"] for a in participants],
        "dialogue_transcript": dialogue_transcript,
        "execution_results": execution_steps,
        "consensus": consensus_text_clean,
        "action_plan": action_plan_text,
    }


async def resume_swarm_session(session_id: str) -> Dict[str, Any]:
    """
    Melanjutkan sesi swarm yang sebelumnya dibatalkan atau tertunda berdasarkan checkpoint.
    """
    if not _CHECKPOINT_AVAILABLE or not _SwarmCheckpoint:
        return {"status": "error", "message": "Checkpoint system tidak tersedia."}

    ckpt = _SwarmCheckpoint.load(session_id)
    if not ckpt:
        return {
            "status": "error",
            "message": f"Checkpoint untuk session '{session_id}' tidak ditemukan.",
        }

    topic = ckpt.get("topic", "")
    mode = ckpt.get("mode", "execute")
    participant_names = [
        a["name"]
        for a in ckpt.get("participants", [])
        if isinstance(a, dict) and "name" in a
    ]

    log_live("RESUME", f"🔄 Melanjutkan sesi {session_id} (Topik: {topic[:60]})...")

    return await conduct_multi_agent_meeting(
        topic=topic,
        participant_names=participant_names or None,
        mode=mode,
        session_id=session_id,
    )


__all__ = [
    "tools",
    "SWARM_OUTPUT_DIR",
    "MAX_SWARM_AGENTS",
    "MAX_QA_ROUNDS",
    "_HARVEST_EXCLUDE",
    "_JUNK_FILE_PATTERNS",
    "_SANDBOX_SNAPSHOT",
    "_TARGET_FOLDER",
    "_EXEC_FS_SNAPSHOT",
    "LIVE_FEED_FILE",
    "CANCEL_FLAG_FILE",
    "LIVE_LOG",
    "MEETING_RUNNING",
    "sanitize_project_directory",
    "_hash_sandbox_projects",
    "_fs_changed_since_snapshot",
    "_sandbox_project_dirs",
    "_harvest_new_sandbox_projects",
    "request_cancel_swarm",
    "_cancel_requested",
    "_clear_cancel_flag",
    "_load_last_seq",
    "_append_feed_file",
    "log_live",
    "log_tool_live",
    "_build_error_context",
    "_record_step_error",
    "qa_verdict_passed",
    "detect_task_intent",
    "KNOWN_OPENAI_PROVIDERS",
    "_default_gemini_model",
    "get_agent_api_client",
    "_generate_with_gemini",
    "_generate_with_openai_compat",
    "generate_agent_response",
    "_extract_html_doc",
    "validate_python_code",
    "_decompose_task",
    "_verify_step_result",
    "_single_shot_edit_fallback",
    "_forced_json_execution",
    "execute_swarm_task_step",
    "conduct_multi_agent_meeting",
    "resume_swarm_session",
]
