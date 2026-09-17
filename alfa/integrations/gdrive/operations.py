"""Google Drive file upload, download, folder creation, and Second Brain sync."""

import logging
import os
from typing import Any, Dict, List, Optional

from alfa.core import database
from alfa.core.runtime_ctx import current_user_id_var
from alfa.integrations.gdrive.auth import (
    PROJECT_DIR,
    SANDBOX_DIR,
    _detect_gdrive_auth_mode,
    _get_default_gdrive_folder_id,
    _get_gdrive_service,
    logger,
)


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


