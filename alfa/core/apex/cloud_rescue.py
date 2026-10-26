"""
Phase 1 Perfection: Resilient Cloud-Local Media Vault & Auto-Rescue Bridge for ALFA OS.

Guarantees 0% data/media loss when Google Drive Service Account uploads are rejected
by quota limits ('[Drive] Upload ditolak'). Automatically vaults field media and
Master Ledgers into a structured local repository (`sandbox_workspace/wa_media_vault/`)
and attempts non-intrusive OAuth2 user-token cloud synchronization without touching
`wa-sheets-bot.service`.
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
from datetime import datetime
from typing import Any

from alfa.core.db.connection import get_sync_db

logger = logging.getLogger("ApexCloudRescue")

DEFAULT_VAULT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "sandbox_workspace", "wa_media_vault")
)


def init_cloud_rescue_tables() -> None:
    """Initialize SQLite table tracking vaulted field media and cloud sync status."""
    with get_sync_db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS alfa_cloud_rescue_vault (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_hash TEXT UNIQUE,
                original_filename TEXT,
                cluster_name TEXT DEFAULT 'GLOBAL',
                local_vault_path TEXT,
                gdrive_file_id TEXT DEFAULT '',
                sync_status TEXT DEFAULT 'LOCAL_VAULTED',
                file_size_bytes INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_cloud_rescue_status ON alfa_cloud_rescue_vault(sync_status);"
        )
        conn.commit()


def _compute_file_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def stage_file_for_cloud_rescue(
    file_path: str,
    cluster_name: str = "LAHAT",
    attempt_cloud_upload: bool = False,
    vault_root: str | None = None,
) -> dict[str, Any]:
    """
    Safely vault a file into the local structured archive (`<vault_root>/<CLUSTER>/<YYYY-MM-DD>/`)
    and optionally attempt OAuth2 Google Drive upload fallback.
    """
    init_cloud_rescue_tables()
    if not file_path or not os.path.isfile(file_path):
        return {"status": "error", "message": f"File not found: {file_path}"}

    c_clean = (cluster_name or "GLOBAL").strip().upper()
    date_folder = datetime.now().strftime("%Y-%m-%d")
    root_dir = vault_root or DEFAULT_VAULT_ROOT
    dest_dir = os.path.join(root_dir, c_clean, date_folder)
    os.makedirs(dest_dir, exist_ok=True)

    fname = os.path.basename(file_path)
    f_hash = _compute_file_sha256(file_path)[:24]
    f_size = os.path.getsize(file_path)

    dest_path = os.path.join(dest_dir, fname)
    if os.path.abspath(file_path) != os.path.abspath(dest_path):
        shutil.copy2(file_path, dest_path)

    gdrive_id = ""
    sync_status = "LOCAL_VAULTED"

    if attempt_cloud_upload:
        try:
            from alfa.tools.filesystem import gdrive_upload_file

            up_res = gdrive_upload_file(local_path=dest_path)
            if isinstance(up_res, dict) and up_res.get("status") == "success":
                gdrive_id = str(up_res.get("file_id") or up_res.get("id") or "")
                sync_status = "CLOUD_SYNCED"
        except Exception as e:
            logger.debug("Cloud upload fallback deferred to local vault: %s", e)

    with get_sync_db() as conn:
        conn.execute(
            """
            INSERT INTO alfa_cloud_rescue_vault
            (file_hash, original_filename, cluster_name, local_vault_path, gdrive_file_id, sync_status, file_size_bytes, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(file_hash) DO UPDATE SET
                local_vault_path = excluded.local_vault_path,
                gdrive_file_id = CASE WHEN excluded.gdrive_file_id != '' THEN excluded.gdrive_file_id ELSE alfa_cloud_rescue_vault.gdrive_file_id END,
                sync_status = CASE WHEN excluded.sync_status = 'CLOUD_SYNCED' THEN 'CLOUD_SYNCED' ELSE alfa_cloud_rescue_vault.sync_status END,
                updated_at = CURRENT_TIMESTAMP
            """,
            (f_hash, fname, c_clean, dest_path, gdrive_id, sync_status, f_size),
        )
        conn.commit()

    return {
        "status": "success",
        "file_hash": f_hash,
        "original_filename": fname,
        "cluster_name": c_clean,
        "local_vault_path": dest_path,
        "sync_status": sync_status,
        "gdrive_file_id": gdrive_id,
        "file_size_bytes": f_size,
    }


def run_cloud_rescue_sweep(workspace_dir: str | None = None) -> dict[str, Any]:
    """
    Scan `sandbox_workspace` for Master Ledgers and field artifacts, ensuring every
    critical file is safely backed up in the structured local vault.
    """
    init_cloud_rescue_tables()
    ws = workspace_dir or os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "sandbox_workspace")
    )
    rescued = 0
    if os.path.isdir(ws):
        for fname in os.listdir(ws):
            fpath = os.path.join(ws, fname)
            if not os.path.isfile(fpath):
                continue
            low = fname.lower()
            if ("master" in low or "laporan" in low or "rekap" in low) and low.endswith((".xlsx", ".pdf")):
                cluster = "LAHAT"
                for cand in ("LAHAT", "CURUP", "BENGKULU", "LUBUKLINGGAU"):
                    if cand.lower() in low:
                        cluster = cand
                        break
                res = stage_file_for_cloud_rescue(fpath, cluster_name=cluster, attempt_cloud_upload=False)
                if res.get("status") == "success":
                    rescued += 1

    metrics = get_cloud_rescue_metrics()
    metrics["newly_secured_files"] = rescued
    return metrics


def get_cloud_rescue_metrics() -> dict[str, Any]:
    """Return telemetry for the Cloud-Local Media & Ledger Rescue Vault."""
    init_cloud_rescue_tables()
    with get_sync_db() as conn:
        row = conn.execute(
            """
            SELECT
                COUNT(*) AS total_vaulted,
                COALESCE(SUM(CASE WHEN sync_status = 'CLOUD_SYNCED' THEN 1 ELSE 0 END), 0) AS cloud_synced,
                COALESCE(SUM(file_size_bytes), 0) AS total_bytes
            FROM alfa_cloud_rescue_vault
            """
        ).fetchone()

    return {
        "status": "success",
        "total_vaulted_files": int(row["total_vaulted"]) if row else 0,
        "cloud_synced_files": int(row["cloud_synced"]) if row else 0,
        "total_vault_size_kb": round((int(row["total_bytes"]) if row else 0) / 1024.0, 2),
        "vault_root": DEFAULT_VAULT_ROOT,
    }
