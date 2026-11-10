"""KML/KMZ cluster map rendering."""
from __future__ import annotations

import json
import logging
import os
import re
import zipfile
from typing import Any

# defusedxml: guard XML serangan (XXE/billion-laughs) utk berkas KML untrusted
from defusedxml.ElementTree import fromstring as _xml_fromstring

from alfa.tools.registry import register_tool
from alfa.tools.system_tools import SANDBOX_DIR

logger = logging.getLogger("AgentTools.Telecom")

@register_tool(category="office")
def render_cluster_kml_map(
    kml_or_kmz_path: str,
    output_html_filename: str = "cluster_map.html",
) -> dict[str, Any]:
    """
    VISUALISASI PETA INTERAKTIF KML / KMZ (LEAFLET.JS):
    Mengekstrak titik tiang, koordinat FAT/ODC, dan rute jalur bentangan kabel dari berkas
    .kml atau .kmz proyek FTTH, lalu menghasilkan halaman peta interaktif visual berbasis Leaflet.js
    (mandiri tanpa API key) yang dapat dibuka di browser atau dikirim ke chat.

    Args:
        kml_or_kmz_path: Lokasi absolut atau relatif file .kml atau .kmz.
        output_html_filename: Nama file output HTML interaktif (default: cluster_map.html).
    """
    try:
        fpath = os.path.realpath(os.path.expanduser(kml_or_kmz_path.strip()))
        if not os.path.exists(fpath):
            return {"status": "error", "message": f"Berkas KML/KMZ '{kml_or_kmz_path}' tidak ditemukan."}

        kml_bytes = b""
        if fpath.endswith(".kmz"):
            with zipfile.ZipFile(fpath, "r") as z:
                kml_names = [n for n in z.namelist() if n.endswith(".kml")]
                if not kml_names:
                    return {"status": "error", "message": "Tidak ditemukan file .kml di dalam arsip KMZ."}
                kml_bytes = z.read(kml_names[0])
        else:
            with open(fpath, "rb") as f:
                kml_bytes = f.read()

        # Parse XML (stripping namespaces for cleaner navigation)
        raw_xml = re.sub(r'xmlns(:\w+)?="[^"]+"', '', kml_bytes.decode("utf-8", errors="ignore"))
        root = _xml_fromstring(raw_xml)

        markers: list[dict[str, Any]] = []
        polylines: list[dict[str, Any]] = []

        all_lats: list[float] = []
        all_lons: list[float] = []

        # Cek data progres lapangan dari arsip WA / SMDT
        reported_terms: set[str] = set()
        installed_markers_count = 0
        try:
            from alfa.core.db.connection import get_sync_db
            with get_sync_db() as conn:
                cluster_key = os.path.splitext(os.path.basename(fpath))[0].lower().replace("aktual", "").strip()
                q_txt = f"%{cluster_key}%" if cluster_key else "%kasambe%"
                rows = conn.execute(
                    "SELECT body FROM wa_incoming_archive WHERE LOWER(body) LIKE ? OR LOWER(chat_name) LIKE ? LIMIT 50",
                    (q_txt, q_txt),
                ).fetchall()
                for rw in rows:
                    for w in re.findall(r"\b[A-Za-z0-9\-_]{2,15}\b", (rw[0] or "").lower()):
                        reported_terms.add(w)
        except Exception as e:
            logger.debug("KML reported-terms lookup skipped: %s", e)

        for pm in root.iter("Placemark"):
            name = (pm.findtext("name") or "Placemark").strip()
            desc = (pm.findtext("description") or "").strip()
            # Clean CDATA or HTML in description
            desc_clean = re.sub(r"<[^>]+>", " ", desc).strip()

            # Check Point
            pt = pm.find(".//Point/coordinates")
            if pt is not None and pt.text:
                coords = pt.text.strip().split(",")
                if len(coords) >= 2:
                    try:
                        lon = float(coords[0])
                        lat = float(coords[1])
                        all_lons.append(lon)
                        all_lats.append(lat)
                        m_type = "POLE" if any(k in name.lower() for k in ['7"', '9"', 'tiang', 'pole']) else "FAT" if "fat" in name.lower() else "POINT"

                        # Status progres: Terpasang vs Rencana
                        is_installed = (
                            any(k in name.lower() for k in ("tanam", "pasang", "done", "selesai", "aktual", "ok"))
                            or name.lower() in reported_terms
                            or "aktual" in os.path.basename(fpath).lower()
                        )
                        if is_installed:
                            m_status = "TERPASANG (INSTALLED)"
                            color = "#10B981"  # Emerald Green
                            installed_markers_count += 1
                        elif m_type == "FAT":
                            m_status = "RENCANA (FAT)"
                            color = "#3B82F6"  # Blue
                        elif m_type == "POLE":
                            m_status = "RENCANA (TIANG)"
                            color = "#F59E0B"  # Amber
                        else:
                            m_status = "RENCANA"
                            color = "#8B5CF6"  # Purple

                        markers.append({
                            "name": name,
                            "desc": desc_clean[:120],
                            "lat": lat,
                            "lon": lon,
                            "type": m_type,
                            "status": m_status,
                            "color": color,
                        })
                    except ValueError:
                        pass

            # Check LineString
            ls = pm.find(".//LineString/coordinates")
            if ls is not None and ls.text:
                line_points = []
                for token in ls.text.strip().split():
                    c_parts = token.split(",")
                    if len(c_parts) >= 2:
                        try:
                            lon = float(c_parts[0])
                            lat = float(c_parts[1])
                            all_lons.append(lon)
                            all_lats.append(lat)
                            line_points.append([lat, lon])
                        except ValueError:
                            pass
                if len(line_points) >= 2:
                    polylines.append({
                        "name": name,
                        "desc": desc_clean[:100],
                        "coords": line_points,
                        "color": "#2563EB",
                    })

        if not markers and not polylines:
            return {"status": "error", "message": f"Tidak ditemukan titik koordinat atau jalur garis pada berkas '{os.path.basename(fpath)}'."}

        center_lat = sum(all_lats) / len(all_lats) if all_lats else 0.0
        center_lon = sum(all_lons) / len(all_lons) if all_lons else 0.0

        # Build Interactive Leaflet HTML
        html_content = f"""<!DOCTYPE html>
<html lang="id">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Peta Interaktif FTTH - {os.path.basename(fpath)}</title>
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <style>
        body, html {{ margin: 0; padding: 0; width: 100%; height: 100%; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }}
        #map {{ width: 100%; height: 100%; }}
        .hud-card {{
            position: absolute; top: 15px; right: 15px; z-index: 1000;
            background: rgba(15, 23, 42, 0.90); backdrop-filter: blur(8px);
            color: #ffffff; padding: 14px 18px; border-radius: 12px;
            box-shadow: 0 4px 20px rgba(0,0,0,0.4); border: 1px solid rgba(255,255,255,0.12);
            max-width: 320px;
        }}
        .hud-title {{ font-size: 14px; font-weight: 700; color: #38BDF8; margin-bottom: 6px; }}
        .hud-stat {{ font-size: 12px; margin: 4px 0; color: #E2E8F0; display: flex; justify-content: space-between; }}
        .badge {{ font-weight: bold; padding: 2px 6px; border-radius: 4px; background: rgba(56, 189, 248, 0.2); color: #38BDF8; }}
        .badge-green {{ background: rgba(16, 185, 129, 0.2); color: #10B981; }}
        .legend {{ margin-top: 10px; border-top: 1px solid rgba(255,255,255,0.1); padding-top: 8px; font-size: 11px; color: #94A3B8; }}
        .legend-item {{ display: flex; align-items: center; margin: 3px 0; }}
        .dot {{ width: 8px; height: 8px; border-radius: 50%; display: inline-block; margin-right: 6px; }}
    </style>
</head>
<body>
    <div id="map"></div>
    <div class="hud-card">
        <div class="hud-title">⚡ ALFA FTTH MAP VIEWER</div>
        <div style="font-size: 11px; color: #94A3B8; margin-bottom: 8px;">{os.path.basename(fpath)}</div>
        <div class="hud-stat"><span>Titik Total:</span> <span class="badge">{len(markers)} pts</span></div>
        <div class="hud-stat"><span>Status Terpasang:</span> <span class="badge badge-green">{installed_markers_count} pts</span></div>
        <div class="hud-stat"><span>Jalur Kabel:</span> <span class="badge">{len(polylines)} routes</span></div>
        <div class="hud-stat"><span>Pusat Koordinat:</span> <span>{round(center_lat, 5)}, {round(center_lon, 5)}</span></div>
        <div class="legend">
            <div class="legend-item"><span class="dot" style="background:#10B981;"></span> Terpasang (Installed)</div>
            <div class="legend-item"><span class="dot" style="background:#3B82F6;"></span> FAT Rencana</div>
            <div class="legend-item"><span class="dot" style="background:#F59E0B;"></span> Tiang Rencana</div>
            <div class="legend-item"><span class="dot" style="background:#2563EB;"></span> Jalur Bentangan Kabel</div>
        </div>
    </div>
    <script>
        const map = L.map('map').setView([{center_lat}, {center_lon}], 16);
        L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
            maxZoom: 19,
            attribution: '© OpenStreetMap contributors | ALFA OS'
        }}).addTo(map);

        const markersData = {json.dumps(markers)};
        markersData.forEach(m => {{
            const circle = L.circleMarker([m.lat, m.lon], {{
                radius: m.type === 'FAT' ? 8 : 6,
                fillColor: m.color,
                color: '#ffffff',
                weight: 2,
                opacity: 1,
                fillOpacity: 0.85
            }}).addTo(map);
            circle.bindPopup(`<b>${{m.name}}</b><br><span style="display:inline-block; margin:3px 0; font-size:10px; font-weight:bold; color:${{m.color}}; background:rgba(255,255,255,0.1); padding:1px 6px; border-radius:4px;">${{m.status}}</span><br><span style="font-size:11px; color:#64748B;">Tipe: ${{m.type}}</span><br><p style="margin:4px 0; font-size:12px;">${{m.desc || 'Tidak ada deskripsi'}}</p><span style="font-size:10px; color:#94A3B8;">${{m.lat}}, ${{m.lon}}</span>`);
        }});

        const linesData = {json.dumps(polylines)};
        linesData.forEach(line => {{
            const poly = L.polyline(line.coords, {{
                color: line.color,
                weight: 4,
                opacity: 0.8
            }}).addTo(map);
            poly.bindPopup(`<b>${{line.name}}</b><br><span style="font-size:12px;">${{line.desc || 'Jalur Bentangan Kabel'}}</span>`);
        }});
    </script>
</body>
</html>
"""
        out_name = output_html_filename if output_html_filename.endswith(".html") else f"{output_html_filename}.html"
        out_path = os.path.join(SANDBOX_DIR, out_name)
        os.makedirs(SANDBOX_DIR, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(html_content)

        return {
            "status": "success",
            "message": f"Berhasil merender peta interaktif dari '{os.path.basename(fpath)}' ke '{out_name}'.",
            "output_html_file": out_path,
            "filename": out_name,
            "total_points": len(markers),
            "total_cable_routes": len(polylines),
            "center_lat": round(center_lat, 6),
            "center_lon": round(center_lon, 6),
        }
    except Exception as e:
        logger.exception("Gagal merender peta KML: %s", e)
        return {"status": "error", "message": f"Render KML map error: {str(e)}"}
