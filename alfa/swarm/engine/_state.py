"""Budget misi, deteksi provider mati, dan state bersama."""

from __future__ import annotations

import logging
import os
import time
from typing import Any

from alfa.swarm.sessions import resume_swarm_session as resume_swarm_session

#: Nama yang dimiliki paket `alfa.swarm.engine` (kontrak patch test).
#: Dibaca lewat __getattr__ (PEP 562) supaya patch/mock pada paket tetap berlaku.
_FORWARDED: frozenset[str] = frozenset({})

logger = logging.getLogger(__name__)


def _provider_dead_streak_limit() -> Any:
    """Nilai _PROVIDER_DEAD_STREAK dari paket `alfa.swarm.engine`."""
    from alfa.swarm import engine

    return engine._PROVIDER_DEAD_STREAK


def _mission_start() -> Any:
    """Nilai _MISSION_START dari paket `alfa.swarm.engine`."""
    from alfa.swarm import engine

    return engine._MISSION_START

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

# ruff: noqa: F821  # nama submodule/forwarded di-resolve via PEP 562 __getattr__
    if name in _FORWARDED:
        from alfa.swarm import engine

        return getattr(engine, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")




def _set_state(name: str, value: Any) -> None:
    """Tulis state mutable misi pada paket (bukan pada modul ini)."""
    from alfa.swarm import engine

    setattr(engine, name, value)

def _swarm_budget() -> tuple[float, int]:
    """Baca budget misi: (timeout_detik, max_langkah). 0 = nonaktif.

    Default-nya AKTIF (1800s / 40 langkah). Sebelumnya default "0" berarti
    timeout & batas langkah mati, sehingga satu misi bisa berjalan tanpa
    henti dan membakar kuota tanpa payung.
    """
    try:
        timeout = float(os.getenv("ALFA_SWARM_TASK_TIMEOUT", "1800") or 1800)
    except ValueError:
        timeout = 1800
    try:
        max_steps = int(os.getenv("ALFA_SWARM_MAX_STEPS", "40") or 40)
    except ValueError:
        max_steps = 40
    return max(0.0, timeout), max(0, max_steps)

def _provider_dead_streak(execution_steps: list) -> str:
    """Deteksi provider mati beruntun: N langkah terakhir gagal total tanpa respons.

    Tanda: status error + 'SEMUA provider gagal' (semua provider & fallback buntu).
    Cegah misi membakar kuota/waktu saat provider benar-benar mati.
    """
    tail = (execution_steps or [])[-_provider_dead_streak_limit():]
    if len(tail) < _provider_dead_streak_limit():
        return ""
    for s in tail:
        out = str((s or {}).get("tool_output", ""))
        summ = str((s or {}).get("execution_summary", ""))
        if (s or {}).get("status") != "error" or "SEMUA provider gagal" not in out + summ:
            return ""
    return (
        f"provider mati {_provider_dead_streak_limit()} langkah beruntun "
        "(semua provider & fallback tanpa respons)"
    )

def _budget_exceeded(execution_steps: list) -> str:
    """Kembalikan alasan bila budget misi terlampaui, else ''."""
    timeout, max_steps = _swarm_budget()
    if timeout > 0 and _mission_start() and (time.monotonic() - _mission_start()) > timeout:
        return f"timeout misi {timeout:g}s"
    if max_steps > 0 and len(execution_steps) >= max_steps:
        return f"batas {max_steps} langkah misi"
    return ""
