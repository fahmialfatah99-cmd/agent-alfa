# -*- coding: utf-8 -*-
"""
Media generation, speech synthesis (TTS), PDF suite, and Office documents.

Backward-compatibility facade module: Re-exports all functionality from
the modular `alfa.tools.media.*` packages.
"""

import logging

from alfa.tools.media.pdf_builder import (
    get_pdf_output_dir,
    generate_pdf_report,
    pdf_apply_watermark_text,
    pdf_insert_page_numbers,
    pdf_convert_to_images,
    images_convert_to_pdf,
)

from alfa.tools.media.pdf_editor import (
    pdf_merge_documents,
    pdf_split_document,
    pdf_extract_full_text,
    pdf_encrypt_password,
    pdf_decrypt_password,
    pdf_rotate_pages,
    pdf_inspect_metadata,
    pdf_compress_and_optimize,
)

from alfa.tools.media.av import (
    upscale_image_hd,
    generate_promo_video_from_images,
    extract_audio_from_video,
    text_to_audio_file,
    convert_media_format,
    edit_image,
)

from alfa.tools.media.documents import (
    generate_excel_spreadsheet,
    generate_presentation_pptx,
    analyze_dataset_csv_json,
    translate_text,
)

logger = logging.getLogger("AgentTools.Media")

__all__ = [
    # pdf_builder
    "get_pdf_output_dir",
    "generate_pdf_report",
    "pdf_apply_watermark_text",
    "pdf_insert_page_numbers",
    "pdf_convert_to_images",
    "images_convert_to_pdf",
    # pdf_editor
    "pdf_merge_documents",
    "pdf_split_document",
    "pdf_extract_full_text",
    "pdf_encrypt_password",
    "pdf_decrypt_password",
    "pdf_rotate_pages",
    "pdf_inspect_metadata",
    "pdf_compress_and_optimize",
    # av
    "upscale_image_hd",
    "generate_promo_video_from_images",
    "extract_audio_from_video",
    "text_to_audio_file",
    "convert_media_format",
    "edit_image",
    # documents
    "generate_excel_spreadsheet",
    "generate_presentation_pptx",
    "analyze_dataset_csv_json",
    "translate_text",
]
