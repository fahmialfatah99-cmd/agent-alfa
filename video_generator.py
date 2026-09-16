"""ALFA Pro Automated Video Generator Engine (V2.1 PRO).

Facade re-exporting from modular subpackage alfa.video.
"""

from alfa.video import (
    GEMINI_API_BASE,
    OMNI_MODEL_MAP,
    VEO_MODEL_MAP,
    VIDEO_OUT_DIR,
    _find_video_payload,
    _generate_cloud_ai_video,
    _generate_gemini_omni_video,
    _generate_google_veo_video,
    _veo_api_request,
    create_product_stage_layer,
    create_ui_overlay_layer,
    draw_lightning_icon,
    draw_star,
    generate_video_from_images,
    generate_voiceover,
    get_audio_duration,
    get_system_font,
    sanitize_display_text,
)

__all__ = [
    "VIDEO_OUT_DIR",
    "sanitize_display_text",
    "get_audio_duration",
    "generate_voiceover",
    "draw_star",
    "draw_lightning_icon",
    "get_system_font",
    "create_product_stage_layer",
    "create_ui_overlay_layer",
    "VEO_MODEL_MAP",
    "OMNI_MODEL_MAP",
    "GEMINI_API_BASE",
    "_veo_api_request",
    "_generate_google_veo_video",
    "_find_video_payload",
    "_generate_gemini_omni_video",
    "_generate_cloud_ai_video",
    "generate_video_from_images",
]
