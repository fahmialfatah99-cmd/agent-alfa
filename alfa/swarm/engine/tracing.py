"""Pencatatan trace rapat (best-effort, bukan jalur kritis)."""

from __future__ import annotations

import logging
import time
from typing import Any

from alfa.swarm.sessions import resume_swarm_session as resume_swarm_session

#: Nama yang dimiliki paket `alfa.swarm.engine` (kontrak patch test).
#: Dibaca lewat __getattr__ (PEP 562) supaya patch/mock pada paket tetap berlaku.
_FORWARDED: frozenset[str] = frozenset({})

logger = logging.getLogger(__name__)

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




def __getattr__(name: str) -> Any:
    """Delegasi ke paket `alfa.swarm.engine` (patch/mock tetap berlaku)."""
    if name in _FORWARDED:
        from alfa.swarm import engine

        return getattr(engine, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

def _record_swarm_trace_safely(
    session_id: str,
    topic: str,
    mode: str,
    rounds: int,
    started_monotonic: float,
    participant_names: list[str] | None,
    result: dict[str, Any] | None = None,
    error: str = "",
) -> None:
    """Tulis jejak run utk observability — SELALU di-swallow.

    Tracing adalah fitur sampingan: kegagalan apa pun (DB dll.) TIDAK boleh
    memengaruhi jalur utama (zero-regression).
    """
    try:
        from alfa.core.db.run_trace import record_swarm_meeting_sync

        record_swarm_meeting_sync(
            session_id=session_id,
            topic=topic,
            mode=mode,
            rounds=rounds,
            duration_ms=int((time.monotonic() - started_monotonic) * 1000),
            participants=list(participant_names or []),
            result=result,
            error=error,
        )
    except (TypeError, ValueError, KeyError, IndexError, AttributeError, RuntimeError, OSError, ArithmeticError, UnicodeError):  # noqa: BLE001 — tracing gagal-lembut (bukan jalur kritis)
        logger.debug("run-trace gagal (diabaikan): %s", session_id)
