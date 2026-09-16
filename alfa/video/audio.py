"""Audio, voiceover generation, duration calculation, and text sanitization."""

import logging
import os
import re
import shutil
import subprocess
import time

logger = logging.getLogger("alfa.video.audio")

VIDEO_OUT_DIR = os.path.expanduser("~/Dokumen/ALFA_GENERATED_VIDEOS")
os.makedirs(VIDEO_OUT_DIR, exist_ok=True)
os.makedirs(os.path.join(VIDEO_OUT_DIR, "Frames"), exist_ok=True)
os.makedirs(os.path.join(VIDEO_OUT_DIR, "Audio"), exist_ok=True)


def sanitize_display_text(text: str) -> str:
    """Removes unsupported emoji glyphs that cause square box [?] rendering in standard TTF fonts."""
    if not text:
        return ""
    # Strip high-plane emojis & dingbats that trigger missing glyph boxes
    cleaned = re.sub(r'[\U00010000-\U0010ffff]', '', text)
    cleaned = re.sub(r'[\u2600-\u27ff]', '', cleaned)
    cleaned = re.sub(r'[\u2300-\u23ff]', '', cleaned)
    cleaned = re.sub(r'[\u200d\ufe0f\ufe0e]', '', cleaned)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned


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
    
    edge_tts_bin = None
    if os.name == "nt":
        candidates = [
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "venv", "Scripts", "edge-tts.exe"),
            shutil.which("edge-tts.exe"),
            shutil.which("edge-tts"),
            "edge-tts",
        ]
    else:
        candidates = [
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "venv", "bin", "edge-tts"),
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
