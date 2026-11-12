"""Eksekusi agen paralel (wave) dalam satu rapat swarm."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from alfa.swarm.live_logger import (
    _build_error_context,
)
from alfa.swarm.meeting_steps import _build_task_desc
from alfa.swarm.sessions import resume_swarm_session as resume_swarm_session

#: Nama yang dimiliki paket `alfa.swarm.engine` (kontrak patch test).
#: Dibaca lewat __getattr__ (PEP 562) supaya patch/mock pada paket tetap berlaku.
_FORWARDED: frozenset[str] = frozenset({})

logger = logging.getLogger(__name__)


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

def _execute_agent_step(*args: Any, **kwargs: Any) -> Any:
    """Delegasi ke paket `alfa.swarm.engine` (patch/mock tetap berlaku)."""
    from alfa.swarm import engine

    return engine._execute_agent_step(*args, **kwargs)

def _record_step_error(*args: Any, **kwargs: Any) -> Any:
    """Delegasi ke paket `alfa.swarm.engine` (patch/mock tetap berlaku)."""
    from alfa.swarm import engine

    return engine._record_step_error(*args, **kwargs)


def _budget_exceeded(*args: Any, **kwargs: Any) -> Any:
    """Delegasi ke paket `alfa.swarm.engine` (patch/mock tetap berlaku)."""
    from alfa.swarm import engine

    return engine._budget_exceeded(*args, **kwargs)

def _provider_dead_streak(*args: Any, **kwargs: Any) -> Any:
    """Delegasi ke paket `alfa.swarm.engine` (patch/mock tetap berlaku)."""
    from alfa.swarm import engine

    return engine._provider_dead_streak(*args, **kwargs)

def log_live(*args: Any, **kwargs: Any) -> Any:
    """Delegasi ke paket `alfa.swarm.engine` (patch/mock tetap berlaku)."""
    from alfa.swarm import engine

    return engine.log_live(*args, **kwargs)


_WAVE_ERR = (
    OSError,
    RuntimeError,
    ValueError,
    TypeError,
    KeyError,
    IndexError,
    AttributeError,
)
_STEP_ERR = (AttributeError, KeyError, IndexError, TypeError, ValueError)


def __getattr__(name: str) -> Any:
    """Delegasi ke paket `alfa.swarm.engine` (patch/mock tetap berlaku)."""

# ruff: noqa: F821  # nama submodule/forwarded di-resolve via PEP 562 __getattr__
    if name in _FORWARDED:
        from alfa.swarm import engine

        return getattr(engine, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

# pragma: no cover - deklarasi agar mypy understands forwarding


def _set_state(name: str, value: Any) -> None:
    """Tulis state mutable misi pada paket (bukan pada modul ini)."""
    from alfa.swarm import engine

    setattr(engine, name, value)

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
                _set_state("_BUDGET_EXCEEDED", budget_reason)
                log_live("TIMEOUT", f"⏱ Budget misi terlampaui ({budget_reason}) — swarm berhenti.")
                if _checkpoint_available():
                    try:
                        _swarm_checkpoint().mark_cancelled(session_id)
                    except (OSError, ValueError, TypeError):
                        pass
                return True
            dead_reason = _provider_dead_streak(execution_steps)
            if dead_reason:
                _set_state("_PROVIDER_DEAD", dead_reason)
                log_live("TIMEOUT", f"🔌 {dead_reason} — swarm dihentikan agar tak membakar kuota.")
                if _checkpoint_available():
                    try:
                        _swarm_checkpoint().mark_cancelled(session_id)
                    except (OSError, ValueError, TypeError):
                        pass
                return True
            wave = participants[wave_start : wave_start + _wave_size]
            if _cancel_requested(session_id):
                log_live("CANCEL", f"⏹ Eksekusi dihentikan pengguna sebelum gelombang {wave_start // _wave_size + 1}.")
                if _checkpoint_available():
                    try:
                        _swarm_checkpoint().mark_cancelled(session_id)
                    except (OSError, ValueError, TypeError):
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
            except _WAVE_ERR as wave_err:
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

                if _checkpoint_available():
                    try:
                        _swarm_checkpoint().save(
                            session_id=session_id,
                            topic=topic,
                            mode=mode,
                            participants=participants,
                            steps=execution_steps,
                            steps_done=len(execution_steps),
                            status="running",
                        )
                    except (OSError, ValueError, TypeError):
                        pass
                brief = (step_result.get("execution_summary") or "")[:180].replace("\n", " ")
                ctx_lines.append(f"{step_result['agent_name']} -> {brief}")
                if _cancel_requested(session_id):
                    log_live("CANCEL", "⏹ Eksekusi dihentikan pengguna setelah langkah gelombang selesai.")
                    return True
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
        return await _execute_agents_parallel(
            participants, {}, topic, intent_info, session_id, mode,
            execution_steps, ctx_lines, failed_steps,
        )

    wave_num = 1
    while queue:
        if _cancel_requested(session_id):
            log_live("CANCEL", f"⏹ Eksekusi dihentikan pengguna sebelum gelombang {wave_num}.")
            if _checkpoint_available():
                try:
                    _swarm_checkpoint().mark_cancelled(session_id)
                except (OSError, ValueError, TypeError):
                    pass
            return True

        budget_reason = _budget_exceeded(execution_steps)
        if budget_reason:
            _set_state("_BUDGET_EXCEEDED", budget_reason)
            log_live("TIMEOUT", f"⏱ Budget misi terlampaui ({budget_reason}) — swarm berhenti.")
            if _checkpoint_available():
                try:
                    _swarm_checkpoint().mark_cancelled(session_id)
                except (OSError, ValueError, TypeError):
                    pass
            return True
        dead_reason = _provider_dead_streak(execution_steps)
        if dead_reason:
            _set_state("_PROVIDER_DEAD", dead_reason)
            log_live("TIMEOUT", f"🔌 {dead_reason} — swarm dihentikan agar tak membakar kuota.")
            if _checkpoint_available():
                try:
                    _swarm_checkpoint().mark_cancelled(session_id)
                except (OSError, ValueError, TypeError):
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
        except _WAVE_ERR as wave_err:
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

            if _checkpoint_available():
                try:
                    _swarm_checkpoint().save(
                        session_id=session_id,
                        topic=topic,
                        mode=mode,
                        participants=participants,
                        steps=execution_steps,
                        steps_done=len(execution_steps),
                        status="running",
                    )
                except (OSError, ValueError, TypeError):
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

        if _cancel_requested(session_id):
            log_live("CANCEL", f"⏹ Eksekusi dihentikan pengguna setelah gelombang {wave_num - 1}.")
            if _checkpoint_available():
                try:
                    _swarm_checkpoint().mark_cancelled(session_id)
                except (OSError, ValueError, TypeError):
                    pass
            return True

    if len(completed) < len(agent_names):
        if _cancel_requested(session_id):
            return True
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

                if _checkpoint_available():
                    try:
                        _swarm_checkpoint().save(
                            session_id=session_id,
                            topic=topic,
                            mode=mode,
                            participants=participants,
                            steps=execution_steps,
                            steps_done=len(execution_steps),
                            status="running",
                        )
                    except (OSError, ValueError, TypeError):
                        pass
                brief = (step_result.get("execution_summary") or "")[:180].replace("\n", " ")
                ctx_lines.append(f"{step_result['agent_name']} -> {brief}")
        except _STEP_ERR as e:
            logger.debug("Ringkasan eksekusi langkah swarm dilewati: %s", e)

    return False
