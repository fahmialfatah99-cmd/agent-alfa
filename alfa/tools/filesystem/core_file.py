"""Core file operations: read, write, edit, unified diff, and python syntax guard."""

import difflib
import logging
import os
import re
from typing import Any, Dict, Optional

from alfa.tools.registry import register_tool
from alfa.tools.system_tools import normalize_path

logger = logging.getLogger("AgentTools.Filesystem.CoreFile")

_MAX_EDIT_FILE_BYTES = 2 * 1024 * 1024


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
        return (
            f"Edit DIBATALKAN (auto-rollback): hasil menyebabkan SyntaxError "
            f"di baris {syn.lineno}: {syn.msg}. Isi file dikembalikan seperti semula."
        )


def _resolve_host_path(file_path: str) -> str:
    file_path = normalize_path(file_path)
    expanded = os.path.expanduser(file_path)
    if not os.path.isabs(expanded):
        expanded = os.path.join(os.path.expanduser("~"), file_path)
    return os.path.realpath(expanded)


@register_tool(category="file")
def read_local_file(
    file_path: str, max_lines: int = 300, start_line: int = 1
) -> Dict[str, Any]:
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
            return {
                "status": "error",
                "message": f"File tidak ditemukan: {file_path}",
                "self_heal_hint": hint,
            }

        if os.path.isdir(expanded_path):
            files = os.listdir(expanded_path)
            return {"status": "is_directory", "files": files[:50], "total": len(files)}

        with open(expanded_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()

        total_lines = len(lines)
        start_idx = max(0, start_line - 1)
        end_idx = min(total_lines, start_idx + max_lines)
        selected_lines = lines[start_idx:end_idx]

        numbered_content = "".join(
            [f"{i+1}: {line}" for i, line in enumerate(selected_lines, start=start_idx)]
        )

        return {
            "status": "success",
            "file_path": expanded_path,
            "total_lines": total_lines,
            "showing_lines": f"{start_idx+1} to {end_idx}",
            "content": numbered_content,
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

        return {
            "status": "success",
            "message": f"File berhasil disimpan di {expanded_path} ({len(content)} karakter)",
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@register_tool(category="file")
def edit_file_precise(
    file_path: str, old_text: str, new_text: str, occurrence: int = 0
) -> Dict[str, Any]:
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
            return {
                "status": "error",
                "message": f"File terlalu besar (>2MB): {file_path}",
            }
        if not old_text:
            return {
                "status": "error",
                "message": "old_text kosong — gunakan write_local_file untuk membuat isi baru.",
            }

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
                cand = "\n".join(lines[i : i + window])
                score = difflib.SequenceMatcher(
                    None, norm_old, "\n".join(ln.rstrip() for ln in cand.splitlines())
                ).ratio()
                if score > best_score:
                    best, best_score = (i + 1, cand), score
            hint = ""
            if best and best_score > 0.6:
                hint = (
                    f" Kemungkinan yang dimaksud di sekitar baris {best[0]} "
                    f"(kemiripan {best_score:.0%}). Salin teks persis dari file."
                )
            return {
                "status": "error",
                "message": f"old_text tidak ditemukan di {file_path}.{hint}",
            }

        if occurrence == 0 and count > 1:
            return {
                "status": "error",
                "message": (
                    f"old_text cocok di {count} lokasi berbeda. "
                    "Tambahkan konteks lebih banyak agar unik, atau sebutkan "
                    "`occurrence` (1=ke-N, -1=terakhir). Tidak ada perubahan ditulis."
                ),
            }

        # Resolusi indeks kecocokan: -1=terakhir, 0/unik=pertama, N=ke-N
        idx = count + 1 + occurrence if occurrence < 0 else max(1, occurrence)
        if not (1 <= idx <= count):
            return {
                "status": "error",
                "message": f"occurrence={occurrence} di luar rentang; ditemukan {count} kecocokan.",
            }

        start = 0
        for _ in range(idx):
            pos = content.find(old_text, start)
            start = pos + 1
        new_content = content[:pos] + new_text + content[pos + len(old_text) :]

        with open(p, "w", encoding="utf-8", errors="surrogateescape") as f:
            f.write(new_content)

        syn_err = _py_syntax_guard(p, content)
        if syn_err:
            return {"status": "error", "message": syn_err}

        return {
            "status": "success",
            "message": (
                f"Berhasil mengganti {len(old_text)} -> {len(new_text)} karakter "
                f"di {file_path} (kecocokan #{idx}/{count})."
            ),
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
            return {
                "status": "error",
                "message": f"File terlalu besar (>2MB): {file_path}",
            }

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
            return {
                "status": "error",
                "message": "Tidak ada hunk @@ valid dalam diff. Pastikan format unified diff.",
            }

        lines = list(orig_lines)
        applied = 0
        cursor = 0
        for hno, h in enumerate(hunks, 1):
            anchor = next((ln for ln in h["old"] if ln.strip()), "")
            n_old = len(h["old"])
            candidates = []
            if anchor:
                for i in range(
                    cursor, min(len(lines), max(len(lines), h["new_start"] + 80))
                ):
                    if lines[i] == anchor:
                        candidates.append(i - h["old"].index(anchor))
                        if len(candidates) >= 3:
                            break
            chosen = None
            for base in candidates + [h["new_start"] - 1]:
                if base is None or base < 0:
                    continue
                seg = lines[base : base + n_old]
                if [x.strip() for x in seg] == [
                    x.strip() for x in h["old"]
                ] or seg == h["old"]:
                    chosen = base
                    break
            if chosen is None:
                return {
                    "status": "error",
                    "message": (
                        f"Hunk #{hno} gagal diterapkan (konteks tidak cocok "
                        f"di sekitar '{anchor[:60]}'). Tidak ada perubahan ditulis. "
                        "Baca ulang file & buat diff baru."
                    ),
                    "hunks_applied_before_fail": applied,
                }

            lines[chosen : chosen + n_old] = h["new"]
            cursor = chosen + len(h["new"])
            applied += 1

        with open(p, "w", encoding="utf-8", errors="surrogateescape") as f:
            f.write("\n".join(lines))

        syn_err = _py_syntax_guard(p, "\n".join(orig_lines))
        if syn_err:
            return {"status": "error", "message": syn_err}

        return {
            "status": "success",
            "message": f"{applied}/{len(hunks)} hunk berhasil diterapkan ke {file_path}.",
            "hunks_applied": applied,
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}
