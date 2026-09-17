"""High-level video generation orchestrator and motion rendering pipeline."""

import logging
import os
import re
import subprocess
import time
from typing import Any, Dict, List, Optional

from alfa.video.ai_engines import (
    OMNI_MODEL_MAP,
    VEO_MODEL_MAP,
    _generate_cloud_ai_video,
    _generate_gemini_omni_video,
    _generate_google_veo_video,
)
from alfa.video.audio import VIDEO_OUT_DIR, generate_voiceover, get_audio_duration
from alfa.video.compositor import create_product_stage_layer, create_ui_overlay_layer

logger = logging.getLogger("alfa.video.orchestrator")


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
