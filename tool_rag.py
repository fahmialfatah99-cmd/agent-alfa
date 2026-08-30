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

# Sinonim ID->EN dan istilah teknis operasional untuk menjembatani prompt
# pengguna bahasa Indonesia & Inggris dengan deskripsi tool teknis.
_SYNONYMS = {
    # System, Hardware & OS
    "screenshot": "capture desktop screenshot display monitor screen",
    "screnshoot": "capture desktop screenshot display monitor screen",
    "ss": "capture desktop screenshot display monitor screen",
    "rekam": "record screen video capture", "perekam": "record screen video",
    "layar": "screen desktop display monitor", "tangkap": "capture screenshot snapshot",
    "layanan": "service systemd daemon manage status restart", "servis": "service systemctl",
    "restart": "restart reboot service reload", "matikan": "stop kill shutdown terminate",
    "bunuh": "kill terminate process", "proses": "process running pid htop ps",
    "penjaga": "guardian proactive threshold health monitor heal",
    "terminal": "bash shell command cli execute exec", "perintah": "command bash execute cli",
    "jadwal": "cron crontab schedule reminder recurring timer",
    "pengingat": "reminder schedule notify alarm",
    "suhu": "hardware battery wifi bluetooth volume system",
    "bersih": "clean storage disk free space", "kapasitas": "storage disk df du usage",
    "jaringan": "network scan wifi ip port devices ping benchmark speedtest",
    "keamanan": "security audit password ssl vulnerability hash",
    "sandi": "password secure generate token credential",

    # Web, Scraper, & Browser
    "cari": "search web query duckduckgo find google",
    "telusuri": "search research explore web",
    "riset": "research academic paper deep search study",
    "unduh": "download fetch get file url",
    "ambil": "fetch scrape extract crawl download get",
    "ekstrak": "extract parse scrape convert text content",
    "ramping": "scrapling stealth scrape anti-bot bypass",
    "rayap": "crawler crawlee crawl4ai spider scrape",
    "jelajah": "browser open click type navigate visual",
    "otomatisasi": "browser_use autonomous robot task web",

    # Files, Documents & Code
    "berkas": "file local read write edit modify document",
    "baca": "read local file view cat head",
    "tulis": "write create save local file edit",
    "ubah": "edit replace precise modify patch diff",
    "folder": "directory workspace folder search list tree",
    "kode": "code index python script lsp symbol function",
    "koding": "code python execute sandbox program script",
    "git": "git commit push pull branch worktree diff status repository repo",
    "pustaka": "codebase search index grep symbol lsp",

    # Media, Audio, Video & PDF
    "gambar": "image photo picture edit upscale crop rotate watermark",
    "foto": "image photo picture vision camera frame webcam",
    "video": "video promo tiktok generate extract audio mp4 ffmpeg",
    "suara": "voice audio speech tts edge mp3 synthesize speech",
    "dokumen": "document pdf docx odt writer libreoffice markitdown text",
    "presentasi": "presentation pptx powerpoint slides impress",
    "tabel": "excel spreadsheet xlsx csv dataset analyze chart data",

    # PDF Specific Operations
    "pdf": "pdf merge split extract encrypt decrypt rotate watermark report compress",
    "gabung": "merge combine pdf documents",
    "pisah": "split divide extract page range",
    "kunci": "encrypt password protect secure pdf vault",
    "buka": "decrypt unlock password open",
    "putar": "rotate angle pdf page",

    # Memory, Brain & Agents
    "ingat": "memory remember save knowledge fact store",
    "simpan": "save store write memory ingest vector vault secret",
    "vektor": "vector brain semantic embedding ingest search similarity rag",
    "rapat": "meeting swarm conduct agents discussion debate consensus",
    "agen": "agent custom swarm subagent background workforce",
    "rahasia": "vault secret encrypt reveal token api key passkey",
    "kunci_api": "api_keys manage provider activate validate gemini groq",
    "afiliasi": "affiliate trending viral copywriting broadcast shopee tokped",
    "kirim": "send deliver broadcast telegram chat email message",
    "terjemah": "translate translation language convert text",
    "fokus": "focus session pomodoro timer work",
}

# Domain Category Keywords untuk Intent Boosting
_CATEGORY_BOOSTS = {
    "pdf": ["generate_pdf_report", "pdf_merge_documents", "pdf_split_document", "pdf_extract_full_text",
            "pdf_encrypt_password", "pdf_decrypt_password", "pdf_rotate_pages", "images_convert_to_pdf",
            "pdf_apply_watermark_text", "pdf_compress_and_optimize"],
    "system": ["get_system_stats", "execute_bash_command", "manage_system_services", "list_running_processes",
               "kill_process", "clean_system_storage", "auto_diagnose_and_heal_system", "manage_crontab_jobs"],
    "code": ["execute_python_sandbox", "read_local_file", "write_local_file", "edit_file_precise",
             "search_codebase", "index_codebase", "git_operations", "grep_workspace"],
    "web": ["web_search", "fetch_web_page_content", "deep_research_topic", "browser_open_url",
            "scrapling_stealth_fetch", "crawl4ai_web_crawler", "universal_deep_scraper"],
    "media": ["edit_image", "text_to_audio_file", "extract_audio_from_video", "convert_media_format",
              "generate_promo_video_from_images", "analyze_dataset_csv_json"],
    "memory": ["save_knowledge_memory", "search_knowledge_memory", "semantic_search_vector_brain",
               "ingest_document_to_vector_brain", "list_vector_brain_documents", "export_knowledge_base"],
    "agent": ["spawn_background_subagent", "check_subagent_status", "conduct_ai_meeting", "manage_custom_agents"]
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

    scores = list(index.scores(q_tokens))
    q_set = set(q_tokens)
    for cat_name, cat_tools in _CATEGORY_BOOSTS.items():
        if cat_name in q_set or any(cat_name in t for t in q_tokens):
            for i, nm in enumerate(names):
                if nm in cat_tools:
                    scores[i] += 2.5

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

        if not _ENABLED:
            return unique_funcs

        k = top_k or TOP_K
        if len(unique_funcs) <= k + len(CORE_ALWAYS):
            return unique_funcs

        names: List[str] = []
        docs: List[str] = []
        for f in unique_funcs:
            nm = getattr(f, "__name__", "")
            names.append(nm)
            docs.append(f"{nm} {(getattr(f, '__doc__', '') or '')[:600]}")

        keep = set(_rank_names(docs, names, user_text, history, k))
        filtered = []
        seen_filtered = set()
        for f in unique_funcs:
            nm = getattr(f, "__name__", "")
            if nm in keep and nm not in seen_filtered:
                seen_filtered.add(nm)
                filtered.append(f)

        if not filtered:
            return unique_funcs

        logger.info(f"[ToolRAG] {len(unique_funcs)} -> {len(filtered)} fungsi unik "
                    f"(hemat ~{(len(unique_funcs) - len(filtered)) * 90} token/turn)")
        return filtered
    except Exception as e:
        logger.warning(f"[ToolRAG] fail-open ke set lengkap: {e}")
        # Tetap deduplikasi saat fallback error
        seen_fallback = set()
        fallback_funcs = []
        for f in (functions or []):
            nm = getattr(f, "__name__", "")
            if nm and nm not in seen_fallback:
                seen_fallback.add(nm)
                fallback_funcs.append(f)
            elif not nm and f not in fallback_funcs:
                fallback_funcs.append(f)
        return fallback_funcs


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

        scores = list(index.scores(q_tokens))
        q_set = set(q_tokens)
        for cat_name, cat_tools in _CATEGORY_BOOSTS.items():
            if cat_name in q_set or any(cat_name in t for t in q_tokens):
                for i, nm in enumerate(doc_names):
                    if nm in cat_tools:
                        scores[i] += 2.5

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
