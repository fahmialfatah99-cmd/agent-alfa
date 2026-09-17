"""
ALFA Tools Registry — daftar canonical semua tool publik.
Dipisahkan dari implementasi agar mudah di-audit, di-test, dan di-organisir.
"""
from typing import Dict, List, Optional

TOOL_DOMAINS: Dict[str, List[str]] = {
    "system": [
        "get_system_stats",
        "execute_bash_command",
        "execute_python_sandbox",
        "control_linux_hardware",
        "scan_local_network",
        "ssh_execute_command",
    ],
    "file": [
        "read_local_file",
        "write_local_file",
        "edit_file_precise",
        "apply_unified_diff",
        "search_workspace_files",
        "grep_workspace",
        "compress_folder_to_zip",
        "send_file_to_chat",
        "index_codebase",
        "search_codebase",
        "query_database",
    ],
    "web": [
        "web_search",
        "fetch_web_page_content",
        "browser_open_url",
        "browser_click_element",
        "browser_type_text",
        "browser_capture_screenshot",
        "browser_close_tab",
        "scrape_real_product_data",
        "scrape_large_scale_batch",
        "marketplace_search_products",
    ],
    "pdf": [
        "pdf_extract_full_text",
        "pdf_merge_documents",
        "pdf_split_document",
        "pdf_compress_and_optimize",
        "pdf_convert_to_images",
        "pdf_rotate_pages",
        "pdf_encrypt_password",
        "pdf_decrypt_password",
        "pdf_apply_watermark_text",
        "pdf_insert_page_numbers",
        "pdf_inspect_metadata",
        "images_convert_to_pdf",
        "generate_pdf_report",
    ],
    "media": [
        "capture_desktop_screenshot",
        "capture_webcam_frame",
        "record_desktop_screen",
        "desktop_click_coordinate",
        "desktop_launch_app",
        "desktop_type_keys",
        "show_desktop_notification",
        "read_clipboard",
        "write_to_clipboard",
        "generate_promo_video_from_images",
    ],
    "memory": [
        "save_knowledge_memory",
        "search_knowledge_memory",
    ],
    "scheduler": [
        "schedule_reminder",
        "add_recurring_task",
        "cancel_recurring_task",
        "list_recurring_tasks",
    ],
    "office": [
        "generate_excel_spreadsheet",
        "generate_presentation_pptx",
    ],
    "agent": [
        "manage_api_keys",
        "manage_custom_agents",
        "spawn_background_subagent",
        "check_subagent_status",
    ],
    "affiliate": [
        "affiliate_hunt_trending_products",
        "affiliate_generate_viral_content",
        "affiliate_broadcast_deal",
        "affiliate_list_campaigns",
    ],
}

# Flat list untuk quick lookup
ALL_TOOL_NAMES: List[str] = sorted({name for names in TOOL_DOMAINS.values() for name in names})

# Reverse mapping: name -> domain
TOOL_DOMAIN_MAP: Dict[str, str] = {
    name: domain
    for domain, names in TOOL_DOMAINS.items()
    for name in names
}


def get_tools_by_domain(domain: str) -> List[str]:
    """Mengembalikan daftar tool untuk domain tertentu."""
    return list(TOOL_DOMAINS.get(domain, []))


def get_domain_for_tool(tool_name: str) -> Optional[str]:
    """Mengembalikan domain untuk tool tertentu."""
    return TOOL_DOMAIN_MAP.get(tool_name)
