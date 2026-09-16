"""Cloud and multimodal AI video generation engines (Google Veo, Gemini Omni Flash, Kling, Luma)."""

import base64
import json
import logging
import os
import subprocess
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from alfa.video.audio import VIDEO_OUT_DIR, generate_voiceover, get_audio_duration

logger = logging.getLogger("alfa.video.ai_engines")

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


def _veo_api_request(url: str, payload: Optional[Dict[str, Any]] = None,
                     api_key: str = "", method: str = "GET") -> Dict[str, Any]:
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
            msg = ("Kuota Veo habis utk periode ini. Cek limit di https://ai.dev/rate-limit "
                   "dan coba lagi setelah reset kuota.")
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
    output_filename: Optional[str] = None
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
        f"photography style, shallow depth of field, vertical 9:16 composition.")
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
        samples = (resp.get("generateVideoResponse", {}).get("generatedSamples")
                   or resp.get("videos") or [])
        if samples:
            video_uri = (samples[0].get("video", {}) or {}).get("uri") or samples[0].get("uri")
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
        output_path=overlay_out
    )

    if not output_filename:
        safe_stem = re.sub(r'[^a-zA-Z0-9_-]', '_', product_name)[:25]
        output_filename = f"{safe_stem}_veo_{int(time.time())}.mp4"
    else:
        output_filename = os.path.basename(output_filename.strip())
        if not output_filename.endswith(".mp4"):
            output_filename = f"{output_filename}.mp4"
    final_video_path = os.path.join(VIDEO_OUT_DIR, output_filename)

    veo_dur = get_audio_duration(raw_path)  # ffprobe; bekerja utk mp4 juga
    cmd = [
        "ffmpeg", "-y",
        "-i", raw_path,
        "-loop", "1", "-i", overlay_out,
        "-i", audio_path,
        "-filter_complex", "[0:v][1:v]overlay=0:0:shortest=1[outv]",
        "-map", "[outv]", "-map", "2:a",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "medium", "-crf", "19",
        "-c:a", "aac", "-b:a", "192k",
        "-t", str(round(veo_dur, 2)),
        final_video_path
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
        "visual_prompt": prompt
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
        if isinstance(uri, str) and uri.startswith("http") and (
            "video" in mime or "video" in uri.lower()
            or "video" in hint.lower() or obj.get("role") == "model"
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
    output_filename: Optional[str] = None
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
        f"photography style, vertical 9:16 composition.")
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
        raise RuntimeError(f"Omni Flash gagal membuat interaksi: {json.dumps(op)[:400]}")

    # 3. Polling status (maks ±10 menit; umumnya selesai ~45-90 detik)
    poll_url = f"{GEMINI_API_BASE}/{op_name}"
    payload_found = None
    for _ in range(60):
        time.sleep(10)
        status = _veo_api_request(poll_url, api_key=api_key)
        if status.get("error"):
            raise RuntimeError(f"Omni Flash error: {json.dumps(status.get('error'))[:400]}")
        state = str(status.get("status") or "").lower()
        done = status.get("done")
        if done is False or state in ("pending", "running", "in_progress", "queued"):
            continue
        payload_found = _find_video_payload(status)
        if payload_found or done is True or state in ("completed", "succeeded", "active", "finished"):
            break
    if not payload_found:
        raise RuntimeError("Omni Flash timeout: video tidak selesai dalam 10 menit.")

    # 4. Dapatkan MP4 mentah (inline base64 atau unduh via URI)
    raw_path = os.path.join(VIDEO_OUT_DIR, f"omni_raw_{ts}.mp4")
    if payload_found.get("inline"):
        with open(raw_path, "wb") as f:
            f.write(base64.b64decode(payload_found["data"]))
    else:
        req = urllib.request.Request(payload_found["uri"], headers={"x-goog-api-key": api_key})
        with urllib.request.urlopen(req, timeout=300) as resp, open(raw_path, "wb") as f:
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
        output_path=overlay_out
    )

    if not output_filename:
        safe_stem = re.sub(r'[^a-zA-Z0-9_-]', '_', product_name)[:25]
        output_filename = f"{safe_stem}_omni_{int(time.time())}.mp4"
    else:
        output_filename = os.path.basename(output_filename.strip())
        if not output_filename.endswith(".mp4"):
            output_filename = f"{output_filename}.mp4"
    final_video_path = os.path.join(VIDEO_OUT_DIR, output_filename)

    omni_dur = get_audio_duration(raw_path)
    cmd = [
        "ffmpeg", "-y",
        "-i", raw_path,
        "-loop", "1", "-i", overlay_out,
        "-i", audio_path,
        "-filter_complex", "[0:v][1:v]overlay=0:0:shortest=1[outv]",
        "-map", "[outv]", "-map", "2:a",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "medium", "-crf", "19",
        "-c:a", "aac", "-b:a", "192k",
        "-t", str(round(omni_dur, 2)),
        final_video_path
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
        "visual_prompt": prompt
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
    output_filename: Optional[str]
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
        "message": f"Konektor Cloud AI Video ({engine.upper()}) siap menerima API Key dan menghasilkan video generatif."
    }
