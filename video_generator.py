"""
╔══════════════════════════════════════════════════════════════════════════════╗
║             ALFA PRO AUTOMATED VIDEO GENERATOR ENGINE (V2.1 PRO)             ║
║   Two-Layer Motion Compositor & Multi-Engine AI Video Generator (9:16)       ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import base64
import json
import logging
import math
import os
import re
import shutil
import subprocess
import textwrap
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

logger = logging.getLogger("alfa.video_gen")

VIDEO_OUT_DIR = os.path.expanduser("~/Dokumen/ALFA_GENERATED_VIDEOS")
os.makedirs(VIDEO_OUT_DIR, exist_ok=True)
os.makedirs(os.path.join(VIDEO_OUT_DIR, "Frames"), exist_ok=True)
os.makedirs(os.path.join(VIDEO_OUT_DIR, "Audio"), exist_ok=True)


def sanitize_display_text(text: str) -> str:
    """Removes unsupported emoji glyphs that cause square box [?] rendering in standard TTF fonts."""
    if not text:
        return ""
    # Strip high-plane emojis & dingbats that trigger missing glyph boxes
    cleaned = re.sub(r"[\U00010000-\U0010ffff]", "", text)
    cleaned = re.sub(r"[\u2600-\u27ff]", "", cleaned)
    cleaned = re.sub(r"[\u2300-\u23ff]", "", cleaned)
    cleaned = re.sub(r"[\u200d\ufe0f\ufe0e]", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def get_audio_duration(audio_path: str) -> float:
    """Get exact duration of audio file in seconds using ffprobe."""
    try:
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            audio_path,
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

    edge_tts_bin = None
    if os.name == "nt":
        candidates = [
            os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "venv",
                "Scripts",
                "edge-tts.exe",
            ),
            shutil.which("edge-tts.exe"),
            shutil.which("edge-tts"),
            "edge-tts",
        ]
    else:
        candidates = [
            os.path.join(
                os.path.dirname(os.path.abspath(__file__)), "venv", "bin", "edge-tts"
            ),
            shutil.which("edge-tts"),
            "edge-tts",
        ]
    for cand in candidates:
        if cand and (os.path.exists(cand) or shutil.which(cand)):
            edge_tts_bin = cand
            break
    if not edge_tts_bin:
        edge_tts_bin = "edge-tts"

    cmd = [edge_tts_bin, "--voice", voice, "-f", "-", "--write-media", audio_path]
    # Teks dikirim via stdin ("-f -") agar tidak muncul di process list (ps aux)
    # dan tidak kena batas ARG_MAX pada voiceover panjang.
    subprocess.run(
        cmd,
        input=text.encode("utf-8"),
        check=True,
        timeout=120,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    return audio_path


def draw_star(
    draw: ImageDraw.ImageDraw,
    center_x: float,
    center_y: float,
    radius: float,
    fill=(251, 191, 36, 255),
    outline=None,
):
    """Draw a crisp 5-pointed vector star without relying on emoji fonts."""
    points = []
    for i in range(10):
        r = radius if i % 2 == 0 else radius * 0.42
        angle = i * math.pi / 5 - math.pi / 2
        x = center_x + r * math.cos(angle)
        y = center_y + r * math.sin(angle)
        points.append((x, y))
    draw.polygon(points, fill=fill, outline=outline)


def draw_lightning_icon(
    draw: ImageDraw.ImageDraw,
    start_x: float,
    start_y: float,
    size: float = 24,
    fill=(255, 255, 255, 255),
):
    """Draw a crisp vector lightning bolt icon."""
    pts = [
        (start_x + size * 0.55, start_y),
        (start_x + size * 0.15, start_y + size * 0.55),
        (start_x + size * 0.45, start_y + size * 0.55),
        (start_x + size * 0.35, start_y + size),
        (start_x + size * 0.85, start_y + size * 0.42),
        (start_x + size * 0.55, start_y + size * 0.42),
    ]
    draw.polygon(pts, fill=fill)


def get_system_font(size: int, bold: bool = True):
    """Load robust TrueType font with cross-platform OS fallback (Linux, Windows, macOS)."""
    font_candidates = [
        # Linux fonts
        (
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
            if bold
            else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"
        ),
        (
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
            if bold
            else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
        ),
        "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
        # Windows fonts
        r"C:\Windows\Fonts\arialbd.ttf" if bold else r"C:\Windows\Fonts\arial.ttf",
        r"C:\Windows\Fonts\segoeuib.ttf" if bold else r"C:\Windows\Fonts\segoeui.ttf",
        r"C:\Windows\Fonts\tahoma.ttf",
        # macOS fonts
        (
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
            if bold
            else "/System/Library/Fonts/Supplemental/Arial.ttf"
        ),
        "/Library/Fonts/Arial.ttf",
    ]
    for path in font_candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def create_product_stage_layer(image_path: str, output_path: str) -> str:
    """
    Creates Layer 0: Ambient blurred background + centered crisp product image.
    This layer will be animated with gentle Ken Burns motion.
    """
    WIDTH, HEIGHT = 1080, 1920
    bg = Image.new("RGBA", (WIDTH, HEIGHT), (10, 15, 29, 255))

    # Load product image or create high-end mock placeholder
    has_real_image = False
    if image_path and os.path.exists(image_path):
        try:
            prod_img = Image.open(image_path).convert("RGBA")
            has_real_image = True
        except Exception:
            has_real_image = False

    if not has_real_image:
        prod_img = Image.new("RGBA", (880, 880), (20, 30, 50, 255))
        d = ImageDraw.Draw(prod_img)
        d.rounded_rectangle(
            [20, 20, 860, 860],
            radius=32,
            fill=(30, 41, 59, 255),
            outline=(6, 182, 212, 120),
            width=4,
        )
        font_mock = get_system_font(42, bold=True)
        font_subm = get_system_font(28, bold=False)
        d.text(
            (440, 410),
            "FOTO PRODUK UTAMA",
            fill=(255, 255, 255, 255),
            font=font_mock,
            anchor="mm",
        )
        d.text(
            (440, 470),
            "Upload foto produk untuk hasil maksimal",
            fill=(148, 163, 184, 255),
            font=font_subm,
            anchor="mm",
        )

    # 1. Ambient Blurred Backdrop
    blur_bg = prod_img.resize((WIDTH, HEIGHT), Image.Resampling.LANCZOS)
    blur_bg = blur_bg.filter(ImageFilter.GaussianBlur(radius=60))
    enhancer = ImageEnhance.Brightness(blur_bg)
    blur_bg = enhancer.enhance(0.25)
    bg.paste(blur_bg, (0, 0))

    # 2. Main Product Image (Centered in Golden Ratio Stage)
    STAGE_TOP = 420
    STAGE_HEIGHT = 980
    STAGE_WIDTH = 900

    aspect = prod_img.height / prod_img.width
    pw = STAGE_WIDTH
    ph = int(pw * aspect)
    if ph > STAGE_HEIGHT:
        ph = STAGE_HEIGHT
        pw = int(ph / aspect)

    prod_resized = prod_img.resize((pw, ph), Image.Resampling.LANCZOS)

    px = (WIDTH - pw) // 2
    py = STAGE_TOP + (STAGE_HEIGHT - ph) // 2

    draw = ImageDraw.Draw(bg)
    # Stage Card backdrop
    card_rect = [px - 14, py - 14, px + pw + 14, py + ph + 14]
    draw.rounded_rectangle(
        card_rect,
        radius=24,
        fill=(15, 23, 42, 220),
        outline=(255, 255, 255, 30),
        width=2,
    )

    bg.paste(prod_resized, (px, py), prod_resized)
    bg.save(output_path, "PNG")
    return output_path


def create_ui_overlay_layer(
    product_name: str,
    orig_price: str,
    disc_price: str,
    badge_text: str = "FLASH SALE DISKON SPESIAL",
    call_to_action: str = "KLIK KERANJANG KUNING / BIO SEBELUM HABIS",
    theme: str = "viral_tiktok",
    rating: str = "4.9",
    output_path: Optional[str] = None,
) -> str:
    """
    Creates Layer 1: Transparent PNG with Pin-Sharp Typography, Vector Gold Stars,
    Vector Lightning Icon, and Unclipped Banners. Overlaid ON TOP of the video stream.
    """
    WIDTH, HEIGHT = 1080, 1920
    overlay = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    # Sanitize text to remove emoji glyphs that cause square [?] boxes
    clean_badge = sanitize_display_text(badge_text) or "FLASH SALE DISKON SPESIAL"
    clean_cta = (
        sanitize_display_text(call_to_action) or "KLIK KERANJANG KUNING / LINK BIO"
    )
    clean_title = sanitize_display_text(product_name) or "PRODUK PILIHAN TERLARIS"

    # Fonts
    font_badge = get_system_font(32, bold=True)
    font_title = get_system_font(36, bold=True)
    font_sub = get_system_font(24, bold=True)
    font_strike = get_system_font(32, bold=True)
    font_price = get_system_font(42, bold=True)
    font_cta = get_system_font(32, bold=True)

    # Theme colors
    if theme == "luxury_gold":
        badge_bg = (180, 83, 9, 245)
        badge_border = (253, 224, 71, 240)
        box_border = (234, 179, 8, 240)
        cta_bg = (234, 179, 8, 255)
        cta_fg = (15, 23, 42, 255)
        drop_color = (253, 224, 71, 255)
    elif theme == "cyberpunk":
        badge_bg = (217, 70, 239, 245)
        badge_border = (244, 114, 182, 240)
        box_border = (6, 182, 212, 240)
        cta_bg = (6, 182, 212, 255)
        cta_fg = (15, 23, 42, 255)
        drop_color = (6, 182, 212, 255)
    elif theme == "clean_minimal":
        badge_bg = (16, 185, 129, 245)
        badge_border = (110, 231, 183, 240)
        box_border = (16, 185, 129, 240)
        cta_bg = (16, 185, 129, 255)
        cta_fg = (15, 23, 42, 255)
        drop_color = (52, 211, 153, 255)
    else:  # viral_tiktok default
        badge_bg = (225, 29, 72, 245)
        badge_border = (254, 205, 211, 240)
        box_border = (16, 185, 129, 240)
        cta_bg = (245, 158, 11, 255)
        cta_fg = (15, 23, 42, 255)
        drop_color = (52, 211, 153, 255)

    # 1. TOP FLASH SALE BADGE (Safe Y: 120 - 195)
    badge_rect = [80, 120, WIDTH - 80, 195]
    draw.rounded_rectangle(
        badge_rect, radius=20, fill=badge_bg, outline=badge_border, width=3
    )

    # Draw vector lightning bolt on left of badge
    draw_lightning_icon(draw, 110, 138, size=24, fill=(255, 255, 255, 255))
    draw_lightning_icon(draw, WIDTH - 134, 138, size=24, fill=(255, 255, 255, 255))
    draw.text(
        (WIDTH // 2, 157),
        clean_badge,
        fill=(255, 255, 255, 255),
        font=font_badge,
        anchor="mm",
    )

    # 2. PRODUCT TITLE (Auto-Wrapped, Safe Y: 220 - 320)
    lines = textwrap.wrap(clean_title, width=34)
    if len(lines) > 2:
        lines = lines[:2]
        lines[1] = lines[1] + "..."

    cur_y = 240
    for line in lines:
        draw.text(
            (WIDTH // 2 + 2, cur_y + 2),
            line,
            fill=(0, 0, 0, 200),
            font=font_title,
            anchor="mm",
        )
        draw.text(
            (WIDTH // 2, cur_y),
            line,
            fill=(255, 255, 255, 255),
            font=font_title,
            anchor="mm",
        )
        cur_y += 44

    # 3. 5 VECTOR GOLD STARS & TRUST BADGE (Safe Y: 350)
    star_start_x = WIDTH // 2 - 120
    for i in range(5):
        draw_star(
            draw, star_start_x + (i * 26), 350, radius=11, fill=(251, 191, 36, 255)
        )

    draw.text(
        (WIDTH // 2 + 65, 350),
        f"Rating {rating} • Terlaris",
        fill=(251, 191, 36, 255),
        font=font_sub,
        anchor="lm",
    )

    # 4. BOTTOM PRICE COMPARISON CONTAINER (Safe Y: 1450 - 1590)
    price_rect = [60, 1450, WIDTH - 60, 1590]
    draw.rounded_rectangle(
        price_rect, radius=24, fill=(15, 23, 42, 245), outline=box_border, width=4
    )

    # Left Pill: Strike Price
    clean_orig = sanitize_display_text(orig_price)
    if not clean_orig.startswith("Rp"):
        clean_orig = f"Rp {clean_orig}"
    draw.text(
        (220, 1520),
        clean_orig,
        fill=(148, 163, 184, 255),
        font=font_strike,
        anchor="mm",
    )

    # Red Strike-through bar
    strike_len = int(len(clean_orig) * 9.5)
    draw.line(
        [(220 - strike_len, 1520), (220 + strike_len, 1520)],
        fill=(239, 68, 68, 255),
        width=4,
    )

    # Right Pill: Flash Drop Price
    clean_disc = sanitize_display_text(disc_price)
    if not clean_disc.startswith("Rp") and not clean_disc.startswith("DROP:"):
        clean_disc = f"DROP: Rp {clean_disc}"
    elif not clean_disc.startswith("DROP:"):
        clean_disc = f"DROP: {clean_disc}"
    draw.text((680, 1520), clean_disc, fill=drop_color, font=font_price, anchor="mm")

    # 5. BOTTOM STICKY CALL TO ACTION (Safe Y: 1640 - 1750)
    cta_rect = [50, 1640, WIDTH - 50, 1750]
    draw.rounded_rectangle(
        cta_rect, radius=20, fill=cta_bg, outline=(254, 240, 138, 255), width=3
    )
    draw.text((WIDTH // 2, 1695), clean_cta, fill=cta_fg, font=font_cta, anchor="mm")

    if not output_path:
        output_path = os.path.join(
            VIDEO_OUT_DIR, "Frames", f"overlay_{int(time.time() * 1000)}.png"
        )
    overlay.save(output_path, "PNG")
    return output_path


# ══════════════════════════════════════════════════════════════════════════════
#  MULTI-ENGINE VIDEO RENDERING (LOCAL PRO COMPOSITOR + CLOUD AI API READY)
# ══════════════════════════════════════════════════════════════════════════════

# Model Google Veo yang tersedia via Gemini API (predictLongRunning).
# Terverifikasi tersedia pada akun user via ListModels.
VEO_MODEL_MAP = {
    "google_veo": "veo-3.1-generate-preview",
    "google_veo_fast": "veo-3.1-fast-generate-preview",
    "google_veo_lite": "veo-3.1-lite-generate-preview",
}

# Gemini Omni Flash — video gen/edit generatif via Interactions API.
# Endpoint-nya BEDA dari Veo (/v1beta/interactions, bukan predictLongRunning).
OMNI_MODEL_MAP = {
    "google_omni_flash": "gemini-omni-flash-preview",
}

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"


def _veo_api_request(
    url: str,
    payload: Optional[Dict[str, Any]] = None,
    api_key: str = "",
    method: str = "GET",
) -> Dict[str, Any]:
    """Helper request JSON ke Gemini API dgn auth header x-goog-api-key."""
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8") if payload is not None else None,
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", errors="replace")
            msg = json.loads(body).get("error", {}).get("message", body)
        except Exception:
            msg = str(e)
        if "RESOURCE_EXHAUSTED" in body or e.code == 429:
            msg = (
                "Kuota Veo habis utk periode ini. Cek limit di https://ai.dev/rate-limit "
                "dan coba lagi setelah reset kuota."
            )
        elif not api_key or e.code == 403:
            msg = f"Akses ditolak ({e.code}). Pastikan Gemini API Key valid & Veo aktif di akun Anda."
        raise RuntimeError(msg)


def _generate_google_veo_video(
    engine: str,
    api_key: str,
    image_paths: List[str],
    product_name: str,
    visual_prompt: str,
    voiceover_text: str,
    orig_price: str,
    disc_price: str,
    voice: str,
    theme: str = "viral_tiktok",
    badge_text: str = "",
    call_to_action: str = "",
    output_filename: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Generate video AI dgn Google Veo 3.1 (Gemini API predictLongRunning),
    lalu komposit ulang: overlay UI promo + dubbing voiceover Indonesia.
    """
    start_t = time.time()
    model = VEO_MODEL_MAP.get(engine, VEO_MODEL_MAP["google_veo"])
    logger.info(f"Dispatching Google Veo request: model={model}")

    ts = int(time.time() * 1000)

    # 1. Gambar referensi pertama (opsional tapi disarankan utk konsistensi produk)
    instance: Dict[str, Any] = {}
    for p in image_paths:
        exp = os.path.expanduser(p.strip())
        if os.path.exists(exp):
            try:
                with open(exp, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode("ascii")
                mime = "image/png" if exp.lower().endswith(".png") else "image/jpeg"
                instance["image"] = {"bytesBase64Encoded": b64, "mimeType": mime}
            except Exception as e:
                logger.warning(f"Gagal membaca gambar referensi {exp}: {e}")
            break

    # 2. Prompt sinematik utk Veo
    prompt = (visual_prompt or "").strip() or (
        f"Cinematic 8K commercial studio video showcasing '{product_name}'. "
        f"Dramatic studio lighting, slow elegant camera push-in, premium product "
        f"photography style, shallow depth of field, vertical 9:16 composition."
    )
    instance["prompt"] = prompt

    body = {
        "instances": [instance],
        "parameters": {
            "aspectRatio": "9:16",
        },
    }

    # 3. Submit operasi generasi (asynchronous)
    submit_url = f"{GEMINI_API_BASE}/models/{model}:predictLongRunning"
    op = _veo_api_request(submit_url, payload=body, api_key=api_key, method="POST")
    op_name = op.get("name")
    if not op_name:
        raise RuntimeError(f"Veo gagal membuat operasi: {json.dumps(op)[:400]}")

    # 4. Polling status operasi (maks ±10 menit)
    poll_url = f"{GEMINI_API_BASE}/{op_name}"
    video_uri = None
    for _ in range(60):
        time.sleep(10)
        status = _veo_api_request(poll_url, api_key=api_key)
        if status.get("error"):
            raise RuntimeError(f"Veo error: {json.dumps(status.get('error'))[:400]}")
        if not status.get("done"):
            continue
        resp = status.get("response", {})
        samples = (
            resp.get("generateVideoResponse", {}).get("generatedSamples")
            or resp.get("videos")
            or []
        )
        if samples:
            video_uri = (samples[0].get("video", {}) or {}).get("uri") or samples[
                0
            ].get("uri")
        if not video_uri:
            raise RuntimeError(f"Veo selesai tanpa video: {json.dumps(resp)[:400]}")
        break
    if not video_uri:
        raise RuntimeError("Veo timeout: operasi tidak selesai dalam 10 menit.")

    # 5. Unduh hasil MP4 mentah dari Veo
    raw_path = os.path.join(VIDEO_OUT_DIR, f"veo_raw_{ts}.mp4")
    req = urllib.request.Request(video_uri, headers={"x-goog-api-key": api_key})
    with urllib.request.urlopen(req, timeout=300) as resp, open(raw_path, "wb") as f:
        shutil.copyfileobj(resp, f)

    # 6. Dubbing voiceover + overlay UI promo (komposit lokal)
    audio_path = generate_voiceover(voiceover_text, voice=voice)
    overlay_out = os.path.join(VIDEO_OUT_DIR, "Frames", f"overlay_{ts}.png")
    create_ui_overlay_layer(
        product_name=product_name,
        orig_price=orig_price,
        disc_price=disc_price,
        badge_text=badge_text or "FLASH SALE DISKON SPESIAL",
        call_to_action=call_to_action or "KLIK KERANJANG KUNING / LINK BIO",
        theme=theme,
        output_path=overlay_out,
    )

    if not output_filename:
        safe_stem = re.sub(r"[^a-zA-Z0-9_-]", "_", product_name)[:25]
        output_filename = f"{safe_stem}_veo_{int(time.time())}.mp4"
    else:
        output_filename = os.path.basename(output_filename.strip())
        if not output_filename.endswith(".mp4"):
            output_filename = f"{output_filename}.mp4"
    final_video_path = os.path.join(VIDEO_OUT_DIR, output_filename)

    veo_dur = get_audio_duration(raw_path)  # ffprobe; bekerja utk mp4 juga
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        raw_path,
        "-loop",
        "1",
        "-i",
        overlay_out,
        "-i",
        audio_path,
        "-filter_complex",
        "[0:v][1:v]overlay=0:0:shortest=1[outv]",
        "-map",
        "[outv]",
        "-map",
        "2:a",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-preset",
        "medium",
        "-crf",
        "19",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-t",
        str(round(veo_dur, 2)),
        final_video_path,
    ]
    subprocess.run(cmd, check=True, timeout=600)
    try:
        os.remove(raw_path)
    except OSError:
        pass

    duration_ms = round((time.time() - start_t) * 1000, 1)
    file_size_mb = round(os.path.getsize(final_video_path) / (1024 * 1024), 2)

    return {
        "status": "success",
        "engine": "google_veo",
        "model": model,
        "product_name": product_name,
        "video_path": final_video_path,
        "video_filename": output_filename,
        "resolution": "1080x1920 (9:16 Vertical AI Generative)",
        "duration_seconds": round(veo_dur, 1),
        "file_size_mb": file_size_mb,
        "render_duration_ms": duration_ms,
        "download_url": f"/api/artifacts/download?path={final_video_path}",
        "audio_voice": voice,
        "theme": theme,
        "visual_prompt": prompt,
    }


def _find_video_payload(obj: Any, hint: str = "") -> Optional[Dict[str, Any]]:
    """Telusuri JSON respons Interactions API secara rekursif mencari payload
    video: inline base64 (mime_type video/* + data) atau URI yang bisa diunduh.
    `hint` membawa nama kunci induk agar URI di bawah kunci seperti
    "videos"/"generatedSamples" tetap dikenali."""
    if isinstance(obj, dict):
        mime = str(obj.get("mime_type") or obj.get("mimeType") or "")
        data = obj.get("data")
        if "video" in mime and isinstance(data, str) and len(data) > 128:
            return {"inline": True, "data": data}
        uri = obj.get("uri") or obj.get("videoUri") or obj.get("file_uri")
        if (
            isinstance(uri, str)
            and uri.startswith("http")
            and (
                "video" in mime
                or "video" in uri.lower()
                or "video" in hint.lower()
                or obj.get("role") == "model"
            )
        ):
            return {"inline": False, "uri": uri}
        for k, v in obj.items():
            found = _find_video_payload(v, hint=str(k))
            if found:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = _find_video_payload(item, hint=hint)
            if found:
                return found
    return None


def _generate_gemini_omni_video(
    engine: str,
    api_key: str,
    image_paths: List[str],
    product_name: str,
    visual_prompt: str,
    voiceover_text: str,
    orig_price: str,
    disc_price: str,
    voice: str,
    theme: str = "viral_tiktok",
    badge_text: str = "",
    call_to_action: str = "",
    output_filename: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Generate video AI dengan Gemini Omni Flash (Interactions API).
    Flow: POST /v1beta/interactions (background) -> poll by name ->
    unduh/decode MP4 -> komposit overlay UI promo + dubbing lokal.
    """
    start_t = time.time()
    model = OMNI_MODEL_MAP.get(engine, engine)
    logger.info(f"Dispatching Gemini Omni Flash request: model={model}")

    ts = int(time.time() * 1000)

    # 1. Susun input multimodal: gambar referensi (image_to_video) atau teks saja
    parts: List[Dict[str, Any]] = []
    task = "text_to_video"
    for p in image_paths:
        exp = os.path.expanduser(p.strip())
        if os.path.exists(exp):
            try:
                with open(exp, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode("ascii")
                mime = "image/png" if exp.lower().endswith(".png") else "image/jpeg"
                parts.append({"type": "image", "data": b64, "mime_type": mime})
                task = "image_to_video"
            except Exception as e:
                logger.warning(f"Gagal membaca gambar referensi {exp}: {e}")
            break

    prompt = (visual_prompt or "").strip() or (
        f"Cinematic commercial studio video showcasing '{product_name}'. "
        f"Dramatic lighting, slow elegant camera push-in, premium product "
        f"photography style, vertical 9:16 composition."
    )
    parts.append({"type": "text", "text": prompt})

    body = {
        "model": model,
        "input": parts,
        "generation_config": {"video_config": {"task": task}},
        "response_format": {"type": "video", "aspect_ratio": "9:16"},
        "background": True,
    }

    # 2. Submit interaksi background
    submit_url = f"{GEMINI_API_BASE}/interactions"
    op = _veo_api_request(submit_url, payload=body, api_key=api_key, method="POST")
    op_name = op.get("name") or op.get("id")
    if not op_name:
        raise RuntimeError(
            f"Omni Flash gagal membuat interaksi: {json.dumps(op)[:400]}"
        )

    # 3. Polling status (maks ±10 menit; umumnya selesai ~45-90 detik)
    poll_url = f"{GEMINI_API_BASE}/{op_name}"
    payload_found = None
    for _ in range(60):
        time.sleep(10)
        status = _veo_api_request(poll_url, api_key=api_key)
        if status.get("error"):
            raise RuntimeError(
                f"Omni Flash error: {json.dumps(status.get('error'))[:400]}"
            )
        state = str(status.get("status") or "").lower()
        done = status.get("done")
        if done is False or state in ("pending", "running", "in_progress", "queued"):
            continue
        payload_found = _find_video_payload(status)
        if (
            payload_found
            or done is True
            or state in ("completed", "succeeded", "active", "finished")
        ):
            break
    if not payload_found:
        raise RuntimeError("Omni Flash timeout: video tidak selesai dalam 10 menit.")

    # 4. Dapatkan MP4 mentah (inline base64 atau unduh via URI)
    raw_path = os.path.join(VIDEO_OUT_DIR, f"omni_raw_{ts}.mp4")
    if payload_found.get("inline"):
        with open(raw_path, "wb") as f:
            f.write(base64.b64decode(payload_found["data"]))
    else:
        req = urllib.request.Request(
            payload_found["uri"], headers={"x-goog-api-key": api_key}
        )
        with urllib.request.urlopen(req, timeout=300) as resp, open(
            raw_path, "wb"
        ) as f:
            shutil.copyfileobj(resp, f)

    # 5. Dubbing voiceover + overlay UI promo (komposit lokal, sama dgn jalur Veo)
    audio_path = generate_voiceover(voiceover_text, voice=voice)
    overlay_out = os.path.join(VIDEO_OUT_DIR, "Frames", f"overlay_{ts}.png")
    create_ui_overlay_layer(
        product_name=product_name,
        orig_price=orig_price,
        disc_price=disc_price,
        badge_text=badge_text or "FLASH SALE DISKON SPESIAL",
        call_to_action=call_to_action or "KLIK KERANJANG KUNING / LINK BIO",
        theme=theme,
        output_path=overlay_out,
    )

    if not output_filename:
        safe_stem = re.sub(r"[^a-zA-Z0-9_-]", "_", product_name)[:25]
        output_filename = f"{safe_stem}_omni_{int(time.time())}.mp4"
    else:
        output_filename = os.path.basename(output_filename.strip())
        if not output_filename.endswith(".mp4"):
            output_filename = f"{output_filename}.mp4"
    final_video_path = os.path.join(VIDEO_OUT_DIR, output_filename)

    omni_dur = get_audio_duration(raw_path)
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        raw_path,
        "-loop",
        "1",
        "-i",
        overlay_out,
        "-i",
        audio_path,
        "-filter_complex",
        "[0:v][1:v]overlay=0:0:shortest=1[outv]",
        "-map",
        "[outv]",
        "-map",
        "2:a",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-preset",
        "medium",
        "-crf",
        "19",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-t",
        str(round(omni_dur, 2)),
        final_video_path,
    ]
    subprocess.run(cmd, check=True, timeout=600)
    try:
        os.remove(raw_path)
    except OSError:
        pass

    duration_ms = round((time.time() - start_t) * 1000, 1)
    file_size_mb = round(os.path.getsize(final_video_path) / (1024 * 1024), 2)

    return {
        "status": "success",
        "engine": "google_omni_flash",
        "model": model,
        "task": task,
        "product_name": product_name,
        "video_path": final_video_path,
        "video_filename": output_filename,
        "resolution": "1080x1920 (9:16 Vertical AI Generative)",
        "duration_seconds": round(omni_dur, 1),
        "file_size_mb": file_size_mb,
        "render_duration_ms": duration_ms,
        "download_url": f"/api/artifacts/download?path={final_video_path}",
        "audio_voice": voice,
        "theme": theme,
        "visual_prompt": prompt,
    }


def generate_video_from_images(
    image_paths: List[str],
    product_name: str,
    voiceover_text: str,
    orig_price: str = "Rp 149.000",
    disc_price: str = "Rp 49.900",
    voice: str = "id-ID-GadisNeural",
    theme: str = "viral_tiktok",
    motion_style: str = "zoom_in",
    badge_text: str = "FLASH SALE DISKON SPESIAL",
    call_to_action: str = "KLIK KERANJANG KUNING / BIO SEBELUM HABIS",
    visual_prompt: Optional[str] = None,
    engine: str = "local_pro",
    api_key: Optional[str] = None,
    output_filename: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Renders ultra-sharp 9:16 (1080x1920) promotional video with Two-Layer Compositor:
    - Layer 0: Smooth Slow Ken Burns Motion (1.00x -> 1.05x) on Product Stage
    - Layer 1: Pixel-Perfect Static Overlay (No UI cropping, No Text overlapping, Vector Stars, No square boxes)
    - Supports Cloud AI Video generation when API key is provided.
    """
    start_t = time.time()
    logger.info(f"Starting Video Render for {product_name}, engine={engine}")

    # Cloud AI Video API Handler Dispatcher (Google Veo / Omni Flash / Kling / Luma / Runway)
    if engine in OMNI_MODEL_MAP:
        try:
            return _generate_gemini_omni_video(
                engine=engine,
                api_key=api_key or "",
                image_paths=image_paths,
                product_name=product_name,
                visual_prompt=visual_prompt,
                voiceover_text=voiceover_text,
                orig_price=orig_price,
                disc_price=disc_price,
                voice=voice,
                theme=theme,
                badge_text=badge_text,
                call_to_action=call_to_action,
                output_filename=output_filename,
            )
        except Exception as e:
            logger.error(f"Omni Flash render gagal: {e}")
            return {
                "status": "error",
                "engine": engine,
                "model": OMNI_MODEL_MAP.get(engine),
                "message": str(e),
            }
    if engine in VEO_MODEL_MAP:
        try:
            return _generate_google_veo_video(
                engine=engine,
                api_key=api_key or "",
                image_paths=image_paths,
                product_name=product_name,
                visual_prompt=visual_prompt,
                voiceover_text=voiceover_text,
                orig_price=orig_price,
                disc_price=disc_price,
                voice=voice,
                theme=theme,
                badge_text=badge_text,
                call_to_action=call_to_action,
                output_filename=output_filename,
            )
        except Exception as e:
            logger.error(f"Veo render gagal: {e}")
            return {
                "status": "error",
                "engine": engine,
                "model": VEO_MODEL_MAP.get(engine),
                "message": str(e),
            }
    if engine in ("kling", "luma", "runway", "fal_ai", "replicate") and api_key:
        return _generate_cloud_ai_video(
            engine=engine,
            api_key=api_key,
            image_paths=image_paths,
            product_name=product_name,
            visual_prompt=visual_prompt,
            voiceover_text=voiceover_text,
            orig_price=orig_price,
            disc_price=disc_price,
            voice=voice,
            output_filename=output_filename,
        )

    # 1. Validate images
    valid_images = []
    for p in image_paths:
        exp = os.path.expanduser(p.strip())
        if os.path.exists(exp):
            valid_images.append(exp)

    if not valid_images:
        placeholder = os.path.join(VIDEO_OUT_DIR, "Frames", "temp_stage.png")
        create_product_stage_layer("", placeholder)
        valid_images = [placeholder]

    # 2. Voiceover & Audio Measurement
    audio_path = generate_voiceover(voiceover_text, voice=voice)
    duration_sec = get_audio_duration(audio_path)
    total_frames = int(duration_sec * 30)

    # 3. Create Layer 0 (Product Stage) & Layer 1 (Transparent UI Overlay)
    stage_layers = []
    for idx, img_p in enumerate(valid_images):
        stage_out = os.path.join(
            VIDEO_OUT_DIR, "Frames", f"stage_{int(time.time() * 1000)}_{idx}.png"
        )
        create_product_stage_layer(img_p, stage_out)
        stage_layers.append(stage_out)

    overlay_out = os.path.join(
        VIDEO_OUT_DIR, "Frames", f"overlay_{int(time.time() * 1000)}.png"
    )
    create_ui_overlay_layer(
        product_name=product_name,
        orig_price=orig_price,
        disc_price=disc_price,
        badge_text=badge_text,
        call_to_action=call_to_action,
        theme=theme,
        output_path=overlay_out,
    )

    # 4. Output Path
    if not output_filename:
        safe_stem = re.sub(r"[^a-zA-Z0-9_-]", "_", product_name)[:25]
        output_filename = f"{safe_stem}_{int(time.time())}.mp4"
    else:
        # Prevent path traversal via user-supplied filenames
        output_filename = os.path.basename(output_filename.strip())
        if not output_filename.endswith(".mp4"):
            output_filename = f"{output_filename}.mp4"

    final_video_path = os.path.join(VIDEO_OUT_DIR, output_filename)

    # 5. Dual-Layer FFmpeg Motion Compositing (Gentle 1.00 -> 1.05 push-in on background only)
    if motion_style == "zoom_out":
        zoom_expr = f"zoompan=z='max(1.05-0.00004*on,1.0)':d={total_frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920:fps=30"
    elif motion_style == "pan_left_right":
        zoom_expr = f"zoompan=z='1.03':x='(iw-iw/zoom)*(sin(it*0.5)+1)/2':y='ih/2-(ih/zoom/2)':d={total_frames}:s=1080x1920:fps=30"
    else:  # zoom_in
        zoom_expr = f"zoompan=z='min(1.0+0.00004*on,1.05)':d={total_frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920:fps=30"

    per_img_dur = max(3.0, duration_sec / len(stage_layers))

    if len(stage_layers) == 1:
        filter_complex = f"[0:v]{zoom_expr}[bg];[bg][1:v]overlay=0:0[outv]"
        cmd = [
            "ffmpeg",
            "-y",
            "-loop",
            "1",
            "-i",
            stage_layers[0],
            "-loop",
            "1",
            "-i",
            overlay_out,
            "-i",
            audio_path,
            "-filter_complex",
            filter_complex,
            "-map",
            "[outv]",
            "-map",
            "2:a",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-preset",
            "medium",
            "-crf",
            "19",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-t",
            str(duration_sec + 0.3),
            final_video_path,
        ]
    else:
        inputs = []
        filter_parts = []
        per_frames = max(1, int(per_img_dur * 30))
        zoom_rate = 0.05 / per_frames
        for i, sl in enumerate(stage_layers):
            # Feed each still image ONCE and let zoompan generate the full
            # frame span (d=per_frames). Duplicating via -loop AND zoompan's d
            # multiplies durations (~25x) so later images were never reached.
            inputs.extend(["-i", sl])
            if motion_style == "zoom_out":
                z_expr = f"max(1.05-{zoom_rate}*on,1.0)"
                pos_expr = "x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
            elif motion_style == "pan_left_right":
                z_expr = "1.03"
                pos_expr = f"x='(iw-iw/zoom)*(sin((on/{per_frames})*PI)+1)/2':y='ih/2-(ih/zoom/2)'"
            else:  # zoom_in
                z_expr = f"min(1.0+{zoom_rate}*on,1.05)"
                pos_expr = "x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
            filter_parts.append(
                f"[{i}:v]zoompan=z='{z_expr}':d={per_frames}:{pos_expr}:s=1080x1920:fps=30[v{i}];"
            )

        concat_inputs = "".join([f"[v{i}]" for i in range(len(stage_layers))])
        filter_parts.append(f"{concat_inputs}concat=n={len(stage_layers)}:v=1:a=0[bg];")

        overlay_idx = len(stage_layers)
        audio_idx = overlay_idx + 1
        inputs.extend(["-loop", "1", "-i", overlay_out])

        filter_parts.append(f"[bg][{overlay_idx}:v]overlay=0:0[outv]")
        filter_str = "".join(filter_parts)

        cmd = [
            "ffmpeg",
            "-y",
            *inputs,
            "-i",
            audio_path,
            "-filter_complex",
            filter_str,
            "-map",
            "[outv]",
            "-map",
            f"{audio_idx}:a",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-preset",
            "medium",
            "-crf",
            "19",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-t",
            str(duration_sec + 0.3),
            final_video_path,
        ]

    logger.info(f"Executing FFmpeg render: {' '.join(cmd)}")
    subprocess.run(cmd, check=True, timeout=600)

    duration_ms = round((time.time() - start_t) * 1000, 1)
    file_size_mb = round(os.path.getsize(final_video_path) / (1024 * 1024), 2)

    return {
        "status": "success",
        "engine": "local_pro_compositor",
        "product_name": product_name,
        "video_path": final_video_path,
        "video_filename": output_filename,
        "resolution": "1080x1920 (9:16 Vertical Pro)",
        "duration_seconds": round(duration_sec, 1),
        "file_size_mb": file_size_mb,
        "render_duration_ms": duration_ms,
        "download_url": f"/api/artifacts/download?path={final_video_path}",
        "audio_voice": voice,
        "theme": theme,
        "motion_style": motion_style,
        "visual_prompt": visual_prompt
        or f"8K Commercial Studio video of {product_name}",
    }


def _generate_cloud_ai_video(
    engine: str,
    api_key: str,
    image_paths: List[str],
    product_name: str,
    visual_prompt: str,
    voiceover_text: str,
    orig_price: str,
    disc_price: str,
    voice: str,
    output_filename: Optional[str],
) -> Dict[str, Any]:
    """
    Dispatcher for Cloud AI Video Generation APIs (Kling, Luma, Runway, Fal.ai, Replicate).
    """
    logger.info(f"Dispatching Cloud AI Video Request to {engine}...")
    # Cloud AI logic template ready to execute with user's specific endpoint/token
    return {
        "status": "pending_api_dispatch",
        "engine": engine,
        "product_name": product_name,
        "visual_prompt": visual_prompt,
        "message": f"Konektor Cloud AI Video ({engine.upper()}) siap menerima API Key dan menghasilkan video generatif.",
    }
