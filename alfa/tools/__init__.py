"""ALFA Tools package re-exporting all domain submodules and tools.

Provides backward-compatible flat namespace imports for all 140+ tools and
utilities previously located directly in tools.py.
"""

import logging
import os
import sys
from typing import Any, Dict, List, Optional

import database
import plugins
from alfa.core.runtime_ctx import (
    current_chat_id_var as current_chat_id_var,
    current_user_id_var as current_user_id_var,
    get_current_chat_id as get_current_chat_id,
    get_current_user_id as get_current_user_id,
)
from alfa.tools import (
    academic_tools,
    desktop_tools,
    filesystem_tools,
    media_tools,
    memory_tools,
    registry,
    system_tools,
    web_tools,
)
from alfa.tools.academic_tools import *  # noqa: F401, F403
from alfa.tools.desktop_tools import *  # noqa: F401, F403
from alfa.tools.filesystem_tools import *  # noqa: F401, F403
from alfa.tools.media_tools import *  # noqa: F401, F403
from alfa.tools.memory_tools import *  # noqa: F401, F403
from alfa.tools.registry import *  # noqa: F401, F403
from alfa.tools.system_tools import *  # noqa: F401, F403
from alfa.tools.web_tools import *  # noqa: F401, F403

# Explicit re-exports for private helpers and constants starting with _
from alfa.tools.system_tools import (  # noqa: E402
    _BASH_BLOCK_PATTERNS as _BASH_BLOCK_PATTERNS,
    _DOCKER_AVAILABLE_CACHE as _DOCKER_AVAILABLE_CACHE,
    _RM_DANGER_TARGETS as _RM_DANGER_TARGETS,
    _SANDBOX_IMAGE as _SANDBOX_IMAGE,
    _SOURCE_CODE_EXTS as _SOURCE_CODE_EXTS,
    _bash_blocked_reason as _bash_blocked_reason,
    _clean_code_snippet as _clean_code_snippet,
    _docker_available as _docker_available,
    _ensure_sandbox_image as _ensure_sandbox_image,
    _sandbox_base as _sandbox_base,
)
from alfa.tools.filesystem_tools import (  # noqa: E402
    _CODE_CHUNK_LINES as _CODE_CHUNK_LINES,
    _CODE_INDEX_DB as _CODE_INDEX_DB,
    _CODE_INDEX_MAX_CHUNKS as _CODE_INDEX_MAX_CHUNKS,
    _CODE_INDEX_SKIP_DIRS as _CODE_INDEX_SKIP_DIRS,
    _MAX_EDIT_FILE_BYTES as _MAX_EDIT_FILE_BYTES,
    _chunk_code_lines as _chunk_code_lines,
    _code_index_connect as _code_index_connect,
    _detect_gdrive_auth_mode as _detect_gdrive_auth_mode,
    _get_default_gdrive_folder_id as _get_default_gdrive_folder_id,
    _get_gdrive_service as _get_gdrive_service,
    _index_freshness as _index_freshness,
    _index_one_file as _index_one_file,
    _iter_code_files as _iter_code_files,
    _py_syntax_guard as _py_syntax_guard,
    _resolve_host_path as _resolve_host_path,
)
from alfa.tools.web_tools import (  # noqa: E402
    _ensure_camofox_server as _ensure_camofox_server,
    _find_camofox_bin as _find_camofox_bin,
    _run_camofox_cli as _run_camofox_cli,
)

logger = logging.getLogger("AgentTools")

AVAILABLE_TOOLS = [
    find_user_files,
    universal_deep_scraper,
    scrape_custom_urls_batch,
    vault_store_secret,
    vault_get_secret,
    vault_list_secrets,
    vault_delete_secret,
    audit_website_security,
    get_system_stats,
    execute_bash_command,
    execute_python_sandbox,
    web_search,
    fetch_web_page_content,
    deep_research_topic,
    browser_open_url,
    browser_click_element,
    browser_type_text,
    browser_capture_screenshot,
    browser_close_tab,
    desktop_click_coordinate,
    desktop_type_keys,
    desktop_launch_app,
    spawn_background_subagent,
    check_subagent_status,
    add_recurring_task,
    list_recurring_tasks,
    cancel_recurring_task,
    generate_pdf_report,
    pdf_merge_documents,
    pdf_split_document,
    pdf_extract_full_text,
    pdf_encrypt_password,
    pdf_decrypt_password,
    pdf_rotate_pages,
    pdf_apply_watermark_text,
    pdf_insert_page_numbers,
    pdf_convert_to_images,
    images_convert_to_pdf,
    upscale_image_hd,
    pdf_inspect_metadata,
    pdf_compress_and_optimize,
    affiliate_hunt_trending_products,
    affiliate_generate_viral_content,
    affiliate_broadcast_deal,
    affiliate_list_campaigns,
    scrape_real_product_data,
    scrape_large_scale_batch,
    marketplace_search_products,
    generate_promo_video_from_images,
    generate_excel_spreadsheet,
    generate_presentation_pptx,
    control_linux_hardware,
    send_file_to_chat,
    compress_folder_to_zip,
    record_desktop_screen,
    read_clipboard,
    manage_api_keys,
    manage_custom_agents,
    conduct_ai_meeting,
    query_token_usage,
    list_wa_drive_uploads,
    write_to_clipboard,
    show_desktop_notification,
    ssh_execute_command,
    query_database,
    send_email,
    list_running_processes,
    kill_process,
    edit_image,
    git_operations,
    translate_text,
    download_file_from_url,
    generate_secure_password,
    vision_click_target,
    auto_diagnose_and_heal_system,
    text_to_audio_file,
    convert_media_format,
    extract_audio_from_video,
    analyze_dataset_csv_json,
    audit_network_security,
    clean_system_storage,
    manage_system_services,
    manage_crontab_jobs,
    extract_and_link_knowledge,
    export_knowledge_base,
    start_focus_session,
    libreoffice_convert_document,
    libreoffice_render_page_previews,
    libreoffice_create_document,
    libreoffice_extract_document_text,
    proactive_ambient_agent_config,
    manage_wa_sheets_bot,
    open_web_dashboard,
    self_add_new_tool,
    list_dynamic_plugins,
    delete_dynamic_plugin,
    semantic_search_vector_brain,
    ingest_document_to_vector_brain,
    list_vector_brain_documents,
    self_restart_service,
    proactive_system_guardian_config,
    markitdown_convert_document,
    scrapling_stealth_fetch,
    scrapy_spider_quick_scrape,
    crawlee_web_scraper,
    crawl4ai_web_crawler,
    browser_use_autonomous_task,
    firecrawl_scrape_and_crawl,
    scrcpy_android_control,
    gdrive_status,
    gdrive_list_files,
    gdrive_upload_file,
    gdrive_download_file,
    gdrive_create_folder,
    gdrive_sync_to_second_brain,
    save_knowledge_memory,
    search_knowledge_memory,
    read_local_file,
    write_local_file,
    search_workspace_files,
    grep_workspace,
    edit_file_precise,
    apply_unified_diff,
    index_codebase,
    search_codebase,
    lsp_find_symbol_definition,
    lsp_find_symbol_references,
    lsp_analyze_module_hierarchy,
    git_worktree_sandbox_create,
    git_worktree_sandbox_verify_and_merge,
    git_worktree_sandbox_rollback,
    git_worktree_sandbox_list,
    browser_visual_test_page,
    academic_deep_research_paper,
    schedule_reminder,
    capture_desktop_screenshot,
    capture_webcam_frame,
    scan_local_network,
    *plugins.load_all_plugin_tools()
]


# Synchronize with registry.AVAILABLE_TOOLS
registry.AVAILABLE_TOOLS.clear()
registry.AVAILABLE_TOOLS.extend(AVAILABLE_TOOLS)


def __getattr__(name: str) -> Any:
    for mod in (
        system_tools,
        filesystem_tools,
        web_tools,
        desktop_tools,
        academic_tools,
        media_tools,
        memory_tools,
        registry,
    ):
        if hasattr(mod, name):
            return getattr(mod, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# Module subclass to propagate monkeypatching across all domain submodules
class _AlfaToolsModule(sys.modules[__name__].__class__):
    def __setattr__(self, name, value):
        super().__setattr__(name, value)
        for mod in (
            system_tools,
            filesystem_tools,
            web_tools,
            desktop_tools,
            academic_tools,
            media_tools,
            memory_tools,
            registry,
        ):
            if hasattr(mod, name):
                setattr(mod, name, value)


sys.modules[__name__].__class__ = _AlfaToolsModule

__all__ = [
    "registry",
    "system_tools",
    "filesystem_tools",
    "web_tools",
    "desktop_tools",
    "academic_tools",
    "media_tools",
    "memory_tools",
    "AVAILABLE_TOOLS",
    "current_chat_id_var",
    "current_user_id_var",
    "get_current_chat_id",
    "get_current_user_id",
    "SANDBOX_DIR",
    "normalize_path",
    "logger",
    "_bash_blocked_reason",
    "_docker_available",
    "_clean_code_snippet",
    "_ensure_sandbox_image",
    "_BASH_BLOCK_PATTERNS",
    "_RM_DANGER_TARGETS",
    "_sandbox_base",
    "_DOCKER_AVAILABLE_CACHE",
    "_SANDBOX_IMAGE",
    "_SOURCE_CODE_EXTS",
    "_MAX_EDIT_FILE_BYTES",
    "_CODE_INDEX_DB",
    "_CODE_INDEX_MAX_CHUNKS",
    "_CODE_CHUNK_LINES",
    "_CODE_INDEX_SKIP_DIRS",
    "_chunk_code_lines",
    "_code_index_connect",
    "_detect_gdrive_auth_mode",
    "_get_default_gdrive_folder_id",
    "_get_gdrive_service",
    "_index_freshness",
    "_index_one_file",
    "_iter_code_files",
    "_py_syntax_guard",
    "_resolve_host_path",
    "_ensure_camofox_server",
    "_find_camofox_bin",
    "_run_camofox_cli",
] + [name for name in dir() if not name.startswith("_")]
