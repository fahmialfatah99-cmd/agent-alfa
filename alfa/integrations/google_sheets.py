"""Google Sheets Integration for ALFA - AI-Powered Material Tracking & Cloud Sync.

Provides structured parsing of material retrieval/transfer requests (DO/TO/Nota/Chat)
using LLM AI, and records them neatly into Google Sheets and local Google Drive mounts.
"""

import datetime
import json
import logging
import os
from typing import Any

from alfa.core import database
from alfa.core.config import ensure_env_loaded

logger = logging.getLogger("AgentTools.GoogleSheets")
ensure_env_loaded()

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
WA_BOT_DIR = os.path.expanduser("~/wa-sheets-bot")
WA_KEY_FILE = os.path.join(WA_BOT_DIR, "service-account.json")
GDRIVE_KEY_FILE = os.path.join(REPO_ROOT, "gdrive_credentials.json")

PENGAMBILAN_HEADERS = [
    "Waktu",
    "No. Dokumen / Form",
    "Cluster / Site",
    "Nama Material / Item",
    "QTY",
    "Satuan",
    "PIC / Pengambil",
    "Pengirim",
    "Keterangan / Isi Pesan",
]

TRANSFER_ORDER_HEADERS = PENGAMBILAN_HEADERS
MATERIAL_HEADERS = PENGAMBILAN_HEADERS
DEFAULT_TAB_NAME = "Pengambilan Material"


def get_sheets_service() -> Any:
    """Initialize and return Google Sheets v4 API resource service."""
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    scopes = ["https://www.googleapis.com/auth/spreadsheets"]

    # 1. Try wa-sheets-bot service-account.json
    if os.path.exists(WA_KEY_FILE):
        try:
            with open(WA_KEY_FILE, encoding="utf-8") as f:
                kdata = json.load(f)
            creds = service_account.Credentials.from_service_account_info(kdata, scopes=scopes)
            return build("sheets", "v4", credentials=creds)
        except Exception as e:
            logger.warning(f"Failed to load WA service-account.json: {e}")

    # 2. Try project gdrive_credentials.json
    if os.path.exists(GDRIVE_KEY_FILE):
        try:
            with open(GDRIVE_KEY_FILE, encoding="utf-8") as f:
                kdata = json.load(f)
            creds = service_account.Credentials.from_service_account_info(kdata, scopes=scopes)
            return build("sheets", "v4", credentials=creds)
        except Exception as e:
            logger.warning(f"Failed to load gdrive_credentials.json: {e}")

    raise ValueError(
        "Kredensial Service Account Google Sheets belum tersedia. "
        "Pastikan file service-account.json tersedia di ~/wa-sheets-bot/ atau unggah di Dashboard."
    )


def get_spreadsheet_id() -> str:
    """Retrieve active Spreadsheet ID from system_settings, .env, or wa-sheets-bot/.env."""
    try:
        with database.get_sync_db() as conn:
            row = conn.execute(
                "SELECT value FROM system_settings WHERE key = 'material_spreadsheet_id' OR key = 'wa_spreadsheet_id' ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if row and row[0] and str(row[0]).strip():
                return str(row[0]).strip()
    except Exception:
        pass

    env_val = os.getenv("SPREADSHEET_ID", "").strip() or os.getenv("MATERIAL_SPREADSHEET_ID", "").strip()
    if env_val:
        return env_val

    # Read from ~/wa-sheets-bot/.env
    wa_env_path = os.path.join(WA_BOT_DIR, ".env")
    if os.path.exists(wa_env_path):
        try:
            with open(wa_env_path, encoding="utf-8") as f:
                for line in f:
                    if line.startswith("SPREADSHEET_ID="):
                        val = line.split("=", 1)[1].strip().strip('"').strip("'")
                        if val:
                            return val
        except Exception:
            pass

    return "1d9Mr1IZszP1Cq34VN1_OTHtWokxDdV4prywsgVxN0RQ"


def set_spreadsheet_id(new_id: str) -> dict[str, Any]:
    """
    Update active Google Sheets ID across system settings, .env, and wa-sheets-bot.
    Automatically validates access and creates the material tracking tab.
    """
    clean_id = new_id.strip()
    # Extract ID if user pasted full Google Sheets URL
    if "spreadsheets/d/" in clean_id:
        try:
            clean_id = clean_id.split("spreadsheets/d/")[1].split("/")[0]
        except Exception:
            pass

    if not clean_id or len(clean_id) < 15:
        return {"status": "error", "message": f"Format Spreadsheet ID tidak valid: '{new_id}'"}

    # 1. Update database
    try:
        with database.get_sync_db() as conn:
            conn.execute(
                "INSERT INTO system_settings (key, value) VALUES ('material_spreadsheet_id', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (clean_id,),
            )
            conn.execute(
                "INSERT INTO system_settings (key, value) VALUES ('wa_spreadsheet_id', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (clean_id,),
            )
            conn.commit()
    except Exception as e:
        logger.warning(f"Could not persist spreadsheet ID to DB: {e}")

    # 2. Update ~/wa-sheets-bot/.env
    wa_env_path = os.path.join(WA_BOT_DIR, ".env")
    if os.path.exists(wa_env_path):
        try:
            lines = []
            replaced = False
            with open(wa_env_path, encoding="utf-8") as f:
                for line in f:
                    if line.startswith("SPREADSHEET_ID="):
                        lines.append(f"SPREADSHEET_ID={clean_id}\n")
                        replaced = True
                    else:
                        lines.append(line)
            if not replaced:
                lines.append(f"SPREADSHEET_ID={clean_id}\n")
            with open(wa_env_path, "w", encoding="utf-8") as f:
                f.writelines(lines)
        except Exception as e:
            logger.warning(f"Could not update wa-sheets-bot .env: {e}")

    # 3. Test and initialize tab
    init_res = ensure_material_sheet_tab(spreadsheet_id=clean_id)
    if init_res.get("status") != "success":
        return {
            "status": "warning",
            "spreadsheet_id": clean_id,
            "message": (
                f"Spreadsheet ID berhasil disetel ke '{clean_id}', namun akses Google Sheets "
                f"menghasilkan peringatan: {init_res.get('message')}. "
                "Pastikan Anda telah membagikan (Share) spreadsheet baru tersebut ke email Service Account:\n"
                "ais-gemini-key-557267392dac418@30020894332.iam.gserviceaccount.com (sebagai Editor)."
            ),
        }

    # Restart wa-sheets-bot so it reloads the new spreadsheet ID immediately
    try:
        import subprocess
        subprocess.run(["systemctl", "--user", "restart", "wa-sheets-bot.service"], check=False)
    except Exception:
        pass

    return {
        "status": "success",
        "spreadsheet_id": clean_id,
        "spreadsheet_title": init_res.get("title", ""),
        "tab_name": DEFAULT_TAB_NAME,
        "message": (
            f"🎉 Konfigurasi Spreadsheet baru berhasil terhubung! "
            f"Tab '{DEFAULT_TAB_NAME}' telah siap menerima pencatatan material."
        ),
    }


def ensure_material_sheet_tab(
    spreadsheet_id: str = "",
    tab_name: str = DEFAULT_TAB_NAME,
    headers: list[str] | None = None,
) -> dict[str, Any]:
    """Ensure target tab exists with standardized columns in Google Sheets."""
    sid = spreadsheet_id or get_spreadsheet_id()
    if not sid:
        return {"status": "error", "message": "Spreadsheet ID belum dikonfigurasi."}

    if headers is None:
        if tab_name.strip().upper() == "TRANSFER ORDER":
            headers = TRANSFER_ORDER_HEADERS
        elif "pengambilan material" in tab_name.lower():
            headers = PENGAMBILAN_HEADERS
        else:
            headers = PENGAMBILAN_HEADERS if "pengambilan" in tab_name.lower() else TRANSFER_ORDER_HEADERS

    try:
        service = get_sheets_service()
        meta = service.spreadsheets().get(spreadsheetId=sid, fields="properties.title,sheets.properties").execute()
        sheet_title = meta.get("properties", {}).get("title", "")
        existing_tabs = [s.get("properties", {}).get("title") for s in meta.get("sheets", [])]

        target_exists = any(t.lower() == tab_name.lower() for t in existing_tabs if t)

        if not target_exists:
            # Create new tab
            service.spreadsheets().batchUpdate(
                spreadsheetId=sid,
                body={"requests": [{"addSheet": {"properties": {"title": tab_name}}}]},
            ).execute()
            logger.info(f"Created new tab '{tab_name}' in spreadsheet {sid}")

        # Check headers on row 1
        val_res = service.spreadsheets().values().get(spreadsheetId=sid, range=f"'{tab_name}'!A1:K1").execute()
        rows = val_res.get("values", [])
        if not rows or len(rows[0]) < len(headers):
            service.spreadsheets().values().update(
                spreadsheetId=sid,
                range=f"'{tab_name}'!A1",
                valueInputOption="USER_ENTERED",
                body={"values": [headers]},
            ).execute()
            logger.info(f"Initialized headers in '{tab_name}'")

        return {
            "status": "success",
            "title": sheet_title,
            "tab_name": tab_name,
            "spreadsheet_id": sid,
        }
    except Exception as e:
        err_msg = str(e)
        if "The caller does not have permission" in err_msg or "403" in err_msg:
            err_msg += (
                " -> Solusi: Bagikan (Share) Google Sheet ke email Service Account: "
                "ais-gemini-key-557267392dac418@30020894332.iam.gserviceaccount.com sebagai Editor."
            )
        return {"status": "error", "message": f"Gagal mengakses Google Sheet: {err_msg}"}


def is_whatsapp_source(source: str, context: str = "") -> bool:
    """
    Validasi ketat: pastikan data yang disimpan ke spreadsheet HANYA
    bersumber dari chat WhatsApp (grup/kontak WhatsApp), bukan percakapan
    Telegram, bot interaktif, dokumen/file, atau sumber non-WhatsApp lainnya.
    """
    if not source and not context:
        return False

    s_raw = str(source or "").strip().lower()
    ctx_raw = str(context or "").strip().lower()

    # Indikator non-WhatsApp yang pasti ditolak
    non_wa_indicators = (
        "telegram", "discord", "dokumen", "document", "file", "excel",
        ".xlsx", ".xls", ".pdf", ".csv", ".doc", "console", "web",
        "manual", "upload", "smdt"
    )
    if any(ind in s_raw for ind in non_wa_indicators):
        return False
    if ctx_raw and any(ind in ctx_raw for ind in ("telegram", "discord", "dokumen", ".xlsx", ".pdf")):
        return False

    return (
        s_raw.startswith("wa:")
        or s_raw.startswith("wa ")
        or s_raw.startswith("grup wa")
        or s_raw == "whatsapp"
        or "whatsapp" in s_raw
    )


def is_pengambilan_material_group(source: str, group: str = "", context: str = "") -> bool:
    """
    Validasi khusus: HANYA mencatat pengambilan material dari grup WhatsApp
    yang namanya memuat keterangan 'pengambilan material'.
    PENTING:
    - Nama grup harus secara spesifik memuat 'pengambilan material'.
    - Sumber generik tanpa nama grup atau sumber dokumen/file DILARANG.
    - Grup WA lain (Transfer Order, Subcon, Rekon, SMDT) DILARANG.
    """
    s_raw = str(source or "").strip().lower()
    g_raw = str(group or "").strip().lower()
    c_raw = str(context or "").strip().lower()

    # Tolak jika ada indikator dokumen atau telegram
    for text_val in (s_raw, g_raw, c_raw):
        if any(ind in text_val for ind in ("telegram", "dokumen", "document", "excel", ".xlsx", ".pdf")):
            return False

    # Kumpulkan kandidat nama grup
    candidates = []
    if s_raw:
        candidates.append(s_raw)
    if g_raw:
        candidates.append(g_raw)
    if c_raw:
        if "grup:" in c_raw:
            gpart = c_raw.split("grup:", 1)[1].split(",", 1)[0].strip()
            candidates.append(gpart)
        else:
            candidates.append(c_raw)

    for c in candidates:
        if "pengambilan material" in c:
            # Tolak jika merupakan grup Transfer Order / Subcon
            if "transfer order" in c or "subcon" in c:
                return False
            return True

    return False


def record_material_rows(
    rows: list[dict[str, Any]],
    source: str = "WhatsApp",
    spreadsheet_id: str = "",
    tab_name: str = DEFAULT_TAB_NAME,
    sender: str = "",
    group: str = "",
) -> dict[str, Any]:
    """
    Append structured material items to Google Sheets and local GDrive Excel backup.

    ATURAN INTEGRASI:
    1. HANYA menerima dan menyimpan baris yang bersumber dari chat WhatsApp.
    2. HANYA mencatat pengambilan material dari grup WhatsApp 'Pengambilan Material'.
    Sumber lain (seperti obrolan Telegram, input dummy, file dokumen, grup lain, atau TO) akan ditolak.
    """
    if not rows:
        return {"status": "error", "message": "Tidak ada baris data material untuk dicatat."}

    # VALIDASI KETAT SUMBER: Tolak jika bukan bersumber dari WhatsApp
    if not is_whatsapp_source(source, context=sender):
        logger.warning(
            f"[google_sheets] Penyimpanan ditolak: Sumber '{source}' bukan bersumber dari chat WhatsApp."
        )
        return {
            "status": "error",
            "message": (
                f"Penyimpanan ke spreadsheet ditolak. Sumber '{source}' bukan bersumber dari chat WhatsApp. "
                "Spreadsheet ini dikhususkan HANYA untuk mencatat data rekap dari chat WhatsApp grup 'Pengambilan Material'."
            ),
        }

    # VALIDASI KETAT GRUP: HANYA catat dari grup Pengambilan Material
    if not is_pengambilan_material_group(source, group=group, context=sender):
        logger.warning(
            f"[google_sheets] Penyimpanan ditolak: Sumber '{source}' / '{group}' bukan dari grup 'Pengambilan Material'."
        )
        return {
            "status": "error",
            "message": (
                f"Penyimpanan ke spreadsheet ditolak. Sumber '{source}' bukan grup 'Pengambilan Material'. "
                "Sesuai aturan, spreadsheet HANYA mencatat pengambilan material dari grup WhatsApp yang memuat keterangan 'pengambilan material'."
            ),
        }

    sid = spreadsheet_id or get_spreadsheet_id()
    now_str = datetime.datetime.now().strftime("%d/%m/%Y, %H.%M.%S")
    active_headers = PENGAMBILAN_HEADERS

    formatted_values = []
    for r in rows:
        row_time = r.get("waktu") or r.get("timestamp") or now_str
        no_doc = str(r.get("no_doc") or r.get("do_number") or r.get("to_number") or "-").strip()
        cluster = str(r.get("cluster") or r.get("site") or "-").strip()
        item = str(r.get("item_name") or r.get("material") or r.get("nama") or "").strip()
        qty = r.get("qty") or r.get("quantity") or 0
        unit = str(r.get("unit") or r.get("satuan") or "PCS").strip()
        pic = str(r.get("pic") or r.get("pengambil") or "-").strip()
        sender_val = str(r.get("sender") or sender or source).strip()
        notes = str(r.get("notes") or r.get("keterangan") or r.get("body") or "").strip()

        # Item harus berupa nama barang nyata, bukan placeholder '-' atau kosong
        # QTY harus valid (angka > 0 atau terisi), bukan '-' atau 0
        qty_str = str(qty).strip()
        if item and item != "-" and qty_str not in ("-", "", "0", "None"):
            formatted_values.append([
                row_time,
                no_doc,
                cluster,
                item,
                qty,
                unit,
                pic,
                sender_val,
                notes,
            ])

    if not formatted_values:
        return {"status": "error", "message": "Semua baris material tidak memiliki nama item yang valid."}

    # 1. Sync to Cloud Google Sheets
    cloud_synced = False
    cloud_error = None
    try:
        ensure_material_sheet_tab(spreadsheet_id=sid, tab_name=tab_name, headers=active_headers)
        service = get_sheets_service()
        res = service.spreadsheets().values().append(
            spreadsheetId=sid,
            range=f"'{tab_name}'!A1",
            valueInputOption="USER_ENTERED",
            body={"values": formatted_values},
        ).execute()
        updated_rows = res.get("updates", {}).get("updatedRows", len(formatted_values))
        cloud_synced = True
        logger.info(f"Synced {updated_rows} rows to Google Sheet [{tab_name}]")
    except Exception as e:
        cloud_error = str(e)
        logger.error(f"Failed to append to Google Sheet: {e}")

    # 2. Sync to Local Google Drive Mount Backup
    local_synced = False
    local_path = None
    try:
        gdrive_backup_dir = os.path.expanduser("~/GDrive1/PENCATATAN_MATERIAL")
        os.makedirs(gdrive_backup_dir, exist_ok=True)
        filename = "Rekap_Pengambilan_Material.xlsx"
        local_path = os.path.join(gdrive_backup_dir, filename)

        import openpyxl

        if os.path.exists(local_path):
            wb = openpyxl.load_workbook(local_path)
            if tab_name in wb.sheetnames:
                ws = wb[tab_name]
            else:
                ws = wb.create_sheet(title=tab_name)
                ws.append(active_headers)
        else:
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = tab_name
            ws.append(active_headers)

        for val_row in formatted_values:
            ws.append(val_row)

        wb.save(local_path)
        local_synced = True
        logger.info(f"Appended {len(formatted_values)} rows to local GDrive Excel: {local_path} [{tab_name}]")
    except Exception as le:
        logger.warning(f"Could not update local GDrive Excel backup: {le}")

    # 3. Save to wa-sheets-bot recorded_reports.json if available
    try:
        # Jangan mencemari recorded_reports.json produksi saat pengujian otomatis (pytest)
        if not os.getenv("PYTEST_CURRENT_TEST"):
            rep_file = os.path.join(WA_BOT_DIR, "recorded_reports.json")
            if os.path.exists(rep_file):
                with open(rep_file, "r+", encoding="utf-8") as f:
                    try:
                        reps = json.load(f)
                    except Exception:
                        reps = []
                    for val_row in formatted_values:
                        item_desc = val_row[3]
                        qty_desc = val_row[4]
                        unit_desc = val_row[5]
                        cluster_desc = val_row[2]
                        reps.append({
                            "id": str(int(datetime.datetime.now().timestamp() * 1000)),
                            "timestamp": val_row[0],
                            "format_name": "Pengambilan Material",
                            "tab": tab_name,
                            "sender": val_row[7],
                            "group": source,
                            "body": f"{item_desc} : {qty_desc} {unit_desc} (Cluster: {cluster_desc})",
                            "synced_to_sheets": cloud_synced,
                            "raw_values": val_row,
                        })
                    f.seek(0)
                    json.dump(reps[-2000:], f, indent=2)
                    f.truncate()
    except Exception:
        pass

    return {
        "status": "success" if (cloud_synced or local_synced) else "error",
        "total_items": len(formatted_values),
        "cloud_synced": cloud_synced,
        "cloud_error": cloud_error,
        "local_synced": local_synced,
        "local_path": local_path,
        "tab_name": tab_name,
        "spreadsheet_id": sid,
        "message": (
            f"✅ Berhasil mencatat {len(formatted_values)} item material ke "
            + (f"Google Sheets [{tab_name}]" if cloud_synced else "Local GDrive Backup")
            + (" & Cloud Google Drive" if local_synced else "")
            + (f" (Peringatan Cloud: {cloud_error})" if cloud_error else "")
        ),
    }


def parse_and_record_material_text(
    text: str,
    source: str = "WhatsApp",
    spreadsheet_id: str = "",
    context: str = "",
    tab_name: str = "",
    sender: str = "",
    group: str = "",
) -> dict[str, Any]:
    """
    Use AI (Gemini) to understand messy material requests/documents, extract
    clean structured rows, and record them directly to Google Sheets.

    ATURAN INTEGRASI: HANYA menerima dan menyimpan teks yang bersumber dari chat WhatsApp grup 'Pengambilan Material'.
    Sumber lain (seperti file/dokumen, obrolan Telegram, grup WhatsApp non-Pengambilan Material, dsb.) akan ditolak.
    """
    if not text or not text.strip():
        return {"status": "error", "message": "Teks material kosong."}

    # VALIDASI KETAT SUMBER: Tolak jika bukan bersumber dari WhatsApp
    if not is_whatsapp_source(source, context=context):
        logger.warning(
            f"[google_sheets] Parsing & penyimpanan ditolak: Sumber '{source}' bukan bersumber dari chat WhatsApp."
        )
        return {
            "status": "error",
            "message": (
                f"Penyimpanan ke spreadsheet ditolak. Sumber '{source}' bukan bersumber dari chat WhatsApp. "
                "Spreadsheet ini dikhususkan HANYA untuk mencatat data rekap dari chat WhatsApp grup 'Pengambilan Material'."
            ),
        }

    # VALIDASI KETAT GRUP: HANYA catat dari grup Pengambilan Material
    if not is_pengambilan_material_group(source, group=group, context=context):
        logger.warning(
            f"[google_sheets] Parsing ditolak: Sumber '{source}' / '{group}' bukan dari grup 'Pengambilan Material'."
        )
        return {
            "status": "error",
            "message": (
                f"Penyimpanan ke spreadsheet ditolak. Sumber '{source}' bukan grup 'Pengambilan Material'. "
                "Sesuai aturan, spreadsheet HANYA mencatat pengambilan material dari grup WhatsApp yang memuat keterangan 'pengambilan material'."
            ),
        }

    # Automatically resolve tab_name if not explicitly provided
    if not tab_name:
        clean_src = source.replace("WA:", "").strip()
        if "pengambilan material" in clean_src.lower():
            tab_name = clean_src.title()
        else:
            tab_name = DEFAULT_TAB_NAME

    try:
        from alfa.bot.config import _main_brain_gemini_model, resolve_main_gemini

        client, _, _ = resolve_main_gemini()
        model = _main_brain_gemini_model()
    except Exception:
        client = None
        model = "gemini-2.5-flash"

    if client is None:
        try:
            from google import genai

            from alfa.swarm.llm_client import get_agent_api_client
            _, api_key, model_name, _, _ = get_agent_api_client({"provider": "gemini"})
            client = genai.Client(api_key=api_key)
            model = model_name or "gemini-2.5-flash"
        except Exception:
            pass

    if client is None:
        return {"status": "error", "message": "Klien AI Gemini tidak tersedia untuk parsing material."}

    prompt = f"""Kamu adalah AI Specialist Pencatatan Pengambilan Material.
Tugasmu adalah menganalisis pesan WhatsApp dari grup Pengambilan Material di bawah ini dan mengekstrak SELURUH data pengambilan material ke dalam format JSON terstruktur.

Konteks Tambahan: {context}

Teks Sumber:
\"\"\"{text}\"\"\"

Instruksi Parsing:
1. Identifikasi Nomor Dokumen / Form Pengambilan jika ada (misal: "FORM-01", atau "-").
2. Identifikasi Cluster / Site / Project (misal: "Lahat", "Cluster A", dll).
3. Identifikasi PIC / Pengambil jika ada.
4. Ekstrak SETIAP item material yang diambil:
   - item_name: Nama spesifik material/barang.
   - qty: Angka murni jumlah material (integer atau float).
   - unit: Satuan (misal: "PCS", "SET", "METER", "ROLL", "BATANG", dll).
   - notes: Catatan tambahan atau isi pesan asli.

OUTPUT WAJIB HANYA JSON MURNI TANPA MARKDOWN:
[
  {{
    "no_doc": "-",
    "cluster": "...",
    "item_name": "...",
    "qty": 10,
    "unit": "PCS",
    "pic": "...",
    "notes": "..."
  }}
]
"""

    candidate_models = []
    if model:
        candidate_models.append(model)
    for m in ["gemini-flash-lite-latest", "gemini-flash-latest", "gemini-3.5-flash-lite", "gemini-3.5-flash"]:
        if m not in candidate_models:
            candidate_models.append(m)

    resp = None
    last_err = None
    for cand in candidate_models:
        try:
            resp = client.models.generate_content(
                model=cand,
                contents=prompt,
            )
            if resp and getattr(resp, "text", ""):
                break
        except Exception as ce:
            last_err = ce
            continue

    if resp is None or not getattr(resp, "text", ""):
        return {"status": "error", "message": f"Semua model AI gagal memproses: {last_err}"}

    raw_response = getattr(resp, "text", "") or ""
    cleaned = raw_response.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned.split("```json", 1)[1]
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```", 1)[1]
    if cleaned.endswith("```"):
        cleaned = cleaned.rsplit("```", 1)[0]
    cleaned = cleaned.strip()

    try:
        parsed_items = json.loads(cleaned)
    except Exception as je:
        return {"status": "error", "message": f"Gagal membaca format JSON dari AI: {je}. Teks AI: {cleaned[:200]}"}

    if not isinstance(parsed_items, list):
        return {"status": "error", "message": "Format output AI bukan berupa JSON array."}

    record_res = record_material_rows(
        rows=parsed_items,
        source=source,
        spreadsheet_id=spreadsheet_id,
        tab_name=tab_name,
        sender=sender,
        group=group,
    )
    record_res["parsed_items"] = parsed_items
    return record_res


def sync_material_if_detected(
    text: str,
    context: str = "",
    source: str = "WhatsApp",
) -> dict[str, Any] | None:
    """
    Intelligently checks if text or context contains material intake/retrieval (Pengambilan Material),
    and if so, extracts and syncs rows to Google Sheets and local GDrive Excel backup.
    ATURAN KETAT: HANYA memproses jika bersumber dari chat WhatsApp grup 'Pengambilan Material'.
    Returns result dict if items were synced, or None if not relevant / no items.
    """
    if not text:
        return None

    # HANYA sinkronkan jika sumbernya berasal dari WhatsApp grup Pengambilan Material
    if not is_whatsapp_source(source, context=context) or not is_pengambilan_material_group(source, context=context):
        return None

    combined_lower = f"{text} {context}".lower()

    # Core material context triggers (Pengambilan Material)
    material_keywords = [
        "pengambilan material", "ambil material", "kebutuhan material",
        "permintaan material", "tarikan material", "pemakaian material",
        "material", "pengambilan",
    ]
    has_mat_kw = any(k in combined_lower for k in material_keywords)

    # Item or quantity indicators
    item_indicators = [
        "•", "qty", "pcs", "set", "roll", "meter", "batang", "zak",
        "unit", "box", "can", "drum", "haspel", "pack", "btg", "mtr",
        "pole", "kabel", "odp", "closure", "clamp", "dropcore", "drop core"
    ]
    has_item_ind = any(i in combined_lower for i in item_indicators)

    # If both context and item patterns match, attempt AI extraction & sync
    if has_mat_kw and has_item_ind:
        try:
            res = parse_and_record_material_text(
                text=text,
                source=source,
                context=context,
            )
            if res.get("status") == "success" and res.get("total_items", 0) > 0:
                logger.info(f"Automatically recorded {res['total_items']} material items from {source}")
                return res
            else:
                logger.debug(f"Material sync check returned: {res}")
        except Exception as e:
            logger.warning(f"Failed to auto-sync material: {e}")

    return None


def get_spreadsheet_metadata(spreadsheet_id: str = "") -> dict[str, Any]:
    """
    Retrieve comprehensive metadata of a Google Spreadsheet including all its tabs.
    """
    sid = spreadsheet_id or get_spreadsheet_id()
    if not sid:
        return {"status": "error", "message": "Spreadsheet ID belum dikonfigurasi."}

    try:
        service = get_sheets_service()
        meta = service.spreadsheets().get(
            spreadsheetId=sid,
            fields="properties.title,properties.locale,properties.timeZone,sheets.properties",
        ).execute()

        title = meta.get("properties", {}).get("title", "Untitled Spreadsheet")
        raw_sheets = meta.get("sheets", [])
        sheets_list = []
        for sh in raw_sheets:
            p = sh.get("properties", {})
            gp = p.get("gridProperties", {})
            sheets_list.append({
                "sheet_id": p.get("sheetId", 0),
                "title": p.get("title", ""),
                "index": p.get("index", 0),
                "row_count": gp.get("rowCount", 0),
                "col_count": gp.get("columnCount", 0),
                "frozen_row_count": gp.get("frozenRowCount", 0),
            })

        return {
            "status": "success",
            "spreadsheet_id": sid,
            "title": title,
            "url": f"https://docs.google.com/spreadsheets/d/{sid}/edit",
            "total_tabs": len(sheets_list),
            "tabs": sheets_list,
        }
    except Exception as e:
        logger.warning(f"Failed to fetch spreadsheet metadata for {sid}: {e}")
        return {
            "status": "error",
            "spreadsheet_id": sid,
            "message": f"Gagal membaca metadata Google Sheets: {e}",
        }


def get_tab_preview(
    spreadsheet_id: str = "",
    tab_name: str = "",
    limit: int = 6,
) -> dict[str, Any]:
    """
    Preview rows and headers of a specific worksheet tab in Google Sheets.
    """
    sid = spreadsheet_id or get_spreadsheet_id()
    if not sid:
        return {"status": "error", "message": "Spreadsheet ID belum dikonfigurasi."}

    try:
        meta_res = get_spreadsheet_metadata(sid)
        if meta_res.get("status") != "success":
            return meta_res

        tabs = meta_res.get("tabs", [])
        target_tab = None
        if tab_name:
            target_tab = next((t for t in tabs if t["title"].lower() == tab_name.lower()), None)
        if not target_tab and tabs:
            target_tab = tabs[0]

        if not target_tab:
            return {"status": "error", "message": f"Tab '{tab_name}' tidak ditemukan di spreadsheet."}

        actual_name = target_tab["title"]
        sheet_id = target_tab["sheet_id"]

        service = get_sheets_service()
        safe_name = actual_name.replace("'", "''")
        val_res = service.spreadsheets().values().get(spreadsheetId=sid, range=f"'{safe_name}'").execute()
        all_rows = val_res.get("values", [])

        headers = all_rows[0] if all_rows else []
        data_rows = all_rows[1:] if len(all_rows) > 1 else []

        # Get latest rows
        recent_rows = data_rows[-limit:] if data_rows else []

        return {
            "status": "success",
            "spreadsheet_id": sid,
            "spreadsheet_title": meta_res.get("title", ""),
            "tab_name": actual_name,
            "sheet_id": sheet_id,
            "url": f"https://docs.google.com/spreadsheets/d/{sid}/edit#gid={sheet_id}",
            "total_rows": len(all_rows),
            "data_rows_count": len(data_rows),
            "headers": headers,
            "recent_rows": recent_rows,
        }
    except Exception as e:
        logger.warning(f"Failed to fetch tab preview for {tab_name} in {sid}: {e}")
        return {
            "status": "error",
            "message": f"Gagal membaca isi tab '{tab_name}': {e}",
        }


def list_accessible_spreadsheets() -> list[dict[str, Any]]:
    """
    Find all spreadsheets accessible in Google Drive and local mounts.
    """
    results = []
    seen_ids = set()

    # 1. Check currently active spreadsheet
    active_id = get_spreadsheet_id()
    if active_id:
        try:
            m = get_spreadsheet_metadata(active_id)
            if m.get("status") == "success":
                results.append({
                    "id": active_id,
                    "title": m.get("title", "Active Spreadsheet"),
                    "is_active": True,
                    "url": m.get("url", ""),
                    "total_tabs": m.get("total_tabs", 0),
                    "source": "Active Config",
                })
                seen_ids.add(active_id)
        except Exception:
            pass

    # 2. Check via Google Drive API
    try:
        from alfa.integrations.gdrive.auth import _get_gdrive_service
        drive_svc = _get_gdrive_service()
        drive_res = drive_svc.files().list(
            q="mimeType='application/vnd.google-apps.spreadsheet' and trashed=false",
            fields="files(id, name, modifiedTime, webViewLink, owners)",
            pageSize=25,
        ).execute()

        for f in drive_res.get("files", []):
            fid = f.get("id")
            if fid and fid not in seen_ids:
                results.append({
                    "id": fid,
                    "title": f.get("name", "Spreadsheet"),
                    "is_active": (fid == active_id),
                    "url": f.get("webViewLink") or f"https://docs.google.com/spreadsheets/d/{fid}/edit",
                    "modified": f.get("modifiedTime", ""),
                    "source": "Google Drive",
                })
                seen_ids.add(fid)
    except Exception as e:
        logger.debug(f"Could not list Drive spreadsheets: {e}")

    # 3. Check local mounted drives for .xlsx / .xls spreadsheets
    for mount_idx in [1, 2, 3]:
        mp = os.path.expanduser(f"~/GDrive{mount_idx}")
        if os.path.isdir(mp):
            try:
                for fname in os.listdir(mp):
                    if fname.lower().endswith((".xlsx", ".xls", ".csv")):
                        fpath = os.path.join(mp, fname)
                        results.append({
                            "id": fpath,
                            "title": fname,
                            "is_active": False,
                            "url": f"file://{fpath}",
                            "source": f"GDrive{mount_idx} (Lokal)",
                            "is_local": True,
                            "size": os.path.getsize(fpath) if os.path.exists(fpath) else 0,
                        })
            except Exception:
                pass

    return results
