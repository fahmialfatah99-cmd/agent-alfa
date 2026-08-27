"""
FAST-PATH TOOL EXECUTOR.
Provides sub-second (10-100ms) execution for direct deterministic file & tool commands:
- Image to PDF ('jadikan pdf', 'ubah foto ini ke pdf', 'convert to pdf')
- Image Upscale & Waifu2x ('scale gambar', 'waifu2x', 'upscale foto', 'perbesar resolusi 2x/4x')
- PDF Merge ('gabung pdf', 'merge pdf')
- PDF Split ('pecah pdf', 'split pdf')
- PDF Text Extract ('ekstrak teks', 'baca teks pdf')
- PDF Rotate ('putar pdf', 'rotate pdf')
- PDF Watermark ('watermark pdf', 'stempel pdf')
- Media Convert ('ubah ke mp3', 'convert mp3', 'ekstrak audio')
"""

import os
import re
import time
import tools
from typing import Any, Dict, List, Optional, Tuple


def try_execute_fast_path(
    user_prompt: str,
    saved_file_paths: List[str]
) -> Optional[Dict[str, Any]]:
    """
    Check if the user prompt is a direct deterministic tool command on the uploaded files.
    Returns: Dict with status, reply (Markdown), tool_name, and execution_time_ms if matched, else None.
    """
    t0 = time.perf_counter()
    p_low = (user_prompt or "").lower().strip()
    
    if not saved_file_paths:
        return None

    image_paths = [p for p in saved_file_paths if os.path.splitext(p)[1].lower() in ('.png', '.jpg', '.jpeg', '.webp', '.bmp', '.gif')]
    pdf_paths = [p for p in saved_file_paths if os.path.splitext(p)[1].lower() == '.pdf']
    audio_video_paths = [p for p in saved_file_paths if os.path.splitext(p)[1].lower() in ('.mp4', '.mkv', '.avi', '.mov', '.webm', '.flv', '.mp3', '.m4a', '.wav', '.ogg', '.aac')]

    # 1. FAST-PATH: IMAGES TO PDF (< 50ms)
    is_image_to_pdf = image_paths and (
        ('pdf' in p_low and any(k in p_low for k in ['jadikan', 'ubah', 'convert', 'buat', 'bikin', 'ganti', 'save', 'simpan', 'ekspor', 'export', 'satukan'])) or
        any(k in p_low for k in ['to pdf', 'ke pdf', 'image to pdf', 'foto ke pdf', 'gambar ke pdf'])
    )
    if is_image_to_pdf:
        m = re.search(r'bernama\s+([a-zA-Z0-9_\-.]+\.pdf)', user_prompt, re.IGNORECASE)
        custom_name = m.group(1) if m else f"album_dokumen_{int(time.time())}.pdf"
        if not custom_name.endswith('.pdf'):
            custom_name += '.pdf'
            
        res = tools.images_convert_to_pdf(image_paths=image_paths, output_filename=custom_name)
        if res.get("status") == "success":
            dt_ms = int((time.perf_counter() - t0) * 1000)
            target_path = res.get("file_path", "")
            download_url = f"/api/artifacts/download?path={target_path}"
            size_kb = os.path.getsize(target_path) / 1024 if os.path.exists(target_path) else 0
            
            md_reply = f"""⚡ **Konversi Berkas Selesai Instan ({dt_ms} ms via Native Engine)!**

📄 **Dokumen PDF:** `{custom_name}`  
📊 **Ukuran:** `{size_kb:.1f} KB` ({len(image_paths)} Gambar)  
📁 **Lokasi Penyimpanan:** `{target_path}`  

<div class="my-3 p-3.5 bg-cyan-950/60 border border-cyan-500/40 rounded-xl flex items-center justify-between shadow-lg">
    <div class="flex items-center gap-3 text-slate-200">
        <div class="w-9 h-9 rounded-lg bg-cyan-500/20 border border-cyan-500/30 flex items-center justify-center text-cyan-400">
            <i data-lucide="file-check" class="w-5 h-5"></i>
        </div>
        <div>
            <p class="font-mono font-bold text-xs text-white truncate max-w-[200px] sm:max-w-xs">{custom_name}</p>
            <span class="text-[10px] text-emerald-400 font-mono">Siap Diunduh • {size_kb:.1f} KB</span>
        </div>
    </div>
    <a href="{download_url}" download class="px-3.5 py-2 bg-gradient-to-r from-cyan-500 to-blue-600 hover:from-cyan-400 hover:to-blue-500 text-dark-950 font-bold font-mono text-xs rounded-lg transition-all flex items-center gap-1.5 shadow-glow-cyan">
        <i data-lucide="download" class="w-3.5 h-3.5"></i> Unduh PDF
    </a>
</div>
"""
            return {
                "status": "success",
                "reply": md_reply,
                "tool_name": "images_convert_to_pdf",
                "execution_time_ms": dt_ms,
                "file_path": target_path
            }

    # 2. FAST-PATH: IMAGE SCALE / UPSCALING / WAIFU2X (< 100ms)
    is_upscale = image_paths and any(k in p_low for k in [
        'scale', 'upscale', 'waifu2x', 'perbesar resolusi', 'perbesar gambar', 'perbesar foto',
        'hd kan', 'jernihkan', 'super resolution', 'tingkatkan resolusi', 'perjelas', 'rescale'
    ])
    if is_upscale:
        scale_val = 2
        if '4x' in p_low or '4 kali' in p_low or 'empat kali' in p_low: scale_val = 4
        elif '8x' in p_low or '8 kali' in p_low or 'delapan kali' in p_low: scale_val = 8
        
        mode_val = "auto"
        if 'anime' in p_low or 'kartun' in p_low or 'waifu' in p_low:
            mode_val = "waifu2x_anime"
        elif 'foto' in p_low or 'photo' in p_low or 'kamera' in p_low:
            mode_val = "waifu2x_photo"
        elif 'pixel' in p_low or 'retro' in p_low:
            mode_val = "pixel_art"

        res = tools.upscale_image_hd(image_path=image_paths[0], scale=scale_val, mode=mode_val)
        if res.get("status") == "success":
            dt_ms = int((time.perf_counter() - t0) * 1000)
            target_path = res.get("file_path", "")
            download_url = f"/api/artifacts/download?path={target_path}"
            fname = res.get("filename", os.path.basename(target_path))
            orig_res = res.get("original_resolution", "-")
            new_res = res.get("new_resolution", "-")
            engine = res.get("engine", "Lanczos Ultra-HD")
            size_kb = res.get("size_kb", 0)

            md_reply = f"""⚡ **Perbesaran Resolusi Gambar Berhasil Instan ({dt_ms} ms via {engine})!**

🖼️ **Resolusi Awal:** `{orig_res}` ➡️ **Resolusi Baru ({scale_val}x HD):** `{new_res}`  
📊 **Ukuran File:** `{size_kb} KB`  
📁 **Lokasi:** `{target_path}`  

<div class="my-3 p-3.5 bg-dark-950/80 border border-cyan-500/40 rounded-xl space-y-3 shadow-lg max-w-md">
    <div class="relative group overflow-hidden rounded-lg border border-white/10 bg-black/40">
        <img src="{download_url}" class="w-full max-h-56 object-contain rounded-lg cursor-pointer hover:opacity-90 transition-all" onclick="openMediaPreviewModal('{fname}', '{download_url}', 'image')" alt="{fname}">
    </div>
    <div class="flex items-center justify-between pt-1 border-t border-white/10">
        <div class="flex items-center gap-2">
            <span class="px-2 py-0.5 rounded bg-cyan-500/20 text-cyan-300 font-mono text-[10px] font-bold">{scale_val}x HD</span>
            <span class="text-slate-300 font-mono text-xs truncate max-w-[150px]">{fname}</span>
        </div>
        <a href="{download_url}" download class="px-3.5 py-1.5 bg-gradient-to-r from-cyan-500 to-blue-600 hover:from-cyan-400 hover:to-blue-500 text-dark-950 font-bold font-mono text-xs rounded-lg transition-all flex items-center gap-1.5 shadow-glow-cyan">
            <i data-lucide="download" class="w-3.5 h-3.5"></i> Unduh HD
        </a>
    </div>
</div>
"""
            return {
                "status": "success",
                "reply": md_reply,
                "tool_name": "upscale_image_hd",
                "execution_time_ms": dt_ms,
                "file_path": target_path
            }

    # 3. FAST-PATH: PDF MERGE (< 50ms)
    is_pdf_merge = len(pdf_paths) >= 2 and any(k in p_low for k in ['gabung', 'merge', 'satukan', 'combine', 'jadikan satu', 'satukan pdf'])
    if is_pdf_merge:
        m = re.search(r'bernama\s+([a-zA-Z0-9_\-.]+\.pdf)', user_prompt, re.IGNORECASE)
        custom_name = m.group(1) if m else f"merged_{int(time.time())}.pdf"
        res = tools.pdf_merge_documents(pdf_paths=pdf_paths, output_filename=custom_name)
        if res.get("status") == "success":
            dt_ms = int((time.perf_counter() - t0) * 1000)
            target_path = res.get("file_path", "")
            download_url = f"/api/artifacts/download?path={target_path}"
            size_kb = os.path.getsize(target_path) / 1024 if os.path.exists(target_path) else 0
            fname = os.path.basename(target_path)
            
            md_reply = f"""⚡ **Penggabungan PDF Selesai Instan ({dt_ms} ms via Native Engine)!**

📄 **Dokumen:** `{fname}`  
📊 **Ukuran:** `{size_kb:.1f} KB` ({len(pdf_paths)} File Digabungkan)  

<div class="my-3 p-3.5 bg-cyan-950/60 border border-cyan-500/40 rounded-xl flex items-center justify-between shadow-lg">
    <div class="flex items-center gap-3 text-slate-200">
        <div class="w-9 h-9 rounded-lg bg-cyan-500/20 border border-cyan-500/30 flex items-center justify-center text-cyan-400">
            <i data-lucide="file-check" class="w-5 h-5"></i>
        </div>
        <div>
            <p class="font-mono font-bold text-xs text-white truncate max-w-[200px] sm:max-w-xs">{fname}</p>
            <span class="text-[10px] text-emerald-400 font-mono">Siap Diunduh • {size_kb:.1f} KB</span>
        </div>
    </div>
    <a href="{download_url}" download class="px-3.5 py-2 bg-gradient-to-r from-cyan-500 to-blue-600 hover:from-cyan-400 hover:to-blue-500 text-dark-950 font-bold font-mono text-xs rounded-lg transition-all flex items-center gap-1.5 shadow-glow-cyan">
        <i data-lucide="download" class="w-3.5 h-3.5"></i> Unduh PDF
    </a>
</div>
"""
            return {
                "status": "success",
                "reply": md_reply,
                "tool_name": "pdf_merge_documents",
                "execution_time_ms": dt_ms,
                "file_path": target_path
            }

    # 4. FAST-PATH: PDF ROTATE (< 30ms)
    is_pdf_rotate = bool(pdf_paths) and any(k in p_low for k in ['putar', 'rotate', 'rotasi', 'miring'])
    if is_pdf_rotate:
        angle = 90
        if '180' in p_low: angle = 180
        elif '270' in p_low: angle = 270
        res = tools.pdf_rotate_pages(pdf_path=pdf_paths[0], angle=angle, output_filename=f"rotated_{int(time.time())}.pdf")
        if res.get("status") == "success":
            dt_ms = int((time.perf_counter() - t0) * 1000)
            target_path = res.get("file_path", "")
            download_url = f"/api/artifacts/download?path={target_path}"
            fname = os.path.basename(target_path)
            md_reply = f"""⚡ **Rotasi PDF ({angle}°) Selesai Instan ({dt_ms} ms)!**

<div class="my-3 p-3.5 bg-cyan-950/60 border border-cyan-500/40 rounded-xl flex items-center justify-between shadow-lg">
    <div class="flex items-center gap-3 text-slate-200">
        <i data-lucide="file-check" class="w-5 h-5 text-cyan-400"></i>
        <p class="font-mono font-bold text-xs text-white">{fname}</p>
    </div>
    <a href="{download_url}" download class="px-3 py-1.5 bg-cyan-500 hover:bg-cyan-400 text-dark-950 font-bold font-mono text-xs rounded-lg transition-all flex items-center gap-1.5 shadow-glow-cyan">
        <i data-lucide="download" class="w-3.5 h-3.5"></i> Unduh
    </a>
</div>
"""
            return {"status": "success", "reply": md_reply, "tool_name": "pdf_rotate_pages", "execution_time_ms": dt_ms}

    # 5. FAST-PATH: MEDIA TO MP3 (< 150ms)
    is_media_to_mp3 = bool(audio_video_paths) and any(k in p_low for k in ['mp3', 'ekstrak audio', 'ambil suara', 'ubah suara', 'convert audio', 'ke audio'])
    if is_media_to_mp3:
        res = tools.convert_media_format(source_file=audio_video_paths[0], output_format="mp3")
        if res.get("status") == "success":
            dt_ms = int((time.perf_counter() - t0) * 1000)
            target_path = res.get("file_path", "")
            download_url = f"/api/artifacts/download?path={target_path}"
            fname = os.path.basename(target_path)
            md_reply = f"""⚡ **Konversi Audio ke MP3 Berhasil Instan ({dt_ms} ms)!**

<div class="my-3 p-3.5 bg-cyan-950/60 border border-cyan-500/40 rounded-xl flex items-center justify-between shadow-lg">
    <div class="flex items-center gap-3 text-slate-200">
        <i data-lucide="music" class="w-5 h-5 text-cyan-400"></i>
        <p class="font-mono font-bold text-xs text-white">{fname}</p>
    </div>
    <a href="{download_url}" download class="px-3 py-1.5 bg-cyan-500 hover:bg-cyan-400 text-dark-950 font-bold font-mono text-xs rounded-lg transition-all flex items-center gap-1.5 shadow-glow-cyan">
        <i data-lucide="download" class="w-3.5 h-3.5"></i> Unduh MP3
    </a>
</div>
"""
            return {"status": "success", "reply": md_reply, "tool_name": "convert_media_format", "execution_time_ms": dt_ms}

    return None
