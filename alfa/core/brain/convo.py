"""Conversation context measuring and compaction for the agentic loop."""

import logging
from typing import Any

from alfa.core.brain.config import _TOOL_KEEP_RECENT as _DEFAULT_KEEP
from alfa.core.brain.config import TOOL_CONTEXT_BUDGET as _DEFAULT_BUDGET
from alfa.core.brain.context_governor import compact_tool_output as compact_tool_output
from alfa.core.brain.context_governor import govern_convo as _govern_convo

logger = logging.getLogger("MainBrain")


def _live_budget() -> tuple[int, int]:
    """Resolve budget/keep dynamically so tests/users can patch `brain.*`.

    Mirrors the original single-module behavior where the globals were
    patchable via the top-level namespace.
    """
    import sys

    pkg = sys.modules.get("alfa.core.brain")
    budget = getattr(pkg, "TOOL_CONTEXT_BUDGET", _DEFAULT_BUDGET)
    keep = getattr(pkg, "_TOOL_KEEP_RECENT", _DEFAULT_KEEP)
    try:
        return int(budget), int(keep)
    except (TypeError, ValueError):
        return _DEFAULT_BUDGET, _DEFAULT_KEEP


def _convo_size(convo: list[dict[str, Any]]) -> int:
    return sum(
        len(m.get("content") or "") + len(str(m.get("tool_calls") or "")) for m in convo
    )


def _compact_convo(convo: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Pangkas output tool LAMA saat total konteks melewati budget.

    Pesan 'tool' terakhir dijaga utuh; yang lebih tua dipotong menjadi
    penanda ringkas agar loop panjang tetap muat dalam jendela konteks.
    Detail strategi (legacy/shadow/on) dikelola
    ``alfa.core.brain.context_governor``. Mutasi in-place; mengembalikan
    convo yang sama.
    """
    try:
        budget, keep = _live_budget()
        stats = _govern_convo(convo, _convo_size, budget, keep)
        if stats.get("saved"):
            logger.debug(
                "[MainBrain] kompaksi konteks: %s -> %s karakter "
                "(%s pesan tool, mode %s)",
                stats.get("before"),
                stats.get("after"),
                stats.get("compacted"),
                stats.get("mode"),
            )
    except (TypeError, ValueError, KeyError, AttributeError) as e:
        logger.warning(f"[MainBrain] kompaksi gagal (abaikan): {e!r}")
    return convo
