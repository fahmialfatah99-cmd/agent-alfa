"""Codebase full-text indexer and semantic/keyword search using SQLite FTS5."""

import logging
import os
import tempfile
import time
from typing import Any

from alfa.tools.filesystem.core_file import _MAX_EDIT_FILE_BYTES, _resolve_host_path
from alfa.tools.registry import register_tool

logger = logging.getLogger("AgentTools.Filesystem.CodeIndex")

_CODE_INDEX_DB = os.path.join(
    tempfile.gettempdir() if os.name == "nt" else "/dev/shm",
    "alfa_code_index.db",
)
_CODE_INDEX_MAX_CHUNKS = 10_000
_CODE_CHUNK_LINES = 60
_CODE_INDEX_SKIP_DIRS = {
    ".git",
    "venv",
    ".venv",
    "env",
    "__pycache__",
    "node_modules",
    "dist",
    "build",
    ".idea",
    ".vscode",
    "coverage",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "site-packages",
}


def _code_index_connect():
    import sqlite3

    conn = sqlite3.connect(_CODE_INDEX_DB, timeout=15)
    conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS code_fts USING fts5(
            rel_path, content, symbol UNINDEXED, repo_root UNINDEXED,
            start_line UNINDEXED, end_line UNINDEXED)
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS code_index_meta(
            repo_root TEXT PRIMARY KEY, indexed_at REAL,
            files INTEGER, chunks INTEGER)
    """)
    return conn


def _index_freshness(root: str, sample_paths: list[str]) -> dict[str, Any]:
    """Periksa apakah index masih segar: bandingkan mtime sampel file
    vs waktu indexing. Mengembalikan info kesegaran utk hasil pencarian."""
    import sqlite3 as _sq

    info: dict[str, Any] = {"stale": False, "indexed_at": None}
    if not root:
        return info
    try:
        conn = _sq.connect(_CODE_INDEX_DB, timeout=10)
        row = conn.execute(
            "SELECT indexed_at, files, chunks FROM code_index_meta WHERE repo_root = ?",
            (root,),
        ).fetchone()
        conn.close()
        if not row:
            info["stale"] = True
            info["note"] = (
                "index tidak tercatat meta-nya — jalankan ulang index_codebase."
            )
            return info
        indexed_at, files, chunks = row
        info["indexed_at"] = indexed_at
        info["files"] = files
        info["chunks"] = chunks
        changed = 0
        checked = 0
        for rel in sample_paths[:12]:
            fp = os.path.join(root, rel)
            try:
                checked += 1
                if os.path.getmtime(fp) > indexed_at:
                    changed += 1
            except OSError:
                continue
        if checked and changed:
            info["stale"] = True
            info["changed_sample"] = changed
    except Exception:
        pass
    return info


def _iter_code_files(root: str, extensions: str):
    exts = {
        "." + e.strip().lstrip(".").lower()
        for e in (extensions or "").split(",")
        if e.strip()
    }
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _CODE_INDEX_SKIP_DIRS]
        for name in filenames:
            if not exts or os.path.splitext(name)[1].lower() in exts:
                yield os.path.join(dirpath, name)


def _chunk_code_lines(lines):
    """Pecah file jadi chunk ~_CODE_CHUNK_LINES di batas baris kosong."""
    chunks, cur, sym = [], [], None
    import re as _re

    sym_re = _re.compile(
        r"^\s*(?:async\s+)?(?:def|class|function|func|fn|impl|type)\s+(\w+)"
    )
    for ln in lines:
        cur.append(ln)
        if len(cur) >= _CODE_CHUNK_LINES and ln.strip() == "":
            chunks.append((cur, sym))
            cur, sym = [], None
        elif sym is None:
            m = sym_re.match(ln)
            if m:
                sym = m.group(1)
    if cur:
        chunks.append((cur, sym))
    return chunks


def _index_one_file(fpath: str, root: str):
    """Baca + pecah satu file jadi chunk index rows (modul-level agar picklable
    untuk ProcessPoolExecutor). None = dilewati (terlalu besar / tak terbaca)."""
    try:
        if os.path.getsize(fpath) > _MAX_EDIT_FILE_BYTES:
            return None
        with open(fpath, encoding="utf-8", errors="replace") as f:
            lines = f.read().split("\n")
    except OSError:
        return None
    rel = os.path.relpath(fpath, root)
    rows = []
    offset = 0
    for chunk_lines, sym in _chunk_code_lines(lines):
        content = "\n".join(chunk_lines)
        n = len(chunk_lines)
        if content.strip():
            rows.append((rel, content, sym or "", root, offset + 1, offset + n))
        offset += n
    return (fpath, rows)


@register_tool(category="file")
def index_codebase(
    repo_path: str,
    file_extensions: str = "py,js,ts,tsx,jsx,go,rs,java,c,cpp,h,md,json,yaml,yml,toml",
) -> dict[str, Any]:
    """
    Build/refresh a full-text INDEX of a repository so later searches are fast
    and context-aware (RAG-style retrieval without external services).
    Run once per repo; call again after big changes to refresh.
    Repo besar (>40 file) diproses paralel lintas proses (ProcessPoolExecutor).

    Args:
        repo_path: Root directory of the project to index.
        file_extensions: Comma-separated extensions to include.
    """
    try:
        root = _resolve_host_path(repo_path)
        if not os.path.isdir(root):
            return {
                "status": "error",
                "message": f"Direktori tidak ditemukan: {repo_path}",
            }

        # Pengaman: jangan indeks home dir / filesystem root utuh — ini yang
        # dulu membengkakkan DB 857MB. Minta folder proyek spesifik.
        if os.path.realpath(root) in (os.path.realpath(os.path.expanduser("~")), "/"):
            return {
                "status": "error",
                "message": (
                    "[KEAMANAN DB] Folder terlalu luas (home/root). "
                    "Sebutkan folder proyek spesifik, mis. "
                    "~/alfa_projects/<nama-proyek>."
                ),
            }

        conn = _code_index_connect()
        files_scanned, chunks_inserted, skipped_big = 0, 0, 0
        truncated = False
        rows = []
        try:
            file_list = list(_iter_code_files(root, file_extensions))

            def _consume(result):
                """Gabungkan hasil satu file ke akumulator global."""
                nonlocal files_scanned, skipped_big
                if result is None:
                    skipped_big += 1
                    return
                _fpath, frows = result
                rows.extend(frows)
                files_scanned += 1

            # Paralel lintas proses utk repo besar (CPU-bound: baca+parse ribuan
            # file memblokir event loop bila dilakukan di satu proses).
            if len(file_list) >= 50:
                try:
                    from concurrent.futures import ProcessPoolExecutor

                    workers = max(2, min(4, (os.cpu_count() or 2)))
                    with ProcessPoolExecutor(max_workers=workers) as pool:
                        for res in pool.map(
                            _index_one_file,
                            file_list[: _CODE_INDEX_MAX_CHUNKS * 3],
                            (root,),
                        ):
                            _consume(res)
                except Exception as pe:
                    logger.warning(f"Index paralel gagal ({pe}); fallback sekuensial.")
                    rows.clear()
                    files_scanned, skipped_big = 0, 0
                    for fpath in file_list:
                        _consume(_index_one_file(fpath, root))
            else:
                for fpath in file_list:
                    _consume(_index_one_file(fpath, root))

            if len(rows) >= _CODE_INDEX_MAX_CHUNKS:
                rows = rows[:_CODE_INDEX_MAX_CHUNKS]
                truncated = True

            # SATU transaksi utk seluruh index (hindari lock war dgn service lain)
            with conn:
                conn.execute("DELETE FROM code_fts WHERE repo_root = ?", (root,))
                conn.executemany(
                    "INSERT INTO code_fts(rel_path, content, symbol, repo_root, start_line, end_line) "
                    "VALUES (?,?,?,?,?,?)",
                    rows,
                )
                chunks_inserted = len(rows)
                conn.execute(
                    "INSERT INTO code_index_meta(repo_root, indexed_at, files, chunks) "
                    "VALUES (?,?,?,?) ON CONFLICT(repo_root) DO UPDATE SET "
                    "indexed_at=excluded.indexed_at, files=excluded.files, chunks=excluded.chunks",
                    (root, time.time(), files_scanned, chunks_inserted),
                )
        finally:
            conn.close()

        return {
            "status": "success",
            "message": (
                f"Index selesai: {files_scanned} file, {chunks_inserted} chunk tersimpan"
                f"{' (' + str(skipped_big) + ' file besar dilewati)' if skipped_big else ''}"
                f"{f'. [DIPOTONG di batas {_CODE_INDEX_MAX_CHUNKS} chunk — indeks folder lebih spesifik bila perlu]' if truncated else ''}."
            ),
            "files_indexed": files_scanned,
            "chunks": chunks_inserted,
            "truncated": truncated,
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@register_tool(category="file")
def search_codebase(query: str, repo_path: str = "", limit: int = 10) -> dict[str, Any]:
    """
    Search an indexed repository semantically-by-keyword (FTS5 ranked).
    Returns the most relevant code chunks with file:line references.
    Call index_codebase() first if this returns 'index kosong'.

    Args:
        query: Keywords or phrase, e.g. 'generate video ffmpeg overlay'.
        repo_path: Optional root to restrict search to one project.
        limit: Max results.
    """
    try:
        if not query.strip():
            return {"status": "error", "message": "Query kosong."}
        conn = _code_index_connect()
        try:
            sql = (
                "SELECT rel_path, content, symbol, repo_root, start_line, end_line, "
                "snippet(code_fts, 1, '>>>', '<<<', ' … ', 12) AS snip "
                "FROM code_fts WHERE code_fts MATCH ? "
            )
            params = [query.strip()]
            if repo_path.strip():
                sql += "AND repo_root = ? "
                params.append(_resolve_host_path(repo_path))
            sql += "ORDER BY rank LIMIT ?"
            params.append(int(limit))
            rows = conn.execute(sql, params).fetchall()
        finally:
            conn.close()

        if not rows:
            return {
                "status": "empty",
                "message": "Tidak ada hasil. Index mungkin belum dibuat — panggil index_codebase dulu.",
            }

        results = [
            {
                "location": f"{r[0]}:{r[4]}-{r[5]}",
                "symbol": r[2] or None,
                "snippet": r[6],
            }
            for r in rows
        ]

        # Cek kesegaran index utk repo-repo yang muncul di hasil
        roots = list(dict.fromkeys(r[3] for r in rows))
        sample_by_root: dict[str, list[str]] = {}
        for r in rows:
            sample_by_root.setdefault(r[3], []).append(r[0])
        stale_roots = []
        for rt in roots:
            info = _index_freshness(rt, sample_by_root.get(rt, []))
            if info.get("stale"):
                stale_roots.append(rt)
        resp = {"status": "success", "matches": len(results), "results": results}
        if stale_roots:
            resp["index_stale_warning"] = (
                f"Index untuk {len(stale_roots)} repo sudah USANG (ada file berubah "
                f"setelah indexing). Jalankan index_codebase lagi utk hasil akurat."
            )
            logger.warning(resp["index_stale_warning"])
        return resp
    except Exception as e:
        return {"status": "error", "message": str(e)}
