"""Test normalizer tata letak Master Rekap Material (alfa.tools.rekap_layout).

Fixture menirukan kerusakan nyata kasus Lahat 30-10-2026: penyisipan
"pembatas" manual (merge sel + baris yatim) membuat update agent berikutnya
menghasilkan rumus TOTAL salah jangkauan dan label bagian hilang.
"""

from __future__ import annotations

import os

import openpyxl

from alfa.core.perm.constants import TOOL_CLASSIFICATION, RiskTier
from alfa.tools.registry import AVAILABLE_TOOLS, TOOL_DOMAINS, TOOL_REGISTRY
from alfa.tools.rekap_layout import (
    KABEL_SHEET,
    REKAP_SHEET,
    detect_anomalies,
    tidy_rekap_excel,
)

QA = "Mandor Aqe Setiawan"
QM = "Mandor Mugi"

REKAP_RECORDS = [
    ("17-10-2026", QM, "TIANG BARU", "T73", "Tiang T73 Otomatis", 5),
    ("18-10-2026", QM, "TIANG BARU", "T73", "Tiang T73 Otomatis", 3),
    ("19-10-2026", QA, "TIANG GANTI", "T72", "Tiang T72 Otomatis", -1),
    ("20-10-2026", QA, "TIANG BARU", "T72", "Tiang T72 Otomatis", 2),
]


def _build_broken_workbook(path: str) -> None:
    """Buat workbook rusak: baris yatim, merge menembus tabel, label hilang."""
    wb = openpyxl.Workbook()

    # ── Sheet Rekap Material (rusak) ──────────────────────────────────────
    ws = wb.active
    ws.title = REKAP_SHEET
    ws["A1"] = "REKAPITULASI RESMI PENGAMBILAN MATERIAL"
    ws["A2"] = "Sumber: Grup WhatsApp — per 30-10-2026 17:00 WIB"
    ws["A3"] = "Mandor Pelapor Terverifikasi: Mandor Mugi, Mandor Aqe Setiawan"
    headers = ["No", "Tanggal", "Mandor", "Status", "Kode", "Spesifikasi", "Jumlah"]
    for i, h in enumerate(headers, 1):
        ws.cell(5, i, h)
    for j, rec in enumerate(REKAP_RECORDS):
        r = 6 + j
        ws.cell(r, 1, j + 1)
        for i, v in enumerate(rec, 2):
            ws.cell(r, i, v)
    # Pembatas manual: merge + baris yatim (A int + qty -3, tanpa identitas)
    ws.merge_cells("A10:C10")
    ws.cell(10, 1, 5)
    ws.cell(10, 7, -3)
    # Rumus TOTAL salah jangkauan ikut menyangkau baris yatim
    ws.merge_cells("A11:F11")
    ws.cell(11, 1, "TOTAL AKUMULASI BERSIH (NET) PENGAMBILAN TIANG")
    ws.cell(11, 7, "=SUM(G6:G10)")
    # Bagian A: baris kedua kehilangan label (B kosong)
    ws.merge_cells("A13:G13")
    ws.cell(13, 1, "A. REKAPITULASI PER MANDOR")
    for i, h in enumerate(
        ["No", "Nama Mandor", "Total Ambil", "Total Retur", "Total Bersih (Net)"], 1
    ):
        ws.cell(14, i, h)
    ws.cell(15, 1, 1)
    ws.cell(15, 2, QM)
    ws.cell(15, 3, '=SUMIFS($G$6:$G$9,$C$6:$C$9,"Mandor Mugi")')
    ws.cell(16, 1, 2)
    ws.cell(16, 2, None)  # label hilang
    ws.cell(16, 3, '=SUMIFS($G$6:$G$9,$C$6:$C$9,"Mandor Aqe Setiawan")')
    # Bagian B
    ws.merge_cells("A18:G18")
    ws.cell(18, 1, "B. REKAPITULASI PER JENIS TIANG")
    for i, h in enumerate(["No", "Kode Item", "Spesifikasi", "Total Net"], 1):
        ws.cell(19, i, h)
    ws.cell(20, 1, 1)
    ws.cell(20, 2, "T73")

    # ── Sheet Kabel & Aksesoris (rusak) ──────────────────────────────────
    wk = wb.create_sheet(KABEL_SHEET)
    wk["A1"] = "REKAPITULASI PENGAMBILAN KABEL & AKSESORIS"
    wk["A2"] = "Sumber: Grup WhatsApp — per 30-10-2026 17:00 WIB"
    headers_k = ["No", "Tanggal", "Mandor", "Kategori", "Kode", "Spesifikasi", "Jumlah", "Satuan"]
    for i, h in enumerate(headers_k, 1):
        wk.cell(4, i, h)
    wk.cell(5, 1, 1)
    for i, v in enumerate(("17-10-2026", QM, "KABEL", "Kabel 24", "ADSS 24 Core", 500, "Meter"), 2):
        wk.cell(5, i, v)
    wk.cell(6, 1, 2)
    for i, v in enumerate(("18-10-2026", QA, "AKSESORIS", "STOPING", "Dead End Clamp", 3, "Pcs"), 2):
        wk.cell(6, i, v)
    # Baris menyela (blank) + baris yatim hasil geser merge
    wk.merge_cells("A8:C8")
    wk.cell(8, 1, 3)
    wk.cell(8, 7, -3)
    wk.cell(8, 8, "Meter")

    wb.save(path)


def test_broken_layout_rebuilt_and_data_preserved(tmp_path):
    path = str(tmp_path / "Rekap_Pengambilan_Material_Test.xlsx")
    _build_broken_workbook(path)

    # Pra-kondisi: kedua sheet terdeteksi bermasalah
    wb0 = openpyxl.load_workbook(path)
    issues_rekap = detect_anomalies(wb0[REKAP_SHEET], REKAP_SHEET)
    issues_kabel = detect_anomalies(wb0[KABEL_SHEET], KABEL_SHEET)
    assert any("yatim" in i for i in issues_rekap)
    assert any("TOTAL" in i for i in issues_rekap)
    assert any("yatim" in i for i in issues_kabel)
    assert any("tidak kontinu" in i for i in issues_kabel)

    result = tidy_rekap_excel(path)
    assert result["status"] == "success", result
    assert result["changed"] is True
    assert result["orphans"][REKAP_SHEET] == 1
    assert result["orphans"][KABEL_SHEET] == 1
    assert result["backup"] and os.path.exists(result["backup"])

    wb = openpyxl.load_workbook(path)
    ws = wb[REKAP_SHEET]

    # Record valid utuh 100% + penomoran ulang kontinu
    assert [ws.cell(r, 1).value for r in range(6, 10)] == [1, 2, 3, 4]
    assert [ws.cell(r, 7).value for r in range(6, 10)] == [5, 3, -1, 2]
    assert ws.cell(6, 2).value == "17-10-2026"
    assert ws.cell(9, 3).value == QA

    # Rumus TOTAL jangkauannya kini pas (baris yatim dikecualikan)
    assert ws.cell(10, 7).value == "=SUM(G6:G9)"
    assert "Catatan" in str(ws.cell(11, 1).value) and "-3" in str(ws.cell(11, 1).value)

    # Bagian A dirapikan: label tidak hilang, SUMIFS dinamis (ambil/retur/net)
    assert ws.cell(15, 2).value == QM
    assert ws.cell(16, 2).value == QA
    assert ws.cell(15, 3).value == f'=SUMIFS($G$6:$G$9,$C$6:$C$9,"{QM}")'
    assert ws.cell(15, 4).value == f'=-SUMIFS($G$6:$G$9,$C$6:$C$9,"{QM}",$G$6:$G$9,"<0")'
    assert ws.cell(15, 5).value == "=C15-D15"

    # Bagian B per jenis tiang terisi label kode
    sec_b_rows = {}
    for r in range(12, ws.max_row + 1):
        val = ws.cell(r, 1).value
        if isinstance(val, str) and "REKAPITULASI PER JENIS" in val:
            sec_b_rows = {ws.cell(rr, 2).value for rr in range(r + 2, ws.max_row + 1)}
    assert {"T73", "T72"} <= (sec_b_rows or set())

    wk = wb[KABEL_SHEET]
    # Record kabel/aksesoris kontinu, tanpa baris menyela/yatim
    assert [wk.cell(r, 1).value for r in range(5, 7)] == [1, 2]
    assert wk.cell(5, 7).value == 500 and isinstance(wk.cell(5, 7).value, (int, float))
    assert wk.cell(6, 8).value == "Pcs"
    # Ringkasan kabel & aksesoris memakai SUMIFS dengan kolom kriteria benar
    flat = [str(wk.cell(r, c).value) for r in range(1, (wk.max_row or 1) + 1) for c in range(1, 9)]
    kabel_sumifs = [f for f in flat if f.startswith("=SUMIFS") and '"KABEL"' in f]
    aks_sumifs = [f for f in flat if f.startswith("=SUMIFS") and '"AKSESORIS"' in f]
    assert any('$D$5:$D$6,"KABEL"' in f for f in kabel_sumifs)
    assert any('$D$5:$D$6,"AKSESORIS",$E$5:$E$6,"STOPING"' in f for f in aks_sumifs)
    assert "Catatan" in " ".join(flat)


def test_tidy_is_idempotent_after_rebuild(tmp_path):
    path = str(tmp_path / "Rekap_Pengambilan_Material_Test.xlsx")
    _build_broken_workbook(path)
    first = tidy_rekap_excel(path)
    assert first["status"] == "success"

    wb = openpyxl.load_workbook(path)
    assert detect_anomalies(wb[REKAP_SHEET], REKAP_SHEET) == []
    assert detect_anomalies(wb[KABEL_SHEET], KABEL_SHEET) == []

    second = tidy_rekap_excel(path)
    assert second["status"] == "success"
    assert second["changed"] is False
    assert second["sheets"] == {REKAP_SHEET: "already_tidy", KABEL_SHEET: "already_tidy"}


def test_orphan_policy_keep_includes_orphans_in_total(tmp_path):
    path = str(tmp_path / "Rekap_Pengambilan_Material_Test.xlsx")
    _build_broken_workbook(path)
    result = tidy_rekap_excel(path, orphan_policy="keep")
    assert result["status"] == "success"

    wb = openpyxl.load_workbook(path)
    ws = wb[REKAP_SHEET]
    # Yatim tetap di tabel: baris 10 = data yatim, TOTAL pindah ke baris 11
    assert ws.cell(10, 7).value == -3
    assert ws.cell(11, 7).value == "=SUM(G6:G10)"
    rep = result["sheets"][REKAP_SHEET]
    assert rep["kept"] == 5 and rep["orphans"] == 1


def test_invalid_inputs_rejected(tmp_path):
    missing = str(tmp_path / "does_not_exist.xlsx")
    assert tidy_rekap_excel("")["status"] == "error"
    assert tidy_rekap_excel(missing)["status"] == "error"
    assert tidy_rekap_excel(str(tmp_path / "Rekap_Pengambilan_Material_Test.xlsx"),
                            orphan_policy="salah")["status"] == "error"


def test_tool_registered_and_classified():
    from alfa.tools.rekap_layout import (
        tidy_rekap_excel as _fn,  # noqa: F401 — trigger dekorasi
    )

    assert "tidy_rekap_excel" in TOOL_REGISTRY
    names = [getattr(f, "__name__", None) for f in AVAILABLE_TOOLS]
    assert "tidy_rekap_excel" in names
    assert "tidy_rekap_excel" in TOOL_DOMAINS.get("office", [])
    tier, note = TOOL_CLASSIFICATION["tidy_rekap_excel"]
    assert tier == RiskTier.MEDIUM
    assert note
