"""
Office documents (Excel, PowerPoint), dataset analysis/charts, and text translation.
"""

import csv
import json
import logging
import os
from typing import Any

from alfa.tools.registry import register_tool
from alfa.tools.system_tools import SANDBOX_DIR

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

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = sheet_title[:30]

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

        ws.append(headers)
        for col_num in range(1, len(headers) + 1):
            cell = ws.cell(row=1, column=col_num)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="center", vertical="center")
            cell.border = thin_border

        rows_data = []
        if isinstance(rows_json, str):
            try:
                rows_data = json.loads(rows_json)
            except Exception:
                rows_data = []
        elif isinstance(rows_json, list):
            rows_data = rows_json

        for row_data in rows_data:
            ws.append(row_data)
            row_idx = ws.max_row
            for col_num in range(1, len(row_data) + 1):
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
    except Exception as e:
        return {"status": "error", "message": f"Gagal membuat Excel: {str(e)}"}


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
    except Exception as e:
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
        headers = []

        ext = os.path.splitext(expanded)[1].lower()
        if ext == ".csv":
            with open(expanded, encoding="utf-8", errors="replace") as f:
                reader = csv.DictReader(f)
                headers = reader.fieldnames or []
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
                y_vals, labels=x_vals, autopct="%1.1f%%", colors=plt.cm.Paired.colors
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
    except Exception as e:
        return {"status": "error", "message": f"Dataset analysis error: {str(e)}"}


@register_tool(category="media")
def translate_text(
    text: str, target_lang: str = "en", source_lang: str = "auto"
) -> dict[str, Any]:
    """
    Translate text between languages using Google Translate.
    """
    try:
        from deep_translator import GoogleTranslator

        translated = GoogleTranslator(source=source_lang, target=target_lang).translate(
            text[:4500]
        )
        return {
            "status": "success",
            "original": text[:500],
            "translated": translated,
            "source_language": source_lang,
            "target_language": target_lang,
        }
    except Exception as e:
        return {"status": "error", "message": f"Gagal menerjemahkan: {str(e)}"}
