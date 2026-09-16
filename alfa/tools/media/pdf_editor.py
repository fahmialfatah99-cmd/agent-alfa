# -*- coding: utf-8 -*-
"""
PDF Editor: merge, split, extract text, encrypt, decrypt, rotate, inspect, and compress.
"""

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from alfa.tools.media.pdf_builder import get_pdf_output_dir
from alfa.tools.registry import register_tool

logger = logging.getLogger("AgentTools.Media.PDFEditor")


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
    except Exception:
        try:
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
def pdf_inspect_metadata(pdf_path: str) -> Dict[str, Any]:
    """
    Periksa informasi teknis mendalam dari file PDF (jumlah halaman, versi PDF, ukuran file, enkripsi, metadata) dan simpan salinan JSON.
    
    Args:
        pdf_path: Path ke file PDF yang ingin diinspeksi.
    """
    try:
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
