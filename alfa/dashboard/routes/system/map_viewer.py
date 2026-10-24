"""
Interactive Cluster Map Viewer Route for ALFA Command Center.

Serves Leaflet.js interactive maps rendered from .kml and .kmz files in ~/Unduhan, ~/Dokumen,
and SANDBOX_DIR directly on http://localhost:8080/map.
"""

from __future__ import annotations

import glob
import os
import urllib.parse
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse

from alfa.tools.system_tools import SANDBOX_DIR
from alfa.tools.telecom_tools import render_cluster_kml_map

router = APIRouter(tags=["system-maps"])


def _discover_map_files() -> list[dict[str, Any]]:
    """Scan local directories for available .kmz and .kml files."""
    paths_to_scan = [
        os.path.expanduser("~/Unduhan"),
        os.path.expanduser("~/Dokumen"),
        SANDBOX_DIR,
    ]
    found: list[dict[str, Any]] = []
    seen = set()

    for p in paths_to_scan:
        if not os.path.exists(p):
            continue
        for ext in ("*.kmz", "*.kml"):
            for fpath in glob.glob(os.path.join(p, "**", ext), recursive=True):
                real_p = os.path.realpath(fpath)
                if real_p in seen:
                    continue
                seen.add(real_p)
                found.append({
                    "name": os.path.basename(real_p),
                    "path": real_p,
                    "size_kb": round(os.path.getsize(real_p) / 1024, 1),
                    "extension": os.path.splitext(real_p)[1].lower(),
                })
    return sorted(found, key=lambda x: x["name"].lower())


@router.get("/api/system/maps", response_class=JSONResponse)
async def list_available_maps() -> dict[str, Any]:
    """API endpoint to list all available KML/KMZ files."""
    maps = _discover_map_files()
    return {"status": "success", "total": len(maps), "maps": maps}


@router.get("/map", response_class=HTMLResponse)
async def serve_map_viewer(request: Request, file: str = Query("", description="Nama atau path file KMZ/KML")) -> HTMLResponse:
    """
    Main Map Viewer Endpoint.
    If 'file' is provided, renders the interactive Leaflet map.
    If 'file' is empty, shows selector dashboard of all available KMZ/KML files.
    """
    available_maps = _discover_map_files()

    if file:
        target_path = ""
        # 1. Cek apakah path absolut/relatif langsung valid
        clean_file = urllib.parse.unquote(file.strip())
        if os.path.exists(os.path.realpath(os.path.expanduser(clean_file))):
            target_path = os.path.realpath(os.path.expanduser(clean_file))
        else:
            # 2. Cari berdasarkan nama file di daftar map yang ditemukan
            for m in available_maps:
                if m["name"].lower() == clean_file.lower() or clean_file.lower() in m["name"].lower():
                    target_path = m["path"]
                    break

        if target_path and os.path.exists(target_path):
            res = render_cluster_kml_map(target_path)
            if res.get("status") == "success" and os.path.exists(res.get("output_html_file", "")):
                with open(res["output_html_file"], encoding="utf-8") as f:
                    html_content = f.read()

                # Inject CSP Nonce agar script Leaflet & inline diizinkan oleh browser
                csp_nonce = getattr(request.state, "csp_nonce", "")
                if csp_nonce:
                    html_content = html_content.replace("<script src=", f'<script nonce="{csp_nonce}" src=')
                    html_content = html_content.replace("<script>", f'<script nonce="{csp_nonce}">')

                # Inject a back button at top-left
                back_nav = """
                <div style="position: absolute; top: 15px; left: 60px; z-index: 1000;">
                    <a href="/map" style="background: rgba(15, 23, 42, 0.85); backdrop-filter: blur(8px); color: #38BDF8; padding: 8px 14px; border-radius: 8px; text-decoration: none; font-size: 13px; font-weight: bold; border: 1px solid rgba(56, 189, 248, 0.3); font-family: sans-serif; box-shadow: 0 4px 12px rgba(0,0,0,0.3);">
                        ← Kembali ke Daftar Peta
                    </a>
                </div>
                """
                if "<body>" in html_content:
                    html_content = html_content.replace("<body>", f"<body>{back_nav}")
                return HTMLResponse(content=html_content, status_code=200)

    # Render Directory Selector UI
    options_html = ""
    for m in available_maps:
        safe_name = urllib.parse.quote(m["name"])
        options_html += f"""
        <div style="background: #1E293B; border: 1px solid #334155; border-radius: 12px; padding: 16px; margin-bottom: 12px; display: flex; justify-content: space-between; align-items: center; transition: all 0.2s;">
            <div>
                <div style="font-weight: 700; color: #F8FAFC; font-size: 15px;">📍 {m['name']}</div>
                <div style="font-size: 12px; color: #94A3B8; margin-top: 4px;">Ukuran: {m['size_kb']} KB | Lokasi: {m['path']}</div>
            </div>
            <div>
                <a href="/map?file={safe_name}" style="background: #0284C7; hover:background: #0369A1; color: #FFFFFF; font-weight: 600; font-size: 13px; padding: 8px 16px; border-radius: 8px; text-decoration: none; display: inline-block;">
                    Buka Peta Interaktif →
                </a>
            </div>
        </div>
        """

    if not options_html:
        options_html = """
        <div style="background: #1E293B; border: 1px solid #334155; border-radius: 12px; padding: 24px; text-align: center; color: #94A3B8;">
            Tidak ditemukan berkas .kml atau .kmz di folder ~/Unduhan atau ~/Dokumen.
        </div>
        """

    index_html = f"""<!DOCTYPE html>
<html lang="id">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ALFA FTTH Cluster Map Center</title>
    <style>
        body {{
            background: #0F172A;
            color: #F8FAFC;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            margin: 0;
            padding: 30px;
        }}
        .container {{
            max-width: 900px;
            margin: 0 auto;
        }}
        .header {{
            margin-bottom: 24px;
            border-bottom: 1px solid #334155;
            padding-bottom: 16px;
        }}
        .header h1 {{
            font-size: 24px;
            color: #38BDF8;
            margin: 0 0 8px 0;
        }}
        .header p {{
            font-size: 14px;
            color: #94A3B8;
            margin: 0;
        }}
        .nav-link {{
            color: #94A3B8;
            text-decoration: none;
            font-size: 13px;
            display: inline-block;
            margin-bottom: 16px;
        }}
        .nav-link:hover {{
            color: #38BDF8;
        }}
    </style>
</head>
<body>
    <div class="container">
        <a href="/" class="nav-link">← Kembali ke Dashboard Utama</a>
        <div class="header">
            <h1>🗺️ ALFA FTTH Cluster Map Center</h1>
            <p>Pusat visualisasi spasial peta jalur kabel dan titik FAT/ODC/Tiang proyek telekomunikasi.</p>
        </div>
        <div style="font-size: 14px; font-weight: 600; color: #E2E8F0; margin-bottom: 12px;">
            Daftar Berkas Peta Tersedia ({len(available_maps)} Berkas):
        </div>
        {options_html}
    </div>
</body>
</html>
"""
    return HTMLResponse(content=index_html, status_code=200)
