"""
Office documents (Excel, PowerPoint), dataset analysis/charts, and text translation.
"""

import csv
import json
import logging
import os
import shutil
import time
from pathlib import Path
from typing import Any
from zipfile import BadZipFile

from openpyxl.utils.exceptions import InvalidFileException

from alfa.tools.registry import register_tool
from alfa.tools.system_tools import SANDBOX_DIR

#: Error realistis saat mem-parse header CSV.
_MD_CSV_ERR = (ValueError, TypeError, AttributeError)

#: Error realistis saat mem-parse JSON.
_MD_JSON_ERR = (json.JSONDecodeError, TypeError, ValueError)

#: Error realistis untuk konversi berkas.
_MD_FILE_ERR = (OSError, ValueError, TypeError, RuntimeError, UnicodeError)

#: Error realistis saat membuat grafik.
_MD_CHART_ERR = (OSError, ValueError, TypeError, RuntimeError)

class _ExcelRowsTypeError(TypeError):
    """Tipe ``rows_json`` tidak didukung."""

    def __init__(self) -> None:
        super().__init__("rows_json harus berupa array JSON.")


#: Error realistis saat membaca/menulis workbook Excel.
_XL_ERR = (
    OSError,
    ValueError,
    TypeError,
    KeyError,
    IndexError,
    RuntimeError,
    UnicodeError,
    BadZipFile,
    InvalidFileException,
    ImportError,
)

logger = logging.getLogger("AgentTools.Media.Documents")


@register_tool(category="office")
def generate_excel_spreadsheet(
    sheet_title: str, headers: list[str], rows_json: str, filename: str = "data.xlsx"
) -> dict[str, Any]:
    """
    Generate an Excel (.xlsx) spreadsheet with styled headers, borders, and auto-adjusted columns, automatically sent to Telegram.
    """
    try:
        import openpyxl
        from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
        from openpyxl.utils import get_column_letter

        safe_name = filename if filename.endswith(".xlsx") else f"{filename}.xlsx"
        target_path = os.path.join(SANDBOX_DIR, safe_name)

        # Bersihkan file .xlsx lama di sandbox agar hanya 1 file excel mutakhir yang dikirim
        if os.path.exists(SANDBOX_DIR):
            for old_f in os.listdir(SANDBOX_DIR):
                if old_f.endswith(".xlsx"):
                    try:
                        os.remove(os.path.join(SANDBOX_DIR, old_f))
                    except OSError:
                        pass

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = sheet_title[:30]

        # Normalisasi headers bila dikirim sebagai string JSON atau teks CSV
        headers_list: list[str] = []
        if isinstance(headers, str):
            try:
                parsed_h = json.loads(headers)
                if isinstance(parsed_h, list):
                    headers_list = [str(x) for x in parsed_h]
                else:
                    headers_list = [h.strip() for h in headers.split(",") if h.strip()]
            except _MD_CSV_ERR:
                headers_list = [h.strip() for h in headers.split(",") if h.strip()]
        elif isinstance(headers, (list, tuple)):
            headers_list = [str(h) for h in headers]

        # Normalisasi rows_data
        rows_data = []
        if isinstance(rows_json, str):
            try:
                rows_data = json.loads(rows_json)
            except _MD_JSON_ERR:
                rows_data = []
        elif isinstance(rows_json, list):
            rows_data = rows_json

        # Jika headers kosong tapi rows_data berisi dict, ambil key dari baris pertama
        if not headers_list and rows_data and isinstance(rows_data[0], dict):
            headers_list = list(rows_data[0].keys())

        header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        header_fill = PatternFill(
            start_color="1E3A8A", end_color="1E3A8A", fill_type="solid"
        )
        thin_border = Border(
            left=Side(style="thin", color="CBD5E1"),
            right=Side(style="thin", color="CBD5E1"),
            top=Side(style="thin", color="CBD5E1"),
            bottom=Side(style="thin", color="CBD5E1"),
        )

        if headers_list:
            ws.append(headers_list)
            for col_num in range(1, len(headers_list) + 1):
                cell = ws.cell(row=1, column=col_num)
                cell.font = header_font
                cell.fill = header_fill
                cell.alignment = Alignment(horizontal="center", vertical="center")
                cell.border = thin_border

        for item in rows_data:
            if isinstance(item, dict):
                if headers_list:
                    row_vals = []
                    item_keys_lower = {str(k).lower().strip(): v for k, v in item.items()}
                    for h in headers_list:
                        h_clean = str(h).strip()
                        if h_clean in item:
                            row_vals.append(item[h_clean])
                        elif h_clean.lower() in item_keys_lower:
                            row_vals.append(item_keys_lower[h_clean.lower()])
                        else:
                            matched = None
                            for k, v in item.items():
                                if str(k).lower() in h_clean.lower() or h_clean.lower() in str(k).lower():
                                    matched = v
                                    break
                            row_vals.append(matched if matched is not None else "")
                else:
                    row_vals = list(item.values())
            elif isinstance(item, (list, tuple)):
                row_vals = list(item)
            else:
                row_vals = [item]

            ws.append(row_vals)
            row_idx = ws.max_row
            for col_num in range(1, len(row_vals) + 1):
                cell = ws.cell(row=row_idx, column=col_num)
                cell.border = thin_border

        for col in ws.columns:
            max_len = max(len(str(cell.value or "")) for cell in col)
            col_letter = get_column_letter(col[0].column)
            ws.column_dimensions[col_letter].width = max(max_len + 4, 12)

        wb.save(target_path)
        return {
            "status": "success",
            "message": f"Spreadsheet Excel '{safe_name}' berhasil dibuat dan akan dikirim ke Telegram.",
            "file_path": target_path,
        }
    except _MD_FILE_ERR as e:
        return {"status": "error", "message": f"Gagal membuat Excel: {str(e)}"}


def _xl_text(value: Any) -> str:
    """Representasi teks aman untuk pengukuran lebar kolom."""
    return "" if value is None else str(value)


def _parse_excel_headers(headers: list[str] | None) -> list[str]:
    """Normalisasi header dari list, JSON array, atau teks CSV."""
    if headers is None:
        return []
    if isinstance(headers, str):
        text = headers.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return [str(item) for item in parsed]
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
        return [item.strip() for item in text.split(",") if item.strip()]
    return [str(item) for item in headers]


def _parse_excel_rows(rows_json: str | list | tuple | dict | None) -> list[Any]:
    """Normalisasi baris dari JSON string/list/dict."""
    if rows_json is None:
        return []
    rows = rows_json
    if isinstance(rows, str):
        if not rows.strip():
            return []
        rows = json.loads(rows)
    if isinstance(rows, dict):
        return [rows]
    if not isinstance(rows, (list, tuple)):
        raise _ExcelRowsTypeError
    return list(rows)


def _normalize_excel_rows(raw_rows: list[Any], headers: list[str]) -> list[list[Any]]:
    """Ubah baris dict/list menjadi list nilai sesuai urutan header."""
    normalized: list[list[Any]] = []
    for item in raw_rows:
        if isinstance(item, dict):
            lower = {str(k).strip().lower(): v for k, v in item.items()}
            normalized.append(
                [
                    item.get(h, lower.get(str(h).strip().lower(), ""))
                    for h in headers
                ]
            )
        elif isinstance(item, (list, tuple)):
            normalized.append(list(item))
        else:
            normalized.append([item])
    return normalized


def _verify_excel_sheet(
    path: Path,
    sheet_name: str,
    headers: list[str],
    header_row: int,
    expected_last_row: int,
) -> tuple[bool, str, list[str]]:
    """Buka ulang workbook dan pastikan sheet/header/baris benar-benar ada."""
    import openpyxl

    wb = openpyxl.load_workbook(path, read_only=True, data_only=False)
    try:
        sheets = list(wb.sheetnames)
        if sheet_name not in wb.sheetnames:
            return False, f"sheet '{sheet_name}' tidak ditemukan", sheets
        ws = wb[sheet_name]
        if headers and header_row:
            actual = next(
                ws.iter_rows(
                    min_row=header_row, max_row=header_row, values_only=True
                ),
                (),
            )
            actual_norm = [_xl_text(value).strip() for value in list(actual)[: len(headers)]]
            expected = [str(header).strip() for header in headers]
            if actual_norm != expected:
                return (
                    False,
                    f"header tidak cocok: {actual_norm} != {expected}",
                    sheets,
                )
        actual_last_row = ws.max_row or 0
        if actual_last_row < expected_last_row:
            return (
                False,
                f"jumlah baris kurang: {actual_last_row} < {expected_last_row}",
                sheets,
            )
        return True, "ok", sheets
    finally:
        wb.close()


@register_tool(category="office")
def update_excel_sheet(
    file_path: str,
    sheet_name: str,
    headers: list[str] | None = None,
    rows_json: str = "",
    mode: str = "upsert",
    title: str = "",
) -> dict[str, Any]:
    """Add or update a sheet in an existing .xlsx workbook, then verify it.

    This is the preferred tool for editing an existing spreadsheet. It writes
    atomically (temp file + replace), reopens the workbook, and only reports
    success when the target sheet, headers, and row count are present.
    Use this instead of execute_bash_command for Excel edits.

    Args:
        file_path: Absolute path or ~ path to the .xlsx/.xlsm workbook. If it
            does not exist yet, a new workbook is created (parent dir must exist).
        sheet_name: Sheet to create or update (1-31 chars, no []:*?/\\).
        headers: Column headers as a list (or JSON array / comma-separated string).
        rows_json: Data rows as a JSON array of arrays (or array of objects).
        mode: "upsert" (replace sheet content), "replace" (recreate sheet), or
            "append" (append rows after existing content).
        title: Optional title row placed above the header.
    """
    try:
        import openpyxl
        from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
        from openpyxl.utils import get_column_letter
    except ImportError as exc:
        return {"status": "error", "message": f"openpyxl tidak tersedia: {exc}"}

    sheet_name = str(sheet_name or "").strip()
    if not sheet_name or len(sheet_name) > 31:
        return {
            "status": "error",
            "message": "sheet_name wajib diisi dan maksimal 31 karakter.",
        }
    if any(char in sheet_name for char in "[]:*?/\\"):
        return {
            "status": "error",
            "message": "sheet_name mengandung karakter terlarang Excel.",
        }

    mode = str(mode or "upsert").strip().lower()
    if mode not in {"upsert", "replace", "append"}:
        return {
            "status": "error",
            "message": "mode harus salah satu dari: upsert, replace, append.",
        }

    raw_path = str(file_path or "").strip()
    if not raw_path:
        return {"status": "error", "message": "file_path wajib diisi."}
    path = Path(os.path.expanduser(raw_path)).resolve()
    if path.suffix.lower() not in {".xlsx", ".xlsm"}:
        return {
            "status": "error",
            "message": "file_path harus berekstensi .xlsx atau .xlsm.",
        }
    if not path.parent.exists():
        return {
            "status": "error",
            "message": f"Folder induk tidak ditemukan: {path.parent}",
        }

    try:
        headers_list = _parse_excel_headers(headers)
        raw_rows = _parse_excel_rows(rows_json)
        if not headers_list and raw_rows and isinstance(raw_rows[0], dict):
            headers_list = [str(key) for key in raw_rows[0]]
        rows_data = _normalize_excel_rows(raw_rows, headers_list)
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        return {"status": "error", "message": f"Data tidak valid: {exc}"}

    if not headers_list and not rows_data and not str(title or "").strip():
        return {
            "status": "error",
            "message": "Tidak ada data: isi headers, rows_json, atau title.",
        }

    existed = path.exists()
    backup: Path | None = None
    tmp: Path | None = None
    wb: Any = None
    replaced = False
    try:
        if existed:
            backup = path.with_name(
                f".{path.name}.bak-{os.getpid()}-{time.time_ns()}"
            )
            shutil.copy2(path, backup)
            wb = openpyxl.load_workbook(
                path, keep_vba=path.suffix.lower() == ".xlsm"
            )
        else:
            wb = openpyxl.Workbook()

        if sheet_name in wb.sheetnames:
            if mode in {"upsert", "replace"}:
                index = wb.sheetnames.index(sheet_name)
                wb.remove(wb[sheet_name])
                ws = wb.create_sheet(sheet_name, index)
            else:
                ws = wb[sheet_name]
        else:
            ws = wb.create_sheet(sheet_name)
            if not existed and "Sheet" in wb.sheetnames and len(wb.sheetnames) > 1:
                wb.remove(wb["Sheet"])

        has_content = (
            ws.max_row > 1
            or ws.max_column > 1
            or ws["A1"].value not in (None, "")
        )
        write_title = bool(str(title or "").strip()) and not (
            mode == "append" and has_content
        )
        start_row = 1
        if write_title:
            ws.cell(row=1, column=1, value=str(title).strip()).font = Font(
                bold=True, size=12
            )
            start_row = 2

        if mode == "append" and has_content:
            start_row = max(start_row, ws.max_row + 1)
            write_headers = False
        else:
            write_headers = bool(headers_list)

        header_row = 0
        if write_headers:
            header_row = start_row
            for col, header in enumerate(headers_list, 1):
                ws.cell(row=header_row, column=col, value=header)
            start_row += 1

        for row_offset, data_row in enumerate(rows_data):
            for col, value in enumerate(data_row, 1):
                ws.cell(row=start_row + row_offset, column=col, value=value)

        if rows_data:
            expected_last_row = start_row + len(rows_data) - 1
        elif header_row:
            expected_last_row = header_row
        else:
            expected_last_row = 1

        if header_row:
            header_font = Font(bold=True, color="FFFFFF")
            header_fill = PatternFill("solid", start_color="1E3A8A")
            thin = Side(style="thin", color="CBD5E1")
            border = Border(left=thin, right=thin, top=thin, bottom=thin)
            for col in range(1, max(len(headers_list), 1) + 1):
                cell = ws.cell(row=header_row, column=col)
                cell.font = header_font
                cell.fill = header_fill
                cell.alignment = Alignment(
                    horizontal="center", vertical="center"
                )
                cell.border = border
            ws.freeze_panes = f"A{header_row + 1}"

        data_border = Border(
            left=Side(style="thin", color="E2E8F0"),
            right=Side(style="thin", color="E2E8F0"),
            top=Side(style="thin", color="E2E8F0"),
            bottom=Side(style="thin", color="E2E8F0"),
        )
        data_start = header_row + 1 if header_row else (2 if write_title else 1)
        for row in range(data_start, expected_last_row + 1):
            for col in range(1, max(len(headers_list), 1) + 1):
                ws.cell(row=row, column=col).border = data_border

        max_col = max(
            len(headers_list),
            max((len(row) for row in rows_data), default=0),
            1,
        )
        for col in range(1, max_col + 1):
            longest = max(
                (
                    len(_xl_text(ws.cell(row=row, column=col).value))
                    for row in range(1, expected_last_row + 1)
                ),
                default=0,
            )
            letter = get_column_letter(col)
            current_width = ws.column_dimensions[letter].width or 0
            ws.column_dimensions[letter].width = max(
                current_width, min(max(longest + 4, 12), 60)
            )

        tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}-{time.time_ns()}.xlsx")
        wb.save(tmp)
        wb.close()
        wb = None
        if existed:
            shutil.copymode(path, tmp)
        else:
            os.chmod(tmp, 0o644)
        os.replace(tmp, path)
        tmp = None
        replaced = True

        verified, detail, sheets = _verify_excel_sheet(
            path, sheet_name, headers_list, header_row, expected_last_row
        )
        if not verified:
            if backup is not None:
                os.replace(backup, path)
                backup = None
            elif not existed:
                path.unlink(missing_ok=True)
            return {
                "status": "error",
                "message": f"Verifikasi gagal: {detail}",
                "verified": False,
                "file_path": str(path),
                "sheet": sheet_name,
            }

        return {
            "status": "success",
            "message": (
                f"Sheet '{sheet_name}' berhasil diperbarui dan terverifikasi "
                f"({len(rows_data)} baris data)."
            ),
            "file_path": str(path),
            "sheet": sheet_name,
            "mode": mode,
            "rows_written": len(rows_data),
            "total_rows": expected_last_row,
            "sheets": sheets,
            "verified": True,
        }
    except _XL_ERR as exc:
        if replaced:
            if backup is not None and backup.exists():
                os.replace(backup, path)
                backup = None
            elif not existed:
                path.unlink(missing_ok=True)
        return {"status": "error", "message": f"Gagal update Excel: {exc}"}
    finally:
        if wb is not None:
            try:
                wb.close()
            except (OSError, ValueError, TypeError):
                pass
        if tmp is not None and tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        if backup is not None and backup.exists():
            try:
                backup.unlink()
            except OSError:
                pass


@register_tool(category="office")
def generate_presentation_pptx(
    title: str, subtitle: str, slides_json: str, filename: str = "presentasi.pptx"
) -> dict[str, Any]:
    """
    Generate a clean PowerPoint presentation (.pptx) and send it directly to Telegram.
    """
    try:
        from pptx import Presentation

        slides_content = (
            json.loads(slides_json) if isinstance(slides_json, str) else slides_json
        )
        if not slides_content:
            slides_content = []
        if isinstance(slides_content, dict):
            slides_content = [slides_content]

        safe_name = filename if filename.endswith(".pptx") else f"{filename}.pptx"
        target_path = os.path.join(SANDBOX_DIR, safe_name)

        prs = Presentation()
        title_layout = prs.slide_layouts[0]
        slide = prs.slides.add_slide(title_layout)
        slide.shapes.title.text = title
        slide.placeholders[1].text = subtitle

        bullet_layout = prs.slide_layouts[1]
        for item in slides_content:
            s = prs.slides.add_slide(bullet_layout)
            s.shapes.title.text = item.get("title", "Slide")
            tf = s.placeholders[1].text_frame
            tf.word_wrap = True
            points = item.get("points", [])
            for i, pt in enumerate(points):
                if i == 0:
                    tf.text = str(pt)
                else:
                    p = tf.add_paragraph()
                    p.text = str(pt)
                    p.level = 0

        prs.save(target_path)
        return {
            "status": "success",
            "message": f"Presentasi PowerPoint '{safe_name}' berhasil dibuat dan akan dikirim ke Telegram.",
            "file_path": target_path,
        }
    except _MD_FILE_ERR as e:
        return {"status": "error", "message": f"Gagal membuat PPTX: {str(e)}"}


@register_tool(category="media")
def analyze_dataset_csv_json(
    file_path: str,
    chart_type: str = "bar",
    x_column: str = "",
    y_column: str = "",
    title: str = "Data Analysis",
) -> dict[str, Any]:
    """
    GOD MODE: Intelligent Dataset Analyzer & Visualizer.
    Reads and parses a CSV, JSON, or Excel dataset, computes statistical metrics
    and generates a professional visualization chart automatically sent to Telegram.
    """
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        expanded = os.path.expanduser(file_path)
        if not os.path.exists(expanded):
            return {
                "status": "error",
                "message": f"File dataset tidak ditemukan: {file_path}",
            }

        data_rows = []
        headers: list[str] = []

        ext = os.path.splitext(expanded)[1].lower()
        if ext == ".csv":
            with open(expanded, encoding="utf-8", errors="replace") as f:
                reader = csv.DictReader(f)
                headers = list(reader.fieldnames or [])
                data_rows = list(reader)
        elif ext == ".json":
            with open(expanded, encoding="utf-8") as f:
                raw_json = json.load(f)
                if isinstance(raw_json, list) and raw_json:
                    data_rows = raw_json
                    headers = (
                        list(raw_json[0].keys())
                        if isinstance(raw_json[0], dict)
                        else []
                    )
                elif isinstance(raw_json, dict):
                    data_rows = [raw_json]
                    headers = list(raw_json.keys())
        else:
            return {
                "status": "error",
                "message": "Format dataset harus .csv atau .json",
            }

        if not data_rows:
            return {
                "status": "error",
                "message": "Dataset kosong atau tidak memiliki baris data.",
            }

        total_rows = len(data_rows)
        sample_data = data_rows[:5]

        chart_path = os.path.join(SANDBOX_DIR, "dataset_analysis_chart.png")
        plt.figure(figsize=(10, 6), dpi=120)
        plt.style.use(
            "seaborn-v0_8-darkgrid"
            if "seaborn-v0_8-darkgrid" in plt.style.available
            else "default"
        )

        x_col = x_column or (headers[0] if headers else "")
        y_col = y_column or (
            headers[1] if len(headers) > 1 else headers[0] if headers else ""
        )

        x_vals = [str(r.get(x_col, "")) for r in data_rows[:20]]
        y_vals = []
        for r in data_rows[:20]:
            try:
                y_vals.append(float(r.get(y_col, 0)))
            except (ValueError, TypeError):
                y_vals.append(0.0)

        if chart_type == "line":
            plt.plot(x_vals, y_vals, marker="o", color="#2563EB", linewidth=2.5)
        elif chart_type == "scatter":
            plt.scatter(x_vals, y_vals, color="#7C3AED", s=80)
        elif chart_type == "pie" and len(x_vals) <= 10:
            plt.pie(
                y_vals,
                labels=x_vals,
                autopct="%1.1f%%",
                colors=getattr(plt.cm.Paired, "colors", None),
            )
        else:
            plt.bar(x_vals, y_vals, color="#3B82F6", edgecolor="#1D4ED8")

        plt.title(title, fontsize=14, fontweight="bold", pad=15)
        if chart_type != "pie":
            plt.xlabel(x_col, fontsize=11)
            plt.ylabel(y_col, fontsize=11)
            plt.xticks(rotation=45, ha="right")
        plt.tight_layout()
        plt.savefig(chart_path, dpi=150)
        plt.close()

        return {
            "status": "success",
            "total_rows": total_rows,
            "columns": headers,
            "sample_rows": sample_data,
            "chart_generated": "dataset_analysis_chart.png",
            "message": f"Analisis dataset '{os.path.basename(expanded)}' selesai. Grafik '{chart_type}' berhasil dibuat dan akan dikirim ke Telegram.",
        }
    except _MD_CHART_ERR as e:
        return {"status": "error", "message": f"Dataset analysis error: {str(e)}"}


@register_tool(category="media")
def translate_text(
    text: str, target_lang: str = "en", source_lang: str = "auto"
) -> dict[str, Any]:
    """
    Translate text between languages using the configured Gemini model.
    (Previously Google Translate via deep-translator, removed: upstream
    package was compromised — see pip-audit PYSEC-2022-252.)
    """
    try:
        from google import genai

        from alfa.swarm.llm_client import get_agent_api_client

        _provider, api_key, model, _base, _kid = get_agent_api_client(
            {"provider": "gemini"}
        )
        if not api_key:
            return {
                "status": "error",
                "message": "Tidak ada Gemini API key aktif untuk penerjemah.",
            }
        client = genai.Client(api_key=api_key, http_options={"timeout": 30000})
        prompt = (
            f"Translate the following text from {source_lang} to {target_lang}. "
            f"Return ONLY the translation, no explanations:\n\n{text[:4500]}"
        )
        resp = client.models.generate_content(model=model, contents=prompt)
        translated = (getattr(resp, "text", "") or "").strip()
        if not translated:
            return {
                "status": "error",
                "message": "Model tidak mengembalikan terjemahan.",
            }
        return {
            "status": "success",
            "original": text[:500],
            "translated": translated,
            "source_language": source_lang,
            "target_language": target_lang,
        }
    except _MD_FILE_ERR as e:
        return {"status": "error", "message": f"Gagal menerjemahkan: {str(e)}"}


@register_tool(category="office")
def record_material_to_sheets(
    material_text: str,
    context: str = "",
    source: str = "",
) -> dict[str, Any]:
    """
    PERINGATAN INTEGRASI: Spreadsheet Pengambilan Material HANYA diperuntukkan bagi sinkronisasi otomatis dari chat grup WhatsApp 'Pengambilan Material'.
    DILARANG menggunakan tool ini untuk mencatat isi file/dokumen (PDF/Excel/Surat Jalan/DO) atau chat Telegram ke Google Sheets.
    Jika dipanggil untuk dokumen atau sumber selain grup WhatsApp 'Pengambilan Material', pencatatan akan otomatis ditolak.
    """
    from alfa.integrations.google_sheets import (
        is_pengambilan_material_group,
        is_whatsapp_source,
        parse_and_record_material_text,
    )

    if not source or not is_whatsapp_source(source) or not is_pengambilan_material_group(source, context=context):
        return {
            "status": "error",
            "message": (
                "Penyimpanan ke spreadsheet ditolak. Sesuai aturan sistem, spreadsheet Pengambilan Material "
                "HANYA mencatat otomatis dari chat WhatsApp grup yang memuat keterangan 'pengambilan material', "
                "bukan dari file/dokumen atau percakapan lain."
            ),
        }

    return parse_and_record_material_text(text=material_text, context=context, source=source)

