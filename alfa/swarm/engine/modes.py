"""Normalisasi mode swarm (single/swarm/plan_and_execute)."""

from __future__ import annotations

import logging
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

_MODE_ALIASES = {
    "rapat": "plan",
    "meeting": "plan",
    "discuss": "plan",
    "discussion": "plan",
    "diskusi": "plan",
    "eksekusi": "execute",
}

_SWARM_MODES = ("plan", "execute", "plan_and_execute")

def _normalize_swarm_mode(mode: Any) -> str:
    """Validasi mode swarm; fallback ke 'execute' bila tak dikenal."""
    m = str(mode or "execute").strip().lower()
    m = _MODE_ALIASES.get(m, m)
    if m not in _SWARM_MODES:
        logger.warning("mode swarm tak dikenal %r — fallback ke 'execute'", mode)
        return "execute"
    return m
