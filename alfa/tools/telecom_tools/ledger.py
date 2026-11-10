"""Stock ledger consolidation and material return/scrap calculation."""
from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any

from alfa.tools.registry import register_tool
from alfa.tools.system_tools import SANDBOX_DIR
from alfa.tools.telecom_tools._common import (
    _classify_telecom_material,
    _extract_telecom_quantities_from_text,
    is_to_group,
)
from alfa.tools.telecom_tools.documents import parse_delivery_order_document

logger = logging.getLogger("AgentTools.Telecom")

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
                "SELECT body, chat_name FROM wa_incoming_archive WHERE LOWER(body) LIKE ? OR LOWER(chat_name) LIKE ?",
                (f"%{cname_clean}%", f"%{cname_clean}%"),
            ).fetchall()
            for r in rows:
                if is_to_group(r[1] or ""):
                    continue
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
