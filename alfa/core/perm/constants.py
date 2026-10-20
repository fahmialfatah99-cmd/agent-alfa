"""Permission gate constants, risk tiers, and classification registry."""

import logging
import os
from enum import Enum

logger = logging.getLogger("PermissionGate")

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

PROJECT_DIR = REPO_ROOT
DB_PATH = os.getenv("ALFA_DB_PATH", os.path.join(PROJECT_DIR, "agent_data.db"))

PERMISSION_GATE_ENABLED = (
    os.getenv("PERMISSION_GATE", "on").strip().lower() != "off"
    and os.getenv("ALFA_UNRESTRICTED", "false").strip().lower() != "true"
)

# Policy izin:
# "true" (default): Izin interaktif hanya diminta untuk perintah berisiko berbahaya (HIGH & CRITICAL).
#                   Tool membaca dokumen/berkas (read_local_file, markitdown, pdf, excel, dll)
#                   serta operasi MEDIUM/LOW lainnya di-auto-approve otomatis sehingga tidak
#                   merepotkan pengguna dengan konfirmasi satu per satu.
# "false": Mode ketat — semua tool non-LOW (termasuk MEDIUM) membutuhkan akumulasi persetujuan
#          eksplisit manusia & trust score sebelum di-auto-approve.
PERMISSION_GATE_DANGEROUS_ONLY = (
    os.getenv("PERMISSION_GATE_DANGEROUS_ONLY", "true").strip().lower()
    in ("true", "1", "yes")
)


def _safe_int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)).strip())
    except (TypeError, ValueError, AttributeError):
        logger.warning(f"Env {name} tidak valid; pakai default {default}")
        return default


def _safe_float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)).strip())
    except (TypeError, ValueError, AttributeError):
        logger.warning(f"Env {name} tidak valid; pakai default {default}")
        return default


APPROVAL_TIMEOUT = _safe_int_env("PERMISSION_GATE_TIMEOUT", 300)
TRUST_THRESHOLD = _safe_float_env("PERMISSION_GATE_TRUST_THRESHOLD", 0.7)
# Ambang trust untuk tier HIGH/CRITICAL — jauh lebih tinggi dari MEDIUM.
HIGH_TRUST_THRESHOLD = _safe_float_env("PERMISSION_GATE_HIGH_TRUST_THRESHOLD", 0.9)
FAIL_MODE = os.getenv("PERMISSION_GATE_FAIL_MODE", "deny").strip().lower()
# Perilaku saat TIDAK ada kanal approval (mis. Web Dashboard tanpa bot Telegram
# berjalan). Sebelumnya selalu fail-closed -> SEMUA tool non-SAFE ditolak sehingga
# agent di dashboard tidak pernah bisa bergerak sama sekali.
#   allow_low_medium : tool LOW & MEDIUM tetap jalan, HIGH/CRITICAL tetap ditolak
#   allow_all        : semua tool diizinkan bila tak ada kanal
#   deny             : perilaku lama (fail-closed penuh)
NO_CHANNEL_POLICY = (
    os.getenv("PERMISSION_GATE_NO_CHANNEL", "allow_low_medium").strip().lower()
)


# ── Klasifikasi Tool dengan Risk Tiers ─────────────────────────────────────────
class RiskTier(Enum):
    LOW = "low"  # Read-only, reversible
    MEDIUM = "medium"  # Write operations, moderate impact
    HIGH = "high"  # System changes, potentially destructive
    CRITICAL = "critical"  # Irreversible, security-sensitive


# Minimum JUMLAH persetujuan eksplisit manusia per tier sebelum tool pada tier
# tersebut boleh di-auto-approve. Trust tidak lagi global: skor dihitung per
# (chat_id, tier) sehingga persetujuan tool LOW tidak pernah membuka tool
# HIGH/CRITICAL. Lihat ``store.update_tier_trust``.
TIER_MIN_EXPLICIT_APPROVALS = {
    RiskTier.LOW: 0,
    RiskTier.MEDIUM: _safe_int_env("PERMISSION_GATE_MIN_APPROVALS_MEDIUM", 3),
    RiskTier.HIGH: _safe_int_env("PERMISSION_GATE_MIN_APPROVALS_HIGH", 5),
    RiskTier.CRITICAL: _safe_int_env("PERMISSION_GATE_MIN_APPROVALS_CRITICAL", 5),
}

# Tool classification dengan risk tier dan deskripsi.
#
# PENTING: seluruh tool yang terdaftar di registry wajib punya entri di sini.
# ``DEFAULT_TIER`` sengaja diset ke HIGH (fail-closed) supaya tool baru yang belum
# terklasifikasi TIDAK otomatis lolos sebagai MEDIUM.
TOOL_CLASSIFICATION = {
    # ── CRITICAL - irreversible, security-critical ──────────────────────────
    "ssh_execute_command": (
        RiskTier.CRITICAL,
        "Akses SSH remote - risiko keamanan tinggi",
    ),
    "manage_crontab_jobs": (
        RiskTier.CRITICAL,
        "Modifikasi scheduled tasks - dampak sistem luas",
    ),
    "clean_system_storage": (
        RiskTier.CRITICAL,
        "Penghapusan massal file - irreversible",
    ),
    "control_linux_hardware": (
        RiskTier.CRITICAL,
        "Kontrol hardware langsung - risiko damage",
    ),
    "vault_delete_secret": (
        RiskTier.CRITICAL,
        "Hapus secret dari vault terenkripsi - irreversible, kehilangan kredensial",
    ),
    "discord_play_music": (
        RiskTier.MEDIUM,
        "Putar musik di voice channel Discord - memakai speaker & jaringan",
    ),
    # ── HIGH - system changes, potentially destructive ──────────────────────
    "kill_process": (RiskTier.HIGH, "Terminasi process - bisa crash sistem"),
    "execute_bash_command": (
        RiskTier.HIGH,
        "Eksekusi command shell - dampak bervariasi",
    ),
    "execute_python_sandbox": (
        RiskTier.HIGH,
        "Eksekusi Python arbitrer - bisa membaca/menulis file host bila sandbox kosong",
    ),
    "write_local_file": (
        RiskTier.HIGH,
        "Write file arbitrary - bisa overwrite penting",
    ),
    "edit_file_precise": (RiskTier.HIGH, "Edit file presisi - risiko corrupt data"),
    "apply_unified_diff": (RiskTier.HIGH, "Patch file - bisa break code"),
    "manage_system_services": (RiskTier.HIGH, "Start/stop services - downtime risk"),
    "query_database": (RiskTier.HIGH, "Query SQL - bisa DROP/DELETE"),
    "git_operations": (RiskTier.HIGH, "Git ops - bisa lose commits"),
    "download_file_from_url": (RiskTier.HIGH, "Download external - malware risk"),
    "vault_get_secret": (
        RiskTier.HIGH,
        "Baca secret terenkripsi - Nilainya masuk konteks model (risiko eksfiltrasi)",
    ),
    "vault_store_secret": (
        RiskTier.HIGH,
        "Simpan secret terenkripsi - menulis kredensial ke vault",
    ),
    "manage_api_keys": (RiskTier.HIGH, "Kelola API key vault - akses kredensial"),
    "self_add_new_tool": (
        RiskTier.HIGH,
        "Daftarkan tool Python baru saat runtime - membuat kode eksekutable",
    ),
    "skill_installer": (RiskTier.HIGH, "Pasang skill/plugin eksternal - risiko supply chain"),
    "mcp_connect": (RiskTier.HIGH, "Koneksi ke MCP server - menambah attack surface"),
    "mcp_call": (RiskTier.HIGH, "Panggil tool MCP server - bisa efek samping"),
    "git_worktree_sandbox_create": (RiskTier.HIGH, "Buat git worktree - tulis ke disk"),
    "git_worktree_sandbox_rollback": (RiskTier.HIGH, "Rollback worktree - bisa lose work"),
    "git_worktree_sandbox_verify_and_merge": (
        RiskTier.HIGH,
        "Merge worktree ke branch utama - bisa merusak repo",
    ),
    "affiliate_broadcast_deal": (
        RiskTier.HIGH,
        "Broadcast promosi ke kanal eksternal - mengirim pesan tanpa izin pemilik",
    ),
    "delete_dynamic_plugin": (RiskTier.HIGH, "Hapus plugin dinamis - modifikasi instalasi"),
    # ── MEDIUM - write operations / reads of sensitive-but-benign data ──────
    "read_local_file": (
        RiskTier.MEDIUM,
        "Baca file lokal - bisa membocorkan .env / private key ke konteks model",
    ),
    "read_clipboard": (RiskTier.MEDIUM, "Baca clipboard - bisa berisi password"),
    "record_desktop_screen": (RiskTier.MEDIUM, "Screen recording - privacy concern"),
    "capture_webcam_frame": (RiskTier.MEDIUM, "Webcam capture - privacy sensitive"),
    "scan_local_network": (RiskTier.MEDIUM, "Network scan - firewall trigger"),
    "desktop_click_coordinate": (RiskTier.MEDIUM, "Automasi klik - unintended actions"),
    "desktop_type_keys": (RiskTier.MEDIUM, "Automasi keyboard - unintended input"),
    "desktop_launch_app": (RiskTier.MEDIUM, "Launch aplikasi - resource usage"),
    "browser_click_element": (RiskTier.MEDIUM, "Interaksi browser - aksi di situs"),
    "browser_type_text": (RiskTier.MEDIUM, "Input teks browser - submit form"),
    "browser_use_autonomous_task": (
        RiskTier.MEDIUM,
        "Browser agent otonom multi-langkah - bisa submit form tak sengaja",
    ),
    "vision_click_target": (RiskTier.MEDIUM, "Visual automation - misclick risk"),
    "schedule_reminder": (RiskTier.MEDIUM, "Buat pengingat terjadwal - tulis ke store"),
    "add_recurring_task": (RiskTier.MEDIUM, "Buat tugas berulang - writes ke store"),
    "cancel_recurring_task": (RiskTier.MEDIUM, "Batalkan tugas berulang"),
    "conduct_ai_meeting": (RiskTier.MEDIUM, "Jalankan rapat multi-agent - boros biaya"),
    "spawn_background_subagent": (RiskTier.MEDIUM, "Jalankan subagent latar - boros biaya"),
    "self_restart_service": (RiskTier.MEDIUM, "Restart service - downtime singkat"),
    "serve_site": (RiskTier.MEDIUM, "Jalankan web server lokal - membuka port"),
    "send_email": (RiskTier.MEDIUM, "Kirim email - berkirim atas nama pengguna"),
    "send_file_to_chat": (RiskTier.MEDIUM, "Kirim file ke chat - membocorkan file"),
    "write_to_clipboard": (RiskTier.MEDIUM, "Tulis clipboard - bisa menimpa data"),
    "start_focus_session": (RiskTier.MEDIUM, "Mode fokus - ubah state aplikasi"),
    "manage_custom_agents": (RiskTier.MEDIUM, "Kelola definisi custom agent"),
    "proactive_ambient_agent_config": (RiskTier.MEDIUM, "Ubah konfigurasi ambient agent"),
    "proactive_system_guardian_config": (RiskTier.MEDIUM, "Ubah konfigurasi guardian"),
    "manage_wa_sheets_bot": (RiskTier.MEDIUM, "Kelola bot WhatsApp sheet"),
    "affiliate_generate_viral_content": (RiskTier.MEDIUM, "Generate konten promosi"),
    "affiliate_hunt_trending_products": (RiskTier.MEDIUM, "Cari produk tren"),
    "affiliate_list_campaigns": (RiskTier.MEDIUM, "Daftar kampanye promosi"),
    "marketplace_search_products": (RiskTier.MEDIUM, "Cari produk marketplace"),
    "analyze_dataset_csv_json": (RiskTier.MEDIUM, "Analisis dataset - baca data user"),
    "extract_and_link_knowledge": (RiskTier.MEDIUM, "Ekstrak & tautkan pengetahuan"),
    "ingest_document_to_vector_brain": (RiskTier.MEDIUM, "Ingest dokumen ke memori"),
    "export_knowledge_base": (RiskTier.MEDIUM, "Ekspor basis pengetahuan"),
    "vault_list_secrets": (RiskTier.MEDIUM, "Daftar nama secret - bocorkan inventaris"),
    "gdrive_create_folder": (RiskTier.MEDIUM, "Buat folder di Google Drive"),
    "gdrive_upload_file": (RiskTier.MEDIUM, "Upload file ke Google Drive"),
    "gdrive_download_file": (RiskTier.MEDIUM, "Download file dari Google Drive"),
    "gdrive_sync_to_second_brain": (RiskTier.MEDIUM, "Sinkron Drive ke memori RAG"),
    "convert_media_format": (RiskTier.MEDIUM, "Konversi format media"),
    "compress_folder_to_zip": (RiskTier.MEDIUM, "Kompres folder - baca isi folder"),
    "edit_image": (RiskTier.MEDIUM, "Edit gambar - tulis file"),
    "upscale_image_hd": (RiskTier.MEDIUM, "Upscale gambar - tulis file"),
    "extract_audio_from_video": (RiskTier.MEDIUM, "Ekstrak audio dari video"),
    "generate_excel_spreadsheet": (RiskTier.MEDIUM, "Buat file spreadsheet"),
    "generate_pdf_report": (RiskTier.MEDIUM, "Buat file PDF"),
    "generate_presentation_pptx": (RiskTier.MEDIUM, "Buat file presentasi"),
    "generate_promo_video_from_images": (RiskTier.MEDIUM, "Buat video promosi"),
    "images_convert_to_pdf": (RiskTier.MEDIUM, "Konversi gambar ke PDF"),
    "libreoffice_convert_document": (RiskTier.MEDIUM, "Konversi dokumen via LibreOffice"),
    "libreoffice_create_document": (RiskTier.MEDIUM, "Buat dokumen via LibreOffice"),
    "libreoffice_extract_document_text": (RiskTier.MEDIUM, "Ekstrak teks dokumen"),
    "libreoffice_render_page_previews": (RiskTier.MEDIUM, "Render preview dokumen"),
    "markitdown_convert_document": (RiskTier.MEDIUM, "Konversi dokumen ke Markdown"),
    "pdf_apply_watermark_text": (RiskTier.MEDIUM, "Beri watermark PDF - tulis file"),
    "pdf_compress_and_optimize": (RiskTier.MEDIUM, "Kompres PDF - tulis file"),
    "pdf_convert_to_images": (RiskTier.MEDIUM, "Konversi PDF ke gambar"),
    "pdf_decrypt_password": (RiskTier.MEDIUM, "Buka PDF terenkripsi"),
    "pdf_encrypt_password": (RiskTier.MEDIUM, "Enkripsi PDF - tulis file"),
    "pdf_insert_page_numbers": (RiskTier.MEDIUM, "Sisip nomor halaman PDF"),
    "pdf_merge_documents": (RiskTier.MEDIUM, "Gabung PDF - tulis file"),
    "pdf_rotate_pages": (RiskTier.MEDIUM, "Putar halaman PDF - tulis file"),
    "pdf_split_document": (RiskTier.MEDIUM, "Pisah PDF - tulis file"),
    "text_to_audio_file": (RiskTier.MEDIUM, "TTS ke file audio - tulis file"),
    "speedtest_network_benchmark": (RiskTier.MEDIUM, "Benchmark jaringan - traffic keluar"),
    "universal_deep_scraper": (RiskTier.MEDIUM, "Scraper universal - traffic keluar"),
    "scrape_custom_urls_batch": (RiskTier.MEDIUM, "Scrape batch URL - traffic keluar"),
    "scrape_large_scale_batch": (RiskTier.MEDIUM, "Scrape skala besar - traffic keluar"),
    "scrape_real_product_data": (RiskTier.MEDIUM, "Scrape data produk"),
    "scrapling_stealth_fetch": (RiskTier.MEDIUM, "Fetch stealth - traffic keluar"),
    "scrapy_spider_quick_scrape": (RiskTier.MEDIUM, "Scrapy quick scrape"),
    "crawl4ai_web_crawler": (RiskTier.MEDIUM, "Crawl4AI crawl - traffic keluar"),
    "crawlee_web_scraper": (RiskTier.MEDIUM, "Crawlee scraper - traffic keluar"),
    "firecrawl_scrape_and_crawl": (RiskTier.MEDIUM, "Firecrawl scrape - traffic keluar"),
    "scrcpy_android_control": (RiskTier.MEDIUM, "Kontrol Android via scrcpy"),
    "wa_send_message": (RiskTier.MEDIUM, "Kirim pesan WhatsApp - kirim atas nama user"),
    "wa_add_format": (RiskTier.MEDIUM, "Tambah format WA"),
    "wa_delete_format": (RiskTier.MEDIUM, "Hapus format WA"),
    "wa_toggle_format": (RiskTier.MEDIUM, "Toggle format WA"),
    # ── LOW - read-only, safe operations ───────────────────────────────────
    "wa_get_chats": (RiskTier.LOW, "Baca daftar chat WA - read-only"),
    "wa_get_incoming": (RiskTier.LOW, "Baca pesan masuk WA - read-only"),
    "wa_get_me": (RiskTier.LOW, "Baca profil WA - read-only"),
    "wa_get_messages": (RiskTier.LOW, "Baca pesan WA - read-only"),
    "wa_get_records": (RiskTier.LOW, "Baca riwayat panggilan WA - read-only"),
    "wa_search_messages": (RiskTier.LOW, "Cari pesan WA - read-only"),
    "wa_list_formats": (RiskTier.LOW, "Daftar format WA - read-only"),
    "wa_mark_read": (RiskTier.LOW, "Tandai pesan WA sudah dibaca"),
    "wa_get_history_archive": (RiskTier.LOW, "Baca arsip pesan WA lokal - read-only"),
    "rea_inspect_android_package": (RiskTier.LOW, "Inspeksi paket APK Android - read-only"),
    "rea_inspect_binary_or_wasm": (RiskTier.LOW, "Inspeksi binary atau WASM - read-only"),
    "rea_inspect_js_app": (RiskTier.LOW, "Inspeksi aplikasi JavaScript/Electron - read-only"),
    "rea_inspect_sqlite_database": (RiskTier.LOW, "Inspeksi snapshot database SQLite - read-only"),
    "rea_recover_js_sources": (RiskTier.LOW, "Pemulihan kode sumber JavaScript - read-only"),
    "rea_run_command": (RiskTier.MEDIUM, "Eksekusi perintah analisis REA khusus"),
    "auto_diagnose_and_heal_system": (RiskTier.LOW, "Diagnostic read-only - safe"),
    "system_clean_memory_and_cache": (RiskTier.LOW, "Optimasi RAM dan bersihkan cache sistem"),
    "open_url_in_system_browser": (RiskTier.LOW, "Buka URL di browser - read-only"),
    "play_youtube_music": (RiskTier.LOW, "Putar musik YouTube - hiburan"),
    "browser_open_url": (RiskTier.LOW, "Buka URL di browser stealth - read-only"),
    "browser_capture_screenshot": (
        RiskTier.LOW,
        "Screenshot browser stealth - read-only",
    ),
    "browser_close_tab": (RiskTier.LOW, "Tutup tab browser stealth - aman"),
    "browser_visual_test_page": (RiskTier.LOW, "Uji visual halaman - read-only"),
    "show_desktop_notification": (RiskTier.LOW, "Notifikasi desktop - aman"),
    "capture_desktop_screenshot": (RiskTier.LOW, "Screenshot desktop - read-only"),
    "web_search": (RiskTier.LOW, "Pencarian web - read-only"),
    "fetch_web_page_content": (RiskTier.LOW, "Ambil isi halaman - read-only"),
    "deep_research_topic": (RiskTier.LOW, "Riset mendalam - read-only"),
    "academic_deep_research_paper": (RiskTier.LOW, "Riset paper akademik - read-only"),
    "get_system_stats": (RiskTier.LOW, "Statistik sistem - read-only"),
    "query_token_usage": (RiskTier.LOW, "Pemakaian token - read-only"),
    "generate_secure_password": (RiskTier.LOW, "Buat password acak - tanpa efek samping"),
    "translate_text": (RiskTier.LOW, "Terjemahkan teks - tanpa efek samping"),
    "find_user_files": (RiskTier.LOW, "Cari file user - read-only"),
    "grep_workspace": (RiskTier.LOW, "Grep workspace - read-only"),
    "search_workspace_files": (RiskTier.LOW, "Cari file di workspace - read-only"),
    "search_codebase": (RiskTier.LOW, "Cari di codebase - read-only"),
    "index_codebase": (RiskTier.LOW, "Indeks codebase - read-only"),
    "list_running_processes": (RiskTier.LOW, "Daftar proses - read-only"),
    "search_knowledge_memory": (RiskTier.LOW, "Cari memori - read-only"),
    "save_knowledge_memory": (RiskTier.LOW, "Simpan fakta ke memori - dampak rendah"),
    "semantic_search_vector_brain": (RiskTier.LOW, "Cari semantik di memori - read-only"),
    "search_vector_memory": (RiskTier.LOW, "Cari di memori vektor - read-only"),
    "list_vector_brain_documents": (RiskTier.LOW, "Daftar dokumen memori - read-only"),
    "hybrid_search_vector_brain": (
        RiskTier.MEDIUM,
        "Pencarian hybrid (vektor + keyword) di memori - read-only tapi mahal",
    ),
    "agentic_document_query_crag": (
        RiskTier.MEDIUM,
        "Query dokumen ala CRAG - bisa memanggil sub-proses pencarian",
    ),
    "analyze_document_tabular_data": (
        RiskTier.MEDIUM,
        "Analisis data tabular dokumen - baca data potentially sensitif",
    ),
    "graph_rag_query_multi_doc": (
        RiskTier.MEDIUM,
        "Query graph RAG lintas dokumen - baca data potentially sensitif",
    ),
    "index_document_to_graph": (
        RiskTier.MEDIUM,
        "Indeks dokumen ke knowledge graph - tulis ke store",
    ),
    "manage_document_context_cache": (
        RiskTier.MEDIUM,
        "Kelola cache konteks dokumen - tulis ke store",
    ),
    "save_to_vector_memory": (
        RiskTier.MEDIUM,
        "Simpan teks ke memori vektor - tulis ke store",
    ),
    "pdf_extract_full_text": (RiskTier.LOW, "Ekstrak teks PDF - read-only"),
    "pdf_inspect_metadata": (RiskTier.LOW, "Metadata PDF - read-only"),
    "qr_barcode_generator": (RiskTier.LOW, "Buat QR code - tanpa efek samping"),
    "crypto_forex_live_rates": (RiskTier.LOW, "Kurs crypto/forex - read-only"),
    "audit_network_security": (RiskTier.LOW, "Audit jaringan - read-only"),
    "audit_website_security": (RiskTier.LOW, "Audit keamanan website - read-only"),
    "audit_project_honesty": (RiskTier.LOW, "Scan dummy-data di source - read-only"),
    "git_repo_health_analyzer": (RiskTier.LOW, "Analisis kesehatan repo - read-only"),
    "git_worktree_sandbox_list": (RiskTier.LOW, "Daftar worktree - read-only"),
    "list_dynamic_plugins": (RiskTier.LOW, "Daftar plugin - read-only"),
    "list_managed_sites": (RiskTier.LOW, "Daftar situs terkelola - read-only"),
    "list_recurring_tasks": (RiskTier.LOW, "Daftar tugas berulang - read-only"),
    "list_wa_drive_uploads": (RiskTier.LOW, "Daftar upload WA drive - read-only"),
    "gdrive_list_files": (RiskTier.LOW, "Daftar file Drive - read-only"),
    "gdrive_status": (RiskTier.LOW, "Status integrasi Drive - read-only"),
    "mcp_status": (RiskTier.LOW, "Status MCP server - read-only"),
    "check_subagent_status": (RiskTier.LOW, "Status subagent - read-only"),
    "lsp_analyze_module_hierarchy": (RiskTier.LOW, "Analisis hierarki modul - read-only"),
    "lsp_find_symbol_definition": (RiskTier.LOW, "Cari definisi simbol - read-only"),
    "lsp_find_symbol_references": (RiskTier.LOW, "Cari referensi simbol - read-only"),
    "github_assistant": (RiskTier.LOW, "Bantu query GitHub - read-only"),
    "ui_ux_pro_max_search": (RiskTier.LOW, "Cari panduan UI/UX - read-only"),
    "whois_dns_domain_lookup": (RiskTier.LOW, "Lookup WHOIS/DNS - read-only"),
    "open_web_dashboard": (RiskTier.LOW, "Buka dashboard di browser - read-only"),
}

# Default tier untuk tool yang TIDAK terklasifikasi.
#
# Fail-closed: tool baru yang belum masuk TOOL_CLASSIFICATION dianggap
# berisiko tinggi, bukan "sedang". Tool yang belum terklasifikasi TIDAK BOLEH
# auto-approve pada trust biasa, dan tidak lolos headless policy default.
DEFAULT_TIER = RiskTier.HIGH

# Safe tools yang selalu otomatis lolos (tier LOW implicit)
SAFE_TOOLS = {
    "web_search",
    "fetch_web_page_content",
    "deep_research_topic",
    "search_workspace_files",
    "grep_workspace",
    "find_user_files",
    "index_codebase",
    "search_codebase",
    "save_knowledge_memory",
    "search_knowledge_memory",
    "get_system_stats",
    "get_current_user_id",
    "get_current_chat_id",
    "capture_desktop_screenshot",
    "list_running_processes",
    "generate_secure_password",
    "translate_text",
    # Nama tool yang sebenarnya terdaftar (sebelumnya salah tulis
    # 'token_usage_query' sehingga query_token_usage minta izin tiap kali)
    "query_token_usage",
    "browser_open_url",
    "browser_capture_screenshot",
    "browser_close_tab",
    "open_url_in_system_browser",
    "play_youtube_music",
    "show_desktop_notification",
}

# Timeout per tier (detik)
TIER_TIMEOUTS = {
    RiskTier.LOW: 60,
    RiskTier.MEDIUM: 180,
    RiskTier.HIGH: 300,
    RiskTier.CRITICAL: 600,
}

_LABELS = {
    "once": "✅ Diizinkan (sekali ini)",
    "always": "🔁 Diizinkan SELALU untuk sesi mendatang",
    "always_session": "⏳ Izinkan sampai sesi berakhir",
    "deny": "❌ Ditolak oleh pengguna",
    "timeout": "⏰ Auto-ditolak (tidak ada respons)",
    "auto_approved": "✨ Auto-approved (trust score tinggi)",
}


# ── Penyimpanan aturan 'selalu izinkan' ──────────────────────────────────────
