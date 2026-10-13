"""Keyword tables, runtime config, and text utils for Tool-RAG."""

import logging
import os
import re
from typing import Any

logger = logging.getLogger("ToolRAG")

_ENABLED = os.getenv("ALFA_TOOL_RAG", "on").strip().lower() != "off"
try:
    TOP_K = max(4, int(os.getenv("ALFA_TOOL_RAG_TOPK", "14")))
except ValueError:
    TOP_K = 14

# Tool fondasi yang SELALU disuntikkan walau tak relevan dengan pesan.
CORE_ALWAYS: set[str] = {
    "execute_python_sandbox",
    "execute_bash_command",
    "read_local_file",
    "write_local_file",
    "web_search",
    "save_knowledge_memory",
    "search_knowledge_memory",
}

_STOPWORDS = {
    "yang",
    "dan",
    "atau",
    "di",
    "ke",
    "dari",
    "untuk",
    "dengan",
    "pada",
    "adalah",
    "itu",
    "ini",
    "the",
    "a",
    "an",
    "of",
    "to",
    "in",
    "on",
    "for",
    "with",
    "and",
    "or",
    "is",
    "are",
    "be",
    "please",
    "coba",
    "tolong",
    "buatkan",
    "bikin",
    "saya",
    "kamu",
    "dia",
    "mereka",
    "bagaimana",
    "apa",
    "kenapa",
    "gimana",
}

# Sinonim ID->EN dan istilah teknis operasional untuk menjembatani prompt
# pengguna bahasa Indonesia & Inggris dengan deskripsi tool teknis.
_SYNONYMS = {
    # System, Hardware & OS
    "screenshot": "capture desktop screenshot display monitor screen",
    "screnshoot": "capture desktop screenshot display monitor screen",
    "ss": "capture desktop screenshot display monitor screen",
    "rekam": "record screen video capture",
    "perekam": "record screen video",
    "layar": "screen desktop display monitor",
    "tangkap": "capture screenshot snapshot",
    "layanan": "service systemd daemon manage status restart",
    "servis": "service systemctl",
    "restart": "restart reboot service reload",
    "matikan": "stop kill shutdown terminate",
    "bunuh": "kill terminate process",
    "proses": "process running pid htop ps",
    "penjaga": "guardian proactive threshold health monitor heal",
    "terminal": "bash shell command cli execute exec",
    "perintah": "command bash execute cli",
    "jadwal": "cron crontab schedule reminder recurring timer",
    "pengingat": "reminder schedule notify alarm",
    "ingatkan": "reminder schedule notify alarm",
    "suhu": "hardware battery wifi bluetooth volume system",
    "bersih": "clean storage disk free space",
    "kapasitas": "storage disk df du usage",
    "jaringan": "network scan wifi ip port devices ping benchmark speedtest",
    "keamanan": "security audit password ssl vulnerability hash",
    "sandi": "password secure generate token credential",
    # Web, Scraper, & Browser
    "cari": "search web query duckduckgo find google",
    "telusuri": "search research explore web",
    "riset": "research academic paper deep search study",
    "unduh": "download fetch get file url",
    "ambil": "fetch scrape extract crawl download get",
    "ekstrak": "extract parse scrape convert text content",
    "ramping": "scrapling stealth scrape anti-bot bypass",
    "rayap": "crawler crawlee crawl4ai spider scrape",
    "jelajah": "browser open click type navigate visual",
    "otomatisasi": "browser_use autonomous robot task web",
    # Files, Documents & Code
    "berkas": "file local read write edit modify document",
    "baca": "read local file view cat head",
    "tulis": "write create save local file edit",
    "ubah": "edit replace precise modify patch diff",
    "folder": "directory workspace folder search list tree",
    "kode": "code index python script lsp symbol function",
    "koding": "code python execute sandbox program script",
    "git": "git commit push pull branch worktree diff status repository repo",
    "pustaka": "codebase search index grep symbol lsp",
    # Media, Audio, Video & Music
    "gambar": "image photo picture edit upscale crop rotate watermark",
    "foto": "image photo picture vision camera frame webcam",
    "video": "video promo youtube watch media play mp4 stream screen record extract",
    "suara": "voice audio speech sound tts edge mp3 volume synthesize speech",
    "audio": "audio voice sound speech music song mp3 stream play media",
    "lagu": "song music audio track mp3 sound media spotify youtube play stream",
    "musik": "music song audio sound track spotify youtube media play stream",
    "youtube": "youtube video audio music play stream media browser open url desktop launch app watch",
    "yt": "youtube video play stream music media watch",
    "spotify": "spotify music song audio play track media desktop launch app",
    "tonton": "watch video youtube movie play stream browser",
    "nyalakan": "play start launch open enable power turn on",
    "setel": "play set configure tune music video volume audio",
    "putar": "play media song video audio music track stream rotate angle",
    "aplikasi": "application app software desktop launch run start program",
    "browser": "browser brave chrome firefox web internet navigate open url",
    "dokumen": "document pdf docx odt writer libreoffice markitdown text",
    "presentasi": "presentation pptx powerpoint slides impress",
    "tabel": "excel spreadsheet xlsx csv dataset analyze chart data",
    # PDF Specific Operations
    "pdf": "pdf merge split extract encrypt decrypt rotate watermark report compress",
    "gabung": "merge combine pdf documents",
    "pisah": "split divide extract page range",
    "kunci": "encrypt password protect secure pdf vault",
    "buka": "open launch browser desktop app url website window document file start view",
    "dekripsi": "decrypt unlock password open protected",
    "rotasi": "rotate angle pdf page orientation",
    # Memory, Brain & Agents
    "ingat": "memory remember save knowledge fact store",
    "simpan": "save store write memory ingest vector vault secret",
    "vektor": "vector brain semantic embedding ingest search similarity rag",
    "rapat": "meeting swarm conduct agents discussion debate consensus",
    "agen": "agent custom swarm subagent background workforce",
    "rahasia": "vault secret encrypt reveal token api key passkey",
    "kunci_api": "api_keys manage provider activate validate gemini groq",
    "afiliasi": "affiliate trending viral copywriting broadcast shopee tokped",
    "kirim": "send deliver broadcast telegram chat email message",
    "terjemah": "translate translation language convert text",
    "fokus": "focus session pomodoro timer work",
    "download": "download fetch save file url",
}

# Domain Category Keywords untuk Intent Boosting
_CATEGORY_BOOSTS = {
    "pdf": [
        "generate_pdf_report",
        "pdf_merge_documents",
        "pdf_split_document",
        "pdf_extract_full_text",
        "pdf_encrypt_password",
        "pdf_decrypt_password",
        "pdf_rotate_pages",
        "images_convert_to_pdf",
        "pdf_apply_watermark_text",
        "pdf_compress_and_optimize",
    ],
    "system": [
        "get_system_stats",
        "execute_bash_command",
        "manage_system_services",
        "list_running_processes",
        "kill_process",
        "clean_system_storage",
        "auto_diagnose_and_heal_system",
        "manage_crontab_jobs",
    ],
    "code": [
        "execute_python_sandbox",
        "read_local_file",
        "write_local_file",
        "edit_file_precise",
        "search_codebase",
        "index_codebase",
        "git_operations",
        "grep_workspace",
    ],
    "web": [
        "web_search",
        "fetch_web_page_content",
        "deep_research_topic",
        "browser_open_url",
        "scrapling_stealth_fetch",
        "crawl4ai_web_crawler",
        "universal_deep_scraper",
    ],
    "media": [
        "desktop_launch_app",
        "control_linux_hardware",
        "browser_open_url",
        "play_youtube_music",
        "open_url_in_system_browser",
        "edit_image",
        "text_to_audio_file",
        "extract_audio_from_video",
        "convert_media_format",
        "generate_promo_video_from_images",
        "analyze_dataset_csv_json",
        "record_desktop_screen",
    ],
    "desktop": [
        "desktop_launch_app",
        "control_linux_hardware",
        "browser_open_url",
        "browser_click_element",
        "browser_type_text",
        "browser_capture_screenshot",
        "capture_desktop_screenshot",
        "open_url_in_system_browser",
        "play_youtube_music",
        "record_desktop_screen",
        "show_desktop_notification",
        "desktop_type_keys",
        "desktop_click_coordinate",
        "vision_click_target",
    ],
    "memory": [
        "save_knowledge_memory",
        "search_knowledge_memory",
        "semantic_search_vector_brain",
        "ingest_document_to_vector_brain",
        "list_vector_brain_documents",
        "export_knowledge_base",
    ],
    "agent": [
        "spawn_background_subagent",
        "check_subagent_status",
        "conduct_ai_meeting",
        "manage_custom_agents",
    ],
}

_CATEGORY_TRIGGERS = {
    "pdf": {"pdf", "dokumen_pdf"},
    "system": {"system", "hardware", "service", "proses", "layanan", "server", "linux"},
    "code": {"code", "kode", "koding", "script", "program", "git", "repo", "python"},
    "web": {
        "web",
        "search",
        "cari",
        "browse",
        "scrape",
        "crawler",
        "internet",
        "link",
        "url",
    },
    "media": {
        "media",
        "lagu",
        "musik",
        "music",
        "song",
        "audio",
        "video",
        "youtube",
        "yt",
        "spotify",
        "sound",
        "suara",
        "mp3",
        "mp4",
        "player",
        "stream",
        "tonton",
        "putar",
        "play",
        "setel",
        "nyalakan",
    },
    "desktop": {
        "desktop",
        "aplikasi",
        "app",
        "browser",
        "brave",
        "chrome",
        "firefox",
        "buka",
        "open",
        "launch",
        "layar",
        "screen",
        "screenshot",
        "window",
        "youtube",
        "spotify",
        "putar",
        "play",
        "notifikasi",
        "klik",
        "click",
    },
    "memory": {"memory", "ingat", "catat", "simpan", "vektor", "knowledge"},
    "agent": {"agent", "agen", "swarm", "rapat", "subagent", "workforce"},
}

_ACTION_TRIGGERS = {
    "buat",
    "bikin",
    "tulis",
    "cari",
    "search",
    "googling",
    "browse",
    "web",
    "scrape",
    "jalankan",
    "run",
    "eksekusi",
    "hitung",
    "baca",
    "cek",
    "analisis",
    "pdf",
    "excel",
    "gambar",
    "foto",
    "drive",
    "email",
    "rapat",
    "meeting",
    "jadwal",
    "ingat",
    "catat",
    "simpan",
    "hapus",
    "file",
    "folder",
    "kode",
    "code",
    "python",
    "bash",
    "curl",
    "swarm",
    "screenshot",
    "screnshoot",
    "ss",
    "layar",
    "desktop",
    "tangkap",
    "capture",
    "kamera",
    "webcam",
    "putar",
    "play",
    "setel",
    "nyalakan",
    "lagu",
    "musik",
    "music",
    "song",
    "youtube",
    "yt",
    "spotify",
    "video",
    "audio",
    "suara",
    "buka",
    "open",
    "launch",
    "tonton",
    "watch",
    "volume",
    "notifikasi",
    "aplikasi",
    "app",
    "unduh",
    "download",
    "perintah",
    "terminal",
    "kirim",
}


def _tokenize(text: str) -> list[str]:
    toks = re.findall(r"[a-zA-Z_][a-zA-Z0-9_]{1,}", (text or "").lower())
    out: list[str] = []
    for t in toks:
        # pecahkan snake_case agar 'record_desktop_screen' cocok dgn 'screen'
        parts = t.split("_") if "_" in t else [t]
        out.extend(p for p in parts if p not in _STOPWORDS)
    return out


def _expand_synonyms(tokens: list[str]) -> list[str]:
    """Suntikkan padanan EN ke query agar cocok dg dokumen tool berbahasa Inggris."""
    out = list(tokens)
    for t in tokens:
        extra = _SYNONYMS.get(t)
        if extra:
            out.extend(extra.split())
    return out


def _schema_to_text(schema: dict[str, Any]) -> str:
    """Gabungkan nama + deskripsi + nama argumen jadi satu dokumen indeks."""
    try:
        fn = schema.get("function", {}) or {}
        parts = [fn.get("name", "")]
        desc = fn.get("description", "") or ""
        parts.append(desc[:600])
        params = (fn.get("parameters") or {}).get("properties") or {}
        parts.extend(params.keys())
        return " ".join(str(p) for p in parts)
    except Exception:
        return ""
