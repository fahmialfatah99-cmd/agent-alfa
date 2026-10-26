"""Auto-Backup & Verified Snapshot Manager for ALFA OS SQLite Database & Memory."""

from __future__ import annotations

import glob
import hashlib
import json
import logging
import os
import shutil
import sqlite3
import tarfile
import tempfile
import time
from datetime import datetime
from typing import Any

from alfa.core.db import connection as _db_conn

logger = logging.getLogger(__name__)

DEFAULT_BACKUP_DIR = os.path.expanduser("~/.alfa/backups")


def _resolve_db_path(db_path: str | None = None) -> str:
    if db_path and str(db_path).strip():
        return os.path.abspath(os.path.expanduser(str(db_path).strip()))
    env_db = os.getenv("ALFA_DB_PATH", "").strip()
    if env_db:
        return os.path.abspath(os.path.expanduser(env_db))
    return os.path.abspath(_db_conn.DB_PATH)


def _resolve_backup_dir(backup_dir: str | None = None) -> str:
    if backup_dir and str(backup_dir).strip():
        target = os.path.abspath(os.path.expanduser(str(backup_dir).strip()))
    else:
        target = os.path.abspath(
            os.path.expanduser(os.getenv("ALFA_BACKUP_DIR", DEFAULT_BACKUP_DIR))
        )
    os.makedirs(target, exist_ok=True)
    return target


def verify_sqlite_integrity(db_path: str | None = None) -> dict[str, Any]:
    """Run SQLite PRAGMA quick_check and table row counts to verify database health."""
    resolved = _resolve_db_path(db_path)
    if not os.path.exists(resolved):
        return {
            "status": "error",
            "healthy": False,
            "db_path": resolved,
            "message": "File database tidak ditemukan.",
        }
    try:
        conn = sqlite3.connect(f"file:{resolved}?mode=ro", uri=True, timeout=10.0)
        try:
            chk = conn.execute("PRAGMA quick_check").fetchall()
            messages = [str(r[0]) for r in chk if r]
            healthy = len(messages) == 1 and messages[0].lower() == "ok"
            counts: dict[str, int] = {}
            for tbl in (
                "user_memory",
                "chat_history",
                "custom_agents",
                "api_keys",
                "alfa_graph_entities",
                "alfa_graph_relations",
            ):
                try:
                    row = conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()  # nosec B608
                    counts[tbl] = int(row[0]) if row else 0
                except sqlite3.Error:
                    counts[tbl] = 0
            return {
                "status": "success" if healthy else "corrupt",
                "healthy": healthy,
                "db_path": resolved,
                "size_bytes": os.path.getsize(resolved),
                "check_result": messages,
                "table_counts": counts,
            }
        finally:
            conn.close()
    except (sqlite3.Error, OSError) as exc:
        return {
            "status": "error",
            "healthy": False,
            "db_path": resolved,
            "message": str(exc),
        }


def create_verified_db_snapshot(
    db_path: str | None = None,
    backup_dir: str | None = None,
    max_backups: int = 7,
) -> dict[str, Any]:
    """Create a hot-safe, integrity-verified .tar.gz snapshot with automatic rotation."""
    src_db = _resolve_db_path(db_path)
    out_dir = _resolve_backup_dir(backup_dir)

    health = verify_sqlite_integrity(src_db)
    if not health.get("healthy"):
        return {
            "status": "error",
            "message": f"Backup dibatalkan karena DB sumber tidak sehat: {health.get('message') or health.get('check_result')}",
            "health": health,
        }

    ts_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_name = f"alfa_snapshot_{ts_str}_{int(time.time() * 1000) % 1000:03d}.tar.gz"
    archive_path = os.path.join(out_dir, archive_name)

    with tempfile.TemporaryDirectory(prefix="alfa_bkp_") as tmp_dir:
        hot_db_copy = os.path.join(tmp_dir, "agent_data.db")
        src_conn = sqlite3.connect(src_db, timeout=15.0)
        dst_conn = sqlite3.connect(hot_db_copy, timeout=15.0)
        try:
            src_conn.backup(dst_conn)
        finally:
            dst_conn.close()
            src_conn.close()

        copy_health = verify_sqlite_integrity(hot_db_copy)
        if not copy_health.get("healthy"):
            return {
                "status": "error",
                "message": "Salinan backup gagal verifikasi integritas.",
            }

        sha256_hash = hashlib.sha256()
        with open(hot_db_copy, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                sha256_hash.update(chunk)

        manifest = {
            "created_at": datetime.now().isoformat(),
            "source_db": src_db,
            "db_sha256": sha256_hash.hexdigest(),
            "db_size_bytes": os.path.getsize(hot_db_copy),
            "table_counts": copy_health.get("table_counts", {}),
        }
        manifest_path = os.path.join(tmp_dir, "manifest.json")
        with open(manifest_path, "w", encoding="utf-8") as mf:
            json.dump(manifest, mf, indent=2, ensure_ascii=False)

        with tarfile.open(archive_path, "w:gz") as tar:
            tar.add(hot_db_copy, arcname="agent_data.db")
            tar.add(manifest_path, arcname="manifest.json")
            sys_prompt = os.path.expanduser("~/.alfa/system_prompt.txt")
            if os.path.exists(sys_prompt):
                tar.add(sys_prompt, arcname="system_prompt.txt")

    # Rotasi otomatis: pertahankan max_backups snapshot terbaru
    removed: list[str] = []
    if max_backups > 0:
        existing = sorted(
            glob.glob(os.path.join(out_dir, "alfa_snapshot_*.tar.gz")),
            key=lambda p: os.path.getmtime(p),
            reverse=True,
        )
        for old_file in existing[max_backups:]:
            try:
                os.remove(old_file)
                removed.append(os.path.basename(old_file))
            except OSError:
                pass

    return {
        "status": "success",
        "snapshot_path": archive_path,
        "snapshot_name": archive_name,
        "size_bytes": os.path.getsize(archive_path),
        "db_sha256": manifest["db_sha256"],
        "table_counts": manifest["table_counts"],
        "rotated_out": removed,
    }


def list_db_snapshots(backup_dir: str | None = None) -> dict[str, Any]:
    """List available database snapshots sorted newest first."""
    out_dir = _resolve_backup_dir(backup_dir)
    files = sorted(
        glob.glob(os.path.join(out_dir, "alfa_snapshot_*.tar.gz")),
        key=lambda p: os.path.getmtime(p),
        reverse=True,
    )
    snapshots = []
    for p in files:
        try:
            st = os.stat(p)
            snapshots.append(
                {
                    "name": os.path.basename(p),
                    "path": p,
                    "size_bytes": st.st_size,
                    "modified_at": datetime.fromtimestamp(st.st_mtime).isoformat(),
                }
            )
        except OSError:
            continue
    return {
        "status": "success",
        "backup_dir": out_dir,
        "total": len(snapshots),
        "snapshots": snapshots,
    }


def restore_db_snapshot(
    snapshot_path: str, target_db_path: str | None = None
) -> dict[str, Any]:
    """Safely restore agent_data.db from a verified .tar.gz snapshot archive."""
    snap = os.path.abspath(os.path.expanduser(str(snapshot_path).strip()))
    if not os.path.exists(snap):
        return {"status": "error", "message": f"Snapshot tidak ditemukan: {snap}"}

    dst_db = _resolve_db_path(target_db_path)
    with tempfile.TemporaryDirectory(prefix="alfa_restore_") as tmp_dir:
        try:
            with tarfile.open(snap, "r:gz") as tar:
                member = tar.getmember("agent_data.db")
                tar.extract(member, path=tmp_dir, filter="data")
        except (tarfile.TarError, KeyError, OSError) as exc:
            return {"status": "error", "message": f"Gagal mengekstrak arsip: {exc}"}

        extracted_db = os.path.join(tmp_dir, "agent_data.db")
        health = verify_sqlite_integrity(extracted_db)
        if not health.get("healthy"):
            return {
                "status": "error",
                "message": "File DB di dalam arsip gagal verifikasi integritas.",
            }

        os.makedirs(os.path.dirname(dst_db), exist_ok=True)
        shutil.copy2(extracted_db, dst_db)

    return {
        "status": "success",
        "restored_to": dst_db,
        "from_snapshot": snap,
        "table_counts": health.get("table_counts", {}),
    }
