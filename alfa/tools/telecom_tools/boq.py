"""BOQ consolidation, revision diff, field reconciliation, anomaly check."""
from __future__ import annotations

import glob
import logging
import os
import re
import sqlite3
from datetime import datetime
from typing import Any

from alfa.tools.registry import register_tool
from alfa.tools.system_tools import SANDBOX_DIR
from alfa.tools.telecom_tools._common import (
    _classify_telecom_material,
    _extract_telecom_quantities_from_text,
    is_to_group,
)

logger = logging.getLogger("AgentTools.Telecom")

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
            except (TypeError, ValueError, KeyError, IndexError, AttributeError, RuntimeError, OSError, ArithmeticError, UnicodeError, sqlite3.Error) as e:
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
    except (TypeError, ValueError, KeyError, IndexError, AttributeError, RuntimeError, OSError, ArithmeticError, UnicodeError, sqlite3.Error) as e:
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
    except (TypeError, ValueError, KeyError, IndexError, AttributeError, RuntimeError, OSError, ArithmeticError, UnicodeError, sqlite3.Error) as e:
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
            unduhan_dir = os.path.expanduser("~/Unduhan")
            cand_files = glob.glob(os.path.join(unduhan_dir, f"*{clean_cname}*.xlsx")) + glob.glob(
                os.path.join(unduhan_dir, "SMDT*.xlsx")
            )
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
                if is_to_group(r[0] or ""):
                    continue
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
    except (TypeError, ValueError, KeyError, IndexError, AttributeError, RuntimeError, OSError, ArithmeticError, UnicodeError, sqlite3.Error) as e:
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
                if is_to_group(c_name or ""):
                    continue
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
                if is_to_group(ir[0] or ""):
                    continue
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
    except (TypeError, ValueError, KeyError, IndexError, AttributeError, RuntimeError, OSError, ArithmeticError, UnicodeError, sqlite3.Error) as e:
        logger.exception("Gagal memeriksa anomali proyek: %s", e)
        return {"status": "error", "message": f"Anomaly check error: {str(e)}"}
