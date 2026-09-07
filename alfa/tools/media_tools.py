"""Media generation, speech synthesis (TTS), PDF suite, and Office documents."""

import datetime
import glob
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional

from alfa.tools.registry import register_tool
from alfa.tools.system_tools import SANDBOX_DIR, normalize_path

logger = logging.getLogger("AgentTools.Media")



@register_tool(category="pdf")
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
        import json

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
def pdf_merge_documents(pdf_paths: List[str], output_filename: str = "merged.pdf") -> Dict[str, Any]:
    """
    Gabungkan beberapa file PDF menjadi satu dokumen PDF utuh.
    
    Args:
        pdf_paths: Daftar path file PDF yang ingin digabungkan (misal: ['/tmp/doc1.pdf', '/tmp/doc2.pdf']).
        output_filename: Nama file PDF hasil penggabungan (misal: 'merged_dokumen.pdf').
    """
    try:
        from pypdf import PdfReader, PdfWriter
        out_dir = get_pdf_output_dir("Merge")
        safe_name = output_filename if output_filename.endswith(".pdf") else f"{output_filename}.pdf"
        target_path = os.path.join(out_dir, safe_name)
        
        writer = PdfWriter()
        merged_count = 0
        total_pages = 0
        
        for p in pdf_paths:
            exp_p = os.path.expanduser(p.strip())
            if not os.path.exists(exp_p):
                continue
            reader = PdfReader(exp_p)
            for page in reader.pages:
                writer.add_page(page)
                total_pages += 1
            merged_count += 1
            
        if merged_count == 0:
            return {"status": "error", "message": "Tidak ada file PDF valid yang ditemukan untuk digabungkan."}
            
        with open(target_path, "wb") as f_out:
            writer.write(f_out)
            
        return {
            "status": "success",
            "message": f"Berhasil menggabungkan {merged_count} file PDF menjadi {total_pages} halaman di folder Dokumen/ALFA_PDF_TOOLS/Merge/.",
            "file_path": target_path,
            "filename": safe_name,
            "total_pages": total_pages,
            "file_size_bytes": os.path.getsize(target_path)
        }
    except Exception as e:
        logger.error(f"Error in pdf_merge_documents: {e}")
        return {"status": "error", "message": f"Gagal merge PDF: {str(e)}"}


@register_tool(category="pdf")
def pdf_split_document(pdf_path: str, page_ranges: str = "", output_dir: str = "") -> Dict[str, Any]:
    """
    Pecah file PDF per halaman atau berdasarkan rentang halaman tertentu (misal '1-3, 5, 8-10').
    
    Args:
        pdf_path: Path ke file PDF yang ingin dipecah.
        page_ranges: Rentang halaman yang ingin diekstrak (kosongkan untuk memecah semua halaman per file).
        output_dir: Direktori output file (opsional, default ke ~/Dokumen/ALFA_PDF_TOOLS/Split/).
    """
    try:
        from pathlib import Path

        from pypdf import PdfReader, PdfWriter
        exp_p = os.path.expanduser(pdf_path.strip())
        if not os.path.exists(exp_p):
            return {"status": "error", "message": f"File PDF '{pdf_path}' tidak ditemukan."}
            
        base_stem = Path(exp_p).stem
        target_dir = os.path.expanduser(output_dir.strip()) if output_dir else os.path.join(get_pdf_output_dir("Split"), base_stem)
        os.makedirs(target_dir, exist_ok=True)
        
        reader = PdfReader(exp_p)
        total = len(reader.pages)
        
        indices = []
        if page_ranges:
            for part in page_ranges.split(","):
                part = part.strip()
                if "-" in part:
                    s, e = part.split("-", 1)
                    s_idx = max(0, int(s.strip()) - 1)
                    e_idx = min(total, int(e.strip()))
                    indices.extend(range(s_idx, e_idx))
                elif part.isdigit():
                    idx = int(part) - 1
                    if 0 <= idx < total:
                        indices.append(idx)
            indices = sorted(list(set(indices)))
        else:
            indices = list(range(total))
            
        output_files = []
        for idx in indices:
            writer = PdfWriter()
            writer.add_page(reader.pages[idx])
            out_file = os.path.join(target_dir, f"{base_stem}_page_{idx+1:03d}.pdf")
            with open(out_file, "wb") as f_out:
                writer.write(f_out)
            output_files.append(out_file)
            
        return {
            "status": "success",
            "message": f"Berhasil memecah PDF menjadi {len(output_files)} file halaman di Dokumen/ALFA_PDF_TOOLS/Split/{base_stem}/.",
            "output_dir": target_dir,
            "files": output_files
        }
    except Exception as e:
        logger.error(f"Error in pdf_split_document: {e}")
        return {"status": "error", "message": f"Gagal split PDF: {str(e)}"}


@register_tool(category="pdf")
def pdf_extract_full_text(pdf_path: str, page_numbers: str = "") -> Dict[str, Any]:
    """
    Ekstrak teks lengkap dari dokumen PDF secara bersih dan terstruktur serta simpan salinan file .txt.
    
    Args:
        pdf_path: Path ke file PDF yang ingin dibaca teksnya.
        page_numbers: Opsi nomor halaman spesifik (misal '1,2,5' atau '1-4').
    """
    try:
        from pathlib import Path
        exp_p = os.path.expanduser(pdf_path.strip())
        if not os.path.exists(exp_p):
            return {"status": "error", "message": f"File PDF '{pdf_path}' tidak ditemukan."}
            
        extracted_pages = []
        import pdfplumber
        with pdfplumber.open(exp_p) as pdf:
            total_pages = len(pdf.pages)
            indices = list(range(total_pages))
            if page_numbers:
                req_indices = []
                for p in page_numbers.split(","):
                    p = p.strip()
                    if "-" in p:
                        s, e = p.split("-", 1)
                        req_indices.extend(range(max(0, int(s)-1), min(total_pages, int(e))))
                    elif p.isdigit():
                        idx = int(p) - 1
                        if 0 <= idx < total_pages:
                            req_indices.append(idx)
                indices = sorted(list(set(req_indices)))
                
            for idx in indices:
                t = pdf.pages[idx].extract_text() or ""
                extracted_pages.append(f"--- [Halaman {idx+1}/{total_pages}] ---\n{t.strip()}")
                
        full_text = "\n\n".join(extracted_pages)
        
        # Save to Dokumen/ALFA_PDF_TOOLS/Extract_Text/
        out_dir = get_pdf_output_dir("Extract_Text")
        txt_filename = f"{Path(exp_p).stem}_extracted.txt"
        target_path = os.path.join(out_dir, txt_filename)
        with open(target_path, "w", encoding="utf-8") as f_txt:
            f_txt.write(full_text)
            
        return {
            "status": "success",
            "message": f"Teks berhasil diekstrak dan disimpan di Dokumen/ALFA_PDF_TOOLS/Extract_Text/{txt_filename}.",
            "file_path": target_path,
            "filename": txt_filename,
            "total_pages": total_pages,
            "extracted_pages_count": len(extracted_pages),
            "text_length_chars": len(full_text),
            "text_preview": full_text[:4000],
            "full_text": full_text
        }
    except Exception as e:
        try:
            from pathlib import Path

            from pypdf import PdfReader
            reader = PdfReader(exp_p)
            texts = [f"--- [Halaman {i+1}] ---\n{p.extract_text() or ''}" for i, p in enumerate(reader.pages)]
            full = "\n\n".join(texts)
            out_dir = get_pdf_output_dir("Extract_Text")
            txt_filename = f"{Path(exp_p).stem}_extracted.txt"
            target_path = os.path.join(out_dir, txt_filename)
            with open(target_path, "w", encoding="utf-8") as f_txt:
                f_txt.write(full)
            return {
                "status": "success",
                "message": f"Teks berhasil diekstrak dan disimpan di Dokumen/ALFA_PDF_TOOLS/Extract_Text/{txt_filename}.",
                "file_path": target_path,
                "filename": txt_filename,
                "total_pages": len(reader.pages),
                "text_preview": full[:4000],
                "full_text": full
            }
        except Exception as err2:
            return {"status": "error", "message": f"Gagal ekstrak teks PDF: {str(err2)}"}


@register_tool(category="pdf")
def pdf_encrypt_password(pdf_path: str, password: str, output_filename: str = "protected.pdf") -> Dict[str, Any]:
    """
    Lindungi dan kunci file PDF dengan password menggunakan enkripsi kuat AES-256.
    
    Args:
        pdf_path: Path ke file PDF yang ingin dienkripsi.
        password: Password pengunci dokumen.
        output_filename: Nama file output terenkripsi.
    """
    try:
        from pypdf import PdfReader, PdfWriter
        exp_p = os.path.expanduser(pdf_path.strip())
        if not os.path.exists(exp_p):
            return {"status": "error", "message": f"File '{pdf_path}' tidak ditemukan."}
            
        out_dir = get_pdf_output_dir("Encrypt")
        safe_name = output_filename if output_filename.endswith(".pdf") else f"{output_filename}.pdf"
        target_path = os.path.join(out_dir, safe_name)
        
        reader = PdfReader(exp_p)
        writer = PdfWriter()
        for p in reader.pages:
            writer.add_page(p)
            
        writer.encrypt(user_password=password, owner_password=password, algorithm="AES-256")
        with open(target_path, "wb") as f_out:
            writer.write(f_out)
            
        return {
            "status": "success",
            "message": f"Dokumen PDF berhasil dienkripsi dengan AES-256 di Dokumen/ALFA_PDF_TOOLS/Encrypt/{safe_name}.",
            "file_path": target_path,
            "filename": safe_name
        }
    except Exception as e:
        return {"status": "error", "message": f"Gagal enkripsi PDF: {str(e)}"}


@register_tool(category="pdf")
def pdf_decrypt_password(pdf_path: str, password: str, output_filename: str = "unlocked.pdf") -> Dict[str, Any]:
    """
    Buka kunci PDF yang terproteksi password dan simpan salinan tanpa password.
    
    Args:
        pdf_path: Path ke file PDF terenkripsi.
        password: Password yang digunakan untuk membuka kunci.
        output_filename: Nama file output yang sudah tidak terkunci.
    """
    try:
        from pypdf import PdfReader, PdfWriter
        exp_p = os.path.expanduser(pdf_path.strip())
        if not os.path.exists(exp_p):
            return {"status": "error", "message": f"File '{pdf_path}' tidak ditemukan."}
            
        out_dir = get_pdf_output_dir("Decrypt")
        safe_name = output_filename if output_filename.endswith(".pdf") else f"{output_filename}.pdf"
        target_path = os.path.join(out_dir, safe_name)
        
        reader = PdfReader(exp_p)
        if reader.is_encrypted:
            res = reader.decrypt(password)
            if not res:
                return {"status": "error", "message": "Password salah atau PDF tidak dapat didekripsi."}
                
        writer = PdfWriter()
        for p in reader.pages:
            writer.add_page(p)
            
        with open(target_path, "wb") as f_out:
            writer.write(f_out)
            
        return {
            "status": "success",
            "message": f"PDF berhasil didekripsi di Dokumen/ALFA_PDF_TOOLS/Decrypt/{safe_name}.",
            "file_path": target_path,
            "filename": safe_name
        }
    except Exception as e:
        return {"status": "error", "message": f"Gagal dekripsi PDF: {str(e)}"}


@register_tool(category="pdf")
def pdf_rotate_pages(pdf_path: str, angle: int = 90, page_numbers: str = "", output_filename: str = "rotated.pdf") -> Dict[str, Any]:
    """
    Putar orientasi halaman PDF (90, 180, atau 270 derajat searah jarum jam).
    
    Args:
        pdf_path: Path ke file PDF.
        angle: Sudut putar (90, 180, 270).
        page_numbers: Halaman tertentu yang ingin diputar (misal '1,3-5', kosongkan untuk semua).
        output_filename: Nama file output.
    """
    try:
        from pypdf import PdfReader, PdfWriter
        exp_p = os.path.expanduser(pdf_path.strip())
        if not os.path.exists(exp_p):
            return {"status": "error", "message": f"File '{pdf_path}' tidak ditemukan."}
            
        out_dir = get_pdf_output_dir("Rotate")
        safe_name = output_filename if output_filename.endswith(".pdf") else f"{output_filename}.pdf"
        target_path = os.path.join(out_dir, safe_name)
        
        reader = PdfReader(exp_p)
        writer = PdfWriter()
        total = len(reader.pages)
        
        target_indices = list(range(total))
        if page_numbers:
            req = []
            for p in page_numbers.split(","):
                p = p.strip()
                if "-" in p:
                    s, e = p.split("-", 1)
                    req.extend(range(max(0, int(s)-1), min(total, int(e))))
                elif p.isdigit():
                    idx = int(p) - 1
                    if 0 <= idx < total:
                        req.append(idx)
            target_indices = list(set(req))
            
        for i, page in enumerate(reader.pages):
            if i in target_indices:
                page.rotate(angle)
            writer.add_page(page)
            
        with open(target_path, "wb") as f_out:
            writer.write(f_out)
            
        return {
            "status": "success",
            "message": f"Berhasil memutar {len(target_indices)} halaman PDF sebesar {angle}° di Dokumen/ALFA_PDF_TOOLS/Rotate/{safe_name}.",
            "file_path": target_path,
            "filename": safe_name
        }
    except Exception as e:
        return {"status": "error", "message": f"Gagal rotasi PDF: {str(e)}"}


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
        import io

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
        import io

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
        from pathlib import Path
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


@register_tool(category="media")
def upscale_image_hd(
    image_path: str,
    scale: int = 2,
    mode: str = "auto",
    denoise: int = 1,
    output_filename: str = ""
) -> Dict[str, Any]:
    """
    Perbesar (scale / upscale / super-resolution) resolusi gambar/foto 2x, 4x, atau 8x dengan AI Waifu2x Engine atau Lanczos HD Enhancement.
    
    Args:
        image_path: Path ke file gambar (PNG, JPG, WEBP, BMP).
        scale: Faktor perbesaran (2, 4, atau 8, default: 2).
        mode: Mode upscale ('waifu2x_anime', 'waifu2x_photo', 'lanczos_hd', 'pixel_art', atau 'auto').
        denoise: Tingkat pembersihan noise/bintik (0: off, 1: low, 2: medium, 3: high).
        output_filename: Nama file hasil perbesaran (opsional).
    """
    try:
        import subprocess

        from PIL import Image, ImageFilter

        exp_p = os.path.expanduser(image_path.strip())
        if not os.path.exists(exp_p):
            return {"status": "error", "message": f"File gambar tidak ditemukan di '{image_path}'."}

        out_dir = os.path.expanduser("~/Dokumen/ALFA_PDF_TOOLS/Image_Upscaling")
        os.makedirs(out_dir, exist_ok=True)

        base_name = os.path.splitext(os.path.basename(exp_p))[0]
        ext = os.path.splitext(exp_p)[1].lower() or ".png"
        if ext not in (".png", ".jpg", ".jpeg", ".webp"):
            ext = ".png"

        scale_factor = int(scale) if scale in (2, 4, 8) else 2
        safe_name = output_filename if output_filename else f"{base_name}_upscaled_{scale_factor}x{ext}"
        if not safe_name.endswith(ext):
            safe_name += ext
        target_path = os.path.join(out_dir, safe_name)

        used_engine = "Lanczos Ultra-HD"

        # 1. Try waifu2x-ncnn-vulkan if requested or auto
        waifu_bin = "/home/fahmial/telegram-ai-bot/bin/waifu2x/waifu2x-ncnn-vulkan-20250915-linux/waifu2x-ncnn-vulkan"
        model_dir = "/home/fahmial/telegram-ai-bot/bin/waifu2x/waifu2x-ncnn-vulkan-20250915-linux"
        
        if mode in ("waifu2x_anime", "waifu2x_photo", "auto") and os.path.exists(waifu_bin):
            selected_model = "models-cunet"
            if mode == "waifu2x_anime":
                selected_model = "models-upconv_7_anime_style_art_rgb"
            elif mode == "waifu2x_photo":
                selected_model = "models-upconv_7_photo"
            
            cmd = [
                waifu_bin,
                "-i", exp_p,
                "-o", target_path,
                "-s", str(scale_factor),
                "-n", str(max(0, min(3, int(denoise)))),
                "-m", os.path.join(model_dir, selected_model),
            ]
            try:
                sub_res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
                if sub_res.returncode == 0 and os.path.exists(target_path):
                    used_engine = f"Waifu2x AI ({selected_model})"
            except Exception:
                pass

        # 2. Fallback to PIL Advanced Lanczos + Unsharp Sharpening if target_path not yet created
        if not os.path.exists(target_path):
            img = Image.open(exp_p).convert("RGBA" if ext == ".png" else "RGB")
            orig_w, orig_h = img.size
            new_w, new_h = orig_w * scale_factor, orig_h * scale_factor

            if mode == "pixel_art":
                upscaled = img.resize((new_w, new_h), resample=Image.Resampling.NEAREST)
                used_engine = "Nearest Neighbor (Pixel Art)"
            else:
                upscaled = img.resize((new_w, new_h), resample=Image.Resampling.LANCZOS)
                if ext != ".png" or img.mode == "RGB":
                    upscaled = upscaled.filter(ImageFilter.UnsharpMask(radius=2, percent=140, threshold=3))
                used_engine = "Lanczos High-Fidelity + Edge Sharpener"

            upscaled.save(target_path, quality=95 if ext in (".jpg", ".jpeg") else None)

        out_img = Image.open(target_path)
        out_w, out_h = out_img.size
        size_kb = os.path.getsize(target_path) / 1024

        return {
            "status": "success",
            "message": f"Berhasil memperbesar gambar {scale_factor}x ({used_engine}) menjadi {out_w}x{out_h} px di {target_path}.",
            "file_path": target_path,
            "filename": safe_name,
            "engine": used_engine,
            "original_resolution": f"{out_w // scale_factor}x{out_h // scale_factor}",
            "new_resolution": f"{out_w}x{out_h}",
            "scale": scale_factor,
            "size_kb": round(size_kb, 1)
        }
    except Exception as e:
        return {"status": "error", "message": f"Gagal memperbesar resolusi gambar: {str(e)}"}


@register_tool(category="pdf")
def pdf_inspect_metadata(pdf_path: str) -> Dict[str, Any]:
    """
    Periksa informasi teknis mendalam dari file PDF (jumlah halaman, versi PDF, ukuran file, enkripsi, metadata) dan simpan salinan JSON.
    
    Args:
        pdf_path: Path ke file PDF yang ingin diinspeksi.
    """
    try:
        from pathlib import Path

        from pypdf import PdfReader
        exp_p = os.path.expanduser(pdf_path.strip())
        if not os.path.exists(exp_p):
            return {"status": "error", "message": f"File '{pdf_path}' tidak ditemukan."}
            
        reader = PdfReader(exp_p)
        meta = reader.metadata or {}
        
        first_page = reader.pages[0] if reader.pages else None
        width_pt = float(first_page.mediabox.width) if first_page else 0
        height_pt = float(first_page.mediabox.height) if first_page else 0
        
        info = {
            "status": "success",
            "file_name": os.path.basename(exp_p),
            "file_path": exp_p,
            "file_size_kb": round(os.path.getsize(exp_p) / 1024, 2),
            "total_pages": len(reader.pages),
            "is_encrypted": reader.is_encrypted,
            "dimensions_pt": f"{width_pt:.1f} x {height_pt:.1f}",
            "title": meta.get("/Title") or meta.title or "N/A",
            "author": meta.get("/Author") or meta.author or "N/A",
            "creator": meta.get("/Creator") or meta.creator or "N/A",
            "producer": meta.get("/Producer") or meta.producer or "N/A"
        }
        
        # Save json copy to Dokumen/ALFA_PDF_TOOLS/Inspect/
        out_dir = get_pdf_output_dir("Inspect")
        json_file = os.path.join(out_dir, f"{Path(exp_p).stem}_metadata.json")
        with open(json_file, "w", encoding="utf-8") as f_j:
            json.dump(info, f_j, indent=2, default=str)
        info["saved_json_path"] = json_file
        
        return info
    except Exception as e:
        return {"status": "error", "message": f"Gagal inspeksi PDF: {str(e)}"}


@register_tool(category="pdf")
def pdf_compress_and_optimize(pdf_path: str, output_filename: str = "compressed.pdf") -> Dict[str, Any]:
    """
    Kompresi dan optimalkan ukuran file PDF dengan mereduksi stream konten dan metadata berlebih.
    
    Args:
        pdf_path: Path ke file PDF yang ingin dikompres.
        output_filename: Nama file output hasil kompresi.
    """
    try:
        from pypdf import PdfReader, PdfWriter
        exp_p = os.path.expanduser(pdf_path.strip())
        if not os.path.exists(exp_p):
            return {"status": "error", "message": f"File '{pdf_path}' tidak ditemukan."}
            
        out_dir = get_pdf_output_dir("Compress")
        safe_name = output_filename if output_filename.endswith(".pdf") else f"{output_filename}.pdf"
        target_path = os.path.join(out_dir, safe_name)
        orig_size = os.path.getsize(exp_p)
        
        reader = PdfReader(exp_p)
        writer = PdfWriter()
        for p in reader.pages:
            p.compress_content_streams()
            writer.add_page(p)
            
        with open(target_path, "wb") as f_out:
            writer.write(f_out)
            
        new_size = os.path.getsize(target_path)
        savings_pct = max(0, round((orig_size - new_size) / orig_size * 100, 1)) if orig_size > 0 else 0
        
        return {
            "status": "success",
            "message": f"PDF berhasil dikompresi di Dokumen/ALFA_PDF_TOOLS/Compress/{safe_name}. Hemat {savings_pct}% ruang penyimpanan.",
            "file_path": target_path,
            "filename": safe_name,
            "original_size_kb": round(orig_size / 1024, 2),
            "new_size_kb": round(new_size / 1024, 2),
            "saved_percentage": savings_pct
        }
    except Exception as e:
        return {"status": "error", "message": f"Gagal kompresi PDF: {str(e)}"}


@register_tool(category="media")
def generate_promo_video_from_images(
    image_paths: List[str],
    product_name: str,
    voiceover_text: str,
    orig_price: str = "Rp 149.000",
    disc_price: str = "Rp 49.900",
    voice: str = "id-ID-GadisNeural",
    theme: str = "viral_tiktok",
    motion_style: str = "zoom_in",
    badge_text: str = "🔥 FLASH SALE DISKON SPESIAL",
    call_to_action: str = "👉 KLIK KERANJANG KUNING / BIO SEBELUM HABIS 🛒",
    visual_prompt: str = "",
    output_filename: str = "promo_video.mp4"
) -> Dict[str, Any]:
    """
    Generate video promosi produk otomatis format 9:16 (1080x1920) untuk TikTok / Reels / Shorts hanya dari foto produk.
    Dilengkapi prompt visual sinematik detail, animasi zoompan Ken Burns, dubbing voiceover AI bahasa Indonesia, dan banner flash sale diskon.
    Hasil otomatis tersimpan di ~/Dokumen/ALFA_GENERATED_VIDEOS/.
    
    Args:
        image_paths: Daftar path file foto produk di komputer (bisa 1 atau banyak foto).
        product_name: Nama produk yang dipromosikan.
        voiceover_text: Naskah teks narasi / promosi yang akan dibacakan oleh voiceover AI.
        orig_price: Harga coret sebelum diskon (misal: 'Rp 149.000').
        disc_price: Harga flash sale / drop (misal: 'Rp 49.900').
        voice: Suara voiceover AI ('id-ID-GadisNeural' untuk cewek ramah, 'id-ID-ArdiNeural' untuk cowok).
        theme: Tema visual video ('viral_tiktok', 'luxury_gold', 'cyberpunk', 'clean_minimal').
        motion_style: Gaya animasi kamera ('zoom_in', 'zoom_out', 'pan_left_right').
        badge_text: Teks badge promo atas.
        call_to_action: Teks banner CTA bawah.
        visual_prompt: Deskripsi prompt visual sinematik AI untuk video.
        output_filename: Nama file output MP4.
    """
    try:
        import video_generator
        return video_generator.generate_video_from_images(
            image_paths=image_paths,
            product_name=product_name,
            voiceover_text=voiceover_text,
            orig_price=orig_price,
            disc_price=disc_price,
            voice=voice,
            theme=theme,
            motion_style=motion_style,
            badge_text=badge_text,
            call_to_action=call_to_action,
            visual_prompt=visual_prompt,
            output_filename=output_filename
        )
    except Exception as e:
        logger.error(f"Error in generate_promo_video_from_images: {e}")
        return {"status": "error", "message": str(e)}


@register_tool(category="media")
def extract_audio_from_video(video_path: str, output_filename: str = "extracted_audio.mp3") -> Dict[str, Any]:
    """
    Extract the audio track from a video file (.mp4, .mkv, .webm, .avi) into an MP3 file and send to Telegram.
    
    Args:
        video_path: Path to the local video file.
        output_filename: Output MP3 filename (default: extracted_audio.mp3).
    """
    try:
        expanded = os.path.expanduser(video_path)
        if not os.path.exists(expanded):
            return {"status": "error", "message": f"File video tidak ditemukan: {video_path}"}
            
        if not output_filename.endswith(".mp3"):
            output_filename += ".mp3"
            
        dest_path = os.path.join(SANDBOX_DIR, output_filename)
        cmd = f'ffmpeg -y -i "{expanded}" -vn -acodec libmp3lame -q:a 2 "{dest_path}"'
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
        
        if os.path.exists(dest_path) and os.path.getsize(dest_path) > 0:
            size_mb = round(os.path.getsize(dest_path) / (1024*1024), 2)
            return {
                "status": "success",
                "message": f"Audio berhasil diekstraksi menjadi '{output_filename}' ({size_mb} MB) dan akan dikirim ke Telegram.",
                "file_path": dest_path
            }
        return {"status": "error", "message": f"Gagal mengekstrak audio: {res.stderr[:500]}"}
    except Exception as e:
        return {"status": "error", "message": f"Extract audio error: {str(e)}"}


@register_tool(category="media")
def text_to_audio_file(text: str, filename: str = "audio_speech.mp3", voice: str = "id-ID-GadisNeural") -> Dict[str, Any]:
    """
    Generate a high-fidelity natural speech audio file (.mp3) from any long text or script
    using Microsoft Edge Neural TTS and send it as an audio file directly to Telegram.
    
    Args:
        text: Full text or script to synthesize into audio.
        filename: Target filename (default: audio_speech.mp3).
        voice: Voice code, e.g. 'id-ID-GadisNeural' (female ID), 'id-ID-ArdiNeural' (male ID), 'en-US-JennyNeural' (US English).
    """
    try:
        import asyncio

        import edge_tts
        
        if not filename.endswith(".mp3"):
            filename += ".mp3"
            
        out_path = os.path.join(SANDBOX_DIR, filename)
        
        async def _synth():
            communicate = edge_tts.Communicate(text[:5000], voice)
            await communicate.save(out_path)
            
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    executor.submit(asyncio.run, _synth()).result()
            else:
                loop.run_until_complete(_synth())
        except Exception:
            asyncio.run(_synth())
            
        if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
            size_kb = round(os.path.getsize(out_path) / 1024, 1)
            return {
                "status": "success",
                "message": f"File audio speech '{filename}' ({size_kb} KB) berhasil dibuat dan akan dikirim ke Telegram.",
                "file_path": out_path,
                "voice": voice
            }
        return {"status": "error", "message": "Gagal membuat file audio speech."}
    except Exception as e:
        return {"status": "error", "message": f"Audio synthesis error: {str(e)}"}


@register_tool(category="media")
def convert_media_format(source_file: str, output_format: str = "mp3", extra_params: str = "") -> Dict[str, Any]:
    """
    Convert any video or audio file to another format using ffmpeg (e.g. mp4 -> mp3, mkv -> mp4, wav -> ogg, flac -> mp3).
    The converted file will be automatically sent to Telegram.
    
    Args:
        source_file: Path to source audio/video file.
        output_format: Target format extension (e.g. 'mp3', 'mp4', 'wav', 'ogg', 'flac', 'aac').
        extra_params: Optional ffmpeg flags (e.g. '-q:a 0' or '-vf scale=1280:720').
    """
    try:
        expanded = os.path.expanduser(source_file)
        if not os.path.exists(expanded):
            return {"status": "error", "message": f"File sumber tidak ditemukan: {source_file}"}
            
        base_name = os.path.splitext(os.path.basename(expanded))[0]
        out_format = output_format.lower().replace(".", "")
        out_name = f"{base_name}_converted.{out_format}"
        dest_path = os.path.join(SANDBOX_DIR, out_name)
        
        cmd = f'ffmpeg -y -i "{expanded}" {extra_params} "{dest_path}"'
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
        
        if os.path.exists(dest_path) and os.path.getsize(dest_path) > 0:
            size_mb = round(os.path.getsize(dest_path) / (1024*1024), 2)
            return {
                "status": "success",
                "message": f"Konversi media ke '{out_name}' ({size_mb} MB) berhasil dan akan dikirim ke Telegram.",
                "file_path": dest_path
            }
        return {"status": "error", "message": f"Gagal mengonversi media: {res.stderr[:500]}"}
    except Exception as e:
        return {"status": "error", "message": f"Media conversion error: {str(e)}"}


@register_tool(category="media")
def edit_image(file_path: str, action: str, params: str = "") -> Dict[str, Any]:
    """
    Edit, convert, or transform an image file using Pillow and send the result to Telegram.
    
    Args:
        file_path: Path to the source image file.
        action: Edit action to perform. Options:
                - 'resize': Resize image (params: 'WIDTHxHEIGHT', e.g. '800x600')
                - 'crop': Crop image (params: 'LEFT,TOP,RIGHT,BOTTOM', e.g. '100,100,500,400')
                - 'rotate': Rotate image (params: degrees, e.g. '90', '180', '270')
                - 'grayscale': Convert to black & white
                - 'flip_horizontal': Flip horizontally
                - 'flip_vertical': Flip vertically
                - 'convert': Convert format (params: target format, e.g. 'PNG', 'JPEG', 'WEBP')
                - 'watermark': Add text watermark (params: watermark text)
                - 'thumbnail': Create thumbnail (params: 'WIDTHxHEIGHT', e.g. '200x200')
                - 'blur': Apply blur effect
                - 'sharpen': Sharpen image
                - 'info': Get image metadata (dimensions, format, size)
        params: Parameters for the action (depends on action type).
    """
    try:
        from PIL import Image, ImageDraw, ImageFilter, ImageFont
        
        expanded = os.path.expanduser(file_path)
        if not os.path.exists(expanded):
            return {"status": "error", "message": f"File gambar tidak ditemukan: {file_path}"}
        
        img = Image.open(expanded)
        base_name = os.path.splitext(os.path.basename(expanded))[0]
        act = action.strip().lower()
        
        if act == "info":
            return {
                "status": "success",
                "format": img.format,
                "size": f"{img.width}x{img.height}",
                "mode": img.mode,
                "file_size_kb": round(os.path.getsize(expanded) / 1024, 1)
            }
        elif act == "resize":
            w, h = [int(x) for x in params.lower().split("x")]
            img = img.resize((w, h), Image.LANCZOS)
        elif act == "crop":
            coords = [int(x.strip()) for x in params.split(",")]
            img = img.crop(tuple(coords))
        elif act == "rotate":
            degrees = int(params)
            img = img.rotate(degrees, expand=True)
        elif act == "grayscale":
            img = img.convert("L")
        elif act == "flip_horizontal":
            img = img.transpose(Image.FLIP_LEFT_RIGHT)
        elif act == "flip_vertical":
            img = img.transpose(Image.FLIP_TOP_BOTTOM)
        elif act == "convert":
            pass  # handled below by save format
        elif act == "watermark":
            draw = ImageDraw.Draw(img)
            text = params or "AI Agent Watermark"
            try:
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 24)
            except Exception:
                font = ImageFont.load_default()
            bbox = draw.textbbox((0, 0), text, font=font)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            x = img.width - tw - 20
            y = img.height - th - 20
            draw.text((x, y), text, fill=(255, 255, 255, 180), font=font)
        elif act == "thumbnail":
            w, h = [int(x) for x in params.lower().split("x")]
            img.thumbnail((w, h), Image.LANCZOS)
        elif act == "blur":
            img = img.filter(ImageFilter.GaussianBlur(radius=5))
        elif act == "sharpen":
            img = img.filter(ImageFilter.SHARPEN)
        else:
            return {"status": "error", "message": f"Aksi '{action}' tidak dikenal."}
        
        if act == "convert":
            fmt = params.strip().upper()
            ext = fmt.lower()
            if fmt == "JPEG":
                ext = "jpg"
                img = img.convert("RGB")
        else:
            fmt = img.format or "PNG"
            ext = fmt.lower()
            if ext == "jpeg":
                ext = "jpg"
        
        if act != "convert" and img.mode == "RGBA" and fmt == "JPEG":
            img = img.convert("RGB")
            
        out_name = f"{base_name}_edited.{ext}"
        out_path = os.path.join(SANDBOX_DIR, out_name)
        img.save(out_path, format=fmt if act == "convert" else None)
        
        return {
            "status": "success",
            "message": f"Gambar berhasil di-{act} dan disimpan sebagai '{out_name}'. Akan dikirim ke Telegram.",
            "file_path": out_path
        }
    except Exception as e:
        return {"status": "error", "message": f"Gagal mengedit gambar: {str(e)}"}


@register_tool(category="office")
def generate_excel_spreadsheet(sheet_title: str, headers: List[str], rows_json: str, filename: str = "data.xlsx") -> Dict[str, Any]:
    """
    Generate an Excel (.xlsx) spreadsheet with styled headers, borders, and auto-adjusted columns, automatically sent to Telegram.
    
    Args:
        sheet_title: Name of the worksheet tab.
        headers: List of column header names (e.g. ['Nama', 'Kategori', 'Harga', 'Jumlah']).
        rows_json: JSON string of 2D array of rows (e.g. '[["Barang A", "Kategori 1", 15000], ["Barang B", "Kategori 2", 25000]]').
        filename: Output filename ending in .xlsx.
    """
    try:
        import json

        import openpyxl
        from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
        from openpyxl.utils import get_column_letter
        
        safe_name = filename if filename.endswith(".xlsx") else f"{filename}.xlsx"
        target_path = os.path.join(SANDBOX_DIR, safe_name)
        
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = sheet_title[:30]
        
        header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        header_fill = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid")
        thin_border = Border(
            left=Side(style='thin', color='CBD5E1'),
            right=Side(style='thin', color='CBD5E1'),
            top=Side(style='thin', color='CBD5E1'),
            bottom=Side(style='thin', color='CBD5E1')
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
            max_len = max(len(str(cell.value or '')) for cell in col)
            col_letter = get_column_letter(col[0].column)
            ws.column_dimensions[col_letter].width = max(max_len + 4, 12)
            
        wb.save(target_path)
        return {
            "status": "success",
            "message": f"Spreadsheet Excel '{safe_name}' berhasil dibuat dan akan dikirim ke Telegram.",
            "file_path": target_path
        }
    except Exception as e:
        return {"status": "error", "message": f"Gagal membuat Excel: {str(e)}"}


@register_tool(category="office")
def generate_presentation_pptx(title: str, subtitle: str, slides_json: str, filename: str = "presentasi.pptx") -> Dict[str, Any]:
    """
    Generate a clean PowerPoint presentation (.pptx) and send it directly to Telegram.
    
    Args:
        title: Main presentation title.
        subtitle: Subtitle / author note.
        slides_json: JSON string list of slide objects, e.g. '[{"title": "Slide 1", "points": ["Poin A", "Poin B"]}]'.
        filename: Output filename ending in .pptx.
    """
    try:
        import json

        from pptx import Presentation
        
        # Accept either a JSON string or an already-parsed list
        slides_content = json.loads(slides_json) if isinstance(slides_json, str) else slides_json
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
            "file_path": target_path
        }
    except Exception as e:
        return {"status": "error", "message": f"Gagal membuat PPTX: {str(e)}"}


@register_tool(category="media")
def analyze_dataset_csv_json(file_path: str, chart_type: str = "bar", x_column: str = "", y_column: str = "", title: str = "Data Analysis") -> Dict[str, Any]:
    """
    GOD MODE: Intelligent Dataset Analyzer & Visualizer.
    Reads and parses a CSV, JSON, or Excel dataset, computes statistical metrics
    (summary stats, row counts, missing values, column data types), and generates
    a professional visualization chart automatically sent to Telegram.
    
    Args:
        file_path: Path to dataset file (.csv or .json).
        chart_type: 'bar', 'line', 'scatter', 'pie', 'hist'.
        x_column: Name of X-axis column (defaults to first column).
        y_column: Name of Y-axis numeric column (defaults to second column).
        title: Chart title.
    """
    try:
        import csv
        import json

        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        
        expanded = os.path.expanduser(file_path)
        if not os.path.exists(expanded):
            return {"status": "error", "message": f"File dataset tidak ditemukan: {file_path}"}
            
        data_rows = []
        headers = []
        
        ext = os.path.splitext(expanded)[1].lower()
        if ext == ".csv":
            with open(expanded, "r", encoding="utf-8", errors="replace") as f:
                reader = csv.DictReader(f)
                headers = reader.fieldnames or []
                data_rows = list(reader)
        elif ext == ".json":
            with open(expanded, "r", encoding="utf-8") as f:
                raw_json = json.load(f)
                if isinstance(raw_json, list) and raw_json:
                    data_rows = raw_json
                    headers = list(raw_json[0].keys()) if isinstance(raw_json[0], dict) else []
                elif isinstance(raw_json, dict):
                    data_rows = [raw_json]
                    headers = list(raw_json.keys())
        else:
            return {"status": "error", "message": "Format dataset harus .csv atau .json"}
            
        if not data_rows:
            return {"status": "error", "message": "Dataset kosong atau tidak memiliki baris data."}
            
        # Statistical summary
        total_rows = len(data_rows)
        sample_data = data_rows[:5]
        
        # Plotting
        chart_path = os.path.join(SANDBOX_DIR, "dataset_analysis_chart.png")
        plt.figure(figsize=(10, 6), dpi=120)
        plt.style.use('seaborn-v0_8-darkgrid' if 'seaborn-v0_8-darkgrid' in plt.style.available else 'default')
        
        x_col = x_column or (headers[0] if headers else "")
        y_col = y_column or (headers[1] if len(headers) > 1 else headers[0] if headers else "")
        
        x_vals = [str(r.get(x_col, "")) for r in data_rows[:20]]
        y_vals = []
        for r in data_rows[:20]:
            try:
                y_vals.append(float(r.get(y_col, 0)))
            except (ValueError, TypeError):
                y_vals.append(0.0)
                
        if chart_type == "line":
            plt.plot(x_vals, y_vals, marker='o', color='#2563EB', linewidth=2.5)
        elif chart_type == "scatter":
            plt.scatter(x_vals, y_vals, color='#7C3AED', s=80)
        elif chart_type == "pie" and len(x_vals) <= 10:
            plt.pie(y_vals, labels=x_vals, autopct='%1.1f%%', colors=plt.cm.Paired.colors)
        else:  # default bar
            plt.bar(x_vals, y_vals, color='#3B82F6', edgecolor='#1D4ED8')
            
        plt.title(title, fontsize=14, fontweight='bold', pad=15)
        if chart_type != "pie":
            plt.xlabel(x_col, fontsize=11)
            plt.ylabel(y_col, fontsize=11)
            plt.xticks(rotation=45, ha='right')
        plt.tight_layout()
        plt.savefig(chart_path, dpi=150)
        plt.close()
        
        return {
            "status": "success",
            "total_rows": total_rows,
            "columns": headers,
            "sample_rows": sample_data,
            "chart_generated": "dataset_analysis_chart.png",
            "message": f"Analisis dataset '{os.path.basename(expanded)}' selesai. Grafik '{chart_type}' berhasil dibuat dan akan dikirim ke Telegram."
        }
    except Exception as e:
        return {"status": "error", "message": f"Dataset analysis error: {str(e)}"}


@register_tool(category="media")
def translate_text(text: str, target_lang: str = "en", source_lang: str = "auto") -> Dict[str, Any]:
    """
    Translate text between languages using Google Translate.
    
    Args:
        text: Text to translate.
        target_lang: Target language code (e.g. 'en' English, 'id' Indonesian, 'ja' Japanese, 'ko' Korean, 'zh-CN' Chinese, 'ar' Arabic, 'fr' French, 'de' German, 'es' Spanish).
        source_lang: Source language code (default: 'auto' for auto-detect).
    """
    try:
        from deep_translator import GoogleTranslator
        
        translated = GoogleTranslator(source=source_lang, target=target_lang).translate(text[:4500])
        return {
            "status": "success",
            "original": text[:500],
            "translated": translated,
            "source_language": source_lang,
            "target_language": target_lang
        }
    except Exception as e:
        return {"status": "error", "message": f"Gagal menerjemahkan: {str(e)}"}

