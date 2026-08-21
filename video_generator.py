"""
╔══════════════════════════════════════════════════════════════════════════════╗
║             ALFA AUTOMATED IMAGE-TO-VIDEO PROMO GENERATOR ENGINE             ║
║   Converts Product Images into 9:16 Vertical TikTok/Reels Videos with Audio  ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import os
import re
import time
import shutil
import asyncio
import logging
import subprocess
from datetime import datetime
from typing import Dict, Any, List, Optional
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance

logger = logging.getLogger("alfa.video_gen")

VIDEO_OUT_DIR = os.path.expanduser("~/Dokumen/ALFA_GENERATED_VIDEOS")
os.makedirs(VIDEO_OUT_DIR, exist_ok=True)
os.makedirs(os.path.join(VIDEO_OUT_DIR, "Frames"), exist_ok=True)
os.makedirs(os.path.join(VIDEO_OUT_DIR, "Audio"), exist_ok=True)


def get_audio_duration(audio_path: str) -> float:
    """Get exact duration of audio file in seconds using ffprobe."""
    try:
        cmd = [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", audio_path
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        return max(3.0, float(res.stdout.strip()))
    except Exception as e:
        logger.warning(f"Failed to get audio duration via ffprobe: {e}")
        return 10.0


def generate_voiceover(text: str, voice: str = "id-ID-GadisNeural") -> str:
    """Generate natural Indonesian voiceover from text."""
    safe_stem = f"voice_{int(time.time() * 1000)}"
    audio_path = os.path.join(VIDEO_OUT_DIR, "Audio", f"{safe_stem}.mp3")
    
    edge_tts_bin = os.path.join(os.path.dirname(os.path.abspath(__file__)), "venv", "bin", "edge-tts")
    if not os.path.exists(edge_tts_bin):
        edge_tts_bin = shutil.which("edge-tts") or "edge-tts"
        
    cmd = [edge_tts_bin, "--voice", voice, "--text", text, "--write-media", audio_path]
    subprocess.run(cmd, check=True)
    return audio_path


def create_aesthetic_frame(
    image_path: str,
    product_name: str,
    orig_price: str,
    disc_price: str,
    rating: str = "4.9",
    badge_text: str = "🔥 FLASH SALE DISKON SPESIAL",
    call_to_action: str = "👉 KLIK KERANJANG KUNING / BIO SEBELUM HABIS 🛒",
    output_path: Optional[str] = None
) -> str:
    """
    Generate a high-converting 1080x1920 9:16 vertical video frame.
    Composites blurred aesthetic ambient background + centered product + luxury overlays.
    """
    WIDTH, HEIGHT = 1080, 1920
    
    # Base background: Dark luxury gradient
    bg = Image.new("RGBA", (WIDTH, HEIGHT), (10, 15, 29, 255))
    
    # Load and process product image
    try:
        prod_img = Image.open(image_path).convert("RGBA")
    except Exception:
        prod_img = Image.new("RGBA", (800, 800), (30, 41, 59, 255))

    # 1. Ambient Blurred Glow in Background
    blur_bg = prod_img.resize((WIDTH, HEIGHT), Image.Resampling.LANCZOS)
    blur_bg = blur_bg.filter(ImageFilter.GaussianBlur(radius=45))
    enhancer = ImageEnhance.Brightness(blur_bg)
    blur_bg = enhancer.enhance(0.35)
    bg.paste(blur_bg, (0, 0))

    # 2. Main Product Image (Centered in golden ratio box)
    prod_w = 880
    aspect = prod_img.height / prod_img.width
    prod_h = int(prod_w * aspect)
    if prod_h > 1000:
        prod_h = 1000
        prod_w = int(prod_h / aspect)
        
    prod_resized = prod_img.resize((prod_w, prod_h), Image.Resampling.LANCZOS)
    
    # Add rounded corners & shadow container for product
    prod_box_x = (WIDTH - prod_w) // 2
    prod_box_y = 380 + (1000 - prod_h) // 2
    
    # Card glow border
    draw = ImageDraw.Draw(bg)
    border_rect = [prod_box_x - 12, prod_box_y - 12, prod_box_x + prod_w + 12, prod_box_y + prod_h + 12]
    draw.rounded_rectangle(border_rect, radius=24, fill=(15, 23, 42, 220), outline=(6, 182, 212, 180), width=4)
    
    bg.paste(prod_resized, (prod_box_x, prod_box_y), prod_resized)

    # 3. Top Floating Badge (Flash Sale / Hot Deal)
    badge_rect = [60, 80, WIDTH - 60, 180]
    draw.rounded_rectangle(badge_rect, radius=20, fill=(225, 29, 72, 240), outline=(254, 205, 211, 200), width=3)
    
    # Try load fonts or default
    try:
        font_title = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 38)
        font_badge = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 40)
        font_price = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 52)
        font_strike = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 36)
        font_cta = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 34)
        font_sub = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 28)
    except Exception:
        font_title = font_badge = font_price = font_strike = font_cta = font_sub = ImageFont.load_default()

    draw.text((WIDTH // 2, 130), badge_text, fill=(255, 255, 255, 255), font=font_badge, anchor="mm")

    # 4. Product Name Title Banner
    short_title = product_name[:65] + ("..." if len(product_name) > 65 else "")
    draw.text((WIDTH // 2, 250), short_title, fill=(255, 255, 255, 255), font=font_title, anchor="mm")
    draw.text((WIDTH // 2, 310), f"⭐⭐⭐⭐⭐  Rating {rating}  •  Terlaris", fill=(251, 191, 36, 255), font=font_sub, anchor="mm")

    # 5. Price Tag Drop Banner (Bottom Section)
    price_box_rect = [60, 1460, WIDTH - 60, 1640]
    draw.rounded_rectangle(price_box_rect, radius=24, fill=(15, 23, 42, 240), outline=(16, 185, 129, 220), width=4)
    
    # Original Strike-through & Flash Sale Price
    draw.text((180, 1550), f"{orig_price}", fill=(148, 163, 184, 255), font=font_strike, anchor="mm")
    # Draw strike line
    draw.line([(100, 1550), (260, 1550)], fill=(239, 68, 68, 255), width=4)
    
    draw.text((580, 1550), f"DROP: {disc_price} 🔥", fill=(52, 211, 153, 255), font=font_price, anchor="mm")

    # 6. Bottom Sticky CTA Banner
    cta_rect = [40, 1700, WIDTH - 40, 1840]
    draw.rounded_rectangle(cta_rect, radius=20, fill=(245, 158, 11, 255), outline=(254, 240, 138, 255), width=3)
    draw.text((WIDTH // 2, 1770), call_to_action, fill=(15, 23, 42, 255), font=font_cta, anchor="mm")

    # Save frame
    if not output_path:
        output_path = os.path.join(VIDEO_OUT_DIR, "Frames", f"frame_{int(time.time() * 1000)}.png")
    bg.save(output_path, "PNG")
    return output_path


def generate_video_from_images(
    image_paths: List[str],
    product_name: str,
    voiceover_text: str,
    orig_price: str = "Rp 149.000",
    disc_price: str = "Rp 49.900",
    voice: str = "id-ID-GadisNeural",
    output_filename: Optional[str] = None
) -> Dict[str, Any]:
    """
    Renders high-quality 9:16 (1080x1920) promotional video from product image(s) with:
    - Dynamic Ken Burns Zoom/Pan animation
    - Neural Indonesian Voiceover
    - Aesthetic Flash Sale Banners & CTA overlays
    """
    start_t = time.time()
    logger.info(f"Starting Video Generation for {product_name} with {len(image_paths)} images")
    
    # 1. Clean & validate images
    valid_images = []
    for p in image_paths:
        exp = os.path.expanduser(p.strip())
        if os.path.exists(exp):
            valid_images.append(exp)
            
    if not valid_images:
        # Create a placeholder product frame if no images provided
        placeholder = os.path.join(VIDEO_OUT_DIR, "Frames", "temp_sample.png")
        sample_img = Image.new("RGBA", (800, 800), (30, 41, 59, 255))
        d = ImageDraw.Draw(sample_img)
        d.text((400, 400), "PRODUK RESMI", fill=(255, 255, 255, 255), anchor="mm")
        sample_img.save(placeholder)
        valid_images = [placeholder]

    # 2. Generate Neural Audio Voiceover
    audio_path = generate_voiceover(voiceover_text, voice=voice)
    duration_sec = get_audio_duration(audio_path)
    
    # 3. Generate High-Res 1080x1920 Frames
    frame_paths = []
    for idx, img_p in enumerate(valid_images):
        frame_out = os.path.join(VIDEO_OUT_DIR, "Frames", f"slide_{int(time.time())}_{idx}.png")
        create_aesthetic_frame(
            image_path=img_p,
            product_name=product_name,
            orig_price=orig_price,
            disc_price=disc_price,
            output_path=frame_out
        )
        frame_paths.append(frame_out)

    # 4. Determine output file
    if not output_filename:
        safe_stem = re.sub(r'[^a-zA-Z0-9_-]', '_', product_name)[:25]
        output_filename = f"{safe_stem}_{int(time.time())}.mp4"
    elif not output_filename.endswith(".mp4"):
        output_filename = f"{output_filename}.mp4"
        
    final_video_path = os.path.join(VIDEO_OUT_DIR, output_filename)

    # 5. FFmpeg Video Rendering with Ken Burns Zoom & Smooth Motion
    per_image_duration = max(3.0, duration_sec / len(frame_paths))
    
    if len(frame_paths) == 1:
        # Single image: Continuous Smooth Zoom-In (Ken Burns)
        cmd = [
            "ffmpeg", "-y",
            "-loop", "1", "-i", frame_paths[0],
            "-i", audio_path,
            "-vf", f"zoompan=z='min(zoom+0.0015,1.15)':d={int(duration_sec * 30)}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920:fps=30",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "fast", "-tune", "stillimage",
            "-c:a", "aac", "-b:a", "192k",
            "-t", str(duration_sec + 0.5),
            final_video_path
        ]
    else:
        # Multi-image slideshow: Concatenate with zoom transitions
        inputs = []
        filter_parts = []
        for i, fp in enumerate(frame_paths):
            inputs.extend(["-loop", "1", "-t", str(per_image_duration), "-i", fp])
            filter_parts.append(f"[{i}:v]zoompan=z='min(zoom+0.0015,1.12)':d={int(per_image_duration * 30)}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920:fps=30[v{i}];")
            
        concat_inputs = "".join([f"[v{i}]" for i in range(len(frame_paths))])
        filter_parts.append(f"{concat_inputs}concat=n={len(frame_paths)}:v=1:a=0[outv]")
        
        filter_str = "".join(filter_parts)
        
        cmd = [
            "ffmpeg", "-y",
            *inputs,
            "-i", audio_path,
            "-filter_complex", filter_str,
            "-map", "[outv]",
            "-map", f"{len(frame_paths)}:a",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "fast",
            "-c:a", "aac", "-b:a", "192k",
            "-t", str(duration_sec + 0.5),
            final_video_path
        ]

    logger.info(f"Executing FFmpeg video render: {' '.join(cmd)}")
    subprocess.run(cmd, check=True)
    
    duration_ms = round((time.time() - start_t) * 1000, 1)
    file_size_kb = round(os.path.getsize(final_video_path) / 1024, 2)
    file_size_mb = round(file_size_kb / 1024, 2)

    return {
        "status": "success",
        "product_name": product_name,
        "video_path": final_video_path,
        "video_filename": output_filename,
        "resolution": "1080x1920 (9:16 Vertical TikTok/Reels)",
        "duration_seconds": round(duration_sec, 1),
        "file_size_mb": file_size_mb,
        "render_duration_ms": duration_ms,
        "download_url": f"/api/artifacts/download?path={final_video_path}",
        "audio_voice": voice,
        "images_used": len(frame_paths)
    }
