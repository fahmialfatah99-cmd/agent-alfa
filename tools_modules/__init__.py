"""Tools Modules - Categorized tool collections for ALFA Agent."""

# System & Infrastructure Tools
from .system_tools import (
    get_system_stats,
    execute_bash_command,
    execute_python_sandbox,
)

# Web & Research Tools  
from .web_tools import (
    web_search,
    fetch_web_page_content,
    deep_research_topic,
)

# File & Workspace Tools
from .file_tools import (
    read_local_file,
    write_local_file,
    edit_file_precise,
    search_workspace_files,
    grep_workspace,
)

# Memory & Knowledge Tools
from .memory_tools import (
    save_knowledge_memory,
    search_knowledge_memory,
    extract_and_link_knowledge,
    export_knowledge_base,
)

# Browser & Automation Tools
from .browser_tools import (
    browser_open_url,
    browser_click_element,
    browser_type_text,
    browser_capture_screenshot,
    browser_close_tab,
)

# Vision & Media Tools
from .vision_tools import (
    capture_desktop_screenshot,
    capture_webcam_frame,
    text_to_audio_file,
    convert_media_format,
)

# Data Analysis Tools
from .data_tools import (
    analyze_dataset_csv_json,
)

# Security & Audit Tools
from .security_tools import (
    audit_network_security,
    audit_website_security,
)

# Swarm & Multi-Agent Tools
from .swarm_tools import (
    spawn_background_subagent,
    check_subagent_status,
    conduct_ai_meeting,
)

__all__ = [
    # System
    "get_system_stats",
    "execute_bash_command",
    "execute_python_sandbox",
    # Web
    "web_search",
    "fetch_web_page_content",
    "deep_research_topic",
    # File
    "read_local_file",
    "write_local_file",
    "edit_file_precise",
    "search_workspace_files",
    "grep_workspace",
    # Memory
    "save_knowledge_memory",
    "search_knowledge_memory",
    "extract_and_link_knowledge",
    "export_knowledge_base",
    # Browser
    "browser_open_url",
    "browser_click_element",
    "browser_type_text",
    "browser_capture_screenshot",
    "browser_close_tab",
    # Vision
    "capture_desktop_screenshot",
    "capture_webcam_frame",
    "text_to_audio_file",
    "convert_media_format",
    # Data
    "analyze_dataset_csv_json",
    # Security
    "audit_network_security",
    "audit_website_security",
    # Swarm
    "spawn_background_subagent",
    "check_subagent_status",
    "conduct_ai_meeting",
]
