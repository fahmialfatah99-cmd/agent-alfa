# -*- coding: utf-8 -*-
"""
PDF Report generation, watermarking, page numbering, and image conversions.
"""

import io
import json
import logging
import os
from pathlib import Path
import subprocess
from typing import Any, Dict, List, Optional

from alfa.tools.registry import register_tool

logger = logging.getLogger("AgentTools.Media.PDFBuilder")


def get_pdf_output_dir(subfolder: str) -> str:
    """Returns absolute path to ~/Dokumen/ALFA_PDF_TOOLS/<subfolder>/ and ensures it exists."""
    home_dir = os.path.expanduser("~")
    dokumen_dir = os.path.join(home_dir, "Dokumen")
    if not os.path.exists(dokumen_dir):
        dokumen_dir = os.path.join(home_dir, "Documents")
    target_dir = os.path.join(dokumen_dir, "ALFA_PDF_TOOLS", subfolder)
    os.makedirs(target_dir, exist_ok=True)
    return target_dir


@register_tool(category="pdf")
def generate_pdf_report(title: str, summary: str, table_data_json: str = "", filename: str = "laporan.pdf") -> Dict[str, Any]:
    """
    Generate a modern, beautifully styled PDF document report with ReportLab and automatically send it to Telegram.
    
    Args:
        title: Main document title (e.g. 'Laporan Analisis Kinerja Server', 'Rangkuman Riset Pasar').
        summary: Paragraphs of text explaining the findings, recommendations, or content.
        table_data_json: Optional JSON string of 2D array for tables, e.g. '[["Header1", "Header2"], ["Val1", "Val2"]]'.
        filename: Output filename ending in .pdf.
    """
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table
        
        table_data = None
        if table_data_json:
            if isinstance(table_data_json, str):
                try:
                    table_data = json.loads(table_data_json)
                except Exception:
                    table_data = None
            elif isinstance(table_data_json, list):
                table_data = table_data_json
        
        out_dir = get_pdf_output_dir("Reports")
        safe_name = filename if filename.endswith(".pdf") else f"{filename}.pdf"
        target_path = os.path.join(out_dir, safe_name)
        
        doc = SimpleDocTemplate(target_path, pagesize=letter, rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40)
        styles = getSampleStyleSheet()
        
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=18,
            leading=22,
            textColor=colors.HexColor('#1E3A8A'),
            spaceAfter=15
        )
        
        body_style = ParagraphStyle(
            'CustomBody',
            parent=styles['Normal'],
            fontSize=10,
            leading=15,
            textColor=colors.HexColor('#334155'),
            spaceAfter=10
        )
        
        elements = [
            Paragraph(f"<b>{title}</b>", title_style),
            Spacer(1, 10),
        ]
        
        for paragraph in summary.split("\n\n"):
            if paragraph.strip():
                clean_p = paragraph.strip().replace("\n", "<br/>")
                elements.append(Paragraph(clean_p, body_style))
                elements.append(Spacer(1, 8))
                
        if table_data and len(table_data) > 0:
            elements.append(Spacer(1, 12))
            t = Table(table_data, style=[
                ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#1E3A8A')),
                ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
                ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
                ('FONTSIZE', (0,0), (-1,0), 10),
                ('BOTTOMPADDING', (0,0), (-1,0), 8),
                ('TOPPADDING', (0,0), (-1,0), 8),
                ('BACKGROUND', (0,1), (-1,-1), colors.HexColor('#F8FAFC')),
                ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#CBD5E1')),
                ('ALIGN', (0,0), (-1,-1), 'LEFT'),
                ('FONTSIZE', (0,1), (-1,-1), 9),
                ('TOPPADDING', (0,1), (-1,-1), 6),
                ('BOTTOMPADDING', (0,1), (-1,-1), 6),
            ])
            elements.append(t)
            
        doc.build(elements)
        return {
            "status": "success",
            "message": f"Dokumen PDF '{safe_name}' tersimpan di Dokumen/ALFA_PDF_TOOLS/Reports/.",
            "file_path": target_path,
            "filename": safe_name
        }
    except Exception as e:
        return {"status": "error", "message": f"Gagal membuat PDF: {str(e)}"}


@register_tool(category="pdf")
def pdf_apply_watermark_text(pdf_path: str, watermark_text: str, opacity: float = 0.2, angle: float = 45, output_filename: str = "watermarked.pdf") -> Dict[str, Any]:
    """
    Tambahkan stempel watermark teks diagonal transparan ke setiap halaman PDF.
    
    Args:
        pdf_path: Path ke file PDF asli.
        watermark_text: Teks watermark (misal 'CONFIDENTIAL', 'RAHASIA DOKUMEN', 'DRAFT').
        opacity: Tingkat transparansi (0.05 sampai 0.5).
        angle: Sudut kemiringan diagonal watermark (default 45 derajat).
        output_filename: Nama file output.
    """
    try:
        from pypdf import PdfReader, PdfWriter
        from reportlab.lib.colors import HexColor
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas as rl_canvas
        
        exp_p = os.path.expanduser(pdf_path.strip())
        if not os.path.exists(exp_p):
            return {"status": "error", "message": f"File '{pdf_path}' tidak ditemukan."}
            
        out_dir = get_pdf_output_dir("Watermark")
        safe_name = output_filename if output_filename.endswith(".pdf") else f"{output_filename}.pdf"
        target_path = os.path.join(out_dir, safe_name)
        
        packet = io.BytesIO()
        can = rl_canvas.Canvas(packet, pagesize=A4)
        can.setFont("Helvetica-Bold", 45)
        can.saveState()
        can.setFillAlpha(max(0.05, min(0.9, opacity)))
        can.setFillColor(HexColor("#64748B"))
        can.translate(A4[0] / 2, A4[1] / 2)
        can.rotate(angle)
        can.drawCentredString(0, 0, watermark_text)
        can.restoreState()
        can.save()
        packet.seek(0)
        
        wm_page = PdfReader(packet).pages[0]
        reader = PdfReader(exp_p)
        writer = PdfWriter()
        
        for p in reader.pages:
            p.merge_page(wm_page)
            writer.add_page(p)
            
        with open(target_path, "wb") as f_out:
            writer.write(f_out)
            
        return {
            "status": "success",
            "message": f"Watermark '{watermark_text}' berhasil ditempelkan di Dokumen/ALFA_PDF_TOOLS/Watermark/{safe_name}.",
            "file_path": target_path,
            "filename": safe_name
        }
    except Exception as e:
        return {"status": "error", "message": f"Gagal watermark PDF: {str(e)}"}


@register_tool(category="pdf")
def pdf_insert_page_numbers(pdf_path: str, position: str = "bottom-center", start_number: int = 1, output_filename: str = "numbered.pdf") -> Dict[str, Any]:
    """
    Sematkan penomoran halaman otomatis pada dokumen PDF.
    
    Args:
        pdf_path: Path ke file PDF.
        position: Posisi nomor ('bottom-center', 'bottom-right', 'bottom-left', 'top-right', 'top-center').
        start_number: Nomor awal penomoran halaman (default 1).
        output_filename: Nama file output.
    """
    try:
        from pypdf import PdfReader, PdfWriter
        from reportlab.lib.colors import HexColor
        from reportlab.pdfgen import canvas as rl_canvas
        
        exp_p = os.path.expanduser(pdf_path.strip())
        if not os.path.exists(exp_p):
            return {"status": "error", "message": f"File '{pdf_path}' tidak ditemukan."}
            
        out_dir = get_pdf_output_dir("Page_Numbers")
        safe_name = output_filename if output_filename.endswith(".pdf") else f"{output_filename}.pdf"
        target_path = os.path.join(out_dir, safe_name)
        
        reader = PdfReader(exp_p)
        writer = PdfWriter()
        total = len(reader.pages)
        
        for i, page in enumerate(reader.pages):
            w = float(page.mediabox.width)
            h = float(page.mediabox.height)
            packet = io.BytesIO()
            can = rl_canvas.Canvas(packet, pagesize=(w, h))
            can.setFont("Helvetica", 10)
            can.setFillColor(HexColor("#334155"))
            
            num_str = f"Halaman {start_number + i} dari {total}"
            positions = {
                "bottom-center": (w / 2, 25),
                "bottom-right": (w - 40, 25),
                "bottom-left": (40, 25),
                "top-center": (w / 2, h - 25),
                "top-right": (w - 40, h - 25),
            }
            x, y = positions.get(position, (w / 2, 25))
            can.drawCentredString(x, y, num_str)
            can.save()
            packet.seek(0)
            
            num_page = PdfReader(packet).pages[0]
            page.merge_page(num_page)
            writer.add_page(page)
            
        with open(target_path, "wb") as f_out:
            writer.write(f_out)
            
        return {
            "status": "success",
            "message": f"Nomor halaman berhasil ditambahkan di Dokumen/ALFA_PDF_TOOLS/Page_Numbers/{safe_name}.",
            "file_path": target_path,
            "filename": safe_name
        }
    except Exception as e:
        return {"status": "error", "message": f"Gagal memberi nomor halaman: {str(e)}"}


@register_tool(category="pdf")
def pdf_convert_to_images(pdf_path: str, dpi: int = 150, output_dir: str = "") -> Dict[str, Any]:
    """
    Konversi seluruh halaman PDF menjadi gambar PNG resolusi tinggi.
    
    Args:
        pdf_path: Path ke file PDF.
        dpi: Kerapatan resolusi gambar (default 150 DPI).
        output_dir: Folder penyimpanan gambar hasil konversi (opsional, default ke ~/Dokumen/ALFA_PDF_TOOLS/PDF_to_Images/).
    """
    try:
        exp_p = os.path.expanduser(pdf_path.strip())
        if not os.path.exists(exp_p):
            return {"status": "error", "message": f"File '{pdf_path}' tidak ditemukan."}
            
        base_name = Path(exp_p).stem
        target_dir = os.path.expanduser(output_dir.strip()) if output_dir else os.path.join(get_pdf_output_dir("PDF_to_Images"), base_name)
        os.makedirs(target_dir, exist_ok=True)
        
        out_prefix = os.path.join(target_dir, f"{base_name}_page")
        
        cmd = ["pdftoppm", "-png", "-r", str(dpi), exp_p, out_prefix]
        subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        
        generated_images = [os.path.join(target_dir, f) for f in os.listdir(target_dir) if f.startswith(f"{base_name}_page") and f.endswith(".png")]
        generated_images.sort()
        
        return {
            "status": "success",
            "message": f"Berhasil merender {len(generated_images)} halaman PDF menjadi gambar PNG di Dokumen/ALFA_PDF_TOOLS/PDF_to_Images/{base_name}/.",
            "output_dir": target_dir,
            "images": generated_images
        }
    except Exception as e:
        return {"status": "error", "message": f"Gagal konversi PDF ke gambar: {str(e)}"}


@register_tool(category="pdf")
def images_convert_to_pdf(image_paths: List[str], output_filename: str = "images_album.pdf") -> Dict[str, Any]:
    """
    Gabungkan kumpulan file foto/gambar (JPG, PNG, WEBP) menjadi satu dokumen PDF rapi.
    
    Args:
        image_paths: Daftar path file gambar yang ingin digabungkan ke PDF.
        output_filename: Nama file output PDF.
    """
    try:
        from PIL import Image
        out_dir = get_pdf_output_dir("Images_to_PDF")
        safe_name = output_filename if output_filename.endswith(".pdf") else f"{output_filename}.pdf"
        target_path = os.path.join(out_dir, safe_name)
        
        opened_images = []
        for p in image_paths:
            exp_p = os.path.expanduser(p.strip())
            if os.path.exists(exp_p):
                img = Image.open(exp_p).convert("RGB")
                opened_images.append(img)
                
        if not opened_images:
            return {"status": "error", "message": "Tidak ada file gambar valid yang ditemukan."}
            
        first = opened_images[0]
        rest = opened_images[1:] if len(opened_images) > 1 else []
        first.save(target_path, "PDF", resolution=100.0, save_all=True, append_images=rest)
        
        return {
            "status": "success",
            "message": f"Berhasil mengubah {len(opened_images)} gambar menjadi PDF di Dokumen/ALFA_PDF_TOOLS/Images_to_PDF/{safe_name}.",
            "file_path": target_path,
            "filename": safe_name
        }
    except Exception as e:
        return {"status": "error", "message": f"Gagal mengubah gambar ke PDF: {str(e)}"}
