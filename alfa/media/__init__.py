"""ALFA Media subpackage (TTS and Audio/Video processing)."""

from alfa.media import tts_engine
from alfa.media.tts_engine import (
    DEFAULT_VOICE,
    VOICE_MAP,
    clean_markdown_for_tts,
    text_to_speech_ogg,
)

__all__ = [
    "tts_engine",
    "clean_markdown_for_tts",
    "text_to_speech_ogg",
    "DEFAULT_VOICE",
    "VOICE_MAP",
]
