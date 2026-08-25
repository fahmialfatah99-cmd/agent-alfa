"""
TOOL-RAG — Semantic Tool Retrieval (BM25 lokal, zero-dependency-fallback).

Masalah: 70+ skema tool disuntikkan penuh ke LLM di setiap giliran ->
ribuan token konteks terbuang + risiko "tool confusion" (salah pilih
tool / halusinasi argumen).

Solusi: indeks BM25 atas nama+deskripsi+argumen setiap tool. Dari pesan
user (+riwayat singkat), pilih hanya TOP-K tool paling relevan. Tool inti
(CORE_ALWAYS) selalu disertakan agar kapabilitas dasar tidak pernah hilang.

Fail-open: bila apa pun gagal, pemanggil memakai set lengkap.

Env:
    ALFA_TOOL_RAG=on|off      (default on)
    ALFA_TOOL_RAG_TOPK=14     jumlah maksimum tool tersuntik (di luar core)
"""

import logging
import os
import re
from typing import Any, Dict, Iterable, List, Optional, Set

logger = logging.getLogger("ToolRAG")

_ENABLED = os.getenv("ALFA_TOOL_RAG", "on").strip().lower() != "off"
try:
    TOP_K = max(4, int(os.getenv("ALFA_TOOL_RAG_TOPK", "14")))
except ValueError:
    TOP_K = 14

# Tool fondasi yang SELALU disuntikkan walau tak relevan dengan pesan.
CORE_ALWAYS: Set[str] = {
    "execute_python_sandbox",
    "execute_bash_command",
    "read_local_file",
    "write_local_file",
    "web_search",
    "save_knowledge_memory",
    "search_knowledge_memory",
}

_STOPWORDS = {
    "yang", "dan", "atau", "di", "ke", "dari", "untuk", "dengan", "pada", "adalah",
    "itu", "ini", "the", "a", "an", "of", "to", "in", "on", "for", "with", "and",
    "or", "is", "are", "be", "please", "coba", "tolong", "buatkan", "bikin",
    "saya", "kamu", "dia", "mereka", "bagaimana", "apa", "kenapa", "gimana",
}

# Sinonim ID->EN untuk menjembatani prompt bahasa Indonesia dengan
# deskripsi tool berbahasa Inggris (BM25 murni leksikal).
_SYNONYMS = {
    "rekam": "record", "perekam": "record", "layar": "screen", "tangkap": "capture",
    "cari": "search", "telusuri": "search", "riset": "research",
    "ingat": "memory remember save", "simpan": "save store write",
    "tulis": "write", "baca": "read", "kirim": "send deliver",
    "gambar": "image photo picture", "video": "video recording",
    "suara": "voice audio tts speech", "terjemah": "translate translation",
    "berkas": "file", "folder": "directory workspace", "proses": "process execute run",
    "bunuh": "kill terminate", "matikan": "stop kill shutdown",
    "jaringan": "network scan", "keamanan": "security audit",
    "git": "git commit push repository", "jadwal": "cron schedule reminder",
}


def _tokenize(text: str) -> List[str]:
    toks = re.findall(r"[a-zA-Z_][a-zA-Z0-9_]{1,}", (text or "").lower())
    out: List[str] = []
    for t in toks:
        # pecahkan snake_case agar 'record_desktop_screen' cocok dgn 'screen'
        parts = t.split("_") if "_" in t else [t]
        out.extend(p for p in parts if p not in _STOPWORDS)
    return out


def _expand_synonyms(tokens: List[str]) -> List[str]:
    """Suntikkan padanan EN ke query agar cocok dg dokumen tool berbahasa Inggris."""
    out = list(tokens)
    for t in tokens:
        extra = _SYNONYMS.get(t)
        if extra:
            out.extend(extra.split())
    return out


def _schema_to_text(schema: Dict[str, Any]) -> str:
    """Gabungkan nama + deskripsi + nama argumen jadi satu dokumen indeks."""
    try:
        fn = schema.get("function", {}) or {}
        parts = [fn.get("name", "")]
        desc = fn.get("description", "") or ""
        parts.append(desc[:600])
        params = ((fn.get("parameters") or {}).get("properties") or {})
        parts.extend(params.keys())
        return " ".join(str(p) for p in parts)
    except Exception:
        return ""


class _BM25Index:
    """Wrapper tipis rank_bm25 dengan fallback scoring overlap sederhana."""

    def __init__(self, docs_tokens: List[List[str]]):
        self.docs = docs_tokens
        self._bm25 = None
        try:
            from rank_bm25 import BM25Okapi  # type: ignore

            self._bm25 = BM25Okapi(docs_tokens) if docs_tokens else None
        except Exception as e:  # pragma: no cover - fallback path
            logger.debug(f"rank_bm25 unavailable ({e}); pakai fallback overlap.")

    def scores(self, query_tokens: List[str]) -> List[float]:
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
    docs: List[str],
    names: List[str],
    user_text: str,
    history: Optional[Iterable[Dict[str, Any]]] = None,
    k: Optional[int] = None,
) -> List[str]:
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

    scores = index.scores(q_tokens)
    ranked = sorted(zip(names, scores), key=lambda x: x[1], reverse=True)

    selected: List[str] = []
    for nm, _sc in ranked:
        if len(selected) >= kk:
            break
        if nm and nm not in selected and nm not in CORE_ALWAYS:
            selected.append(nm)
    selected.extend([c for c in CORE_ALWAYS if c not in selected])
    return list(dict.fromkeys(selected))


def select_relevant_functions(
    functions: List[Any],
    user_text: str,
    history: Optional[Iterable[Dict[str, Any]]] = None,
    top_k: Optional[int] = None,
) -> List[Any]:
    """
    Versi untuk daftar callable Python mentah (jalur Gemini native AFC):
    indeks dari __name__ + __doc__, lalu filter seperti select_relevant_tools.
    Fail-open ke daftar lengkap.
    """
    try:
        if not _ENABLED or not functions:
            return functions
        k = top_k or TOP_K
        if len(functions) <= k + len(CORE_ALWAYS):
            return functions

        names: List[str] = []
        docs: List[str] = []
        for f in functions:
            nm = getattr(f, "__name__", "")
            names.append(nm)
            docs.append(f"{nm} {(getattr(f, '__doc__', '') or '')[:600]}")

        keep = set(_rank_names(docs, names, user_text, history, k))
        filtered = [f for f in functions if getattr(f, "__name__", "") in keep]
        if not filtered:
            return functions
        logger.info(f"[ToolRAG] {len(functions)} -> {len(filtered)} fungsi "
                    f"(hemat ~{(len(functions) - len(filtered)) * 90} token/turn)")
        return filtered
    except Exception as e:
        logger.warning(f"[ToolRAG] fail-open ke set lengkap: {e}")
        return functions


def select_relevant_tools(
    tools_schema: List[Dict[str, Any]],
    user_text: str,
    history: Optional[Iterable[Dict[str, Any]]] = None,
    top_k: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    Filter skema tools OpenAI-style agar hanya TOP-K paling relevan dengan
    pesan user (+gabungan riwayat terakhir). CORE_ALWAYS selalu masuk.
    Return set lengkap bila fitur off/terjadi error/jumlah tool <= top_k.
    """
    try:
        if not _ENABLED or not tools_schema:
            return tools_schema
        k = top_k or TOP_K
        if len(tools_schema) <= k + len(CORE_ALWAYS):
            return tools_schema

        corpus_docs: List[List[str]] = []
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

        name_to_schema: Dict[str, Dict[str, Any]] = {}
        doc_names: List[str] = []
        for s, doc in zip(tools_schema, corpus_docs):
            nm = ((s.get("function") or {}).get("name")) or ""
            name_to_schema[nm] = s
            doc_names.append(nm)

        scores = index.scores(q_tokens)
        ranked = sorted(zip(doc_names, scores), key=lambda x: x[1], reverse=True)

        selected: List[str] = []
        for nm, _sc in ranked:
            if len(selected) >= k:
                break
            if nm and nm not in selected and nm not in CORE_ALWAYS:
                selected.append(nm)
        for core in CORE_ALWAYS:
            if core in name_to_schema:
                selected.append(core)

        filtered = [name_to_schema[nm] for nm in dict.fromkeys(selected) if nm in name_to_schema]
        if not filtered:  # safety net: jangan pernah kosongkan tools
            return tools_schema
        dropped = len(tools_schema) - len(filtered)
        logger.info(f"[ToolRAG] {len(tools_schema)} -> {len(filtered)} tool "
                    f"({dropped} disembunyikan; hemat ~{(len(tools_schema) - len(filtered)) * 90} token/turn)")
        return filtered
    except Exception as e:
        logger.warning(f"[ToolRAG] fail-open ke set lengkap: {e}")
        return tools_schema
