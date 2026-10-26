"""
Phase 4 Perfection: Autonomous Maintenance, Dreaming Consolidation & Ledger Audit Daemon.

Orchestrates periodic self-maintenance across ALFA OS Level 5+ without interrupting
active chats or quarantined services (`wa-sheets-bot.service`):
1. Runs Offline Dreaming Fast-Path Compilation.
2. Audits all Master Excel Ledgers for 100% dynamic formula integrity (0 circular refs).
3. Sweeps and secures field artifacts into the Resilient Cloud-Local Vault.
4. Executes a non-blocking SQLite WAL passive checkpoint.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from alfa.core.apex.cloud_rescue import run_cloud_rescue_sweep
from alfa.core.apex.dreaming_compiler import run_idle_dreaming_cycle
from alfa.core.apex.hardware_governor import get_hardware_governor_state
from alfa.core.apex.neuro_symbolic import sync_symbolic_constraints_from_master_ledgers
from alfa.core.db.connection import get_sync_db

logger = logging.getLogger("ApexMaintenance")


def run_autonomous_apex_maintenance(force: bool = False) -> dict[str, Any]:
    """
    Execute the complete 4-Stage Level 5+ Perfection Maintenance Cycle.
    """
    t0 = time.perf_counter()
    gov = get_hardware_governor_state()

    # 1. Dreaming Fast-Path Consolidation
    dream_res = run_idle_dreaming_cycle(force=force)

    # 2. Symbolic Master Ledger Formula Integrity Audit & Sync
    ledger_res = sync_symbolic_constraints_from_master_ledgers()

    # 3. Resilient Cloud-Local Vault Sweep
    vault_res = run_cloud_rescue_sweep()

    # 4. Non-blocking SQLite WAL Passive Checkpoint
    wal_status = "ok"
    try:
        with get_sync_db() as conn:
            conn.execute("PRAGMA wal_checkpoint(PASSIVE);")
    except Exception as e:
        wal_status = f"skipped: {e}"

    # 5. Verified SQLite Snapshot & Auto-Rotation (7-snapshot retention)
    snapshot_res: dict[str, Any] = {"status": "skipped"}
    try:
        from alfa.core.db.backup_manager import create_verified_db_snapshot

        snapshot_res = create_verified_db_snapshot(max_backups=7)
    except Exception as bkp_err:
        snapshot_res = {"status": "error", "message": str(bkp_err)}

    elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
    return {
        "status": "success",
        "governor_mode": gov.get("governor_mode"),
        "dreaming_consolidation": dream_res,
        "symbolic_ledger_audit": ledger_res,
        "cloud_local_vault": vault_res,
        "sqlite_wal_checkpoint": wal_status,
        "db_snapshot_backup": snapshot_res,
        "duration_ms": elapsed_ms,
    }
