"""Visual motion compositor, product staging, vector graphics, and text overlays."""

import logging
import math
import os
import textwrap
import time

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from alfa.video.audio import VIDEO_OUT_DIR, sanitize_display_text

logger = logging.getLogger("alfa.video.compositor")


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
    output_path: str | None = None,
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
