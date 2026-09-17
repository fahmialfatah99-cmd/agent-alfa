# -*- coding: utf-8 -*-
"""
Workspace hygiene, sandboxing project snapshotting, and output harvesting for ALFA Swarm.
"""

import collections
import fnmatch
import itertools
import json
import logging
import os
import re
import shutil
import sys
import time
from typing import Any, Dict, List, Optional, Set

from alfa import tools

logger = logging.getLogger(__name__)

SWARM_OUTPUT_DIR = os.path.expanduser("~/Dokumen/ALFA_SWARM_OUTPUTS")
MAX_SWARM_AGENTS = max(1, int(os.getenv("ALFA_SWARM_MAX_AGENTS", "15")))
MAX_QA_ROUNDS = max(0, int(os.getenv("ALFA_SWARM_QA_ROUNDS", "3")))
os.makedirs(SWARM_OUTPUT_DIR, exist_ok=True)

_HARVEST_EXCLUDE = {
    # Dependency & build clutter
    "node_modules",
    ".next",
    ".nuxt",
    ".turbo",
    ".parcel-cache",
    ".svelte-kit",
    ".venv",
    "venv",
    "env",
    ".toolchain",
    # Python & test caches
    "__pycache__",
    ".cache",
    ".local",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    # Version control
    ".git",
    # Docker bind-mount leak artifacts (never belong inside project outputs)
    "alfa_projects",
    "ALFA_WORKSPACE",
    "ALFA_SWARM_OUTPUTS",
    "output",
}

_JUNK_FILE_PATTERNS = {
    "*.pyc",
    "*.pyo",
    "*.pyd",
    ".DS_Store",
    "Thumbs.db",
    "desktop.ini",
    "ehthumbs.db",
    "*.tmp",
    "*.temp",
    "*~",
    "*.swp",
    "*.swo",
    "*.bak",
    "*.orig",
    "npm-debug.log*",
    "yarn-debug.log*",
    "yarn-error.log*",
    "pnpm-debug.log*",
    "server.log",
    "fallback.log",
    "audit_test.py",
    "test_fallback.py",
    "secret.key",
    "*.log",
}

_SANDBOX_SNAPSHOT: Set[str] = set()
_TARGET_FOLDER: str = ""
_EXEC_FS_SNAPSHOT: Dict[str, str] = {}

LIVE_FEED_FILE = os.path.join(SWARM_OUTPUT_DIR, "live_meeting_feed.jsonl")
CANCEL_FLAG_FILE = os.path.join(SWARM_OUTPUT_DIR, "swarm_cancel.flag")
LIVE_LOG: collections.deque = collections.deque(maxlen=400)
MEETING_RUNNING = False


def _get_swarm_output_dir() -> str:
    for mod_name in ("swarm_engine", "alfa.swarm.engine"):
        mod = sys.modules.get(mod_name)
        if mod and hasattr(mod, "SWARM_OUTPUT_DIR"):
            return getattr(mod, "SWARM_OUTPUT_DIR")
    return SWARM_OUTPUT_DIR


def _get_target_folder() -> str:
    for mod_name in ("swarm_engine", "alfa.swarm.engine"):
        mod = sys.modules.get(mod_name)
        if mod and hasattr(mod, "_TARGET_FOLDER"):
            return getattr(mod, "_TARGET_FOLDER")
    return _TARGET_FOLDER


def _get_sandbox_snapshot() -> Set[str]:
    for mod_name in ("swarm_engine", "alfa.swarm.engine"):
        mod = sys.modules.get(mod_name)
        if mod and hasattr(mod, "_SANDBOX_SNAPSHOT"):
            return getattr(mod, "_SANDBOX_SNAPSHOT")
    return _SANDBOX_SNAPSHOT


def sanitize_project_directory(dir_path: str) -> Dict[str, int]:
    """
    Membersihkan file sampah, folder dependensi/clutter (node_modules, .cache, dll),
    dan memangkas habis seluruh folder kosong dari proyek/website secara menyeluruh.
    """
    if not dir_path or not os.path.isdir(dir_path):
        return {"deleted_files": 0, "pruned_dirs": 0}

    deleted_files = 0
    pruned_dirs = 0

    # 1. Hapus direktori sampah / clutter / bocoran docker
    for root, dirs, _ in os.walk(dir_path, topdown=False):
        for d in list(dirs):
            dp = os.path.join(root, d)
            if d in _HARVEST_EXCLUDE or d.startswith(".tmp_") or d == "__MACOSX":
                try:
                    shutil.rmtree(dp, ignore_errors=True)
                    pruned_dirs += 1
                except Exception:
                    pass

    # 2. Hapus file sampah (patterns & debug logs)
    for root, _, files in os.walk(dir_path, topdown=False):
        for f in files:
            fp = os.path.join(root, f)
            low_f = f.lower()
            is_junk = any(
                fnmatch.fnmatch(low_f, pat.lower()) for pat in _JUNK_FILE_PATTERNS
            )
            if is_junk:
                try:
                    os.remove(fp)
                    deleted_files += 1
                except OSError:
                    pass

    # 3. Pangkas habis seluruh folder kosong secara rekursif (bottom-up)
    for root, dirs, _ in os.walk(dir_path, topdown=False):
        if os.path.abspath(root) == os.path.abspath(dir_path):
            continue
        try:
            if not os.listdir(root):
                os.rmdir(root)
                pruned_dirs += 1
        except OSError:
            pass

    return {"deleted_files": deleted_files, "pruned_dirs": pruned_dirs}


def _hash_sandbox_projects() -> Dict[str, str]:
    out: Dict[str, str] = {}
    target = _get_target_folder()
    try:
        if target and os.path.isdir(target):
            roots = [target]
        else:
            sb = tools.SANDBOX_DIR
            roots = [
                os.path.join(sb, d)
                for d in os.listdir(sb)
                if os.path.isdir(os.path.join(sb, d))
                and not d.startswith(".")
                and d not in _HARVEST_EXCLUDE
            ]
        for pdir in roots:
            for root, dirs, files in os.walk(pdir):
                dirs[:] = [x for x in dirs if x not in _HARVEST_EXCLUDE]
                for f in files:
                    fp = os.path.join(root, f)
                    try:
                        st = os.stat(fp)
                        out[fp] = f"{st.st_size}:{st.st_mtime_ns}"
                    except OSError:
                        pass
    except Exception:
        pass
    return out


def _fs_changed_since_snapshot() -> bool:
    if not _EXEC_FS_SNAPSHOT:
        return True
    return _hash_sandbox_projects() != _EXEC_FS_SNAPSHOT


def _sandbox_project_dirs() -> set:
    try:
        sb = tools.SANDBOX_DIR
        return {
            d
            for d in os.listdir(sb)
            if os.path.isdir(os.path.join(sb, d))
            and not d.startswith(".")
            and d not in _HARVEST_EXCLUDE
        }
    except Exception:
        return set()


def _harvest_new_sandbox_projects(topic: str = "") -> List[str]:
    """Arsipkan folder proyek baru di sandbox tanpa file sampah & folder kosong."""
    from alfa.swarm.live_logger import log_live

    harvested: List[str] = []
    output_dir = _get_swarm_output_dir()
    target_folder = _get_target_folder()
    snapshot = _get_sandbox_snapshot()

    try:
        new_dirs = _sandbox_project_dirs() - snapshot
        # Folder target jika di dalam sandbox ikut di-harvest
        if target_folder and os.path.isdir(target_folder):
            real_tf = os.path.realpath(target_folder)
            real_sb = os.path.realpath(tools.SANDBOX_DIR)
            if real_tf.startswith(real_sb):
                new_dirs.add(os.path.basename(target_folder.rstrip("/")))
            else:
                sanitize_project_directory(target_folder)
                harvested.append(target_folder)

        # Buang folder internal/clutter dari daftar proyek
        new_dirs = {
            d for d in new_dirs if d not in _HARVEST_EXCLUDE and not d.startswith(".")
        }
        if not new_dirs:
            return harvested

        low_topic = (topic or "").lower()
        is_website_topic = any(
            k in low_topic
            for k in (
                "website",
                "web ",
                "web-",
                "landing",
                "html",
                "portofolio",
                "frontend",
                "front-end",
                "tampilan",
                "ui/ux",
                "dashboard",
            )
        )

        slug = re.sub(r"[^a-z0-9]+", "_", low_topic[:30]).strip("_") or "proyek"
        ts = int(time.time())

        for d in sorted(new_dirs):
            src = os.path.join(tools.SANDBOX_DIR, d)
            if not os.path.isdir(src):
                continue

            sanitize_project_directory(src)

            total = sum(
                os.path.getsize(os.path.join(root, f))
                for root, _, files in os.walk(src)
                for f in files
            )
            file_count = sum(len(files) for _, _, files in os.walk(src))

            if total > 400 * 1024 * 1024:
                log_live("HARVEST", f"⏭️ '{d}' dilewati (melebihi 400MB)")
                continue
            if file_count == 0 or total == 0:
                log_live("HARVEST", f"⏭️ '{d}' dilewati (folder kosong/tanpa karya)")
                continue

            is_web = (
                is_website_topic
                or os.path.exists(os.path.join(src, "index.html"))
                or any(
                    f.endswith((".html", ".htm"))
                    for _, _, files in os.walk(src)
                    for f in files
                )
            )
            cat = "websites" if is_web else "projects"
            cat_parent = os.path.join(output_dir, cat)
            os.makedirs(cat_parent, exist_ok=True)

            target_slug = (
                slug
                if slug != "proyek"
                else re.sub(r"[^a-z0-9]+", "_", d.lower())[:30].strip("_")
            )
            dst_dir = os.path.join(cat_parent, f"{target_slug}_{ts}")
            if os.path.exists(dst_dir):
                dst_dir = os.path.join(cat_parent, f"{target_slug}_{d}_{ts}")

            shutil.copytree(
                src,
                dst_dir,
                ignore=shutil.ignore_patterns(*_HARVEST_EXCLUDE),
                dirs_exist_ok=True,
            )

            sanitize_project_directory(dst_dir)

            harvested.append(dst_dir)
            log_live(
                "HARVEST",
                f"📦 {cat.capitalize()} '{os.path.basename(dst_dir)}' ({max(1, total // 1024)}KB) rapi tanpa sampah diarsipkan ke {dst_dir}",
            )
        return harvested
    except Exception as e:
        log_live("HARVEST", f"⚠️ harvest gagal: {e}")
        return harvested
    finally:
        snapshot.clear()
        snapshot.update(_sandbox_project_dirs())


def request_cancel_swarm() -> bool:
    """Minta pembatalan eksekusi swarm yang sedang berjalan.
    Return True bila memang ada sesi aktif untuk dibatalkan."""
    from alfa.swarm.live_logger import log_live

    if not MEETING_RUNNING:
        return False
    try:
        output_dir = _get_swarm_output_dir()
        flag_file = os.path.join(output_dir, "swarm_cancel.flag")
        os.makedirs(output_dir, exist_ok=True)
        with open(flag_file, "w", encoding="utf-8") as f:
            f.write(str(time.time()))
    except OSError:
        pass
    log_live(
        "CANCEL",
        "⏹ Permintaan pembatalan diterima — menghentikan setelah langkah berjalan selesai...",
    )
    return True


def _cancel_requested() -> bool:
    output_dir = _get_swarm_output_dir()
    flag_file = os.path.join(output_dir, "swarm_cancel.flag")
    return os.path.exists(flag_file) or os.path.exists(CANCEL_FLAG_FILE)


def _clear_cancel_flag() -> None:
    output_dir = _get_swarm_output_dir()
    for ff in (os.path.join(output_dir, "swarm_cancel.flag"), CANCEL_FLAG_FILE):
        try:
            if os.path.exists(ff):
                os.remove(ff)
        except OSError:
            pass
