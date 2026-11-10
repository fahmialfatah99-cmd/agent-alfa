"""Normalizer tata letak Master Ledger Rekap Material (Excel).

Latar belakang: berkas Master Rekap Cluster (Curup / Lahat / lainnya) bisa
teracak setelah pemilik menyisipkan baris "pembatas" atau merge sel manual
langsung di Excel — alamat sel bergeser sehingga update Agent berikutnya
menghasilkan baris yatim, label kehilangan teks, dan merge tumpang tindih.

Tool ini menyusun ulang tata letak sheet dari DATA di dalam berkas itu
sendiri (tanpa menebak dokumen luar), dengan struktur kanonik generator
``reconcile_whatsapp_material_group``:

Sheet "Rekap Material"    : judul → tabel tiang → TOTAL(=SUM) → catatan →
                            A. rekap per mandor (SUMIFS ambil/retur/net) →
                            B. rekap per jenis tiang (SUMIFS + total kolom).
Sheet "Kabel & Aksesoris" : judul → tabel → RINGKASAN KABEL (SUMIFS per
                            mandor + TOTAL) → RINGKASAN AKSESORIS (SUMIFS
                            per kode item).

Prinsip keamanan data (Zero Regression):
* Record beridentitas lengkap dipertahankan 100% — tidak ada data hilang.
* Record yatim (tanggal/mandor/kode kosong — sisa pembatas manual) tidak
  ikut dihitung; isinya dilaporkan pada baris catatan untuk dikonfirmasi.
* Berkas di-backup dulu ke ``.excel_backups/`` sebelum ditulis; bila hasil
  gagal di-verifikasi muat ulang, berkas dipulihkan dari backup.
* Bila struktur sudah rapi → no-op idempoten.
"""

from __future__ import annotations

import datetime as _dt
import logging
import os
import shutil
from copy import copy
from typing import Any

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

from alfa.tools.registry import register_tool

logger = logging.getLogger("alfa.rekap_layout")

REKAP_SHEET = "Rekap Material"
KABEL_SHEET = "Kabel & Aksesoris"

_NOTE_FONT = Font(italic=True, size=9, color="666666")
_THIN = Side(style="thin", color="808080")
_BORDER = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)

# Fallback style bila panen style kosong (berkas tanpa format sama sekali).
_FT_TITLE = Font(bold=True, size=14)
_FT_SUB = Font(italic=True, size=10, color="444444")
_FT_HDR = Font(bold=True, color="FFFFFF", size=10)
_DATA_FONT = Font(size=10)
_FT_SEC = Font(bold=True, size=11, color="1F4E79")
_FT_TOT = Font(bold=True, size=10)
_FILL_HDR = PatternFill("solid", fgColor="2F5597")
_FILL_TOT = PatternFill("solid", fgColor="C6E0B4")
_AL_WRAP = Alignment(horizontal="center", vertical="center", wrap_text=True)


class _Band:
    """Template style sel (font/fill/border/alignment/number_format)."""

    __slots__ = ("font", "fill", "border", "alignment", "number_format")

    def __init__(
        self,
        font: Any = None,
        fill: Any = None,
        alignment: Any = None,
        border: Any = None,
        number_format: str = "General",
    ) -> None:
        self.font = font if font is not None else Font()
        self.fill = fill if fill is not None else PatternFill()
        self.border = border if border is not None else _BORDER
        self.alignment = alignment if alignment is not None else _AL_WRAP
        self.number_format = number_format

    @classmethod
    def harvest(cls, cell: Any) -> _Band:
        return cls(
            font=copy(cell.font),
            fill=copy(cell.fill),
            alignment=copy(cell.alignment),
            border=copy(cell.border),
            number_format=cell.number_format or "General",
        )

    def apply(self, target: Any) -> None:
        target.font = self.font
        target.fill = self.fill
        target.border = self.border
        target.alignment = self.alignment
        target.number_format = self.number_format


def _norm(value: Any) -> str:
    """Sel teks/tanggal dinormalkan ke string dd-mm-yyyy yang konsisten."""
    if isinstance(value, _dt.datetime):
        return value.strftime("%d-%m-%Y")
    if isinstance(value, _dt.date):
        return value.strftime("%d-%m-%Y")
    return str(value).strip() if value is not None else ""


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _letters(n: int) -> list[str]:
    return [chr(ord("A") + i) for i in range(n)]


def _header_row(family: str) -> int:
    return 5 if family == REKAP_SHEET else 4


# ═════════════════════════════ 1. PANEN ═════════════════════════════════


def _parse_family(ws: Any, family: str) -> dict[str, Any]:
    """Panen konten sheet: judul/mandor + record (nilai mentah per sel).

    Record = baris dengan kolom A berupa nomor urut int DAN kolom G berisi
    angka (bukan rumus/teks) — baris bagian/ringkasan otomatis terlewat.
    Nilai sel B..akhir disimpan apa adanya: teks dinormalkan ke string,
    angka (kuantitas) disimpan numerik agar rumus SUM tetap menghitung.
    """
    ncols = 7 if family == REKAP_SHEET else 8
    hdr = _header_row(family)
    dr0 = hdr + 1
    qcol = 7  # kolom G = kuantitas untuk kedua keluarga sheet

    parsed: dict[str, Any] = {
        "title": _norm(ws["A1"].value),
        "sub": _norm(ws["A2"].value),
        "mandors_line": _norm(ws["A3"].value) if family == REKAP_SHEET else "",
        "records": [],
        "widths": {col: ws.column_dimensions[col].width for col in _letters(ncols)},
        "ncols": ncols,
        "header_row": hdr,
        "dr0": dr0,
    }

    for r in range(dr0, (ws.max_row or 1) + 1):
        no_val = ws.cell(r, 1).value
        if not isinstance(no_val, int) or isinstance(no_val, bool):
            continue
        qty = ws.cell(r, qcol).value
        if not _is_number(qty):
            continue
        cells: list[Any] = []
        for c in range(2, ncols + 1):  # B .. kolom terakhir
            v = ws.cell(r, c).value
            cells.append(v if _is_number(v) else _norm(v))
        rec: dict[str, Any] = {"row": r, "no": no_val, "qty": qty, "cells": cells}
        # identitas wajib: B tanggal, C mandor, E kode item (indeks cells 0/1/3)
        rec["orphan"] = any(not c for c in (cells[0], cells[1], cells[3]))
        parsed["records"].append(rec)
    return parsed


# ═════════════════════════ 2. DETEKSI ANOMALI ═══════════════════════════


def detect_anomalies(ws: Any, family: str) -> list[str]:
    """Daftar anomali tata letak; kosong berarti sheet sudah rapi."""
    issues: list[str] = []
    data = _parse_family(ws, family)
    records = data["records"]
    good = [r for r in records if not r["orphan"]]
    orphans = [r for r in records if r["orphan"]]

    if orphans:
        issues.append(f"{len(orphans)} baris record tanpa identitas (yatim)")

    all_rows = [r["row"] for r in records]
    if all_rows and all_rows != list(range(all_rows[0], all_rows[-1] + 1)):
        issues.append("baris record tidak kontinu (ada baris menyela di zona data)")

    rows_idx = [r["row"] for r in good]

    if rows_idx:
        for rng in ws.merged_cells.ranges:
            if rng.min_row >= rows_idx[0] and rng.max_row <= rows_idx[-1]:
                issues.append("merge sel menembus zona data")
                break

    if family == REKAP_SHEET and good:
        end_scan = records[-1]["row"] + 1 if records else 1
        total = next(
            (
                ws.cell(rr, 7).value
                for rr in range(end_scan, (ws.max_row or 1) + 1)
                if isinstance(ws.cell(rr, 7).value, str)
                and str(ws.cell(rr, 7).value).startswith("=SUM(")
            ),
            None,
        )
        expect = f"=SUM(G{rows_idx[0]}:G{rows_idx[-1]})"
        if total != expect:
            issues.append(f"rumus TOTAL tabel utama {total!r}, seharusnya {expect!r}")
    elif family == KABEL_SHEET and good and not any(
        isinstance(ws.cell(rr, 3).value, str)
        and str(ws.cell(rr, 3).value).startswith("=SUM(C")
        for rr in range((records[-1]["row"] + 1) if records else 1, (ws.max_row or 1) + 1)
    ):
        issues.append("ringkasan kabel (rumus SUM) tidak ditemukan")

    # Baris bagian/segment: A int + rumus di C..F tapi label B kosong
    for rr in range(1, (ws.max_row or 1) + 1):
        a = ws.cell(rr, 1).value
        if not isinstance(a, int) or isinstance(a, bool):
            continue
        b = _norm(ws.cell(rr, 2).value)
        c_any = any(
            _is_number(ws.cell(rr, cc).value)
            or (isinstance(ws.cell(rr, cc).value, str)
                and str(ws.cell(rr, cc).value).startswith("="))
            for cc in range(3, 7)
        )
        if not b and c_any:
            issues.append(f"baris {rr}: label (kolom B) kosong padahal ada rumus")
            break
    return issues


# ═══════════════════════ 3. SUSUN ULANG SHEET ═══════════════════════════


def _paint(ws: Any, coord: str, value: Any, band: _Band, merge: str = "") -> None:
    if merge:
        ws.merge_cells(merge)
    ws[coord] = value
    band.apply(ws[coord])
    ws[coord].border = _BORDER


def _first_total_row(ws: Any, family: str) -> int | None:
    for rr in range(1, (ws.max_row or 1) + 1):
        v = ws.cell(rr, 7).value
        if isinstance(v, str) and v.startswith("=SUM("):
            return rr
        if family == KABEL_SHEET:
            vc = ws.cell(rr, 3).value
            if isinstance(vc, str) and vc.startswith("=SUM("):
                return rr
    return None


def _harvest_bands(ws: Any, family: str) -> dict[str, _Band]:
    """Panen style sel representatif per zona agar hasil identik visualnya."""
    bands: dict[str, _Band] = {}
    try:
        hdr = _header_row(family)
        dr0 = hdr + 1
        total_row = _first_total_row(ws, family)
        for rr in range(1, (ws.max_row or 1) + 1):
            txt = _norm(ws.cell(rr, 1).value).upper()
            if txt.startswith("RINGKASAN PENGAMBILAN KABEL") and "rk_lbl" not in bands:
                bands["rk_lbl"] = _Band.harvest(ws.cell(rr, 1))
                bands["rk_hdr"] = _Band.harvest(ws.cell(rr + 1, 1))
                if _is_number(ws.cell(rr + 2, 1).value) or isinstance(
                    ws.cell(rr + 2, 1).value, int
                ):
                    bands["rk_data"] = _Band.harvest(ws.cell(rr + 2, 1))
            elif txt.startswith("RINGKASAN PENGAMBILAN AKSESORIS") and "acc_lbl" not in bands:
                bands["acc_lbl"] = _Band.harvest(ws.cell(rr, 1))
                bands["acc_hdr"] = _Band.harvest(ws.cell(rr + 1, 1))
                if isinstance(ws.cell(rr + 2, 1).value, int):
                    bands["acc_data"] = _Band.harvest(ws.cell(rr + 2, 1))
            elif "REKAPITULASI PER MANDOR" in txt and "sec" not in bands:
                bands["sec"] = _Band.harvest(ws.cell(rr, 1))
            elif "REKAPITULASI PER JENIS" in txt and "secb" not in bands:
                bands["secb"] = _Band.harvest(ws.cell(rr, 1))
        picks: dict[str, Any] = {
            "title": ws["A1"],
            "sub": ws["A2"],
            "hdr": ws.cell(hdr, 1),
            "data": ws.cell(dr0, 1),
            "qty": ws.cell(dr0, 7),
            "total": ws.cell(total_row, 1) if total_row else None,
        }
        for key, cell in picks.items():
            if cell is not None and key not in bands:
                bands[key] = _Band.harvest(cell)
    except (AttributeError, IndexError, KeyError):
        pass
    for key in (
        "title", "sub", "hdr", "data", "qty", "total", "sec", "secb",
        "rk_lbl", "rk_hdr", "rk_data", "acc_lbl", "acc_hdr", "acc_data",
    ):
        bands.setdefault(key, _Band())
    return bands


def _rebuild(wb: Any, name: str, policy: str) -> dict[str, Any]:
    ws = wb[name]
    parsed = _parse_family(ws, name)
    bands = _harvest_bands(ws, name)
    widths = parsed["widths"]
    idx = wb.sheetnames.index(name)
    wb.remove(ws)
    ws2 = wb.create_sheet(name, idx)
    return _paint_canonical(ws2, name, parsed, bands, widths, policy)


def _paint_canonical(
    ws: Any,
    family: str,
    parsed: dict[str, Any],
    bands: dict[str, _Band],
    widths: dict[str, Any],
    policy: str,
) -> dict[str, Any]:
    """Tulis ulang sheet sesuai struktur kanonik generator Master Ledger."""
    ncols = parsed["ncols"]
    letters = _letters(ncols)
    last = letters[-1]
    hdr_row = parsed["header_row"]
    dr0 = hdr_row + 1

    title = parsed.get("title") or "REKAPITULASI RESMI PENGAMBILAN MATERIAL"
    sub = parsed.get("sub") or "Sumber: Grup WhatsApp"
    title_b, sub_b = bands["title"], bands["sub"]
    hdr_b, data_b, qty_b, tot_b = bands["hdr"], bands["data"], bands["qty"], bands["total"]
    sec_b, secb_b = bands["sec"], bands["secb"]
    rk_lbl_b, rk_hdr_b = bands["rk_lbl"], bands["rk_hdr"]
    acc_lbl_b, acc_hdr_b = bands["acc_lbl"], bands["acc_hdr"]

    ws.merge_cells(f"A1:{last}1")
    _paint(ws, "A1", title, title_b)
    ws.merge_cells(f"A2:{last}2")
    _paint(ws, "A2", sub, sub_b)
    if family == REKAP_SHEET:
        ws.merge_cells("A3:G3")
        _paint(ws, "A3", parsed["mandors_line"] or "Mandor Pelapor Terverifikasi", sub_b)
    # Sheet kabel: baris 3 sengaja kosong agar header tetap di baris 4

    headers_rekap = [
        "No", "Tanggal", "Mandor Lapangan", "Status / Tipe", "Kode Item",
        "Spesifikasi Material", "Jumlah (Batang)",
    ]
    headers_ka = [
        "No", "Tanggal", "Mandor Lapangan", "Kategori", "Kode Item",
        "Spesifikasi Material", "Jumlah", "Satuan",
    ]
    for i, h in enumerate(headers_rekap if family == REKAP_SHEET else headers_ka, 1):
        _paint(ws, f"{letters[i - 1]}{hdr_row}", h, hdr_b)

    valid = [rec for rec in parsed["records"] if not rec["orphan"]]
    orphans = [rec for rec in parsed["records"] if rec["orphan"]]
    kept = valid if policy == "exclude" else valid + orphans

    for j, rec in enumerate(kept):
        row = dr0 + j
        ws.cell(row, 1, j + 1)
        for i, v in enumerate(rec["cells"], 2):
            ws.cell(row, i, v)
        for c in range(1, ncols + 1):
            cell_d = ws.cell(row, c)
            (qty_b if c == 7 else data_b).apply(cell_d)
    rvn = dr0 + len(kept) - 1

    # ── Baris TOTAL tabel utama ──────────────────────────────────────────
    tr = rvn + 1
    label_total = (
        "TOTAL AKUMULASI BERSIH (NET) PENGAMBILAN TIANG"
        if family == REKAP_SHEET
        else "TOTAL REKAPITULASI KABEL & AKSESORIS"
    )
    _paint(ws, f"A{tr}", label_total, tot_b, merge=f"A{tr}:F{tr}")
    _paint(ws, f"G{tr}", f"=SUM(G{dr0}:G{rvn})", tot_b)

    note_r = tr + 1
    if orphans:
        det = "; ".join(f"qty {rec['qty']} (semula baris {rec['row']})" for rec in orphans)
        _paint(
            ws, f"A{note_r}",
            "Catatan: baris tanpa identitas dari berkas lama tidak ikut dihitung "
            f"({det}). Konfirmasi via bot bila itu retur/ambil sebenarnya.",
            _Band(font=_NOTE_FONT, border=_BORDER),
            merge=f"A{note_r}:{last}{note_r}",
        )
        note_r += 1

    gsum = f"$G${dr0}:$G${rvn}"
    csum = f"$C${dr0}:$C${rvn}"
    dsum = f"$D${dr0}:$D${rvn}"
    esum = f"$E${dr0}:$E${rvn}"

    mandors: list[str] = []
    items: list[tuple[str, str]] = []
    for rec in valid:
        mm = rec["cells"][1]
        if mm and mm not in mandors:
            mandors.append(mm)
        code, spec = rec["cells"][3], rec["cells"][4]
        if code and (code,) not in [(it[0],) for it in items]:
            items.append((code, spec))

    result: dict[str, Any] = {"kept": len(kept), "orphans": len(orphans)}

    if family == REKAP_SHEET:
        # ── A. Rekap per mandor ──────────────────────────────────────────
        ra = note_r + 1
        _paint(ws, f"A{ra}", "A. REKAPITULASI PER MANDOR", sec_b, merge=f"A{ra}:G{ra}")
        hdr_a = ra + 1
        for i, h in enumerate(
            ["No", "Nama Mandor", "Total Ambil", "Total Retur", "Total Bersih (Net)"], 1
        ):
            _paint(ws, f"{letters[i - 1]}{hdr_a}", h, hdr_b)
        for k, mm in enumerate(mandors):
            row = hdr_a + 1 + k
            ws.cell(row, 1, k + 1)
            ws.cell(row, 2, mm)
            ws.cell(row, 3, f'=SUMIFS({gsum},{csum},"{mm}")')
            ws.cell(row, 4, f'=-SUMIFS({gsum},{csum},"{mm}",{gsum},"<0")')
            ws.cell(row, 5, f"=C{row}-D{row}")
            for c in range(1, 6):
                (qty_b if c >= 3 else data_b).apply(ws.cell(row, c))
        ra_end = hdr_a + len(mandors)
        rt = ra_end + 1
        for col in ("C", "D", "E"):
            _paint(ws, f"{col}{rt}", f"=SUM({col}{hdr_a + 1}:{col}{ra_end})", tot_b)
        _paint(ws, f"A{rt}", "TOTAL GABUNGAN MANDOR", tot_b, merge=f"A{rt}:B{rt}")
        result["section_a"] = {"mandors": mandors, "total_row": rt}

        # ── B. Rekap per jenis tiang ─────────────────────────────────────
        rb = rt + 2
        _paint(ws, f"A{rb}", "B. REKAPITULASI PER JENIS TIANG", secb_b, merge=f"A{rb}:G{rb}")
        hdr_b_row = rb + 1
        head_b = ["No", "Kode Item", "Spesifikasi Tiang"]
        head_b += [f"{mm} (Net)" for mm in mandors] + ["Total Akhir (Net)"]
        for i, h in enumerate(head_b, 1):
            _paint(ws, f"{letters[i - 1]}{hdr_b_row}", h, hdr_b)
        for k, (code, spec) in enumerate(items):
            row = hdr_b_row + 1 + k
            ws.cell(row, 1, k + 1)
            ws.cell(row, 2, code)
            ws.cell(row, 3, spec)
            for i, mm in enumerate(mandors):
                ws.cell(row, 4 + i, f'=SUMIFS({gsum},{csum},"{mm}",{esum},"{code}")')
            last_mcol = chr(ord("D") + max(len(mandors) - 1, 0))
            ws.cell(row, 4 + len(mandors), f"=SUM(D{row}:{last_mcol}{row})")
            for c in range(1, 4 + len(mandors) + 1):
                data_b.apply(ws.cell(row, c))
        rb_end = hdr_b_row + len(items)
        rtb = rb_end + 1
        _paint(ws, f"A{rtb}", "TOTAL KESELURUHAN TIANG (NET)", tot_b, merge=f"A{rtb}:C{rtb}")
        for c in range(4, 4 + len(mandors) + 1):
            col = letters[c - 1]
            _paint(ws, f"{col}{rtb}", f"=SUM({col}{hdr_b_row + 1}:{col}{rb_end})", tot_b)
        result["section_b"] = {"items": [it[0] for it in items], "total_row": rtb}
    else:
        # ── Ringkasan kabel udara ────────────────────────────────────────
        rk = note_r + 1
        _paint(
            ws, f"A{rk}", "RINGKASAN PENGAMBILAN KABEL UDARA (Kabel 24)",
            rk_lbl_b, merge=f"A{rk}:C{rk}",
        )
        hdr_k = rk + 1
        for i, h in enumerate(["No", "Nama Mandor", "Total Kabel (Meter)"], 1):
            _paint(ws, f"{letters[i - 1]}{hdr_k}", h, rk_hdr_b)
        kmandors: list[str] = []
        for rec in valid:
            if rec["cells"][2] == "KABEL" and rec["cells"][1] not in kmandors:
                kmandors.append(rec["cells"][1])
        for k, mm in enumerate(kmandors):
            row = hdr_k + 1 + k
            ws.cell(row, 1, k + 1)
            ws.cell(row, 2, mm)
            ws.cell(row, 3, f'=SUMIFS({gsum},{csum},"{mm}",{dsum},"KABEL")')
            for c in range(1, 4):
                (qty_b if c == 3 else data_b).apply(ws.cell(row, c))
        rk_end = hdr_k + len(kmandors)
        kt = rk_end + 1
        _paint(ws, f"A{kt}", "TOTAL KABEL UDARA", tot_b, merge=f"A{kt}:B{kt}")
        _paint(ws, f"C{kt}", f"=SUM(C{hdr_k + 1}:C{rk_end})", tot_b)
        result["ringkasan_kabel"] = {"mandors": kmandors, "total_row": kt}

        # ── Ringkasan aksesoris FTTH ─────────────────────────────────────
        acc = kt + 2
        _paint(
            ws, f"A{acc}", "RINGKASAN PENGAMBILAN AKSESORIS FTTH",
            acc_lbl_b, merge=f"A{acc}:E{acc}",
        )
        hdr_acc = acc + 1
        for i, h in enumerate(
            ["No", "Kode Aksesoris", "Nama Material", "Total Diambil", "Satuan"], 1
        ):
            _paint(ws, f"{letters[i - 1]}{hdr_acc}", h, acc_hdr_b)
        accs: list[tuple[str, str, str]] = []
        seen: set[str] = set()
        for rec in valid:
            if rec["cells"][2] == "AKSESORIS":
                code, spec, unit = rec["cells"][3], rec["cells"][4], rec["cells"][6]
                if code and code not in seen:
                    seen.add(code)
                    accs.append((code, spec, unit))
        accs.sort(key=lambda x: x[0])
        for k, (code, spec, unit) in enumerate(accs):
            row = hdr_acc + 1 + k
            ws.cell(row, 1, k + 1)
            ws.cell(row, 2, code)
            ws.cell(row, 3, spec)
            ws.cell(row, 4, f'=SUMIFS({gsum},{dsum},"AKSESORIS",{esum},"{code}")')
            ws.cell(row, 5, unit)
            for c in range(1, 6):
                (qty_b if c == 4 else data_b).apply(ws.cell(row, c))
        result["ringkasan_aksesoris"] = {"codes": [a[0] for a in accs]}

    for col in letters:
        w = widths.get(col)
        ws.column_dimensions[col].width = w if isinstance(w, (int, float)) and w else 14
    return result


# ═══════════════════════════ 4. ENTRYPOINT ══════════════════════════════


@register_tool(
    category="office",
    description=(
        "Rapikan tata letak file Master Rekap Material (Excel) yang teracak "
        "akibat penyisipan pembatas manual - menyusun ulang sheet dari data "
        "di dalam berkas itu sendiri tanpa kehilangan record valid."
    ),
    tags=["excel", "rekap", "material", "layout", "openpyxl"],
)
def tidy_rekap_excel(
    xlsx_path: str = "",
    backup: bool = True,
    orphan_policy: str = "exclude",
) -> dict[str, Any]:
    """Rapikan tata letak file Master Rekap Material (Excel) in-place.

    Menyusun ulang sheet ``Rekap Material`` dan ``Kabel & Aksesoris`` dari
    data di dalam berkas itu sendiri. Record beridentitas dipertahankan 100%;
    baris tanpa identitas (sisa pembatas manual) dikecualikan dari TOTAL dan
    dilaporkan pada baris catatan. Sheet yang sudah rapi dibiarkan apa adanya.

    Args:
        xlsx_path: path berkas master rekap, mis. ``~/alfa_projects/
            lahat_material/Rekap_Pengambilan_Material_Lahat.xlsx``.
        backup: salin dulu ke ``<dir>/.excel_backups/<stamp>__<file>``.
        orphan_policy: ``exclude`` (default — baris yatim hanya dilaporkan)
            atau ``keep`` — baris yatim tetap di tabel dengan identitas kosong.

    Returns:
        dict: status, changed, sheets, orphans, backup, message.
    """
    if not xlsx_path:
        return {
            "status": "error",
            "message": "Parameter 'xlsx_path' wajib diisi (path berkas Rekap xlsx).",
        }
    if orphan_policy not in ("exclude", "keep"):
        return {
            "status": "error",
            "message": "orphan_policy hanya boleh 'exclude' atau 'keep'.",
        }

    path = os.path.abspath(os.path.expanduser(xlsx_path))
    if not os.path.exists(path):
        return {"status": "error", "message": f"Berkas tidak ditemukan: {path}"}

    try:
        wb = openpyxl.load_workbook(path)
    except (OSError, ValueError) as exc:
        return {"status": "error", "message": f"Gagal membuka workbook: {exc}"}

    present = [n for n in (REKAP_SHEET, KABEL_SHEET) if n in wb.sheetnames]
    if not present:
        return {
            "status": "error",
            "message": f"Sheet {REKAP_SHEET!r}/{KABEL_SHEET!r} tidak ditemukan. "
            f"Sheet tersedia: {wb.sheetnames}",
        }

    plan = {n: detect_anomalies(wb[n], n) for n in present}
    if all(not issues for issues in plan.values()):
        return {
            "status": "success",
            "changed": False,
            "message": "Tata letak sudah rapi — tidak ada perubahan.",
            "sheets": {n: "already_tidy" for n in present},
        }

    backup_path = ""
    if backup:
        stamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        bdir = os.path.join(os.path.dirname(path), ".excel_backups")
        os.makedirs(bdir, exist_ok=True)
        backup_path = os.path.join(bdir, f"{stamp}__{os.path.basename(path)}")
        try:
            shutil.copy2(path, backup_path)
        except OSError as exc:
            return {"status": "error", "message": f"Backup gagal, penataan dibatalkan: {exc}"}

    sheets_report: dict[str, Any] = {}
    orphans_report: dict[str, int] = {}
    try:
        for n in present:
            if plan[n]:
                rep = _rebuild(wb, n, orphan_policy)
                sheets_report[n] = rep
                orphans_report[n] = rep.get("orphans", 0)
        wb.save(path)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        if backup_path and os.path.exists(backup_path):
            shutil.copy2(backup_path, path)
            logger.exception("Penataan gagal — berkas dipulihkan dari backup %s", backup_path)
        return {
            "status": "error",
            "message": f"Penataan gagal (berkas dipulihkan dari backup): {exc}",
            "backup": backup_path,
        }

    try:
        _wb_check = openpyxl.load_workbook(path)
        for n in present:
            _wb_check[n].calculate_dimension()
    except (OSError, ValueError) as exc:
        if backup_path and os.path.exists(backup_path):
            shutil.copy2(backup_path, path)
        return {
            "status": "error",
            "message": f"Hasil berkas tidak valid (dipulihkan dari backup): {exc}",
        }

    message = "Tata letak Rekap Material disusun ulang dari datanya sendiri. "
    if any(orphans_report.get(n) for n in present):
        message += (
            "Sebagian baris tanpa identitas tidak ikut dihitung — "
            "konfirmasi via bot bila itu retur sebenarnya."
        )
    return {
        "status": "success",
        "changed": True,
        "sheets": sheets_report,
        "orphans": orphans_report,
        "backup": backup_path,
        "message": message,
    }
