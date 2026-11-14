"""Tes Evidence Ledger: bukti deterministik, fail-soft, dan proof-carrying."""

from __future__ import annotations

import json
import sqlite3

import pytest

from alfa.core.db import evidence
from alfa.core.db.connection import get_sync_db, init_db_sync
from alfa.core.runtime_ctx import begin_turn, reset_turn_context


@pytest.fixture(autouse=True)
def _clean_turn_ctx():
    reset_turn_context()
    yield
    reset_turn_context()


@pytest.fixture()
def isolated_evidence_db(tmp_path, monkeypatch):
    db_file = str(tmp_path / "evidence_test.db")
    monkeypatch.setenv("ALFA_DB_PATH", db_file)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    init_db_sync()
    with get_sync_db() as conn:
        try:
            conn.execute("DELETE FROM evidence_ledger")
            conn.commit()
        except sqlite3.Error:
            pass
    return db_file


def _artifact(tmp_path, name: str = "rekap.xlsx") -> str:
    path = tmp_path / name
    path.write_bytes(b"nama file uji")
    return str(path)


def test_record_hashes_real_artifact(isolated_evidence_db, tmp_path):
    reset_turn_context()
    turn_id = begin_turn()
    path = _artifact(tmp_path)

    rows = evidence.record_tool_evidence(
        "update_excel_sheet",
        arguments=json.dumps({"file_path": path}),
        output=json.dumps({"status": "success", "file_path": path}),
    )

    assert len(rows) == 1
    assert rows[0]["path"] == path
    assert len(rows[0]["sha256"]) == 64
    assert rows[0]["turn_id"] == turn_id
    stored = evidence.list_evidence_sync(turn_id=turn_id)
    assert len(stored) == 1
    assert stored[0]["tool"] == "update_excel_sheet"
    assert stored[0]["meta"]["mutating"] is True


def test_dry_run_output_is_recorded_as_preview(isolated_evidence_db, tmp_path):
    path = _artifact(tmp_path)
    rows = evidence.record_tool_evidence(
        "update_excel_sheet",
        arguments=json.dumps({"file_path": path}),
        output=json.dumps(
            {"status": "preview", "dry_run": True, "file_path": path}
        ),
    )

    assert len(rows) == 1
    assert rows[0]["status"] == "preview"


def test_error_status_is_recorded_for_mutating_tool(isolated_evidence_db, tmp_path):
    path = _artifact(tmp_path)
    rows = evidence.record_tool_evidence(
        "update_excel_sheet",
        arguments=json.dumps({"file_path": path}),
        output=json.dumps(
            {"status": "error", "message": "verifikasi gagal", "file_path": path}
        ),
    )

    assert len(rows) == 1
    assert rows[0]["status"] == "error"
    assert rows[0]["path"] == ""
    assert rows[0]["sha256"] == ""


def test_prune_keeps_only_newest_rows(isolated_evidence_db, tmp_path):
    path = _artifact(tmp_path)
    for _ in range(3):
        evidence.record_tool_evidence(
            "update_excel_sheet", output=json.dumps({"file_path": path})
        )

    result = evidence.prune_evidence_sync(days=0, max_rows=2)

    assert result["status"] == "ok"
    assert result["deleted_excess"] == 1
    assert len(evidence.list_evidence_sync()) == 2


def test_read_only_tool_without_artifact_is_not_recorded(isolated_evidence_db):
    rows = evidence.record_tool_evidence(
        "web_search", arguments='{"q":"alfa"}', output="hasil teks"
    )
    assert rows == []


def test_mode_off_records_nothing(isolated_evidence_db, tmp_path, monkeypatch):
    monkeypatch.setenv("ALFA_EVIDENCE_LEDGER", "off")
    path = _artifact(tmp_path)

    assert (
        evidence.record_tool_evidence(
            "update_excel_sheet",
            output=json.dumps({"file_path": path}),
        )
        == []
    )
    assert evidence.list_evidence_sync() == []


def test_ledger_mode_normalization(monkeypatch):
    monkeypatch.setenv("ALFA_EVIDENCE_LEDGER", "TRUE")
    assert evidence.ledger_mode() == "on"
    monkeypatch.setenv("ALFA_EVIDENCE_LEDGER", "0")
    assert evidence.ledger_mode() == "off"
    monkeypatch.setenv("ALFA_EVIDENCE_LEDGER", "aneh")
    assert evidence.ledger_mode() == "shadow"


def test_summary_counts_recent_rows(isolated_evidence_db, tmp_path):
    path = _artifact(tmp_path)
    evidence.record_tool_evidence(
        "update_excel_sheet", output=json.dumps({"file_path": path})
    )

    summary = evidence.evidence_summary_sync(hours=24)

    assert summary["total"] == 1
    assert summary["recent"] == 1
    assert summary["unique_paths"] == 1
    assert summary["by_status"] == {"success": 1}
    assert summary["top_tools"][0]["tool"] == "update_excel_sheet"


def test_shadow_mode_does_not_change_reply(
    isolated_evidence_db, tmp_path, monkeypatch
):
    monkeypatch.setenv("ALFA_EVIDENCE_LEDGER", "shadow")
    reset_turn_context()
    turn_id = begin_turn()
    path = _artifact(tmp_path)
    evidence.record_tool_evidence(
        "update_excel_sheet", output=json.dumps({"file_path": path})
    )

    assert evidence.decorate_with_evidence("Selesai.", turn_id) == "Selesai."


def test_on_mode_appends_proof_block(isolated_evidence_db, tmp_path, monkeypatch):
    monkeypatch.setenv("ALFA_EVIDENCE_LEDGER", "on")
    reset_turn_context()
    turn_id = begin_turn()
    path = _artifact(tmp_path)
    evidence.record_tool_evidence(
        "update_excel_sheet", output=json.dumps({"file_path": path})
    )

    decorated = evidence.decorate_with_evidence("Selesai.", turn_id)

    assert decorated.startswith("Selesai.")
    assert "Bukti eksekusi (evidence ledger)" in decorated
    assert "update_excel_sheet" in decorated
    assert "sha256" in decorated
    # Idempoten: dekorasi kedua tidak menambah blok baru.
    assert evidence.decorate_with_evidence(decorated, turn_id) == decorated


def test_proof_block_empty_without_artifact(isolated_evidence_db):
    reset_turn_context()
    assert evidence.proof_block_for_turn(begin_turn()) == ""


def test_record_failure_is_fail_soft(tmp_path, monkeypatch):
    broken = tmp_path / "bukan-file"
    broken.mkdir()
    monkeypatch.setenv("ALFA_DB_PATH", str(broken))
    monkeypatch.setenv("ALFA_EVIDENCE_LEDGER", "on")

    assert (
        evidence.record_tool_evidence(
            "update_excel_sheet",
            output=json.dumps({"file_path": str(tmp_path / "x.xlsx")}),
        )
        == []
    )


def test_execute_tool_writes_evidence(isolated_evidence_db, tmp_path, monkeypatch):
    from alfa.core.brain.tool_exec import _execute_tool

    monkeypatch.setenv("ALFA_EVIDENCE_LEDGER", "on")
    reset_turn_context()
    turn_id = begin_turn()
    path = tmp_path / "rekap.xlsx"
    payload = {
        "file_path": str(path),
        "sheet_name": "Stok",
        "headers": ["Item", "Qty"],
        "rows_json": '[["A", 1]]',
    }

    output = _execute_tool("update_excel_sheet", json.dumps(payload))

    assert "success" in output
    rows = evidence.list_evidence_sync(turn_id=turn_id)
    assert rows
    assert rows[0]["path"] == str(path)
    assert rows[0]["sha256"]
