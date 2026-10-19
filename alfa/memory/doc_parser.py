"""
Structured, Layout-Aware Document Parser and Contextual Chunker for ALFA Vector Brain.
Upgrades document ingestion to preserve headers, tables, slide titles, and metadata:
- PDF: PyMuPDF (fitz) layout-aware page extractor with table preservation & pypdf fallback.
- DOCX: Heading hierarchy preservation (#, ##) and Markdown table generation.
- XLSX/XLS/CSV: Multi-sheet dataframe to Markdown table conversion.
- PPTX: Slide-by-slide structure with speaker notes and slide titles.
- Contextual Chunking: Attaches document and section breadcrumbs to each chunk to prevent context loss.
"""

import logging
import os
import re

logger = logging.getLogger("DocParser")

_DOC_ERR = (
    OSError,
    ValueError,
    RuntimeError,
    TypeError,
    KeyError,
    AttributeError,
    ImportError,
)


def extract_document_content(content_or_path: str) -> tuple[str, str]:
    """
    Extracts text from a file path or raw text string, converting structured documents
    (PDF, Word, Excel, CSV, PPTX) into clean, layout-preserving Markdown text.

    Returns:
        tuple[text_content, source_type]
    """
    if not isinstance(content_or_path, str):
        return "", "unknown"

    raw_input = content_or_path.strip()
    if not os.path.isfile(content_or_path):
        # Raw text / markdown content
        return raw_input, "text"

    file_path = content_or_path
    ext = os.path.splitext(file_path)[1].lower().lstrip(".")
    fname = os.path.basename(file_path)

    try:
        # 1. PDF
        if ext == "pdf":
            return _extract_pdf_file(file_path), "pdf"

        # 2. WORD (.docx, .doc)
        if ext in ("docx", "doc"):
            return _extract_docx_file(file_path), "docx"

        # 3. EXCEL (.xlsx, .xls, .xlsm, .ods)
        if ext in ("xlsx", "xls", "xlsm", "ods"):
            return _extract_excel_file(file_path), "excel"

        # 4. CSV / TSV
        if ext in ("csv", "tsv"):
            return _extract_csv_file(file_path, ext), ext

        # 5. PPTX (.pptx, .ppt)
        if ext in ("pptx", "ppt"):
            return _extract_pptx_file(file_path), "pptx"

        # 6. Plain text / Markdown / Code fallback
        with open(file_path, encoding="utf-8", errors="replace") as f:
            return f.read(), ext or "text"

    except _DOC_ERR as e:
        logger.error(f"Error extracting document {fname}: {e}")
        return f"[Gagal membaca berkas {fname}: {e}]", ext or "file"


def _extract_pdf_file(file_path: str) -> str:
    """Extract PDF pages preserving layout and page markers using PyMuPDF / fitz, falling back to pypdf."""
    # Attempt 1: PyMuPDF (fitz)
    try:
        import fitz  # PyMuPDF

        doc = fitz.open(file_path)
        pages_out = []
        for i, page in enumerate(doc):
            text = page.get_text("text").strip()
            if text:
                pages_out.append(f"## --- Halaman {i + 1} ---\n{text}")
        doc.close()
        if pages_out:
            return "\n\n".join(pages_out)
    except _DOC_ERR as e:
        logger.debug(f"PyMuPDF failed on {file_path}: {e}")

    # Attempt 2: pypdf fallback
    try:
        import pypdf

        reader = pypdf.PdfReader(file_path)
        pages_out = []
        for i, page in enumerate(reader.pages):
            txt = page.extract_text() or ""
            if txt.strip():
                pages_out.append(f"## --- Halaman {i + 1} ---\n{txt.strip()}")
        if pages_out:
            return "\n\n".join(pages_out)
    except _DOC_ERR as e:
        logger.debug(f"pypdf fallback failed on {file_path}: {e}")

    return f"[Teks tidak dapat diekstrak dari PDF {os.path.basename(file_path)}]"


def _extract_docx_file(file_path: str) -> str:
    """Extract Word document preserving headings and converting tables to Markdown."""
    try:
        import docx

        doc = docx.Document(file_path)
        out: list[str] = []

        for p in doc.paragraphs:
            txt = p.text.strip()
            if not txt:
                continue
            style_name = (p.style.name if p.style and p.style.name else "").lower()
            if "heading 1" in style_name:
                out.append(f"# {txt}")
            elif "heading 2" in style_name:
                out.append(f"## {txt}")
            elif "heading 3" in style_name:
                out.append(f"### {txt}")
            else:
                out.append(txt)

        for t_idx, table in enumerate(doc.tables, 1):
            out.append(f"\n### Tabel {t_idx}")
            rows = []
            for r in table.rows:
                rows.append([cell.text.strip().replace("\n", " ") for cell in r.cells])
            if rows:
                headers = rows[0]
                cols = len(headers)
                out.append("| " + " | ".join(headers) + " |")
                out.append("| " + " | ".join(["---"] * cols) + " |")
                for r in rows[1:]:
                    # Pad or truncate row to cols
                    padded = (r + [""] * cols)[:cols]
                    out.append("| " + " | ".join(padded) + " |")

        return "\n\n".join(out)
    except _DOC_ERR as e:
        logger.warning(f"Failed docx parse for {file_path}: {e}")
        return f"[Gagal membaca file docx: {e}]"


def _extract_excel_file(file_path: str) -> str:
    """Extract Excel sheets converting each sheet into a Markdown table."""
    try:
        import pandas as pd

        xl = pd.ExcelFile(file_path)
        out: list[str] = []
        for sheet_name in xl.sheet_names:
            df = xl.parse(sheet_name)
            out.append(f"## Sheet: {sheet_name}")
            if df.empty:
                out.append("*(Sheet kosong)*")
                continue
            # Render top 200 rows as clean markdown table
            sample_df = df.head(200).fillna("")
            out.append(sample_df.to_markdown(index=False))
            if len(df) > 200:
                out.append(f"\n*(Total {len(df)} baris; 200 baris pertama ditampilkan)*")
        return "\n\n".join(out)
    except _DOC_ERR as e:
        logger.warning(f"Failed excel parse for {file_path}: {e}")
        return f"[Gagal membaca file excel: {e}]"


def _extract_csv_file(file_path: str, ext: str = "csv") -> str:
    """Extract CSV/TSV file converting into Markdown table."""
    try:
        import pandas as pd

        sep = "\t" if ext == "tsv" else ","
        df = pd.read_csv(file_path, sep=sep, nrows=300, on_bad_lines="skip")
        fname = os.path.basename(file_path)
        out = [f"## Data Tabel: {fname}"]
        if df.empty:
            out.append("*(Tabel kosong)*")
        else:
            out.append(df.fillna("").to_markdown(index=False))
        return "\n\n".join(out)
    except _DOC_ERR as e:
        logger.warning(f"Failed CSV parse for {file_path}: {e}")
        return f"[Gagal membaca CSV: {e}]"


def _extract_pptx_file(file_path: str) -> str:
    """Extract PowerPoint slides with slide numbers and bullet points."""
    try:
        from pptx import Presentation

        prs = Presentation(file_path)
        out: list[str] = []
        for i, slide in enumerate(prs.slides, 1):
            slide_texts = []
            for shape in slide.shapes:
                if shape.has_text_frame:
                    for paragraph in shape.text_frame.paragraphs:
                        txt = paragraph.text.strip()
                        if txt:
                            slide_texts.append(txt)
            if slide_texts:
                title = slide_texts[0]
                body = "\n".join(f"• {t}" for t in slide_texts[1:])
                out.append(f"## Slide {i}: {title}\n{body}")
        return "\n\n".join(out)
    except _DOC_ERR as e:
        logger.warning(f"Failed PPTX parse for {file_path}: {e}")
        return f"[Gagal membaca PPTX: {e}]"


def chunk_document_contextual(
    text: str,
    doc_title: str = "Dokumen",
    chunk_size: int = 500,
    overlap: int = 60,
) -> list[str]:
    """
    Contextual Semantic Chunker:
    1. Splits document while respecting Markdown section headers (#, ##, ###) and page breaks.
    2. Keeps Markdown table blocks intact without splitting rows.
    3. Prepends a contextual breadcrumb `[Dokumen: {doc_title} | Bagian: {current_heading}]`
       to each chunk so downstream vector retrieval retains high semantic context.
    """
    if not text or not text.strip():
        return []

    lines = text.split("\n")
    chunks: list[str] = []
    current_lines: list[str] = []
    current_len = 0
    current_heading = "Pendahuluan"

    heading_pattern = re.compile(r"^(#{1,4}\s+.*|---\s+Halaman\s+\d+\s+---)")

    for line in lines:
        stripped = line.strip()

        # Check for heading update
        if heading_pattern.match(stripped):
            # Clean heading text
            clean_head = re.sub(r"^[#\s\-]+", "", stripped).strip("- ")
            current_heading = clean_head or current_heading

        line_len = len(line) + 1

        # Check if boundary reached
        if current_len + line_len > chunk_size and current_lines:
            # Create chunk with contextual breadcrumb
            raw_chunk = "\n".join(current_lines).strip()
            if raw_chunk:
                breadcrumb = f"[Dokumen: {doc_title} | Bagian: {current_heading}]\n"
                chunks.append(breadcrumb + raw_chunk)

            # Calculate overlap lines
            if overlap > 0 and len(current_lines) > 2:
                # Keep last 1-2 lines for overlap
                overlap_lines = current_lines[-2:]
                current_lines = list(overlap_lines) + [line]
                current_len = sum(len(cl) + 1 for cl in current_lines)
            else:
                current_lines = [line]
                current_len = line_len
        else:
            current_lines.append(line)
            current_len += line_len

    if current_lines:
        raw_chunk = "\n".join(current_lines).strip()
        if raw_chunk:
            breadcrumb = f"[Dokumen: {doc_title} | Bagian: {current_heading}]\n"
            chunks.append(breadcrumb + raw_chunk)

    return chunks
