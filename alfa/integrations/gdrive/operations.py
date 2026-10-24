"""Google Drive file upload, download, folder creation, and Second Brain sync."""

import os
from typing import Any

from alfa.core.runtime_ctx import current_user_id_var
from alfa.integrations.gdrive.auth import (
    SANDBOX_DIR,
    _get_default_gdrive_folder_id,
    _get_gdrive_service,
)


def gdrive_list_files(
    folder_id: str = "", query: str = "", limit: int = 20
) -> dict[str, Any]:
    """
    List, search, and browse files and folders stored in Google Drive cloud.

    PERINGATAN PEMANGGILAN:
    HANYA panggil tool ini jika pengguna secara eksplisit meminta mencari/melihat file di Google Drive
    (misal: 'cari file di drive ...', 'cari di gdrive ...', 'cek google drive').
    DILARANG memanggil tool ini untuk pencarian dokumen/file umum atau riwayat WhatsApp.

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
            tf_lower = target_folder.lower()
            if tf_lower == "all":
                pass
            elif tf_lower == "shared":
                q_parts.append("sharedWithMe = true")
            elif tf_lower == "root":
                q_parts.append("'root' in parents")
            else:
                q_parts.append(f"'{target_folder}' in parents")

        if query:
            q_parts.append(f"(name contains '{query}' or fullText contains '{query}')")
        q_str = " and ".join(q_parts)

        results = (
            service.files()
            .list(
                q=q_str,
                pageSize=min(limit, 100),
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
                fields="nextPageToken, files(id, name, mimeType, size, modifiedTime, webViewLink, webContentLink, iconLink, parents)",
            )
            .execute()
        )

        files = results.get("files", [])

        # Fallback: if default folder was requested but returned 0 items, fetch all accessible items
        if not files and not query and target_folder and target_folder.lower() not in ("all", "shared", "root"):
            fallback_res = (
                service.files()
                .list(
                    q="trashed = false",
                    pageSize=min(limit, 100),
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                    fields="nextPageToken, files(id, name, mimeType, size, modifiedTime, webViewLink, webContentLink, iconLink, parents)",
                )
                .execute()
            )
            fallback_files = fallback_res.get("files", [])
            if fallback_files:
                files = fallback_files
                target_folder = "all"

        return {
            "status": "success",
            "total_found": len(files),
            "folder_id": target_folder,
            "files": files,
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Gagal mengambil daftar file Google Drive: {str(e)}",
        }



def gdrive_upload_file(
    filepath: str, folder_id: str = "", custom_filename: str = ""
) -> dict[str, Any]:
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
                return {
                    "status": "error",
                    "message": f"File '{filepath}' tidak ditemukan di sistem lokal.",
                }

        service = _get_gdrive_service()
        target_folder = (
            folder_id.strip() if folder_id else _get_default_gdrive_folder_id()
        )
        upload_name = custom_filename or os.path.basename(resolved_path)
        mime_type, _ = mimetypes.guess_type(resolved_path)
        if not mime_type:
            mime_type = "application/octet-stream"

        file_metadata: dict[str, Any] = {"name": upload_name}
        if target_folder:
            file_metadata["parents"] = [target_folder]

        media = MediaFileUpload(resolved_path, mimetype=mime_type, resumable=True)
        file = (
            service.files()
            .create(
                body=file_metadata,
                media_body=media,
                supportsAllDrives=True,
                fields="id, name, mimeType, size, webViewLink, webContentLink",
            )
            .execute()
        )

        try:
            service.permissions().create(
                fileId=file.get("id"),
                body={"role": "reader", "type": "anyone"},
                supportsAllDrives=True,
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
            "download_link": file.get("webContentLink"),
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
        return {
            "status": "error",
            "message": f"Gagal mengunggah file ke Google Drive: {err_str}",
        }


def gdrive_download_file(file_id: str, save_filename: str = "") -> dict[str, Any]:
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
        file_meta = (
            service.files()
            .get(fileId=file_id, supportsAllDrives=True, fields="id, name, mimeType")
            .execute()
        )
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
            "file_size": os.path.getsize(target_path),
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Gagal mengunduh file dari Google Drive: {str(e)}",
        }


def gdrive_create_folder(
    folder_name: str, parent_folder_id: str = ""
) -> dict[str, Any]:
    """
    Create a new folder in Google Drive.

    Args:
        folder_name: Name of the folder to create.
        parent_folder_id: Optional ID of the parent folder (defaults to configured folder).
    """
    try:
        service = _get_gdrive_service()
        target_parent = (
            parent_folder_id.strip()
            if parent_folder_id
            else _get_default_gdrive_folder_id()
        )
        file_metadata: dict[str, Any] = {
            "name": folder_name,
            "mimeType": "application/vnd.google-apps.folder",
        }
        if target_parent:
            file_metadata["parents"] = [target_parent]

        folder = (
            service.files()
            .create(
                body=file_metadata,
                supportsAllDrives=True,
                fields="id, name, webViewLink",
            )
            .execute()
        )

        return {
            "status": "success",
            "message": f"Folder '{folder_name}' berhasil dibuat di Google Drive!",
            "folder_id": folder.get("id"),
            "folder_name": folder.get("name"),
            "web_link": folder.get("webViewLink"),
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Gagal membuat folder Google Drive: {str(e)}",
        }


def gdrive_sync_to_second_brain(folder_id: str = "", limit: int = 10) -> dict[str, Any]:
    """
    Ingest and sync documents from Google Drive directly into ALFA's Neural Vector Brain (Second Brain RAG).

    Args:
        folder_id: Optional Google Drive folder ID to ingest from (defaults to configured folder).
        limit: Max documents to ingest (default 10).
    """
    try:
        from alfa.memory import vector as vector_memory

        target_folder = (
            folder_id.strip() if folder_id else _get_default_gdrive_folder_id()
        )
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
                uid = (
                    int(allowed.split(",")[0])
                    if allowed.split(",")[0].strip().isdigit()
                    else 0
                )
            except (ValueError, TypeError, IndexError):
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
                    content_or_path=local_f or "",
                    category="Google Drive Sync",
                )
                ingested.append(
                    {
                        "name": fname,
                        "file_id": fid,
                        "vector_status": v_res.get("status"),
                    }
                )

        return {
            "status": "success",
            "total_ingested": len(ingested),
            "folder_id": target_folder,
            "synced_files": ingested,
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Gagal sinkronisasi Google Drive ke Second Brain: {str(e)}",
        }


def gdrive_list_mounted_files(
    drive_index: int = 1, subpath: str = "", query: str = "", limit: int = 50
) -> dict[str, Any]:
    """
    List files directly from locally mounted Google Drives (GDrive1, GDrive2, GDrive3 via rclone).
    HANYA panggil tool ini jika pengguna secara eksplisit meminta mencari file di drive/gdrive.
    """
    import os

    drive_dir = os.path.expanduser(f"~/GDrive{drive_index}")
    if not os.path.isdir(drive_dir):
        return {
            "status": "error",
            "message": f"Direktori Google Drive ~/GDrive{drive_index} tidak ditemukan atau belum dimount.",
        }
    target_path = os.path.join(drive_dir, subpath.lstrip("/")) if subpath else drive_dir
    if not os.path.exists(target_path):
        return {
            "status": "error",
            "message": f"Path '{subpath}' tidak ditemukan di GDrive{drive_index}.",
        }

    files = []
    try:
        for entry in sorted(os.listdir(target_path)):
            if query and query.lower() not in entry.lower():
                continue
            full_p = os.path.join(target_path, entry)
            is_d = os.path.isdir(full_p)
            files.append(
                {
                    "name": entry,
                    "is_dir": is_d,
                    "path": full_p,
                    "size": os.path.getsize(full_p) if not is_d else 0,
                }
            )
            if len(files) >= limit:
                break
        return {
            "status": "success",
            "drive": f"GDrive{drive_index}",
            "mount_path": target_path,
            "total_found": len(files),
            "files": files,
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Gagal membaca direktori GDrive{drive_index}: {str(e)}",
        }


def gdrive_copy_to_drive(
    source_path: str, drive_index: int = 1, subpath: str = ""
) -> dict[str, Any]:
    """
    Copy a local file or directory into Google Drive via local rclone mount.
    Automatically synced to the Google Cloud in real-time.
    """
    import os
    import shutil

    drive_dir = os.path.expanduser(f"~/GDrive{drive_index}")
    if not os.path.isdir(drive_dir):
        return {
            "status": "error",
            "message": f"Direktori Google Drive ~/GDrive{drive_index} tidak ditemukan atau belum dimount.",
        }

    src = os.path.expanduser(source_path)
    if not os.path.exists(src):
        return {"status": "error", "message": f"File sumber '{source_path}' tidak ditemukan."}

    dest_dir = os.path.join(drive_dir, subpath.lstrip("/")) if subpath else drive_dir
    os.makedirs(dest_dir, exist_ok=True)
    dest_path = os.path.join(dest_dir, os.path.basename(src))

    try:
        if os.path.isdir(src):
            shutil.copytree(src, dest_path, dirs_exist_ok=True)
        else:
            shutil.copy2(src, dest_path)
        return {
            "status": "success",
            "message": f"File berhasil disalin ke Google Drive (~/GDrive{drive_index}/{subpath}) dan otomatis tersinkronkan ke cloud!",
            "drive": f"GDrive{drive_index}",
            "destination": dest_path,
        }
    except Exception as e:
        return {"status": "error", "message": f"Gagal menyalin ke Google Drive: {str(e)}"}


def gdrive_copy_from_drive(
    filename_or_relpath: str, drive_index: int = 1, destination_dir: str = ""
) -> dict[str, Any]:
    """
    Copy a file from mounted Google Drive to local destination (or sandbox dir).
    """
    import os
    import shutil

    drive_dir = os.path.expanduser(f"~/GDrive{drive_index}")
    src_path = os.path.join(drive_dir, filename_or_relpath.lstrip("/"))
    if not os.path.exists(src_path):
        return {
            "status": "error",
            "message": f"File '{filename_or_relpath}' tidak ditemukan di ~/GDrive{drive_index}.",
        }

    target_dir = os.path.expanduser(destination_dir) if destination_dir else SANDBOX_DIR
    os.makedirs(target_dir, exist_ok=True)
    dest_path = os.path.join(target_dir, os.path.basename(src_path))

    try:
        shutil.copy2(src_path, dest_path)
        return {
            "status": "success",
            "message": f"File '{os.path.basename(src_path)}' berhasil disalin dari Google Drive!",
            "saved_path": dest_path,
            "size": os.path.getsize(dest_path),
        }
    except Exception as e:
        return {"status": "error", "message": f"Gagal menyalin dari Google Drive: {str(e)}"}

