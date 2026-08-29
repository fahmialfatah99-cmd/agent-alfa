"""Google Drive & Google Cloud Suite — dipisah dari tools.py.

Seksi ini kohesif (hanya bergantung pada database + stdlib) sehingga aman
dijadikan modul sendiri. tools.py tetap mengekspor ulang seluruh nama
(pola facade) agar semua pemanggil lama `tools.gdrive_*` bekerja tanpa
perubahan. Jangan menambah logika baru di sini yang memanggil fungsi
tools.py lain — itu akan membuat impor melingkar."""

import logging
import os
from typing import Any, Dict

import database
from runtime_ctx import current_user_id_var

logger = logging.getLogger("AgentTools")

# Identik dengan tools.SANDBOX_DIR; didefinisikan lokal agar modul ini
# tidak pernah mengimpor balik tools.py (bebas siklus impor).
if os.name == "nt":
    _drive = os.path.splitdrive(os.path.abspath("."))[0] or "C:"
    SANDBOX_DIR = os.path.join(_drive + os.sep, "dev", "shm", "alfa_sandbox")
else:
    SANDBOX_DIR = "/dev/shm/alfa_sandbox"
os.makedirs(SANDBOX_DIR, exist_ok=True)

# ==================== GOOGLE DRIVE & GOOGLE CLOUD SUITE ====================


def _get_default_gdrive_folder_id() -> str:
    """Return default Google Drive folder ID from database or environment."""
    try:
        with database.get_sync_db() as conn:
            row = conn.execute("SELECT value FROM system_settings WHERE key = 'gdrive_default_folder_id'").fetchone()
            if row and row[0] and row[0].strip():
                return row[0].strip()
    except Exception:
        pass
    return os.getenv("GDRIVE_DEFAULT_FOLDER_ID", "1WTQuU2lbAQy438Whnhtn95jld-1d17lE").strip()


def _get_gdrive_service():
    """Helper to initialize and return an authorized Google Drive API v3 resource service."""
    import json

    from google.oauth2 import service_account
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    scopes = [
        "https://www.googleapis.com/auth/drive",
        "https://www.googleapis.com/auth/drive.file"
    ]

    creds = None

    # 1. Check OAuth 2.0 User Token (allows uploading to personal Google Drive with user's quota)
    oauth_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gdrive_oauth_token.json")
    if os.path.exists(oauth_file):
        try:
            # Honor the scopes actually granted during consent - forcing extra
            # scopes here makes Google reject the refresh with invalid_scope.
            try:
                with open(oauth_file, "r", encoding="utf-8") as f:
                    stored_scopes = json.load(f).get("scopes") or scopes
            except Exception:
                stored_scopes = scopes
            creds = Credentials.from_authorized_user_file(oauth_file, scopes=stored_scopes)
            if creds and creds.expired and creds.refresh_token:
                from google.auth.transport.requests import Request
                creds.refresh(Request())
        except Exception as e:
            logger.error(f"Error loading gdrive_oauth_token.json: {e}")
            creds = None

    if not creds:
        try:
            with database.get_sync_db() as conn:
                row = conn.execute("SELECT value FROM system_settings WHERE key = 'gdrive_oauth_token_json'").fetchone()
                if row and row[0]:
                    info = json.loads(row[0])
                    creds = Credentials.from_authorized_user_info(info, scopes=info.get("scopes") or scopes)
                    if creds and creds.expired and creds.refresh_token:
                        from google.auth.transport.requests import Request
                        creds.refresh(Request())
        except Exception:
            creds = None

    # 2. Check Service Account JSON file
    if not creds:
        cred_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gdrive_credentials.json")
        if os.path.exists(cred_file):
            try:
                creds = service_account.Credentials.from_service_account_file(cred_file, scopes=scopes)
            except Exception as e:
                logger.error(f"Error loading gdrive_credentials.json: {e}")

    if not creds:
        env_json = os.getenv("GDRIVE_SERVICE_ACCOUNT_JSON", "").strip()
        if env_json:
            try:
                info = json.loads(env_json)
                creds = service_account.Credentials.from_service_account_info(info, scopes=scopes)
            except Exception as e:
                logger.error(f"Error loading GDRIVE_SERVICE_ACCOUNT_JSON from env: {e}")

    if not creds:
        try:
            with database.get_sync_db() as conn:
                row = conn.execute("SELECT value FROM system_settings WHERE key = 'gdrive_credentials_json'").fetchone()
                if row and row[0]:
                    info = json.loads(row[0])
                    creds = service_account.Credentials.from_service_account_info(info, scopes=scopes)
        except Exception as e:
            logger.error(f"Error loading gdrive credentials from database: {e}")

    if not creds:
        raise ValueError(
            "Google Drive credentials belum dikonfigurasi! "
            "Unggah Service Account JSON dari Google Cloud Console ke menu Google Drive Hub atau simpan file 'gdrive_credentials.json'."
        )

    return build("drive", "v3", credentials=creds)


def _detect_gdrive_auth_mode() -> str:
    """Return which credential source will be used: 'oauth' or 'service_account'."""
    oauth_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gdrive_oauth_token.json")
    if os.path.exists(oauth_file):
        return "oauth"
    try:
        with database.get_sync_db() as conn:
            row = conn.execute("SELECT value FROM system_settings WHERE key = 'gdrive_oauth_token_json'").fetchone()
            if row and row[0]:
                return "oauth"
    except Exception:
        pass
    cred_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gdrive_credentials.json")
    if os.path.exists(cred_file):
        return "service_account"
    if os.getenv("GDRIVE_SERVICE_ACCOUNT_JSON", "").strip():
        return "service_account"
    return "none"


def gdrive_oauth_login(port: int = 8999, wait_timeout: int = 300) -> Dict[str, Any]:
    """
    Run the OAuth 2.0 consent flow so uploads use YOUR personal Drive quota.

    Service accounts created recently have ZERO storage quota and cannot upload
    anywhere ("Service Accounts do not have storage quota"), so the reliable
    method is logging in as your own Google account once; the refreshable token
    is stored locally and picked up automatically afterwards.

    Requires an OAuth Client ID (type: Desktop app) downloaded from Google Cloud
    Console, saved as 'gdrive_oauth_client_secret.json' in the project directory.

    Args:
        port: Local redirect port for the consent callback (default 8999).
        wait_timeout: Seconds to wait for you to finish the browser login (default 300).
    """
    import json as _json

    project_dir = os.path.dirname(os.path.abspath(__file__))
    secret_candidates = [
        os.path.join(project_dir, "gdrive_oauth_client_secret.json"),
        os.path.join(project_dir, "client_secret.json"),
    ]
    secret_path = next((p for p in secret_candidates if os.path.exists(p)), None)

    if not secret_path:
        return {
            "status": "error",
            "needs_client_secret": True,
            "message": (
                "File OAuth client secret belum ada. Langkah persisnya:\n"
                "1. Buka https://console.cloud.google.com/apis/credentials (project yang sama dgn service account)\n"
                "2. Create Credentials > OAuth client ID > Application type: Desktop app\n"
                "3. Download JSON, simpan sebagai: " + secret_candidates[0] + "\n"
                "4. Tambahkan email Anda sebagai Test user di OAuth consent screen\n"
                "5. Jalankan lagi login ini."
            ),
        }

    # Detect the classic mix-up: renaming a SERVICE ACCOUNT key instead of
    # downloading an OAuth client ID (they are different credential types).
    try:
        with open(secret_path, "r", encoding="utf-8") as f:
            probe = _json.load(f)
        if isinstance(probe, dict) and "installed" not in probe and "web" not in probe:
            if probe.get("type") == "service_account" or "private_key" in probe:
                return {
                    "status": "error",
                    "needs_client_secret": True,
                    "wrong_type": "service_account",
                    "message": (
                        f"'{os.path.basename(secret_path)}' adalah file SERVICE ACCOUNT, "
                        "bukan OAuth client secret - keduanya jenis kredensial berbeda.\n"
                        "Yang dibutuhkan: OAuth Client ID tipe Desktop app.\n"
                        "1. https://console.cloud.google.com/apis/credentials\n"
                        "2. Create Credentials > OAuth client ID > Desktop app > Create\n"
                        "3. Klik ikon Download pada client baru itu, rename hasilnya menjadi "
                        + os.path.basename(secret_candidates[0]) + "\n"
                        "4. OAuth consent screen > Audience > tambahkan email Anda sebagai Test user"
                    ),
                }
    except Exception as probe_err:
        logger.warning(f"Could not probe oauth secret file: {probe_err}")

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow

        scopes = ["https://www.googleapis.com/auth/drive"]
        flow = InstalledAppFlow.from_client_secrets_file(secret_path, scopes=scopes)

        creds = flow.run_local_server(
            host="localhost",
            port=port,
            open_browser=True,
            timeout_seconds=wait_timeout,
            authorization_prompt_message=(
                "\n🔐 Buka link berikut di browser untuk login Google Drive:\n%s\n"
                "Menunggu konfirmasi...\n"
            ),
            success_message="✅ Login Google Drive berhasil! Jendela boleh ditutup.\n",
        )

        token_data = {
            "refresh_token": creds.refresh_token,
            "token": creds.token,
            "token_uri": creds.token_uri,
            "client_id": creds.client_id,
            "client_secret": creds.client_secret,
            "scopes": creds.scopes,
        }
        token_file = os.path.join(project_dir, "gdrive_oauth_token.json")
        with open(token_file, "w", encoding="utf-8") as f:
            _json.dump(token_data, f, indent=2)
        try:
            os.chmod(token_file, 0o600)
        except OSError:
            pass

        # Backup into DB so other services/processes share the same token
        try:
            with database.get_sync_db() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO system_settings (key, value) VALUES ('gdrive_oauth_token_json', ?)",
                    (_json.dumps(token_data),),
                )
                conn.commit()
        except Exception as db_err:
            logger.warning(f"Could not mirror OAuth token to DB: {db_err}")

        return {
            "status": "success",
            "message": "Login OAuth Google Drive berhasil. Upload kini memakai kuota akun Anda.",
            "token_file": token_file,
            "scopes": list(creds.scopes or []),
        }
    except Exception as e:
        return {"status": "error", "message": f"OAuth login gagal/dibatalkan: {str(e)}"}


def gdrive_save_oauth_client_secret(raw_content: Any) -> Dict[str, Any]:
    """Save uploaded or pasted OAuth Client Secret JSON (Desktop or Web App)."""
    import json as _json
    project_dir = os.path.dirname(os.path.abspath(__file__))
    target_file = os.path.join(project_dir, "gdrive_oauth_client_secret.json")

    try:
        if isinstance(raw_content, str):
            data = _json.loads(raw_content)
        elif isinstance(raw_content, dict):
            data = raw_content
        else:
            return {"status": "error", "message": "Format data client secret tidak valid."}

        if "installed" not in data and "web" not in data:
            if data.get("type") == "service_account" or "private_key" in data:
                return {
                    "status": "error",
                    "message": "File yang Anda masukkan adalah Service Account JSON, bukan OAuth Client Secret. "
                               "Silakan unduh OAuth Client ID (tipe Desktop App atau Web Application) dari Google Cloud Console."
                }
            return {"status": "error", "message": "JSON harus memiliki key 'installed' atau 'web' dari Google Cloud Console."}

        with open(target_file, "w", encoding="utf-8") as f:
            _json.dump(data, f, indent=2)

        try:
            with database.get_sync_db() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO system_settings (key, value) VALUES ('gdrive_oauth_client_secret_json', ?)",
                    (_json.dumps(data),)
                )
                conn.commit()
        except Exception as db_err:
            logger.warning(f"Could not mirror client secret to DB: {db_err}")

        return {
            "status": "success",
            "message": "OAuth Client Secret berhasil disimpan. Sekarang Anda dapat menghubungkan akun Google pribadi Anda!",
            "file": target_file
        }
    except Exception as e:
        return {"status": "error", "message": f"Gagal menyimpan client secret: {str(e)}"}


def gdrive_oauth_get_auth_url(redirect_uri: str = "http://localhost:8080/api/gdrive/oauth/callback") -> Dict[str, Any]:
    """Generate Google OAuth 2.0 authorization URL for 1-click browser login."""
    from google_auth_oauthlib.flow import Flow

    project_dir = os.path.dirname(os.path.abspath(__file__))
    secret_candidates = [
        os.path.join(project_dir, "gdrive_oauth_client_secret.json"),
        os.path.join(project_dir, "client_secret.json"),
    ]
    secret_path = next((p for p in secret_candidates if os.path.exists(p)), None)

    # Check DB if not on disk
    if not secret_path:
        try:
            with database.get_sync_db() as conn:
                row = conn.execute("SELECT value FROM system_settings WHERE key = 'gdrive_oauth_client_secret_json'").fetchone()
                if row and row[0]:
                    secret_path = os.path.join(project_dir, "gdrive_oauth_client_secret.json")
                    with open(secret_path, "w", encoding="utf-8") as f:
                        f.write(row[0])
        except Exception:
            pass

    if not secret_path:
        return {
            "status": "error",
            "needs_client_secret": True,
            "message": "File OAuth Client Secret belum diunggah. Unggah file JSON client secret di Dashboard terlebih dahulu."
        }

    try:
        scopes = ["https://www.googleapis.com/auth/drive"]
        flow = Flow.from_client_secrets_file(
            secret_path,
            scopes=scopes,
            redirect_uri=redirect_uri
        )
        auth_url, state = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent"
        )
        return {
            "status": "success",
            "auth_url": auth_url,
            "state": state,
            "redirect_uri": redirect_uri
        }
    except Exception as e:
        return {"status": "error", "message": f"Gagal membuat URL otentikasi Google: {str(e)}"}


def gdrive_oauth_exchange_code(auth_code: str, redirect_uri: str = "http://localhost:8080/api/gdrive/oauth/callback") -> Dict[str, Any]:
    """Exchange authorization code for OAuth credentials and store token permanently."""
    import json as _json

    from google_auth_oauthlib.flow import Flow

    project_dir = os.path.dirname(os.path.abspath(__file__))
    secret_candidates = [
        os.path.join(project_dir, "gdrive_oauth_client_secret.json"),
        os.path.join(project_dir, "client_secret.json"),
    ]
    secret_path = next((p for p in secret_candidates if os.path.exists(p)), None)

    if not secret_path:
        return {"status": "error", "message": "OAuth client secret tidak ditemukan."}

    try:
        scopes = ["https://www.googleapis.com/auth/drive"]
        flow = Flow.from_client_secrets_file(
            secret_path,
            scopes=scopes,
            redirect_uri=redirect_uri
        )
        flow.fetch_token(code=auth_code.strip())
        creds = flow.credentials

        token_data = {
            "refresh_token": creds.refresh_token,
            "token": creds.token,
            "token_uri": creds.token_uri,
            "client_id": creds.client_id,
            "client_secret": creds.client_secret,
            "scopes": creds.scopes,
        }
        token_file = os.path.join(project_dir, "gdrive_oauth_token.json")
        with open(token_file, "w", encoding="utf-8") as f:
            _json.dump(token_data, f, indent=2)

        try:
            with database.get_sync_db() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO system_settings (key, value) VALUES ('gdrive_oauth_token_json', ?)",
                    (_json.dumps(token_data),),
                )
                conn.commit()
        except Exception as db_err:
            logger.warning(f"Could not mirror OAuth token to DB: {db_err}")

        return {
            "status": "success",
            "message": "Login Google Drive berhasil! Upload sekarang menggunakan kuota akun pribadi Anda.",
            "token_file": token_file
        }
    except Exception as e:
        return {"status": "error", "message": f"Pertukaran kode otorisasi gagal: {str(e)}"}


def gdrive_oauth_logout() -> Dict[str, Any]:
    """Remove stored OAuth tokens (falls back to service account auth)."""
    removed = False
    token_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gdrive_oauth_token.json")
    if os.path.exists(token_file):
        try:
            os.remove(token_file)
            removed = True
        except OSError:
            pass
    try:
        with database.get_sync_db() as conn:
            conn.execute("DELETE FROM system_settings WHERE key = 'gdrive_oauth_token_json'")
            conn.commit()
    except Exception:
        pass
    return {"status": "success", "removed": removed, "message": "Token OAuth dihapus."}


def gdrive_status() -> Dict[str, Any]:
    """
    Check the connection status of Google Drive Integration, storage quota, and default folder info.
    """
    try:
        service = _get_gdrive_service()
        about = service.about().get(fields="user, storageQuota").execute()
        def_folder = _get_default_gdrive_folder_id()
        folder_name = "alfa agent"

        try:
            with database.get_sync_db() as conn:
                r = conn.execute("SELECT value FROM system_settings WHERE key = 'gdrive_default_folder_name'").fetchone()
                if r and r[0]:
                    folder_name = r[0]
        except Exception:
            pass

        return {
            "status": "success",
            "connected": True,
            "auth_mode": _detect_gdrive_auth_mode(),
            "user": about.get("user", {}),
            "storage_quota": about.get("storageQuota", {}),
            "default_folder_id": def_folder,
            "default_folder_name": folder_name,
            "default_folder_url": f"https://drive.google.com/drive/folders/{def_folder}"
        }
    except Exception as e:
        return {
            "status": "error",
            "connected": False,
            "message": str(e),
            "default_folder_id": _get_default_gdrive_folder_id()
        }


def gdrive_list_files(folder_id: str = "", query: str = "", limit: int = 20) -> Dict[str, Any]:
    """
    List, search, and browse files and folders stored in Google Drive.

    Args:
        folder_id: Optional ID of the Google Drive folder to list (defaults to configured folder).
        query: Optional search keyword or query term.
        limit: Max number of files to return (default 20, max 100).
    """
    try:
        service = _get_gdrive_service()
        target_folder = folder_id.strip() if folder_id else _get_default_gdrive_folder_id()
        q_parts = ["trashed = false"]
        if target_folder:
            q_parts.append(f"'{target_folder}' in parents")
        if query:
            q_parts.append(f"(name contains '{query}' or fullText contains '{query}')")
        q_str = " and ".join(q_parts)

        results = service.files().list(
            q=q_str,
            pageSize=min(limit, 100),
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
            fields="nextPageToken, files(id, name, mimeType, size, modifiedTime, webViewLink, webContentLink, iconLink)"
        ).execute()

        files = results.get("files", [])
        return {
            "status": "success",
            "total_found": len(files),
            "folder_id": target_folder,
            "files": files
        }
    except Exception as e:
        return {"status": "error", "message": f"Gagal mengambil daftar file Google Drive: {str(e)}"}


def gdrive_upload_file(filepath: str, folder_id: str = "", custom_filename: str = "") -> Dict[str, Any]:
    """
    Upload a local file or document (PDF, Excel, Word, images, code, archive) to Google Drive.

    Args:
        filepath: Path to the local file (e.g. '~/Dokumen/ALFA_SWARM_OUTPUTS/laporan.pdf' or filename).
        folder_id: Optional Google Drive folder ID to upload into (defaults to configured folder).
        custom_filename: Optional custom file name on Google Drive.
    """
    try:
        import mimetypes

        from googleapiclient.http import MediaFileUpload

        resolved_path = os.path.expanduser(filepath)
        if not os.path.exists(resolved_path):
            alt_path = os.path.join(SANDBOX_DIR, filepath)
            if os.path.exists(alt_path):
                resolved_path = alt_path
            else:
                return {"status": "error", "message": f"File '{filepath}' tidak ditemukan di sistem lokal."}

        service = _get_gdrive_service()
        target_folder = folder_id.strip() if folder_id else _get_default_gdrive_folder_id()
        upload_name = custom_filename or os.path.basename(resolved_path)
        mime_type, _ = mimetypes.guess_type(resolved_path)
        if not mime_type:
            mime_type = "application/octet-stream"

        file_metadata = {"name": upload_name}
        if target_folder:
            file_metadata["parents"] = [target_folder]

        media = MediaFileUpload(resolved_path, mimetype=mime_type, resumable=True)
        file = service.files().create(
            body=file_metadata,
            media_body=media,
            supportsAllDrives=True,
            fields="id, name, mimeType, size, webViewLink, webContentLink"
        ).execute()

        try:
            service.permissions().create(
                fileId=file.get("id"),
                body={"role": "reader", "type": "anyone"},
                supportsAllDrives=True
            ).execute()
        except Exception:
            pass

        return {
            "status": "success",
            "message": f"File '{upload_name}' berhasil diunggah ke Google Drive di folder target!",
            "file_id": file.get("id"),
            "file_name": file.get("name"),
            "folder_id": target_folder,
            "web_link": file.get("webViewLink"),
            "download_link": file.get("webContentLink")
        }
    except Exception as e:
        err_str = str(e)
        if "Service Accounts do not have storage quota" in err_str:
            return {
                "status": "error",
                "message": (
                    "Upload gagal: Service Account Google tidak punya kuota penyimpanan "
                    "(kebijakan Google terbaru). Solusi: lakukan login OAuth sekali via "
                    "Dashboard > Google Drive > 'Login OAuth', atau jalankan "
                    "./venv/bin/python scripts/gdrive_oauth_login.py - upload selanjutnya memakai kuota akun Anda."
                ),
                "needs_oauth": True,
            }
        return {"status": "error", "message": f"Gagal mengunggah file ke Google Drive: {err_str}"}


def gdrive_download_file(file_id: str, save_filename: str = "") -> Dict[str, Any]:
    """
    Download a file from Google Drive by its File ID to the local system.

    Args:
        file_id: The unique Google Drive File ID.
        save_filename: Optional local filename to save the downloaded content as.
    """
    try:
        import io

        from googleapiclient.http import MediaIoBaseDownload

        service = _get_gdrive_service()
        file_meta = service.files().get(fileId=file_id, supportsAllDrives=True, fields="id, name, mimeType").execute()
        target_name = save_filename or file_meta.get("name", f"gdrive_{file_id}")
        target_path = os.path.join(SANDBOX_DIR, target_name)

        request = service.files().get_media(fileId=file_id, supportsAllDrives=True)
        fh = io.FileIO(target_path, "wb")
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            status, done = downloader.next_chunk()

        return {
            "status": "success",
            "message": f"File '{target_name}' berhasil diunduh dari Google Drive!",
            "file_id": file_id,
            "saved_path": target_path,
            "file_size": os.path.getsize(target_path)
        }
    except Exception as e:
        return {"status": "error", "message": f"Gagal mengunduh file dari Google Drive: {str(e)}"}


def gdrive_create_folder(folder_name: str, parent_folder_id: str = "") -> Dict[str, Any]:
    """
    Create a new folder in Google Drive.

    Args:
        folder_name: Name of the folder to create.
        parent_folder_id: Optional ID of the parent folder (defaults to configured folder).
    """
    try:
        service = _get_gdrive_service()
        target_parent = parent_folder_id.strip() if parent_folder_id else _get_default_gdrive_folder_id()
        file_metadata = {
            "name": folder_name,
            "mimeType": "application/vnd.google-apps.folder"
        }
        if target_parent:
            file_metadata["parents"] = [target_parent]

        folder = service.files().create(
            body=file_metadata,
            supportsAllDrives=True,
            fields="id, name, webViewLink"
        ).execute()

        return {
            "status": "success",
            "message": f"Folder '{folder_name}' berhasil dibuat di Google Drive!",
            "folder_id": folder.get("id"),
            "folder_name": folder.get("name"),
            "web_link": folder.get("webViewLink")
        }
    except Exception as e:
        return {"status": "error", "message": f"Gagal membuat folder Google Drive: {str(e)}"}


def gdrive_sync_to_second_brain(folder_id: str = "", limit: int = 10) -> Dict[str, Any]:
    """
    Ingest and sync documents from Google Drive directly into ALFA's Neural Vector Brain (Second Brain RAG).

    Args:
        folder_id: Optional Google Drive folder ID to ingest from (defaults to configured folder).
        limit: Max documents to ingest (default 10).
    """
    try:
        import vector_memory
        target_folder = folder_id.strip() if folder_id else _get_default_gdrive_folder_id()
        list_res = gdrive_list_files(folder_id=target_folder, limit=limit)
        if list_res.get("status") != "success":
            return list_res

        files = list_res.get("files", [])
        ingested = []
        # Attribute to the PRIMARY user so the main agent (Telegram/Web) can
        # retrieve these chunks - dashboard context has no telegram user id.
        uid = current_user_id_var.get()
        if not uid:
            try:
                allowed = os.getenv("ALLOWED_USER_IDS", "").strip()
                uid = int(allowed.split(",")[0]) if allowed.split(",")[0].strip().isdigit() else 0
            except Exception:
                uid = 0

        for f in files:
            fid = f.get("id")
            fname = f.get("name", "")
            mime = f.get("mimeType", "")

            if "folder" in mime:
                continue

            dl_res = gdrive_download_file(file_id=fid, save_filename=fname)
            if dl_res.get("status") == "success":
                local_f = dl_res.get("saved_path")
                v_res = vector_memory.ingest_document(
                    user_id=uid,
                    title=f"GDrive: {fname}",
                    content_or_path=local_f,
                    category="Google Drive Sync"
                )
                ingested.append({"name": fname, "file_id": fid, "vector_status": v_res.get("status")})

        return {
            "status": "success",
            "total_ingested": len(ingested),
            "folder_id": target_folder,
            "synced_files": ingested
        }
    except Exception as e:
        return {"status": "error", "message": f"Gagal sinkronisasi Google Drive ke Second Brain: {str(e)}"}
