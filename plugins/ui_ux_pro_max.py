"""
Dynamic Plugin Tool: ui_ux_pro_max
Description: AI UI/UX intelligence engine for generating design systems, selecting UI styles (from 67 styles), color palettes, typography pairings, charts, motion, and landing page patterns.
"""

import os
import sys
from typing import Any, Dict, Optional

# Add skills/ui-ux-pro-max/scripts to path
SKILL_SCRIPTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "skills", "ui-ux-pro-max", "scripts")
if SKILL_SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SKILL_SCRIPTS_DIR)


def ui_ux_pro_max_search(query: str, domain: str = "auto", action: str = "search", project_name: str = "My Project") -> Dict[str, Any]:
    """
    Kueri mesin kecerdasan UI/UX Pro Max untuk mendapatkan rekomendasi gaya UI (67 styles),
    palet warna, tipografi Google Fonts, animasi/motion, pola landing page, atau pembuatan
    Design System lengkap untuk website dan aplikasi mobile.

    Args:
        query: Kata kunci pencarian, topik produk, atau deskripsi aplikasi (misal: 'fintech crypto dashboard', 'glassmorphism dark mode', 'travel tourism booking', 'minimalist aesthetic').
        domain: Domain pencarian: 'auto', 'product', 'style', 'color', 'typography', 'landing', 'motion', 'chart', 'icon', 'ux-guidelines'.
        action: 'search' (pencarian domain tertentu) atau 'generate_design_system' (membuat arsitektur design system lengkap).
        project_name: Nama proyek jika action='generate_design_system'.
    """
    if not query or not query.strip():
        return {"status": "error", "message": "Query wajib diisi."}

    query = query.strip()
    action = (action or "search").strip().lower()
    domain = (domain or "auto").strip().lower()

    try:
        if action == "generate_design_system":
            from design_system import generate_design_system
            ds_res = generate_design_system(query, project_name)
            return {
                "status": "success",
                "action": "generate_design_system",
                "query": query,
                "project_name": project_name,
                "design_system_text": ds_res.get("text", ""),
                "summary": f"Design system berhasil dibuat untuk '{project_name}' berdasarkan konsep '{query}'."
            }
        else:
            from core import search
            from search import format_output
            target_domain = None if domain == "auto" else domain
            search_result_dict = search(query, target_domain, max_results=5)
            formatted_text = format_output(search_result_dict)
            return {
                "status": "success",
                "action": "search",
                "domain": search_result_dict.get("domain", target_domain or "auto"),
                "query": query,
                "total_found": search_result_dict.get("count", 0),
                "results": search_result_dict.get("results", []),
                "formatted_output": formatted_text
            }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Gagal mengeksekusi UI/UX Pro Max: {str(e)}"
        }
