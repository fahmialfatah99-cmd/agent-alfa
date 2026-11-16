"""Tes operasional backup DB: snapshot, sidecar, drill, dan isolasi test."""

from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_backup_module():
    """Muat scripts/backup_db.py tanpa menjadikan scripts sebuah package."""
    path = ROOT / "scripts" / "backup_db.py"
    spec = importlib.util.spec_from_file_location("alfa_backup_db_ops", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def ops_db(tmp_path, monkeypatch):
    """DB mirip produksi (beberapa tabel + baris) dan direktori backup terisolasi."""
    db_path = tmp_path / "prod_like.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE api_keys (id INTEGER PRIMARY KEY, label TEXT);
        CREATE TABLE chat_history (id INTEGER PRIMARY KEY, message TEXT);
        CREATE TABLE durable_tasks (id INTEGER PRIMARY KEY, status TEXT);
        INSERT INTO api_keys (label) VALUES ('a'), ('b');
        INSERT INTO chat_history (message) VALUES ('halo'), ('tes'), ('backup');
        INSERT INTO durable_tasks (status) VALUES ('done');
        """
    )
    conn.commit()
    conn.close()
    monkeypatch.setenv("ALFA_DB_PATH", str(db_path))
    monkeypatch.setenv("ALFA_BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.delenv("ALFA_BACKUP_OFFSITE_REMOTE", raising=False)
    return db_path


def test_run_backup_creates_verified_snapshot_and_sidecar(ops_db, tmp_path):
    module = _load_backup_module()
    result = module.run_backup(
        backup_dir=tmp_path / "backups", offsite_remote=""
    )

    assert result["status"] == "ok", result
    archive = Path(result["archive"])
    assert archive.exists()
    assert archive.stat().st_size > 0
    assert result["table_total"] == 3
    assert result["offsite"]["status"] == "skipped"

    sidecar = json.loads(
        archive.with_name(archive.name + module.SIDECAR_SUFFIX).read_text(
            encoding="utf-8"
        )
    )
    assert sidecar["table_total"] == 3
    assert sidecar["tables"]["api_keys"] == 2
    assert sidecar["tables"]["chat_history"] == 3

    weekly = Path(result["weekly"]["target"])
    assert weekly.exists()
    assert result["weekly"]["copied"] is True


def test_verify_archive_detects_sidecar_mismatch(ops_db, tmp_path):
    module = _load_backup_module()
    result = module.run_backup(
        backup_dir=tmp_path / "backups", offsite_remote=""
    )
    archive = Path(result["archive"])
    sidecar_path = archive.with_name(archive.name + module.SIDECAR_SUFFIX)
    payload = json.loads(sidecar_path.read_text(encoding="utf-8"))
    payload["tables"]["api_keys"] = 999
    sidecar_path.write_text(json.dumps(payload), encoding="utf-8")

    checked = module.verify_archive(archive)

    assert checked["status"] == "error"
    assert any("api_keys" in problem for problem in checked["problems"])


def test_restore_drill_passes_on_latest_snapshot(ops_db, tmp_path):
    module = _load_backup_module()
    backup_dir = tmp_path / "backups"
    created = module.run_backup(backup_dir=backup_dir, offsite_remote="")
    assert created["status"] == "ok", created

    drilled = module.restore_drill(backup_dir=backup_dir)

    assert drilled["status"] == "ok", drilled
    assert drilled["table_total"] == 3
    assert drilled["sidecar"] is True
    assert drilled["tables"]["durable_tasks"] == 1


def test_run_backup_fails_when_source_missing(monkeypatch, tmp_path):
    module = _load_backup_module()
    monkeypatch.setenv("ALFA_DB_PATH", str(tmp_path / "missing.db"))

    result = module.run_backup(
        backup_dir=tmp_path / "backups", offsite_remote=""
    )

    assert result["status"] == "error"
    assert result["stage"] == "source"


def test_compare_counts_ignores_skipped_virtual_tables():
    module = _load_backup_module()
    info = {"table_total": 2, "tables": {"api_keys": 1}, "skipped": ["vss_idx"]}
    expected = {
        "table_total": 2,
        "tables": {"api_keys": 1, "vss_idx": 5},
        "skipped": ["vss_idx"],
    }

    assert module._compare_counts(info, expected, exact=True) == []


def test_backup_dir_is_isolated_from_production_home():
    """Regresi: test suite tidak boleh menulis ke ~/.alfa/backups asli."""
    from alfa.core.db.backup_manager import _resolve_backup_dir

    configured = Path(os.environ["ALFA_BACKUP_DIR"]).resolve()
    production = Path.home() / ".alfa" / "backups"
    assert configured != production.resolve()
    assert str(configured).startswith(tempfile.gettempdir())
    assert Path(_resolve_backup_dir()).resolve() == configured
