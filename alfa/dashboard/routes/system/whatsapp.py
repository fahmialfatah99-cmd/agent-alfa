import asyncio
import json
import logging
import os
import shutil
import sqlite3
import subprocess
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import aiosqlite
import psutil
from dotenv import dotenv_values
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response

from alfa import tools
from alfa.core import database
from alfa.dashboard.common import REPO_ROOT, get_primary_user_id, logger, safe_int

router = APIRouter()

# ==================== WHATSAPP SUITE ====================

WA_BOT_FORMATS_FILE = os.path.expanduser("~/wa-sheets-bot/formats.json")
WA_BOT_MEDIA_RULES_FILE = os.path.expanduser("~/wa-sheets-bot/media_rules.json")
WA_DRIVE_UPLOADS_FILE = os.path.expanduser("~/wa-sheets-bot/drive_uploads.json")
_WA_DYNAMIC_SOURCES = {"timestamp", "sender", "group", "body"}
_WA_MEDIA_TYPES = {"foto", "video", "pdf", "excel", "dokumen", "audio"}


def _validate_media_rules(rules: Any) -> List[str]:
    errs = []
    if not isinstance(rules, list):
        return ["Field 'rules' harus berupa array."]
    if len(rules) > 30:
        return ["Maksimal 30 aturan."]
    seen = set()
    for i, r in enumerate(rules, 1):
        tag = f"Aturan #{i}"
        if not isinstance(r, dict):
            errs.append(f"{tag}: bukan objek.")
            continue
        name = str(r.get("name", "")).strip()
        if not name:
            errs.append(f"{tag}: nama kosong.")
        elif name.lower() in seen:
            errs.append(f"{tag}: nama '{name}' duplikat.")
        seen.add(name.lower())
        types = r.get("types")
        if (
            not isinstance(types, list)
            or not types
            or not all(t in _WA_MEDIA_TYPES for t in types)
        ):
            errs.append(
                f"{tag} '{name}': pilih minimal satu jenis file ({', '.join(sorted(_WA_MEDIA_TYPES))})."
            )
        pattern = str(r.get("naming", "")).strip()
        if not pattern:
            errs.append(f"{tag} '{name}': pola nama file kosong.")
    return errs


def _validate_wa_formats(formats: Any) -> List[str]:
    errs = []
    if not isinstance(formats, list):
        return ["Field 'formats' harus berupa array."]
    if len(formats) > 50:
        return ["Maksimal 50 format."]
    seen_names, seen_tabs = set(), set()
    for i, f in enumerate(formats, 1):
        tag = f"Format #{i}"
        if not isinstance(f, dict):
            errs.append(f"{tag}: bukan objek.")
            continue
        name = str(f.get("name", "")).strip()
        tab = str(f.get("tab", "")).strip()
        keywords = f.get("keywords")
        columns = f.get("columns")
        if not name:
            errs.append(f"{tag}: nama kosong.")
        if name.lower() in seen_names:
            errs.append(f"{tag}: nama '{name}' duplikat.")
        seen_names.add(name.lower())
        if not tab:
            errs.append(f"{tag} '{name}': tab Sheets kosong.")
        if tab in seen_tabs:
            errs.append(f"{tag}: tab '{tab}' dipakai lebih dari satu format.")
        seen_tabs.add(tab)
        if (
            not isinstance(keywords, list)
            or not keywords
            or not all(isinstance(k, str) and k.strip() for k in keywords)
        ):
            errs.append(f"{tag} '{name}': keywords wajib minimal 1 kata pemicu.")
        if not isinstance(columns, list) or not columns:
            errs.append(f"{tag} '{name}': minimal 1 kolom.")
            continue
        if len(columns) > 30:
            errs.append(f"{tag} '{name}': maksimal 30 kolom.")
        for j, c in enumerate(columns, 1):
            title = str((c or {}).get("title", "")).strip()
            source = str((c or {}).get("source", (c or {}).get("value", ""))).strip()
            if not title:
                errs.append(f"{tag} '{name}' kolom {j}: judul kosong.")
            if not source:
                errs.append(f"{tag} '{name}' kolom {j} '{title}': sumber kosong.")
    return errs


def _gdrive_ensure_subfolder(folder_name: str) -> str:
    parent = tools._get_default_gdrive_folder_id()
    service = tools._get_gdrive_service()
    q = f"name = '{folder_name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    if parent:
        q += f" and '{parent}' in parents"
    found = (
        service.files()
        .list(
            q=q,
            fields="files(id, name)",
            spaces="drive",
            supportsAllDrives=True,
            pageSize=5,
        )
        .execute()
    )
    files = found.get("files", [])
    if files:
        return files[0]["id"]
    meta = {"name": folder_name, "mimeType": "application/vnd.google-apps.folder"}
    if parent:
        meta["parents"] = [parent]
    created = (
        service.files().create(body=meta, fields="id", supportsAllDrives=True).execute()
    )
    return created["id"]


def _log_wa_drive_upload(entry: Dict[str, Any]):
    try:
        data = {"uploads": []}
        if os.path.exists(WA_DRIVE_UPLOADS_FILE):
            try:
                with open(WA_DRIVE_UPLOADS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f) or data
            except Exception:
                pass
        uploads = data.get("uploads", [])
        uploads.insert(0, entry)
        data["uploads"] = uploads[:200]
        tmp = WA_DRIVE_UPLOADS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, WA_DRIVE_UPLOADS_FILE)
    except Exception as e:
        logger.warning(f"Could not log wa drive upload: {e}")


@router.get("/api/wa/qr")
async def get_wa_qr():
    """Fetch live WhatsApp QR code and authentication status."""
    try:
        import httpx

        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get("http://localhost:3000/api/qr")
            if resp.status_code == 200:
                return resp.json()
    except Exception:
        pass

    status_file = os.path.expanduser("~/.alfa/wa_status.json")
    if os.path.exists(status_file):
        try:
            with open(status_file, "r") as f:
                data = json.load(f)
            qr_str = data.get("qr", "")
            qr_data_url = None
            if qr_str:
                import base64
                import io

                import qrcode

                img = qrcode.make(qr_str)
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                b64 = base64.b64encode(buf.getvalue()).decode()
                qr_data_url = f"data:image/png;base64,{b64}"
            return {
                "status": data.get("status", "UNKNOWN"),
                "is_ready": data.get("status") == "READY",
                "qr_available": bool(qr_str),
                "qr_string": qr_str,
                "qr_data_url": qr_data_url,
                "timestamp": data.get("updated_at", ""),
            }
        except Exception:
            pass

    return {
        "status": "DISCONNECTED",
        "is_ready": False,
        "qr_available": False,
        "qr_string": "",
        "qr_data_url": None,
        "timestamp": datetime.now().isoformat(),
    }


@router.post("/api/wa/logout")
async def logout_wa():
    """Trigger WhatsApp logout to force new QR generation."""
    try:
        import httpx

        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post("http://localhost:3000/api/logout")
            if resp.status_code == 200:
                return resp.json()
    except Exception:
        pass
    return {
        "status": "error",
        "message": "Failed to connect to WhatsApp bot server on port 3000",
    }


@router.get("/api/wa/reports")
async def get_wa_reports():
    """Fetch recorded WhatsApp Google Sheets reports and format definitions."""
    try:
        import httpx

        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get("http://localhost:3000/api/reports")
            if resp.status_code == 200:
                return resp.json()
    except Exception:
        pass

    reports_file = os.path.expanduser("~/wa-sheets-bot/recorded_reports.json")
    formats_file = os.path.expanduser("~/wa-sheets-bot/formats.json")
    reports_data = []
    formats_data = []
    if os.path.exists(reports_file):
        try:
            with open(reports_file, "r") as f:
                reports_data = json.load(f)
        except Exception:
            pass
    if os.path.exists(formats_file):
        try:
            with open(formats_file, "r") as f:
                formats_data = json.load(f).get("formats", [])
        except Exception:
            pass

    return {
        "status": "success",
        "spreadsheet_id": "1d9Mr1IZszP1Cq34VN1_OTHtWokxDdV4prywsgVxN0RQ",
        "formats": formats_data,
        "total_recorded": len(reports_data),
        "pending_queue_count": 0,
        "reports": reports_data,
    }


@router.get("/api/wa/media-rules")
async def get_wa_media_rules():
    """Read automatic media-saving rules for the Drive side of wa-sheets-bot."""
    result = {
        "status": "success",
        "exists": False,
        "rules": [],
        "path": WA_BOT_MEDIA_RULES_FILE,
    }
    try:
        if os.path.exists(WA_BOT_MEDIA_RULES_FILE):
            with open(WA_BOT_MEDIA_RULES_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            result["exists"] = True
            result["rules"] = data.get("rules", []) if isinstance(data, dict) else []
    except Exception as e:
        result["status"] = "error"
        result["message"] = f"Gagal membaca media_rules.json: {e}"
    return result


@router.post("/api/wa/media-rules")
async def save_wa_media_rules(payload: Dict[str, Any]):
    """Save media auto-save rules."""
    rules = payload.get("rules")
    errors = _validate_media_rules(rules)
    if errors:
        return {
            "status": "error",
            "validation_errors": errors,
            "message": "; ".join(errors[:4]),
        }

    clean = []
    for r in rules:
        clean.append(
            {
                "name": str(r["name"]).strip(),
                "enabled": bool(r.get("enabled", True)),
                "types": [str(t).strip() for t in r["types"]],
                "keyword": str(r.get("keyword", "")).strip(),
                "folder": str(r.get("folder", "")).strip() or "Umum",
                "naming": str(r["naming"]).strip(),
            }
        )

    try:
        os.makedirs(os.path.dirname(WA_BOT_MEDIA_RULES_FILE), exist_ok=True)
        if os.path.exists(WA_BOT_MEDIA_RULES_FILE):
            shutil.copyfile(WA_BOT_MEDIA_RULES_FILE, WA_BOT_MEDIA_RULES_FILE + ".bak")
        tmp_path = WA_BOT_MEDIA_RULES_FILE + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump({"rules": clean}, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp_path, WA_BOT_MEDIA_RULES_FILE)
        return {
            "status": "success",
            "saved": len(clean),
            "message": f"{len(clean)} aturan media tersimpan. Bot langsung memakainya.",
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Gagal menyimpan media_rules.json: {str(e)}",
        }


@router.get("/api/wa/drive-uploads")
async def get_wa_drive_uploads():
    """Recent files auto-uploaded from WhatsApp to Google Drive."""
    result = {"status": "success", "uploads": [], "total": 0}
    try:
        if os.path.exists(WA_DRIVE_UPLOADS_FILE):
            with open(WA_DRIVE_UPLOADS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            ups = data.get("uploads", []) if isinstance(data, dict) else []
            result["uploads"] = ups
            result["total"] = len(ups)
    except Exception as e:
        result["status"] = "error"
        result["message"] = str(e)
    return result


@router.post("/api/wa/media-upload")
async def wa_media_upload(
    file: UploadFile = File(...),
    format_name: str = Form("Lainnya"),
    subfolder: str = Form(""),
    sender: str = Form(""),
    group: str = Form(""),
    caption: str = Form(""),
):
    """Receive media from wa-sheets-bot and upload to Google Drive."""
    try:
        upload_dir = os.path.join("/dev/shm", "alfa_wa_media")
        os.makedirs(upload_dir, exist_ok=True)
        safe_name = os.path.basename(file.filename or "media.bin") or "media.bin"
        tmp_path = os.path.join(upload_dir, f"{int(time.time()*1000)}_{safe_name}")
        with open(tmp_path, "wb") as out:
            out.write(await file.read())

        target_sub = subfolder.strip() or f"{(format_name or 'Lainnya').strip()[:40]}"
        subfolder_id = _gdrive_ensure_subfolder(f"WA Media / {target_sub}")
        res = tools.gdrive_upload_file(
            filepath=tmp_path, folder_id=subfolder_id, custom_filename=safe_name
        )
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        if res.get("status") == "success":
            _log_wa_drive_upload(
                {
                    "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "file_name": res.get("file_name"),
                    "web_link": res.get("web_link"),
                    "folder": f"WA Media / {target_sub}",
                    "format_name": format_name or "",
                    "sender": sender or "",
                    "group": group or "",
                    "caption": (caption or "")[:300],
                }
            )
            return {
                "status": "success",
                "web_link": res.get("web_link"),
                "file_name": res.get("file_name"),
                "folder": f"WA Media / {target_sub}",
            }
        return res
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/api/wa/formats")
async def get_wa_formats():
    """Read the WhatsApp report format definitions consumed by wa-sheets-bot."""
    result = {
        "status": "success",
        "exists": False,
        "formats": [],
        "path": WA_BOT_FORMATS_FILE,
    }
    try:
        if os.path.exists(WA_BOT_FORMATS_FILE):
            with open(WA_BOT_FORMATS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            result["exists"] = True
            result["formats"] = (
                data.get("formats", []) if isinstance(data, dict) else []
            )
    except Exception as e:
        result["status"] = "error"
        result["message"] = f"Gagal membaca formats.json: {e}"
    return result


@router.post("/api/wa/formats")
async def save_wa_formats(payload: Dict[str, Any]):
    """Save report formats."""
    formats = payload.get("formats")
    errors = _validate_wa_formats(formats)
    if errors:
        return {
            "status": "error",
            "validation_errors": errors,
            "message": "; ".join(errors[:4]),
        }

    clean = []
    for f in formats:
        cols = [
            {"title": str(c["title"]).strip(), "source": str(c["source"]).strip()}
            for c in f["columns"]
        ]
        clean.append(
            {
                "name": str(f["name"]).strip(),
                "keywords": [str(k).strip() for k in f["keywords"]],
                "tab": str(f["tab"]).strip(),
                "columns": cols,
            }
        )

    try:
        os.makedirs(os.path.dirname(WA_BOT_FORMATS_FILE), exist_ok=True)
        if os.path.exists(WA_BOT_FORMATS_FILE):
            shutil.copyfile(WA_BOT_FORMATS_FILE, WA_BOT_FORMATS_FILE + ".bak")

        tmp_path = WA_BOT_FORMATS_FILE + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump({"formats": clean}, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp_path, WA_BOT_FORMATS_FILE)
        return {
            "status": "success",
            "saved": len(clean),
            "backup": WA_BOT_FORMATS_FILE + ".bak",
            "message": f"{len(clean)} format laporan tersimpan. Bot WhatsApp langsung memakainya (tanpa restart).",
        }
    except Exception as e:
        return {"status": "error", "message": f"Gagal menyimpan formats.json: {str(e)}"}
