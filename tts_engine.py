"""
TTS Engine for Telegram AI Bot using Edge-TTS.
Generates ultra-natural voice audio for Telegram Voice Notes.
"""

import logging
import os
import re
import tempfile

import edge_tts

logger = logging.getLogger("TTSEngine")

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

    try:
        communicate = edge_tts.Communicate(clean_text, voice)
        await communicate.save(temp_path)
        return temp_path
    except Exception as e:
        logger.error(f"TTS generation error: {e}")
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass
        raise e

