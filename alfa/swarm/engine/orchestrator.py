"""Orkestrator rapat multi-agen (loop rapat, QA, dan anggaran)."""

from __future__ import annotations

import logging
import os
import time
import uuid
from datetime import datetime
from typing import Any, cast

from alfa import tools
from alfa.core import database
from alfa.swarm.deliberation import (
    Proposal as _Proposal,
)
from alfa.swarm.deliberation import (
    Turn as _Turn,
)
from alfa.swarm.deliberation import (
    apply_votes as _apply_votes,
)
from alfa.swarm.deliberation import (
    build_context_digest as _build_context_digest,
)
from alfa.swarm.deliberation import (
    build_proposal_menu as _build_proposal_menu,
)
from alfa.swarm.deliberation import (
    collect_proposals as _collect_proposals,
)
from alfa.swarm.deliberation import (
    parse_turn as _parse_turn,
)
from alfa.swarm.engine.modes import _normalize_swarm_mode
from alfa.swarm.engine.tracing import _record_swarm_trace_safely
from alfa.swarm.live_logger import (
    qa_verdict_passed,
)
from alfa.swarm.sessions import resume_swarm_session as resume_swarm_session
from alfa.swarm.workspace_hygiene import (
    MAX_SWARM_AGENTS,
)

#: Nama yang dimiliki paket `alfa.swarm.engine` (kontrak patch test).
#: Dibaca lewat __getattr__ (PEP 562) supaya patch/mock pada paket tetap berlaku.
_FORWARDED: frozenset[str] = frozenset({})

logger = logging.getLogger(__name__)

def _package_impl(*args: Any, **kwargs: Any) -> Any:
    """Panggil implementasi rapat lewat paket (patch/mock tetap berlaku)."""
    from alfa.swarm import engine

    return engine._conduct_multi_agent_meeting_impl(*args, **kwargs)


def _package_wave(*args: Any, **kwargs: Any) -> Any:
    """Panggil eksekusi wave lewat paket (patch/mock tetap berlaku)."""
    from alfa.swarm import engine

    return engine._execute_agents_parallel(*args, **kwargs)


def _swarm_checkpoint() -> Any:
    """Kelas checkpoint dari paket `alfa.swarm.engine` (patch/mock berlaku)."""
    from alfa.swarm import engine

    return engine._SwarmCheckpoint

def _checkpoint_available() -> Any:
    """Nilai _checkpoint_available() dari paket `alfa.swarm.engine` (patch/mock tetap berlaku)."""
    from alfa.swarm import engine

    return engine._CHECKPOINT_AVAILABLE



def _max_qa_rounds() -> Any:
    """Nilai _max_qa_rounds() dari paket `alfa.swarm.engine` (patch/mock tetap berlaku)."""
    from alfa.swarm import engine

    return engine.MAX_QA_ROUNDS



def _set_target_folder(value: Any) -> None:
    """Tulis _target_folder() pada paket `alfa.swarm.engine`."""
    from alfa.swarm import engine

    engine._TARGET_FOLDER = value


def _target_folder() -> Any:
    """Nilai _target_folder() dari paket `alfa.swarm.engine` (patch/mock tetap berlaku)."""
    from alfa.swarm import engine

    return engine._TARGET_FOLDER




def _sandbox_snapshot() -> Any:
    """Nilai _sandbox_snapshot() dari paket `alfa.swarm.engine` (patch/mock tetap berlaku)."""
    from alfa.swarm import engine

    return engine._SANDBOX_SNAPSHOT



def _exec_fs_snapshot() -> Any:
    """Nilai _exec_fs_snapshot() dari paket `alfa.swarm.engine` (patch/mock tetap berlaku)."""
    from alfa.swarm import engine

    return engine._EXEC_FS_SNAPSHOT



def _budget_exceeded_state() -> Any:
    """Nilai _budget_exceeded_state() dari paket `alfa.swarm.engine` (patch/mock tetap berlaku)."""
    from alfa.swarm import engine

    return engine._BUDGET_EXCEEDED



def _provider_dead_state() -> Any:
    """Nilai _provider_dead_state() dari paket `alfa.swarm.engine` (patch/mock tetap berlaku)."""
    from alfa.swarm import engine

    return engine._PROVIDER_DEAD



def _cancel_requested(*args: Any, **kwargs: Any) -> Any:
    """Delegasi ke paket `alfa.swarm.engine` (patch/mock tetap berlaku)."""
    from alfa.swarm import engine

    return engine._cancel_requested(*args, **kwargs)

def _clear_cancel_flag(*args: Any, **kwargs: Any) -> Any:
    """Delegasi ke paket `alfa.swarm.engine` (patch/mock tetap berlaku)."""
    from alfa.swarm import engine

    return engine._clear_cancel_flag(*args, **kwargs)


def generate_agent_response(*args: Any, **kwargs: Any) -> Any:
    """Delegasi ke paket `alfa.swarm.engine` (patch/mock tetap berlaku)."""
    from alfa.swarm import engine

    return engine.generate_agent_response(*args, **kwargs)

def detect_task_intent(*args: Any, **kwargs: Any) -> Any:
    """Delegasi ke paket `alfa.swarm.engine` (patch/mock tetap berlaku)."""
    from alfa.swarm import engine

    return engine.detect_task_intent(*args, **kwargs)

def _decompose_task(*args: Any, **kwargs: Any) -> Any:
    """Delegasi ke paket `alfa.swarm.engine` (patch/mock tetap berlaku)."""
    from alfa.swarm import engine

    return engine._decompose_task(*args, **kwargs)

def _budget_exceeded(*args: Any, **kwargs: Any) -> Any:
    """Delegasi ke paket `alfa.swarm.engine` (patch/mock tetap berlaku)."""
    from alfa.swarm import engine

    return engine._budget_exceeded(*args, **kwargs)

def sanitize_project_directory(*args: Any, **kwargs: Any) -> Any:
    """Delegasi ke paket `alfa.swarm.engine` (patch/mock tetap berlaku)."""
    from alfa.swarm import engine

    return engine.sanitize_project_directory(*args, **kwargs)

def log_live(*args: Any, **kwargs: Any) -> Any:
    """Delegasi ke paket `alfa.swarm.engine` (patch/mock tetap berlaku)."""
    from alfa.swarm import engine

    return engine.log_live(*args, **kwargs)

def execute_swarm_task_step(*args: Any, **kwargs: Any) -> Any:
    """Delegasi ke paket `alfa.swarm.engine` (patch/mock tetap berlaku)."""
    from alfa.swarm import engine

    return engine.execute_swarm_task_step(*args, **kwargs)

def _sandbox_project_dirs(*args: Any, **kwargs: Any) -> Any:
    """Delegasi ke paket `alfa.swarm.engine` (patch/mock tetap berlaku)."""
    from alfa.swarm import engine

    return engine._sandbox_project_dirs(*args, **kwargs)

def _hash_sandbox_projects(*args: Any, **kwargs: Any) -> Any:
    """Delegasi ke paket `alfa.swarm.engine` (patch/mock tetap berlaku)."""
    from alfa.swarm import engine

    return engine._hash_sandbox_projects(*args, **kwargs)

def _harvest_new_sandbox_projects(*args: Any, **kwargs: Any) -> Any:
    """Delegasi ke paket `alfa.swarm.engine` (patch/mock tetap berlaku)."""
    from alfa.swarm import engine

    return engine._harvest_new_sandbox_projects(*args, **kwargs)


_OPTIONAL_ERR = (
    ImportError,
    AttributeError,
    TypeError,
    ValueError,
    KeyError,
    OSError,
    RuntimeError,
)


def __getattr__(name: str) -> Any:
    """Delegasi ke paket `alfa.swarm.engine` (patch/mock tetap berlaku)."""

# ruff: noqa: F821  # nama submodule/forwarded di-resolve via PEP 562 __getattr__
    if name in _FORWARDED:
        from alfa.swarm import engine

        return getattr(engine, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")




def _set_state(name: str, value: Any) -> None:
    """Tulis state mutable misi pada paket (bukan pada modul ini)."""
    from alfa.swarm import engine

    setattr(engine, name, value)

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

    # State sesi disimpan PER-SESI (bukan global) — pastikan session_id definitif sebelum didaftarkan
    session_id = session_id or f"swarm_{int(time.time())}_{uuid.uuid4().hex[:6]}"
    _sid = workspace_hygiene.register_session(session_id)
    workspace_hygiene._clear_cancel_flag(session_id)
    _t0 = time.monotonic()
    try:
        result = await _package_impl(
            topic=topic,
            participant_names=participant_names,
            rounds=rounds,
            mode=mode,
            target_folder=target_folder,
            session_id=session_id,
        )
    except Exception:  # noqa: BLE001 - jalur rapat utama, error harus tertangkap
        _record_swarm_trace_safely(
            session_id,
            topic,
            mode,
            rounds,
            _t0,
            participant_names,
            error="exception",
        )
        raise
    finally:
        workspace_hygiene.unregister_session(_sid)
        workspace_hygiene._clear_cancel_flag(_sid)
    _record_swarm_trace_safely(
        session_id,
        topic,
        mode,
        rounds,
        _t0,
        participant_names,
        result=result,
    )
    return cast("dict[str, Any]", result)

async def _conduct_multi_agent_meeting_impl(
    topic: str,
    participant_names: list[str] | None = None,
    rounds: int = 2,
    mode: str = "execute",
    target_folder: str = "",
    session_id: str | None = None,
) -> dict[str, Any]:
    from alfa.swarm import workspace_hygiene

    mode = _normalize_swarm_mode(mode)
    session_id = session_id or f"swarm_{int(time.time())}_{uuid.uuid4().hex[:6]}"
    workspace_hygiene.set_current_session(session_id)

    # Folder target kerja agen
    _set_target_folder("")
    workspace_hygiene._TARGET_FOLDER = ""
    if target_folder and str(target_folder).strip():
        tf = os.path.realpath(os.path.expanduser(str(target_folder).strip()))
        if os.path.isdir(tf):
            _set_target_folder(tf)
            workspace_hygiene._TARGET_FOLDER = tf
            log_live("TARGET", f"📁 Folder kerja agen: {_target_folder()}")
        else:
            log_live(
                "TARGET",
                f"⚠️ Folder '{target_folder}' tidak ada — agen bebas memilih lokasi.",
            )

    intent_info = detect_task_intent(topic)

    # AUTO-CREATE: prompt bertema membangun aplikasi/kode tapi tanpa folder pilihan
    if not _target_folder() and mode in ("execute", "plan_and_execute"):
        if intent_info.get("is_build") or intent_info.get("is_code"):
            from alfa.swarm.workspace_hygiene import smart_slug as _smart_slug

            slug = _smart_slug(topic) or "proyek-baru"
            nf = os.path.join(tools.SANDBOX_DIR, f"{slug}_{int(time.time()) % 100000}")
            try:
                os.makedirs(nf, exist_ok=True)
                _set_target_folder(nf)
                workspace_hygiene._TARGET_FOLDER = nf
                log_live("TARGET", f"📁 Folder proyek baru dibuat otomatis: {nf}")
            except OSError as mk_err:
                log_live("TARGET", f"⚠️ Gagal buat folder otomatis: {mk_err}")

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

    if not participants:
        error_msg = (
            "Tidak ada agen yang terdaftar di workforce. "
            "Tambahkan minimal satu agen terlebih dahulu (Dashboard > AI Workforce) sebelum menjalankan rapat swarm."
        )
        logger.error(error_msg)
        workspace_hygiene.unregister_session(session_id)
        log_live("ERROR", "Sesi dibatalkan: tidak ada agen terdaftar.")
        return {
            "status": "error",
            "error": error_msg,
            "session_id": session_id,
            "meeting_id": None,
            "title": f"Swarm: {topic[:60]}",
            "topic": topic,
            "mode": mode,
            "target_folder": _target_folder(),
            "harvested_projects": {},
            "participants": [],
            "dialogue_transcript": [],
            "execution_results": [],
            "consensus": f"❌ {error_msg}",
            "action_plan": "",
        }

    if _checkpoint_available():
        try:
            _swarm_checkpoint().save(
                session_id=session_id,
                topic=topic,
                mode=mode,
                participants=participants,
                steps=[],
                steps_done=0,
                status="running",
            )
        except (OSError, ValueError, TypeError):
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
    workspace_hygiene.register_session(session_id)
    workspace_hygiene.set_current_session(session_id)
    _clear_cancel_flag(session_id)

    _set_state("_BUDGET_EXCEEDED", "")
    _set_state("_PROVIDER_DEAD", "")
    _set_state("_MISSION_START", time.monotonic())
    log_live(
        "SESSION",
        f"Sesi {mode.upper()} dimulai — topik: {topic[:80]} ({len(participants)} agen)",
    )

    _sandbox_snapshot().clear()
    _sandbox_snapshot().update(_sandbox_project_dirs())
    workspace_hygiene._SANDBOX_SNAPSHOT.clear()
    workspace_hygiene._SANDBOX_SNAPSHOT.update(_sandbox_project_dirs())

    if mode == "execute":
        _exec_fs_snapshot().clear()
        _exec_fs_snapshot().update(_hash_sandbox_projects())
        workspace_hygiene._EXEC_FS_SNAPSHOT.clear()
        workspace_hygiene._EXEC_FS_SNAPSHOT.update(_hash_sandbox_projects())
        if _target_folder():
            os.environ["ALFA_TARGET_FOLDER"] = _target_folder()
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
    # ── Deliberasi terstruktur (mode diskusi) ──────────────────────────────────
    # Tiap giliran menghasilkan posisi + bukti + keyakinan; sejak putaran ke-2
    # agen juga memberi suara atas proposal yang sudah ada. Suara dihitung
    # mekanis (lihat alfa.swarm.deliberation), bukan ditebak LLM.
    deliberation_turns: list[_Turn] = []
    proposals: list[_Proposal] = []
    all_votes: list[tuple[str, bool, str]] = []
    vote_tally: dict = {}
    pre_meeting_intel = ""

    if actual_rounds > 0:
        try:
            from alfa.swarm.deliberation import gather_pre_meeting_intel

            pre_meeting_intel = gather_pre_meeting_intel(topic, intent_info=intent_info)
            if pre_meeting_intel:
                log_live(
                    "PLAN",
                    f"📊 Fact-Grounded War Room: Lembar Fakta Pra-Rapat siap ({len(pre_meeting_intel)} char).",
                )
        except _OPTIONAL_ERR as e:
            logger.debug("Fact-grounded war room dilewati: %s", e)
            pre_meeting_intel = ""

    for r in range(1, actual_rounds + 1):
        if _cancel_requested():
            break
        for agent in participants:
            if _cancel_requested():
                break
            context_text = (
                _build_context_digest(deliberation_turns)
                if deliberation_turns
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
                menu = _build_proposal_menu(proposals)
                vote_block = (
                    ""
                    if r == 1
                    else (
                        "\n\n=== PROPOSAL TIM YANG ADA (BERI SUARA) ===\n"
                        f"{menu}\n\n"
                        "S voted untuk setiap proposal: SETUJU atau TOLAK, sertakan alasan singkat."
                    )
                )
                from alfa.swarm.personas import get_adaptive_system_instruction

                task_focus_line = (
                    "1. Berikan analisis tajam dan solusi praktis sesuai keahlianmu (Mode Masalah Umum/Strategis — JANGAN membahas pembuatan website/kode yang tidak diminta)."
                    if intent_info.get("is_general_advisory")
                    else "1. Berikan posisi/solusi teknis tajam sesuai bidang keahlianmu."
                )
                intel_block = f"{pre_meeting_intel}\n\n" if pre_meeting_intel else ""
                prompt = (
                    f"=== TOPIK AGENDA DISKUSI ===\n"
                    f"{topic}\n\n"
                    f"{intel_block}"
                    f"=== RINGKASAN OBROLAN TIM (PUTARAN {r}) ===\n"
                    f"{context_text}\n\n"
                    f"=== IDENTITAS KAMU ===\n"
                    f"Nama: {agent['name']} ({agent['role']})\n"
                    f"Persona: {agent['persona']}\n\n"
                    f"TUGAS KAMU:\n"
                    f"{task_focus_line}\n"
                    f"2. Kritik/dukung poin peserta lain secara to-the-point.\n"
                    f"3. HEMAT TOKEN: 2-4 kalimat padat.\n\n"
                    f"JAWAB DENGAN JSON MURNI (tanpa teks lain):\n"
                    f'{{"position":"posisimu 2-4 kalimat",'
                    f'"evidence":"bukti/fakta pendukung singkat",'
                    f'"confidence":0.0-1.0,'
                    f'"votes":[{{"id":"id-proposal","approve":true,"reason":"alasan singkat"}}]}}'
                    f"{vote_block}"
                )

            from alfa.swarm.personas import get_adaptive_system_instruction

            adaptive_sys = get_adaptive_system_instruction(
                agent, topic=topic, mode=mode, intent_info=intent_info
            )
            response_text = (
                await generate_agent_response(
                    agent=agent,
                    prompt=prompt,
                    system_instruction=adaptive_sys,
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

            # ── Catat giliran terstruktur (mode diskusi) ──────────────────────
            if mode not in ("execute", "plan_and_execute"):
                parsed = _parse_turn(response_text)
                turn = _Turn(
                    round=r,
                    agent=agent["name"],
                    role=agent["role"],
                    position=parsed.get("position") or response_text[:600],
                    evidence=parsed.get("evidence", ""),
                    confidence=parsed.get("confidence", 0.5),
                    votes=list(parsed.get("votes", [])),
                    raw=response_text,
                )
                deliberation_turns.append(turn)
                for ref, approve in turn.votes:
                    all_votes.append((turn.agent, approve, ref))
                # Proposal dihitung ulang tiap giliran (posisi terbaru tiap agen).
                proposals = _collect_proposals(deliberation_turns)

    # ── Hitung suara secara mekanis ──────────────────────────────────────────
    if mode not in ("execute", "plan_and_execute") and deliberation_turns:
        vote_tally = _apply_votes(proposals, all_votes)
        if vote_tally.get("winner"):
            _w = vote_tally["winner"]
            log_live(
                "VOTE",
                f"🗳️ Pemungutan suara: {_w['id']} ({_w['author']}) "
                f"{_w['votes_for']} setuju / {_w['votes_against']} tolak"
                f" — agreement {vote_tally.get('agreement', 0):.0%}",
            )
        if vote_tally.get("dissent"):
            _d = ", ".join(sorted({x["voter"] for x in vote_tally["dissent"]}))
            log_live("VOTE", f"⚖️ Dissenting agents: {_d}")

    swarm_cancelled = _cancel_requested(session_id)
    if not swarm_cancelled and mode in ["execute", "plan_and_execute"]:
        logger.info(
            f"⚡ Launching Live Autonomous Swarm Execution for {len(participants)} agents..."
        )

        subtask_map = await _decompose_task(topic, participants)
        if _cancel_requested(session_id):
            swarm_cancelled = True
        else:
            if subtask_map:
                logger.info("Task decomposition OK: %s", list(subtask_map.keys()))
                for _n, _t in subtask_map.items():
                    tk = _t["task"] if isinstance(_t, dict) else _t
                    deps = _t.get("depends_on", []) if isinstance(_t, dict) else []
                    log_live("PLAN", f"🗂️ {_n}: {tk[:90]} (Deps: {deps})")

            failed_steps: list[dict[str, Any]] = []
            ctx_lines: list[str] = []

            swarm_cancelled = await _package_wave(
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
        and _max_qa_rounds() > 0
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
            for qa_round in range(1, _max_qa_rounds() + 1):
                if _cancel_requested():
                    break
                budget_reason = _budget_exceeded(execution_steps)
                if budget_reason:
                    _set_state("_BUDGET_EXCEEDED", budget_reason)
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
                    f"🛡️ Sentinel QA putaran {qa_round}/{_max_qa_rounds()}: menguji hasil kerja tim...",
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


    lead_agent = participants[0]

    target_fol = workspace_hygiene._get_target_folder()
    if swarm_cancelled or _cancel_requested(session_id):
        workspace_hygiene.unregister_session(session_id)
        _clear_cancel_flag(session_id)
        stop_note = (
            f"Budget misi terlampaui ({_budget_exceeded_state()})."
            if _budget_exceeded_state()
            else (
                f"Provider mati ({_provider_dead_state()}). Coba lagi setelah kuota reset "
                "atau via model Gemini."
                if _provider_dead_state()
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
        # Hasil pemungutan suara dihitung mekanis — kapten menulis narasi
        # berdasarkan angka nyata, bukan menebak.
        vote_block = ""
        if vote_tally.get("winner"):
            _w = vote_tally["winner"]
            _dissent = ", ".join(sorted({x["voter"] for x in vote_tally.get("dissent", [])}))
            vote_block = (
                "\n\n=== HASIL PEMUNGUTAN SUARA (KOMPUTASI, BUKAN TEBAKAN) ===\n"
                f"Pemili suara: {vote_tally.get('total_voters', 0)} | "
                f"Proposal: {vote_tally.get('total_proposals', 0)}\n"
                f"Pemenang: {_w['id']} (oleh {_w['author']}) — "
                f"{_w['votes_for']} setuju, {_w['votes_against']} tolak\n"
                f"Agreement: {vote_tally.get('agreement', 0):.0%}\n"
                f"Isi: {_w['summary'][:300]}\n"
                + (f"Agen yang menyanggah: {_dissent}\n" if _dissent else "")
            )
        intel_section = f"{pre_meeting_intel}\n\n" if pre_meeting_intel else ""
        consensus_prompt = (
            f"=== TOPIK RAPAT ===\n{topic}\n\n"
            f"{intel_section}"
            f"=== TRANSKRIP LENGKAP DISKUSI TIM ===\n"
            + "\n".join(history_summary)
            + vote_block
            + "\n\n"
            f"Sebagai kapten rapat ({lead_agent['name']}), buatlah rangkuman KONSENSUS & ACTION PLAN yang ON-POINT:\n"
            f"1. KONSENSUS UTAMA (Inti kesepakatan tim dalam 2-3 poin ringkas).\n"
            f"2. ACTION PLAN (Tabel tugas terstruktur: No, Modul/Tugas, Penanggung Jawab, Target).\n"
            + (
                "3. CATAT DISSENT: sebutkan succinctly agen yang tidak setuju dan alasannya.\n"
                if vote_tally.get("dissent")
                else ""
            )
            + "Gunakan gaya bahasa santai, tegas, to-the-point tanpa basa-basi."
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

    workspace_hygiene.unregister_session(session_id)
    harvested_projects = _harvest_new_sandbox_projects(topic)

    if target_fol and os.path.isdir(target_fol):
        sanitize_project_directory(target_fol)

    if _checkpoint_available():
        try:
            _deliverables = [
                s["deliverable_file"]
                for s in execution_steps
                if s.get("deliverable_file")
            ]
            _swarm_checkpoint().mark_completed(session_id, deliverables=_deliverables)
        except (OSError, ValueError, TypeError):
            pass

    log_live("DONE", "🏁 Eksekusi swarm selesai.")

    final_result: dict[str, Any] = {
        "status": "success",
        "session_id": session_id,
        "meeting_id": None,
        "title": meeting_title,
        "topic": topic,
        "mode": mode,
        "target_folder": target_fol,
        "harvested_projects": harvested_projects,
        "participants": [a["name"] for a in participants],
        "pre_meeting_intel": pre_meeting_intel,
        "dialogue_transcript": dialogue_transcript,
        "execution_results": execution_steps,
        "consensus": consensus_text_clean,
        "action_plan": action_plan_text,
        # Hasil deliberasi terstruktur (dihitung mekanis, bukan tebakan LLM).
        "vote_tally": vote_tally,
        "proposals": [
            {
                "id": p.id,
                "author": p.author,
                "round": p.round,
                "summary": p.summary,
                "evidence": p.evidence,
                "confidence": p.confidence,
                "votes_for": p.votes_for,
                "votes_against": p.votes_against,
            }
            for p in proposals
        ],
        "dissent": vote_tally.get("dissent", []),
        "consensus_agreement": vote_tally.get("agreement", 0.0),
    }

    if mode not in ("execute", "plan_and_execute"):
        try:
            from alfa.swarm.deliberation import export_meeting_report_files

            export_meeting_report_files(final_result)
        except _OPTIONAL_ERR as e:
            logger.debug("Export laporan rapat dilewati: %s", e)

    return final_result
