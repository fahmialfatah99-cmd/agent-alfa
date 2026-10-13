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
        k in txt_low for k in ["code", "kode", "koding", "script", "python", "file"]
    ):
        required.update(
            [
                "read_local_file",
                "write_local_file",
                "edit_file_precise",
                "execute_python_sandbox",
            ]
        )
    return required
