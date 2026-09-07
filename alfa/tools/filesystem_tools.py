"""Filesystem, workspace search, codebase indexer, git, and document tools."""

import datetime
import difflib
import glob
import json
import logging
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from typing import Any, Dict, List, Optional, Tuple

import database
from alfa.core.runtime_ctx import (
    current_chat_id_var,
    current_user_id_var,
    get_current_chat_id,
    get_current_user_id,
)
from alfa.tools.registry import register_tool
from alfa.tools.system_tools import SANDBOX_DIR, normalize_path

# Facade re-exports for git worktrees, LSP, and Google Drive
from git_sandbox import (
    git_worktree_sandbox_create as git_worktree_sandbox_create,
    git_worktree_sandbox_list as git_worktree_sandbox_list,
    git_worktree_sandbox_rollback as git_worktree_sandbox_rollback,
    git_worktree_sandbox_verify_and_merge as git_worktree_sandbox_verify_and_merge,
)
from lsp_code_intelligence import (
    lsp_analyze_module_hierarchy as lsp_analyze_module_hierarchy,
    lsp_find_symbol_definition as lsp_find_symbol_definition,
    lsp_find_symbol_references as lsp_find_symbol_references,
)
from alfa.integrations.gdrive import (
    _detect_gdrive_auth_mode as _detect_gdrive_auth_mode,
    _get_default_gdrive_folder_id as _get_default_gdrive_folder_id,
    _get_gdrive_service as _get_gdrive_service,
    gdrive_create_folder as gdrive_create_folder,
    gdrive_download_file as gdrive_download_file,
    gdrive_list_files as gdrive_list_files,
    gdrive_oauth_exchange_code as gdrive_oauth_exchange_code,
    gdrive_oauth_get_auth_url as gdrive_oauth_get_auth_url,
    gdrive_oauth_login as gdrive_oauth_login,
    gdrive_oauth_logout as gdrive_oauth_logout,
    gdrive_save_oauth_client_secret as gdrive_save_oauth_client_secret,
    gdrive_status as gdrive_status,
    gdrive_sync_to_second_brain as gdrive_sync_to_second_brain,
    gdrive_upload_file as gdrive_upload_file,
)

logger = logging.getLogger("AgentTools.Filesystem")

_MAX_EDIT_FILE_BYTES = 2 * 1024 * 1024

_CODE_INDEX_DB = os.path.join(
    tempfile.gettempdir() if os.name == "nt" else "/dev/shm",
    "alfa_code_index.db",
)
_CODE_INDEX_MAX_CHUNKS = 10_000
_CODE_CHUNK_LINES = 60
_CODE_INDEX_SKIP_DIRS = {
    ".git", "venv", ".venv", "env", "__pycache__", "node_modules",
    "dist", "build", ".idea", ".vscode", "coverage", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", "site-packages",
}



@register_tool(category="file")
def read_local_file(file_path: str, max_lines: int = 300, start_line: int = 1) -> Dict[str, Any]:
    """
    Read the text content of a local file on the system safely.
    
    Args:
        file_path: Absolute or relative path to the file.
        max_lines: Maximum number of lines to read (default: 300).
        start_line: Starting line number (1-indexed).
    """
    try:
        file_path = normalize_path(file_path)
        expanded_path = os.path.expanduser(file_path)
        if not os.path.isabs(expanded_path):
            expanded_path = os.path.join(os.path.expanduser("~"), file_path)

        if not os.path.exists(expanded_path):
            base = os.path.basename(file_path) or "*"
            hint = f"[SELF_HEAL_HINT] File '{file_path}' tidak ditemukan. Gunakan `search_workspace_files` dengan pattern='*{base}*' atau `grep_workspace` untuk mencari lokasi berkas."
            return {"status": "error", "message": f"File tidak ditemukan: {file_path}", "self_heal_hint": hint}
        
        if os.path.isdir(expanded_path):
            files = os.listdir(expanded_path)
            return {"status": "is_directory", "files": files[:50], "total": len(files)}

        with open(expanded_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
            
        total_lines = len(lines)
        start_idx = max(0, start_line - 1)
        end_idx = min(total_lines, start_idx + max_lines)
        selected_lines = lines[start_idx:end_idx]
        
        numbered_content = "".join([f"{i+1}: {line}" for i, line in enumerate(selected_lines, start=start_idx)])
            
        return {
            "status": "success",
            "file_path": expanded_path,
            "total_lines": total_lines,
            "showing_lines": f"{start_idx+1} to {end_idx}",
            "content": numbered_content
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@register_tool(category="file")
def write_local_file(file_path: str, content: str) -> Dict[str, Any]:
    """
    Write or create a text file on the local system.
    
    Args:
        file_path: Path to the target file.
        content: Text content to write.
    """
    try:
        file_path = normalize_path(file_path)
        expanded_path = os.path.expanduser(file_path)
        if not os.path.isabs(expanded_path):
            expanded_path = os.path.join(os.path.expanduser("~"), file_path)

        os.makedirs(os.path.dirname(expanded_path), exist_ok=True)
        with open(expanded_path, "w", encoding="utf-8") as f:
            f.write(content)

        return {"status": "success", "message": f"File berhasil disimpan di {expanded_path} ({len(content)} karakter)"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def _py_syntax_guard(path: str, original_content: str) -> Optional[str]:
    """Validasi sintaks Python pasca-edit; rollback bila rusak.

    Mengembalikan pesan error (dan memulihkan isi lama) bila file .py kini
    gagal dikompilasi; mengembalikan None bila aman/bukan file Python.
    """
    if not path.endswith(".py"):
        return None
    try:
        with open(path, "r", encoding="utf-8", errors="surrogateescape") as f:
            new_content = f.read()
        compile(new_content, path, "exec")
        return None
    except SyntaxError as syn:
        with open(path, "w", encoding="utf-8", errors="surrogateescape") as f:
            f.write(original_content)
        return (f"Edit DIBATALKAN (auto-rollback): hasil menyebabkan SyntaxError "
                f"di baris {syn.lineno}: {syn.msg}. Isi file dikembalikan seperti semula.")


def _resolve_host_path(file_path: str) -> str:
    file_path = normalize_path(file_path)
    expanded = os.path.expanduser(file_path)
    if not os.path.isabs(expanded):
        expanded = os.path.join(os.path.expanduser("~"), file_path)
    return os.path.realpath(expanded)


@register_tool(category="file")
def edit_file_precise(file_path: str, old_text: str, new_text: str,
                      occurrence: int = 0) -> Dict[str, Any]:
    """
    Edit a file with SURGICAL precision (opencode-style): replace an exact
    unique snippet instead of rewriting the whole file. old_text must match
    the file content EXACTLY (including indentation).

    Safety rule: if old_text matches MULTIPLE locations, the call FAILS and
    you must pass `occurrence` (1-based index of the match to replace,
    -1 = last match) or include more surrounding context.

    Args:
        file_path: Path to the existing text file.
        old_text: Exact existing snippet to replace.
        new_text: Replacement text.
        occurrence: 0 = require unique match (default); N = replace Nth match;
                    -1 = replace last match.
    """
    try:
        p = _resolve_host_path(file_path)
        if not os.path.isfile(p):
            return {"status": "error", "message": f"File tidak ditemukan: {file_path}"}
        if os.path.getsize(p) > _MAX_EDIT_FILE_BYTES:
            return {"status": "error", "message": f"File terlalu besar (>2MB): {file_path}"}
        if not old_text:
            return {"status": "error", "message": "old_text kosong — gunakan write_local_file untuk membuat isi baru."}

        with open(p, "r", encoding="utf-8", errors="surrogateescape") as f:
            content = f.read()

        count = content.count(old_text)
        if count == 0:
            # Bantu model: cari kandidat mirip (abaikan trailing whitespace per baris)
            norm_old = "\n".join(line.rstrip() for line in old_text.splitlines())
            lines = content.splitlines()
            best, best_score = None, 0.0
            window = len(old_text.splitlines())
            for i in range(0, max(1, len(lines) - window + 1)):
                cand = "\n".join(lines[i:i + window])
                score = difflib.SequenceMatcher(None, norm_old,
                                                "\n".join(ln.rstrip() for ln in cand.splitlines())).ratio()
                if score > best_score:
                    best, best_score = (i + 1, cand), score
            hint = ""
            if best and best_score > 0.6:
                hint = (f" Kemungkinan yang dimaksud di sekitar baris {best[0]} "
                        f"(kemiripan {best_score:.0%}). Salin teks persis dari file.")
            return {"status": "error",
                    "message": f"old_text tidak ditemukan di {file_path}.{hint}"}

        if occurrence == 0 and count > 1:
            return {"status": "error",
                    "message": (f"old_text cocok di {count} lokasi berbeda. "
                                "Tambahkan konteks lebih banyak agar unik, atau sebutkan "
                                "`occurrence` (1=ke-N, -1=terakhir). Tidak ada perubahan ditulis.")}

        # Resolusi indeks kecocokan: -1=terakhir, 0/unik=pertama, N=ke-N
        idx = count + 1 + occurrence if occurrence < 0 else max(1, occurrence)
        if not (1 <= idx <= count):
            return {"status": "error",
                    "message": f"occurrence={occurrence} di luar rentang; ditemukan {count} kecocokan."}

        start = 0
        for _ in range(idx):
            pos = content.find(old_text, start)
            start = pos + 1
        new_content = content[:pos] + new_text + content[pos + len(old_text):]

        with open(p, "w", encoding="utf-8", errors="surrogateescape") as f:
            f.write(new_content)

        syn_err = _py_syntax_guard(p, content)
        if syn_err:
            return {"status": "error", "message": syn_err}

        return {
            "status": "success",
            "message": (f"Berhasil mengganti {len(old_text)} -> {len(new_text)} karakter "
                        f"di {file_path} (kecocokan #{idx}/{count})."),
            "line_hint": content.count("\n", 0, pos) + 1,
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@register_tool(category="file")
def apply_unified_diff(file_path: str, diff_text: str) -> Dict[str, Any]:
    """
    Apply a UNIFIED DIFF (format `diff -u` / git diff) to a single file with
    context-matching and small drift tolerance — like `patch` but built-in.
    Only one file per call. All hunks must apply or nothing is written.

    Args:
        file_path: Path to the target text file.
        diff_text: Unified diff body (lines starting with ---/+++ are ignored;
                   hunks start with @@).
    """
    import re as _re
    try:
        p = _resolve_host_path(file_path)
        if not os.path.isfile(p):
            return {"status": "error", "message": f"File tidak ditemukan: {file_path}"}
        if os.path.getsize(p) > _MAX_EDIT_FILE_BYTES:
            return {"status": "error", "message": f"File terlalu besar (>2MB): {file_path}"}

        with open(p, "r", encoding="utf-8", errors="surrogateescape") as f:
            orig_lines = f.read().split("\n")

        # Parse hunks
        hunks, cur = [], None
        for raw in diff_text.split("\n"):
            if raw.startswith("@@"):
                m = _re.match(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", raw)
                if m:
                    cur = {"old": [], "new": [], "new_start": int(m.group(1))}
                    hunks.append(cur)
                continue
            if cur is None:
                continue
            if raw.startswith(("---", "+++")) or raw.startswith("\\ No newline"):
                continue
            tag = raw[:1]
            if tag == "+":
                cur["new"].append(raw[1:])
            elif tag == "-":
                cur["old"].append(raw[1:])
            elif raw.startswith("\\ No newline"):
                continue
            else:
                # Baris konteks: format baku ' teks'; toleransi model tanpa spasi
                body = raw[1:] if raw.startswith(" ") else raw
                cur["old"].append(body)
                cur["new"].append(body)

        if not hunks:
            return {"status": "error",
                    "message": "Tidak ada hunk @@ valid dalam diff. Pastikan format unified diff."}

        lines = list(orig_lines)
        applied = 0
        cursor = 0
        for hno, h in enumerate(hunks, 1):
            anchor = next((ln for ln in h["old"] if ln.strip()), "")
            n_old = len(h["old"])
            candidates = []
            if anchor:
                for i in range(cursor, min(len(lines), max(len(lines), h["new_start"] + 80))):
                    if lines[i] == anchor:
                        candidates.append(i - h["old"].index(anchor))
                        if len(candidates) >= 3:
                            break
            chosen = None
            for base in candidates + [h["new_start"] - 1]:
                if base is None or base < 0:
                    continue
                seg = lines[base:base + n_old]
                if [x.strip() for x in seg] == [x.strip() for x in h["old"]] or seg == h["old"]:
                    chosen = base
                    break
            if chosen is None:
                return {"status": "error",
                        "message": (f"Hunk #{hno} gagal diterapkan (konteks tidak cocok "
                                    f"di sekitar '{anchor[:60]}'). Tidak ada perubahan ditulis. "
                                    "Baca ulang file & buat diff baru."),
                        "hunks_applied_before_fail": applied}

            lines[chosen:chosen + n_old] = h["new"]
            cursor = chosen + len(h["new"])
            applied += 1

        with open(p, "w", encoding="utf-8", errors="surrogateescape") as f:
            f.write("\n".join(lines))

        syn_err = _py_syntax_guard(p, "\n".join(orig_lines))
        if syn_err:
            return {"status": "error", "message": syn_err}

        return {"status": "success",
                "message": f"{applied}/{len(hunks)} hunk berhasil diterapkan ke {file_path}.",
                "hunks_applied": applied}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@register_tool(category="file")
def search_workspace_files(pattern: str, base_dir: str = "~", max_results: int = 30) -> Dict[str, Any]:
    """
    Search for files and directories matching a glob pattern (e.g. '*.py', '*.json', 'bot*').
    
    Args:
        pattern: Glob pattern to search.
        base_dir: Root search directory (default: user home).
        max_results: Maximum number of files to return.
    """
    try:
        root_dir = os.path.expanduser(normalize_path(base_dir))
        matches = []
        for root, dirs, files in os.walk(root_dir):
            # Ignore heavy/hidden directories
            dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ('node_modules', 'venv', '__pycache__', 'dist', 'build')]
            for name in files:
                if glob.fnmatch.fnmatch(name, pattern) or pattern.lower() in name.lower():
                    rel = os.path.relpath(os.path.join(root, name), root_dir)
                    matches.append(rel)
                    if len(matches) >= max_results:
                        break
            if len(matches) >= max_results:
                break

        return {
            "status": "success",
            "base_dir": root_dir,
            "matches_count": len(matches),
            "files": matches
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@register_tool(category="file")
def grep_workspace(query: str, base_dir: str = "~", file_pattern: str = "") -> Dict[str, Any]:
    """
    Search for text or regex pattern inside files across workspace.
    
    Args:
        query: String or regex query to find.
        base_dir: Search directory.
        file_pattern: Optional glob filter for files (e.g. '*.py').
    """
    try:
        root_dir = os.path.expanduser(normalize_path(base_dir))
        if os.name == "nt":
            # Windows: cari dengan Python murni (biner 'grep' tidak di PATH)
            import re as _re
            try:
                rx = _re.compile(query)
                use_regex = True
            except _re.error:
                use_regex = False
            matches = []
            for r, dirs, files in os.walk(root_dir):
                dirs[:] = [d for d in dirs if d not in _CODE_INDEX_SKIP_DIRS]
                for fn in files:
                    if file_pattern and not glob.fnmatch.fnmatch(fn, file_pattern):
                        continue
                    fpath = os.path.join(r, fn)
                    try:
                        if os.path.getsize(fpath) > 2 * 1024 * 1024:
                            continue
                        with open(fpath, "r", encoding="utf-8", errors="ignore") as fh:
                            for i, ln in enumerate(fh, 1):
                                ok = rx.search(ln) if use_regex else (query.lower() in ln.lower())
                                if ok:
                                    matches.append(f"{fpath}:{i}:{ln.strip()[:200]}")
                                    if len(matches) >= 30:
                                        raise StopIteration
                    except StopIteration:
                        raise
                    except OSError:
                        continue
            return {"status": "success", "matches_count": len(matches), "results": matches[:30]}
        cmd = ["grep", "-rnI", "--exclude-dir={.git,venv,node_modules,__pycache__}"]
        if file_pattern:
            cmd.append(f"--include={file_pattern}")
        cmd.extend([query, root_dir])

        res = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        lines = res.stdout.strip().split("\n") if res.stdout.strip() else []
        
        return {
            "status": "success",
            "matches_count": len(lines),
            "results": lines[:30]
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


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


def _index_freshness(root: str, sample_paths: List[str]) -> Dict[str, Any]:
    """Periksa apakah index masih segar: bandingkan mtime sampel file
    vs waktu indexing. Mengembalikan info kesegaran utk hasil pencarian."""
    import sqlite3 as _sq
    info: Dict[str, Any] = {"stale": False, "indexed_at": None}
    if not root:
        return info
    try:
        conn = _sq.connect(_CODE_INDEX_DB, timeout=10)
        row = conn.execute(
            "SELECT indexed_at, files, chunks FROM code_index_meta WHERE repo_root = ?",
            (root,)).fetchone()
        conn.close()
        if not row:
            info["stale"] = True
            info["note"] = "index tidak tercatat meta-nya — jalankan ulang index_codebase."
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
    exts = {"." + e.strip().lstrip(".").lower()
            for e in (extensions or "").split(",") if e.strip()}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _CODE_INDEX_SKIP_DIRS]
        for name in filenames:
            if not exts or os.path.splitext(name)[1].lower() in exts:
                yield os.path.join(dirpath, name)


def _chunk_code_lines(lines):
    """Pecah file jadi chunk ~_CODE_CHUNK_LINES di batas baris kosong."""
    chunks, cur, sym = [], [], None
    import re as _re
    sym_re = _re.compile(r"^\s*(?:async\s+)?(?:def|class|function|func|fn|impl|type)\s+(\w+)")
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
        with open(fpath, "r", encoding="utf-8", errors="replace") as f:
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
def index_codebase(repo_path: str, file_extensions: str = "py,js,ts,tsx,jsx,go,rs,java,c,cpp,h,md,json,yaml,yml,toml") -> Dict[str, Any]:
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
            return {"status": "error", "message": f"Direktori tidak ditemukan: {repo_path}"}

        # Pengaman: jangan indeks home dir / filesystem root utuh — ini yang
        # dulu membengkakkan DB 857MB. Minta folder proyek spesifik.
        if os.path.realpath(root) in (
            os.path.realpath(os.path.expanduser("~")), "/"
        ):
            return {
                "status": "error",
                "message": ("[KEAMANAN DB] Folder terlalu luas (home/root). "
                            "Sebutkan folder proyek spesifik, mis. "
                            "~/alfa_projects/<nama-proyek>."),
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
                        for res in pool.map(_index_one_file,
                                            file_list[:_CODE_INDEX_MAX_CHUNKS * 3],
                                            (root,)):
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
                    "VALUES (?,?,?,?,?,?)", rows)
                chunks_inserted = len(rows)
                conn.execute(
                    "INSERT INTO code_index_meta(repo_root, indexed_at, files, chunks) "
                    "VALUES (?,?,?,?) ON CONFLICT(repo_root) DO UPDATE SET "
                    "indexed_at=excluded.indexed_at, files=excluded.files, chunks=excluded.chunks",
                    (root, time.time(), files_scanned, chunks_inserted))
        finally:
            conn.close()

        return {
            "status": "success",
            "message": (f"Index selesai: {files_scanned} file, {chunks_inserted} chunk tersimpan"
                        f"{' (' + str(skipped_big) + ' file besar dilewati)' if skipped_big else ''}"
                        f"{f'. [DIPOTONG di batas {_CODE_INDEX_MAX_CHUNKS} chunk — indeks folder lebih spesifik bila perlu]' if truncated else ''}."),
            "files_indexed": files_scanned,
            "chunks": chunks_inserted,
            "truncated": truncated,
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@register_tool(category="file")
def search_codebase(query: str, repo_path: str = "", limit: int = 10) -> Dict[str, Any]:
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
            sql = ("SELECT rel_path, content, symbol, repo_root, start_line, end_line, "
                   "snippet(code_fts, 1, '>>>', '<<<', ' … ', 12) AS snip "
                   "FROM code_fts WHERE code_fts MATCH ? ")
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
            return {"status": "empty",
                    "message": "Tidak ada hasil. Index mungkin belum dibuat — panggil index_codebase dulu."}

        results = [{
            "location": f"{r[0]}:{r[4]}-{r[5]}",
            "symbol": r[2] or None,
            "snippet": r[6],
        } for r in rows]

        # Cek kesegaran index utk repo-repo yang muncul di hasil
        roots = list(dict.fromkeys(r[3] for r in rows))
        sample_by_root: Dict[str, List[str]] = {}
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
                f"setelah indexing). Jalankan index_codebase lagi utk hasil akurat.")
            logger.warning(resp["index_stale_warning"])
        return resp
    except Exception as e:
        return {"status": "error", "message": str(e)}


@register_tool(category="file")
def find_user_files(pattern: str = "", file_types: str = "all", folder: str = "") -> Dict[str, Any]:
    """
    Cari file/aset ASLI yang disediakan pengguna di folder-folder umum
    (Downloads, Documents, Desktop, Pictures). WAJIB dipanggil sebelum
    membuat gambar/dokumen sendiri bila user menyebut 'sudah disediakan'.

    Args:
        pattern: Kata kunci nama file (mis. 'porsche', 'logo', 'laporan'). Kosong = semua.
        file_types: 'image', 'video', 'audio', 'doc', 'archive', 'data', atau 'all'.
        folder: Nama subfolder spesifik di dalam lokasi umum (mis. 'WEBSITE PROMOSI').
    """
    try:
        from datetime import datetime as _dtmod
        home = os.path.expanduser("~")
        roots = [os.path.join(home, f) for f in ("Downloads", "Documents", "Desktop", "Pictures")]
        if folder:
            roots = [os.path.join(r, folder) for r in roots]

        ext_map = {
            "image": {".jpg", ".jpeg", ".png", ".webp", ".avif", ".gif", ".bmp", ".svg", ".heic"},
            "video": {".mp4", ".mov", ".mkv", ".webm", ".avi"},
            "audio": {".mp3", ".wav", ".ogg", ".m4a", ".flac"},
            "doc": {".pdf", ".docx", ".xlsx", ".pptx", ".txt", ".md", ".csv"},
            "archive": {".zip", ".rar", ".7z", ".tar", ".gz"},
            "data": {".json", ".xml", ".yaml", ".yml", ".db"},
        }
        wanted = set()
        for t in file_types.split(","):
            t = t.strip().lower()
            if t == "all":
                wanted |= set().union(*ext_map.values())
            elif t in ext_map:
                wanted |= ext_map[t]
        if not wanted:
            wanted |= set().union(*ext_map.values())

        skip_dirs = {"node_modules", ".git", "venv", "__pycache__", "AppData",
                     "_backup-pre-audit", "_evidence"}
        results = []
        pat = pattern.strip().lower()
        for root in roots:
            if not os.path.isdir(root):
                continue
            for dirpath, dirnames, filenames in os.walk(root):
                dirnames[:] = [d for d in dirnames if d not in skip_dirs and not d.startswith(".")]
                for fn in filenames:
                    low = fn.lower()
                    ext = os.path.splitext(low)[1]
                    if ext not in wanted:
                        continue
                    if pat and pat not in low:
                        continue
                    fp = os.path.join(dirpath, fn)
                    try:
                        st = os.stat(fp)
                        if st.st_size < 1024:  # skip file korup/tersembunyi kecil
                            continue
                        results.append({
                            "path": fp,
                            "name": fn,
                            "size_mb": round(st.st_size / 1024 / 1024, 2),
                            "modified": _dtmod.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M"),
                        })
                    except OSError:
                        continue
        # terbaru dulu, batasi 25
        results.sort(key=lambda x: x["modified"], reverse=True)
        return {
            "status": "success",
            "total": len(results),
            "files": results[:25],
            "message": (f"Ditemukan {len(results)} file. GUNAKAN path asli ini — "
                        "DILARANG membuat gambar/file dummy pengganti.") if results
                        else "Tidak ditemukan. Konfirmasi ke pengguna bila perlu.",
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@register_tool(category="file")
def compress_folder_to_zip(folder_path: str, output_filename: str = "archive.zip") -> Dict[str, Any]:
    """
    Compress an entire folder/directory into a ZIP archive and send it to Telegram.
    Use this when the user wants to send a whole folder, backup a project, or archive files.
    
    Args:
        folder_path: Path to the folder to compress (e.g. '~/Documents/project', '~/telegram-ai-bot').
        output_filename: Output ZIP filename (default: archive.zip).
    """
    try:
        import shutil
        expanded = os.path.expanduser(folder_path)
        if not os.path.isdir(expanded):
            return {"status": "error", "message": f"Folder tidak ditemukan: {folder_path}"}
        
        safe_name = output_filename.replace(".zip", "")
        zip_base = os.path.join(SANDBOX_DIR, safe_name)
        result_path = shutil.make_archive(zip_base, 'zip', expanded)
        
        size_mb = os.path.getsize(result_path) / (1024 * 1024)
        if size_mb > 50:
            os.remove(result_path)
            return {"status": "error", "message": f"Ukuran ZIP ({round(size_mb, 1)} MB) melebihi batas Telegram (50 MB)."}
        
        return {
            "status": "success",
            "message": f"Folder '{os.path.basename(expanded)}' berhasil di-compress menjadi '{safe_name}.zip' ({round(size_mb, 2)} MB) dan akan dikirim ke Telegram.",
            "file_path": result_path
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@register_tool(category="file")
def send_file_to_chat(file_path: str, caption: str = "") -> Dict[str, Any]:
    """
    Send an existing file (document, PDF, photo, video, audio, ZIP, code script, data file)
    from the computer filesystem directly to the Telegram user chat.
    Use this tool when the user asks to send, upload, or transfer a specific file from disk to Telegram.
    
    Args:
        file_path: Absolute or relative path to the local file (e.g. '~/Documents/invoice.pdf', '~/Downloads/video.mp4', '~/Downloads/archive.zip', 'bot.py').
        caption: Optional description or caption to accompany the file in chat.
    """
    try:
        import shutil
        expanded = os.path.expanduser(file_path)
        if not os.path.isabs(expanded):
            expanded = os.path.join(os.path.expanduser("~"), file_path)
            
        if not os.path.exists(expanded) or not os.path.isfile(expanded):
            return {"status": "error", "message": f"File tidak ditemukan di path: {file_path}"}
            
        file_size_mb = os.path.getsize(expanded) / (1024 * 1024)
        if file_size_mb > 50:
            return {"status": "error", "message": f"Ukuran file ({round(file_size_mb, 1)} MB) melebihi batas upload Telegram Bot API (50 MB)."}
            
        base_name = os.path.basename(expanded)
        dest_path = os.path.join(SANDBOX_DIR, base_name)
        shutil.copyfile(expanded, dest_path)
        
        return {
            "status": "success",
            "message": f"File '{base_name}' ({round(file_size_mb, 2)} MB) berhasil disiapkan dan akan otomatis terkirim ke Telegram.",
            "file_name": base_name,
            "caption": caption
        }
    except Exception as e:
        return {"status": "error", "message": f"Gagal memproses file: {str(e)}"}


@register_tool(category="file")
def git_operations(action: str, repo_path: str = ".", message: str = "", remote: str = "origin", branch: str = "") -> Dict[str, Any]:
    """
    Perform Git operations on a local repository directly from Telegram.
    
    Args:
        action: Git action to perform. Options:
                - 'status': Show git status (modified, staged, untracked files)
                - 'log': Show recent commit history
                - 'pull': Pull latest changes from remote
                - 'add_all': Stage all changes (git add .)
                - 'commit': Commit staged changes (requires message parameter)
                - 'push': Push commits to remote
                - 'diff': Show unstaged changes
                - 'branch': List branches
                - 'stash': Stash current changes
                - 'stash_pop': Pop stashed changes
        repo_path: Path to git repository (default: current directory).
        message: Commit message (required for 'commit' action).
        remote: Remote name (default: 'origin').
        branch: Branch name (optional).
    """
    try:
        expanded = os.path.expanduser(repo_path)
        
        cmd_map = {
            "status": "git status --porcelain -b",
            "log": "git log --oneline --graph -n 15",
            "pull": f"git pull {remote} {branch}".strip(),
            "add_all": "git add -A",
            "commit": f'git commit -m "{message}"' if message else 'echo "ERROR: commit message required"',
            "push": f"git push {remote} {branch}".strip(),
            "diff": "git diff --stat",
            "branch": "git branch -a",
            "stash": "git stash",
            "stash_pop": "git stash pop",
        }
        
        act = action.strip().lower()
        cmd = cmd_map.get(act)
        if not cmd:
            return {"status": "error", "message": f"Git action '{action}' tidak dikenal. Pilihan: {', '.join(cmd_map.keys())}"}
        
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=expanded, timeout=30)
        output = res.stdout.strip() or res.stderr.strip()
        
        return {
            "status": "success" if res.returncode == 0 else "error",
            "action": act,
            "output": output[:6000],
            "exit_code": res.returncode
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@register_tool(category="file")
def markitdown_convert_document(source_path_or_url: str, output_filename: str = "") -> Dict[str, Any]:
    """
    MARKITDOWN SUITE: Convert any document (Office Word/PowerPoint/Excel, PDF, HTML, CSV, JSON, Audio)
    or public URL into clean, structured LLM-ready Markdown text.
    
    Args:
        source_path_or_url: Local file path or web URL to convert to Markdown.
        output_filename: Optional filename to save the resulting .md in ~/Dokumen/ALFA_SWARM_OUTPUTS/.
    """
    try:
        from markitdown import MarkItDown
        md = MarkItDown()
        
        target = os.path.expanduser(source_path_or_url.strip())
        result = md.convert(target)
        markdown_content = result.text_content
        
        saved_path = None
        if output_filename:
            out_dir = os.path.expanduser("~/Dokumen/ALFA_SWARM_OUTPUTS")
            os.makedirs(out_dir, exist_ok=True)
            if not output_filename.endswith(".md"):
                output_filename += ".md"
            saved_path = os.path.join(out_dir, output_filename)
            with open(saved_path, "w", encoding="utf-8") as f:
                f.write(markdown_content)
                
        return {
            "status": "success",
            "source": source_path_or_url,
            "title": getattr(result, "title", None) or os.path.basename(source_path_or_url),
            "content_length": len(markdown_content),
            "markdown_snippet": markdown_content[:2000] if len(markdown_content) > 2000 else markdown_content,
            "is_truncated": len(markdown_content) > 2000,
            "saved_file": saved_path
        }
    except Exception as e:
        return {"status": "error", "message": f"MarkItDown conversion failed: {str(e)}"}


@register_tool(category="file")
def libreoffice_convert_document(source_file: str, output_format: str = "pdf") -> Dict[str, Any]:
    """
    LIBREOFFICE SUITE: Universal Document Converter.
    Converts any document between formats using LibreOffice Headless engine.
    Supported inputs: ODT, DOCX, DOC, RTF, TXT, HTML, EPUB, ODS, XLSX, XLS, CSV, ODP, PPTX, PPT, ODG, SVG, PDF.
    Supported outputs: pdf, docx, odt, xlsx, ods, pptx, odp, html, txt, csv, png.
    The converted document is automatically sent to Telegram as a file attachment.
    
    Args:
        source_file: Path to source document (e.g. '~/Documents/report.docx' or 'data.xlsx').
        output_format: Target format (e.g. 'pdf', 'docx', 'odt', 'xlsx', 'ods', 'html', 'txt').
    """
    try:
        expanded = os.path.expanduser(source_file)
        if not os.path.exists(expanded):
            return {"status": "error", "message": f"File sumber tidak ditemukan: {source_file}"}
            
        out_fmt = output_format.lower().replace(".", "").strip()
        base_name = os.path.splitext(os.path.basename(expanded))[0]
        
        # Run libreoffice conversion with output dir as SANDBOX_DIR
        cmd = ["libreoffice", "--headless", "--convert-to", out_fmt, expanded, "--outdir", SANDBOX_DIR]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        
        expected_file = os.path.join(SANDBOX_DIR, f"{base_name}.{out_fmt}")
        if os.path.exists(expected_file) and os.path.getsize(expected_file) > 0:
            size_kb = round(os.path.getsize(expected_file) / 1024, 1)
            return {
                "status": "success",
                "message": f"Dokumen berhasil dikonversi ke '{base_name}.{out_fmt}' ({size_kb} KB) via LibreOffice dan akan dikirim ke Telegram.",
                "file_path": expected_file,
                "output_format": out_fmt
            }
            
        # Check for matching files in sandbox if name changed
        matches = glob.glob(os.path.join(SANDBOX_DIR, f"*.{out_fmt}"))
        if matches:
            latest = max(matches, key=os.path.getmtime)
            size_kb = round(os.path.getsize(latest) / 1024, 1)
            return {
                "status": "success",
                "message": f"Dokumen berhasil dikonversi ke '{os.path.basename(latest)}' ({size_kb} KB) via LibreOffice dan akan dikirim ke Telegram.",
                "file_path": latest,
                "output_format": out_fmt
            }
            
        return {"status": "error", "message": f"Konversi LibreOffice gagal: {res.stderr or res.stdout}"}
    except Exception as e:
        return {"status": "error", "message": f"LibreOffice conversion error: {str(e)}"}


@register_tool(category="file")
def libreoffice_render_page_previews(document_path: str, max_pages: int = 3, dpi: int = 150) -> Dict[str, Any]:
    """
    LIBREOFFICE SUITE: Document High-Res Page Preview Renderer.
    Converts any office document (DOCX, ODT, XLSX, ODS, PPTX, ODP, PDF, RTF) into
    high-resolution PNG page images using LibreOffice Headless + pdftoppm, allowing visual
    inspection directly in Telegram as photos without opening the desktop app.
    
    Args:
        document_path: Path to the office document or PDF.
        max_pages: Number of pages to render as images (1-10, default: 3).
        dpi: Image resolution DPI (default: 150).
    """
    try:
        expanded = os.path.expanduser(document_path)
        if not os.path.exists(expanded):
            return {"status": "error", "message": f"File dokumen tidak ditemukan: {document_path}"}
            
        base_name = os.path.splitext(os.path.basename(expanded))[0]
        ext = os.path.splitext(expanded)[1].lower()
        
        # Step 1: Ensure we have a PDF version
        if ext == ".pdf":
            pdf_path = expanded
            temp_pdf = None
        else:
            # Convert document to PDF first
            cmd_pdf = ["libreoffice", "--headless", "--convert-to", "pdf", expanded, "--outdir", "/tmp"]
            subprocess.run(cmd_pdf, capture_output=True, text=True, timeout=45)
            temp_pdf = os.path.join("/tmp", f"{base_name}.pdf")
            if not os.path.exists(temp_pdf):
                return {"status": "error", "message": "Gagal mengonversi dokumen ke PDF untuk rendering preview."}
            pdf_path = temp_pdf
            
        # Step 2: Render PDF pages to PNG via pdftoppm into SANDBOX_DIR
        out_prefix = os.path.join(SANDBOX_DIR, f"preview_{base_name}")
        pages_to_render = min(max(1, max_pages), 10)
        cmd_ppm = ["pdftoppm", "-png", "-r", str(dpi), "-f", "1", "-l", str(pages_to_render), pdf_path, out_prefix]
        res_ppm = subprocess.run(cmd_ppm, capture_output=True, text=True, timeout=30)
        
        # Clean up temp pdf if created
        if temp_pdf and os.path.exists(temp_pdf):
            try:
                os.remove(temp_pdf)
            except OSError:
                pass
                
        rendered_images = sorted(glob.glob(f"{out_prefix}-*.png"))
        if rendered_images:
            return {
                "status": "success",
                "message": f"Berhasil me-render {len(rendered_images)} halaman preview untuk '{os.path.basename(expanded)}'. Gambar akan langsung dikirim ke Telegram!",
                "rendered_pages": len(rendered_images),
                "images": [os.path.basename(img) for img in rendered_images]
            }
        return {"status": "error", "message": f"Gagal merender halaman: {res_ppm.stderr}"}
    except Exception as e:
        return {"status": "error", "message": f"LibreOffice render preview error: {str(e)}"}


@register_tool(category="file")
def libreoffice_create_document(doc_type: str, title: str, content_html_or_text: str, filename: str = "", export_format: str = "odt") -> Dict[str, Any]:
    """
    LIBREOFFICE SUITE: Create Professional Office Documents (Writer, Calc, Impress).
    Generates rich formatted LibreOffice documents (.odt, .ods, .odp) or Microsoft Office (.docx, .xlsx, .pptx)
    with headings, tables, styled sections, and exports directly to Telegram.
    
    Args:
        doc_type: 'writer' (Text document), 'calc' (Spreadsheet), 'impress' (Presentation).
        title: Title of the document.
        content_html_or_text: Rich HTML or text content (with <h1>, <h2>, <p>, <table>, <ul>, <b>, <i>).
        filename: Optional output filename (e.g. 'laporan_resmi.odt' or 'data_keuangan.xlsx').
        export_format: Target format ('odt', 'docx', 'pdf', 'ods', 'xlsx', 'odp', 'pptx').
    """
    try:
        dtype = doc_type.lower().strip()
        exp_fmt = export_format.lower().replace(".", "").strip()
        
        if not filename:
            clean_title = re.sub(r'[^a-zA-Z0-9_-]', '_', title.lower())[:30]
            filename = f"{clean_title}.{exp_fmt}"
        elif not filename.endswith(f".{exp_fmt}"):
            filename = f"{os.path.splitext(filename)[0]}.{exp_fmt}"
            
        dest_path = os.path.join(SANDBOX_DIR, filename)
        
        # Build clean styled HTML template
        html_doc = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
body {{ font-family: 'Liberation Sans', 'Segoe UI', Arial, sans-serif; margin: 40px; color: #1E293B; line-height: 1.6; }}
h1 {{ color: #1E3A8A; border-bottom: 2px solid #3B82F6; padding-bottom: 8px; font-size: 24pt; }}
h2 {{ color: #1E40AF; margin-top: 24px; font-size: 16pt; }}
h3 {{ color: #2563EB; font-size: 13pt; }}
p {{ font-size: 11pt; margin-bottom: 12px; }}
table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
th {{ background-color: #2563EB; color: white; padding: 10px; border: 1px solid #CBD5E1; text-align: left; }}
td {{ padding: 8px 10px; border: 1px solid #CBD5E1; }}
tr:nth-child(even) {{ background-color: #F8FAFC; }}
ul, ol {{ padding-left: 25px; }}
li {{ margin-bottom: 6px; }}
.footer {{ margin-top: 40px; font-size: 9pt; color: #64748B; border-top: 1px solid #E2E8F0; padding-top: 8px; }}
</style>
</head>
<body>
<h1>{title}</h1>
{content_html_or_text}
<div class="footer">Dibuat secara otomatis oleh Sovereign Telegram AI Agent via LibreOffice Engine | {datetime.datetime.now().strftime("%d %B %Y %H:%M")}</div>
</body>
</html>"""

        temp_html = os.path.join("/tmp", f"temp_lo_{os.getpid()}.html")
        with open(temp_html, "w", encoding="utf-8") as f:
            f.write(html_doc)
            
        # Convert via LibreOffice to target format
        cmd = ["libreoffice", "--headless", "--convert-to", exp_fmt, temp_html, "--outdir", SANDBOX_DIR]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=45)
        
        if os.path.exists(temp_html):
            try:
                os.remove(temp_html)
            except OSError:
                pass
                
        expected_out = os.path.join(SANDBOX_DIR, f"temp_lo_{os.getpid()}.{exp_fmt}")
        if os.path.exists(expected_out):
            os.rename(expected_out, dest_path)
            
        if os.path.exists(dest_path) and os.path.getsize(dest_path) > 0:
            size_kb = round(os.path.getsize(dest_path) / 1024, 1)
            return {
                "status": "success",
                "message": f"Dokumen LibreOffice '{filename}' ({size_kb} KB) berhasil dibuat dan akan dikirim ke Telegram.",
                "file_path": dest_path,
                "doc_type": dtype,
                "format": exp_fmt
            }
            
        return {"status": "error", "message": f"Gagal membuat dokumen LibreOffice: {res.stderr or res.stdout}"}
    except Exception as e:
        return {"status": "error", "message": f"Create LibreOffice document error: {str(e)}"}


@register_tool(category="file")
def libreoffice_extract_document_text(document_path: str) -> Dict[str, Any]:
    """
    LIBREOFFICE SUITE: Extract Text & Structure from Any Document.
    Extracts complete clean text from complex binary files (ODT, DOCX, DOC, RTF, ODS, ODP, EPUB, PDF)
    using LibreOffice Headless text filter.
    
    Args:
        document_path: Path to the document file.
    """
    try:
        expanded = os.path.expanduser(document_path)
        if not os.path.exists(expanded):
            return {"status": "error", "message": f"File tidak ditemukan: {document_path}"}
        
        temp_dir = f"/tmp/lo_txt_{os.getpid()}"
        os.makedirs(temp_dir, exist_ok=True)
        
        cmd = ["libreoffice", "--headless", "--convert-to", "txt:Text", expanded, "--outdir", temp_dir]
        subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        
        txt_files = glob.glob(os.path.join(temp_dir, "*.txt"))
        if txt_files:
            with open(txt_files[0], "r", encoding="utf-8", errors="replace") as f:
                extracted_text = f.read().strip()
                
            # Cleanup temp dir
            import shutil
            shutil.rmtree(temp_dir, ignore_errors=True)
            
            return {
                "status": "success",
                "document": os.path.basename(expanded),
                "character_count": len(extracted_text),
                "word_count": len(extracted_text.split()),
                "text_content": extracted_text[:8000]
            }
            
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)
        return {"status": "error", "message": "Tidak dapat mengekstrak teks dari dokumen via LibreOffice."}
    except Exception as e:
        return {"status": "error", "message": f"LibreOffice extract text error: {str(e)}"}


@register_tool(category="file")
def vault_store_secret(name: str, value: str, category: str = "api_key", notes: str = "") -> Dict[str, Any]:
    """
    Encrypt and store a sensitive credential, API key, affiliate token, or secret note
    into αlfa Secure Vault with AES-256-GCM authenticated encryption.
    
    Args:
        name: Unique identifier name for the secret (e.g. 'KLING_AI_KEY', 'SHOPEE_COOKIE', 'DB_PASSWORD').
        value: Secret text/token/key to encrypt and store securely.
        category: Category of secret ('api_key', 'affiliate', 'password', 'note').
        notes: Optional description or context about the secret.
    """
    try:
        import vault_engine
        res = vault_engine.vault.store_secret(name=name, value=value, category=category, notes=notes)
        return res
    except Exception as e:
        return {"status": "error", "message": f"Vault store error: {str(e)}"}


@register_tool(category="file")
def vault_get_secret(name_or_id: str) -> Dict[str, Any]:
    """
    Retrieve and decrypt a sensitive secret from αlfa Secure Vault using AES-256-GCM.
    
    Args:
        name_or_id: The unique name or ID of the secret to decrypt.
    """
    try:
        import vault_engine
        sec = vault_engine.vault.get_secret(name_or_id)
        if not sec:
            return {"status": "error", "message": f"Secret '{name_or_id}' tidak ditemukan di dalam vault."}
        return {
            "status": "success",
            "name": sec["name"],
            "category": sec["category"],
            "value": sec["value"],
            "notes": sec["notes"],
            "updated_at": sec["updated_at"]
        }
    except Exception as e:
        return {"status": "error", "message": f"Vault retrieval error: {str(e)}"}


@register_tool(category="file")
def vault_list_secrets(category: str = "all") -> Dict[str, Any]:
    """
    List all stored secrets metadata in αlfa Secure Vault without exposing decrypted plaintext.
    
    Args:
        category: Filter by category ('all', 'api_key', 'affiliate', 'password', 'note').
    """
    try:
        import vault_engine
        items = vault_engine.vault.list_secrets(category=category)
        return {
            "status": "success",
            "total_secrets": len(items),
            "encryption": "AES-256-GCM (Authenticated)",
            "secrets": items
        }
    except Exception as e:
        return {"status": "error", "message": f"Vault list error: {str(e)}"}


@register_tool(category="file")
def vault_delete_secret(secret_id: int) -> Dict[str, Any]:
    """
    Permanently delete a secret from αlfa Secure Vault by ID.
    
    Args:
        secret_id: Numeric ID of the secret to delete.
    """
    try:
        import vault_engine
        deleted = vault_engine.vault.delete_secret(int(secret_id))
        if deleted:
            return {"status": "success", "message": f"Secret ID {secret_id} berhasil dihapus permanen dari vault."}
        return {"status": "error", "message": f"Secret ID {secret_id} tidak ditemukan."}
    except Exception as e:
        return {"status": "error", "message": f"Vault delete error: {str(e)}"}

