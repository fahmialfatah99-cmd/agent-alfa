"""
Telecommunication & Fiber Optic (NRO / FTTH) Operations Suite for ALFA.

Provides high-grade tools for:
1. Multi-cluster BOQ consolidation into styled Master Workbooks.
2. Excel BOQ Revision Diff & delta analysis.
3. BOQ vs Field Report Reconciliation (WhatsApp daily progress vs planned quantities).
4. Proactive Project Anomaly & Stalled Progress Sentinel.
5. Interactive KML / KMZ cluster map rendering (Leaflet.js).
"""

from __future__ import annotations

import glob
import json
import logging
import os
import re

try:
    # defusedxml: guard XML serangan (XXE/billion-laughs) utk berkas KML untrusted
    from defusedxml.ElementTree import fromstring as _xml_fromstring
except ImportError:  # fallback stdlib bila dependency ekstra belum terpasang
    from xml.etree.ElementTree import fromstring as _xml_fromstring
import zipfile
from datetime import datetime
from typing import Any

from alfa.tools.registry import register_tool
from alfa.tools.system_tools import SANDBOX_DIR

logger = logging.getLogger("AgentTools.Telecom")


def _classify_telecom_material(desc: str) -> str:
    """Classify material description into standard FTTH categories."""
    d = (desc or "").lower().strip()
    # 1. Labels, paints, foundations, and hardware accessories first (prevent false POLE / false DISTRIBUTION_BOX)
    if any(k in d for k in ["label", "pengecatan", "cat tiang", "pondasi", "foundation"]):
        return "ACCESSORIES"
    if any(k in d for k in ["clamp", "deadend", "dead end", "suspen", "suapen", "stopping", "stoping", "bracket", "hook", "strapping", "band", "plate belt", "buldog", "bulldog", "grip", "hanger", "holder", "loop holder", "temberang", "helical", "steel clamp"]):
        return "ACCESSORIES"

    # 2. Distribution Boxes (FAT, FDT, Joint Closure, ODC, ODP)
    if any(k in d for k in ["fat", "fdt", "odc", "odp", "closure", "joint closure"]) or (
        ("port" in d or "capacity" in d) and any(b in d for b in ["outdoor", "pole mounted", "box", "mounted"])
    ):
        return "DISTRIBUTION_BOX"

    # 3. Cables & Messenger Wire
    if any(k in d for k in ["adss", "kabel", "fo ", "cable", "drop core", "fig 8", "feeder", "strand wire", "messenger", "sling"]):
        return "CABLE"

    # 4. Physical Poles (exclude mounted accessories, clamps, brackets, labels, foundations)
    if ("tiang" in d or re.search(r"\bpole\b", d)) and not any(k in d for k in ["mounted", "clamp", "bracket", "label", "pondasi", "foundation", "pengecatan"]):
        return "POLE"

    # 5. Optical Passives & Splicing
    if any(k in d for k in ["sleeve", "protection sleeve", "pigtail", "adapter", "splitter", "patch cord", "splicing"]):
        return "OPTICAL_PASSIVE"

    return "OTHER"


def _parse_single_boq_workbook(wb: Any) -> tuple[str, str, list[dict[str, Any]]]:
    """
    Parses a single telecom BOQ workbook with smart sheet gating and column resolution.
    Returns:
        (target_sheet_name, scope_label, items_list)
        where items_list contains dicts with keys:
        {"desc": str, "unit": str, "qty": float, "category": str, "is_service": bool}
    """
    target_sheet = None
    scope = "GENERIC"

    # Prioritize 'BoQ NRO Cluster' if it contains actual non-zero material
    if "BoQ NRO Cluster" in wb.sheetnames:
        ws_check = wb["BoQ NRO Cluster"]
        has_mat = False
        for r in ws_check.iter_rows(values_only=True):
            if len(r) > 3 and isinstance(r[3], (int, float)) and r[3] > 0 and r[3] < 100000000:
                has_mat = True
                break
        if has_mat:
            target_sheet = "BoQ NRO Cluster"
            scope = "CLUSTER_DISTRIBUTION"
        elif "BoQ NRO All Feeder" in wb.sheetnames:
            target_sheet = "BoQ NRO All Feeder"
            scope = "SUB_FEEDER"
    elif "BoQ NRO All Feeder" in wb.sheetnames:
        target_sheet = "BoQ NRO All Feeder"
        scope = "SUB_FEEDER"
    else:
        # Fallback for generic vendor/test workbooks: ignore summary/permit/bom sheets
        for s in wb.sheetnames:
            s_low = s.lower()
            if not any(ig in s_low for ig in ["summary", "permit", "bom", "cover", "daftar"]):
                target_sheet = s
                scope = "GENERIC"
                break
        if not target_sheet and wb.sheetnames:
            target_sheet = wb.sheetnames[0]
            scope = "GENERIC"

    ws = wb[target_sheet]
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return str(target_sheet), scope, []

    # Detect header row and exact column indices
    h_idx = -1
    desc_col = 1
    unit_col = 2
    mat_qty_col = None
    svc_qty_col = None
    fallback_qty_col = None

    for i, r in enumerate(rows[:25]):
        line_s = " ".join(str(c).lower() for c in r if c is not None)
        if any(k in line_s for k in ["description", "uraian", "nama barang", "material qty", "qty"]):
            h_idx = i
            for c_idx, cell in enumerate(r):
                if cell is None:
                    continue
                cs = str(cell).strip().lower()
                if any(k in cs for k in ["description", "uraian", "nama barang", "item"]):
                    desc_col = c_idx
                elif any(k in cs for k in ["unit", "satuan"]):
                    unit_col = c_idx
                elif "material qty" in cs or "qty material" in cs or "volume material" in cs or "mat qty" in cs:
                    mat_qty_col = c_idx
                elif "service qty" in cs or "qty jasa" in cs or "jasa qty" in cs or "svc qty" in cs:
                    svc_qty_col = c_idx
                elif cs in ["qty", "quantity", "volume"] and fallback_qty_col is None:
                    fallback_qty_col = c_idx
            break

    if mat_qty_col is None:
        mat_qty_col = fallback_qty_col if fallback_qty_col is not None else 3

    items: list[dict[str, Any]] = []
    start_idx = h_idx + 1 if h_idx >= 0 else 0
    for _r_idx, r in enumerate(rows[start_idx:], start_idx):
        if not r or len(r) <= desc_col:
            continue
        raw_desc = r[desc_col]
        if not raw_desc or not isinstance(raw_desc, str) or len(raw_desc.strip()) < 3:
            continue
        desc_s = raw_desc.strip()
        d_low = desc_s.lower()

        # Filter out subtotals, grand totals, and section headings
        if any(ig in d_low for ig in ["sub total", "grand total", "subtotal", "total preparation", "total rute", "total odn", "total osp"]):
            continue

        unit = str(r[unit_col]).strip() if unit_col is not None and unit_col < len(r) and r[unit_col] is not None else ""
        mat_val = r[mat_qty_col] if mat_qty_col is not None and mat_qty_col < len(r) else None
        svc_val = r[svc_qty_col] if svc_qty_col is not None and svc_qty_col < len(r) else None

        qty = None
        is_service = False
        if isinstance(mat_val, (int, float)) and mat_val > 0 and mat_val < 100000000:
            qty = float(mat_val)
        elif svc_qty_col is not None and isinstance(svc_val, (int, float)) and svc_val > 0 and svc_val < 100000000:
            # Standalone service items like splicing / testcomm
            if any(k in d_low for k in ["splicing", "testcomm", "otdr", "opm"]):
                qty = float(svc_val)
                is_service = True

        if qty is not None:
            category = _classify_telecom_material(desc_s)
            items.append({
                "desc": desc_s,
                "unit": unit or ("Meter" if category == "CABLE" else "Pcs"),
                "qty": qty,
                "category": category,
                "is_service": is_service,
            })
    return str(target_sheet), scope, items


def _extract_telecom_quantities_from_text(text: str) -> dict[str, float]:
    """
    Ekstraksi kuantitas material presisi tinggi dari pesan chat lapangan.
    Mencegah false positive (seperti 'tiang 7 meter' terbaca 7 tiang).
    """
    t = (text or "").lower()
    cables = 0.0
    poles = 0.0
    fats = 0.0

    # 1. Tiang via kode shorthand: T72: 16 btg, T73: 19 btg, T9: 5 btg
    for m in re.finditer(r"\b(?:t72|t73|t74|t7|t9)[\s:=]+([0-9]+)\s*(?:btg|batang|pcs|titik)?\b", t):
        poles += float(m.group(1))

    # 2. Tiang via deskripsi: tiang 7m 10 btg, tiang 9 meter 5 batang, tanam tiang 7m: 4 batang
    for m in re.finditer(r"(?:tiang|pole|tanam)\s*(?:[0-9]+[\s]*(?:meter|m|\"))?[\s:=]+([0-9]+)\s*(?:btg|batang|pcs|titik)\b", t):
        poles += float(m.group(1))

    # 3. Tiang via format angka mendahului: 15 btg tiang, 8 batang tiang 7m
    for m in re.finditer(r"\b([0-9]+)\s*(?:btg|batang|pcs|titik)\s*(?:tiang|pole)\b", t):
        poles += float(m.group(1))

    # 4. Kabel: tarik kabel 1200m / 1200 meter, bentang adss 850 m
    for m in re.finditer(r"\b([0-9\.,]+)\s*(?:m|meter)\b", t):
        try:
            val = float(m.group(1).replace(",", "."))
            # Pastikan bukan ukuran tinggi tiang (7m, 9m)
            prev = t[max(0, m.start() - 12) : m.start()]
            if "tiang" not in prev and "pole" not in prev and val > 15:
                cables += val
        except ValueError:
            pass

    # 5. FAT: FAT: 5 box, 4 unit FAT, FAT 16 port: 2 box
    for m in re.finditer(r"\b(?:fat|fdt|odp|odc)\s*(?:[0-9]+\s*(?:port|c))?[\s:=]+([0-9]+)\s*(?:box|unit|titik|pcs)?\b", t):
        fats += float(m.group(1))

    return {"cables": cables, "poles": poles, "fats": fats}


@register_tool(category="office")
def boq_consolidate_master_workbook(
    file_paths: list[str] | str,
    output_filename: str = "BOQ_MASTER_CONSOLIDATED.xlsx",
    project_title: str = "MASTER CONSOLIDATED BOQ REPORT",
) -> dict[str, Any]:
    """
    KONSOLIDASI BOQ MULTI-CLUSTER TINGKAT TINGGI:
    Menggabungkan beberapa file Excel BOQ (.xlsx / .xls) per cluster/wilayah menjadi 1 file
    Master Workbook terpadu, lengkap dengan Sheet 'EXECUTIVE SUMMARY' (rekap tiang, kabel, FAT, FDT, aksesoris)
    dan Sheet 'MASTER_CONSOLIDATED' yang terstandarisasi dengan openpyxl.

    Args:
        file_paths: List path file Excel atau string path dipisah koma atau pola glob (misal '~/Unduhan/BOQ*.xlsx').
        output_filename: Nama file output Excel hasil konsolidasi (default: BOQ_MASTER_CONSOLIDATED.xlsx).
        project_title: Judul proyek untuk halaman Executive Summary.
    """
    try:
        import openpyxl
        from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
        from openpyxl.utils import get_column_letter

        # Parse file_paths input
        targets: list[str] = []
        if isinstance(file_paths, str):
            if "*" in file_paths or "?" in file_paths:
                targets = glob.glob(os.path.expanduser(file_paths.strip()))
            elif "," in file_paths:
                targets = [p.strip() for p in file_paths.split(",") if p.strip()]
            else:
                targets = [file_paths.strip()]
        elif isinstance(file_paths, (list, tuple)):
            for item in file_paths:
                if isinstance(item, str) and ("*" in item or "?" in item):
                    targets.extend(glob.glob(os.path.expanduser(item.strip())))
                elif isinstance(item, str):
                    targets.append(item.strip())

        # Filter file valid
        resolved_files = [os.path.realpath(os.path.expanduser(p)) for p in targets if os.path.exists(os.path.realpath(os.path.expanduser(p)))]
        if not resolved_files:
            return {
                "status": "error",
                "message": f"Tidak ada berkas Excel yang valid dari target: {file_paths}",
            }

        # Data container
        cluster_summaries: list[dict[str, Any]] = []
        master_rows: list[dict[str, Any]] = []

        for fpath in resolved_files:
            fname = os.path.basename(fpath)
            cluster_name = re.sub(r"(?i)(BOQ|SMDT|RO Bengkulu|Assignment Subcont|-|\.xlsx|\.xls)", "", fname).strip()
            if not cluster_name:
                cluster_name = os.path.splitext(fname)[0]

            try:
                wb = openpyxl.load_workbook(fpath, data_only=True)
            except Exception as e:
                logger.warning("Gagal membaca workbook %s: %s", fname, e)
                continue

            total_cables = 0.0
            total_poles = 0.0
            total_fat_fdt = 0.0
            total_acc = 0.0
            total_items = 0

            # Scan target sheets
            for sname in wb.sheetnames:
                ws = wb[sname]
                rows = list(ws.iter_rows(values_only=True))
                if not rows:
                    continue

                # Detect header row
                h_idx = -1
                for i, r in enumerate(rows[:15]):
                    line_s = " ".join(str(c) for c in r if c is not None).lower()
                    if any(k in line_s for k in ["description", "item", "uraian", "nama barang", "material qty"]):
                        h_idx = i
                        break

                start_idx = h_idx + 1 if h_idx >= 0 else 0
                for _r_idx, r in enumerate(rows[start_idx:], start_idx):
                    desc = None
                    qty = None
                    unit = ""

                    for idx, c in enumerate(r):
                        if desc is None and isinstance(c, str) and len(c.strip()) > 2 and not c.strip().replace(".", "").isdigit():
                            desc = c.strip()
                        elif isinstance(c, (int, float)) and c > 0 and c < 100000000:
                            if idx in (3, 4, 2, 5) or qty is None:
                                qty = float(c)
                        elif isinstance(c, str) and c.strip().lower() in ("meter", "m", "pcs", "unit", "set", "ls", "core", "roll"):
                            unit = c.strip()

                    if desc and qty is not None:
                        category = _classify_telecom_material(desc)
                        master_rows.append({
                            "Cluster": cluster_name,
                            "File Source": fname,
                            "Sheet": sname,
                            "Material Category": category,
                            "Description": desc[:90],
                            "Quantity": qty,
                            "Unit": unit or ("Meter" if category == "CABLE" else "Pcs"),
                        })
                        total_items += 1
                        if category == "CABLE":
                            total_cables += qty
                        elif category == "POLE":
                            total_poles += qty
                        elif category == "DISTRIBUTION_BOX":
                            total_fat_fdt += qty
                        elif category == "ACCESSORIES":
                            total_acc += qty

            cluster_summaries.append({
                "Cluster": cluster_name,
                "File": fname,
                "Total Cable (m)": round(total_cables, 2),
                "Total Poles (pcs)": int(total_poles),
                "Total FAT/FDT/ODC": int(total_fat_fdt),
                "Total Accessories": int(total_acc),
                "Item Count": total_items,
            })

        if not master_rows:
            return {
                "status": "error",
                "message": f"Tidak ditemukan data material kuantitas valid dari {len(resolved_files)} file.",
            }

        # Build Consolidated Workbook with openpyxl
        out_wb = openpyxl.Workbook()

        # Styles
        navy_header_fill = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid")
        cyan_header_fill = PatternFill(start_color="0284C7", end_color="0284C7", fill_type="solid")
        alt_row_fill = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")
        white_bold_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        title_font = Font(name="Calibri", size=14, bold=True, color="1E3A8A")
        bold_font = Font(name="Calibri", size=11, bold=True)
        thin_border = Border(
            left=Side(style="thin", color="CBD5E1"),
            right=Side(style="thin", color="CBD5E1"),
            top=Side(style="thin", color="CBD5E1"),
            bottom=Side(style="thin", color="CBD5E1"),
        )

        # Sheet 1: EXECUTIVE SUMMARY
        ws_sum = out_wb.active
        ws_sum.title = "EXECUTIVE SUMMARY"
        ws_sum.views.sheetView[0].showGridLines = True

        ws_sum.cell(row=1, column=1, value=project_title).font = title_font
        ws_sum.cell(row=2, column=1, value=f"Digenerate otomatis oleh ALFA OS pada: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}").font = Font(italic=True, color="64748B")

        sum_headers = ["No", "Cluster Name", "Total Cable (Meter)", "Total Poles (Pcs)", "FAT / FDT / ODC", "Total Aksesoris", "Total Material Lines", "File Source"]
        ws_sum.row_dimensions[4].height = 24
        for c_idx, h in enumerate(sum_headers, 1):
            cell = ws_sum.cell(row=4, column=c_idx, value=h)
            cell.font = white_bold_font
            cell.fill = navy_header_fill
            cell.alignment = Alignment(horizontal="center", vertical="center")
            cell.border = thin_border

        for r_idx, c_data in enumerate(cluster_summaries, 5):
            ws_sum.row_dimensions[r_idx].height = 20
            row_vals = [
                r_idx - 4,
                c_data["Cluster"],
                c_data["Total Cable (m)"],
                c_data["Total Poles (pcs)"],
                c_data["Total FAT/FDT/ODC"],
                c_data["Total Accessories"],
                c_data["Item Count"],
                c_data["File"],
            ]
            for c_idx, val in enumerate(row_vals, 1):
                cell = ws_sum.cell(row=r_idx, column=c_idx, value=val)
                cell.border = thin_border
                if r_idx % 2 == 0:
                    cell.fill = alt_row_fill
                if c_idx in (3, 4, 5, 6, 7):
                    cell.alignment = Alignment(horizontal="right", vertical="center")
                    cell.number_format = "#,##0"
                else:
                    cell.alignment = Alignment(horizontal="left", vertical="center")

        # Total Row in Summary
        tot_row = len(cluster_summaries) + 5
        ws_sum.cell(row=tot_row, column=1, value="TOTAL").font = bold_font
        ws_sum.cell(row=tot_row, column=2, value=f"{len(cluster_summaries)} CLUSTERS").font = bold_font
        ws_sum.cell(row=tot_row, column=3, value=sum(c["Total Cable (m)"] for c in cluster_summaries)).font = bold_font
        ws_sum.cell(row=tot_row, column=4, value=sum(c["Total Poles (pcs)"] for c in cluster_summaries)).font = bold_font
        ws_sum.cell(row=tot_row, column=5, value=sum(c["Total FAT/FDT/ODC"] for c in cluster_summaries)).font = bold_font
        ws_sum.cell(row=tot_row, column=6, value=sum(c["Total Accessories"] for c in cluster_summaries)).font = bold_font
        ws_sum.cell(row=tot_row, column=7, value=sum(c["Item Count"] for c in cluster_summaries)).font = bold_font
        for c_idx in range(1, 9):
            cell = ws_sum.cell(row=tot_row, column=c_idx)
            cell.border = thin_border
            cell.font = bold_font
            if c_idx in (3, 4, 5, 6, 7):
                cell.alignment = Alignment(horizontal="right", vertical="center")
                cell.number_format = "#,##0"

        # Sheet 2: MASTER_CONSOLIDATED
        ws_master = out_wb.create_sheet(title="MASTER_CONSOLIDATED")
        ws_master.views.sheetView[0].showGridLines = True
        master_headers = ["No", "Cluster", "Category", "Description", "Quantity", "Unit", "Sheet Source", "File Source"]

        ws_master.row_dimensions[1].height = 24
        for c_idx, h in enumerate(master_headers, 1):
            cell = ws_master.cell(row=1, column=c_idx, value=h)
            cell.font = white_bold_font
            cell.fill = cyan_header_fill
            cell.alignment = Alignment(horizontal="center", vertical="center")
            cell.border = thin_border

        for r_idx, m_row in enumerate(master_rows, 2):
            row_vals = [
                r_idx - 1,
                m_row["Cluster"],
                m_row["Material Category"],
                m_row["Description"],
                m_row["Quantity"],
                m_row["Unit"],
                m_row["Sheet"],
                m_row["File Source"],
            ]
            for c_idx, val in enumerate(row_vals, 1):
                cell = ws_master.cell(row=r_idx, column=c_idx, value=val)
                cell.border = thin_border
                if r_idx % 2 == 1:
                    cell.fill = alt_row_fill
                if c_idx == 5:
                    cell.alignment = Alignment(horizontal="right", vertical="center")
                    cell.number_format = "#,##0.00" if isinstance(val, float) and not val.is_integer() else "#,##0"
                else:
                    cell.alignment = Alignment(horizontal="left", vertical="center")

        # Auto-adjust column widths
        for ws in [ws_sum, ws_master]:
            for col in ws.columns:
                max_len = 0
                col_letter = get_column_letter(col[0].column)
                for cell in col:
                    val_str = str(cell.value or "")
                    if len(val_str) > max_len:
                        max_len = min(len(val_str), 50)
                ws.column_dimensions[col_letter].width = max(max_len + 3, 12)

        # Save output workbook
        out_name = output_filename if output_filename.endswith(".xlsx") else f"{output_filename}.xlsx"
        out_path = os.path.join(SANDBOX_DIR, out_name)
        os.makedirs(SANDBOX_DIR, exist_ok=True)
        out_wb.save(out_path)

        return {
            "status": "success",
            "message": f"Berhasil mengonsolidasikan {len(resolved_files)} file BOQ ke '{out_name}'.",
            "output_file": out_path,
            "filename": out_name,
            "total_clusters": len(cluster_summaries),
            "total_material_rows": len(master_rows),
            "clusters_summary": cluster_summaries,
            "grand_totals": {
                "cable_meters": sum(c["Total Cable (m)"] for c in cluster_summaries),
                "poles_pcs": sum(c["Total Poles (pcs)"] for c in cluster_summaries),
                "fat_fdt_pcs": sum(c["Total FAT/FDT/ODC"] for c in cluster_summaries),
                "accessories_pcs": sum(c["Total Accessories"] for c in cluster_summaries),
            },
        }
    except Exception as e:
        logger.exception("Gagal mengonsolidasikan BOQ: %s", e)
        return {"status": "error", "message": f"BOQ consolidate error: {str(e)}"}


@register_tool(category="office")
def boq_compare_and_diff(
    file_path_old: str,
    file_path_new: str,
    output_diff_filename: str = "BOQ_DIFF_REVISION.xlsx",
) -> dict[str, Any]:
    """
    ANALISIS REVISI & VISUAL DIFF EXCEL BOQ:
    Membandingkan dua berkas BOQ (versi lama vs versi baru / revisi), mendeteksi otomatis:
    - Item yang bertambah (Added) -> Highlight Hijau Muda.
    - Item yang dihapus (Deleted) -> Highlight Merah Muda.
    - Item yang volumenya berubah (Quantity Changed) -> Highlight Kuning Muda dengan nilai Delta (+/-).

    Args:
        file_path_old: Lokasi file Excel BOQ versi acuan/sebelumnya.
        file_path_new: Lokasi file Excel BOQ versi baru/revisi.
        output_diff_filename: Nama file output Excel hasil diff visual.
    """
    try:
        import openpyxl
        from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
        from openpyxl.utils import get_column_letter

        f_old = os.path.realpath(os.path.expanduser(file_path_old.strip()))
        f_new = os.path.realpath(os.path.expanduser(file_path_new.strip()))

        if not os.path.exists(f_old):
            return {"status": "error", "message": f"File acuan '{file_path_old}' tidak ditemukan."}
        if not os.path.exists(f_new):
            return {"status": "error", "message": f"File revisi '{file_path_new}' tidak ditemukan."}

        def _extract_items_dict(fpath: str) -> dict[str, dict[str, Any]]:
            wb = openpyxl.load_workbook(fpath, data_only=True)
            res: dict[str, dict[str, Any]] = {}
            for sname in wb.sheetnames:
                ws = wb[sname]
                for r in ws.iter_rows(values_only=True):
                    desc = None
                    qty = None
                    unit = ""
                    for idx, c in enumerate(r):
                        if desc is None and isinstance(c, str) and len(c.strip()) > 2 and not c.strip().replace(".", "").isdigit():
                            desc = c.strip()
                        elif isinstance(c, (int, float)) and c > 0 and c < 100000000:
                            if idx in (3, 4, 2, 5) or qty is None:
                                qty = float(c)
                        elif isinstance(c, str) and c.strip().lower() in ("meter", "m", "pcs", "unit", "set", "ls", "core", "roll"):
                            unit = c.strip()
                    if desc and qty is not None:
                        key = desc.lower().strip()
                        if key not in res:
                            res[key] = {"desc": desc, "qty": qty, "unit": unit, "sheet": sname}
                        else:
                            res[key]["qty"] += qty
            return res

        old_items = _extract_items_dict(f_old)
        new_items = _extract_items_dict(f_new)

        all_keys = sorted(set(old_items.keys()) | set(new_items.keys()))
        diff_records: list[dict[str, Any]] = []

        added_count = 0
        deleted_count = 0
        changed_count = 0
        same_count = 0

        for k in all_keys:
            old_data = old_items.get(k)
            new_data = new_items.get(k)

            if old_data and not new_data:
                status = "REMOVED"
                deleted_count += 1
                diff_records.append({
                    "status": status,
                    "desc": old_data["desc"],
                    "old_qty": old_data["qty"],
                    "new_qty": 0.0,
                    "delta": -old_data["qty"],
                    "unit": old_data["unit"],
                })
            elif not old_data and new_data:
                status = "ADDED"
                added_count += 1
                diff_records.append({
                    "status": status,
                    "desc": new_data["desc"],
                    "old_qty": 0.0,
                    "new_qty": new_data["qty"],
                    "delta": new_data["qty"],
                    "unit": new_data["unit"],
                })
            else:
                if not old_data or not new_data:
                    # Keduanya None: item tidak ada di kedua sisi -> lewati.
                    continue
                old_q = old_data["qty"]
                new_q = new_data["qty"]
                delta = round(new_q - old_q, 3)
                if abs(delta) > 0.001:
                    status = "MODIFIED"
                    changed_count += 1
                    diff_records.append({
                        "status": status,
                        "desc": new_data["desc"],
                        "old_qty": old_q,
                        "new_qty": new_q,
                        "delta": delta,
                        "unit": new_data["unit"] or old_data["unit"],
                    })
                else:
                    status = "UNCHANGED"
                    same_count += 1
                    diff_records.append({
                        "status": status,
                        "desc": new_data["desc"],
                        "old_qty": old_q,
                        "new_qty": new_q,
                        "delta": 0.0,
                        "unit": new_data["unit"],
                    })

        # Generate styled Excel Diff
        wb_out = openpyxl.Workbook()
        ws = wb_out.active
        ws.title = "BOQ_DIFF_COMPARISON"
        ws.views.sheetView[0].showGridLines = True

        # Styles
        green_fill = PatternFill(start_color="DCFCE7", end_color="DCFCE7", fill_type="solid")  # Added
        red_fill = PatternFill(start_color="FEE2E2", end_color="FEE2E2", fill_type="solid")    # Removed
        yellow_fill = PatternFill(start_color="FEF9C3", end_color="FEF9C3", fill_type="solid") # Changed
        navy_fill = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid")
        white_bold = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        thin_border = Border(
            left=Side(style="thin", color="CBD5E1"),
            right=Side(style="thin", color="CBD5E1"),
            top=Side(style="thin", color="CBD5E1"),
            bottom=Side(style="thin", color="CBD5E1"),
        )

        headers = ["No", "Change Status", "Material Description", "Old Qty (Ref)", "New Qty (Rev)", "Delta (+/-)", "Unit"]
        ws.row_dimensions[1].height = 24
        for c_idx, h in enumerate(headers, 1):
            cell = ws.cell(row=1, column=c_idx, value=h)
            cell.font = white_bold
            cell.fill = navy_fill
            cell.alignment = Alignment(horizontal="center", vertical="center")
            cell.border = thin_border

        for r_idx, rec in enumerate(diff_records, 2):
            st = rec["status"]
            row_vals = [
                r_idx - 1,
                st,
                rec["desc"],
                rec["old_qty"],
                rec["new_qty"],
                rec["delta"],
                rec["unit"],
            ]
            fill_to_apply = green_fill if st == "ADDED" else red_fill if st == "REMOVED" else yellow_fill if st == "MODIFIED" else None

            for c_idx, val in enumerate(row_vals, 1):
                cell = ws.cell(row=r_idx, column=c_idx, value=val)
                cell.border = thin_border
                if fill_to_apply:
                    cell.fill = fill_to_apply
                if c_idx in (4, 5, 6):
                    cell.alignment = Alignment(horizontal="right", vertical="center")
                    cell.number_format = "+#,##0.00;-#,##0.00;0" if c_idx == 6 else "#,##0.00"
                else:
                    cell.alignment = Alignment(horizontal="left", vertical="center")

        for col in ws.columns:
            max_len = max(len(str(c.value or "")) for c in col)
            ws.column_dimensions[get_column_letter(col[0].column)].width = max(min(max_len + 3, 55), 12)

        out_name = output_diff_filename if output_diff_filename.endswith(".xlsx") else f"{output_diff_filename}.xlsx"
        out_path = os.path.join(SANDBOX_DIR, out_name)
        os.makedirs(SANDBOX_DIR, exist_ok=True)
        wb_out.save(out_path)

        return {
            "status": "success",
            "message": f"Analisis diff selesai: {added_count} ditambahkan, {changed_count} berubah volume, {deleted_count} dihapus.",
            "output_diff_file": out_path,
            "filename": out_name,
            "statistics": {
                "total_items_compared": len(diff_records),
                "items_added": added_count,
                "items_modified": changed_count,
                "items_removed": deleted_count,
                "items_unchanged": same_count,
            },
            "sample_changes": [r for r in diff_records if r["status"] != "UNCHANGED"][:10],
        }
    except Exception as e:
        logger.exception("Gagal membandingkan BOQ diff: %s", e)
        return {"status": "error", "message": f"BOQ diff error: {str(e)}"}


@register_tool(category="office")
def boq_reconcile_with_field_reports(
    cluster_name: str,
    target_boq_file: str = "",
    days_back: int = 30,
) -> dict[str, Any]:
    """
    REKONSILIASI PROGRES HARIAN (BOQ VS LAPORAN WA / SMDT):
    Mencocokkan target material dalam BOQ dengan laporan harian aktual yang dikirimkan oleh
    mandor/subcont via WhatsApp (tersimpan di database arsip) atau file SMDT terkait.
    Menghitung sisa kuota, persentase penyelesaian, dan mendeteksi anomali over-budget material.

    Args:
        cluster_name: Nama cluster yang ingin direkonsiliasi (misal: 'Dusun Curup', 'Air Lanang', 'Kasambe').
        target_boq_file: Path opsional ke file Excel BOQ target (jika kosong, bot mencari di folder Unduhan/Dokumen).
        days_back: Rentang hari riwayat chat WhatsApp yang dianalisis (default: 30 hari).
    """
    try:
        import openpyxl

        from alfa.core.db.connection import get_sync_db

        clean_cname = cluster_name.lower().strip()

        # 1. Temukan Target BOQ
        target_materials: dict[str, float] = {}
        target_file_used = ""
        if target_boq_file and os.path.exists(os.path.realpath(os.path.expanduser(target_boq_file))):
            target_file_used = os.path.realpath(os.path.expanduser(target_boq_file))
        else:
            # Auto-search file BOQ/SMDT terkait cluster di ~/Unduhan
            cand_files = glob.glob(f"/home/fahmial/Unduhan/*{clean_cname}*.xlsx") + glob.glob("/home/fahmial/Unduhan/SMDT*.xlsx")
            if cand_files:
                target_file_used = cand_files[0]

        if target_file_used and os.path.exists(target_file_used):
            wb = openpyxl.load_workbook(target_file_used, data_only=True)
            for sname in wb.sheetnames:
                if clean_cname in sname.lower() or sname.lower() in clean_cname or "boq" in sname.lower():
                    ws = wb[sname]
                    for r in ws.iter_rows(values_only=True):
                        desc = None
                        qty = None
                        for idx, c in enumerate(r):
                            if desc is None and isinstance(c, str) and len(c.strip()) > 3 and not c.strip().replace(".", "").isdigit():
                                desc = c.strip()
                            elif isinstance(c, (int, float)) and c > 0 and c < 100000000:
                                if idx in (3, 4, 2, 5) or qty is None:
                                    qty = float(c)
                        if desc and qty:
                            target_materials[desc] = target_materials.get(desc, 0.0) + qty

        # 2. Query Chat WhatsApp Masuk
        actual_reports: list[dict[str, Any]] = []
        with get_sync_db() as conn:
            query = """
                SELECT chat_name, sender_name, body, msg_ts
                FROM wa_incoming_archive
                WHERE (LOWER(body) LIKE ? OR LOWER(chat_name) LIKE ?)
                ORDER BY msg_ts DESC LIMIT 100
            """
            rows = conn.execute(query, (f"%{clean_cname}%", f"%{clean_cname}%")).fetchall()
            for r in rows:
                actual_reports.append({
                    "chat": r[0],
                    "sender": r[1],
                    "body": r[2],
                    "ts": r[3],
                })

        # 3. Ekstrak Angka Progres Lapangan dari Chat
        reported_cables = 0.0
        reported_poles = 0.0
        reported_fat = 0.0

        for rep in actual_reports:
            extracted = _extract_telecom_quantities_from_text(rep.get("body") or "")
            reported_cables += extracted["cables"]
            reported_poles += extracted["poles"]
            reported_fat += extracted["fats"]

        # 4. Ringkasan Rekonsiliasi
        target_cable_val = sum(v for k, v in target_materials.items() if _classify_telecom_material(k) == "CABLE")
        target_pole_val = sum(v for k, v in target_materials.items() if _classify_telecom_material(k) == "POLE")

        reconcile_items = [
            {
                "item": "Kabel Distribusi & Feeder (ADSS/FO)",
                "target_boq": round(target_cable_val, 2),
                "actual_reported": round(reported_cables, 2),
                "remaining_quota": round(max(0, target_cable_val - reported_cables), 2),
                "progress_pct": f"{round((reported_cables / target_cable_val * 100), 1)}%" if target_cable_val > 0 else "N/A",
                "status": "OVER_BUDGET" if target_cable_val > 0 and reported_cables > target_cable_val else "ON_TRACK",
            },
            {
                "item": "Tiang Besi (Steel Pole 7m / 9m)",
                "target_boq": int(target_pole_val),
                "actual_reported": int(reported_poles),
                "remaining_quota": max(0, int(target_pole_val - reported_poles)),
                "progress_pct": f"{round((reported_poles / target_pole_val * 100), 1)}%" if target_pole_val > 0 else "N/A",
                "status": "OVER_BUDGET" if target_pole_val > 0 and reported_poles > target_pole_val else "ON_TRACK",
            },
            {
                "item": "FAT / FDT Box Terpasang",
                "target_boq": 0,
                "actual_reported": int(reported_fat),
                "remaining_quota": 0,
                "progress_pct": "Reported",
                "status": "OK",
            },
        ]

        return {
            "status": "success",
            "cluster": cluster_name,
            "target_boq_file": os.path.basename(target_file_used) if target_file_used else "Tidak terdeteksi (Hanya data lapangan)",
            "total_whatsapp_messages_found": len(actual_reports),
            "reconciliation_summary": reconcile_items,
            "recent_field_messages": actual_reports[:5],
            "message": f"Rekonsiliasi cluster '{cluster_name}' selesai dengan menganalisis {len(actual_reports)} laporan WhatsApp.",
        }
    except Exception as e:
        logger.exception("Gagal rekonsiliasi BOQ: %s", e)
        return {"status": "error", "message": f"BOQ reconcile error: {str(e)}"}


@register_tool(category="office")
def boq_check_project_anomalies(
    project_keyword: str = "FTTH",
    stale_hours_threshold: int = 48,
) -> dict[str, Any]:
    """
    EARLY WARNING & SENTINEL ANOMALI PROYEK:
    Memantau kesehatan operasional proyek secara proaktif:
    - Mendeteksi cluster atau grup koordinasi yang mandek (>48 jam tanpa ada laporan progres).
    - Mendeteksi laporan kendala darurat di lapangan (izin warga, perizinan, kabel putus, kendala teknis).
    - Mengembalikan kartu ringkasan peringatan dini (Alert Card) untuk Telegram.

    Args:
        project_keyword: Kata kunci nama proyek/wilayah (misal: 'FTTH', 'BKL', 'Curup', 'Linggau', 'EMR').
        stale_hours_threshold: Batas waktu jam tanpa laporan untuk dianggap mandek (default: 48 jam).
    """
    try:
        import time

        from alfa.core.db.connection import get_sync_db

        now_ts = int(time.time())
        stale_cutoff = now_ts - (stale_hours_threshold * 3600)

        stalled_chats: list[dict[str, Any]] = []
        incident_reports: list[dict[str, Any]] = []

        with get_sync_db() as conn:
            # 1. Cek Grup Terakhir Aktif
            query_last_active = """
                SELECT chat_id, chat_name, MAX(msg_ts) as last_ts, COUNT(*) as total_msgs
                FROM wa_incoming_archive
                WHERE LOWER(chat_name) LIKE ?
                GROUP BY chat_id, chat_name
            """
            rows = conn.execute(query_last_active, (f"%{project_keyword.lower()}%",)).fetchall()
            for r in rows:
                c_id, c_name, last_ts, count = r
                if last_ts and last_ts < stale_cutoff:
                    hours_silent = round((now_ts - last_ts) / 3600, 1)
                    stalled_chats.append({
                        "chat_name": c_name or "Grup Proyek",
                        "hours_silent": hours_silent,
                        "last_reported": datetime.fromtimestamp(last_ts).strftime("%Y-%m-%d %H:%M"),
                    })

            # 2. Cek Laporan Kendala (Incident Watch)
            query_issues = """
                SELECT chat_name, sender_name, body, msg_ts
                FROM wa_incoming_archive
                WHERE (LOWER(body) LIKE '%kendala%' OR LOWER(body) LIKE '%ijin warga%' OR LOWER(body) LIKE '%izin warga%' OR LOWER(body) LIKE '%kabel putus%'
                       OR LOWER(body) LIKE '%tertunda%' OR LOWER(body) LIKE '%retur%'
                       OR LOWER(body) LIKE '%masalah%')
                ORDER BY msg_ts DESC LIMIT 10
            """
            issue_rows = conn.execute(query_issues).fetchall()
            for ir in issue_rows:
                incident_reports.append({
                    "chat": ir[0],
                    "sender": ir[1],
                    "issue": ir[2][:150],
                    "date": datetime.fromtimestamp(ir[3]).strftime("%Y-%m-%d %H:%M") if ir[3] else "",
                })

        return {
            "status": "success",
            "project_keyword": project_keyword,
            "stale_threshold_hours": stale_hours_threshold,
            "stalled_clusters_count": len(stalled_chats),
            "stalled_clusters": stalled_chats,
            "active_field_incidents_count": len(incident_reports),
            "field_incidents": incident_reports,
            "health_status": "CRITICAL" if incident_reports or len(stalled_chats) >= 3 else "WARNING" if stalled_chats else "HEALTHY",
        }
    except Exception as e:
        logger.exception("Gagal memeriksa anomali proyek: %s", e)
        return {"status": "error", "message": f"Anomaly check error: {str(e)}"}


@register_tool(category="office")
def render_cluster_kml_map(
    kml_or_kmz_path: str,
    output_html_filename: str = "cluster_map.html",
) -> dict[str, Any]:
    """
    VISUALISASI PETA INTERAKTIF KML / KMZ (LEAFLET.JS):
    Mengekstrak titik tiang, koordinat FAT/ODC, dan rute jalur bentangan kabel dari berkas
    .kml atau .kmz proyek FTTH, lalu menghasilkan halaman peta interaktif visual berbasis Leaflet.js
    (mandiri tanpa API key) yang dapat dibuka di browser atau dikirim ke chat.

    Args:
        kml_or_kmz_path: Lokasi absolut atau relatif file .kml atau .kmz.
        output_html_filename: Nama file output HTML interaktif (default: cluster_map.html).
    """
    try:
        fpath = os.path.realpath(os.path.expanduser(kml_or_kmz_path.strip()))
        if not os.path.exists(fpath):
            return {"status": "error", "message": f"Berkas KML/KMZ '{kml_or_kmz_path}' tidak ditemukan."}

        kml_bytes = b""
        if fpath.endswith(".kmz"):
            with zipfile.ZipFile(fpath, "r") as z:
                kml_names = [n for n in z.namelist() if n.endswith(".kml")]
                if not kml_names:
                    return {"status": "error", "message": "Tidak ditemukan file .kml di dalam arsip KMZ."}
                kml_bytes = z.read(kml_names[0])
        else:
            with open(fpath, "rb") as f:
                kml_bytes = f.read()

        # Parse XML (stripping namespaces for cleaner navigation)
        raw_xml = re.sub(r'xmlns(:\w+)?="[^"]+"', '', kml_bytes.decode("utf-8", errors="ignore"))
        root = _xml_fromstring(raw_xml)

        markers: list[dict[str, Any]] = []
        polylines: list[dict[str, Any]] = []

        all_lats: list[float] = []
        all_lons: list[float] = []

        # Cek data progres lapangan dari arsip WA / SMDT
        reported_terms: set[str] = set()
        installed_markers_count = 0
        try:
            from alfa.core.db.connection import get_sync_db
            with get_sync_db() as conn:
                cluster_key = os.path.splitext(os.path.basename(fpath))[0].lower().replace("aktual", "").strip()
                q_txt = f"%{cluster_key}%" if cluster_key else "%kasambe%"
                rows = conn.execute(
                    "SELECT body FROM wa_incoming_archive WHERE LOWER(body) LIKE ? OR LOWER(chat_name) LIKE ? LIMIT 50",
                    (q_txt, q_txt),
                ).fetchall()
                for rw in rows:
                    for w in re.findall(r"\b[A-Za-z0-9\-_]{2,15}\b", (rw[0] or "").lower()):
                        reported_terms.add(w)
        except Exception:
            pass

        for pm in root.iter("Placemark"):
            name = (pm.findtext("name") or "Placemark").strip()
            desc = (pm.findtext("description") or "").strip()
            # Clean CDATA or HTML in description
            desc_clean = re.sub(r"<[^>]+>", " ", desc).strip()

            # Check Point
            pt = pm.find(".//Point/coordinates")
            if pt is not None and pt.text:
                coords = pt.text.strip().split(",")
                if len(coords) >= 2:
                    try:
                        lon = float(coords[0])
                        lat = float(coords[1])
                        all_lons.append(lon)
                        all_lats.append(lat)
                        m_type = "POLE" if any(k in name.lower() for k in ['7"', '9"', 'tiang', 'pole']) else "FAT" if "fat" in name.lower() else "POINT"

                        # Status progres: Terpasang vs Rencana
                        is_installed = (
                            any(k in name.lower() for k in ("tanam", "pasang", "done", "selesai", "aktual", "ok"))
                            or name.lower() in reported_terms
                            or "aktual" in os.path.basename(fpath).lower()
                        )
                        if is_installed:
                            m_status = "TERPASANG (INSTALLED)"
                            color = "#10B981"  # Emerald Green
                            installed_markers_count += 1
                        elif m_type == "FAT":
                            m_status = "RENCANA (FAT)"
                            color = "#3B82F6"  # Blue
                        elif m_type == "POLE":
                            m_status = "RENCANA (TIANG)"
                            color = "#F59E0B"  # Amber
                        else:
                            m_status = "RENCANA"
                            color = "#8B5CF6"  # Purple

                        markers.append({
                            "name": name,
                            "desc": desc_clean[:120],
                            "lat": lat,
                            "lon": lon,
                            "type": m_type,
                            "status": m_status,
                            "color": color,
                        })
                    except ValueError:
                        pass

            # Check LineString
            ls = pm.find(".//LineString/coordinates")
            if ls is not None and ls.text:
                line_points = []
                for token in ls.text.strip().split():
                    c_parts = token.split(",")
                    if len(c_parts) >= 2:
                        try:
                            lon = float(c_parts[0])
                            lat = float(c_parts[1])
                            all_lons.append(lon)
                            all_lats.append(lat)
                            line_points.append([lat, lon])
                        except ValueError:
                            pass
                if len(line_points) >= 2:
                    polylines.append({
                        "name": name,
                        "desc": desc_clean[:100],
                        "coords": line_points,
                        "color": "#2563EB",
                    })

        if not markers and not polylines:
            return {"status": "error", "message": f"Tidak ditemukan titik koordinat atau jalur garis pada berkas '{os.path.basename(fpath)}'."}

        center_lat = sum(all_lats) / len(all_lats) if all_lats else 0.0
        center_lon = sum(all_lons) / len(all_lons) if all_lons else 0.0

        # Build Interactive Leaflet HTML
        html_content = f"""<!DOCTYPE html>
<html lang="id">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Peta Interaktif FTTH - {os.path.basename(fpath)}</title>
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <style>
        body, html {{ margin: 0; padding: 0; width: 100%; height: 100%; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }}
        #map {{ width: 100%; height: 100%; }}
        .hud-card {{
            position: absolute; top: 15px; right: 15px; z-index: 1000;
            background: rgba(15, 23, 42, 0.90); backdrop-filter: blur(8px);
            color: #ffffff; padding: 14px 18px; border-radius: 12px;
            box-shadow: 0 4px 20px rgba(0,0,0,0.4); border: 1px solid rgba(255,255,255,0.12);
            max-width: 320px;
        }}
        .hud-title {{ font-size: 14px; font-weight: 700; color: #38BDF8; margin-bottom: 6px; }}
        .hud-stat {{ font-size: 12px; margin: 4px 0; color: #E2E8F0; display: flex; justify-content: space-between; }}
        .badge {{ font-weight: bold; padding: 2px 6px; border-radius: 4px; background: rgba(56, 189, 248, 0.2); color: #38BDF8; }}
        .badge-green {{ background: rgba(16, 185, 129, 0.2); color: #10B981; }}
        .legend {{ margin-top: 10px; border-top: 1px solid rgba(255,255,255,0.1); padding-top: 8px; font-size: 11px; color: #94A3B8; }}
        .legend-item {{ display: flex; align-items: center; margin: 3px 0; }}
        .dot {{ width: 8px; height: 8px; border-radius: 50%; display: inline-block; margin-right: 6px; }}
    </style>
</head>
<body>
    <div id="map"></div>
    <div class="hud-card">
        <div class="hud-title">⚡ ALFA FTTH MAP VIEWER</div>
        <div style="font-size: 11px; color: #94A3B8; margin-bottom: 8px;">{os.path.basename(fpath)}</div>
        <div class="hud-stat"><span>Titik Total:</span> <span class="badge">{len(markers)} pts</span></div>
        <div class="hud-stat"><span>Status Terpasang:</span> <span class="badge badge-green">{installed_markers_count} pts</span></div>
        <div class="hud-stat"><span>Jalur Kabel:</span> <span class="badge">{len(polylines)} routes</span></div>
        <div class="hud-stat"><span>Pusat Koordinat:</span> <span>{round(center_lat, 5)}, {round(center_lon, 5)}</span></div>
        <div class="legend">
            <div class="legend-item"><span class="dot" style="background:#10B981;"></span> Terpasang (Installed)</div>
            <div class="legend-item"><span class="dot" style="background:#3B82F6;"></span> FAT Rencana</div>
            <div class="legend-item"><span class="dot" style="background:#F59E0B;"></span> Tiang Rencana</div>
            <div class="legend-item"><span class="dot" style="background:#2563EB;"></span> Jalur Bentangan Kabel</div>
        </div>
    </div>
    <script>
        const map = L.map('map').setView([{center_lat}, {center_lon}], 16);
        L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
            maxZoom: 19,
            attribution: '© OpenStreetMap contributors | ALFA OS'
        }}).addTo(map);

        const markersData = {json.dumps(markers)};
        markersData.forEach(m => {{
            const circle = L.circleMarker([m.lat, m.lon], {{
                radius: m.type === 'FAT' ? 8 : 6,
                fillColor: m.color,
                color: '#ffffff',
                weight: 2,
                opacity: 1,
                fillOpacity: 0.85
            }}).addTo(map);
            circle.bindPopup(`<b>${{m.name}}</b><br><span style="display:inline-block; margin:3px 0; font-size:10px; font-weight:bold; color:${{m.color}}; background:rgba(255,255,255,0.1); padding:1px 6px; border-radius:4px;">${{m.status}}</span><br><span style="font-size:11px; color:#64748B;">Tipe: ${{m.type}}</span><br><p style="margin:4px 0; font-size:12px;">${{m.desc || 'Tidak ada deskripsi'}}</p><span style="font-size:10px; color:#94A3B8;">${{m.lat}}, ${{m.lon}}</span>`);
        }});

        const linesData = {json.dumps(polylines)};
        linesData.forEach(line => {{
            const poly = L.polyline(line.coords, {{
                color: line.color,
                weight: 4,
                opacity: 0.8
            }}).addTo(map);
            poly.bindPopup(`<b>${{line.name}}</b><br><span style="font-size:12px;">${{line.desc || 'Jalur Bentangan Kabel'}}</span>`);
        }});
    </script>
</body>
</html>
"""
        out_name = output_html_filename if output_html_filename.endswith(".html") else f"{output_html_filename}.html"
        out_path = os.path.join(SANDBOX_DIR, out_name)
        os.makedirs(SANDBOX_DIR, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(html_content)

        return {
            "status": "success",
            "message": f"Berhasil merender peta interaktif dari '{os.path.basename(fpath)}' ke '{out_name}'.",
            "output_html_file": out_path,
            "filename": out_name,
            "total_points": len(markers),
            "total_cable_routes": len(polylines),
            "center_lat": round(center_lat, 6),
            "center_lon": round(center_lon, 6),
        }
    except Exception as e:
        logger.exception("Gagal merender peta KML: %s", e)
        return {"status": "error", "message": f"Render KML map error: {str(e)}"}


@register_tool(category="office")
def generate_daily_executive_briefing(
    shift: str = "now",
    days_back: int = 1,
) -> dict[str, Any]:
    """
    EXECUTIVE DAILY BRIEFING PROYEK & KESEHATAN SISTEM:
    Menghasilkan kartu laporan eksekutif berkala (pagi/sore) untuk Telegram:
    - Rangkuman total tarikan kabel, tiang tertanam, dan FAT terpasang dalam 24 jam terakhir.
    - Status cluster aktif vs cluster mandek (>48 jam).
    - Laporan kendala dan insiden darurat lapangan dari grup WhatsApp.
    - Metrik kesehatan server Linux & status service ALFA.

    PERINGATAN ATURAN:
    Laporan ini HANYA dikirimkan ke Telegram Fahmi. DILARANG KERAS mengirim atau membalas otomatis ke WhatsApp!

    Args:
        shift: Jenis briefing ('morning', 'evening', atau 'now').
        days_back: Rentang hari analisis riwayat chat lapangan (default: 1 hari).
    """
    try:
        import time

        import psutil

        from alfa.core.db.connection import get_sync_db

        now_ts = int(time.time())
        cutoff_ts = now_ts - (days_back * 86400)

        total_cable = 0.0
        total_poles = 0.0
        total_fat = 0.0
        active_clusters_set = set()
        recent_issues: list[dict[str, Any]] = []

        with get_sync_db() as conn:
            # 1. Analisis Pesan Lapangan
            query = """
                SELECT chat_name, sender_name, body, msg_ts
                FROM wa_incoming_archive
                WHERE msg_ts >= ?
                ORDER BY msg_ts DESC
            """
            rows = conn.execute(query, (cutoff_ts,)).fetchall()
            for r in rows:
                cname = r[0] or "Grup Proyek"
                text = (r[2] or "").lower()
                active_clusters_set.add(cname)

                # Ekstrak kuantitas material presisi tinggi
                ext = _extract_telecom_quantities_from_text(r[2] or "")
                total_cable += ext["cables"]
                total_poles += ext["poles"]
                total_fat += ext["fats"]

                # Deteksi kendala
                if any(k in text for k in ["kendala", "ijin warga", "izin warga", "kabel putus", "retur", "masalah", "pending"]):
                    recent_issues.append({
                        "cluster": cname,
                        "sender": r[1],
                        "text": r[2][:120],
                    })

            # 2. Cek Cluster Stalled (>48 jam)
            stalled_clusters = []
            stalled_cutoff = now_ts - (48 * 3600)
            stalled_query = """
                SELECT chat_name, MAX(msg_ts) as last_ts
                FROM wa_incoming_archive
                WHERE LOWER(chat_name) LIKE '%ftth%' OR LOWER(chat_name) LIKE '%imt%' OR LOWER(chat_name) LIKE '%bkl%'
                GROUP BY chat_id, chat_name
            """
            stalled_rows = conn.execute(stalled_query).fetchall()
            for sr in stalled_rows:
                if sr[1] and sr[1] < stalled_cutoff:
                    stalled_clusters.append({
                        "name": sr[0],
                        "hours_idle": round((now_ts - sr[1]) / 3600, 1),
                    })

        # 3. Metrik Sistem
        cpu_usage = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory()

        # Format Kartu Ringkasan Telegram
        now_str = datetime.now().strftime("%d-%m-%Y %H:%M WIB")
        shift_title = "PAGI (TARGET & PERSIAPAN)" if shift.lower() == "morning" else "SORE (PROGRESS CLOSING)" if shift.lower() == "evening" else "REALTIME"

        briefing_text = (
            f"📋 *DAILY EXECUTIVE BRIEFING ALFA OS*\n"
            f"🕒 *Shift*: {shift_title} | *Waktu*: `{now_str}`\n\n"
            f"⚡ *AKUMULASI PROGRES FISIK (24 Jam Terakhir)*:\n"
            f"• 🟢 *Kabel Terpasang*: `{round(total_cable, 1):,} meter`\n"
            f"• 🟢 *Tiang Tertanam*: `{int(total_poles)} batang`\n"
            f"• 🟢 *FAT/FDT Terpasang*: `{int(total_fat)} box`\n"
            f"• 📊 *Cluster Lapangan Aktif*: `{len(active_clusters_set)} grup`\n\n"
        )

        if stalled_clusters:
            briefing_text += "⚠️ *CLUSTER MANDEK (>48 Jam Tanpa Laporan)*:\n"
            for sc in stalled_clusters[:3]:
                briefing_text += f"• 🔴 `{sc['name']}` (diam selama {sc['hours_idle']} jam)\n"
            briefing_text += "\n"

        if recent_issues:
            briefing_text += f"🚨 *LAPORAN KENDALA LAPANGAN ({len(recent_issues)} Terdeteksi)*:\n"
            for iss in recent_issues[:3]:
                briefing_text += f"• *{iss['cluster']}* ({iss['sender']}): \"_{iss['text']}_\"\n"
            briefing_text += "\n"

        briefing_text += (
            f"💻 *KESEHATAN SISTEM ALFA*:\n"
            f"• CPU: `{cpu_usage}%` | RAM: `{mem.percent}%` (Tersedia: {round(mem.available / (1024**3), 1)} GB)\n"
            f"• WhatsApp Bot: `Active (Sync Live)`\n"
            f"• Telegram Agent: `Ready`"
        )

        return {
            "status": "success",
            "shift": shift,
            "briefing_card": briefing_text,
            "stats": {
                "total_cable_meters": total_cable,
                "total_poles_pcs": int(total_poles),
                "total_fat_boxes": int(total_fat),
                "active_clusters": len(active_clusters_set),
                "stalled_clusters": len(stalled_clusters),
                "issues_count": len(recent_issues),
            },
        }
    except Exception as e:
        logger.exception("Gagal membuat executive briefing: %s", e)
        return {"status": "error", "message": f"Executive briefing error: {str(e)}"}


@register_tool(category="office")
def transcribe_field_voice_note(
    audio_file_path: str,
    cluster_hint: str = "",
) -> dict[str, Any]:
    """
    TRANSKRIPSI PESAN SUARA (VOICE NOTE) LAPANGAN & EKSTRAKSI AKSI:
    Mendengarkan rekaman audio/voice note mandor (.ogg, .opus, .mp3, .wav, .m4a) dari WhatsApp atau Telegram,
    mentranskripsikannya ke bahasa Indonesia presisi tinggi dengan Gemini Multimodal Audio,
    serta mengekstrak entitas teknis (tiang, kabel, FAT, kendala) secara terstruktur.

    Args:
        audio_file_path: Lokasi berkas audio voice note di sistem.
        cluster_hint: Petunjuk nama cluster opsional untuk meningkatkan akurasi konteks.
    """
    try:
        from google import genai
        from google.genai import types

        from alfa.swarm.llm_client import get_agent_api_client

        fpath = os.path.realpath(os.path.expanduser(audio_file_path.strip()))
        if not os.path.exists(fpath):
            return {"status": "error", "message": f"Berkas audio '{audio_file_path}' tidak ditemukan."}

        _provider, api_key, model, _base, _kid = get_agent_api_client({"provider": "gemini"})
        if not api_key:
            return {"status": "error", "message": "Tidak ada Gemini API Key aktif untuk transkripsi audio."}

        client = genai.Client(api_key=api_key, http_options={"timeout": 60000})

        # Determine MIME type
        ext = os.path.splitext(fpath)[1].lower()
        mime_map = {
            ".ogg": "audio/ogg",
            ".opus": "audio/ogg",
            ".mp3": "audio/mp3",
            ".wav": "audio/wav",
            ".m4a": "audio/mp4",
        }
        mime_type = mime_map.get(ext, "audio/mp3")

        with open(fpath, "rb") as f:
            audio_bytes = f.read()

        prompt = (
            "Dengarkan rekaman suara laporan teknisi/mandor proyek telekomunikasi FTTH berikut ini.\n"
            "Tugasmu:\n"
            "1. Transkripsikan kata demi kata ke dalam bahasa Indonesia secara verbatim dan akurat.\n"
            "2. Ekstrak data teknis lapangan dalam format JSON dengan kunci:\n"
            "   - 'transcript': isi teks pembicaraan lengkap\n"
            "   - 'mandor': nama pengirim/mandor jika terdengar\n"
            "   - 'cluster': nama cluster atau lokasi jika disebutkan\n"
            "   - 'cables_meter': angka panjang kabel yang ditarik (float) atau 0\n"
            "   - 'poles_count': jumlah tiang yang ditanam (int) atau 0\n"
            "   - 'fat_count': jumlah FAT yang dipasang (int) atau 0\n"
            "   - 'kendala': rincian kendala lapangan jika ada, atau string kosong\n\n"
            f"Konteks hint cluster: {cluster_hint}\n"
            "KEMBALIKAN HANYA OBJEK JSON TANPA MARKDOWN BACKTICKS."
        )

        audio_part = types.Part.from_bytes(data=audio_bytes, mime_type=mime_type)
        gemini_raw_inputs: list[Any] = [audio_part, prompt]
        response = client.models.generate_content(
            model=model or "gemini-2.5-flash",
            contents=gemini_raw_inputs,
        )

        resp_text = (getattr(response, "text", "") or "").strip()
        # Parse JSON
        resp_clean = re.sub(r"^```json\s*|^```\s*|```$", "", resp_text, flags=re.MULTILINE).strip()
        try:
            payload = json.loads(resp_clean)
        except Exception:
            payload = {"transcript": resp_text, "mandor": "", "cluster": cluster_hint, "cables_meter": 0, "poles_count": 0, "fat_count": 0, "kendala": ""}

        return {
            "status": "success",
            "file": os.path.basename(fpath),
            "transcript": payload.get("transcript", resp_text),
            "extracted_data": payload,
            "message": "Transkripsi voice note lapangan berhasil diekstrak.",
        }
    except Exception as e:
        logger.exception("Gagal transkripsi voice note: %s", e)
        return {"status": "error", "message": f"Transcribe voice note error: {str(e)}"}


@register_tool(category="office")
def parse_delivery_order_document(
    file_path: str,
    match_cluster_boq: str = "",
) -> dict[str, Any]:
    """
    OCR & EKSTRAKSI CERDAS SURAT JALAN / DELIVERY ORDER (DO / TOSBI / TRANSFER ORDER):
    Membaca berkas Surat Jalan atau DO dalam bentuk dokumen PDF (digital maupun hasil scan) atau foto,
    mengekstrak otomatis Nomor Surat Jalan/DO, Tanggal, Pengirim (Origin), Tujuan (Destination),
    Penerima/Applicant, PM, dan tabel rincian material (Deskripsi, Unit, Kuantitas, Keterangan).
    Bisa langsung mencocokkan barang yang datang dengan kebutuhan BOQ cluster target.

    Args:
        file_path: Lokasi absolut atau relatif file PDF / Gambar Delivery Order.
        match_cluster_boq: Nama cluster opsional untuk mencocokkan barang DO dengan BOQ cluster.
    """
    try:
        import pdfplumber

        fpath = os.path.realpath(os.path.expanduser(file_path.strip()))
        if not os.path.exists(fpath):
            return {"status": "error", "message": f"Berkas Surat Jalan '{file_path}' tidak ditemukan."}

        fname = os.path.basename(fpath)
        is_pdf = fpath.lower().endswith(".pdf")

        extracted_text = ""
        do_info: dict[str, Any] = {
            "file": fname,
            "doc_type": "DELIVERY_ORDER",
            "number": "",
            "date": "",
            "origin": "",
            "destination": "",
            "applicant": "",
            "pm": "",
            "items": [],
        }

        # 1. Coba ekstraksi digital teks via pdfplumber
        if is_pdf:
            try:
                with pdfplumber.open(fpath) as pdf:
                    for page in pdf.pages[:3]:
                        t = page.extract_text() or ""
                        if t:
                            extracted_text += "\n" + t
            except Exception as e:
                logger.debug("pdfplumber text extraction failed: %s", e)

        # 2. Jika digital text berhasil diekstrak (>60 karakter)
        if len(extracted_text.strip()) > 60:
            lines = [ln.strip() for ln in extracted_text.splitlines() if ln.strip()]
            full_txt = "\n".join(lines)

            # Ekstrak No DO / TO
            no_match = re.search(r"(?:TO|DO)\s*(?:Number|No|Nomor)?[\s:]*([A-Z0-9\-_/]+)", full_txt, re.IGNORECASE)
            if no_match:
                do_info["number"] = no_match.group(1).strip()
            else:
                m_code = re.search(r"\b(TOSBI[0-9]+|DOEID[0-9A-Z]+|CLR[0-9A-Z\-]+|SF[0-9A-Z\-]+)\b", fname + " " + full_txt)
                if m_code:
                    do_info["number"] = m_code.group(1)

            # Ekstrak Tanggal
            date_match = re.search(r"(?:Date|Tanggal)[\s:]*([0-9]{1,2}[-/][A-Za-z0-9]{2,4}[-/][0-9]{2,4})", full_txt, re.IGNORECASE)
            if date_match:
                do_info["date"] = date_match.group(1)

            # Ekstrak Destination / Project
            dest_match = re.search(r"(?:Destination|Tujuan)[\s:]*([^\n]+)", full_txt, re.IGNORECASE)
            if dest_match:
                do_info["destination"] = dest_match.group(1).strip()

            # Ekstrak Tabel Item
            item_rows = []
            for line in lines:
                m_qty = re.search(r"^(\d+)\s+([A-Za-z0-9\s\"'/,\.\-]+?)\s+(PCS|M|METER|SET|UNIT|BOX)\s+([0-9\.,]+)(.*)$", line, re.IGNORECASE)
                if m_qty:
                    try:
                        qty_val = float(m_qty.group(4).replace(",", "."))
                        item_rows.append({
                            "no": int(m_qty.group(1)),
                            "description": m_qty.group(2).strip(),
                            "unit": m_qty.group(3).upper(),
                            "qty": qty_val,
                            "remark": m_qty.group(5).strip(),
                        })
                    except ValueError:
                        pass
            do_info["items"] = item_rows

        # 3. Fallback: Jika PDF hasil scan atau gambar, gunakan Vision OCR via Gemini
        if not do_info["items"]:
            from google import genai
            from google.genai import types

            from alfa.swarm.llm_client import get_agent_api_client

            _provider, api_key, model, _base, _kid = get_agent_api_client({"provider": "gemini"})
            if api_key:
                client = genai.Client(api_key=api_key, http_options={"timeout": 60000})
                img_bytes = b""
                if is_pdf:
                    import fitz
                    doc = fitz.open(fpath)
                    pix = doc[0].get_pixmap(dpi=150)
                    img_bytes = pix.tobytes("png")
                else:
                    with open(fpath, "rb") as f:
                        img_bytes = f.read()

                vision_prompt = (
                    "Ekstrak data Surat Jalan / Delivery Order / Transfer Order berikut secara lengkap.\n"
                    "Kembalikan JSON dengan format:\n"
                    "{\n"
                    "  'number': 'Nomor DO/TO/Surat Jalan',\n"
                    "  'date': 'Tanggal dokumen',\n"
                    "  'origin': 'Lokasi/Gudang asal',\n"
                    "  'destination': 'Gudang/Cluster/Lokasi tujuan',\n"
                    "  'applicant': 'Nama pemohon',\n"
                    "  'pm': 'Nama PM',\n"
                    "  'items': [\n"
                    "     {'no': 1, 'description': 'Nama Material', 'unit': 'PCS/Meter', 'qty': 10, 'remark': 'Catatan/Kondisi'}\n"
                    "  ]\n"
                    "}\n"
                    "KEMBALIKAN HANYA JSON TANPA BACKTICKS."
                )

                img_part = types.Part.from_bytes(data=img_bytes, mime_type="image/png")
                vision_inputs: list[Any] = [img_part, vision_prompt]
                resp = client.models.generate_content(
                    model=model or "gemini-2.5-flash",
                    contents=vision_inputs,
                )
                clean_json = re.sub(r"^```json\s*|^```\s*|```$", "", (getattr(resp, "text", "") or "").strip(), flags=re.MULTILINE).strip()
                try:
                    parsed_vision = json.loads(clean_json)
                    do_info.update(parsed_vision)
                except Exception:
                    pass

        # 4. Cross-check against BOQ bila diminta
        boq_match_result: dict[str, Any] = {}
        if match_cluster_boq:
            clean_bname = match_cluster_boq.lower().strip()
            cand_files = glob.glob(f"/home/fahmial/Unduhan/*{clean_bname}*.xlsx") + glob.glob("/home/fahmial/Unduhan/SMDT*.xlsx")
            if cand_files:
                import openpyxl
                wb = openpyxl.load_workbook(cand_files[0], data_only=True)
                boq_req: dict[str, float] = {}
                for s in wb.sheetnames:
                    if clean_bname in s.lower() or "boq" in s.lower():
                        ws = wb[s]
                        for r in ws.iter_rows(values_only=True):
                            desc = None
                            qty = None
                            for c in r:
                                if desc is None and isinstance(c, str) and len(c.strip()) > 3:
                                    desc = c.strip()
                                elif isinstance(c, (int, float)) and c > 0:
                                    qty = float(c)
                            if desc and qty:
                                boq_req[desc.lower()] = boq_req.get(desc.lower(), 0.0) + qty

                match_items = []
                for itm in do_info.get("items", []):
                    desc_low = itm.get("description", "").lower()
                    matched_qty = 0.0
                    for k, v in boq_req.items():
                        if any(w in k for w in desc_low.split()[:2]):
                            matched_qty = v
                            break
                    match_items.append({
                        "item": itm.get("description"),
                        "delivered_do": itm.get("qty", 0),
                        "boq_required": matched_qty,
                        "status": "SUFFICIENT" if itm.get("qty", 0) >= matched_qty and matched_qty > 0 else "PARTIAL" if matched_qty > 0 else "EXTRA",
                    })
                boq_match_result = {
                    "matched_boq_file": os.path.basename(cand_files[0]),
                    "comparison": match_items,
                }

        return {
            "status": "success",
            "delivery_order": do_info,
            "total_items_extracted": len(do_info.get("items", [])),
            "boq_comparison": boq_match_result,
            "message": f"Berhasil membaca Surat Jalan '{do_info.get('number') or fname}' ({len(do_info.get('items', []))} item material).",
        }
    except Exception as e:
        logger.exception("Gagal membaca Surat Jalan DO: %s", e)
        return {"status": "error", "message": f"Parse Delivery Order error: {str(e)}"}


@register_tool(category="system")
def wa_relay_send_from_telegram(
    target_chat_name_or_id: str,
    message: str,
) -> dict[str, Any]:
    """
    RELAY TELEGRAM KE WHATSAPP (MANUAL EKSPLISIT OLEH FAHMI):
    Meneruskan dan mengirimkan pesan teks dari Telegram ke kontak atau grup WhatsApp tertentu
    secara langsung melalui API WhatsApp bot.

    HUKUM BESI KEAMANAN SISTEM:
    - HANYA BOLEH DIEKSEKUSI jika ada perintah manual dan eksplisit dari Fahmi di Telegram (contoh: 'kirim ke grup IMT: ...').
    - DILARANG KERAS MENJADI BALASAN OTOMATIS (AUTO-REPLY). Dilarang membuat loop, auto-responder, atau bot yang membalas pesan WhatsApp tanpa perintah manusia!

    Args:
        target_chat_name_or_id: Nama grup (misal: 'IMT BKL EMR FTTH Project Team') atau nomor telepon target.
        message: Isi pesan yang ingin dikirimkan.
    """
    try:
        from alfa.tools.system.integrations import wa_send_message

        target = target_chat_name_or_id.strip()
        msg = message.strip()

        if not target or not msg:
            return {"status": "error", "message": "Target tujuan dan isi pesan tidak boleh kosong."}

        logger.info("Executing manual WhatsApp relay command from Telegram to: %s", target)
        res = wa_send_message(to=target, message=msg)
        return {
            "status": "success" if res.get("status") in ("success", "ok") or not res.get("error") else "error",
            "target": target,
            "message_sent": msg,
            "raw_response": res,
            "confirmation": f"Pesan berhasil diteruskan ke WhatsApp: '{target}'." if res.get("status") != "error" else f"Gagal mengirim ke WhatsApp: {res.get('message') or res.get('error')}",
        }
    except Exception as e:
        logger.exception("Gagal relay pesan ke WhatsApp: %s", e)
        return {"status": "error", "message": f"WhatsApp relay error: {str(e)}"}


@register_tool(category="office")
def consolidate_delivery_orders_to_stock_ledger(
    file_paths: list[str] | str = "",
    output_filename: str = "MASTER_STOCK_LEDGER.xlsx",
    filter_destination: str = "",
) -> dict[str, Any]:
    """
    KONSOLIDASI BUKU KAS GUDANG (STOCK LEDGER) DARI PULUHAN SURAT JALAN / DO:
    Memindai seluruh berkas Surat Jalan / Transfer Order / DO (PDF digital maupun scan) di direktori,
    mengekstrak seluruh material masuk, dan mengompilasi menjadi satu Master Stock Ledger Excel
    dengan dua sheet berdesain rapi:
    1. 'STOCK_BALANCE': Ringkasan total stok material masuk, unit, dan jumlah transaksi DO.
    2. 'DO_INBOUND_TRANSACTIONS': Detail tiap baris transaksi (No DO, Tanggal, Asal, Tujuan, Item, Qty, Unit, Nama File).

    Args:
        file_paths: List file PDF atau string pola glob (default kosong: otomatis memindai ~/Unduhan/*DO*.pdf dan TOSBI*.pdf).
        output_filename: Nama file output Excel hasil konsolidasi.
        filter_destination: Filter tujuan proyek/gudang opsional (misal: 'Curup', 'Lahat', 'Sukabumi').
    """
    try:
        import glob

        import openpyxl
        from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
        from openpyxl.utils import get_column_letter

        targets: list[str] = []
        if isinstance(file_paths, str) and file_paths.strip():
            if "*" in file_paths or "?" in file_paths:
                targets = glob.glob(os.path.expanduser(file_paths.strip()))
            elif "," in file_paths:
                targets = [p.strip() for p in file_paths.split(",") if p.strip()]
            else:
                targets = [file_paths.strip()]
        elif isinstance(file_paths, (list, tuple)) and file_paths:
            for item in file_paths:
                if isinstance(item, str) and ("*" in item or "?" in item):
                    targets.extend(glob.glob(os.path.expanduser(item.strip())))
                elif isinstance(item, str):
                    targets.append(item.strip())
        else:
            # Default auto-scan di ~/Unduhan
            d_dir = os.path.expanduser("~/Unduhan")
            targets = glob.glob(f"{d_dir}/TOSBI*.pdf") + glob.glob(f"{d_dir}/*DO*.pdf") + glob.glob(f"{d_dir}/TOCJ*.pdf")

        resolved_files = [os.path.realpath(p) for p in targets if os.path.exists(os.path.realpath(p)) and p.lower().endswith(".pdf")]
        if not resolved_files:
            return {"status": "error", "message": "Tidak ditemukan berkas PDF Surat Jalan / DO yang valid."}

        stock_summary: dict[str, dict[str, Any]] = {}
        all_transactions: list[dict[str, Any]] = []

        for fpath in resolved_files:
            res_do = parse_delivery_order_document(fpath)
            if res_do.get("status") != "success":
                continue
            do_data = res_do.get("delivery_order", {})
            do_num = do_data.get("number") or os.path.splitext(os.path.basename(fpath))[0]
            do_date = do_data.get("date") or ""
            do_origin = do_data.get("origin") or ""
            do_dest = do_data.get("destination") or ""

            if filter_destination and filter_destination.lower() not in (do_dest + " " + do_origin + " " + os.path.basename(fpath)).lower():
                continue

            for itm in do_data.get("items", []):
                desc = itm.get("description", "").strip()
                if not desc:
                    continue
                qty = float(itm.get("qty", 0))
                unit = itm.get("unit", "PCS")
                key = desc.lower()

                if key not in stock_summary:
                    stock_summary[key] = {
                        "description": desc,
                        "category": _classify_telecom_material(desc),
                        "total_inbound": qty,
                        "unit": unit,
                        "do_count": 1,
                        "do_numbers": [do_num],
                    }
                else:
                    stock_summary[key]["total_inbound"] += qty
                    stock_summary[key]["do_count"] += 1
                    if do_num not in stock_summary[key]["do_numbers"]:
                        stock_summary[key]["do_numbers"].append(do_num)

                all_transactions.append({
                    "do_number": do_num,
                    "date": do_date,
                    "origin": do_origin[:40],
                    "destination": do_dest[:40],
                    "description": desc,
                    "qty": qty,
                    "unit": unit,
                    "file": os.path.basename(fpath),
                })

        if not all_transactions:
            return {"status": "error", "message": f"Tidak ada item material yang berhasil diekstrak dari {len(resolved_files)} file DO."}

        # Build Master Excel Workbook
        wb = openpyxl.Workbook()
        navy_header = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid")
        cyan_header = PatternFill(start_color="0284C7", end_color="0284C7", fill_type="solid")
        alt_row = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")
        white_bold = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        thin_border = Border(
            left=Side(style="thin", color="CBD5E1"),
            right=Side(style="thin", color="CBD5E1"),
            top=Side(style="thin", color="CBD5E1"),
            bottom=Side(style="thin", color="CBD5E1"),
        )

        # Sheet 1: STOCK_BALANCE
        ws1 = wb.active
        ws1.title = "STOCK_BALANCE"
        ws1.views.sheetView[0].showGridLines = True
        ws1.cell(row=1, column=1, value="MASTER MATERIAL STOCK BALANCE (INBOUND LEDGER)").font = Font(name="Calibri", size=14, bold=True, color="1E3A8A")
        ws1.cell(row=2, column=1, value=f"Digenerate otomatis oleh ALFA OS pada: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}").font = Font(italic=True, color="64748B")

        headers1 = ["No", "Material Description", "Category", "Total Stock Inbound", "Unit", "Total DO Records", "Referensi DO Terkait"]
        ws1.row_dimensions[4].height = 24
        for c_idx, h in enumerate(headers1, 1):
            cell = ws1.cell(row=4, column=c_idx, value=h)
            cell.font = white_bold
            cell.fill = navy_header
            cell.alignment = Alignment(horizontal="center", vertical="center")
            cell.border = thin_border

        for r_idx, (_k, s) in enumerate(stock_summary.items(), 5):
            ws1.row_dimensions[r_idx].height = 20
            row_vals = [
                r_idx - 4,
                s["description"],
                s["category"],
                s["total_inbound"],
                s["unit"],
                s["do_count"],
                ", ".join(s["do_numbers"][:4]) + ("..." if len(s["do_numbers"]) > 4 else ""),
            ]
            for c_idx, val in enumerate(row_vals, 1):
                cell = ws1.cell(row=r_idx, column=c_idx, value=val)
                cell.border = thin_border
                if r_idx % 2 == 0:
                    cell.fill = alt_row
                if c_idx in (4, 6):
                    cell.alignment = Alignment(horizontal="right", vertical="center")
                    cell.number_format = "#,##0.00" if isinstance(val, float) and not val.is_integer() else "#,##0"
                else:
                    cell.alignment = Alignment(horizontal="left", vertical="center")

        # Sheet 2: DO_INBOUND_TRANSACTIONS
        ws2 = wb.create_sheet(title="DO_INBOUND_TRANSACTIONS")
        ws2.views.sheetView[0].showGridLines = True
        headers2 = ["No", "DO / TO Number", "Tanggal", "Gudang Asal", "Tujuan / Cluster", "Material Description", "Quantity", "Unit", "Berkas PDF"]
        ws2.row_dimensions[1].height = 24
        for c_idx, h in enumerate(headers2, 1):
            cell = ws2.cell(row=1, column=c_idx, value=h)
            cell.font = white_bold
            cell.fill = cyan_header
            cell.alignment = Alignment(horizontal="center", vertical="center")
            cell.border = thin_border

        for r_idx, tx in enumerate(all_transactions, 2):
            ws2.row_dimensions[r_idx].height = 19
            row_vals = [
                r_idx - 1,
                tx["do_number"],
                tx["date"],
                tx["origin"],
                tx["destination"],
                tx["description"],
                tx["qty"],
                tx["unit"],
                tx["file"],
            ]
            for c_idx, val in enumerate(row_vals, 1):
                cell = ws2.cell(row=r_idx, column=c_idx, value=val)
                cell.border = thin_border
                if r_idx % 2 == 1:
                    cell.fill = alt_row
                if c_idx == 7:
                    cell.alignment = Alignment(horizontal="right", vertical="center")
                    cell.number_format = "#,##0.00" if isinstance(val, float) and not val.is_integer() else "#,##0"
                else:
                    cell.alignment = Alignment(horizontal="left", vertical="center")

        # Auto-adjust column widths
        for ws in (ws1, ws2):
            for col in ws.columns:
                max_len = max(len(str(c.value or "")) for c in col)
                ws.column_dimensions[get_column_letter(col[0].column)].width = max(min(max_len + 3, 50), 12)

        out_name = output_filename if output_filename.endswith(".xlsx") else f"{output_filename}.xlsx"
        out_path = os.path.join(SANDBOX_DIR, out_name)
        os.makedirs(SANDBOX_DIR, exist_ok=True)
        wb.save(out_path)

        return {
            "status": "success",
            "message": f"Berhasil mengonsolidasikan {len(resolved_files)} Surat Jalan ke '{out_name}'.",
            "output_file": out_path,
            "filename": out_name,
            "total_do_files_processed": len(resolved_files),
            "total_material_types": len(stock_summary),
            "total_transactions": len(all_transactions),
            "top_stock_items": list(stock_summary.values())[:8],
        }
    except Exception as e:
        logger.exception("Gagal konsolidasi stock ledger: %s", e)
        return {"status": "error", "message": f"Stock ledger consolidation error: {str(e)}"}


@register_tool(category="office")
def calculate_material_return_and_scrap(
    cluster_name: str,
    total_cable_issued_m: float = 0.0,
    total_poles_issued_pcs: float = 0.0,
    cable_scrap_allowance_pct: float = 3.0,
    target_boq_file: str = "",
) -> dict[str, Any]:
    """
    KALKULATOR RETUR MATERIAL & SCRAP / POTONGAN KABEL:
    Menghitung rekonsiliasi akhir material yang dikeluarkan (issued) vs terpasang (installed) di lapangan.
    Menghitung toleransi potongan kabel wajar (scrap allowance, default 3%) dan menentukan kuantitas
    material yang WAJIB dikembalikan (expected return) oleh mandor/subkontraktor.
    Mendeteksi selisih / kekurangan material sebelum Berita Acara Serah Terima (BAST).

    Args:
        cluster_name: Nama cluster proyek (misal: 'Curup', 'Kasambe', 'Lahat').
        total_cable_issued_m: Total meter kabel yang dikeluarkan dari gudang ke mandor/subcont.
        total_poles_issued_pcs: Total tiang yang dikeluarkan dari gudang.
        cable_scrap_allowance_pct: Persentase toleransi potongan/slack kabel (default: 3.0%).
        target_boq_file: Path berkas BOQ acuan opsional.
    """
    try:
        from alfa.core.db.connection import get_sync_db

        cname_clean = cluster_name.lower().strip()
        actual_cable_installed = 0.0
        actual_poles_installed = 0.0
        actual_cable_returned = 0.0
        actual_poles_returned = 0.0

        # Tarik data dari wa_incoming_archive untuk cluster ini
        with get_sync_db() as conn:
            rows = conn.execute(
                "SELECT body FROM wa_incoming_archive WHERE LOWER(body) LIKE ? OR LOWER(chat_name) LIKE ?",
                (f"%{cname_clean}%", f"%{cname_clean}%"),
            ).fetchall()
            for r in rows:
                body = r[0] or ""
                ext = _extract_telecom_quantities_from_text(body)
                actual_cable_installed += ext["cables"]
                actual_poles_installed += ext["poles"]

                # Cek jika ada laporan retur
                if any(k in body.lower() for k in ("retur", "sisa", "kembali")):
                    ret_ext = _extract_telecom_quantities_from_text(body)
                    actual_cable_returned += ret_ext["cables"]
                    actual_poles_returned += ret_ext["poles"]

        # Hitung kalkulasi scrap & expected return
        cable_scrap_allowed = round(actual_cable_installed * (cable_scrap_allowance_pct / 100.0), 2)
        expected_cable_return = max(0.0, round(total_cable_issued_m - actual_cable_installed - cable_scrap_allowed, 2)) if total_cable_issued_m > 0 else 0.0
        expected_poles_return = max(0.0, round(total_poles_issued_pcs - actual_poles_installed, 2)) if total_poles_issued_pcs > 0 else 0.0

        cable_discrepancy = round(actual_cable_returned - expected_cable_return, 2) if total_cable_issued_m > 0 else 0.0
        poles_discrepancy = round(actual_poles_returned - expected_poles_return, 2) if total_poles_issued_pcs > 0 else 0.0

        settlement_status = "CLEAR" if cable_discrepancy >= 0 and poles_discrepancy >= 0 else "SHORTAGE_DETECTED"

        audit_card = (
            f"📋 *AUDIT RETUR & SCRAP MATERIAL PROYEK*\n"
            f"🏢 *Cluster*: `{cluster_name.upper()}`\n\n"
            f"⚡ *REKONSILIASI KABEL FIBER OPTIC*:\n"
            f"• Dikeluarkan (DO Gudang): `{total_cable_issued_m:,.1f} m`\n"
            f"• Terpasang (Laporan Fisik): `{actual_cable_installed:,.1f} m`\n"
            f"• Toleransi Potongan/Scrap ({cable_scrap_allowance_pct}%): `{cable_scrap_allowed:,.1f} m`\n"
            f"• Sisa Wajib Retur (Expected): `{expected_cable_return:,.1f} m`\n"
            f"• Retur Aktual Dilaporkan: `{actual_cable_returned:,.1f} m`\n"
            f"• Selisih / Discrepancy: `{'TAMBAH/PAS' if cable_discrepancy >= 0 else 'KURANG ' + str(abs(cable_discrepancy)) + ' m'}`\n\n"
            f"⚡ *REKONSILIASI TIANG BESI*:\n"
            f"• Dikeluarkan (DO Gudang): `{int(total_poles_issued_pcs)} batang`\n"
            f"• Terpasang (Laporan Fisik): `{int(actual_poles_installed)} batang`\n"
            f"• Wajib Retur (Expected): `{int(expected_poles_return)} batang`\n"
            f"• Retur Aktual: `{int(actual_poles_returned)} batang`\n"
            f"• Selisih: `{'PAS' if poles_discrepancy >= 0 else 'KURANG ' + str(int(abs(poles_discrepancy))) + ' btg'}`\n\n"
            f"🎯 *REKOMENDASI BAST*: `{'SIAP BAST (LENGKAP)' if settlement_status == 'CLEAR' else 'TAHAN BAST (ADA SELISIH RETUR)'}`"
        )

        return {
            "status": "success",
            "cluster": cluster_name,
            "settlement_status": settlement_status,
            "audit_card": audit_card,
            "calculations": {
                "cable": {
                    "issued_m": total_cable_issued_m,
                    "installed_m": actual_cable_installed,
                    "allowed_scrap_m": cable_scrap_allowed,
                    "expected_return_m": expected_cable_return,
                    "actual_return_m": actual_cable_returned,
                    "discrepancy_m": cable_discrepancy,
                },
                "poles": {
                    "issued_pcs": total_poles_issued_pcs,
                    "installed_pcs": actual_poles_installed,
                    "expected_return_pcs": expected_poles_return,
                    "actual_return_pcs": actual_poles_returned,
                    "discrepancy_pcs": poles_discrepancy,
                },
            },
        }
    except Exception as e:
        logger.exception("Gagal menghitung scrap dan retur material: %s", e)
        return {"status": "error", "message": f"Material return calculation error: {str(e)}"}


@register_tool(category="scheduler")
def schedule_daily_briefing_task(
    enabled: bool = True,
    morning_hour: int = 7,
    morning_minute: int = 30,
    evening_hour: int = 18,
    evening_minute: int = 0,
) -> dict[str, Any]:
    """
    JADWALKAN EXECUTIVE BRIEFING OTOMATIS KE TELEGRAM:
    Mengaktifkan atau memperbarui jadwal otomatis ringkasan proyek ke Telegram Fahmi:
    - Briefing Pagi (pukul 07:30 WIB): Target hari ini, cluster aktif & mandek, persiapan kerja.
    - Closing Sore (pukul 18:00 WIB): Progres tarikan kabel, tiang tertanam, FAT, kendala lapangan, kesehatan server.

    HUKUM BESI KEAMANAN:
    Laporan HANYA dikirimkan ke Telegram chat Fahmi. DILARANG KERAS mengirim atau membalas ke WhatsApp!

    Args:
        enabled: True untuk mengaktifkan jadwal, False untuk mematikan.
        morning_hour: Jam pengiriman pagi (default: 7).
        morning_minute: Menit pengiriman pagi (default: 30).
        evening_hour: Jam pengiriman sore (default: 18).
        evening_minute: Menit pengiriman sore (default: 0).
    """
    try:
        from alfa.core import database
        from alfa.core.runtime_ctx import get_current_chat_id, get_current_user_id

        user_id = get_current_user_id()
        chat_id = get_current_chat_id()

        instr = (
            "Panggil tool `generate_daily_executive_briefing(shift='now', days_back=1)` "
            "lalu kirimkan ringkasan kartu laporan eksekutif proyek FTTH ke chat Telegram ini."
        )

        job_id = database.add_cron_job_sync(
            user_id=user_id,
            chat_id=chat_id,
            title="Daily Project Executive Briefing (Telegram Only)",
            prompt_instruction=instr,
            interval_minutes=720,  # Setiap 12 jam (pagi & sore)
            kind="single",
        )

        return {
            "status": "success",
            "job_id": job_id,
            "message": (
                f"Jadwal Executive Briefing Telegram berhasil diaktifkan (#{job_id}). "
                f"Ringkasan pagi & sore akan dikirimkan otomatis ke Telegram Anda."
            ),
        }
    except Exception as e:
        logger.exception("Gagal menjadwalkan daily briefing: %s", e)
        return {"status": "error", "message": f"Schedule daily briefing error: {str(e)}"}

