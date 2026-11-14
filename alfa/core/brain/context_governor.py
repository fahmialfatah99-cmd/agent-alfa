"""Context & Cost Governor — kompaksi konteks deterministik per giliran.

Lapisan ini memperluas ``_compact_convo`` yang sudah ada tanpa mengubah
kontraknya. Mode diatur ``ALFA_CONTEXT_GOVERNOR``:

- ``off``    — hanya kompaksi legacy (perilaku v2.18.0).
- ``shadow`` — kompaksi legacy + statistik proyeksi (default, tanpa perubahan).
- ``on``     — kompaksi adaptif head+tail, hard budget, dan pemangkasan
  output tool baru sebelum masuk riwayat.

Semua fungsi fail-soft: kegagalan governor tidak boleh mematikan giliran.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any

from alfa.core.config import env_int, env_str

logger = logging.getLogger("MainBrain.Governor")

#: Marker legacy dipertahankan agar tes/kompatibilitas tetap sama.
_LEGACY_MARKER = "[output tool dipangkas utk hemat konteks] "
_HARD_MARKER = "[output tool dipangkas keras oleh context governor] "
_OUTPUT_MARKER = "\n\n[... output dipangkas oleh context governor: {n} karakter ...]\n\n"

_STATS_LOCK = threading.Lock()
_STATS: dict[str, Any] = {
    "mode": "shadow",
    "calls": 0,
    "compactions": 0,
    "hard_compactions": 0,
    "last_before_chars": 0,
    "last_after_chars": 0,
    "last_saved_chars": 0,
    "last_estimated_tokens": 0,
    "last_budget": 0,
    "last_hard_budget": 0,
    "last_tool_messages": 0,
    "last_compacted": 0,
    "last_at": 0.0,
}

#: Error realistis untuk operasi governor.
_GOV_ERR = (TypeError, ValueError, KeyError, AttributeError, RuntimeError, OSError)


def governor_mode() -> str:
    """Mode governor aktif: ``off`` | ``shadow`` | ``on``."""
    raw = env_str("ALFA_CONTEXT_GOVERNOR", "shadow").strip().lower()
    if raw in {"1", "true", "yes"}:
        return "on"
    if raw in {"0", "false", "no"}:
        return "off"
    if raw in {"off", "shadow", "on"}:
        return raw
    return "shadow"


def governor_limits() -> dict[str, int]:
    """Batas governor dari env (dibaca dinamis agar mudah diuji)."""
    return {
        "hard_budget": env_int(
            "ALFA_CONTEXT_HARD_BUDGET", 180_000, minimum=10_000
        ),
        "output_threshold": env_int(
            "ALFA_TOOL_OUTPUT_COMPACT_THRESHOLD", 9_000, minimum=1_000
        ),
        "output_head": env_int("ALFA_TOOL_OUTPUT_HEAD", 4_000, minimum=200),
        "output_tail": env_int("ALFA_TOOL_OUTPUT_TAIL", 2_000, minimum=200),
        "old_head": env_int("ALFA_CONTEXT_OLD_HEAD", 800, minimum=100),
        "old_tail": env_int("ALFA_CONTEXT_OLD_TAIL", 400, minimum=100),
        "assistant_head": env_int(
            "ALFA_CONTEXT_ASSISTANT_HEAD", 800, minimum=100
        ),
    }


def _estimate_tokens(chars: int) -> int:
    """Estimasi kasar token (4 karakter/token) untuk dashboard/biaya."""
    return max(0, int(chars) // 4)


def _note_stats(**values: Any) -> None:
    try:
        with _STATS_LOCK:
            _STATS.update(values)
    except _GOV_ERR:
        pass


def governor_stats() -> dict[str, Any]:
    """Snapshot statistik governor terakhir (thread-safe)."""
    try:
        with _STATS_LOCK:
            data = dict(_STATS)
    except _GOV_ERR:
        return {"mode": "shadow"}
    data["mode"] = governor_mode()
    data["limits"] = governor_limits()
    return data


def _content_len(message: dict[str, Any]) -> int:
    return len(str(message.get("content") or ""))


def compact_tool_output(text: str) -> str:
    """Pangkas output tool baru secara head+tail bila mode ``on``.

    Deterministik (tanpa LLM) dan idempoten: output yang sudah dipangkas
    tidak akan dipangkas ulang karena sudah di bawah ambang.
    """
    if not isinstance(text, str) or not text:
        return text
    result = text
    try:
        mode = governor_mode()
        limits = governor_limits()
        threshold = limits["output_threshold"]
        head = max(0, limits["output_head"])
        tail = max(0, limits["output_tail"])
        if (
            mode == "on"
            and len(text) > threshold
            and len(text) > head + tail + 120
        ):
            omitted = len(text) - head - tail
            compacted = (
                text[:head]
                + _OUTPUT_MARKER.format(n=omitted)
                + text[-tail:]
            )
            if len(compacted) < len(text):
                result = compacted
                _note_stats(
                    compactions=_STATS.get("compactions", 0) + 1,
                    last_saved_chars=_STATS.get("last_saved_chars", 0)
                    + (len(text) - len(compacted)),
                )
    except _GOV_ERR as exc:
        logger.debug("Kompaksi output tool gagal (abaikan): %s", exc)
        return text
    return result


def _compact_old_tools(
    convo: list[dict[str, Any]],
    tool_idx: list[int],
    keep: int,
    *,
    head: int,
    tail: int,
    marker: str,
) -> int:
    """Pangkas tool lama; return jumlah pesan yang berubah."""
    changed = 0
    for index in tool_idx[:-keep] if keep > 0 else tool_idx:
        content = str(convo[index].get("content") or "")
        if len(content) <= head + tail + 80:
            continue
        if tail > 0:
            replacement = f"{marker}{content[:head]} ... {content[-tail:]}"
        else:
            replacement = f"{marker}{content[:head]} ..."
        if len(replacement) >= len(content):
            continue
        convo[index]["content"] = replacement
        changed += 1
    return changed


def govern_convo(
    convo: list[dict[str, Any]],
    size_fn: Callable[[list[dict[str, Any]]], int],
    budget: int,
    keep: int,
) -> dict[str, Any]:
    """Terapkan kompaksi sesuai mode; selalu mengembalikan statistik.

    Legacy compaction dipertahankan persis seperti sebelumnya. Mode ``on``
    menambahkan head+tail adaptif dan hard budget; mode ``shadow`` hanya
    menghitung proyeksi tanpa mengubah isi tambahan.
    """
    stats: dict[str, Any] = {
        "mode": governor_mode(),
        "before": 0,
        "after": 0,
        "saved": 0,
        "compacted": 0,
        "hard_compacted": 0,
        "tool_messages": 0,
    }
    try:
        mode = stats["mode"]
        limits = governor_limits()
        hard_budget = limits["hard_budget"]
        before = int(size_fn(convo))
        stats["before"] = before
        tool_idx = [
            i for i, message in enumerate(convo) if message.get("role") == "tool"
        ]
        stats["tool_messages"] = len(tool_idx)

        if before <= budget:
            stats["after"] = before
            _note_stats(
                mode=mode,
                calls=_STATS.get("calls", 0) + 1,
                last_before_chars=before,
                last_after_chars=before,
                last_saved_chars=0,
                last_estimated_tokens=_estimate_tokens(before),
                last_budget=int(budget),
                last_hard_budget=hard_budget,
                last_tool_messages=len(tool_idx),
                last_compacted=0,
                last_at=time.time(),
            )
            return stats

        # 1) Kompaksi legacy: selalu aktif agar perilaku lama tidak berubah.
        if mode == "on":
            compacted = _compact_old_tools(
                convo,
                tool_idx,
                keep,
                head=limits["old_head"],
                tail=limits["old_tail"],
                marker=_LEGACY_MARKER,
            )
        else:
            compacted = _compact_old_tools(
                convo, tool_idx, keep, head=180, tail=0, marker=_LEGACY_MARKER
            )
        stats["compacted"] = compacted

        # 2) Hard budget: hanya mode on yang memangkas lebih agresif.
        hard_compacted = 0
        after = int(size_fn(convo))
        if mode == "on" and after > hard_budget:
            hard_compacted += _compact_old_tools(
                convo,
                tool_idx,
                keep,
                head=200,
                tail=0,
                marker=_HARD_MARKER,
            )
            after = int(size_fn(convo))
            if after > hard_budget:
                assistant_idx = [
                    i
                    for i, message in enumerate(convo)
                    if message.get("role") == "assistant"
                ]
                head = limits["assistant_head"]
                for index in assistant_idx[:-2]:
                    content = str(convo[index].get("content") or "")
                    if len(content) <= head + 120:
                        continue
                    replacement = (
                        f"[assistant dipangkas oleh context governor] "
                        f"{content[:head]} ..."
                    )
                    if len(replacement) < len(content):
                        convo[index]["content"] = replacement
                        hard_compacted += 1
                after = int(size_fn(convo))

        stats["hard_compacted"] = hard_compacted
        stats["after"] = after
        stats["saved"] = max(0, before - after)
        _note_stats(
            mode=mode,
            calls=_STATS.get("calls", 0) + 1,
            compactions=_STATS.get("compactions", 0)
            + (1 if compacted else 0),
            hard_compactions=_STATS.get("hard_compactions", 0)
            + (1 if hard_compacted else 0),
            last_before_chars=before,
            last_after_chars=after,
            last_saved_chars=stats["saved"],
            last_estimated_tokens=_estimate_tokens(after),
            last_budget=int(budget),
            last_hard_budget=hard_budget,
            last_tool_messages=len(tool_idx),
            last_compacted=compacted,
            last_at=time.time(),
        )
        if after > hard_budget:
            logger.warning(
                "[Governor] konteks masih %d karakter (> hard budget %d) "
                "setelah kompaksi; lanjut agar tugas tidak terpotong.",
                after,
                hard_budget,
            )
    except _GOV_ERR as exc:
        logger.debug("Context governor gagal (abaikan): %s", exc)
    return stats


__all__ = [
    "compact_tool_output",
    "govern_convo",
    "governor_limits",
    "governor_mode",
    "governor_stats",
]
