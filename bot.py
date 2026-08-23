#!/usr/bin/env python3
"""
Ultra-Advanced Telegram AI Agent Bot (Surpassing Hermes Agent & OpenClaw)
Powered by Google Gemini API & Autonomous Real Tool Execution.

Features:
- Full Multi-User Context Isolation via contextvars
- Real Subprocess Python Sandbox & Matplotlib Data Plotter (auto-delivered as photos)
- Ultra-Fast Desktop Screenshot & Hardware Webcam Frame Capture
- Full File & Code Workspace Intelligence (grep, find, read, write)
- Deep Live Web Intelligence (DuckDuckGo search, URL content scraper)
- Native Multimodal: Voice Notes, Photos/Vision, Documents (PDF/Code/Data)
- High-fidelity Natural Voice Audio Notes (Edge-TTS)
- Persistent SQLite Database with WAL Mode for Chat History & Long-Term Memories
- Proactive Background Cron & Reminder Dispatcher
- Safe Telegram Markdown/HTML Formatter with Zero Entity Parsing Errors
- Interactive Telegram Control Center & Inline Menus
"""

import os
import sys
import io
import json
import asyncio
import logging
import glob
import subprocess
import psutil
from datetime import datetime
from typing import List, Optional, Dict, Any

from dotenv import load_dotenv
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    constants,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# Local modules
import database
import main_brain
import tools
import token_usage
import permission_gate
from tools import (
    AVAILABLE_TOOLS,
    get_system_stats,
    current_user_id_var,
    current_chat_id_var,
    SANDBOX_DIR
)
import tts_engine

# Load environment
load_dotenv()

# Setup logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("TelegramAIAgent")

# Configuration
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()
# Nama pemilik bot — dipakai di persona & prompt agar bot personal bagi
# siapa pun yang menginstalnya (default netral untuk distribusi publik).
OWNER_NAME = os.getenv("OWNER_NAME", "Pemilik").strip() or "Pemilik"

raw_allowed_users = os.getenv("ALLOWED_USER_IDS", "").strip()
ALLOWED_USER_IDS = [
    int(uid.strip()) for uid in raw_allowed_users.split(",") if uid.strip().isdigit()
]

# Load Dynamic System Prompt from file, .env, or smart default
ALFA_PROMPT_PATH = os.path.expanduser("~/.alfa/system_prompt.txt")
ENV_SYSTEM_INSTRUCTION = os.getenv("SYSTEM_INSTRUCTION", "").strip()

if os.path.exists(ALFA_PROMPT_PATH):
    with open(ALFA_PROMPT_PATH, "r", encoding="utf-8") as f:
        BASE_SYSTEM_PROMPT = f.read().strip()
elif ENV_SYSTEM_INSTRUCTION:
    BASE_SYSTEM_PROMPT = ENV_SYSTEM_INSTRUCTION
else:
    BASE_SYSTEM_PROMPT = (
        f"You are ALFA, asisten AI otonom pribadi dan partner harian {OWNER_NAME} yang cerdas, luwes, dan seru.\n\n"
        "### 🎭 KEPRIBADIAN & GAYA KOMUNIKASI (SANTAI & ALAMI - ANTI-ROBOT)\n"
        "1. GAYA BAHASA SANTAI: Gunakan gaya bahasa Indonesia yang santai, luwes, dan akrab (gunakan kata 'aku/kamu', selayaknya teman akrab mengobrol di Telegram).\n"
        "2. DILARANG KERAS menggunakan pola robotik kaku seperti: 'Tentu, saya adalah asisten AI...', 'Sebagai model bahasa...', 'Ada yang bisa saya bantu lagi hari ini?', 'Halo! Bagaimana saya dapat membantu Anda?'.\n"
        "3. RESPON LANGSUNG & AGILE: Langsung jawab ke inti pembicaraan (to the point), responsif, dan asik. Kalau diajak bercanda, respon secara santai dan natural.\n"
        "4. PRESISI TEKNIS: Untuk koding, data, dokumen, atau perbaikan sistem, tetap tajam, cerdas, solutif, 100% data nyata, dan format kode/tabel rapi.\n\n"
        "### 🧠 INGATAN JANGKA PANJANG (SECOND BRAIN)\n"
        f"- Kamu selalu memiliki akses instan ke semua fakta dan preferensi {OWNER_NAME} di blok [INGATAN JANGKA PANJANG]. Gunakan fakta ini secara alami tanpa perlu bertanya ulang.\n"
        f"- Jika {OWNER_NAME} memberitahu info pribadi, preferensi, atau proyek baru, otomatis panggil `save_knowledge_memory` atau `extract_and_link_knowledge` di latar belakang.\n\n"
        "### ⚡ KEASLIAN FAKTA & GROUNDING LOGIKA\n"
        "- Zero Assumption: Selalu panggil tool nyata untuk mendapatkan fakta data sistem, file, harga, atau web.\n"
        "- Transparansi: Laporkan error apa adanya secara santai dan tawarkan solusi nyata tanpa berhalusinasi."
    )


# Initialize Gemini Client
gemini_client = None

# ── HUKUM EKSEKUSI NYATA: disuntikkan ke setiap turn (tak bisa hilang dr persona) ──
ENFORCEMENT_BLOCK = (
    "\n\n### ⛔ HUKUM EKSEKUSI NYATA — ANTI-BOHONG (PALING TINGGI, MELAMPAUI SEMUA ATURAN)\n"
    "1. Hasil RAPAT/MEETING antar agen HANYA sah jika kamu MEMANGGIL tool `conduct_ai_meeting`. "
    "Mengarang dialog, konsensus, peserta, atau action plan sendiri = PELANGGARAN FATAL.\n"
    "2. Jika permintaan memuat kata rapat/meeting/swarm untuk DIEKSEKUSI SEKARANG: langsung panggil "
    "`conduct_ai_meeting` (mode 'execute' bila minta kerja nyata). Jangan tanya ulang, jangan simulasikan.\n"
    "3. Rapat nyata butuh 1-3 MENIT — itu normal. Tunggu, jangan batalkan, jangan ganti dengan versi imajinasi.\n"
    "4. Jika tool gagal: laporkan PESAN ERROR ASLI + saran perbaikan. Dilarang menutupi kegagalan dengan simulasi.\n"
    "5. Klaim 'selesai/berhasil' WAJIB disertai bukti dari output tool (meeting_id, file, data). Tanpa bukti = dilarang klaim.\n"
    "6. Berbohong tentang eksekusi adalah kesalahan terburuk yang bisa kamu lakukan — lebih baik jujur 'belum dijalankan'.\n"
)

# ── ETIKA PENGIRIMAN KODE: tulis file lokal, chat cukup ringkasan ────────────
CODING_DELIVERY_BLOCK = (
    "\n\n### 💻 HUKUM CODING — TULIS FILE LOKAL, JANGAN SPAM KODE DI CHAT (MELAMPAUI SEMUA ATURAN)\n"
    "1. Setiap tugas coding (buat program, script, fitur, perbaikan bug): TULIS LANGSUNG ke file "
    "di folder proyek lokal pakai `write_local_file` / `edit_file_precise` / `apply_unified_diff`. "
    "Folder default: `~/alfa_projects/<nama-proyek>/`. Jangan pernah menumpuk kode di folder sandbox.\n"
    "2. Uji/compile/run pakai `execute_bash_command` dengan `working_dir` mengarah ke folder proyek "
    "tersebut — bukan di sandbox root.\n"
    "3. BALASAN CHAT = RINGKASAN: apa yang dikerjakan, daftar file yang dibuat/diubah (dengan path), "
    "cara menjalankan, dan hasil tes. DILARANG menempelkan kode mentah panjang (>10 baris) di pesan. "
    "Cuplikan <=10 baris hanya bila benar-benar perlu menjelaskan sesuatu.\n"
    "4. File kode TIDAK dikirim sebagai dokumen/lampiran. Kirim berkas via `send_file_to_chat` HANYA "
    f"bila {OWNER_NAME} meminta secara eksplisit ('kirim filenya').\n"
    f"5. {OWNER_NAME} bisa melihat/mengedit semua file langsung di mesin — chat bukan tempat membaca kode, "
    "tapi tempat melihat hasil kerja."
)

# ── PETA KEMAMPUAN: agar agent paham semua fitur ekosistem & kapan memakainya ──
CAPABILITIES_BLOCK = (

    "\n\n### 🗺️ PETA KEMAMPUAN ALFA (ekosistem Telegram + Web Dashboard)\n"
    "Kamu aktif di DUA kanal sekaligus — Telegram dan Web Dashboard (http://localhost:8080) — "
    "dengan ingatan, riwayat, dan kepribadian yang SAMA. Fitur dashboard punya padanan tool "
    "yang bisa kamu panggil langsung:\n\n"
    "• RAPAT/SWARM MULTI-AGEN → `conduct_ai_meeting` (mode plan/execute; execute = kerja nyata: "
    "scraping CSV, eksekusi Python Docker, audit keamanan). Rapat butuh 1-3 menit = normal.\n"
    "• GITHUB → `github_assistant` (repos/info/issues/create_issue/search/prs/notifikasi).\n"
    "• SKILL DARI GITHUB → `skill_installer`: install_repo (repo dokumen→Second Brain), "
    "install_tool (file .py→tools AI), list, remove.\n"
    "• SECOND BRAIN / DRIVE → `gdrive_sync_to_second_brain` (sinkron dokumen folder Drive), "
    "`semantic_search_vector_brain` untuk pertanyaan mendalam, `ingest_document_to_vector_brain`. "
    "Auto-RAG sudah aktif: potongan relevan otomatis masuk kontensmu tiap pesan.\n"
    "• GOOGLE DRIVE → `gdrive_upload_file`, `gdrive_list_files`, `gdrive_download_file`, "
    "`gdrive_create_folder`, `gdrive_status`.\n"
    "• WHATSAPP SHEETS BOT → `manage_wa_sheets_bot` (start/stop/status); format laporan & aturan "
    "Drive diedit user di tab 'WA Laporan'; daftar berkas terunggah: `list_wa_drive_uploads`.\n"
    "• PEMAKAIAN TOKEN → `query_token_usage` (per API key, realtime).\n"
    "• WEB & DATA → `web_search`, `universal_deep_scraper`, `scrape_custom_urls_batch`, "
    "`fetch_web_page_content`, `deep_research_topic`, `analyze_dataset_csv_json`.\n"
    "• DOKUMEN → suite `pdf_*`, `generate_excel_spreadsheet`, `generate_presentation_pptx`, "
    "LibreOffice (`libreoffice_*`), hasil otomatis dikirim sebagai berkas.\n"
    "• SISTEM & KONTROL PERANGKAT → `execute_bash_command`, `execute_python_sandbox` (Docker), "
    "`get_system_stats`, screenshot/webcam/desktop keys, browser automation (camoufox/crawl4ai), "
    "`manage_system_services`, `manage_crontab_jobs`, SSH, Android (scrcpy).\n"
    "• PRODUKTIVITAS → `schedule_reminder`, `add_recurring_task`, `spawn_background_subagent`, "
    "`start_focus_session`.\n"
    "• VAULT RAHASIA → `vault_store_secret/get_secret/list_secrets`.\n"
    "• AFFILIASI & MEDIA → `affiliate_*`, `marketplace_search_products`, "
    "`generate_promo_video_from_images`, `text_to_audio_file`.\n"
    "• EVOLUSI DIRI → `self_add_new_tool`, `manage_custom_agents`, `delete_dynamic_plugin`, "
    "`list_dynamic_plugins`.\n\n"
    "PANDUAN MENJAWAB:\n"
    "- Ditanya 'fitur apa saja / apa yang bisa kamu lakukan' → rangkum grup di atas dengan bahasa santai + arahkan tab dashboard terkait (Overview, Tools Explorer, Swarm, WA Laporan, Google Drive Hub, Keys, Vault, Guardian, Services, Settings).\n"
    "- Pilih tool PALING SPESIFIK untuk maksud user; jangan menebak data kalau tool tersedia.\n"
    "- Untuk pekerjaan berat multi-langkah, tawarkan mode swarm execute.\n"
)


def _meetings_count() -> int:
    """Ground truth: jumlah rapat NYATA di database."""
    try:
        with database.get_sync_db() as conn:
            row = conn.execute("SELECT COUNT(*) FROM agent_meetings").fetchone()
            return int(row[0]) if row else 0
    except Exception:
        return 0


ARTIFACT_DIRS = [
    os.path.expanduser("~/Dokumen/ALFA_SWARM_OUTPUTS"),
    SANDBOX_DIR,
]
ARTIFACT_NOUNS = ('laporan', 'file', 'csv', 'excel', 'pdf', 'website', 'scrape',
                  'grafik', 'chart', 'pptx', 'dokumen', 'landing')
COMPLETION_VERBS = ('sudah', 'selesai', 'berhasil', 'telah dibuat', 'sudah dibuat',
                    'aku buatkan')


def _artifact_signature() -> list:
    """Snapshot (path,size,mtime) berkas output - ground truth klaim artefak."""
    sig = []
    for d in ARTIFACT_DIRS:
        try:
            for root, _, files in os.walk(d):
                for f in files:
                    p = os.path.join(root, f)
                    try:
                        st = os.stat(p)
                        sig.append((p, st.st_size, int(st.st_mtime)))
                    except OSError:
                        pass
        except Exception:
            pass
    return sorted(sig)


MEETING_INTENT_KEYWORDS = ('rapat', 'meeting', 'swarm', 'diskusi tim', 'round-table', 'roundtable')
MEETING_FABRICATION_MARKERS = ('konsensus', 'transkrip', 'action plan', 'peserta',
                               'putaran', 'hasil rapat', 'kesimpulan rapat')

AUDIT_CORRECTION_TEXT = (
    "⛔ SISTEM AUDIT KEBENARAN:\n"
    "Pada giliran ini TIDAK ADA rapat yang benar-benar dijalankan oleh sistem — "
    "tool `conduct_ai_meeting` TIDAK kamu panggil, sedangkan jawabanmu menampilkan "
    "hasil rapat. Itu berarti kamu mengarang, dan itu dilarang keras.\n\n"
    "Perbaiki SEKARANG dengan SALAH SATU:\n"
    f"(a) Jika {OWNER_NAME} meminta rapat NYATA sekarang → panggil tool `conduct_ai_meeting` "
    "untuk topik ini, tunggu sampai selesai (1-3 menit itu normal), lalu jawab HANYA "
    "dari data nyata yang dikembalikan (meeting_id, dialog, konsensus, action_plan).\n"
    "(b) Jika permintaannya belum jelas untuk dieksekusi sekarang → jawab singkat dan "
    "JUJUR bahwa rapat belum dijalankan, lalu tanyakan konfirmasi topik & mode.\n\n"
    "DILARANG mengulang atau mempertahankan klaim rapat fiktif dalam bentuk apa pun."
)

if GEMINI_API_KEY and GEMINI_API_KEY != "your_gemini_api_key_here":
    try:
        from google import genai
        gemini_client = genai.Client(api_key=GEMINI_API_KEY)
        logger.info("Google GenAI client initialized successfully.")
    except Exception as e:
        logger.error(f"Failed to initialize GenAI client: {e}")


# Resolver bersama: kunci AKTIF di vault selalu menang atas .env, sehingga
# pergantian key/model lewat dashboard langsung berlaku untuk Telegram & Web.
_gemini_client_cache: Dict[str, Any] = {}


def _main_brain_gemini_model() -> str:
    """Model Gemini aktif sesuai konfigurasi Otak Utama (vault).

    Prioritas: override main_brain_model -> default_model kunci gemini aktif
    di vault -> GEMINI_MODEL env. Mencegah loop latar memakai model .env
    yang sudah usang/retire sementara dashboard memakai model lain.
    """
    try:
        override = database.get_main_brain_model()
        if override:
            return override.strip()
    except Exception:
        pass
    try:
        active = database.get_active_api_key_sync("gemini")
        m = (active or {}).get("default_model")
        if m and m.strip():
            return m.strip()
    except Exception:
        pass
    return GEMINI_MODEL


def resolve_main_gemini():
    """Return (client, key_id, key_label) for the MAIN agent.

    Priority: active 'gemini' key in the vault -> GEMINI_API_KEY env.
    Clients are cached per key string to avoid rebuilding per message.
    """
    try:
        active = database.get_active_api_key_sync("gemini")
    except Exception:
        active = None

    if active and (active.get("api_key") or "").strip():
        api_key = active["api_key"].strip()
        key_id = active.get("id")
        label = f"vault#{key_id}"
    else:
        api_key = os.getenv("GEMINI_API_KEY", "").strip()
        key_id = None
        label = "gemini-env"

    if not api_key or api_key == "your_gemini_api_key_here":
        return None, None, ""

    cli = _gemini_client_cache.get(api_key)
    if cli is None:
        from google import genai as _genai
        cli = _genai.Client(api_key=api_key)
        _gemini_client_cache[api_key] = cli
    return cli, key_id, label


_whitelist_warning_sent = False


def is_authorized(user_id: int) -> bool:
    """Check if the user is authorized to access the bot.

    Fail-safe: an empty/misconfigured whitelist DENIES access instead of
    granting public control over this machine's tools (bash/python/etc).
    """
    global _whitelist_warning_sent
    if not ALLOWED_USER_IDS:
        if not _whitelist_warning_sent:
            logger.critical(
                "ALLOWED_USER_IDS kosong/tidak valid di .env - SEMUA akses ditolak. "
                "Tambahkan Telegram ID Anda ke ALLOWED_USER_IDS untuk mengaktifkan bot."
            )
            _whitelist_warning_sent = True
        return False
    return user_id in ALLOWED_USER_IDS


def split_message(text: str, max_length: int = 3900) -> List[str]:
    """Split long response into safe Telegram message chunks without breaking code fences."""
    if len(text) <= max_length:
        return [text]
    chunks = []
    lines = text.split("\n")
    current_chunk = ""
    in_code_block = False
    code_block_lang = ""

    for line in lines:
        if line.strip().startswith("```"):
            if not in_code_block:
                in_code_block = True
                code_block_lang = line.strip()[3:]
            else:
                in_code_block = False

        if len(current_chunk) + len(line) + 2 > max_length:
            if current_chunk:
                if in_code_block:
                    current_chunk += "\n```"
                chunks.append(current_chunk)
                current_chunk = ""
                if in_code_block:
                    current_chunk = f"```{code_block_lang}\n"

            while len(line) > max_length:
                chunks.append(line[:max_length])
                line = line[max_length:]
            current_chunk += line if not current_chunk else "\n" + line
        else:
            if current_chunk:
                current_chunk += "\n" + line
            else:
                current_chunk = line

    if current_chunk:
        chunks.append(current_chunk)
    return chunks


async def safe_send_message(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    text: str,
    reply_to_message_id: Optional[int] = None,
    reply_markup: Optional[InlineKeyboardMarkup] = None
):
    """
    Safely send message to Telegram with automatic chunking and fallback to plain text
    if Markdown parsing fails.
    """
    chunks = split_message(text)
    for i, chunk in enumerate(chunks):
        markup = reply_markup if i == len(chunks) - 1 else None
        reply_id = reply_to_message_id if i == 0 else None
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=chunk,
                parse_mode=constants.ParseMode.MARKDOWN,
                reply_to_message_id=reply_id,
                reply_markup=markup
            )
        except Exception:
            try:
                # Fallback to plain text without parse mode
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=chunk,
                    reply_to_message_id=reply_id,
                    reply_markup=markup
                )
            except Exception as e:
                logger.error(f"Failed to send message chunk: {e}")


async def send_typing_loop(
    chat_id: int,
    context: ContextTypes.DEFAULT_TYPE,
    stop_event: asyncio.Event,
    action=constants.ChatAction.TYPING
):
    """Keep sending chat action indicator while processing."""
    while not stop_event.is_set():
        try:
            await context.bot.send_chat_action(chat_id=chat_id, action=action)
        except Exception:
            pass
        await asyncio.sleep(4)


# --- Core AI Generation Engine ---
async def run_agent_turn(
    user_id: int,
    user_prompt: str,
    multimodal_parts: Optional[list] = None,
    chat_id: Optional[int] = None
) -> str:
    """
    Executes an autonomous agent turn with memory context, real tool calling, and multimodal inputs.
    Propagates contextvars for per-user tool isolation.
    Supports MAIN BRAIN lintas-provider: otak mengikuti kunci yang diaktivasi di vault.
    """
    global gemini_client
    import main_brain

    brain = main_brain.get_main_brain()
    if brain["provider"] == "gemini":
        gemini_client, gkey_id, gkey_label = resolve_main_gemini()
        if not gemini_client:
            return (
                "⚠️ **API key belum tersedia.**\n"
                "Aktivasi kunci (Gemini/OpenRouter/custom) di Dashboard > API Key Vault — "
                "kunci yang terakhir diaktifkan menjadi otak utama agent."
            )
    else:
        gemini_client, gkey_id, gkey_label = None, None, ""

    # Set context variables for tools
    current_user_id_var.set(user_id)
    current_chat_id_var.set(chat_id or user_id)

    # Permission Gate (human-in-the-loop) utk tool berbahaya
    approval_gate = permission_gate.make_gate(chat_id or user_id)

    # 1. Fetch recent chat history from SQLite
    history_rows = await database.get_recent_chat_history(user_id, limit=12)
    
    # 2. Build contents payload
    from google.genai import types
    contents = []
    
    for row in history_rows:
        role = "user" if row["role"] == "user" else "model"
        contents.append(
            types.Content(
                role=role,
                parts=[types.Part.from_text(text=row["content"])]
            )
        )

    # 3. Add current turn with any multimodal attachments
    current_parts = []
    if multimodal_parts:
        current_parts.extend(multimodal_parts)
    if user_prompt:
        current_parts.append(types.Part.from_text(text=user_prompt))

    contents.append(types.Content(role="user", parts=current_parts))

    # 4. Save user turn to database
    display_user_text = user_prompt or "[Lampiran Media]"
    await database.save_chat_message(user_id, "user", display_user_text)

    # 5. Fetch all long-term memories & knowledge graph for instant recall
    user_memories = await database.get_all_memories(user_id)
    kg_triples = database.get_all_knowledge_graph_sync(user_id)
    
    memory_context_parts = []
    if user_memories:
        memory_context_parts.append("📌 FAKTA & CATATAN PRIBADI TERSIMPAN:")
        for m in user_memories:
            memory_context_parts.append(f"- [{m['category']}] {m['key_topic']}: {m['content']}")
            
    if kg_triples:
        memory_context_parts.append("🕸️ RELASI KNOWLEDGE GRAPH:")
        for k in kg_triples:
            tag_str = f" ({k['tags']})" if k.get('tags') else ""
            memory_context_parts.append(f"- {k['entity']} -> [{k['relation']}] -> {k['target_value']}{tag_str}")

    # 5b. AUTO-RAG: ambil potongan dokumen Drive yang relevan dgn pertanyaan.
    # Inilah yang membuat Second Brain benar-benar jadi otak: tanpa diminta,
    # pengetahuan dari dokumen tersinkron ikut masuk konteks tiap giliran.
    try:
        import vector_memory
        brain_hits = vector_memory.semantic_search(
            user_id=user_id, query=user_prompt or "", top_k=4
        )
        relevant = [h for h in brain_hits if (h.get("similarity_score") or 0) >= 0.25]
        if relevant:
            memory_context_parts.append("📄 PENGETAHUAN DARI DOKUMEN DRIVE (Second Brain):")
            for h in relevant:
                memory_context_parts.append(
                    f"- [{h.get('doc_title','?')}] {str(h.get('chunk_text',''))[:350]}"
                )
    except Exception as rag_err:
        logger.debug(f"Auto-RAG skipped: {rag_err}")
            
    memory_block = ""
    if memory_context_parts:
        memory_block = (
            "\n\n======================================================\n"
            "🧠 [INGATAN JANGKA PANJANG & SECOND BRAIN AKTIF]\n"
            f"Berikut adalah seluruh ingatan jangka panjang dan fakta yang tersimpan tentang {OWNER_NAME}. "
            "Pahami dan gunakan fakta ini secara alami dalam percakapan tanpa perlu bertanya ulang:\n"
            + "\n".join(memory_context_parts) +
            "\n======================================================\n"
        )

    # 6. Fetch user settings for prompt override / preferred model
    user_settings = await database.get_user_settings(user_id)
    
    # Reload latest prompt from file if available
    active_base_prompt = BASE_SYSTEM_PROMPT
    if os.path.exists(ALFA_PROMPT_PATH):
        try:
            with open(ALFA_PROMPT_PATH, "r", encoding="utf-8") as f:
                active_base_prompt = f.read().strip()
        except Exception:
            pass

    base_instruction = user_settings.get("system_prompt_override") or active_base_prompt
    full_system_instruction = base_instruction + memory_block + ENFORCEMENT_BLOCK + CODING_DELIVERY_BLOCK + CAPABILITIES_BLOCK
    preferred_model = user_settings.get("model_name") or GEMINI_MODEL

    # 7. Call Gemini with Agent Tools and fast fallback chain
    fallback_chain = [m.strip() for m in os.getenv(
        "GEMINI_FALLBACK_MODELS",
        "gemini-3.6-flash,gemini-3.5-flash-lite,gemini-flash-latest"
    ).split(",") if m.strip()]

    # Model otak utama (dari System Settings) menang atas preferensi per-user
    brain_model_override = database.get_main_brain_model()
    base_model = brain_model_override or preferred_model
    candidate_models = [base_model] + (
        [preferred_model] if preferred_model and preferred_model != base_model else []
    ) + fallback_chain
    models_to_try = list(dict.fromkeys(candidate_models))

    last_error = None
    # ── Ground-truth audit: berapa rapat NYATA sebelum turn ini ──
    meetings_before = _meetings_count()
    art_before = _artifact_signature()
    prompt_low = (user_prompt or "").lower()
    meeting_intent = any(k in prompt_low for k in MEETING_INTENT_KEYWORDS)

    # ══ OTAK UTAMA LINTAS PROVIDER (OpenRouter/Ox Alpha/Custom/NVIDIA dll) ══
    if brain["provider"] != "gemini":
        compat_text = user_prompt or ""
        if multimodal_parts:
            compat_text = (compat_text + "\n[Lampiran media tidak didukung provider otak utama saat ini]").strip()
        history_msgs = [{"role": r["role"], "content": r["content"]} for r in history_rows]
        reply_text = await main_brain.run_openai_agentic_turn(
            provider=brain["provider"],
            base_url=brain["base_url"],
            api_key=brain["api_key"],
            model=brain["model"] or preferred_model,
            system_instruction=full_system_instruction,
            user_text=compat_text,
            history=history_msgs,
            key_id=brain["key_id"],
            key_label=brain["label"],
            approval_gate=approval_gate,
        )
        new_meetings = _meetings_count() - meetings_before
        if meeting_intent and new_meetings == 0 and reply_text:
            low = reply_text.lower()
            if ('rapat' in low or 'meeting' in low) and \
               any(mk in low for mk in MEETING_FABRICATION_MARKERS):
                logger.warning("[AUDIT-compat] klaim rapat tanpa tool -> pass koreksi")
                corrected = await main_brain.run_openai_agentic_turn(
                    provider=brain["provider"], base_url=brain["base_url"],
                    api_key=brain["api_key"],
                    model=brain["model"] or preferred_model,
                    system_instruction=full_system_instruction,
                    user_text=compat_text + "\n\n" + AUDIT_CORRECTION_TEXT,
                    history=history_msgs, key_id=brain["key_id"],
                    key_label=brain["label"], approval_gate=approval_gate)
                if corrected:
                    reply_text = corrected
        if reply_text:
            await database.save_chat_message(user_id, "model", reply_text)
            return reply_text
        logger.warning(f"[MainBrain:{brain['provider']}] gagal total -> fallback rantai Gemini")

    for model_name in models_to_try:
        try:
            gate_on = approval_gate is not None
            config = types.GenerateContentConfig(
                system_instruction=full_system_instruction,
                temperature=0.75,
                tools=AVAILABLE_TOOLS,
                # AFC SDK dimatikan saat gate aktif agar tiap tool call
                # melewati persetujuan manusia (loop manual di bawah).
                automatic_function_calling=(
                    types.AutomaticFunctionCallingConfig(disable=True)
                    if gate_on else None
                ),
            )

            response = await gemini_client.aio.models.generate_content(
                model=model_name,
                contents=contents,
                config=config
            )
            token_usage.from_gemini_response(response, model=model_name,
                                             key_id=gkey_id,
                                             key_label=gkey_label or "gemini-env",
                                             context="telegram_chat")

            # ── Loop agentic manual (Permission Gate ON) ──
            if gate_on:
                _turn_contents = list(contents or [])
                for _iter in range(main_brain.MAX_ITERATIONS):
                    fcs = list(getattr(response, "function_calls", None) or [])
                    if not fcs:
                        break
                    try:
                        model_content = response.candidates[0].content
                        if model_content is not None:
                            _turn_contents.append(model_content)
                    except Exception:
                        pass
                    for fc in fcs:
                        args_json = json.dumps(dict(fc.args or {}),
                                               ensure_ascii=False, default=str)
                        denial = await approval_gate(fc.name, args_json)
                        if denial:
                            out = denial
                        else:
                            out = await asyncio.to_thread(
                                main_brain._execute_tool, fc.name, args_json)
                        logger.info(f"[GatePath] tool {fc.name} -> {str(out)[:80]}")
                        _turn_contents.append(types.Content(role="user", parts=[
                            types.Part(function_response=types.FunctionResponse(
                                name=fc.name,
                                response={"result": str(out)[:4000]}))]))
                    response = await gemini_client.aio.models.generate_content(
                        model=model_name, contents=_turn_contents, config=config)
                    token_usage.from_gemini_response(response, model=model_name,
                                                     key_id=gkey_id,
                                                     key_label=gkey_label or "gemini-env",
                                                     context="telegram_chat:gate")

            try:
                reply_text = response.text or "✅ Permintaan selesai diproses."
            except Exception:
                reply_text = "✅ Permintaan selesai diproses."

            # ══ AUDIT ANTI-BOHONG v2 (deterministik: database + filesystem) ══
            new_meetings = _meetings_count() - meetings_before
            reply_low = reply_text.lower()

            need_meeting_audit = (
                meeting_intent and new_meetings == 0
                and ('rapat' in reply_low or 'meeting' in reply_low)
                and any(mk in reply_low for mk in MEETING_FABRICATION_MARKERS)
            )
            need_artifact_audit = (
                any(n in prompt_low for n in ARTIFACT_NOUNS)
                and _artifact_signature() == art_before
                and new_meetings == 0
                and any(v in reply_low for v in COMPLETION_VERBS)
                and any(n in reply_low for n in ARTIFACT_NOUNS)
            )

            if need_meeting_audit or need_artifact_audit:
                audit_kind = "RAPAT FIKTIF" if need_meeting_audit else "ARTEFAK BELUM DIBUAT"
                logger.warning(f"[AUDIT] {audit_kind} terdeteksi -> pass koreksi ({model_name})")
                audit_parts = ["⛔ SISTEM AUDIT KEBENARAN:"]
                if need_meeting_audit:
                    audit_parts.append(
                        "TIDAK ADA rapat nyata dijalankan (tool conduct_ai_meeting tidak dipanggil).")
                if need_artifact_audit:
                    audit_parts.append(
                        "TIDAK ADA berkas baru tercipta di sistem, padahal jawabanmu mengklaim selesai.")
                audit_parts.append(
                    "Perbaiki SEKARANG: panggil tool pembuatnya secara nyata "
                    "(conduct_ai_meeting / execute_python_sandbox / generate_pdf_report / "
                    "generate_excel_spreadsheet / universal_deep_scraper) ATAU jawab jujur "
                    "bahwa belum dieksekusi. Dilarang klaim palsu."
                )
                contents.append(types.Content(
                    role="user",
                    parts=[types.Part.from_text(text="\n".join(audit_parts))]
                ))
                response2 = await gemini_client.aio.models.generate_content(
                    model=model_name,
                    contents=contents,
                    config=config
                )
                token_usage.from_gemini_response(response2, model=f"{model_name}:audit",
                                                 key_id=gkey_id,
                                                 key_label=gkey_label or "gemini-env",
                                                 context="telegram_chat")
                if response2.text and response2.text.strip():
                    reply_text = response2.text
                logger.warning(f"[AUDIT] Koreksi selesai ({audit_kind}); "
                               f"rapat baru: {_meetings_count() - meetings_before}; "
                               f"artefak berubah: {_artifact_signature() != art_before}")

            # Save model response to database
            await database.save_chat_message(user_id, "model", reply_text)
            return reply_text

        except Exception as e:
            logger.warning(f"Model {model_name} failed: {e}. Trying next candidate...")
            last_error = e

    logger.error(f"All candidate models failed: {last_error}", exc_info=True)
    return f"❌ Terjadi kesalahan saat memproses permintaan:\n`{str(last_error)}`"


# --- Telegram Command Handlers ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command."""
    user = update.effective_user
    chat_id = update.effective_chat.id
    if not is_authorized(user.id):
        await update.message.reply_text(
            f"⛔ *Akses Ditolak*\n\nID Anda: `{user.id}` belum terdaftar di whitelist bot.",
            parse_mode=constants.ParseMode.MARKDOWN
        )
        return

    keyboard = [
        [
            InlineKeyboardButton("📊 System Stats", callback_data="btn_stats"),
            InlineKeyboardButton("🧠 Memori", callback_data="btn_memory"),
        ],
        [
            InlineKeyboardButton("📈 Python Sandbox", callback_data="btn_python_info"),
            InlineKeyboardButton("🎙️ Toggle Voice", callback_data="btn_toggle_voice"),
        ],
        [
            InlineKeyboardButton("🧹 Reset Sesi", callback_data="btn_clear"),
            InlineKeyboardButton("📖 Bantuan & Tools", callback_data="btn_help"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    welcome_text = (
        f"🤖 **Personal Autonomous AI Agent**\n"
        f"Halo, **{user.first_name}**! Saya asisten AI otonom pribadi berbasis **Google Gemini API** yang terhubung langsung dengan mesin Linux Anda.\n\n"
        f"⚡ **Kemampuan & Tools Aktif (100% Real):**\n"
        f"• 🐍 **Python Sandbox & Data Plotter:** Eksekusi script & pembuatan grafik visual otomatis.\n"
        f"• 🖥️ **Desktop & Webcam Vision:** Screenshot layar desktop & snapshot webcam real-time.\n"
        f"• 🎙️ **Voice Notes (STT & TTS):** Kirim suara, AI membalas dengan suara natural Edge-TTS.\n"
        f"• 🌐 **Deep Web Intelligence:** DuckDuckGo search & ekstraksi konten artikel web.\n"
        f"• 🔍 **Workspace Intelligence:** Grep, find files, read/write file lokal.\n"
        f"• 🧠 **Persistent Long-Term Memory:** Memori permanen terisolasi per akun.\n"
        f"• ⏰ **Proactive Reminders:** Pengingat otomatis terjadwal.\n\n"
        f"Kirimkan pesan, pertanyaan, perintah bash, atau voice note langsung ke chat ini!"
    )
    await safe_send_message(context, chat_id, welcome_text, reply_markup=reply_markup)


async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /menu command."""
    user = update.effective_user
    chat_id = update.effective_chat.id
    if not is_authorized(user.id):
        return

    settings = await database.get_user_settings(user.id)
    voice_status = "ON 🔊" if settings.get("voice_reply") else "OFF 🔇"

    keyboard = [
        [
            InlineKeyboardButton("📊 System Stats", callback_data="btn_stats"),
            InlineKeyboardButton("🧠 Lihat Memori", callback_data="btn_memory"),
        ],
        [
            InlineKeyboardButton(f"🎙️ Suara: {voice_status}", callback_data="btn_toggle_voice"),
            InlineKeyboardButton("📈 Python & Plot", callback_data="btn_python_info"),
        ],
        [
            InlineKeyboardButton("🧹 Reset Konteks", callback_data="btn_clear"),
            InlineKeyboardButton("❓ Daftar Perintah", callback_data="btn_help"),
        ]
    ]
    await safe_send_message(context, chat_id, "🎛️ **Menu Kontrol Autonomous Agent:**", reply_markup=InlineKeyboardMarkup(keyboard))


async def cekagen_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/cekagen — audit kesehatan konfigurasi otak utama & agen swarm.
    Deteksi dini mismatch provider/kunci/model sebelum menimbulkan
    kegagalan senyap saat rapat atau chat."""
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        return

    import sqlite3 as _sq
    conn = _sq.connect(os.path.join(PROJECT_DIR, "agent_data.db"))
    conn.row_factory = _sq.Row
    try:
        brain_key = conn.execute(
            "SELECT value FROM system_settings WHERE key='main_brain_key_id'").fetchone()
        brain_model = conn.execute(
            "SELECT value FROM system_settings WHERE key='main_brain_model'").fetchone()
        bk = int(brain_key[0]) if brain_key else None
        bm = (brain_model[0] or "").strip() if brain_model else ""
        krow = conn.execute(
            "SELECT name,provider,default_model,is_active FROM api_keys WHERE id=?",
            (bk,)).fetchone() if bk else None

        lines = ["🩺 **AUDIT KONFIGURASI AGENT**\n"]
        if krow:
            ok_model = (bm == (krow["default_model"] or "").strip())
            lines.append(
                f"*Otak Utama:* key#{bk} `{krow['name']}` ({krow['provider']})\n"
                f"  Model override: `{bm}` {'✅' if ok_model else '⚠️ beda dari default kunci (`' + krow['default_model'] + '`)'}\n"
                f"  Status kunci: {'🟢 aktif' if krow['is_active'] else '🔴 NONAKTIF'}")
        else:
            lines.append("*Otak Utama:* ❌ pointer kosong/tidak valid!")

        lines.append("\n*Agen Swarm:*")
        problems = 0
        for a in conn.execute("SELECT name,provider,model,api_key_id,is_enabled FROM custom_agents ORDER BY id"):
            kid = a["api_key_id"]
            k2 = conn.execute(
                "SELECT provider,default_model,is_active FROM api_keys WHERE id=?",
                (kid,)).fetchone() if kid else None
            issues = []
            if not k2:
                issues.append("kunci hilang")
            else:
                if k2["provider"] != a["provider"]:
                    issues.append(f"kunci {k2['provider']} ≠ agen {a['provider']}")
                if not k2["is_active"]:
                    issues.append("kunci nonaktif/kuota bisa habis terpisah")
                if (a["model"] or "").strip() and a["model"].strip() != (k2["default_model"] or "").strip():
                    if a["provider"] == k2["provider"]:
                        issues.append(f"model '{a['model']}' ≠ default kunci")
            flag = "✅" if not issues else "❌"
            problems += len(issues)
            status = " | ".join(issues) if issues else "sehat"
            on = "" if a["is_enabled"] else " (off)"
            lines.append(f"  {flag} {a['name']}: {a['provider']}/{a['model']} → key#{kid} — {status}{on}")

        lines.append(
            f"\n{'🎉 Semua konfigurasi konsisten.' if problems == 0 else f'⚠️ {problems} masalah ditemukan.'}\n"
            "Perbaiki lewat Dashboard › API Key Vault / Agen Swarm.")
        await safe_send_message(context, update.effective_chat.id, "\n".join(lines))
    finally:
        conn.close()


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /stats command."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if not is_authorized(user_id):
        return

    stats = get_system_stats()
    text = (
        f"📊 **Status Server / Laptop Real-Time:**\n\n"
        f"• **CPU:** `{stats.get('cpu')}`\n"
        f"• **RAM:** `{stats.get('ram')}`\n"
        f"• **Swap:** `{stats.get('swap')}`\n"
        f"• **Disk:** `{stats.get('disk')}`\n"
        f"• **Power/Baterai:** `{stats.get('battery')}`\n"
        f"• **IP Addr:** `{stats.get('ip_addresses')}`\n"
        f"• **Uptime:** `{stats.get('uptime')}`\n\n"
        f"🔥 **Top RAM:**\n" + "\n".join([f"  - {p}" for p in stats.get('top_ram_processes', [])]) + "\n\n"
        f"⚡ **Top CPU:**\n" + "\n".join([f"  - {p}" for p in stats.get('top_cpu_processes', [])])
    )
    await safe_send_message(context, chat_id, text)


async def memory_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /memory command."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if not is_authorized(user_id):
        return

    memories = await database.get_all_memories(user_id)
    if not memories:
        await safe_send_message(
            context,
            chat_id,
            "🧠 **Memori Jangka Panjang Kosong.**\n\nAnda bisa menyuruh bot mengingat sesuatu, contoh:\n_\"Ingat bahwa port database staging adalah 5433\"_"
        )
        return

    text = f"🧠 **Memori Tersimpan ({len(memories)} item):**\n\n"
    for m in memories:
        text += f"• *[{m['category'].upper()}]* `{m['key_topic']}`:\n  {m['content']}\n\n"

    await safe_send_message(context, chat_id, text)


async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /clear command."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if not is_authorized(user_id):
        return

    await database.clear_user_chat_history(user_id)
    await safe_send_message(context, chat_id, "🧹 **Riwayat percakapan berhasil direset.** Memori jangka panjang tetap aman tersimpan!")


async def id_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /id command."""
    user = update.effective_user
    chat_id = update.effective_chat.id
    text = (
        f"👤 **Nama:** {user.full_name}\n"
        f"🆔 **Telegram ID:** `{user.id}`\n"
        f"💬 **Chat ID:** `{chat_id}`"
    )
    await safe_send_message(context, chat_id, text)


async def voice_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /voice toggle command."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if not is_authorized(user_id):
        return

    is_on = await database.toggle_voice_setting(user_id)
    status_str = "AKTIF 🔊 (Bot akan membalas dengan Voice Note & Teks)" if is_on else "NONAKTIF 🔇 (Bot membalas teks saja)"
    await safe_send_message(context, chat_id, f"🎙️ **Mode Suara:** {status_str}")


# --- Callback Query Handler for Inline Buttons ---
async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline button clicks."""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if not is_authorized(user_id):
        await query.edit_message_text("⛔ Akses ditolak.")
        return

    data = query.data
    if data == "btn_stats":
        stats = get_system_stats()
        text = (
            f"📊 **Status Server / Laptop Real-Time:**\n\n"
            f"• **CPU:** `{stats.get('cpu')}`\n"
            f"• **RAM:** `{stats.get('ram')}`\n"
            f"• **Swap:** `{stats.get('swap')}`\n"
            f"• **Disk:** `{stats.get('disk')}`\n"
            f"• **Power:** `{stats.get('battery')}`\n"
            f"• **IP:** `{stats.get('ip_addresses')}`\n"
            f"• **Uptime:** `{stats.get('uptime')}`\n\n"
            f"🔥 **Top RAM:**\n" + "\n".join([f"  - {p}" for p in stats.get('top_ram_processes', [])])
        )
        await safe_send_message(context, chat_id, text)

    elif data == "btn_memory":
        memories = await database.get_all_memories(user_id)
        if not memories:
            await safe_send_message(context, chat_id, "🧠 Memori jangka panjang masih kosong.")
        else:
            text = f"🧠 **Memori Tersimpan ({len(memories)} item):**\n\n"
            for m in memories:
                text += f"• *[{m['category'].upper()}]* `{m['key_topic']}`:\n  {m['content']}\n\n"
            await safe_send_message(context, chat_id, text)

    elif data == "btn_toggle_voice":
        is_on = await database.toggle_voice_setting(user_id)
        status_str = "AKTIF 🔊" if is_on else "NONAKTIF 🔇"
        await safe_send_message(context, chat_id, f"🎙️ Mode Balasan Suara sekarang: **{status_str}**")

    elif data == "btn_python_info":
        info_text = (
            "📈 **Python Sandbox & Data Plotter:**\n\n"
            "Anda dapat meminta bot untuk:\n"
            "• Menghitung data kompleks, rumus matematika, atau simulasi.\n"
            "• Membuat grafik statistik / visualisasi (misal: *'Buatkan grafik perbandingan penjualan 2024-2026'*).\n"
            "• Menjalankan snippet kode Python secara langsung.\n"
            "Grafik yang dihasilkan akan otomatis dikirimkan sebagai gambar langsung ke chat Telegram!"
        )
        await safe_send_message(context, chat_id, info_text)

    elif data == "btn_clear":
        await database.clear_user_chat_history(user_id)
        await safe_send_message(context, chat_id, "🧹 Konteks percakapan telah direset.")

    elif data == "btn_help":
        help_text = (
            "📖 **Daftar Perintah & Panduan Interaksi:**\n\n"
            "• `/menu` - Tampilkan tombol kontrol utama\n"
            "• `/wa` - Kontrol & pantau WhatsApp Google Sheets Bot\n"
            "• `/stats` - Cek performa CPU, RAM, Disk, & Baterai\n"
            "• `/memory` - Cek data memori jangka panjang\n"
            "• `/proactive` - Cek/atur inisiatif mandiri ambient bot\n"
            "• `/voice` - Hidupkan/matikan respon suara\n"
            "• `/clear` - Hapus riwayat chat (mulai sesi baru)\n"
            "• `/id` - Cek ID Telegram & Chat ID\n\n"
            "💬 **Contoh Perintah AI:**\n"
            "- *'Ambil screenshot desktop sekarang'* -> Mengirim foto layar aktif.\n"
            "- *'Cek status bot whatsapp'* -> Melihat kondisi wa-sheets-bot.\n"
            "- *'Restart wa sheets bot'* -> Merestart service WhatsApp bot.\n"
            "- *'Buatkan grafik plot fungsi sinus dan cosinus'* -> Menghasilkan gambar grafik.\n"
            "- *'Cari informasi berita AI terkini hari ini'* -> Browsing real-time.\n"
            "- *'Ingat bahwa email dev saya adalah admin@example.com'* -> Simpan memori.\n"
            "- *'Ingatkan saya jam 18:00 untuk evaluasi project'* -> Set pengingat otomatis."
        )
        await safe_send_message(context, chat_id, help_text)

    elif data == "btn_wa_status":
        res = tools.manage_wa_sheets_bot("status")
        st = "🟢 RUNNING (Aktif)" if res.get("is_running") else "🔴 STOPPED (Mati)"
        await safe_send_message(context, chat_id, f"📱 **Status WhatsApp Bot:** {st}\n\n```\n{res.get('details', '')}\n```")

    elif data == "btn_wa_restart":
        res = tools.manage_wa_sheets_bot("restart")
        await safe_send_message(context, chat_id, f"🔄 {res.get('message', 'Restart diproses.')}")

    elif data == "btn_wa_start":
        res = tools.manage_wa_sheets_bot("start")
        await safe_send_message(context, chat_id, f"▶️ {res.get('message', 'Start diproses.')}")

    elif data == "btn_wa_stop":
        res = tools.manage_wa_sheets_bot("stop")
        await safe_send_message(context, chat_id, f"⏹️ {res.get('message', 'Stop diproses.')}")


# --- Media & Document Artifact Auto-Dispatcher ---
async def check_and_send_media_artifacts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Checks if any screenshot, webcam frame, Python chart, or document (PDF, Excel, PPTX, ZIP)
    was created and dispatches it directly to the Telegram user.
    """
    chat_id = update.effective_chat.id
    if not os.path.exists(SANDBOX_DIR):
        return

    # 1. Standard named media
    named_media = [
        ("desktop_screen.png", "🖥️ Tangkapan Layar Desktop"),
        ("webcam_frame.jpg", "📷 Foto Kamera Webcam"),
        ("generated_plot.png", "📊 Grafik Visualisasi Data (Python)"),
        ("browser_screenshot.png", "🌐 Tangkapan Layar Browser (Camofox)"),
    ]

    for filename, caption in named_media:
        full_path = os.path.join(SANDBOX_DIR, filename)
        if os.path.exists(full_path) and os.path.getsize(full_path) > 0:
            try:
                with open(full_path, "rb") as photo_file:
                    await context.bot.send_photo(
                        chat_id=chat_id,
                        photo=photo_file,
                        caption=caption
                    )
            except Exception as send_err:
                logger.error(f"Failed to send media artifact {filename}: {send_err}")
            finally:
                try:
                    os.remove(full_path)
                except OSError:
                    pass

    # 2. Check all other files in sandbox (images, docs, code, archives, audio, video)
    for fname in os.listdir(SANDBOX_DIR):
        fpath = os.path.join(SANDBOX_DIR, fname)
        if tools.is_internal_sandbox_artifact(fname):
            continue
        if tools.is_source_code_file(fname):
            # Kode sumber tidak dikirim mentah ke chat; agent menulisnya
            # langsung di folder proyek lokal.
            continue
        if not os.path.isfile(fpath) or os.path.getsize(fpath) == 0:
            continue
        ext = os.path.splitext(fname)[1].lower()
        if ext in ['.png', '.jpg', '.jpeg', '.webp']:
            try:
                with open(fpath, "rb") as pf:
                    await context.bot.send_photo(
                        chat_id=chat_id,
                        photo=pf,
                        caption=f"📸 Berkas Gambar: {fname}"
                    )
            except Exception as img_err:
                logger.error(f"Failed to send image {fname}: {img_err}")
            finally:
                try:
                    os.remove(fpath)
                except OSError:
                    pass
        else:
            try:
                with open(fpath, "rb") as df:
                    await context.bot.send_document(
                        chat_id=chat_id,
                        document=df,
                        caption=f"📄 Berkas: {fname}"
                    )
            except Exception as doc_err:
                logger.error(f"Failed to send document {fname}: {doc_err}")
            finally:
                try:
                    os.remove(fpath)
                except OSError:
                    pass


def should_reply_with_text_instead_of_voice(text: str) -> bool:
    """
    Decide whether an AI response is best delivered as Text rather than a Voice Note.
    Returns True (send Text) if the reply contains code blocks, tables, commands, or heavy technical data.
    Returns False (send Voice Note) for conversational speech, summaries, and explanations.
    """
    # 1. Code blocks or raw command snippets
    if "```" in text:
        return True
    
    # 2. Markdown tables
    if "\n|" in text and ("|---" in text or "|:---" in text or "---|" in text):
        return True
        
    # 3. Multiple URLs/links
    import re
    urls = re.findall(r"https?://\S+", text)
    if len(urls) >= 2:
        return True
        
    # 4. Long structured technical lists (>900 chars with multiple bullet points)
    if len(text) > 900 and (text.count("\n- ") >= 4 or text.count("\n* ") >= 4 or text.count("\n1. ") >= 3):
        return True
        
    return False


# --- Multimodal & Message Handlers ---
async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming text messages."""
    if not update.message or not update.message.text:
        return
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if not is_authorized(user_id):
        await safe_send_message(context, chat_id, "⛔ Akses ditolak. ID Anda belum terdaftar di whitelist.")
        return

    user_text = update.message.text.strip()

    # Typing indicator
    stop_typing = asyncio.Event()
    typing_task = asyncio.create_task(send_typing_loop(chat_id, context, stop_typing, constants.ChatAction.TYPING))

    try:
        reply = await run_agent_turn(user_id=user_id, user_prompt=user_text, chat_id=chat_id)
    finally:
        stop_typing.set()
        await typing_task

    # Send text response
    await safe_send_message(context, chat_id, reply)

    # Auto-send any generated media/doc artifacts
    await check_and_send_media_artifacts(update, context)

    # If voice mode enabled and content is conversational, send voice note
    settings = await database.get_user_settings(user_id)
    if settings.get("voice_reply") and not should_reply_with_text_instead_of_voice(reply):
        voice_path = None
        try:
            await context.bot.send_chat_action(chat_id=chat_id, action=constants.ChatAction.RECORD_VOICE)
            voice_path = await tts_engine.text_to_speech_ogg(reply)
            with open(voice_path, "rb") as voice_file:
                await update.message.reply_voice(voice=voice_file)
        except Exception as tts_err:
            logger.error(f"TTS sending error: {tts_err}")
        finally:
            if voice_path and os.path.exists(voice_path):
                try:
                    os.remove(voice_path)
                except OSError:
                    pass


async def handle_voice_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle incoming Voice Notes & Audio.
    Smart Adaptive Reply: Sends ONLY ONE response (either Voice Note OR Text) based on content.
    """
    if not update.message:
        return
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if not is_authorized(user_id):
        await safe_send_message(context, chat_id, "⛔ Akses ditolak.")
        return

    voice = update.message.voice or update.message.audio
    if not voice:
        return

    stop_typing = asyncio.Event()
    typing_task = asyncio.create_task(send_typing_loop(chat_id, context, stop_typing, constants.ChatAction.RECORD_VOICE))
    reply = "❌ Maaf, terjadi kesalahan saat memproses pesan suaramu."

    try:
        # Download voice audio
        file_obj = await context.bot.get_file(voice.file_id)
        voice_bytes_io = io.BytesIO()
        await file_obj.download_to_memory(voice_bytes_io)
        voice_bytes = voice_bytes_io.getvalue()

        from google.genai import types
        mime = getattr(voice, "mime_type", None) or "audio/ogg"
        audio_part = types.Part.from_bytes(data=voice_bytes, mime_type=mime)

        prompt = "Dengarkan rekaman suara ini dengan teliti, pahami instruksi/pertanyaannya, dan berikan jawaban yang lengkap dan akurat."
        reply = await run_agent_turn(user_id=user_id, user_prompt=prompt, multimodal_parts=[audio_part], chat_id=chat_id)
    finally:
        stop_typing.set()
        await typing_task

    # Auto-send any generated media artifacts
    await check_and_send_media_artifacts(update, context)

    # Adaptive Single Reply Decision
    prefer_text = should_reply_with_text_instead_of_voice(reply)
    sent_voice = False

    if not prefer_text:
        voice_path = None
        try:
            await context.bot.send_chat_action(chat_id=chat_id, action=constants.ChatAction.RECORD_VOICE)
            voice_path = await tts_engine.text_to_speech_ogg(reply)
            with open(voice_path, "rb") as vf:
                await update.message.reply_voice(voice=vf)
            sent_voice = True
        except Exception as e:
            logger.error(f"TTS voice reply error: {e}, falling back to text")
            sent_voice = False
        finally:
            if voice_path and os.path.exists(voice_path):
                try:
                    os.remove(voice_path)
                except OSError:
                    pass

    # If response is better as text (has code/tables/urls) or TTS failed, send ONLY as text
    if not sent_voice:
        await safe_send_message(context, chat_id, reply)


async def handle_photo_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming photos & images for vision analysis."""
    if not update.message:
        return
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if not is_authorized(user_id):
        await safe_send_message(context, chat_id, "⛔ Akses ditolak.")
        return

    photos = update.message.photo
    if not photos:
        return

    caption = update.message.caption or "Analisis gambar ini secara detail."
    best_photo = photos[-1]

    stop_typing = asyncio.Event()
    typing_task = asyncio.create_task(send_typing_loop(chat_id, context, stop_typing, constants.ChatAction.UPLOAD_PHOTO))
    reply = "❌ Maaf, terjadi kesalahan saat memproses gambarmu."

    try:
        photo_file = await context.bot.get_file(best_photo.file_id)
        photo_bytes_io = io.BytesIO()
        await photo_file.download_to_memory(photo_bytes_io)
        photo_bytes = photo_bytes_io.getvalue()

        from google.genai import types
        image_part = types.Part.from_bytes(data=photo_bytes, mime_type="image/jpeg")

        reply = await run_agent_turn(user_id=user_id, user_prompt=caption, multimodal_parts=[image_part], chat_id=chat_id)
    finally:
        stop_typing.set()
        await typing_task

    await safe_send_message(context, chat_id, reply)
    await check_and_send_media_artifacts(update, context)


async def handle_document_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle incoming documents (PDF, TXT, code, Excel, CSV, and long Audio meeting files).
    """
    if not update.message:
        return
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if not is_authorized(user_id):
        await safe_send_message(context, chat_id, "⛔ Akses ditolak.")
        return

    doc = update.message.document
    if not doc:
        return

    caption = update.message.caption or "Analisis isi dokumen ini secara mendalam."
    file_name = doc.file_name or "file.bin"
    mime_type = doc.mime_type or "application/octet-stream"

    stop_typing = asyncio.Event()
    typing_task = asyncio.create_task(send_typing_loop(chat_id, context, stop_typing, constants.ChatAction.UPLOAD_DOCUMENT))
    reply = "❌ Maaf, terjadi kesalahan saat memproses dokumenmu."

    try:
        doc_file = await context.bot.get_file(doc.file_id)
        doc_bytes_io = io.BytesIO()
        await doc_file.download_to_memory(doc_bytes_io)
        doc_bytes = doc_bytes_io.getvalue()

        from google.genai import types
        
        # Audio meeting recording file (.mp3, .m4a, .wav, .aac, .ogg)
        if mime_type.startswith("audio/") or any(file_name.lower().endswith(ext) for ext in ['.mp3', '.m4a', '.wav', '.aac', '.flac', '.ogg']):
            audio_part = types.Part.from_bytes(data=doc_bytes, mime_type=mime_type if mime_type.startswith("audio/") else "audio/mp3")
            prompt = (
                f"Ini adalah rekaman audio/rapat '{file_name}'.\n"
                f"Instruksi Khusus: {caption}\n\n"
                f"Tugas Anda:\n"
                f"1. Buatkan Ringkasan Eksekutif (Executive Summary).\n"
                f"2. Notulen Rapat lengkap dengan poin-poin diskusi utama.\n"
                f"3. Keputusan Penting yang diambil.\n"
                f"4. Daftar Tindak Lanjut / Action Items beserta PIC/tanggung jawab jika disebutkan."
            )
            reply = await run_agent_turn(user_id=user_id, user_prompt=prompt, multimodal_parts=[audio_part], chat_id=chat_id)

        # PDF Document
        elif file_name.lower().endswith(".pdf") or mime_type == "application/pdf":
            try:
                import pypdf
                reader = pypdf.PdfReader(io.BytesIO(doc_bytes))
                extracted_text = ""
                for page_num, page in enumerate(reader.pages[:20]):
                    extracted_text += f"\n--- Halaman {page_num + 1} ---\n" + (page.extract_text() or "")
                
                prompt = f"Isi Dokumen PDF '{file_name}':\n```\n{extracted_text[:12000]}\n```\n\nInstruksi: {caption}"
                reply = await run_agent_turn(user_id=user_id, user_prompt=prompt, chat_id=chat_id)
            except Exception:
                pdf_part = types.Part.from_bytes(data=doc_bytes, mime_type="application/pdf")
                prompt = f"Dokumen PDF '{file_name}': {caption}"
                reply = await run_agent_turn(user_id=user_id, user_prompt=prompt, multimodal_parts=[pdf_part], chat_id=chat_id)

        # Text / Code / CSV Document
        else:
            try:
                text_content = doc_bytes.decode("utf-8", errors="replace")
                prompt = f"Isi file '{file_name}':\n```\n{text_content[:10000]}\n```\n\nInstruksi: {caption}"
                reply = await run_agent_turn(user_id=user_id, user_prompt=prompt, chat_id=chat_id)
            except Exception:
                doc_part = types.Part.from_bytes(data=doc_bytes, mime_type=mime_type)
                prompt = f"Dokumen '{file_name}': {caption}"
                reply = await run_agent_turn(user_id=user_id, user_prompt=prompt, multimodal_parts=[doc_part], chat_id=chat_id)

    finally:
        stop_typing.set()
        await typing_task

    await safe_send_message(context, chat_id, reply)
    await check_and_send_media_artifacts(update, context)


# --- Background Proactive Reminder Dispatcher ---
async def proactive_reminder_loop(application: Application):
    """Background task to poll and send scheduled reminders."""
    logger.info("Proactive reminder dispatcher started.")
    while True:
        try:
            due_reminders = await database.get_due_reminders()
            for r in due_reminders:
                rem_id = r["id"]
                chat_id = r["chat_id"]
                msg = r["message"]
                rem_time = r["reminder_time"]

                alert_text = (
                    f"⏰ **PENGINGAT OTOMATIS (REMINDER #{rem_id})**\n\n"
                    f"📌 **Pesan:** {msg}\n"
                    f"🕒 **Waktu:** `{rem_time}`"
                )
                try:
                    await safe_send_message(application, chat_id, alert_text)
                    await database.mark_reminder_executed(rem_id)
                    logger.info(f"Dispatched reminder #{rem_id} to chat {chat_id}")
                except Exception as send_err:
                    # Keep the reminder queued for retry unless it is stale (>24h overdue)
                    logger.error(f"Failed to dispatch reminder #{rem_id}: {send_err}. Will retry.")
                    try:
                        due_dt = datetime.fromisoformat(rem_time.replace("T", " "))
                        if (datetime.now() - due_dt).total_seconds() > 86400:
                            await database.mark_reminder_executed(rem_id)
                            logger.warning(f"Reminder #{rem_id} dropped: overdue >24h and undeliverable.")
                    except Exception:
                        await database.mark_reminder_executed(rem_id)
        except Exception as e:
            logger.error(f"Error in reminder loop: {e}")

        await asyncio.sleep(20)


# --- Background Proactive Recurring Cron & Watchdog Dispatcher ---
async def proactive_cron_watchdog_loop(application: Application):
    """Background task to execute scheduled recurring cron tasks & proactive watchdogs."""
    logger.info("Proactive cron watchdog loop started.")
    while True:
        try:
            due_jobs = await database.get_due_cron_jobs()
            for job in due_jobs:
                job_id = job["id"]
                user_id = job["user_id"]
                chat_id = job["chat_id"]
                title = job["title"]
                prompt = job["prompt_instruction"]
                interval = job["interval_minutes"]

                logger.info(f"Executing recurring cron task #{job_id}: '{title}' for user {user_id}")
                await database.update_cron_job_after_run(job_id, interval)

                cron_prompt = (
                    f"[TUGAS TERJADWAL OTONOM: {title.upper()}]\n"
                    f"Instruksi: {prompt}\n\n"
                    f"Jalankan tugas ini secara otonom menggunakan tools yang relevan dan laporkan hasilnya dengan rapi."
                )
                try:
                    result = await run_agent_turn(user_id=user_id, user_prompt=cron_prompt, chat_id=chat_id)
                    header = f"⏰ **[WATCHDOG / CRON TASK #{job_id}: {title.upper()}]**\n\n{result}"
                    await safe_send_message(application, chat_id, header)

                    # Send any generated documents/images
                    if os.path.isdir(SANDBOX_DIR):
                        for fname in os.listdir(SANDBOX_DIR):
                            fpath = os.path.join(SANDBOX_DIR, fname)
                            if tools.is_internal_sandbox_artifact(fname):
                                continue
                            if tools.is_source_code_file(fname):
                                continue
                            if os.path.isfile(fpath) and os.path.getsize(fpath) > 0:
                                ext = os.path.splitext(fname)[1].lower()
                                try:
                                    if ext in ['.png', '.jpg', '.jpeg', '.webp']:
                                        with open(fpath, "rb") as pf:
                                            await application.bot.send_photo(chat_id=chat_id, photo=pf, caption=f"📸 Lampiran Cron: {fname}")
                                    else:
                                        with open(fpath, "rb") as df:
                                            await application.bot.send_document(chat_id=chat_id, document=df, caption=f"📄 Lampiran Cron: {fname}")
                                    try:
                                        os.remove(fpath)
                                    except OSError:
                                        pass
                                except Exception as attach_err:
                                    logger.error(f"Failed to send cron attachment {fname}: {attach_err}")
                except Exception as run_err:
                    logger.error(f"Error executing cron job #{job_id}: {run_err}")
        except Exception as e:
            logger.error(f"Error in cron watchdog loop: {e}")

        await asyncio.sleep(25)


# --- GOD MODE: Proactive System Guardian Daemon ---
async def proactive_system_guardian_loop(application: Application):
    """Background daemon that monitors system health 24/7 and takes autonomous protective actions."""
    logger.info("🛡️ God Mode: System Guardian daemon started.")
    import json as _json
    config_path = os.path.join(os.path.expanduser("~"), ".alfa", "guardian_config.json")
    
    while True:
        try:
            if not os.path.exists(config_path):
                await asyncio.sleep(30)
                continue
            
            with open(config_path, "r") as f:
                config = _json.load(f)
            
            if not config.get("enabled", False):
                await asyncio.sleep(30)
                continue
            
            alerts = []
            
            # Check CPU
            cpu_pct = psutil.cpu_percent(interval=1)
            cpu_thresh = config.get("cpu_threshold", 90)
            if cpu_pct > cpu_thresh:
                alerts.append(f"🔴 **CPU** sangat tinggi: {cpu_pct}% (threshold: {cpu_thresh}%)")
            
            # Check RAM
            ram = psutil.virtual_memory()
            ram_thresh = config.get("ram_threshold", 85)
            if ram.percent > ram_thresh:
                alert_msg = f"🔴 **RAM** kritis: {ram.percent}% ({round(ram.used / (1024**3), 1)}/{round(ram.total / (1024**3), 1)} GB)"
                alerts.append(alert_msg)
                
                # Auto-kill RAM hogs if enabled
                if config.get("auto_kill_ram_hogs", False):
                    protected = {"python3", "systemd", "gnome-shell", "Xwayland", "pipewire", "dbus-daemon", "telegram-ai"}
                    killed = []
                    procs = sorted(psutil.process_iter(['pid', 'name', 'memory_info']), 
                                   key=lambda p: (p.info.get('memory_info') or type('', (), {'rss': 0})).rss, reverse=True)
                    for p in procs[:5]:
                        try:
                            pname = p.info.get('name', '')
                            if not any(prot in pname.lower() for prot in protected):
                                mem_mb = round(p.info['memory_info'].rss / (1024*1024), 1)
                                if mem_mb > 500:  # Only kill if using >500MB
                                    p.terminate()
                                    killed.append(f"{pname} ({mem_mb}MB)")
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            continue
                    if killed:
                        alerts.append(f"⚡ **Auto-Kill:** {', '.join(killed)}")
            
            # Check Disk
            disk = psutil.disk_usage("/")
            disk_thresh = config.get("disk_threshold", 90)
            if disk.percent > disk_thresh:
                alerts.append(f"🔴 **Disk** hampir penuh: {disk.percent}% ({round(disk.free / (1024**3), 1)} GB tersisa)")
            
            # Check Battery
            battery = psutil.sensors_battery()
            batt_thresh = config.get("battery_critical", 10)
            if battery and not battery.power_plugged and battery.percent <= batt_thresh:
                alerts.append(f"🔴 **Baterai KRITIS:** {battery.percent}% — Tidak sedang mengisi!")
            
            # Send alerts to all authorized users
            if alerts:
                alert_text = f"🛡️ **[SYSTEM GUARDIAN ALERT]**\n\n" + "\n".join(alerts)
                for uid in ALLOWED_USER_IDS:
                    try:
                        await safe_send_message(application, uid, alert_text)
                    except Exception:
                        pass
        except Exception as e:
            logger.error(f"Guardian daemon error: {e}")
        
        await asyncio.sleep(30)


# --- Background Focus & Pomodoro Watchdog ---
async def proactive_focus_session_loop(application: Application):
    """Background task to poll and notify completed focus/pomodoro sessions."""
    logger.info("🎯 Proactive focus session watchdog started.")
    while True:
        try:
            due_sessions = await database.get_due_focus_sessions()
            for s in due_sessions:
                s_id = s["id"]
                chat_id = s["chat_id"]
                title = s["title"]
                duration = s["duration_minutes"]
                notes = s.get("notes", "")
                
                alert_text = (
                    f"🎉 **[SESI FOKUS SELESAI!]**\n\n"
                    f"🎯 **Target:** {title}\n"
                    f"⏱️ **Durasi:** {duration} menit\n"
                    f"📝 **Catatan:** {notes if notes else 'Kerja bagus! Istirahatlah sejenak (5-10 menit) sebelum melanjutkan.'}"
                )
                try:
                    await safe_send_message(application, chat_id, alert_text)
                    await database.mark_focus_session_completed(s_id)
                    logger.info(f"Dispatched focus session completion #{s_id} to chat {chat_id}")
                except Exception as send_err:
                    logger.error(f"Failed to dispatch focus session #{s_id}: {send_err}")
                    await database.mark_focus_session_completed(s_id)
        except Exception as e:
            logger.error(f"Error in focus session loop: {e}")
            
        await asyncio.sleep(15)


# --- Background Ambient Proactive Engagement Loop ---
async def proactive_ambient_agent_loop(application: Application):
    """
    GOD MODE: Ambient Proactive Agent.
    Evaluates real-time ambient context (time of day, battery, system status, active memories)
    and autonomously initiates context-aware check-ins, briefings, or questions to the user.
    """
    logger.info("🤖 Ambient Proactive Agent loop started.")
    import json as _json
    config_path = os.path.join(os.path.expanduser("~"), ".alfa", "proactive_config.json")
    
    # Initial wait after startup before evaluation
    await asyncio.sleep(60)
    
    while True:
        cycle_backoff = 600  # default: evaluasi tiap 10 menit
        try:
            config = {"enabled": True, "min_hours_between_pings": 3, "quiet_hours_start": 23, "quiet_hours_end": 7}
            if os.path.exists(config_path):
                try:
                    with open(config_path, "r", encoding="utf-8") as f:
                        config = _json.load(f)
                except Exception:
                    pass

            if config.get("enabled", True):
                now_dt = datetime.now()
                current_hour = now_dt.hour
                q_start = config.get("quiet_hours_start", 23)
                q_end = config.get("quiet_hours_end", 7)

                # Hemat kuota free-tier: batas jumlah ping per hari
                today_str = now_dt.strftime("%Y-%m-%d")
                pings_today = config.get("pings_today", 0) if config.get("last_ping_date") == today_str else 0
                max_pings = int(config.get("max_pings_per_day", 4))

                # Check quiet hours (e.g. 23 to 7)
                is_quiet = False
                if q_start > q_end:
                    is_quiet = (current_hour >= q_start or current_hour < q_end)
                else:
                    is_quiet = (q_start <= current_hour < q_end)

                if is_quiet or pings_today >= max_pings:
                    pass  # diam di jam tenang / kuota ping harian habis
                else:
                    last_ping_str = config.get("last_ping_time")
                    should_evaluate = True
                    if last_ping_str:
                        try:
                            last_ping_dt = datetime.fromisoformat(last_ping_str)
                            elapsed_hours = (now_dt - last_ping_dt).total_seconds() / 3600.0
                            min_hours = config.get("min_hours_between_pings", 3)
                            if elapsed_hours < min_hours:
                                should_evaluate = False
                        except Exception:
                            pass
                            
                    if should_evaluate and gemini_client and ALLOWED_USER_IDS:
                        target_user = ALLOWED_USER_IDS[0]
                        day_names = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
                        now_formatted = f"{day_names[now_dt.weekday()]}, {now_dt.strftime('%d %B %Y pukul %H:%M WIB')}"
                        
                        batt = psutil.sensors_battery()
                        batt_status = f"{batt.percent}% ({'Mengisi daya ⚡' if batt.power_plugged else 'Menggunakan baterai 🔋'})" if batt else "Desktop / AC Power"
                        ram = psutil.virtual_memory()
                        ram_str = f"RAM terpakai {ram.percent}%"
                        
                        user_memories = await database.get_all_memories(target_user)
                        mem_samples = [f"{m['key_topic']}: {m['content']}" for m in user_memories[:4]]
                        memories_summary = "; ".join(mem_samples) if mem_samples else "Belum ada catatan proyek spesifik."
                        
                        proactive_eval_prompt = (
                            f"Kamu adalah ALFA, asisten AI otonom pribadi {OWNER_NAME} yang cerdas, proaktif, dan memiliki inisiatif sendiri.\n"
                            f"Kondisi real-time saat ini:\n"
                            f"- Waktu: {now_formatted}\n"
                            f"- Baterai: {batt_status}\n"
                            f"- Status Sistem: {ram_str}\n"
                            f"- Catatan Memori Proyek: {memories_summary}\n\n"
                            f"INSTRUKSI:\n"
                            f"Tentukan apakah kamu perlu secara mandiri menyapa, menanyakan progres proyek, atau mengingatkan sesuatu kepada {OWNER_NAME}.\n"
                            f"Pedoman:\n"
                            f"1. Jika waktu saat ini cocok untuk sapaan / check-in produktivitas / saran rehat / follow-up, buatlah pesan pendek yang natural, hangat, dan mengajukan 1 pertanyaan atau tawaran bantuan relevan (maks 2-3 kalimat).\n"
                            f"2. Jika saat ini tidak ada hal yang bernilai tinggi untuk disampaikan, balas hanya satu kata: NO_ACTION.\n"
                            f"3. DILARANG menggunakan format robotik kaku. Bersikaplah seperti partner asisten pribadi profesional."
                        )
                        
                        from google.genai import types
                        p_client, p_key_id, p_key_label = resolve_main_gemini()
                        if not p_client:
                            raise RuntimeError("Tidak ada API key Gemini aktif (vault/env) untuk loop proaktif.")
                        proactive_model = _main_brain_gemini_model()
                        resp = await p_client.aio.models.generate_content(
                            model=proactive_model,
                            contents=[types.Content(role="user", parts=[types.Part.from_text(text=proactive_eval_prompt)])]
                        )
                        token_usage.from_gemini_response(resp, model=proactive_model,
                                                         key_id=p_key_id,
                                                         key_label=p_key_label or "gemini-env",
                                                         context="proactive")
                        
                        reply_text = (resp.text or "").strip()
                        # Setiap evaluasi memakai kuota API (termasuk yang
                        # berujung NO_ACTION) — catat pemakaian harian di sini.
                        config["last_ping_date"] = today_str
                        config["pings_today"] = pings_today + 1

                        if reply_text and "NO_ACTION" not in reply_text.upper() and len(reply_text) > 10:
                            logger.info(f"Proactive agent initiated autonomous message to user {target_user}")
                            await safe_send_message(application, target_user, f"✨ **[INISIATIF MANDIRI ALFA]**\n\n{reply_text}")
                            await database.save_chat_message(target_user, "model", f"[Inisiatif Mandiri]: {reply_text}")

                            config["last_ping_time"] = now_dt.isoformat()

                        with open(config_path, "w", encoding="utf-8") as f:
                            _json.dump(config, f, indent=2)

        except Exception as e:
            logger.error(f"Error in proactive ambient loop: {e}")
            if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                cycle_backoff = 3600
                logger.warning("Kuota model habis (429) -> loop proaktif tidur 1 jam agar chat utama tetap punya jatah.")

        await asyncio.sleep(cycle_backoff)


# --- WhatsApp Sheets Bot Ecosystem Watchdog ---
async def proactive_ecosystem_watchdog_loop(application: Application):
    """
    Background watchdog that ensures wa-sheets-bot is automatically kept alive
    and immediately alerts Telegram if WhatsApp logs out.
    """
    logger.info("📱 WhatsApp Sheets Bot Ecosystem Watchdog started.")
    import socket
    
    def is_internet_connected():
        try:
            socket.create_connection(("1.1.1.1", 53), timeout=3)
            return True
        except OSError:
            return False
            
    last_known_auth_status = "UNKNOWN"
    status_file = os.path.expanduser("~/.alfa/wa_status.json")
    allowed_env = os.getenv("ALLOWED_USER_IDS", "").strip()
    primary_uid = int(allowed_env.split(",")[0].strip()) if allowed_env else None

    while True:
        try:
            online = await asyncio.to_thread(is_internet_connected)
            if online:
                # 1. Ensure service is active
                res = await asyncio.to_thread(
                    lambda: subprocess.run(["systemctl", "--user", "is-active", "wa-sheets-bot.service"], capture_output=True, text=True)
                )
                state = res.stdout.strip()
                if state in ["inactive", "failed"]:
                    logger.info("🌐 Internet connected & wa-sheets-bot is offline. Auto-starting wa-sheets-bot.service...")
                    await asyncio.to_thread(
                        lambda: subprocess.run(["systemctl", "--user", "start", "wa-sheets-bot.service"], capture_output=True, text=True)
                    )

                # 2. Check WhatsApp authentication status & alert if logged out
                if os.path.exists(status_file) and primary_uid:
                    try:
                        with open(status_file, "r") as f:
                            wa_data = json.load(f)
                        current_status = wa_data.get("status", "UNKNOWN")
                        qr_str = wa_data.get("qr", "")
                        
                        # Detect transition: was READY/AUTHENTICATED, now QR_READY or LOGGED_OUT
                        if last_known_auth_status in ["READY", "AUTHENTICATED"] and current_status in ["QR_READY", "LOGGED_OUT", "DISCONNECTED"]:
                            logger.warning(f"🚨 WhatsApp logged out! Sending instant alarm to Telegram user {primary_uid}...")
                            alarm_text = (
                                "🚨 **ALARM: WhatsApp Web Logout / Sesi Terputus!**\n\n"
                                "Bot mendeteksi sesi WhatsApp kamu telah keluar (*logged out*).\n"
                                "📲 **QR Code baru telah siap!** Silakan scan QR code di atas atau buka di browser:\n"
                                "👉 [http://localhost:8080](http://localhost:8080) (Tab Services Hub)\n\n"
                                "Ketik `/wa` untuk kontrol penuh."
                            )
                            if qr_str:
                                import qrcode
                                import io
                                img = qrcode.make(qr_str)
                                buf = io.BytesIO()
                                img.save(buf, format="PNG")
                                buf.seek(0)
                                await application.bot.send_photo(
                                    chat_id=primary_uid,
                                    photo=buf,
                                    caption=alarm_text,
                                    parse_mode="Markdown"
                                )
                            else:
                                await application.bot.send_message(
                                    chat_id=primary_uid,
                                    text=alarm_text,
                                    parse_mode="Markdown"
                                )
                                
                        last_known_auth_status = current_status
                    except Exception as e:
                        logger.error(f"Error checking WA status in watchdog: {e}")
                        
        except Exception as e:
            logger.error(f"Ecosystem watchdog error: {e}")
            
        await asyncio.sleep(15)


async def post_init(application: Application):
    """Post initialization hook."""
    await database.init_db()
    
    # Connect Subagent swarm to Telegram app instance
    import subagents
    subagents.set_telegram_app(application)
    
    # Start background dispatchers
    asyncio.create_task(proactive_reminder_loop(application))
    asyncio.create_task(proactive_cron_watchdog_loop(application))
    asyncio.create_task(proactive_system_guardian_loop(application))
    asyncio.create_task(proactive_focus_session_loop(application))
    asyncio.create_task(proactive_ambient_agent_loop(application))
    asyncio.create_task(proactive_ecosystem_watchdog_loop(application))


# --- Additional Command Handlers ---
async def cron_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List scheduled recurring tasks."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if not is_authorized(user_id):
        await safe_send_message(context, chat_id, "⛔ Akses ditolak.")
        return

    jobs = database.list_cron_jobs_sync(user_id)
    if not jobs:
        await safe_send_message(context, chat_id, "⏰ Belum ada tugas berulang (cron/watchdog) yang aktif.\n\nContoh membuat: *'Jadwalkan pantau server tiap 30 menit'*.")
        return

    text = f"⏰ **Daftar Tugas Berulang & Watchdog ({len(jobs)} tugas):**\n\n"
    for j in jobs:
        status_icon = "🟢 Aktif" if j['is_active'] else "🔴 Nonaktif"
        text += f"• **#{j['id']} {j['title']}** ({status_icon})\n"
        text += f"  - Interval: Setiap {j['interval_minutes']} menit\n"
        text += f"  - Instruksi: `{j['prompt_instruction']}`\n"
        text += f"  - Jadwal Berikutnya: `{j['next_run']}`\n\n"

    await safe_send_message(context, chat_id, text)


async def proactive_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /proactive command to view or toggle ambient proactive intelligence."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if not is_authorized(user_id):
        return
        
    config = tools.proactive_ambient_agent_config("status")
    p_cfg = config.get("proactive_config", {})
    status_str = "🟢 AKTIF" if p_cfg.get("enabled", True) else "🔴 NONAKTIF"
    
    text = (
        f"🤖 **Status Inisiatif Proaktif Otonom:**\n\n"
        f"• **Status:** {status_str}\n"
        f"• **Jeda Inisiatif:** Minimal setiap `{p_cfg.get('min_hours_between_pings', 3)}` jam\n"
        f"• **Jam Tenang (Quiet Hours):** `{p_cfg.get('quiet_hours_start', 23)}:00` s/d `{p_cfg.get('quiet_hours_end', 7)}:00`\n"
        f"• **Waktu Terakhir:** `{p_cfg.get('last_ping_time', 'Belum pernah')}`\n\n"
        f"💡 _Saat aktif, bot akan berinisiatif mandiri menyapa, menanyakan progres tugas, atau mengingatkan sesuatu berdasarkan waktu & kondisi laptop._"
    )
    await safe_send_message(context, chat_id, text)


async def wa_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /wa or /washeets command to control WhatsApp Google Sheets Bot."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if not is_authorized(user_id):
        return

    res = tools.manage_wa_sheets_bot("status")
    is_running = res.get("is_running", False)
    status_icon = "🟢 RUNNING (Aktif)" if is_running else "🔴 STOPPED (Mati)"

    wa_auth_status = "UNKNOWN"
    qr_str = ""
    status_file = os.path.expanduser("~/.alfa/wa_status.json")
    if os.path.exists(status_file):
        try:
            with open(status_file, "r") as f:
                wa_data = json.load(f)
            wa_auth_status = wa_data.get("status", "UNKNOWN")
            qr_str = wa_data.get("qr", "")
        except Exception:
            pass

    keyboard = [
        [
            InlineKeyboardButton("🔄 Restart WA Bot", callback_data="btn_wa_restart"),
            InlineKeyboardButton("📊 Cek Status", callback_data="btn_wa_status"),
        ],
        [
            InlineKeyboardButton("▶️ Start WA Bot", callback_data="btn_wa_start"),
            InlineKeyboardButton("⏹️ Stop WA Bot", callback_data="btn_wa_stop"),
        ],
        [
            InlineKeyboardButton("🌐 Buka Web Dashboard", url="http://localhost:8080"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    auth_desc = "✅ Terhubung (Logged In)" if wa_auth_status == "READY" else f"⚠️ {wa_auth_status} (Perlu Scan QR)"

    text = (
        f"📱 **Manajer WhatsApp Google Sheets Bot:**\n\n"
        f"• **Status Layanan:** {status_icon}\n"
        f"• **Status Akun WA:** `{auth_desc}`\n"
        f"• **Auto-Start Saat Boot/Internet:** `{'Aktif 🟢' if res.get('enabled_on_boot') else 'Nonaktif 🔴'}`\n"
        f"• **Service Name:** `wa-sheets-bot.service`\n\n"
        f"💡 _Bot WhatsApp ini otomatis aktif saat laptop online dan diawasi 24/7 oleh Ecosystem Watchdog._"
    )

    if wa_auth_status == "QR_READY" and qr_str:
        try:
            import qrcode
            import io
            img = qrcode.make(qr_str)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            buf.seek(0)
            await context.bot.send_photo(
                chat_id=chat_id,
                photo=buf,
                caption=f"📲 **SCAN QR CODE WHATSAPP SEKARANG**\n\n{text}",
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
            return
        except Exception as e:
            logger.error(f"Failed to generate QR photo: {e}")

    await safe_send_message(context, chat_id, text, reply_markup=reply_markup)
async def dashboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /dashboard or /web command."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if not is_authorized(user_id):
        return
        
    res = tools.open_web_dashboard(port=8080)
    text = (
        f"🛸 **ALFA SOVEREIGN COMMAND CENTER (Web Dashboard):**\n\n"
        f"• **Akses Lokal (Laptop):** `{res.get('local_url')}`\n"
        f"• **Akses Jaringan (HP / WiFi):** `{res.get('network_url')}`\n\n"
        f"⚡ **Fitur Dashboard:**\n"
        f"1. 📊 Live Telemetry Hardware & Gauges Real-time\n"
        f"2. ⚡ 75+ Tools Arsenal Explorer & Interactive Runner\n"
        f"3. 📱 Ecosystem Hub (Telegram & WA Sheets Bot Controller)\n"
        f"4. 🧠 Second Brain & Semantic Knowledge Graph Visualizer\n"
        f"5. 🛡️ 24/7 System Guardian & Proactive Watchdogs Config\n"
        f"6. 💬 Live Web AI Interactive Console\n"
        f"7. 🤖 AI Agent Workforce & Ruang Rapat (Multi-Agent Swarm)\n"
        f"8. 🔑 Multi-Provider API Key Vault"
    )
    await safe_send_message(context, chat_id, text)


async def keys_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /keys command to manage API keys vault."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if not is_authorized(user_id):
        return

    keys = database.list_api_keys_sync()
    if not keys:
        text = "🔑 **API Key Vault Kosong.** Tambahkan via Web Dashboard (http://localhost:8080) atau gunakan perintah tool."
    else:
        text = "🔑 **Multi-Provider API Key Vault:**\n\n"
        for k in keys:
            act = "🟢 *[ACTIVE]*" if k["is_active"] else "⚪"
            text += f"{act} **{k['name']}** (`{k['provider'].upper()}`)\n"
            text += f"   • Key: `{k['masked_key']}` | Model: `{k['default_model']}`\n\n"
        text += "💡 _Kelola, uji koneksi, & tambah key baru dengan mudah via Web Dashboard di tab API Key Vault._"
    await safe_send_message(context, chat_id, text)


async def agents_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /agents or /swarm command to view autonomous AI workforce."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if not is_authorized(user_id):
        return

    agents = database.list_custom_agents_sync()
    if not agents:
        text = "🤖 **Belum ada AI Agent terdaftar.**"
    else:
        text = "🤖 **ALFA Autonomous AI Agent Workforce:**\n\n"
        for a in agents:
            status = "🟢 Aktif" if a.get("is_enabled", 1) else "🔴 Nonaktif"
            text += f"{a.get('avatar_emoji', '🤖')} **{a['name']}** ({status})\n"
            text += f"   • Role: *{a['role']}*\n"
            text += f"   • Model: `{a['provider']}/{a['model']}`\n\n"
        text += "💡 _Mulai rapat antar agent dengan perintah `/rapat <topik>` atau via Web Dashboard!_"
    await safe_send_message(context, chat_id, text)


async def rapat_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /rapat or /meeting command to conduct an autonomous round-table meeting (Plan Mode)."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if not is_authorized(user_id):
        return

    topic = " ".join(context.args).strip() if context.args else ""
    if not topic:
        text = (
            "🏛️ **Panduan Ruang Rapat AI (Mode 1: Plan):**\n\n"
            "Format: `/rapat <topik / masalah yang ingin dibahas>`\n\n"
            "**Contoh:**\n"
            "• `/rapat Desain arsitektur database baru untuk auto-sync WhatsApp ke cloud`\n"
            "• `/rapat Strategi meningkatkan performa agent bot dan penghematan token API`\n\n"
            "💡 _Para agent akan berdebat, berdiskusi, dan merumuskan Action Plan!_\n"
            "⚡ _Untuk menyuruh agent langsung bekerja & mengeksekusi tugas nyata, gunakan `/swarm <perintah>`!_"
        )
        await safe_send_message(context, chat_id, text)
        return

    await safe_send_message(
        context, chat_id, 
        f"🏛️ **Membuka Rapat Perencanaan AI...**\n\n"
        f"📋 **Agenda:** _{topic}_\n"
        f"👥 Memanggil para agent spesialis untuk memulai diskusi round-table. Mohon tunggu..."
    )

    try:
        import swarm_engine
        result = await swarm_engine.conduct_multi_agent_meeting(topic=topic, rounds=2, mode="plan")
        
        # Send summary of transcript
        transcript = result.get("dialogue_transcript", [])
        dialogue_text = "🗣️ **Transkrip Diskusi Antar Agent:**\n\n"
        for d in transcript[:6]:
            dialogue_text += f"{d.get('avatar_emoji', '🤖')} **{d['agent_name']}** ({d['role']}):\n{d['message'][:350]}...\n\n"

        await safe_send_message(context, chat_id, dialogue_text)

        # Send Final Consensus & Action Plan
        final_text = (
            f"🎯 **KONSENSUS & KEPUTUSAN RAPAT:**\n\n"
            f"{result.get('consensus', '')}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📋 **ACTION PLAN / LANGKAH KERJA:**\n\n"
            f"{result.get('action_plan', '')}\n\n"
            f"🌐 _Transkrip lengkap tersimpan di Web Dashboard (ID: #{result.get('meeting_id')})_"
        )
        await safe_send_message(context, chat_id, final_text)

    except Exception as e:
        logger.error(f"Error during Telegram /rapat meeting: {e}")
        await safe_send_message(context, chat_id, f"❌ Terjadi kesalahan saat rapat agent: {str(e)}")


async def swarm_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /swarm or /eksekusi command to trigger live collaborative tool execution (Execute Mode)."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if not is_authorized(user_id):
        return

    topic = " ".join(context.args).strip() if context.args else ""
    if not topic:
        text = (
            "⚡ **Panduan Swarm Eksekusi Langsung (Mode 2: Bekerja Nyata):**\n\n"
            "Format: `/swarm <perintah / tugas nyata yang ingin dikerjakan bersama>`\n\n"
            "**Contoh:**\n"
            "• `/swarm Scrape 20 mouse gaming terlaris di Shopee & Tokopedia dan buatkan CSV-nya`\n"
            "• `/swarm Buatkan script Python monitoring RAM/CPU dan jalankan di sandbox`\n"
            "• `/swarm Audit port lokal dan status keamanan server`\n\n"
            "💡 _Seluruh tim agen AI akan langsung membagi tugas, menjalankan tools live, dan mengirimkan file hasil ke Telegram kamu!_"
        )
        await safe_send_message(context, chat_id, text)
        return

    await safe_send_message(
        context, chat_id, 
        f"⚡ **Membangunkan AI Swarm & Mengeksekusi Tugas Nyata...**\n\n"
        f"📌 **Tugas:** _{topic}_\n"
        f"🛠️ Alpha Lead, Researcher Prime, Code Crafter, dan Cyber Sentry sedang mengeksekusi tools. Mohon tunggu..."
    )

    try:
        import swarm_engine
        result = await swarm_engine.conduct_multi_agent_meeting(topic=topic, rounds=1, mode="execute")
        
        # Send execution steps breakdown
        steps = result.get("execution_results", [])
        steps_text = "⚡ **Laporan Eksekusi Tiap Agen:**\n\n"
        for s in steps:
            steps_text += f"{s.get('avatar_emoji', '🤖')} **{s['agent_name']}** ({s['role']})\n"
            steps_text += f"   • Tool: `{s['tool_used']}` ({s['duration_ms']}ms)\n"
            steps_text += f"   • Output: _{s['execution_summary'][:200]}_\n\n"

        await safe_send_message(context, chat_id, steps_text)

        # Send Final Consensus Report
        final_text = (
            f"🏆 **LAPORAN HASIL EKSEKUSI NYATA:**\n\n"
            f"{result.get('consensus', '')}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🌐 _ID Sesi: #{result.get('meeting_id')} • Tersimpan di Web Dashboard & Dokumen_"
        )
        await safe_send_message(context, chat_id, final_text)

        # Automatically send generated deliverable files to Telegram if any!
        for s in steps:
            fpath = s.get("deliverable_file")
            if fpath and os.path.exists(fpath):
                try:
                    with open(fpath, "rb") as f_doc:
                        await context.bot.send_document(
                            chat_id=chat_id,
                            document=f_doc,
                            filename=os.path.basename(fpath),
                            caption=f"📁 **File Deliverable Hasil Swarm ({s['agent_name']}):**\n`{os.path.basename(fpath)}`"
                        )
                except Exception as file_err:
                    logger.warning(f"Failed to send deliverable file to Telegram: {file_err}")

    except Exception as e:
        logger.error(f"Error during Telegram /swarm execution: {e}")
        await safe_send_message(context, chat_id, f"❌ Terjadi kesalahan saat eksekusi swarm: {str(e)}")


def main():
    """Main application launcher."""
    if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "your_telegram_bot_token_here":
        print("❌ ERROR: TELEGRAM_BOT_TOKEN belum disetel di .env!")
        sys.exit(1)

    if not GEMINI_API_KEY or GEMINI_API_KEY == "your_gemini_api_key_here":
        print("⚠️ PERINGATAN: GEMINI_API_KEY belum diisi di .env.")

    print("🚀 Menginisialisasi Ultra-Advanced Telegram AI Agent Bot...")
    application = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    # Command handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("menu", menu_command))
    application.add_handler(CommandHandler("dashboard", dashboard_command))
    application.add_handler(CommandHandler("web", dashboard_command))
    application.add_handler(CommandHandler("wa", wa_command))
    application.add_handler(CommandHandler("washeets", wa_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("cekagen", cekagen_command))
    application.add_handler(CommandHandler("memory", memory_command))
    application.add_handler(CommandHandler("cron", cron_command))
    application.add_handler(CommandHandler("tasks", cron_command))
    application.add_handler(CommandHandler("proactive", proactive_command))
    application.add_handler(CommandHandler("keys", keys_command))
    application.add_handler(CommandHandler("vault", keys_command))
    application.add_handler(CommandHandler("agents", agents_command))
    application.add_handler(CommandHandler("swarm", swarm_command))
    application.add_handler(CommandHandler("eksekusi", swarm_command))
    application.add_handler(CommandHandler("rapat", rapat_command))
    application.add_handler(CommandHandler("meeting", rapat_command))
    application.add_handler(CommandHandler("clear", clear_command))
    application.add_handler(CommandHandler("reset", clear_command))
    application.add_handler(CommandHandler("id", id_command))
    application.add_handler(CommandHandler("voice", voice_command))
    application.add_handler(CommandHandler("help", start_command))

    # Callback Query (Buttons)
    application.add_handler(CallbackQueryHandler(handle_callback_query))
    application.add_handler(CallbackQueryHandler(
        permission_gate.handle_permission_callback, pattern=r"^perm\|"))

    # Multimodal message handlers
    application.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_voice_message))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo_message))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document_message))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))

    print(f"✅ Bot Telegram Otonom siap melayani! Menunggu interaksi...")
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()


