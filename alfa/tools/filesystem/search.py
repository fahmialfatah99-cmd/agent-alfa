"""Workspace searching, file grepping, user file finder, compression, and git tools."""

import datetime
import glob
import logging
import os
import shutil
import subprocess
from typing import Any, Dict, List

from alfa.tools.filesystem.core_file import _MAX_EDIT_FILE_BYTES
from alfa.tools.registry import register_tool
from alfa.tools.system_tools import SANDBOX_DIR, normalize_path

logger = logging.getLogger("AgentTools.Filesystem.Search")

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


@register_tool(category="file")
def search_workspace_files(
    pattern: str, base_dir: str = "~", max_results: int = 30
) -> Dict[str, Any]:
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
            dirs[:] = [
                d
                for d in dirs
                if not d.startswith(".")
                and d not in ("node_modules", "venv", "__pycache__", "dist", "build")
            ]
            for name in files:
                if (
                    glob.fnmatch.fnmatch(name, pattern)
                    or pattern.lower() in name.lower()
                ):
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
            "files": matches,
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@register_tool(category="file")
def grep_workspace(
    query: str, base_dir: str = "~", file_pattern: str = ""
) -> Dict[str, Any]:
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
                                ok = (
                                    rx.search(ln)
                                    if use_regex
                                    else (query.lower() in ln.lower())
                                )
                                if ok:
                                    matches.append(f"{fpath}:{i}:{ln.strip()[:200]}")
                                    if len(matches) >= 30:
                                        raise StopIteration
                    except StopIteration:
                        raise
                    except OSError:
                        continue
            return {
                "status": "success",
                "matches_count": len(matches),
                "results": matches[:30],
            }
        cmd = ["grep", "-rnI", "--exclude-dir={.git,venv,node_modules,__pycache__}"]
        if file_pattern:
            cmd.append(f"--include={file_pattern}")
        cmd.extend([query, root_dir])

        res = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        lines = res.stdout.strip().split("\n") if res.stdout.strip() else []

        return {"status": "success", "matches_count": len(lines), "results": lines[:30]}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@register_tool(category="file")
def find_user_files(
    pattern: str = "", file_types: str = "all", folder: str = ""
) -> Dict[str, Any]:
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
        roots = [
            os.path.join(home, f)
            for f in ("Downloads", "Documents", "Desktop", "Pictures")
        ]
        if folder:
            roots = [os.path.join(r, folder) for r in roots]

        ext_map = {
            "image": {
                ".jpg",
                ".jpeg",
                ".png",
                ".webp",
                ".avif",
                ".gif",
                ".bmp",
                ".svg",
                ".heic",
            },
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

        skip_dirs = {
            "node_modules",
            ".git",
            "venv",
            "__pycache__",
            "AppData",
            "_backup-pre-audit",
            "_evidence",
        }
        results = []
        pat = pattern.strip().lower()
        for root in roots:
            if not os.path.isdir(root):
                continue
            for dirpath, dirnames, filenames in os.walk(root):
                dirnames[:] = [
                    d for d in dirnames if d not in skip_dirs and not d.startswith(".")
                ]
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
                        results.append(
                            {
                                "path": fp,
                                "name": fn,
                                "size_mb": round(st.st_size / 1024 / 1024, 2),
                                "modified": _dtmod.fromtimestamp(st.st_mtime).strftime(
                                    "%Y-%m-%d %H:%M"
                                ),
                            }
                        )
                    except OSError:
                        continue
        # terbaru dulu, batasi 25
        results.sort(key=lambda x: x["modified"], reverse=True)
        return {
            "status": "success",
            "total": len(results),
            "files": results[:25],
            "message": (
                (
                    f"Ditemukan {len(results)} file. GUNAKAN path asli ini — "
                    "DILARANG membuat gambar/file dummy pengganti."
                )
                if results
                else "Tidak ditemukan. Konfirmasi ke pengguna bila perlu."
            ),
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@register_tool(category="file")
def compress_folder_to_zip(
    folder_path: str, output_filename: str = "archive.zip"
) -> Dict[str, Any]:
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
            return {
                "status": "error",
                "message": f"Folder tidak ditemukan: {folder_path}",
            }

        safe_name = output_filename.replace(".zip", "")
        zip_base = os.path.join(SANDBOX_DIR, safe_name)
        result_path = shutil.make_archive(zip_base, "zip", expanded)

        size_mb = os.path.getsize(result_path) / (1024 * 1024)
        if size_mb > 50:
            os.remove(result_path)
            return {
                "status": "error",
                "message": f"Ukuran ZIP ({round(size_mb, 1)} MB) melebihi batas Telegram (50 MB).",
            }

        return {
            "status": "success",
            "message": f"Folder '{os.path.basename(expanded)}' berhasil di-compress menjadi '{safe_name}.zip' ({round(size_mb, 2)} MB) dan akan dikirim ke Telegram.",
            "file_path": result_path,
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
            return {
                "status": "error",
                "message": f"File tidak ditemukan di path: {file_path}",
            }

        file_size_mb = os.path.getsize(expanded) / (1024 * 1024)
        if file_size_mb > 50:
            return {
                "status": "error",
                "message": f"Ukuran file ({round(file_size_mb, 1)} MB) melebihi batas upload Telegram Bot API (50 MB).",
            }

        base_name = os.path.basename(expanded)
        dest_path = os.path.join(SANDBOX_DIR, base_name)
        shutil.copyfile(expanded, dest_path)

        return {
            "status": "success",
            "message": f"File '{base_name}' ({round(file_size_mb, 2)} MB) berhasil disiapkan dan akan otomatis terkirim ke Telegram.",
            "file_name": base_name,
            "caption": caption,
        }
    except Exception as e:
        return {"status": "error", "message": f"Gagal memproses file: {str(e)}"}


@register_tool(category="file")
def git_operations(
    action: str,
    repo_path: str = ".",
    message: str = "",
    remote: str = "origin",
    branch: str = "",
) -> Dict[str, Any]:
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
            "commit": (
                f'git commit -m "{message}"'
                if message
                else 'echo "ERROR: commit message required"'
            ),
            "push": f"git push {remote} {branch}".strip(),
            "diff": "git diff --stat",
            "branch": "git branch -a",
            "stash": "git stash",
            "stash_pop": "git stash pop",
        }

        act = action.strip().lower()
        cmd = cmd_map.get(act)
        if not cmd:
            return {
                "status": "error",
                "message": f"Git action '{action}' tidak dikenal. Pilihan: {', '.join(cmd_map.keys())}",
            }

        res = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, cwd=expanded, timeout=30
        )
        output = res.stdout.strip() or res.stderr.strip()

        return {
            "status": "success" if res.returncode == 0 else "error",
            "action": act,
            "output": output[:6000],
            "exit_code": res.returncode,
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}
