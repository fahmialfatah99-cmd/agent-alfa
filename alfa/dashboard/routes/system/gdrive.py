import asyncio
import json
import os
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse

from alfa import tools
from alfa.core import database
from alfa.dashboard.common import REPO_ROOT, safe_int

router = APIRouter()

# ==================== GOOGLE DRIVE & CLOUD ====================


@router.get("/api/gdrive/status")
async def gdrive_status_endpoint():
    """Check status of Google Drive integration."""
    try:
        res = tools.gdrive_status()
        cred_file = os.path.join(REPO_ROOT, "gdrive_credentials.json")
        has_file = os.path.exists(cred_file)

        account_email = ""
        project_id = ""
        if has_file:
            try:
                with open(cred_file, encoding="utf-8") as f:
                    cdata = json.load(f)
                    account_email = cdata.get("client_email", "")
                    project_id = cdata.get("project_id", "")
            except Exception:
                pass

        active_email = (res.get("user") or {}).get("emailAddress", "")
        return {
            "status": "success",
            "connected": res.get("connected", False),
            "auth_mode": res.get("auth_mode", ""),
            "client_email": active_email or account_email,
            "project_id": project_id,
            "storage_quota": res.get("storage_quota", {}),
            "default_folder_id": res.get(
                "default_folder_id", "1WTQuU2lbAQy438Whnhtn95jld-1d17lE"
            ),
            "default_folder_name": res.get("default_folder_name", "alfa agent"),
            "default_folder_url": res.get(
                "default_folder_url",
                "https://drive.google.com/drive/folders/1WTQuU2lbAQy438Whnhtn95jld-1d17lE",
            ),
            "error": res.get("message", "") if not res.get("connected") else "",
        }
    except Exception as e:
        return {"status": "error", "connected": False, "message": str(e)}


@router.post("/api/gdrive/folder")
async def gdrive_set_default_folder(payload: dict[str, Any]):
    """Set default Google Drive folder ID and name."""
    folder_id = payload.get("folder_id", "").strip()
    folder_name = payload.get("folder_name", "alfa agent").strip()

    if not folder_id:
        raise HTTPException(status_code=400, detail="folder_id wajib diisi.")

    with database.get_sync_db() as conn:
        conn.execute(
            "INSERT INTO system_settings (key, value) VALUES ('gdrive_default_folder_id', ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (folder_id,),
        )
        conn.execute(
            "INSERT INTO system_settings (key, value) VALUES ('gdrive_default_folder_name', ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (folder_name,),
        )
        conn.execute(
            "INSERT INTO system_settings (key, value) VALUES ('gdrive_default_folder_url', ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (f"https://drive.google.com/drive/folders/{folder_id}",),
        )

    return {
        "status": "success",
        "message": f"Folder default Google Drive berhasil disetel ke '{folder_name}' ({folder_id})",
        "folder_id": folder_id,
        "folder_name": folder_name,
    }


@router.post("/api/gdrive/credentials")
async def gdrive_save_credentials(
    file: UploadFile | None = File(None), raw_json: str | None = Form(None)
):
    """Upload Service Account JSON file or paste raw JSON for Google Drive / Google Cloud."""
    cred_file = os.path.join(REPO_ROOT, "gdrive_credentials.json")
    content = ""

    if file:
        content_bytes = await file.read()
        content = content_bytes.decode("utf-8")
    elif raw_json:
        content = raw_json.strip()
    else:
        raise HTTPException(
            status_code=400,
            detail="File JSON atau teks JSON Service Account wajib disediakan.",
        )

    try:
        data = json.loads(content)
        if "type" not in data or data.get("type") != "service_account":
            if "client_email" not in data:
                return {
                    "status": "error",
                    "message": "File JSON bukan merupakan Service Account Key yang valid dari Google Cloud Console.",
                }

        with open(cred_file, "w", encoding="utf-8") as f:
            f.write(content)

        with database.get_sync_db() as conn:
            conn.execute(
                "INSERT INTO system_settings (key, value) VALUES ('gdrive_credentials_json', ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (content,),
            )

        test_res = tools.gdrive_status()
        return {
            "status": "success",
            "message": "Kredensial Service Account Google Cloud berhasil disimpan dan diverifikasi!",
            "client_email": data.get("client_email", ""),
            "project_id": data.get("project_id", ""),
            "connected": test_res.get("connected", False),
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Gagal memproses kredensial Google Cloud: {str(e)}",
        }


@router.delete("/api/gdrive/credentials")
async def gdrive_delete_credentials():
    """Remove stored Google Drive credentials."""
    cred_file = os.path.join(REPO_ROOT, "gdrive_credentials.json")
    if os.path.exists(cred_file):
        os.remove(cred_file)
    with database.get_sync_db() as conn:
        conn.execute(
            "DELETE FROM system_settings WHERE key = 'gdrive_credentials_json'"
        )
    return {"status": "success", "message": "Kredensial Google Drive berhasil dihapus."}


@router.get("/api/gdrive/oauth/secret-check")
async def gdrive_oauth_secret_check():
    """Check whether the OAuth client secret exists AND is the right kind."""
    secret_path = os.path.join(REPO_ROOT, "gdrive_oauth_client_secret.json")
    result = {
        "status": "success",
        "exists": os.path.exists(secret_path),
        "expected_path": secret_path,
        "kind": "",
    }
    if result["exists"]:
        try:
            with open(secret_path, encoding="utf-8") as f:
                probe = json.load(f)
            if isinstance(probe, dict) and ("installed" in probe or "web" in probe):
                result["kind"] = "oauth_client"
            elif probe.get("type") == "service_account" or "private_key" in probe:
                result["kind"] = "service_account"
                result["exists"] = False
        except Exception:
            result["kind"] = "invalid_json"
            result["exists"] = False
    return result


@router.post("/api/gdrive/oauth/upload-secret")
async def gdrive_oauth_upload_secret(
    file: UploadFile | None = File(None), raw_json: str | None = Form(None)
):
    """Upload OAuth Client Secret JSON (Desktop or Web App) or paste raw JSON."""
    content = ""
    if file:
        content_bytes = await file.read()
        content = content_bytes.decode("utf-8")
    elif raw_json:
        content = raw_json.strip()
    else:
        raise HTTPException(
            status_code=400,
            detail="File JSON atau teks JSON OAuth Client Secret wajib disediakan.",
        )

    return tools.gdrive_save_oauth_client_secret(content)


@router.get("/api/gdrive/oauth/auth-url")
async def gdrive_oauth_auth_url(request: Request):
    """Generate authorization URL for Google Drive OAuth."""
    base_url = str(request.base_url).rstrip("/")
    redirect_uri = f"{base_url}/api/gdrive/oauth/callback"
    return tools.gdrive_oauth_get_auth_url(redirect_uri=redirect_uri)


@router.get("/api/gdrive/oauth/callback")
async def gdrive_oauth_callback(
    code: str | None = None, error: str | None = None, request: Request = None
):
    """Handle OAuth redirect callback from Google."""
    if error:
        return HTMLResponse(f"""
        <!DOCTYPE html>
        <html>
        <head><title>Otentikasi Gagal</title></head>
        <body style="font-family: sans-serif; background: #0f172a; color: #f8fafc; text-align: center; padding: 50px;">
            <h2 style="color: #f43f5e;">❌ Otentikasi Google Dibatalkan / Gagal</h2>
            <p style="color: #94a3b8;">{error}</p>
            <p><a href="/" style="color: #38bdf8; text-decoration: none; font-weight: bold;">← Kembali ke Dashboard</a></p>
        </body>
        </html>
        """)

    if not code:
        raise HTTPException(
            status_code=400,
            detail="Authorization code tidak ditemukan dalam URL callback.",
        )

    base_url = str(request.base_url).rstrip("/") if request else "http://localhost:8080"
    redirect_uri = f"{base_url}/api/gdrive/oauth/callback"
    res = tools.gdrive_oauth_exchange_code(auth_code=code, redirect_uri=redirect_uri)

    if res.get("status") == "success":
        return HTMLResponse("""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Login Berhasil</title>
            <meta http-equiv="refresh" content="2;url=/?gdrive_oauth=success#view-gdrive">
        </head>
        <body style="font-family: sans-serif; background: #0f172a; color: #f8fafc; text-align: center; padding: 50px;">
            <h2 style="color: #10b981;">🎉 Login Google Drive Berhasil!</h2>
            <p style="color: #94a3b8;">Upload Google Drive sekarang menggunakan kuota akun pribadi Anda (15 GB+).</p>
            <p style="color: #64748b; font-size: 12px;">Mengarahkan kembali ke Dashboard ALFA...</p>
            <p><a href="/#view-gdrive" style="color: #38bdf8; text-decoration: none; font-weight: bold;">Klik di sini jika tidak otomatis diarahkan</a></p>
        </body>
        </html>
        """)
    else:
        return HTMLResponse(f"""
        <!DOCTYPE html>
        <html>
        <head><title>Otentikasi Gagal</title></head>
        <body style="font-family: sans-serif; background: #0f172a; color: #f8fafc; text-align: center; padding: 50px;">
            <h2 style="color: #f43f5e;">❌ Gagal Menyimpan Token</h2>
            <p style="color: #94a3b8;">{res.get('message')}</p>
            <p><a href="/#view-gdrive" style="color: #38bdf8; text-decoration: none; font-weight: bold;">← Kembali ke Dashboard</a></p>
        </body>
        </html>
        """)


@router.post("/api/gdrive/oauth/exchange-code")
async def gdrive_oauth_exchange_code_endpoint(
    payload: dict[str, Any], request: Request
):
    """Exchange manually pasted authorization code for OAuth token."""
    code = payload.get("code", "").strip()
    if not code:
        raise HTTPException(status_code=400, detail="code wajib diisi.")
    base_url = str(request.base_url).rstrip("/")
    redirect_uri = f"{base_url}/api/gdrive/oauth/callback"
    return tools.gdrive_oauth_exchange_code(auth_code=code, redirect_uri=redirect_uri)


@router.post("/api/gdrive/oauth/start")
async def gdrive_oauth_start():
    """Start the OAuth login flow."""
    try:
        res = await asyncio.wait_for(
            asyncio.to_thread(tools.gdrive_oauth_login),
            timeout=330,
        )
        return res
    except asyncio.TimeoutError:
        return {
            "status": "error",
            "message": "Waktu login habis (5 menit) tanpa konfirmasi dari browser.",
        }
    except Exception as oauth_err:
        return {"status": "error", "message": f"OAuth error: {str(oauth_err)}"}


@router.post("/api/gdrive/oauth/logout")
async def gdrive_oauth_logout_endpoint():
    """Remove OAuth tokens and fall back to service-account auth."""
    return tools.gdrive_oauth_logout()


@router.get("/api/gdrive/files")
async def gdrive_list_files_endpoint(
    folder_id: str = "", query: str = "", limit: int = 30
):
    """List and search files in Google Drive."""
    return tools.gdrive_list_files(folder_id=folder_id, query=query, limit=limit)


@router.post("/api/gdrive/upload")
async def gdrive_upload_endpoint(
    file: UploadFile | None = File(None),
    filepath: str | None = Form(None),
    folder_id: str | None = Form(""),
):
    """Upload a file to Google Drive."""
    if file:
        upload_dir = tools.get_pdf_output_dir("Uploads")
        safe_name = os.path.basename(file.filename or "upload.bin") or "upload.bin"
        target_path = os.path.join(upload_dir, safe_name)
        with open(target_path, "wb") as f:
            f.write(await file.read())
        return tools.gdrive_upload_file(filepath=target_path, folder_id=folder_id or "")
    elif filepath:
        return tools.gdrive_upload_file(filepath=filepath, folder_id=folder_id or "")
    else:
        raise HTTPException(
            status_code=400, detail="File atau path file wajib ditentukan."
        )


@router.post("/api/gdrive/create-folder")
async def gdrive_create_folder_endpoint(payload: dict[str, Any]):
    """Create a folder in Google Drive."""
    folder_name = payload.get("name")
    parent_id = payload.get("parent_id", "")
    if not folder_name:
        raise HTTPException(status_code=400, detail="Nama folder wajib diisi.")
    return tools.gdrive_create_folder(
        folder_name=folder_name, parent_folder_id=parent_id
    )


@router.post("/api/gdrive/sync-brain")
async def gdrive_sync_brain_endpoint(payload: dict[str, Any] = None):
    """Sync Google Drive documents to Neural Vector Brain."""
    folder_id = (payload or {}).get("folder_id", "")
    limit = safe_int((payload or {}).get("limit", 10), 10, minimum=1, maximum=100)
    return tools.gdrive_sync_to_second_brain(folder_id=folder_id, limit=limit)
