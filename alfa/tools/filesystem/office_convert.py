"""LibreOffice and MarkItDown document conversion, preview, and generation tools."""

import datetime
import glob
import logging
import os
import re
import subprocess
from typing import Any, Dict

from alfa.tools.registry import register_tool
from alfa.tools.system_tools import SANDBOX_DIR

logger = logging.getLogger("AgentTools.Filesystem.OfficeConvert")

@register_tool(category="file")
def markitdown_convert_document(source_path_or_url: str, output_filename: str = "") -> Dict[str, Any]:
    """
    MARKITDOWN SUITE: Convert any document (Office Word/PowerPoint/Excel, PDF, HTML, CSV, JSON, Audio)
    or public URL into clean, structured LLM-ready Markdown text.
    
    Args:
        source_path_or_url: Local file path or web URL to convert to Markdown.
        output_filename: Optional filename to save the resulting .md in ~/Dokumen/ALFA_SWARM_OUTPUTS/.
    """
    try:
        from markitdown import MarkItDown
        md = MarkItDown()
        
        target = os.path.expanduser(source_path_or_url.strip())
        result = md.convert(target)
        markdown_content = result.text_content
        
        saved_path = None
        if output_filename:
            out_dir = os.path.expanduser("~/Dokumen/ALFA_SWARM_OUTPUTS")
            os.makedirs(out_dir, exist_ok=True)
            if not output_filename.endswith(".md"):
                output_filename += ".md"
            saved_path = os.path.join(out_dir, output_filename)
            with open(saved_path, "w", encoding="utf-8") as f:
                f.write(markdown_content)
                
        return {
            "status": "success",
            "source": source_path_or_url,
            "title": getattr(result, "title", None) or os.path.basename(source_path_or_url),
            "content_length": len(markdown_content),
            "markdown_snippet": markdown_content[:2000] if len(markdown_content) > 2000 else markdown_content,
            "is_truncated": len(markdown_content) > 2000,
            "saved_file": saved_path
        }
    except Exception as e:
        return {"status": "error", "message": f"MarkItDown conversion failed: {str(e)}"}


@register_tool(category="file")
def libreoffice_convert_document(source_file: str, output_format: str = "pdf") -> Dict[str, Any]:
    """
    LIBREOFFICE SUITE: Universal Document Converter.
    Converts any document between formats using LibreOffice Headless engine.
    Supported inputs: ODT, DOCX, DOC, RTF, TXT, HTML, EPUB, ODS, XLSX, XLS, CSV, ODP, PPTX, PPT, ODG, SVG, PDF.
    Supported outputs: pdf, docx, odt, xlsx, ods, pptx, odp, html, txt, csv, png.
    The converted document is automatically sent to Telegram as a file attachment.
    
    Args:
        source_file: Path to source document (e.g. '~/Documents/report.docx' or 'data.xlsx').
        output_format: Target format (e.g. 'pdf', 'docx', 'odt', 'xlsx', 'ods', 'html', 'txt').
    """
    try:
        expanded = os.path.expanduser(source_file)
        if not os.path.exists(expanded):
            return {"status": "error", "message": f"File sumber tidak ditemukan: {source_file}"}
            
        out_fmt = output_format.lower().replace(".", "").strip()
        base_name = os.path.splitext(os.path.basename(expanded))[0]
        
        # Run libreoffice conversion with output dir as SANDBOX_DIR
        cmd = ["libreoffice", "--headless", "--convert-to", out_fmt, expanded, "--outdir", SANDBOX_DIR]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        
        expected_file = os.path.join(SANDBOX_DIR, f"{base_name}.{out_fmt}")
        if os.path.exists(expected_file) and os.path.getsize(expected_file) > 0:
            size_kb = round(os.path.getsize(expected_file) / 1024, 1)
            return {
                "status": "success",
                "message": f"Dokumen berhasil dikonversi ke '{base_name}.{out_fmt}' ({size_kb} KB) via LibreOffice dan akan dikirim ke Telegram.",
                "file_path": expected_file,
                "output_format": out_fmt
            }
            
        # Check for matching files in sandbox if name changed
        matches = glob.glob(os.path.join(SANDBOX_DIR, f"*.{out_fmt}"))
        if matches:
            latest = max(matches, key=os.path.getmtime)
            size_kb = round(os.path.getsize(latest) / 1024, 1)
            return {
                "status": "success",
                "message": f"Dokumen berhasil dikonversi ke '{os.path.basename(latest)}' ({size_kb} KB) via LibreOffice dan akan dikirim ke Telegram.",
                "file_path": latest,
                "output_format": out_fmt
            }
            
        return {"status": "error", "message": f"Konversi LibreOffice gagal: {res.stderr or res.stdout}"}
    except Exception as e:
        return {"status": "error", "message": f"LibreOffice conversion error: {str(e)}"}


@register_tool(category="file")
def libreoffice_render_page_previews(document_path: str, max_pages: int = 3, dpi: int = 150) -> Dict[str, Any]:
    """
    LIBREOFFICE SUITE: Document High-Res Page Preview Renderer.
    Converts any office document (DOCX, ODT, XLSX, ODS, PPTX, ODP, PDF, RTF) into
    high-resolution PNG page images using LibreOffice Headless + pdftoppm, allowing visual
    inspection directly in Telegram as photos without opening the desktop app.
    
    Args:
        document_path: Path to the office document or PDF.
        max_pages: Number of pages to render as images (1-10, default: 3).
        dpi: Image resolution DPI (default: 150).
    """
    try:
        expanded = os.path.expanduser(document_path)
        if not os.path.exists(expanded):
            return {"status": "error", "message": f"File dokumen tidak ditemukan: {document_path}"}
            
        base_name = os.path.splitext(os.path.basename(expanded))[0]
        ext = os.path.splitext(expanded)[1].lower()
        
        # Step 1: Ensure we have a PDF version
        if ext == ".pdf":
            pdf_path = expanded
            temp_pdf = None
        else:
            # Convert document to PDF first
            cmd_pdf = ["libreoffice", "--headless", "--convert-to", "pdf", expanded, "--outdir", "/tmp"]
            subprocess.run(cmd_pdf, capture_output=True, text=True, timeout=45)
            temp_pdf = os.path.join("/tmp", f"{base_name}.pdf")
            if not os.path.exists(temp_pdf):
                return {"status": "error", "message": "Gagal mengonversi dokumen ke PDF untuk rendering preview."}
            pdf_path = temp_pdf
            
        # Step 2: Render PDF pages to PNG via pdftoppm into SANDBOX_DIR
        out_prefix = os.path.join(SANDBOX_DIR, f"preview_{base_name}")
        pages_to_render = min(max(1, max_pages), 10)
        cmd_ppm = ["pdftoppm", "-png", "-r", str(dpi), "-f", "1", "-l", str(pages_to_render), pdf_path, out_prefix]
        res_ppm = subprocess.run(cmd_ppm, capture_output=True, text=True, timeout=30)
        
        # Clean up temp pdf if created
        if temp_pdf and os.path.exists(temp_pdf):
            try:
                os.remove(temp_pdf)
            except OSError:
                pass
                
        rendered_images = sorted(glob.glob(f"{out_prefix}-*.png"))
        if rendered_images:
            return {
                "status": "success",
                "message": f"Berhasil me-render {len(rendered_images)} halaman preview untuk '{os.path.basename(expanded)}'. Gambar akan langsung dikirim ke Telegram!",
                "rendered_pages": len(rendered_images),
                "images": [os.path.basename(img) for img in rendered_images]
            }
        return {"status": "error", "message": f"Gagal merender halaman: {res_ppm.stderr}"}
    except Exception as e:
        return {"status": "error", "message": f"LibreOffice render preview error: {str(e)}"}


@register_tool(category="file")
def libreoffice_create_document(doc_type: str, title: str, content_html_or_text: str, filename: str = "", export_format: str = "odt") -> Dict[str, Any]:
    """
    LIBREOFFICE SUITE: Create Professional Office Documents (Writer, Calc, Impress).
    Generates rich formatted LibreOffice documents (.odt, .ods, .odp) or Microsoft Office (.docx, .xlsx, .pptx)
    with headings, tables, styled sections, and exports directly to Telegram.
    
    Args:
        doc_type: 'writer' (Text document), 'calc' (Spreadsheet), 'impress' (Presentation).
        title: Title of the document.
        content_html_or_text: Rich HTML or text content (with <h1>, <h2>, <p>, <table>, <ul>, <b>, <i>).
        filename: Optional output filename (e.g. 'laporan_resmi.odt' or 'data_keuangan.xlsx').
        export_format: Target format ('odt', 'docx', 'pdf', 'ods', 'xlsx', 'odp', 'pptx').
    """
    try:
        dtype = doc_type.lower().strip()
        exp_fmt = export_format.lower().replace(".", "").strip()
        
        if not filename:
            clean_title = re.sub(r'[^a-zA-Z0-9_-]', '_', title.lower())[:30]
            filename = f"{clean_title}.{exp_fmt}"
        elif not filename.endswith(f".{exp_fmt}"):
            filename = f"{os.path.splitext(filename)[0]}.{exp_fmt}"
            
        dest_path = os.path.join(SANDBOX_DIR, filename)
        
        # Build clean styled HTML template
        html_doc = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
body {{ font-family: 'Liberation Sans', 'Segoe UI', Arial, sans-serif; margin: 40px; color: #1E293B; line-height: 1.6; }}
h1 {{ color: #1E3A8A; border-bottom: 2px solid #3B82F6; padding-bottom: 8px; font-size: 24pt; }}
h2 {{ color: #1E40AF; margin-top: 24px; font-size: 16pt; }}
h3 {{ color: #2563EB; font-size: 13pt; }}
p {{ font-size: 11pt; margin-bottom: 12px; }}
table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
th {{ background-color: #2563EB; color: white; padding: 10px; border: 1px solid #CBD5E1; text-align: left; }}
td {{ padding: 8px 10px; border: 1px solid #CBD5E1; }}
tr:nth-child(even) {{ background-color: #F8FAFC; }}
ul, ol {{ padding-left: 25px; }}
li {{ margin-bottom: 6px; }}
.footer {{ margin-top: 40px; font-size: 9pt; color: #64748B; border-top: 1px solid #E2E8F0; padding-top: 8px; }}
</style>
</head>
<body>
<h1>{title}</h1>
{content_html_or_text}
<div class="footer">Dibuat secara otomatis oleh Sovereign Telegram AI Agent via LibreOffice Engine | {datetime.datetime.now().strftime("%d %B %Y %H:%M")}</div>
</body>
</html>"""

        temp_html = os.path.join("/tmp", f"temp_lo_{os.getpid()}.html")
        with open(temp_html, "w", encoding="utf-8") as f:
            f.write(html_doc)
            
        # Convert via LibreOffice to target format
        cmd = ["libreoffice", "--headless", "--convert-to", exp_fmt, temp_html, "--outdir", SANDBOX_DIR]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=45)
        
        if os.path.exists(temp_html):
            try:
                os.remove(temp_html)
            except OSError:
                pass
                
        expected_out = os.path.join(SANDBOX_DIR, f"temp_lo_{os.getpid()}.{exp_fmt}")
        if os.path.exists(expected_out):
            os.rename(expected_out, dest_path)
            
        if os.path.exists(dest_path) and os.path.getsize(dest_path) > 0:
            size_kb = round(os.path.getsize(dest_path) / 1024, 1)
            return {
                "status": "success",
                "message": f"Dokumen LibreOffice '{filename}' ({size_kb} KB) berhasil dibuat dan akan dikirim ke Telegram.",
                "file_path": dest_path,
                "doc_type": dtype,
                "format": exp_fmt
            }
            
        return {"status": "error", "message": f"Gagal membuat dokumen LibreOffice: {res.stderr or res.stdout}"}
    except Exception as e:
        return {"status": "error", "message": f"Create LibreOffice document error: {str(e)}"}


@register_tool(category="file")
def libreoffice_extract_document_text(document_path: str) -> Dict[str, Any]:
    """
    LIBREOFFICE SUITE: Extract Text & Structure from Any Document.
    Extracts complete clean text from complex binary files (ODT, DOCX, DOC, RTF, ODS, ODP, EPUB, PDF)
    using LibreOffice Headless text filter.
    
    Args:
        document_path: Path to the document file.
    """
    try:
        expanded = os.path.expanduser(document_path)
        if not os.path.exists(expanded):
            return {"status": "error", "message": f"File tidak ditemukan: {document_path}"}
        
        temp_dir = f"/tmp/lo_txt_{os.getpid()}"
        os.makedirs(temp_dir, exist_ok=True)
        
        cmd = ["libreoffice", "--headless", "--convert-to", "txt:Text", expanded, "--outdir", temp_dir]
        subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        
        txt_files = glob.glob(os.path.join(temp_dir, "*.txt"))
        if txt_files:
            with open(txt_files[0], "r", encoding="utf-8", errors="replace") as f:
                extracted_text = f.read().strip()
                
            # Cleanup temp dir
            import shutil
            shutil.rmtree(temp_dir, ignore_errors=True)
            
            return {
                "status": "success",
                "document": os.path.basename(expanded),
                "character_count": len(extracted_text),
                "word_count": len(extracted_text.split()),
                "text_content": extracted_text[:8000]
            }
            
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)
        return {"status": "error", "message": "Tidak dapat mengekstrak teks dari dokumen via LibreOffice."}
    except Exception as e:
        return {"status": "error", "message": f"LibreOffice extract text error: {str(e)}"}

