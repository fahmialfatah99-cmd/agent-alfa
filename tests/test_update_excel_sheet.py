"""Tes tool deterministik `update_excel_sheet` (atomic write + read-back)."""

from __future__ import annotations

import json
from pathlib import Path

from openpyxl import Workbook, load_workbook

from alfa.tools.media import documents


def _make_workbook(path, sheet: str = "Rekap Material", rows=(("lama",),)):
    wb = Workbook()
    ws = wb.active
    ws.title = sheet
    for row in rows:
        ws.append(list(row))
    wb.save(path)
    return path


def _sheet_rows(path, sheet: str, max_row: int = 10):
    wb = load_workbook(path, read_only=True)
    try:
        return list(
            wb[sheet].iter_rows(min_row=1, max_row=max_row, values_only=True)
        )
    finally:
        wb.close()


def test_creates_new_workbook_and_verifies(tmp_path):
    path = tmp_path / "baru.xlsx"

    result = documents.update_excel_sheet(
        str(path),
        "Monitoring Stok",
        headers=["Kategori", "Item", "Sisa"],
        rows_json=json.dumps([["Tiang", "T72", 15]]),
        title="MONITORING STOK",
    )

    assert result["status"] == "success"
    assert result["verified"] is True
    assert result["sheets"] == ["Monitoring Stok"]
    assert result["rows_written"] == 1
    rows = _sheet_rows(path, "Monitoring Stok", max_row=3)
    assert rows[0][0] == "MONITORING STOK"
    assert rows[1][:3] == ("Kategori", "Item", "Sisa")
    assert rows[2][:3] == ("Tiang", "T72", 15)


def test_upsert_replaces_sheet_and_preserves_others(tmp_path):
    path = _make_workbook(tmp_path / "rekap.xlsx")
    wb = load_workbook(path)
    wb.create_sheet("Lain").append(["tetap"])
    wb.save(path)

    result = documents.update_excel_sheet(
        str(path),
        "Rekap Material",
        headers=["A", "B"],
        rows_json='[["baru", 1]]',
    )

    assert result["status"] == "success"
    assert result["sheets"] == ["Rekap Material", "Lain"]
    rows = _sheet_rows(path, "Rekap Material", max_row=2)
    assert rows[0][:2] == ("A", "B")
    assert rows[1][:2] == ("baru", 1)
    assert _sheet_rows(path, "Lain", max_row=1)[0][0] == "tetap"


def test_append_adds_rows_without_duplicating_headers(tmp_path):
    path = _make_workbook(tmp_path / "rekap.xlsx", sheet="Stok", rows=())
    documents.update_excel_sheet(
        str(path), "Stok", headers=["Item", "Qty"], rows_json='[["A", 1]]'
    )

    result = documents.update_excel_sheet(
        str(path), "Stok", rows_json='[["B", 2]]', mode="append"
    )

    assert result["status"] == "success"
    assert result["total_rows"] == 3
    rows = _sheet_rows(path, "Stok", max_row=3)
    assert rows[0][:2] == ("Item", "Qty")
    assert rows[1][:2] == ("A", 1)
    assert rows[2][:2] == ("B", 2)


def test_dict_rows_derive_headers(tmp_path):
    path = tmp_path / "dict.xlsx"

    result = documents.update_excel_sheet(
        str(path),
        "Data",
        rows_json=json.dumps([{"Nama": "Tiang", "Qty": 3}]),
    )

    assert result["status"] == "success"
    rows = _sheet_rows(path, "Data", max_row=2)
    assert rows[0][:2] == ("Nama", "Qty")
    assert rows[1][:2] == ("Tiang", 3)


def test_replace_mode_recreates_sheet(tmp_path):
    path = _make_workbook(tmp_path / "rekap.xlsx", sheet="S", rows=(("lama",),))

    result = documents.update_excel_sheet(
        str(path), "S", headers=["Baru"], rows_json='[["isi"]]', mode="replace"
    )

    assert result["status"] == "success"
    rows = _sheet_rows(path, "S", max_row=2)
    assert rows[0][0] == "Baru"
    assert rows[1][0] == "isi"


def test_invalid_inputs_return_error_without_writing(tmp_path):
    path = tmp_path / "x.xlsx"

    assert documents.update_excel_sheet("x.csv", "S", headers=["A"])["status"] == "error"
    assert documents.update_excel_sheet(str(path), "", headers=["A"])["status"] == "error"
    assert (
        documents.update_excel_sheet(str(path), "S", headers=["A"], mode="delete")[
            "status"
        ]
        == "error"
    )
    assert documents.update_excel_sheet(str(path), "S")["status"] == "error"
    assert (
        documents.update_excel_sheet(str(tmp_path / "missing" / "x.xlsx"), "S", headers=["A"])[
            "status"
        ]
        == "error"
    )
    assert (
        documents.update_excel_sheet(str(path), "S[]", headers=["A"])["status"]
        == "error"
    )
    assert not path.exists()


def test_corrupt_workbook_returns_error_and_preserves_file(tmp_path):
    path = tmp_path / "rusak.xlsx"
    path.write_bytes(b"bukan zip excel")

    result = documents.update_excel_sheet(str(path), "S", headers=["A"])

    assert result["status"] == "error"
    assert "Gagal update Excel" in result["message"]
    assert path.read_bytes() == b"bukan zip excel"


def test_failed_verification_restores_original(tmp_path, monkeypatch):
    path = _make_workbook(tmp_path / "rekap.xlsx", sheet="S", rows=(("lama",),))
    monkeypatch.setattr(
        documents,
        "_verify_excel_sheet",
        lambda *_a, **_k: (False, "simulasi verifikasi gagal", ["S"]),
    )

    result = documents.update_excel_sheet(str(path), "S", headers=["Baru"])

    assert result["status"] == "error"
    assert result["verified"] is False
    assert "Verifikasi gagal" in result["message"]
    rows = _sheet_rows(path, "S", max_row=1)
    assert rows[0][0] == "lama"


def test_failed_verification_removes_new_file(tmp_path, monkeypatch):
    path = tmp_path / "baru.xlsx"
    monkeypatch.setattr(
        documents,
        "_verify_excel_sheet",
        lambda *_a, **_k: (False, "simulasi", []),
    )

    result = documents.update_excel_sheet(str(path), "S", headers=["A"])

    assert result["status"] == "error"
    assert not path.exists()


def test_dry_run_previews_append_without_writing(tmp_path):
    path = _make_workbook(tmp_path / "rekap.xlsx", sheet="Stok", rows=())
    documents.update_excel_sheet(
        str(path), "Stok", headers=["Item", "Qty"], rows_json='[["A", 1]]'
    )
    before = path.read_bytes()

    result = documents.update_excel_sheet(
        str(path),
        "Stok",
        rows_json='[["B", 2]]',
        mode="append",
        dry_run=True,
    )

    assert result["status"] == "preview"
    assert result["dry_run"] is True
    assert result["applied"] is False
    diff = result["diff"]
    assert diff["action"] == "append_rows"
    assert diff["rows_added"] == 1
    assert diff["changed"] is True
    assert diff["file_sha256"]
    assert ["B", 2] in diff["sample_after"]
    assert path.read_bytes() == before
    rows = _sheet_rows(path, "Stok", max_row=3)
    assert rows[0][:2] == ("Item", "Qty")
    assert rows[1][:2] == ("A", 1)


def test_dry_run_does_not_create_missing_workbook(tmp_path):
    path = tmp_path / "belum-ada.xlsx"

    result = documents.update_excel_sheet(
        str(path),
        "Baru",
        headers=["A"],
        rows_json='[["isi"]]',
        dry_run=True,
    )

    assert result["status"] == "preview"
    assert result["diff"]["action"] == "create_sheet"
    assert result["diff"]["file_exists"] is False
    assert not path.exists()


def test_dry_run_replace_reports_replaced_sheet(tmp_path):
    path = _make_workbook(
        tmp_path / "rekap.xlsx", sheet="S", rows=(("lama", 1),)
    )
    result = documents.update_excel_sheet(
        str(path), "S", headers=["Baru"], rows_json='[["isi"]]', dry_run=True
    )

    assert result["status"] == "preview"
    assert result["diff"]["action"] == "replace_sheet"
    assert result["diff"]["sheet_existed"] is True
    assert result["diff"]["headers_before"] == ["lama", 1]
    assert result["diff"]["headers_after"] == ["Baru"]


def test_keep_backup_then_restore_excel_backup(tmp_path):
    path = _make_workbook(tmp_path / "rekap.xlsx", sheet="S", rows=(("lama",),))
    updated = documents.update_excel_sheet(
        str(path),
        "S",
        headers=["Baru"],
        rows_json='[["baru"]]',
        keep_backup=True,
    )

    assert updated["status"] == "success"
    backup = updated["backup_path"]
    assert backup and Path(backup).exists()
    assert _sheet_rows(path, "S", max_row=2)[1][0] == "baru"

    restored = documents.restore_excel_backup(str(path), backup)

    assert restored["status"] == "success"
    assert restored["verified"] is True
    rows = _sheet_rows(path, "S", max_row=2)
    assert rows[0][0] == "lama"


def test_default_write_deletes_backup(tmp_path):
    path = _make_workbook(tmp_path / "rekap.xlsx", sheet="S", rows=(("lama",),))
    result = documents.update_excel_sheet(
        str(path), "S", headers=["Baru"], rows_json='[["baru"]]'
    )

    assert result["status"] == "success"
    assert "backup_path" not in result
    assert list(tmp_path.glob(".rekap.xlsx.bak-*")) == []


def test_restore_rejects_untrusted_backup(tmp_path):
    path = _make_workbook(tmp_path / "rekap.xlsx")
    other = tmp_path / "lain.xlsx"
    other.write_bytes(path.read_bytes())

    result = documents.restore_excel_backup(str(path), str(other))

    assert result["status"] == "error"
    assert "tidak valid" in result["message"]


def test_restore_without_backup_returns_error(tmp_path):
    path = _make_workbook(tmp_path / "rekap.xlsx")

    result = documents.restore_excel_backup(str(path))

    assert result["status"] == "error"
    assert "Tidak ada backup" in result["message"]
