"""
Media Tools Package for ALFA.
Deconstructed modules:
- pdf_builder: Report generator, watermarking, page numbers, and image conversions
- pdf_editor: Merge, split, OCR/text extract, encrypt/decrypt, rotate, inspect, compress
- av: Video promo, TTS neural voice, media convert, HD upscale, and Pillow editing
- documents: Excel spreadsheet generator, PowerPoint pptx, dataset analysis, translation
"""

from alfa.tools.media.av import (
    convert_media_format,
    edit_image,
    extract_audio_from_video,
    generate_promo_video_from_images,
    text_to_audio_file,
    upscale_image_hd,
)
from alfa.tools.media.documents import (
    analyze_dataset_csv_json,
    generate_excel_spreadsheet,
    generate_presentation_pptx,
    translate_text,
)
from alfa.tools.media.pdf_builder import (
    generate_pdf_report,
    get_pdf_output_dir,
    images_convert_to_pdf,
    pdf_apply_watermark_text,
    pdf_convert_to_images,
    pdf_insert_page_numbers,
)
from alfa.tools.media.pdf_editor import (
    pdf_compress_and_optimize,
    pdf_decrypt_password,
    pdf_encrypt_password,
    pdf_extract_full_text,
    pdf_inspect_metadata,
    pdf_merge_documents,
    pdf_rotate_pages,
    pdf_split_document,
)

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
