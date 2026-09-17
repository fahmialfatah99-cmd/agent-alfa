# -*- coding: utf-8 -*-
"""
Audio, Video, TTS, Upscaling, and Image manipulation tools for ALFA.
"""

import asyncio
import concurrent.futures
import logging
import os
import subprocess
from typing import Any, Dict, List, Optional

from alfa.tools.registry import register_tool
from alfa.tools.system_tools import SANDBOX_DIR

logger = logging.getLogger("AgentTools.Media.AV")


@register_tool(category="media")
def upscale_image_hd(
    image_path: str,
    scale: int = 2,
    mode: str = "auto",
    denoise: int = 1,
    output_filename: str = "",
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
        from PIL import Image, ImageFilter

        exp_p = os.path.expanduser(image_path.strip())
        if not os.path.exists(exp_p):
            return {
                "status": "error",
                "message": f"File gambar tidak ditemukan di '{image_path}'.",
            }

        out_dir = os.path.expanduser("~/Dokumen/ALFA_PDF_TOOLS/Image_Upscaling")
        os.makedirs(out_dir, exist_ok=True)

        base_name = os.path.splitext(os.path.basename(exp_p))[0]
        ext = os.path.splitext(exp_p)[1].lower() or ".png"
        if ext not in (".png", ".jpg", ".jpeg", ".webp"):
            ext = ".png"

        scale_factor = int(scale) if scale in (2, 4, 8) else 2
        safe_name = (
            output_filename
            if output_filename
            else f"{base_name}_upscaled_{scale_factor}x{ext}"
        )
        if not safe_name.endswith(ext):
            safe_name += ext
        target_path = os.path.join(out_dir, safe_name)

        used_engine = "Lanczos Ultra-HD"

        waifu_bin = "/home/fahmial/telegram-ai-bot/bin/waifu2x/waifu2x-ncnn-vulkan-20250915-linux/waifu2x-ncnn-vulkan"
        model_dir = "/home/fahmial/telegram-ai-bot/bin/waifu2x/waifu2x-ncnn-vulkan-20250915-linux"

        if mode in ("waifu2x_anime", "waifu2x_photo", "auto") and os.path.exists(
            waifu_bin
        ):
            selected_model = "models-cunet"
            if mode == "waifu2x_anime":
                selected_model = "models-upconv_7_anime_style_art_rgb"
            elif mode == "waifu2x_photo":
                selected_model = "models-upconv_7_photo"

            cmd = [
                waifu_bin,
                "-i",
                exp_p,
                "-o",
                target_path,
                "-s",
                str(scale_factor),
                "-n",
                str(max(0, min(3, int(denoise)))),
                "-m",
                os.path.join(model_dir, selected_model),
            ]
            try:
                sub_res = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=15
                )
                if sub_res.returncode == 0 and os.path.exists(target_path):
                    used_engine = f"Waifu2x AI ({selected_model})"
            except Exception:
                pass

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
                    upscaled = upscaled.filter(
                        ImageFilter.UnsharpMask(radius=2, percent=140, threshold=3)
                    )
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
            "size_kb": round(size_kb, 1),
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Gagal memperbesar resolusi gambar: {str(e)}",
        }


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
    output_filename: str = "promo_video.mp4",
) -> Dict[str, Any]:
    """
    Generate video promosi produk otomatis format 9:16 (1080x1920) untuk TikTok / Reels / Shorts hanya dari foto produk.
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
            output_filename=output_filename,
        )
    except Exception as e:
        logger.error(f"Error in generate_promo_video_from_images: {e}")
        return {"status": "error", "message": str(e)}


@register_tool(category="media")
def extract_audio_from_video(
    video_path: str, output_filename: str = "extracted_audio.mp3"
) -> Dict[str, Any]:
    """
    Extract the audio track from a video file (.mp4, .mkv, .webm, .avi) into an MP3 file and send to Telegram.
    """
    try:
        expanded = os.path.expanduser(video_path)
        if not os.path.exists(expanded):
            return {
                "status": "error",
                "message": f"File video tidak ditemukan: {video_path}",
            }

        if not output_filename.endswith(".mp3"):
            output_filename += ".mp3"

        dest_path = os.path.join(SANDBOX_DIR, output_filename)
        cmd = f'ffmpeg -y -i "{expanded}" -vn -acodec libmp3lame -q:a 2 "{dest_path}"'
        res = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=60
        )

        if os.path.exists(dest_path) and os.path.getsize(dest_path) > 0:
            size_mb = round(os.path.getsize(dest_path) / (1024 * 1024), 2)
            return {
                "status": "success",
                "message": f"Audio berhasil diekstraksi menjadi '{output_filename}' ({size_mb} MB) dan akan dikirim ke Telegram.",
                "file_path": dest_path,
            }
        return {
            "status": "error",
            "message": f"Gagal mengekstrak audio: {res.stderr[:500]}",
        }
    except Exception as e:
        return {"status": "error", "message": f"Extract audio error: {str(e)}"}


@register_tool(category="media")
def text_to_audio_file(
    text: str, filename: str = "audio_speech.mp3", voice: str = "id-ID-GadisNeural"
) -> Dict[str, Any]:
    """
    Generate a high-fidelity natural speech audio file (.mp3) from any long text or script
    using Microsoft Edge Neural TTS and send it as an audio file directly to Telegram.
    """
    try:
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
                "voice": voice,
            }
        return {"status": "error", "message": "Gagal membuat file audio speech."}
    except Exception as e:
        return {"status": "error", "message": f"Audio synthesis error: {str(e)}"}


@register_tool(category="media")
def convert_media_format(
    source_file: str, output_format: str = "mp3", extra_params: str = ""
) -> Dict[str, Any]:
    """
    Convert any video or audio file to another format using ffmpeg.
    """
    try:
        expanded = os.path.expanduser(source_file)
        if not os.path.exists(expanded):
            return {
                "status": "error",
                "message": f"File sumber tidak ditemukan: {source_file}",
            }

        base_name = os.path.splitext(os.path.basename(expanded))[0]
        out_format = output_format.lower().replace(".", "")
        out_name = f"{base_name}_converted.{out_format}"
        dest_path = os.path.join(SANDBOX_DIR, out_name)

        cmd = f'ffmpeg -y -i "{expanded}" {extra_params} "{dest_path}"'
        res = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=60
        )

        if os.path.exists(dest_path) and os.path.getsize(dest_path) > 0:
            size_mb = round(os.path.getsize(dest_path) / (1024 * 1024), 2)
            return {
                "status": "success",
                "message": f"Konversi media ke '{out_name}' ({size_mb} MB) berhasil dan akan dikirim ke Telegram.",
                "file_path": dest_path,
            }
        return {
            "status": "error",
            "message": f"Gagal mengonversi media: {res.stderr[:500]}",
        }
    except Exception as e:
        return {"status": "error", "message": f"Media conversion error: {str(e)}"}


@register_tool(category="media")
def edit_image(file_path: str, action: str, params: str = "") -> Dict[str, Any]:
    """
    Edit, convert, or transform an image file using Pillow and send the result to Telegram.
    """
    try:
        from PIL import Image, ImageDraw, ImageFilter, ImageFont

        expanded = os.path.expanduser(file_path)
        if not os.path.exists(expanded):
            return {
                "status": "error",
                "message": f"File gambar tidak ditemukan: {file_path}",
            }

        img = Image.open(expanded)
        base_name = os.path.splitext(os.path.basename(expanded))[0]
        act = action.strip().lower()

        if act == "info":
            return {
                "status": "success",
                "format": img.format,
                "size": f"{img.width}x{img.height}",
                "mode": img.mode,
                "file_size_kb": round(os.path.getsize(expanded) / 1024, 1),
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
            pass
        elif act == "watermark":
            draw = ImageDraw.Draw(img)
            text = params or "AI Agent Watermark"
            try:
                font = ImageFont.truetype(
                    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 24
                )
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
            "file_path": out_path,
        }
    except Exception as e:
        return {"status": "error", "message": f"Gagal mengedit gambar: {str(e)}"}
