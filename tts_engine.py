"""
TTS Engine for Telegram AI Bot using Edge-TTS.
Generates ultra-natural voice audio for Telegram Voice Notes.
"""

from __future__ import annotations

import logging
import os
import re
import tempfile
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import edge_tts as _edge_tts

logger = logging.getLogger("TTSEngine")

# Lazy import for edge_tts to speed up module loading
_edge_tts_module = None


def _get_edge_tts():
    """Lazy load edge_tts module."""
    global _edge_tts_module
    if _edge_tts_module is None:
        try:
            import edge_tts
            _edge_tts_module = edge_tts
        except ImportError:
            _edge_tts_module = None
    return _edge_tts_module

# Available high-quality neural voices
VOICE_MAP = {
    "id_female": "id-ID-GadisNeural",
    "id_male": "id-ID-ArdiNeural",
    "en_female": "en-US-AriaNeural",
    "en_male": "en-US-GuyNeural",
}
DEFAULT_VOICE = "id-ID-GadisNeural"


def clean_markdown_for_tts(text: str) -> str:
    """Strip markdown symbols, links, emojis, and code blocks for smooth speech reading."""
    # Replace code blocks with spoken summary
    text = re.sub(r"```[\s\S]*?```", " [cuplikan kode terlampir pada teks] ", text)
    text = re.sub(r"`[^`]*`", " ", text)
    # Strip links and keep text
    text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)
    # Strip markdown formatting
    text = re.sub(r"[\*\_~#>`|]", " ", text)
    # Strip URL addresses
    text = re.sub(r"https?://\S+", " ", text)
    # Strip bullet points
    text = re.sub(r"^\s*[-•*]\s+", "", text, flags=re.MULTILINE)
    # Normalize spaces
    text = re.sub(r"\s+", " ", text).strip()
    return text


async def text_to_speech_ogg(text: str, voice: str = DEFAULT_VOICE) -> str:
    """
    Convert text to an audio file (.mp3) suitable for Telegram voice notes.
    Returns the path to the temporary audio file.
    Caller MUST remove the returned temp_path in a finally block.
    """
    clean_text = clean_markdown_for_tts(text)
    if not clean_text or len(clean_text) < 2:
        clean_text = "Baik, permintaan Anda telah selesai diproses."

    # Limit TTS length to first 850 characters to prevent overly long voice notes
    if len(clean_text) > 850:
        clean_text = clean_text[:850] + " ...dan rincian selengkapnya telah saya sertakan dalam teks."

    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
    temp_path = temp_file.name
    temp_file.close()

    # 1. Try Primary Edge-TTS
    if edge_tts is not None:
        try:
            communicate = edge_tts.Communicate(clean_text, voice)
            await communicate.save(temp_path)
            if os.path.exists(temp_path) and os.path.getsize(temp_path) > 100:
                return temp_path
        except Exception as e:
            logger.warning(f"Edge-TTS primary voice '{voice}' failed: {e}. Trying fallback...")

        # 2. Try Secondary Edge-TTS voice
        fallback_voice = "id-ID-ArdiNeural" if voice != "id-ID-ArdiNeural" else "id-ID-GadisNeural"
        try:
            communicate = edge_tts.Communicate(clean_text, fallback_voice)
            await communicate.save(temp_path)
            if os.path.exists(temp_path) and os.path.getsize(temp_path) > 100:
                return temp_path
        except Exception as e:
            logger.warning(f"Edge-TTS fallback voice '{fallback_voice}' failed: {e}. Trying gTTS...")
    else:
        logger.debug("edge_tts module is not installed, skipping Edge-TTS.")

    # 3. Try gTTS (Google Translate TTS) as robust fallback
    try:
        import gtts
        tts_obj = gtts.gTTS(text=clean_text, lang='id', slow=False)
        tts_obj.save(temp_path)
        if os.path.exists(temp_path) and os.path.getsize(temp_path) > 100:
            return temp_path
    except Exception as e:
        logger.error(f"gTTS fallback error: {e}")

    if os.path.exists(temp_path):
        try:
            os.remove(temp_path)
        except OSError:
            pass
    raise RuntimeError("Semua engine TTS (Edge-TTS & gTTS) gagal memproduksi audio.")
