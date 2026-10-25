"""BM25 retrieval over tool schemas (select_relevant_* entry points)."""

import logging
from collections.abc import Iterable
from typing import Any

from alfa.tools.rag.actions import _expand_families, get_required_action_tools
from alfa.tools.rag.keywords import (
    _CATEGORY_BOOSTS,
    _CATEGORY_TRIGGERS,
    CORE_ALWAYS,
    TOP_K,
    _expand_synonyms,
    _schema_to_text,
    _tokenize,
)

logger = logging.getLogger("ToolRAG")


def _rag_enabled() -> bool:
    """Read the live toggle so tests/users can flip `rag._ENABLED` at runtime.

    Mirrors the original single-module behavior where `select_*` read the
    module-global flag (patchable via `tool_rag._ENABLED = ...`).
    """
    import sys

    pkg = sys.modules.get("alfa.tools.rag")
    if pkg is not None and hasattr(pkg, "_ENABLED"):
        return bool(pkg._ENABLED)
    from alfa.tools.rag import keywords

    return bool(keywords._ENABLED)


class _BM25Index:
    """Wrapper tipis rank_bm25 dengan fallback scoring overlap sederhana."""

    def __init__(self, docs_tokens: list[list[str]]):
        self.docs = docs_tokens
        self._bm25 = None
        try:
            from rank_bm25 import BM25Okapi

            self._bm25 = BM25Okapi(docs_tokens) if docs_tokens else None
        except Exception as e:  # pragma: no cover - fallback path
            logger.debug(f"rank_bm25 unavailable ({e}); pakai fallback overlap.")

    def scores(self, query_tokens: list[str]) -> list[float]:
        if self._bm25 is not None:
            try:
                return list(self._bm25.get_scores(query_tokens))
            except Exception:
                pass
        # Fallback: skor overlap token (cukup baik untuk seleksi kasar)
        qset = set(query_tokens)
        out = []
        for doc in self.docs:
            dset = set(doc)
            out.append(len(qset & dset) / (len(qset) or 1))
        return out


def _rank_names(
    docs: list[str],
    names: list[str],
    user_text: str,
    history: Iterable[dict[str, Any]] | None = None,
    k: int | None = None,
) -> list[str]:
    """Ranking inti: kembalikan nama teratas + selalu sertakan CORE_ALWAYS."""
    kk = k or TOP_K
    corpus_docs = [_tokenize(d) for d in docs]
    index = _BM25Index(corpus_docs)

    query_parts = [user_text or ""]
    try:
        for h in list(history or [])[-3:]:
            if isinstance(h, dict) and h.get("content"):
                query_parts.append(str(h["content"])[:400])
    except Exception:
        pass
    q_tokens = _expand_synonyms(_tokenize(" ".join(query_parts)))

    scores = list(index.scores(q_tokens))
    q_set = set(q_tokens)
    for cat_name, cat_tools in _CATEGORY_BOOSTS.items():
        triggers = _CATEGORY_TRIGGERS.get(cat_name, {cat_name})
        if any(tr in q_set for tr in triggers):
            for i, nm in enumerate(names):
                if nm in cat_tools:
                    scores[i] += 3.0

    ranked = sorted(zip(names, scores, strict=False), key=lambda x: x[1], reverse=True)

    selected: list[str] = []
    for nm, _sc in ranked:
        if len(selected) >= kk:
            break
        if nm and nm not in selected and nm not in CORE_ALWAYS:
            selected.append(nm)
    selected.extend([c for c in CORE_ALWAYS if c not in selected])
    return list(dict.fromkeys(selected))


def select_relevant_functions(
    functions: list[Any],
    user_text: str,
    history: Iterable[dict[str, Any]] | None = None,
    top_k: int | None = None,
) -> list[Any]:
    """
    Versi untuk daftar callable Python mentah (jalur Gemini native AFC):
    indeks dari __name__ + __doc__, lalu filter seperti select_relevant_tools.
    Menjamin tidak ada fungsi duplikat yang dikirim ke Gemini SDK.
    """
    try:
        if not functions:
            return []

        # Deduplikasi awal berdasarkan __name__
        unique_funcs = []
        seen = set()
        for f in functions:
            nm = getattr(f, "__name__", "")
            if nm and nm not in seen:
                seen.add(nm)
                unique_funcs.append(f)
            elif not nm and f not in unique_funcs:
                unique_funcs.append(f)

        if not _rag_enabled():
            return unique_funcs

        k = top_k or TOP_K
        if len(unique_funcs) <= k + len(CORE_ALWAYS):
            return unique_funcs

        names: list[str] = []
        docs: list[str] = []
        for f in unique_funcs:
            nm = getattr(f, "__name__", "")
            names.append(nm)
            docs.append(f"{nm} {(getattr(f, '__doc__', '') or '')[:600]}")

        keep = set(_rank_names(docs, names, user_text, history, k))
        keep = _expand_families(keep, set(names))
        keep.update(get_required_action_tools(user_text))
        filtered = []
        seen_filtered = set()
        for f in unique_funcs:
            nm = getattr(f, "__name__", "")
            if nm in keep and nm not in seen_filtered:
                seen_filtered.add(nm)
                filtered.append(f)

        if not filtered:
            return unique_funcs

        logger.info(
            f"[ToolRAG] {len(unique_funcs)} -> {len(filtered)} fungsi unik "
            f"(hemat ~{(len(unique_funcs) - len(filtered)) * 90} token/turn)"
        )
        return filtered
    except Exception as e:
        logger.warning(f"[ToolRAG] fail-open ke set lengkap: {e}")
        # Tetap deduplikasi saat fallback error
        seen_fallback = set()
        fallback_funcs = []
        for f in functions or []:
            nm = getattr(f, "__name__", "")
            if nm and nm not in seen_fallback:
                seen_fallback.add(nm)
                fallback_funcs.append(f)
            elif not nm and f not in fallback_funcs:
                fallback_funcs.append(f)
        return fallback_funcs


def select_relevant_tools(
    tools_schema: list[dict[str, Any]],
    user_text: str,
    history: Iterable[dict[str, Any]] | None = None,
    top_k: int | None = None,
) -> list[dict[str, Any]]:
    """
    Filter skema tools OpenAI-style agar hanya TOP-K paling relevan dengan
    pesan user (+gabungan riwayat terakhir). CORE_ALWAYS selalu masuk.
    Return set lengkap bila fitur off/terjadi error/jumlah tool <= top_k.
    """
    try:
        if not _rag_enabled() or not tools_schema:
            return tools_schema
        k = top_k or TOP_K
        if len(tools_schema) <= k + len(CORE_ALWAYS):
            return tools_schema

        corpus_docs: list[list[str]] = []
        for s in tools_schema:
            corpus_docs.append(_tokenize(_schema_to_text(s)))
        index = _BM25Index(corpus_docs)

        query_parts = [user_text or ""]
        try:
            for h in list(history or [])[-3:]:
                if isinstance(h, dict) and h.get("content"):
                    query_parts.append(str(h["content"])[:400])
        except Exception:
            pass
        q_tokens = _expand_synonyms(_tokenize(" ".join(query_parts)))

        name_to_schema: dict[str, dict[str, Any]] = {}
        doc_names: list[str] = []
        for s in tools_schema:
            nm = (
                ((s.get("function") or {}).get("name"))
                or s.get("name")
                or (((s.get("openai_spec") or {}).get("function") or {}).get("name"))
                or ""
            )
            name_to_schema[nm] = s
            doc_names.append(nm)

        scores = list(index.scores(q_tokens))
        q_set = set(q_tokens)
        for cat_name, cat_tools in _CATEGORY_BOOSTS.items():
            triggers = _CATEGORY_TRIGGERS.get(cat_name, {cat_name})
            if any(tr in q_set for tr in triggers):
                for i, nm in enumerate(doc_names):
                    if nm in cat_tools:
                        scores[i] += 3.0

        ranked = sorted(
            zip(doc_names, scores, strict=False), key=lambda x: x[1], reverse=True
        )

        selected: list[str] = []
        for nm, _sc in ranked:
            if len(selected) >= k:
                break
            if nm and nm not in selected and nm not in CORE_ALWAYS:
                selected.append(nm)
        for core in CORE_ALWAYS:
            if core in name_to_schema:
                selected.append(core)
        _with_family = _expand_families(set(selected), set(name_to_schema))
        selected = [n for n in selected if n in _with_family] + sorted(
            _with_family - set(selected)
        )
        for required in get_required_action_tools(user_text):
            if required in name_to_schema:
                selected.append(required)

        filtered = [
            name_to_schema[nm] for nm in dict.fromkeys(selected) if nm in name_to_schema
        ]
        if not filtered:  # safety net: jangan pernah kosongkan tools
            return tools_schema
        dropped = len(tools_schema) - len(filtered)
        logger.info(
            f"[ToolRAG] {len(tools_schema)} -> {len(filtered)} tool "
            f"({dropped} disembunyikan; hemat ~{(len(tools_schema) - len(filtered)) * 90} token/turn)"
        )
        return filtered
    except Exception as e:
        logger.warning(f"[ToolRAG] fail-open ke set lengkap: {e}")
        return tools_schema
