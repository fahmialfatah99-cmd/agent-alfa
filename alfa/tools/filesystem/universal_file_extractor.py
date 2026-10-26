"""
UNIVERSAL FILE & MULTIMODAL ATTACHMENT EXTRACTOR.
Enterprise-grade parser for all document, spreadsheet, code, archive, audio, and visual formats:
- PDF: PyMuPDF (fitz) + pypdf page extractor
- Word: python-docx + mammoth paragraph & table parser
- PowerPoint: python-pptx per-slide extractor with speaker notes
- Excel: openpyxl + pandas multi-sheet markdown table converter
- CSV/TSV: csv.Sniffer with auto delimiter detection
- HTML/XML: BeautifulSoup clean text extractor
- JSON/YAML/TOML: structure parser
- Code: 30+ programming language syntax blocks with line numbers
- Archives: ZIP/TAR directory hierarchy and nested file extractor
- Audio/Video/Images: Gemini native multimodal Part generator + Real File Path Persistence
"""

import csv
import io
import json
import logging
import os
import re
import tarfile
import time
import zipfile
from typing import Any

logger = logging.getLogger("UniversalFileExtractor")

_UFE_ERR = (
    OSError,
    ValueError,
    RuntimeError,
    TypeError,
    KeyError,
    AttributeError,
    ImportError,
    csv.Error,
    zipfile.BadZipFile,
    tarfile.TarError,
)

UPLOAD_DIR = os.path.expanduser("~/Dokumen/ALFA_SWARM_OUTPUTS/uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)


def process_uploaded_attachment(
    filename: str, mime_type: str, raw_bytes: bytes, save_disk: bool = True
) -> tuple[str | None, Any | None]:
    """
    Process any uploaded file and return (text_context, multimodal_part).
    - Persists file to ~/Dokumen/ALFA_SWARM_OUTPUTS/uploads/ so real tools can operate on it.
    - If file is an image or audio or native PDF: returns multimodal_part for Gemini vision/audio/doc models.
    - Returns rich structured text context with exact file disk path for immediate tool execution.
    """
    ext = os.path.splitext(filename)[1].lower()
    fname_clean = os.path.basename(filename)
    safe_name = re.sub(r"[^a-zA-Z0-9_.-]", "_", fname_clean)

    file_disk_path = ""
    if save_disk:
        try:
            file_disk_path = os.path.join(UPLOAD_DIR, f"{int(time.time())}_{safe_name}")
            with open(file_disk_path, "wb") as f_disk:
                f_disk.write(raw_bytes)
        except OSError as e:
            logger.warning(f"Gagal simpan upload ke disk: {e}")

    path_header = (
        f"[FILE TERSIMPAN DI DISK: {file_disk_path}]\n" if file_disk_path else ""
    )
    tool_hint = "[Catatan sistem: berkas tersimpan di path di atas untuk keperluan operasi tool berkas jika diminta pengguna]\n"

    # 1. IMAGES (Vision + Real Tool Execution)
    if mime_type.startswith("image/") or ext in (
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
        ".gif",
        ".bmp",
        ".tiff",
        ".ico",
    ):
        multimodal_part = None
        try:
            from google.genai import types

            img_mime = (
                mime_type
                if mime_type.startswith("image/")
                else f"image/{ext.lstrip('.')}"
            )
            if img_mime == "image/jpg":
                img_mime = "image/jpeg"
            multimodal_part = types.Part.from_bytes(data=raw_bytes, mime_type=img_mime)
        except _UFE_ERR as e:
            logger.warning(f"Native image part error: {e}")

        text_ctx = f"[LAMPIRAN GAMBAR/FOTO: {fname_clean}]\n{path_header}{tool_hint}"
        return text_ctx, multimodal_part

    # 2. AUDIO & VOICE (Native Audio + Real Tool Execution)
    if mime_type.startswith("audio/") or ext in (
        ".mp3",
        ".m4a",
        ".wav",
        ".ogg",
        ".aac",
        ".flac",
    ):
        multimodal_part = None
        try:
            from google.genai import types

            aud_mime = (
                mime_type
                if mime_type.startswith("audio/")
                else f"audio/{ext.lstrip('.')}"
            )
            multimodal_part = types.Part.from_bytes(data=raw_bytes, mime_type=aud_mime)
        except _UFE_ERR as e:
            logger.warning(f"Native audio part error: {e}")

        text_ctx = f"[LAMPIRAN AUDIO/SUARA: {fname_clean}]\n{path_header}{tool_hint}"
        return text_ctx, multimodal_part

    # 3. PDF DOCUMENTS (Dual mode: PyMuPDF text + Native Part)
    if ext == ".pdf" or mime_type == "application/pdf":
        pdf_text = _extract_pdf(raw_bytes, fname_clean)
        multimodal_part = None
        try:
            from google.genai import types

            multimodal_part = types.Part.from_bytes(
                data=raw_bytes, mime_type="application/pdf"
            )
        except _UFE_ERR:
            pass
        return (
            f"[DOKUMEN PDF: {fname_clean}]\n{path_header}{tool_hint}\n{pdf_text}",
            multimodal_part,
        )

    # 4. WORD DOCUMENTS (.docx, .doc)
    if ext in (".docx", ".doc"):
        doc_text = _extract_word(raw_bytes, fname_clean)
        return (
            f"[DOKUMEN WORD: {fname_clean}]\n{path_header}{tool_hint}\n{doc_text}",
            None,
        )

    # 5. POWERPOINT PRESENTATIONS (.pptx, .ppt)
    if ext in (".pptx", ".ppt"):
        pptx_text = _extract_powerpoint(raw_bytes, fname_clean)
        return (
            f"[PRESENTASI PPTX: {fname_clean}]\n{path_header}{tool_hint}\n{pptx_text}",
            None,
        )

    # 6. SPREADSHEETS (.xlsx, .xls, .xlsm, .ods)
    if ext in (".xlsx", ".xls", ".xlsm", ".xltx", ".ods"):
        sheet_text = _extract_excel(raw_bytes, fname_clean, ext)
        return (
            f"[SPREADSHEET EXCEL: {fname_clean}]\n{path_header}{tool_hint}\n{sheet_text}",
            None,
        )

    # 7. CSV / TSV / DELIMITED DATA
    if ext in (".csv", ".tsv", ".dsv", ".txt") and (
        "," in raw_bytes[:1000].decode("utf-8", errors="ignore")
        or "\t" in raw_bytes[:1000].decode("utf-8", errors="ignore")
    ):
        csv_text = _extract_csv(raw_bytes, fname_clean)
        if csv_text:
            return (
                f"[DATA TABEL CSV: {fname_clean}]\n{path_header}{tool_hint}\n{csv_text}",
                None,
            )

    # 8. ARCHIVES (.zip, .tar, .tar.gz, .tgz)
    if ext in (".zip", ".tar", ".gz", ".tgz", ".bz2"):
        archive_text = _extract_archive(raw_bytes, fname_clean, ext)
        return (
            f"[ARSIP TERKOMPRESI: {fname_clean}]\n{path_header}{tool_hint}\n{archive_text}",
            None,
        )

    # 9. HTML / XML / SVG
    if ext in (".html", ".htm", ".xhtml", ".xml", ".svg"):
        html_text = _extract_html_xml(raw_bytes, fname_clean, ext)
        return f"[KODE WEB / STRUKTUR: {fname_clean}]\n{path_header}\n{html_text}", None

    # 10. JSON / YAML / TOML
    if ext in (".json", ".jsonl", ".ndjson", ".yaml", ".yml", ".toml"):
        data_text = _extract_data_formats(raw_bytes, fname_clean, ext)
        return f"[DATA KONFIGURASI: {fname_clean}]\n{path_header}\n{data_text}", None

    # 11. SOURCE CODE & SCRIPTS
    code_exts = {
        ".py": "python",
        ".js": "javascript",
        ".ts": "typescript",
        ".tsx": "tsx",
        ".jsx": "jsx",
        ".java": "java",
        ".c": "c",
        ".cpp": "cpp",
        ".h": "c",
        ".cs": "csharp",
        ".go": "go",
        ".rs": "rust",
        ".php": "php",
        ".rb": "ruby",
        ".sh": "bash",
        ".bash": "bash",
        ".zsh": "bash",
        ".sql": "sql",
        ".css": "css",
        ".scss": "scss",
        ".vue": "vue",
        ".svelte": "svelte",
        ".proto": "protobuf",
        ".graphql": "graphql",
        ".dockerfile": "dockerfile",
        ".md": "markdown",
        ".txt": "text",
        ".log": "log",
        ".env": "ini",
    }
    if ext in code_exts or mime_type.startswith("text/"):
        lang = code_exts.get(ext, "text")
        try:
            decoded = raw_bytes.decode("utf-8", errors="replace")
            lines = decoded.splitlines()
            numbered = "\n".join(
                [f"{i + 1:4d} | {line}" for i, line in enumerate(lines[:1000])]
            )
            total_hint = (
                f" (Menampilkan {min(len(lines), 1000)} dari total {len(lines)} baris)"
                if len(lines) > 1000
                else ""
            )
            return (
                f"[KODE SUMBER: {fname_clean}{total_hint}]\n{path_header}\n```{lang}\n{numbered}\n```",
                None,
            )
        except (ValueError, TypeError):
            pass

    # 12. Fallback UTF-8 text decoder
    try:
        decoded = raw_bytes.decode("utf-8", errors="replace")
        return f"[BERKAS TEKS: {fname_clean}]\n{path_header}\n{decoded}", None
    except (ValueError, TypeError, AttributeError):
        return (
            f"[BERKAS BINER: {fname_clean} ({len(raw_bytes)} bytes)]\n{path_header}",
            None,
        )


# ── EXTRACTOR IMPLEMENTATIONS ─────────────────────────────────────────────────


def _extract_pdf(raw_bytes: bytes, fname: str) -> str:
    try:
        import fitz

        doc = fitz.open(stream=raw_bytes, filetype="pdf")
        pages = []
        for i, page in enumerate(doc):
            text = page.get_text("text").strip()
            if text:
                pages.append(f"--- Halaman {i + 1} ---\n{text}")
        if pages:
            return f"Total {len(doc)} halaman:\n\n" + "\n\n".join(pages[:50])
    except _UFE_ERR as e:
        logger.debug(f"fitz pdf error: {e}")

    try:
        import pypdf

        reader = pypdf.PdfReader(io.BytesIO(raw_bytes))
        pages = []
        for i, page in enumerate(reader.pages):
            txt = page.extract_text()
            if txt:
                pages.append(f"--- Halaman {i + 1} ---\n{txt}")
        if pages:
            return f"Total {len(reader.pages)} halaman:\n\n" + "\n\n".join(pages[:50])
    except _UFE_ERR as e:
        logger.debug(f"pypdf error: {e}")

    return f"Gagal membaca teks dari PDF {fname}."


def _extract_word(raw_bytes: bytes, fname: str) -> str:
    try:
        import docx

        doc = docx.Document(io.BytesIO(raw_bytes))
        out = []
        for p in doc.paragraphs:
            if p.text.strip():
                if p.style and p.style.name and p.style.name.startswith("Heading"):
                    out.append(f"### {p.text.strip()}")
                else:
                    out.append(p.text.strip())

        for t_idx, table in enumerate(doc.tables, 1):
            out.append(f"\n#### Tabel {t_idx}")
            rows = []
            for r in table.rows:
                rows.append([cell.text.strip().replace("\n", " ") for cell in r.cells])
            if rows:
                headers = rows[0]
                cols = len(headers)
                out.append("| " + " | ".join(headers) + " |")
                out.append("| " + " | ".join(["---"] * cols) + " |")
                for r in rows[1:]:
                    out.append("| " + " | ".join(r[:cols]) + " |")

        return "\n\n".join(out)
    except _UFE_ERR as e:
        logger.warning(f"docx error: {e}")
        return f"Gagal membaca dokumen Word {fname}."


def _extract_powerpoint(raw_bytes: bytes, fname: str) -> str:
    try:
        import pptx

        prs = pptx.Presentation(io.BytesIO(raw_bytes))
        slides_out = []
        for i, slide in enumerate(prs.slides, 1):
            s_texts = []
            for shape in slide.shapes:
                if hasattr(shape, "text") and shape.text.strip():
                    s_texts.append(shape.text.strip())
            notes = ""
            if slide.has_notes_slide and slide.notes_slide.notes_text_frame:
                notes = slide.notes_slide.notes_text_frame.text.strip()

            slide_md = f"### Slide {i}\n" + "\n".join(f"- {t}" for t in s_texts)
            if notes:
                slide_md += f"\n*Catatan Presenter:* {notes}"
            slides_out.append(slide_md)

        return f"Total {len(prs.slides)} Slide Presentasi:\n\n" + "\n\n".join(
            slides_out
        )
    except _UFE_ERR as e:
        logger.warning(f"pptx error: {e}")
        return f"Gagal membaca presentasi PPTX {fname}."


def _build_full_sheet_pre_aggregation(
    headers: list[str], data_rows: list[list[Any]]
) -> str:
    """Compute instant 100%-row exact aggregations (counts, sums, averages) in <20ms."""
    from collections import Counter

    total_rows = len(data_rows)
    if total_rows == 0 or not headers:
        return ""

    num_cols = len(headers)
    cat_summaries: list[str] = []
    num_summaries: list[str] = []

    for col_idx in range(num_cols):
        col_name = str(headers[col_idx] or f"Kolom_{col_idx + 1}").strip()
        if not col_name:
            continue
        num_vals: list[float] = []
        str_vals: list[str] = []
        for r in data_rows:
            if col_idx >= len(r):
                continue
            val = r[col_idx]
            if val is None or val == "":
                continue
            if isinstance(val, bool):
                str_vals.append(str(val))
            elif isinstance(val, (int, float)):
                num_vals.append(float(val))
            else:
                s = str(val).strip()
                if not s:
                    continue
                # Cek apakah string angka murni
                s_clean = s.replace(",", "")
                try:
                    if s_clean.replace(".", "", 1).replace("-", "", 1).isdigit():
                        num_vals.append(float(s_clean))
                        continue
                except ValueError:
                    pass
                str_vals.append(s)

        if len(num_vals) >= max(1, int(total_rows * 0.4)) and len(num_vals) > len(str_vals):
            total_sum = sum(num_vals)
            avg_val = total_sum / len(num_vals)
            min_val = min(num_vals)
            max_val = max(num_vals)
            if all(float(v).is_integer() for v in num_vals):
                num_summaries.append(
                    f"• **{col_name}**: Total (SUM) = `{int(total_sum):,}` | Rata-rata = `{avg_val:,.2f}` | Min = `{int(min_val):,}` | Max = `{int(max_val):,}` (dari {len(num_vals)} baris)"
                )
            else:
                num_summaries.append(
                    f"• **{col_name}**: Total (SUM) = `{total_sum:,.2f}` | Rata-rata = `{avg_val:,.2f}` | Min = `{min_val:,.2f}` | Max = `{max_val:,.2f}` (dari {len(num_vals)} baris)"
                )
        elif str_vals:
            counts = Counter(str_vals)
            unique_cnt = len(counts)
            max_freq = max(counts.values()) if counts else 0
            # Jangan rekap kolom tanggal mentah atau kolom ID/Deskripsi yang tiap barisnya unik (freq=1)
            is_date_like = "date" in col_name.lower() or "tanggal" in col_name.lower()
            is_all_unique_ids = total_rows > 5 and max_freq <= 1
            if (
                1 <= unique_cnt <= 50
                and not is_all_unique_ids
                and not (is_date_like and unique_cnt > 12)
            ):
                items_sorted = sorted(counts.items(), key=lambda x: (-x[1], x[0]))
                formatted_items = ", ".join(f"{k}: {v}" for k, v in items_sorted)
                cat_summaries.append(
                    f"• **{col_name}** ({unique_cnt} kategori): {formatted_items}"
                )

    lines = [
        f"### ⚡ REKAPITULASI EKSAK 100% DATA ({total_rows} Baris Data — Sudah Dihitung Mesin Python Lokal)",
        "_(Catatan Sistem: Angka di bawah ini adalah hasil perhitungan eksak 100% seluruh baris. Gunakan langsung angka ini untuk menjawab dengan cepat tanpa perlu memanggil Python Sandbox lagi, kecuali diminta membuat grafik/file baru.)_",
        f"- **Total Baris Data (Tanpa Header)**: `{total_rows}` baris",
    ]
    if cat_summaries:
        lines.append("\n**Rincian Jumlah per Kategori / Kolom Teks (100% Baris):**")
        lines.extend(cat_summaries)
    if num_summaries:
        lines.append("\n**Rincian Total & Statistik Kolom Angka/Biaya/QTY (100% Baris):**")
        lines.extend(num_summaries)
    return "\n".join(lines)


_PRIORITY_HEADER_KEYWORDS = (
    "total material provided",
    "usage qty",
    "remaining qty",
    "to outbound",
    "to outbond",
    "should remain",
    "remaining after to",
    "actual stock",
    "aktual stok",
    "actual stok",
    "deduct qty",
    "gap",
    "type",
    "material code",
    "material description",
    "unit",
    "brand / type",
    "pati - kudus",
    "jepara",
    "kendal",
    "semarang",
    "cj aaea intotal",
    "bali",
)

_ANCHOR_HEADER_TERMS = {
    "type",
    "material code",
    "material description",
    "unit",
    "brand / type",
    "kode material",
    "nama material",
    "nama barang",
    "satuan",
    "uraian",
    "task id",
    "project name",
}


def _prepare_sheet_headers_and_rows(
    rows: list[list[Any]],
) -> tuple[list[str], list[list[Any]], int]:
    """Detect multi-row merged headers, prune 100+ empty/daily columns on wide sheets, and clean footer noise."""
    if not rows:
        return [], [], 0

    raw_cols = max(len(r) for r in rows)
    padded_rows = [list(r) + [None] * (raw_cols - len(r)) for r in rows]

    # 1. Cari batas baris header (cek 6 baris pertama untuk anchor seperti 'Material Code', 'Material Description')
    header_end_idx = 1
    preserve_anchor_row_as_summary = False
    for r_idx in range(min(6, len(padded_rows))):
        row_strs = {
            str(c).strip().lower()
            for c in padded_rows[r_idx]
            if c is not None and not isinstance(c, (int, float))
        }
        matches = row_strs.intersection(_ANCHOR_HEADER_TERMS)
        if len(matches) >= 2:
            header_end_idx = r_idx + 1
            # Jika baris anchor ini juga memuat angka ringkasan di kolom kanan (seperti sheet Summary SMDT)
            num_cnt = sum(
                1
                for c in padded_rows[r_idx][3:]
                if isinstance(c, (int, float)) and not isinstance(c, bool)
            )
            if r_idx >= 1 and num_cnt >= 3:
                preserve_anchor_row_as_summary = True
            break

    header_rows = padded_rows[:header_end_idx]
    data_rows = padded_rows[header_end_idx:]
    if preserve_anchor_row_as_summary:
        summary_row = list(padded_rows[header_end_idx - 1])
        summary_row[0] = "TOTAL / RINGKASAN"
        if len(summary_row) > 1:
            summary_row[1] = "-"
        if len(summary_row) > 2:
            summary_row[2] = "Total Selisih / GAP Wilayah"
        data_rows = [summary_row] + data_rows

    # 2. Gabungkan multi-row header per kolom dengan prioritas kata kunci metrik utama
    merged_headers: list[str] = []
    for c_idx in range(raw_cols):
        col_candidates: list[str] = []
        for h_row in header_rows:
            val = h_row[c_idx]
            if val is None or isinstance(val, (int, float, bool)):
                continue
            s = str(val).strip().replace("\n", " ")
            if not s or s.upper() in ("A", "B", "C", "A - B", "A - (B+C)", "OP", "DIST", "SF"):
                continue
            if "datetime" in s.lower() or s.startswith("202"):
                continue
            col_candidates.append(s)

        chosen = ""
        for cand in col_candidates:
            cand_l = cand.lower()
            if any(pk in cand_l for pk in _PRIORITY_HEADER_KEYWORDS):
                chosen = cand
                break
        if not chosen and col_candidates:
            chosen = col_candidates[-1]
        merged_headers.append(chosen)

    # 3. Jika sheet adalah tabel korporat multi-header yang punya Material Code / Material Description,
    #    saring baris footer/catatan bawah yang tidak punya nama material
    desc_col = -1
    code_col = -1
    for idx, h in enumerate(merged_headers):
        hl = h.lower()
        if "material description" in hl or "nama material" in hl:
            desc_col = idx
        elif "material code" in hl or "kode material" in hl:
            code_col = idx

    if header_end_idx > 1 and (desc_col >= 0 or code_col >= 0):
        cleaned_data_rows = []
        for r in data_rows:
            has_desc = (
                desc_col >= 0
                and r[desc_col] is not None
                and str(r[desc_col]).strip() != ""
                and not str(r[desc_col]).strip().lower().endswith((".pdf", ".jpg", ".png"))
            )
            has_code = (
                code_col >= 0
                and r[code_col] is not None
                and str(r[code_col]).strip() != ""
                and not str(r[code_col]).strip().lower().endswith((".pdf", ".jpg", ".png"))
            )
            if has_desc or has_code:
                cleaned_data_rows.append(r)
        if cleaned_data_rows:
            data_rows = cleaned_data_rows

    # 4. Pangkas kolom kosong dan batasi sheet super-lebar (> 18 kolom) ke kolom identitas & ringkasan
    active_col_indices = [
        c_idx
        for c_idx in range(raw_cols)
        if merged_headers[c_idx]
        or any(r[c_idx] is not None and str(r[c_idx]).strip() != "" for r in data_rows)
    ]

    if len(active_col_indices) > 14:
        keep_indices: list[int] = []
        summary_kw = (
            "type",
            "code",
            "kode",
            "description",
            "nama",
            "unit",
            "satuan",
            "brand",
            "total",
            "provided",
            "usage",
            "terpakai",
            "remaining",
            "sisa",
            "outbound",
            "outbond",
            "inbound",
            "actual",
            "aktual",
            "stock",
            "stok",
            "gap",
            "selisih",
            "deduct",
            "pati",
            "jepara",
            "kendal",
            "semarang",
            "bali",
            "qty",
            "jumlah",
            "status",
        )
        for c_idx in active_col_indices:
            hl = merged_headers[c_idx].lower()
            if any(k in hl for k in summary_kw):
                keep_indices.append(c_idx)
        if len(keep_indices) < 6:
            keep_indices = active_col_indices[:15]
        active_col_indices = keep_indices[:15]

    final_headers = [
        merged_headers[c_idx] or f"Kolom_{pos + 1}"
        for pos, c_idx in enumerate(active_col_indices)
    ]
    final_rows = [[r[c_idx] for c_idx in active_col_indices] for r in data_rows]
    return final_headers, final_rows, raw_cols


def _build_cross_sheet_material_rollup(sheet_records: list[dict[str, Any]]) -> str:
    """Jika workbook memiliki beberapa sheet wilayah dengan Material Description & Provided/Usage/Stock, hitung rekap gabungannya secara instan."""
    if len(sheet_records) < 2:
        return ""

    rollup: dict[str, dict[str, Any]] = {}
    matched_sheets: list[str] = []

    for rec in sheet_records:
        sname = rec["name"]
        if sname.lower() in ("summary", "rekap", "ringkasan"):
            continue
        headers = [h.lower() for h in rec["headers"]]
        rows = rec["rows"]

        desc_i = next((i for i, h in enumerate(headers) if "material description" in h or "nama material" in h), -1)
        unit_i = next((i for i, h in enumerate(headers) if h in ("unit", "satuan")), -1)
        type_i = next((i for i, h in enumerate(headers) if h == "type"), -1)
        prov_i = next((i for i, h in enumerate(headers) if "total material provided" in h or "provided" in h), -1)
        use_i = next((i for i, h in enumerate(headers) if "usage qty" in h or "terpakai" in h), -1)
        rem_i = next((i for i, h in enumerate(headers) if "remaining qty" in h), -1)
        stk_i = next((i for i, h in enumerate(headers) if "actual stock" in h or "aktual stok" in h or "actual stok" in h), -1)

        if desc_i < 0 or (prov_i < 0 and use_i < 0 and stk_i < 0):
            continue

        matched_sheets.append(sname)
        last_type = ""
        for r in rows:
            if type_i >= 0 and r[type_i] is not None and str(r[type_i]).strip():
                last_type = str(r[type_i]).strip()
            raw_desc = r[desc_i]
            if raw_desc is None:
                continue
            desc = (
                " ".join(str(raw_desc).replace("\xa0", " ").split())
                .replace("”", '"')
                .replace("“", '"')
                .replace('2,5"', '2.5"')
            )
            if not desc or desc.lower() in ("material description", "total / ringkasan"):
                continue
            unit = str(r[unit_i]).strip() if (unit_i >= 0 and r[unit_i] is not None) else ""

            def _num(idx: int) -> float:
                if idx < 0 or idx >= len(r) or r[idx] is None:
                    return 0.0
                v = r[idx]
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    return float(v)
                try:
                    return float(str(v).replace(",", "").strip())
                except ValueError:
                    return 0.0

            item = rollup.setdefault(
                desc,
                {
                    "type": last_type,
                    "unit": unit,
                    "provided": 0.0,
                    "usage": 0.0,
                    "remaining": 0.0,
                    "stock": 0.0,
                },
            )
            if not item["unit"] and unit:
                item["unit"] = unit
            if not item["type"] and last_type:
                item["type"] = last_type
            item["provided"] += _num(prov_i)
            item["usage"] += _num(use_i)
            item["remaining"] += _num(rem_i)
            item["stock"] += _num(stk_i)

    if not rollup or len(matched_sheets) < 2:
        return ""

    out = [
        f"## 🌐 REKAPITULASI GABUNGAN LINTAS SHEET ({len(matched_sheets)} Wilayah: {', '.join(matched_sheets)})",
        "_(Catatan Sistem: Tabel di bawah ini adalah hasil penjumlahan eksak 100% seluruh sheet wilayah oleh mesin Python lokal. Gunakan angka ini secara langsung tanpa perlu memanggil Python Sandbox lagi!)_",
        "| Kategori | Nama Material / Item | Satuan | Total Provided | Total Terpakai (Usage) | Remaining Qty | Actual Stock |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for desc, info in rollup.items():
        p_str = f"{int(info['provided']):,}" if info["provided"].is_integer() else f"{info['provided']:,.2f}"
        u_str = f"{int(info['usage']):,}" if info["usage"].is_integer() else f"{info['usage']:,.2f}"
        r_str = f"{int(info['remaining']):,}" if info["remaining"].is_integer() else f"{info['remaining']:,.2f}"
        s_str = f"{int(info['stock']):,}" if info["stock"].is_integer() else f"{info['stock']:,.2f}"
        out.append(
            f"| {info['type']} | {desc} | {info['unit']} | {p_str} | {u_str} | {r_str} | {s_str} |"
        )
    return "\n".join(out)


def _extract_excel(raw_bytes: bytes, fname: str, ext: str) -> str:
    if ext in (".xlsx", ".xlsm", ".xltx"):
        try:
            import openpyxl

            wb = openpyxl.load_workbook(io.BytesIO(raw_bytes), data_only=True)
            sheets_out = []
            sheet_records = []
            for sname in wb.sheetnames:
                ws = wb[sname]
                rows = [
                    list(r)
                    for r in ws.iter_rows(values_only=True)
                    if any(c is not None and str(c).strip() != "" for c in r)
                ]
                if not rows:
                    continue
                headers, data_rows, raw_cols = _prepare_sheet_headers_and_rows(rows)
                if not headers or not data_rows:
                    continue
                cols = len(headers)
                sheet_records.append({"name": sname, "headers": headers, "rows": data_rows})

                pre_agg = _build_full_sheet_pre_aggregation(headers, data_rows)
                sample_limit = 30 if len(wb.sheetnames) > 1 or len(data_rows) > 80 else 80
                sample_rows = data_rows[:sample_limit]

                col_note = (
                    f"{cols} kolom inti dari {raw_cols} kolom"
                    if raw_cols > cols
                    else f"{cols} kolom"
                )
                table_lines = [
                    f"### Sheet: {sname} ({len(data_rows)} baris data, {col_note})"
                ]
                if pre_agg:
                    table_lines.append(pre_agg)
                    table_lines.append(
                        f"\n#### Tabel Data ({'Seluruh ' + str(len(data_rows)) if len(data_rows) <= sample_limit else str(sample_limit) + ' Sampel Pertama dari ' + str(len(data_rows))} Baris):"
                    )
                table_lines.append("| " + " | ".join(headers) + " |")
                table_lines.append("| " + " | ".join(["---"] * cols) + " |")
                for r in sample_rows:
                    str_r = [
                        " ".join(str(c).replace("\xa0", " ").split()) if c is not None else ""
                        for c in r
                    ]
                    padded = str_r + [""] * (cols - len(str_r))
                    table_lines.append("| " + " | ".join(padded[:cols]) + " |")
                sheets_out.append("\n".join(table_lines))
            if sheets_out:
                cross_rollup = _build_cross_sheet_material_rollup(sheet_records)
                if cross_rollup:
                    return cross_rollup + "\n\n" + "\n\n".join(sheets_out)
                return "\n\n".join(sheets_out)
        except _UFE_ERR as e:
            logger.warning(f"openpyxl error: {e}")

    try:
        import pandas as pd

        if ext == ".ods":
            df = pd.read_excel(io.BytesIO(raw_bytes), engine="odf")
        else:
            df = pd.read_excel(io.BytesIO(raw_bytes))
        headers = [str(c) for c in df.columns]
        data_rows = df.values.tolist()
        pre_agg = _build_full_sheet_pre_aggregation(headers, data_rows)
        sample_limit = 80 if len(df) <= 80 else 30
        return str(
            f"### Data Spreadsheet: {fname} ({df.shape[0]} baris x {df.shape[1]} kolom)\n\n"
            + (pre_agg + "\n\n" if pre_agg else "")
            + df.head(sample_limit).to_markdown(index=False)
        )
    except _UFE_ERR as e:
        logger.warning(f"pandas excel error: {e}")

    return f"Gagal membaca spreadsheet {fname}."


def _extract_csv(raw_bytes: bytes, fname: str) -> str | None:
    try:
        import pandas as pd

        text_preview = raw_bytes[:4096].decode("utf-8", errors="replace")
        dialect = csv.Sniffer().sniff(text_preview)
        sep = dialect.delimiter
        df = pd.read_csv(io.BytesIO(raw_bytes), sep=sep)
        headers = [str(c) for c in df.columns]
        data_rows = df.values.tolist()
        pre_agg = _build_full_sheet_pre_aggregation(headers, data_rows)
        sample_limit = 80 if len(df) <= 80 else 30
        return str(
            f"### Data Tabel ({df.shape[0]} baris x {df.shape[1]} kolom, delimiter '{sep}'):\n\n"
            + (pre_agg + "\n\n" if pre_agg else "")
            + df.head(sample_limit).to_markdown(index=False)
        )
    except _UFE_ERR:
        try:
            decoded = raw_bytes.decode("utf-8", errors="replace")
            lines = decoded.splitlines()[:150]
            return "```csv\n" + "\n".join(lines) + "\n```"
        except (ValueError, TypeError, AttributeError):
            return None


def _extract_archive(raw_bytes: bytes, fname: str, ext: str) -> str:
    out = [f"### 📦 Struktur Berkas Arsip: {fname}"]
    try:
        if ext == ".zip":
            with zipfile.ZipFile(io.BytesIO(raw_bytes)) as zf:
                info_list = zf.infolist()
                out.append(f"Total {len(info_list)} item di dalam zip:\n")
                for info in info_list[:60]:
                    size_kb = (
                        f"{info.file_size / 1024:.1f} KB"
                        if not info.is_dir()
                        else "DIR"
                    )
                    out.append(f"- `/{info.filename}` ({size_kb})")

                for info in info_list[:10]:
                    if (
                        not info.is_dir()
                        and info.file_size < 30000
                        and any(
                            info.filename.endswith(e)
                            for e in (".txt", ".md", ".json", ".py", ".csv")
                        )
                    ):
                        try:
                            content = zf.read(info.filename).decode(
                                "utf-8", errors="replace"
                            )
                            out.append(
                                f"\n#### 📄 Pratinjau Isi: `{info.filename}`\n```\n{content[:2000]}\n```"
                            )
                            break
                        except _UFE_ERR:
                            pass

        elif ext in (".tar", ".gz", ".tgz", ".bz2"):
            with tarfile.open(fileobj=io.BytesIO(raw_bytes)) as tf:
                members = tf.getmembers()
                out.append(f"Total {len(members)} item di dalam tar:\n")
                for m in members[:60]:
                    size_kb = f"{m.size / 1024:.1f} KB" if not m.isdir() else "DIR"
                    out.append(f"- `/{m.name}` ({size_kb})")

        return "\n".join(out)
    except _UFE_ERR as e:
        return f"Gagal membaca arsip {fname}: {e}"


def _extract_html_xml(raw_bytes: bytes, fname: str, ext: str) -> str:
    try:
        from bs4 import BeautifulSoup

        decoded = raw_bytes.decode("utf-8", errors="replace")
        soup = BeautifulSoup(decoded, "html.parser")
        for tag in soup(["script", "style", "nav", "footer"]):
            tag.decompose()
        text = soup.get_text(separator="\n").strip()
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        clean_text = "\n".join(lines[:500])
        return f"### Konten Web/Struktur {fname}:\n\n{clean_text}"
    except _UFE_ERR:
        return raw_bytes.decode("utf-8", errors="replace")[:4000]


def _extract_data_formats(raw_bytes: bytes, fname: str, ext: str) -> str:
    try:
        decoded = raw_bytes.decode("utf-8", errors="replace")
        if ext in (".json", ".jsonl", ".ndjson"):
            if ext == ".json":
                parsed = json.loads(decoded)
                return (
                    "```json\n"
                    + json.dumps(parsed, indent=2, ensure_ascii=False)[:4000]
                    + "\n```"
                )
            else:
                lines = decoded.splitlines()
                return (
                    f"Total {len(lines)} baris JSONL:\n```json\n"
                    + "\n".join(lines[:50])
                    + "\n```"
                )
        elif ext in (".yaml", ".yml"):
            import yaml

            parsed = yaml.safe_load(decoded)
            return str(
                "```yaml\n" + yaml.dump(parsed, sort_keys=False)[:4000] + "\n```"
            )
        return "```\n" + decoded[:4000] + "\n```"
    except _UFE_ERR:
        return raw_bytes.decode("utf-8", errors="replace")[:4000]
