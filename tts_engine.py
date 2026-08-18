"""
TTS Engine for Telegram AI Bot using Edge-TTS.
Generates ultra-natural voice audio for Telegram Voice Notes.
"""

import os
import re
import tempfile
import edge_tts
import logging

logger = logging.getLogger("TTSEngine")

# Available voices:
# id-ID-GadisNeural (Female Indonesian)
# id-ID-ArdiNeural (Male Indonesian)
# en-US-AriaNeural (Female English)
DEFAULT_VOICE = "id-ID-GadisNeural"


def clean_markdown_for_tts(text: str) -> str:
    """Strip markdown symbols and code blocks for smooth speech reading."""
    # Remove code blocks
    text = re.sub(r"```[\s\S]*?```", " [cuplikan kode] ", text)
    text = re.sub(r"`[^`]*`", " ", text)
    # Remove bold, italics, links, headers
    text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)
    text = re.sub(r"[\*\_~#>`-]", " ", text)
    # Normalize spaces
    text = re.sub(r"\s+", " ", text).strip()
    return text


async def text_to_speech_ogg(text: str, voice: str = DEFAULT_VOICE) -> str:
    """
    Convert text to an audio file (.ogg / .mp3) suitable for Telegram voice notes.
    Returns the path to the temporary audio file.
    """
    clean_text = clean_markdown_for_tts(text)
    if not clean_text:
        clean_text = "Baik, pesan telah diterima."

    # Limit TTS length to first 800 characters to prevent huge files
    if len(clean_text) > 800:
        clean_text = clean_text[:800] + " ...dan rincian selengkapnya telah saya sertakan dalam teks."

    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
    temp_path = temp_file.name
    temp_file.close()

    try:
        communicate = edge_tts.Communicate(clean_text, voice)
        await communicate.save(temp_path)
        return temp_path
    except Exception as e:
        logger.error(f"TTS generation error: {e}")
        if os.path.exists(temp_path):
            os.remove(temp_path)
        raise e
