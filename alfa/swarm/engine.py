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
import time
import uuid
from datetime import datetime
from typing import Any

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
from alfa.swarm.meeting_steps import _build_task_desc, _execute_agent_step
from alfa.swarm.sessions import resume_swarm_session as resume_swarm_session
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

_BUDGET_EXCEEDED = ""
_PROVIDER_DEAD = ""
_PROVIDER_DEAD_STREAK = 3
_MISSION_START = 0.0


def _swarm_budget() -> tuple[float, int]:
    """Baca budget misi: (timeout_detik, max_langkah). 0 = nonaktif."""
    try:
        timeout = float(os.getenv("ALFA_SWARM_TASK_TIMEOUT", "0") or 0)
    except ValueError:
        timeout = 0
    try:
        max_steps = int(os.getenv("ALFA_SWARM_MAX_STEPS", "0") or 0)
    except ValueError:
        max_steps = 0
    return max(0.0, timeout), max(0, max_steps)


def _provider_dead_streak(execution_steps: list) -> str:
    """Deteksi provider mati beruntun: N langkah terakhir gagal total tanpa respons.

    Tanda: status error + 'SEMUA provider gagal' (semua provider & fallback buntu).
    Cegah misi membakar kuota/waktu saat provider benar-benar mati.
    """
    tail = (execution_steps or [])[-_PROVIDER_DEAD_STREAK:]
    if len(tail) < _PROVIDER_DEAD_STREAK:
        return ""
    for s in tail:
        out = str((s or {}).get("tool_output", ""))
        summ = str((s or {}).get("execution_summary", ""))
        if (s or {}).get("status") != "error" or "SEMUA provider gagal" not in out + summ:
            return ""
    return (
        f"provider mati {_PROVIDER_DEAD_STREAK} langkah beruntun "
        "(semua provider & fallback tanpa respons)"
    )


def _budget_exceeded(execution_steps: list) -> str:
    """Kembalikan alasan bila budget misi terlampaui, else ''."""
    timeout, max_steps = _swarm_budget()
    if timeout > 0 and _MISSION_START and (time.monotonic() - _MISSION_START) > timeout:
        return f"timeout misi {timeout:g}s"
    if max_steps > 0 and len(execution_steps) >= max_steps:
        return f"batas {max_steps} langkah misi"
    return ""


async def _execute_agents_parallel(
    participants: list[dict[str, Any]],
    subtask_map: dict[str, Any],
    topic: str,
    intent_info: dict[str, Any],
    session_id: str,
    mode: str,
    execution_steps: list[dict[str, Any]],
    ctx_lines: list[str],
    failed_steps: list[dict[str, Any]]
) -> bool:
    global _BUDGET_EXCEEDED, _PROVIDER_DEAD
    has_deps = False
    if subtask_map:
        for t in subtask_map.values():
            if isinstance(t, dict) and "depends_on" in t and t["depends_on"]:
                has_deps = True
                break

    if not has_deps:
        _parallel = os.getenv("ALFA_SWARM_PARALLEL", "on").strip().lower() != "off"
        try:
            _wave_size = max(1, int(os.getenv("ALFA_SWARM_MAX_CONCURRENT", "3")))
        except ValueError:
            _wave_size = 3
        if not _parallel:
            _wave_size = 1

        for wave_start in range(0, len(participants), _wave_size):
            budget_reason = _budget_exceeded(execution_steps)
            if budget_reason:
                _BUDGET_EXCEEDED = budget_reason
                log_live("TIMEOUT", f"⏱ Budget misi terlampaui ({budget_reason}) — swarm berhenti.")
                if _CHECKPOINT_AVAILABLE:
                    try:
                        _SwarmCheckpoint.mark_cancelled(session_id)
                    except Exception:
                        pass
                return True
            dead_reason = _provider_dead_streak(execution_steps)
            if dead_reason:
                _PROVIDER_DEAD = dead_reason
                log_live("TIMEOUT", f"🔌 {dead_reason} — swarm dihentikan agar tak membakar kuota.")
                if _CHECKPOINT_AVAILABLE:
                    try:
                        _SwarmCheckpoint.mark_cancelled(session_id)
                    except Exception:
                        pass
                return True
            wave = participants[wave_start : wave_start + _wave_size]
            if _cancel_requested():
                log_live("CANCEL", f"⏹ Eksekusi dihentikan pengguna sebelum gelombang {wave_start // _wave_size + 1}.")
                if _CHECKPOINT_AVAILABLE:
                    try:
                        _SwarmCheckpoint.mark_cancelled(session_id)
                    except Exception:
                        pass
                return True

            err_ctx_snapshot = _build_error_context(failed_steps)
            try:
                wave_results: list[Any] = await asyncio.gather(
                    *[
                        _execute_agent_step(
                            a,
                            _build_task_desc(
                                a,
                                err_ctx_snapshot,
                                subtask_map=subtask_map,
                                topic=topic,
                                ctx_lines=ctx_lines,
                            ),
                            topic=topic,
                            intent_info=intent_info,
                        )
                        for a in wave
                    ],
                    return_exceptions=True,
                )
            except Exception as wave_err:
                logger.error(f"Wave execution error: {wave_err}")
                wave_results = [wave_err] * len(wave)

            for agent, res in zip(wave, wave_results, strict=True):
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

                if _CHECKPOINT_AVAILABLE:
                    try:
                        _SwarmCheckpoint.save(
                            session_id=session_id,
                            topic=topic,
                            mode=mode,
                            participants=participants,
                            steps=execution_steps,
                            steps_done=len(execution_steps),
                            status="running",
                        )
                    except Exception:
                        pass
                brief = (step_result.get("execution_summary") or "")[:180].replace("\n", " ")
                ctx_lines.append(f"{step_result['agent_name']} -> {brief}")
        return False

    agent_names = [a["name"] for a in participants]
    agent_by_name = {a["name"]: a for a in participants}

    in_degree = {name: 0 for name in agent_names}
    adj_list: dict[str, list[str]] = {name: [] for name in agent_names}

    for name in agent_names:
        info = subtask_map.get(name, {})
        deps = info.get("depends_on", []) if isinstance(info, dict) else []
        for dep in deps:
            if dep in agent_names:
                adj_list[dep].append(name)
                in_degree[name] += 1

    queue = [name for name in agent_names if in_degree[name] == 0]
    completed = set()

    if not queue and agent_names:
        log_live("WARN", "⚠️ Terdeteksi siklus pada dependensi! Beralih ke fallback sekuensial.")
        return await _execute_agents_parallel(participants, {}, topic, intent_info, session_id, mode, execution_steps, ctx_lines, failed_steps)

    wave_num = 1
    while queue:
        if _cancel_requested():
            log_live("CANCEL", f"⏹ Eksekusi dihentikan pengguna sebelum gelombang {wave_num}.")
            if _CHECKPOINT_AVAILABLE:
                try:
                    _SwarmCheckpoint.mark_cancelled(session_id)
                except Exception:
                    pass
            return True

        budget_reason = _budget_exceeded(execution_steps)
        if budget_reason:
            _BUDGET_EXCEEDED = budget_reason
            log_live("TIMEOUT", f"⏱ Budget misi terlampaui ({budget_reason}) — swarm berhenti.")
            if _CHECKPOINT_AVAILABLE:
                try:
                    _SwarmCheckpoint.mark_cancelled(session_id)
                except Exception:
                    pass
            return True
        dead_reason = _provider_dead_streak(execution_steps)
        if dead_reason:
            _PROVIDER_DEAD = dead_reason
            log_live("TIMEOUT", f"🔌 {dead_reason} — swarm dihentikan agar tak membakar kuota.")
            if _CHECKPOINT_AVAILABLE:
                try:
                    _SwarmCheckpoint.mark_cancelled(session_id)
                except Exception:
                    pass
            return True

        wave_names = queue[:]
        wave = [agent_by_name[n] for n in wave_names]
        queue = []

        err_ctx_snapshot = _build_error_context(failed_steps)
        try:
            wave_results = await asyncio.gather(
                *[
                    _execute_agent_step(
                        a,
                        _build_task_desc(
                            a,
                            err_ctx_snapshot,
                            subtask_map=subtask_map,
                            topic=topic,
                            ctx_lines=ctx_lines,
                        ),
                        topic=topic,
                        intent_info=intent_info,
                    )
                    for a in wave
                ],
                return_exceptions=True,
            )
        except Exception as wave_err:
            logger.error(f"Wave execution error: {wave_err}")
            wave_results = [wave_err] * len(wave)

        for agent, res in zip(wave, wave_results, strict=True):
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

            if _CHECKPOINT_AVAILABLE:
                try:
                    _SwarmCheckpoint.save(
                        session_id=session_id,
                        topic=topic,
                        mode=mode,
                        participants=participants,
                        steps=execution_steps,
                        steps_done=len(execution_steps),
                        status="running",
                    )
                except Exception:
                    pass

            brief = (step_result.get("execution_summary") or "")[:180].replace("\n", " ")
            ctx_lines.append(f"{step_result['agent_name']} -> {brief}")
            completed.add(agent["name"])

        for name in wave_names:
            for neighbor in adj_list[name]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)
        wave_num += 1

    if len(completed) < len(agent_names):
        remaining = [name for name in agent_names if name not in completed]
        log_live("WARN", f"⚠️ Agen tersisa karena dependensi macet: {remaining}. Menjalankan fallback!")
        wave = [agent_by_name[n] for n in remaining]
        err_ctx_snapshot = _build_error_context(failed_steps)
        try:
            wave_results = await asyncio.gather(
                *[
                    _execute_agent_step(
                        a,
                        _build_task_desc(
                            a,
                            err_ctx_snapshot,
                            subtask_map=subtask_map,
                            topic=topic,
                            ctx_lines=ctx_lines,
                        ),
                        topic=topic,
                        intent_info=intent_info,
                    )
                    for a in wave
                ],
                return_exceptions=True,
            )
            for agent, res in zip(wave, wave_results, strict=True):
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

                if _CHECKPOINT_AVAILABLE:
                    try:
                        _SwarmCheckpoint.save(
                            session_id=session_id,
                            topic=topic,
                            mode=mode,
                            participants=participants,
                            steps=execution_steps,
                            steps_done=len(execution_steps),
                            status="running",
                        )
                    except Exception:
                        pass
                brief = (step_result.get("execution_summary") or "")[:180].replace("\n", " ")
                ctx_lines.append(f"{step_result['agent_name']} -> {brief}")
        except Exception:
            pass

    return False

_SWARM_MODES = ("plan", "execute", "plan_and_execute")
_MODE_ALIASES = {
    "rapat": "plan",
    "meeting": "plan",
    "discuss": "plan",
    "discussion": "plan",
    "diskusi": "plan",
    "eksekusi": "execute",
}


def _normalize_swarm_mode(mode: Any) -> str:
    """Validasi mode swarm; fallback ke 'execute' bila tak dikenal."""
    m = str(mode or "execute").strip().lower()
    m = _MODE_ALIASES.get(m, m)
    if m not in _SWARM_MODES:
        logger.warning("mode swarm tak dikenal %r — fallback ke 'execute'", mode)
        return "execute"
    return m


async def conduct_multi_agent_meeting(
    topic: str,
    participant_names: list[str] | None = None,
    rounds: int = 2,
    mode: str = "execute",
    target_folder: str = "",
    session_id: str | None = None,
) -> dict[str, Any]:
    """
    Dual-mode: "plan" (diskusi round-table → konsensus + action plan, tanpa
    eksekusi tool) vs "execute"/"plan_and_execute" (dekomposisi → eksekusi
    paralel/DAG → verifikasi ground-truth → QA loop).

    Jika `target_folder` diisi (path lokal yang valid), SEMUA agen wajib
    mengedit di dalam folder tersebut.
    """
    from alfa.swarm import workspace_hygiene

    mode = _normalize_swarm_mode(mode)
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
            from alfa.swarm.workspace_hygiene import smart_slug as _smart_slug

            slug = _smart_slug(topic) or "proyek-baru"
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

    if _CHECKPOINT_AVAILABLE:
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
    history_summary: list[str] = []
    execution_steps: list[dict[str, Any]] = []

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
    global _BUDGET_EXCEEDED, _MISSION_START, _PROVIDER_DEAD
    _BUDGET_EXCEEDED = ""
    _PROVIDER_DEAD = ""
    _MISSION_START = time.monotonic()
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

    # Mode eksekusi langsung tidak butuh sesi diskusi (konteks dibangun dari
    # hasil eksekusi nyata). Mode diskusi/plan HARUS tetap berputar `rounds`
    # kali — dulu hard-coded 0 sehingga transkrip selalu kosong dan laporan
    # konsensus dibuat tanpa riwayat (total_dialogues selalu 0).
    if mode in ("execute", "plan_and_execute"):
        actual_rounds = 0
    else:
        try:
            actual_rounds = max(1, int(rounds or 1))
        except (TypeError, ValueError):
            actual_rounds = 2
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
                tk = _t["task"] if isinstance(_t, dict) else _t
                deps = _t.get("depends_on", []) if isinstance(_t, dict) else []
                log_live("PLAN", f"🗂️ {_n}: {tk[:90]} (Deps: {deps})")

        failed_steps: list[dict[str, Any]] = []
        ctx_lines: list[str] = []

        swarm_cancelled = await _execute_agents_parallel(
            participants,
            subtask_map,
            topic,
            intent_info,
            session_id,
            mode,
            execution_steps,
            ctx_lines,
            failed_steps
        )

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
                budget_reason = _budget_exceeded(execution_steps)
                if budget_reason:
                    _BUDGET_EXCEEDED = budget_reason
                    log_live(
                        "TIMEOUT",
                        f"⏱ Budget misi terlampaui ({budget_reason}) — QA dihentikan.",
                    )
                    break
                deliverables = [
                    s["deliverable_file"]
                    for s in execution_steps
                    if s.get("deliverable_file")
                ]
                work_summary = "\n".join(
                    f"- {s['agent_name']} ({s.get('tool_used', '?')}): {(s.get('execution_summary') or '')[:220]}"
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
        stop_note = (
            f"Budget misi terlampaui ({_BUDGET_EXCEEDED})."
            if _BUDGET_EXCEEDED
            else (
                f"Provider mati ({_PROVIDER_DEAD}). Coba lagi setelah kuota reset "
                "atau via model Gemini."
                if _PROVIDER_DEAD
                else "Eksekusi dibatalkan pengguna."
            )
        )
        log_live(
            "DONE",
            f"🏁 Eksekusi swarm BERHENTI ({stop_note}) — {len(execution_steps)} langkah tuntas sebelum berhenti.",
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
                f"⏹ **{stop_note}** {len(execution_steps)} dari "
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

    if _CHECKPOINT_AVAILABLE:
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
