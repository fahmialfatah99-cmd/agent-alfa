"""
Level 5+ Predictive Operational World-Model for ALFA OS.

Maintains a live causal representation of field operations (Telecom clusters,
material dispatches, pole returns, and Master Ledger integrity) to pre-emptively
flag anomalies and prepare actionable insights before the user even asks.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
from typing import Any

from alfa.core.db.connection import get_sync_db

logger = logging.getLogger("ApexWorldModel")


def init_world_model_tables() -> None:
    """Ensure SQLite tables for the Predictive World-Model are initialized."""
    with get_sync_db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS alfa_world_state_anomalies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                anomaly_id TEXT UNIQUE,
                cluster_name TEXT,
                category TEXT,
                severity TEXT DEFAULT 'MEDIUM',
                description TEXT,
                recommended_action TEXT,
                resolved INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_world_anomalies_cluster ON alfa_world_state_anomalies(cluster_name);"
        )
        conn.commit()


def record_world_anomaly(
    cluster_name: str,
    category: str,
    description: str,
    recommended_action: str,
    severity: str = "MEDIUM",
) -> dict[str, Any]:
    """Record a pre-emptive operational anomaly detected by the World-Model."""
    init_world_model_tables()
    c_clean = cluster_name.strip().upper() or "GLOBAL"
    aid_hash = hashlib.sha256(f"{c_clean}:{category}:{description}".encode()).hexdigest()[:10]
    anomaly_id = f"anom_{c_clean}_{aid_hash}"

    with get_sync_db() as conn:
        conn.execute(
            """
            INSERT INTO alfa_world_state_anomalies
            (anomaly_id, cluster_name, category, severity, description, recommended_action, resolved)
            VALUES (?, ?, ?, ?, ?, ?, 0)
            ON CONFLICT(anomaly_id) DO UPDATE SET
                severity = excluded.severity,
                recommended_action = excluded.recommended_action
            """,
            (anomaly_id, c_clean, category.upper(), severity.upper(), description, recommended_action),
        )
        conn.commit()

    return {
        "status": "recorded",
        "anomaly_id": anomaly_id,
        "cluster_name": c_clean,
        "category": category.upper(),
        "severity": severity.upper(),
        "description": description,
        "recommended_action": recommended_action,
    }


def analyze_field_event_preemptively(event_text: str, cluster_hint: str = "LAHAT") -> dict[str, Any]:
    """
    Causal & Predictive analysis of incoming field messages (WhatsApp / Telegram):
    Detects potential logistics discrepancies before they corrupt the Master Ledger.
    """
    init_world_model_tables()
    if not event_text or not event_text.strip():
        return {"status": "clean", "anomalies_detected": []}

    t_low = event_text.lower()
    cluster = cluster_hint.strip().upper()
    for candidate in ("LAHAT", "CURUP", "BENGKULU", "LUBUKLINGGAU"):
        if candidate.lower() in t_low:
            cluster = candidate
            break

    detected: list[dict[str, Any]] = []

    # 1. Detect unquantified return mention ('retur' without explicit pole count)
    if "retur" in t_low and not re.search(r"\d+\s*(?:batang|btg|unit|pcs|tiang)?", t_low):
        anom = record_world_anomaly(
            cluster_name=cluster,
            category="UNQUANTIFIED_RETURN",
            severity="HIGH",
            description=f"Terdeteksi penyebutan 'retur' tanpa kuantitas angka yang jelas: '{event_text[:80]}'",
            recommended_action="Konfirmasi jumlah batang retur ke mandor terkait sebelum memperbarui saldo Net.",
        )
        detected.append(anom)

    # 2. Detect large pole dispatch without breakdown specification (T72/T73/T74/T94)
    large_qty_match = re.search(r"\b(\d{2,4})\s*(?:batang|btg)\s*tiang\b|\btiang\s*(\d{2,4})\s*(?:batang|btg)\b", t_low)
    if large_qty_match:
        qty_str = large_qty_match.group(1) or large_qty_match.group(2)
        qty = int(qty_str) if qty_str and qty_str.isdigit() else 0
        has_spec = any(spec in t_low for spec in ("7m", "9m", "2.5", "3 inch", "4 inch", "t72", "t73", "t74", "t94"))
        if qty >= 50 and not has_spec:
            anom = record_world_anomaly(
                cluster_name=cluster,
                category="MISSING_POLE_SPEC_BREAKDOWN",
                severity="MEDIUM",
                description=f"Pengambilan tiang jumlah besar ({qty} btg) belum mencantumkan spesifikasi tipe (7m/9m).",
                recommended_action="Pastikan distribusi T72/T73/T74/T94 tercatat agar kolom SUMIFS di Master Ledger akurat.",
            )
            detected.append(anom)

    return {
        "status": "alert" if detected else "clean",
        "cluster": cluster,
        "anomalies_detected": detected,
    }


def get_world_model_summary() -> dict[str, Any]:
    """Retrieve the current Predictive World-Model state and active pre-emptive alerts."""
    init_world_model_tables()
    with get_sync_db() as conn:
        unresolved_count = conn.execute(
            "SELECT COUNT(*) FROM alfa_world_state_anomalies WHERE resolved = 0"
        ).fetchone()[0]
        recent_rows = conn.execute(
            """
            SELECT anomaly_id, cluster_name, category, severity, description, recommended_action, created_at
            FROM alfa_world_state_anomalies
            WHERE resolved = 0
            ORDER BY id DESC
            LIMIT 5
            """
        ).fetchall()
        active_anomalies = [dict(r) for r in recent_rows]

    # Check known Master Ledger files on disk
    sandbox_dir = os.path.expanduser("~/agent alfa/sandbox_workspace")
    master_files = []
    if os.path.isdir(sandbox_dir):
        for fname in os.listdir(sandbox_dir):
            if "master" in fname.lower() and fname.endswith(".xlsx"):
                master_files.append(fname)

    return {
        "status": "success",
        "unresolved_anomalies_count": unresolved_count,
        "active_anomalies": active_anomalies,
        "tracked_clusters": ["LAHAT", "CURUP", "BENGKULU"],
        "detected_master_ledgers": sorted(master_files)[:5],
    }
