"""Action-intent detection: mandatory tool families for action requests."""

from alfa.tools.rag.keywords import _ACTION_TRIGGERS


def is_action_request(user_text: str) -> bool:
    if not user_text:
        return False
    txt_low = user_text.lower().strip()
    return any(k in txt_low for k in _ACTION_TRIGGERS)


# Tool yang hanya berguna BERSAMA tool lain. Tanpa ekspansi ini, model memilih
# browser_open_url tapi kehilangan browser_click_element/type -> membuka halaman
# lalu buntu karena tool klik tidak pernah disuntikkan ke LLM.
_TOOL_FAMILIES: dict[str, set[str]] = {
    "browser_open_url": {
        "browser_click_element",
        "browser_type_text",
        "browser_capture_screenshot",
        "browser_close_tab",
    },
    "browser_click_element": {
        "browser_open_url",
        "browser_type_text",
        "browser_capture_screenshot",
    },
    "browser_type_text": {
        "browser_open_url",
        "browser_click_element",
        "browser_capture_screenshot",
    },
    "browser_use_autonomous_task": {
        "browser_open_url",
        "browser_click_element",
        "browser_capture_screenshot",
    },
    "desktop_launch_app": {
        "capture_desktop_screenshot",
        "desktop_click_coordinate",
        "desktop_type_keys",
        "vision_click_target",
        "open_url_in_system_browser",
    },
    "desktop_click_coordinate": {
        "capture_desktop_screenshot",
        "vision_click_target",
        "desktop_type_keys",
    },
    "vision_click_target": {
        "capture_desktop_screenshot",
        "desktop_click_coordinate",
        "desktop_type_keys",
    },
    "desktop_type_keys": {
        "capture_desktop_screenshot",
        "desktop_click_coordinate",
        "vision_click_target",
    },
    "open_url_in_system_browser": {
        "play_youtube_music",
        "desktop_launch_app",
        "capture_desktop_screenshot",
    },
    "play_youtube_music": {
        "open_url_in_system_browser",
        "control_linux_hardware",
        "desktop_launch_app",
    },
    "control_linux_hardware": {
        "play_youtube_music",
        "capture_desktop_screenshot",
    },
    "images_convert_to_pdf": {
        "find_user_files",
        "pdf_merge_documents",
        "pdf_split_document",
        "pdf_compress_and_optimize",
    },
    "convert_media_format": {
        "find_user_files",
        "execute_bash_command",
    },
    "generate_excel_spreadsheet": {
        "analyze_dataset_csv_json",
        "read_local_file",
        "write_local_file",
    },
    "wa_get_chats": {
        "wa_get_messages",
        "wa_send_message",
        "wa_get_incoming",
    },
    "wa_get_messages": {
        "wa_get_chats",
        "wa_send_message",
    },
    "wa_send_message": {
        "wa_get_chats",
        "wa_get_messages",
    },
    "rea_inspect_android_package": {
        "rea_synthesize_skill_from_code",
        "rea_clone_and_build_app",
        "apex_software_factory_build",
        "serve_site",
    },
    "rea_recover_js_sources": {
        "rea_inspect_js_app",
        "rea_synthesize_skill_from_code",
        "rea_clone_and_build_app",
        "apex_software_factory_build",
        "serve_site",
    },
    "rea_synthesize_skill_from_code": {
        "rea_clone_and_build_app",
        "apex_software_factory_build",
        "serve_site",
        "record_agent_experience",
    },
    "rea_clone_and_build_app": {
        "apex_software_factory_build",
        "serve_site",
        "list_managed_sites",
    },
    "apex_software_factory_build": {
        "apex_repo_architect_build",
        "rea_clone_and_build_app",
        "serve_site",
        "list_managed_sites",
        "browser_visual_test_page",
    },
    "apex_repo_architect_build": {
        "generate_codebase_repomap",
        "lsp_find_symbol_definition",
        "lsp_find_symbol_references",
        "git_worktree_sandbox_create",
        "git_worktree_sandbox_verify_and_merge",
        "git_worktree_sandbox_rollback",
        "serve_site",
    },
    "generate_codebase_repomap": {
        "lsp_find_symbol_definition",
        "lsp_find_symbol_references",
        "lsp_analyze_module_hierarchy",
        "apex_repo_architect_build",
        "edit_file_precise",
    },
    "lsp_find_symbol_definition": {
        "lsp_find_symbol_references",
        "lsp_analyze_module_hierarchy",
        "generate_codebase_repomap",
        "edit_file_precise",
    },
    "git_worktree_sandbox_create": {
        "git_worktree_sandbox_verify_and_merge",
        "git_worktree_sandbox_rollback",
        "git_worktree_sandbox_list",
    },
    "apex_computer_use_action": {
        "capture_desktop_screenshot",
        "desktop_click_coordinate",
        "desktop_type_keys",
    },
}


def _expand_families(selected: set[str], available: set[str]) -> set[str]:
    """Tambahkan tool pendamping dari keluarga yang sama (hanya yang tersedia)."""
    out = set(selected)
    for name in list(selected):
        out |= _TOOL_FAMILIES.get(name, set())
    return {n for n in out if n in available}


def get_required_action_tools(user_text: str) -> set[str]:
    if not user_text:
        return set()
    txt_low = user_text.lower().strip()
    required = set()
    if any(
        k in txt_low
        for k in [
            "youtube",
            "yt",
            "spotify",
            "lagu",
            "musik",
            "music",
            "song",
            "putar",
            "play",
            "setel",
            "tonton",
            "video",
            "aplikasi",
            "app",
            "buka",
            "launch",
        ]
    ):
        required.update(
            [
                "discord_play_music",
                "play_youtube_music",
                "open_url_in_system_browser",
                "desktop_launch_app",
                "control_linux_hardware",
                "browser_open_url",
                "browser_click_element",
                "browser_type_text",
                "capture_desktop_screenshot",
                "desktop_click_coordinate",
                "desktop_type_keys",
                "vision_click_target",
                "web_search",
                "execute_bash_command",
            ]
        )
    if any(
        k in txt_low
        for k in [
            "pdf",
            "dokumen",
            "laporan",
            "convert",
            "ubah",
            "gambar",
            "foto",
            "satukan",
            "gabung",
        ]
    ):
        required.update(
            [
                "generate_pdf_report",
                "images_convert_to_pdf",
                "pdf_merge_documents",
                "pdf_split_document",
                "pdf_extract_full_text",
                "pdf_convert_to_images",
                "pdf_compress_and_optimize",
                "find_user_files",
            ]
        )
    if any(
        k in txt_low for k in ["excel", "xlsx", "csv", "spreadsheet", "tabel", "data"]
    ):
        required.update(
            [
                "generate_excel_spreadsheet",
                "analyze_dataset_csv_json",
                "read_local_file",
            ]
        )
    if any(
        k in txt_low
        for k in ["konversi", "convert", "format", "mp4", "mp3", "wav", "m4a"]
    ):
        required.update(
            [
                "convert_media_format",
                "libreoffice_convert_document",
                "markitdown_convert_document",
                "find_user_files",
            ]
        )
    if any(
        k in txt_low for k in ["code", "kode", "koding", "script", "python", "file", "repo", "repositori", "refactor", "arsitektur", "bug", "sandbox", "worktree", "lsp", "repomap"]
    ):
        required.update(
            [
                "read_local_file",
                "write_local_file",
                "edit_file_precise",
                "execute_python_sandbox",
                "generate_codebase_repomap",
                "lsp_find_symbol_definition",
                "lsp_find_symbol_references",
                "lsp_analyze_module_hierarchy",
                "git_worktree_sandbox_create",
                "git_worktree_sandbox_verify_and_merge",
                "git_worktree_sandbox_rollback",
                "apex_repo_architect_build",
            ]
        )
    if any(
        k in txt_low for k in ["wa", "whatsapp", "washeets", "waringkas", "pesan wa", "chat wa"]
    ):
        required.update(
            [
                "wa_get_chats",
                "wa_get_messages",
                "wa_get_incoming",
                "wa_send_message",
                "wa_get_records",
            ]
        )
    if any(
        k in txt_low
        for k in ["rea", "bedah", "decompile", "reverse", "apk", "asar", "adb", "wasm", "binary"]
    ):
        required.update(
            [
                "rea_inspect_android_package",
                "rea_inspect_js_app",
                "rea_recover_js_sources",
                "rea_inspect_sqlite_database",
                "rea_inspect_binary_or_wasm",
                "rea_android_device_control",
                "rea_synthesize_skill_from_code",
                "rea_clone_and_build_app",
                "apex_software_factory_build",
                "serve_site",
            ]
        )
    if any(
        k in txt_low
        for k in ["buat aplikasi", "bikin aplikasi", "buatkan aplikasi", "buat web", "bikin web", "situs", "/sites", "fullstack", "web app"]
    ):
        required.update(
            [
                "apex_software_factory_build",
                "rea_clone_and_build_app",
                "serve_site",
                "list_managed_sites",
            ]
        )
    if any(
        k in txt_low
        for k in ["klik", "kursor", "cursor", "coordinate", "grid", "computer use", "layar"]
    ):
        required.update(
            [
                "apex_computer_use_action",
                "capture_desktop_screenshot",
                "desktop_click_coordinate",
                "desktop_type_keys",
            ]
        )
    if any(
        k in txt_low
        for k in ["graphrag", "hubungan", "relasi", "aturan", "skill", "belajar", "koreksi"]
    ):
        required.update(
            [
                "apex_temporal_graphrag_query",
                "query_learned_skills",
                "record_agent_experience",
            ]
        )
    return required
