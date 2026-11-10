"""Shared constants and parsers used across the telecom tool suite."""
from __future__ import annotations

import logging
import os
import re
from typing import Any

logger = logging.getLogger("AgentTools.Telecom")

FIELD_CONSOLIDATION_ENABLED: bool = (
    os.getenv("ALFA_FIELD_CONSOLIDATION_ENABLED", "0").strip().lower() in ("1", "true", "yes")
)

def _classify_telecom_material(desc: str) -> str:
    """Classify material description into standard FTTH categories."""
    d = (desc or "").lower().strip()
    # 1. Labels, paints, foundations, and hardware accessories first (prevent false POLE / false DISTRIBUTION_BOX)
    if any(k in d for k in ["label", "pengecatan", "cat tiang", "pondasi", "foundation"]):
        return "ACCESSORIES"
    if any(k in d for k in ["clamp", "deadend", "dead end", "suspen", "suapen", "stopping", "stoping", "bracket", "hook", "strapping", "band", "plate belt", "buldog", "bulldog", "grip", "hanger", "holder", "loop holder", "temberang", "helical", "steel clamp"]):
        return "ACCESSORIES"

    # 2. Distribution Boxes (FAT, FDT, Joint Closure, ODC, ODP)
    if any(k in d for k in ["fat", "fdt", "odc", "odp", "closure", "joint closure"]) or (
        ("port" in d or "capacity" in d) and any(b in d for b in ["outdoor", "pole mounted", "box", "mounted"])
    ):
        return "DISTRIBUTION_BOX"

    # 3. Cables & Messenger Wire
    if any(k in d for k in ["adss", "kabel", "fo ", "cable", "drop core", "fig 8", "feeder", "strand wire", "messenger", "sling"]):
        return "CABLE"

    # 4. Physical Poles (exclude mounted accessories, clamps, brackets, labels, foundations)
    if ("tiang" in d or re.search(r"\bpole\b", d)) and not any(k in d for k in ["mounted", "clamp", "bracket", "label", "pondasi", "foundation", "pengecatan"]):
        return "POLE"

    # 5. Optical Passives & Splicing
    if any(k in d for k in ["sleeve", "protection sleeve", "pigtail", "adapter", "splitter", "patch cord", "splicing"]):
        return "OPTICAL_PASSIVE"

    return "OTHER"

def _parse_single_boq_workbook(wb: Any) -> tuple[str, str, list[dict[str, Any]]]:
    """
    Parses a single telecom BOQ workbook with smart sheet gating and column resolution.
    Returns:
        (target_sheet_name, scope_label, items_list)
        where items_list contains dicts with keys:
        {"desc": str, "unit": str, "qty": float, "category": str, "is_service": bool}
    """
    target_sheet = None
    scope = "GENERIC"

    # Prioritize 'BoQ NRO Cluster' if it contains actual non-zero material
    if "BoQ NRO Cluster" in wb.sheetnames:
        ws_check = wb["BoQ NRO Cluster"]
        has_mat = False
        for r in ws_check.iter_rows(values_only=True):
            if len(r) > 3 and isinstance(r[3], (int, float)) and r[3] > 0 and r[3] < 100000000:
                has_mat = True
                break
        if has_mat:
            target_sheet = "BoQ NRO Cluster"
            scope = "CLUSTER_DISTRIBUTION"
        elif "BoQ NRO All Feeder" in wb.sheetnames:
            target_sheet = "BoQ NRO All Feeder"
            scope = "SUB_FEEDER"
    elif "BoQ NRO All Feeder" in wb.sheetnames:
        target_sheet = "BoQ NRO All Feeder"
        scope = "SUB_FEEDER"
    else:
        # Fallback for generic vendor/test workbooks: ignore summary/permit/bom sheets
        for s in wb.sheetnames:
            s_low = s.lower()
            if not any(ig in s_low for ig in ["summary", "permit", "bom", "cover", "daftar"]):
                target_sheet = s
                scope = "GENERIC"
                break
        if not target_sheet and wb.sheetnames:
            target_sheet = wb.sheetnames[0]
            scope = "GENERIC"

    ws = wb[target_sheet]
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return str(target_sheet), scope, []

    # Detect header row and exact column indices
    h_idx = -1
    desc_col = 1
    unit_col = 2
    mat_qty_col = None
    svc_qty_col = None
    fallback_qty_col = None

    for i, r in enumerate(rows[:25]):
        line_s = " ".join(str(c).lower() for c in r if c is not None)
        if any(k in line_s for k in ["description", "uraian", "nama barang", "material qty", "qty"]):
            h_idx = i
            for c_idx, cell in enumerate(r):
                if cell is None:
                    continue
                cs = str(cell).strip().lower()
                if any(k in cs for k in ["description", "uraian", "nama barang", "item"]):
                    desc_col = c_idx
                elif any(k in cs for k in ["unit", "satuan"]):
                    unit_col = c_idx
                elif "material qty" in cs or "qty material" in cs or "volume material" in cs or "mat qty" in cs:
                    mat_qty_col = c_idx
                elif "service qty" in cs or "qty jasa" in cs or "jasa qty" in cs or "svc qty" in cs:
                    svc_qty_col = c_idx
                elif cs in ["qty", "quantity", "volume"] and fallback_qty_col is None:
                    fallback_qty_col = c_idx
            break

    if mat_qty_col is None:
        mat_qty_col = fallback_qty_col if fallback_qty_col is not None else 3

    items: list[dict[str, Any]] = []
    start_idx = h_idx + 1 if h_idx >= 0 else 0
    for _r_idx, r in enumerate(rows[start_idx:], start_idx):
        if not r or len(r) <= desc_col:
            continue
        raw_desc = r[desc_col]
        if not raw_desc or not isinstance(raw_desc, str) or len(raw_desc.strip()) < 3:
            continue
        desc_s = raw_desc.strip()
        d_low = desc_s.lower()

        # Filter out subtotals, grand totals, and section headings
        if any(ig in d_low for ig in ["sub total", "grand total", "subtotal", "total preparation", "total rute", "total odn", "total osp"]):
            continue

        unit = str(r[unit_col]).strip() if unit_col is not None and unit_col < len(r) and r[unit_col] is not None else ""
        mat_val = r[mat_qty_col] if mat_qty_col is not None and mat_qty_col < len(r) else None
        svc_val = r[svc_qty_col] if svc_qty_col is not None and svc_qty_col < len(r) else None

        qty = None
        is_service = False
        if isinstance(mat_val, (int, float)) and mat_val > 0 and mat_val < 100000000:
            qty = float(mat_val)
        elif svc_qty_col is not None and isinstance(svc_val, (int, float)) and svc_val > 0 and svc_val < 100000000:
            # Standalone service items like splicing / testcomm
            if any(k in d_low for k in ["splicing", "testcomm", "otdr", "opm"]):
                qty = float(svc_val)
                is_service = True

        if qty is not None:
            category = _classify_telecom_material(desc_s)
            items.append({
                "desc": desc_s,
                "unit": unit or ("Meter" if category == "CABLE" else "Pcs"),
                "qty": qty,
                "category": category,
                "is_service": is_service,
            })
    return str(target_sheet), scope, items

PLAN_OR_SPECULATIVE_WORDS = (
    "besok",
    "rencana",
    "akan ",
    "otw",
    "mau ",
    "planning",
    "jadwal",
    "target besok",
    "insyaallah",
    "gass",
    "gas ",
    "semoga",
    "nanti",
    "entar",
    "kalo ",
    "kalau ",
    "tolong",
    "mohon",
    "bisa minta",
)

def _extract_telecom_quantities_from_text(text: str) -> dict[str, float]:
    """
    Ekstraksi kuantitas material presisi tinggi dari pesan chat lapangan (Strict Mode).
    Mencegah false positive dan halusinasi angka:
    1. Mengabaikan baris yang merupakan obrolan rencana/masa depan ('besok', 'rencana', 'gass', 'akan').
    2. Membedakan nomor identitas perangkat ('FDT 2', 'FAT 01') dengan kuantitas fisik riil (wajib unit 'box'/'unit'/'pcs'/'buah'/'set').
    3. Memisahkan secara ketat antara FAT (Fiber Access Terminal/ODP) dan FDT (Fiber Distribution Terminal/ODC).
    4. Mencegah salah tafsir spesifikasi port ('FAT 16 port') atau ukuran tinggi ('tiang 7m') sebagai jumlah barang.
    5. Kabel hanya dihitung bila memiliki konteks penarikan/bentangan kabel fisik (bukan lebar jalan/jarak).
    """
    t = (text or "").lower()
    cables = 0.0
    poles = 0.0
    fats = 0.0
    fdts = 0.0

    lines = [line.strip() for line in t.splitlines() if line.strip()]
    for line in lines:
        # Jika baris adalah rencana masa depan / diskusi santai, abaikan penambahan kuantitas
        if any(pw in line for pw in PLAN_OR_SPECULATIVE_WORDS):
            continue

        # 1. Tiang via kode shorthand: T72: 10 btg, T73: 19 btg, T7.3.-15.btng., T7.2,5-10.btng, T72:12, T74: 1, T94: 2
        for m in re.finditer(
            r"\b(?:t72|t73|t74|t94|t9|t7(?:\.2[,.]5|\.3|\.4)?)\b[\s:=.-]+([0-9]+)(?:\s*(?:btg|batang|btng|pcs|titik)\b)?",
            line,
            re.IGNORECASE,
        ):
            poles += float(m.group(1))

        # 2. Tiang via deskripsi: tiang 7m: 10 btg, tanam tiang 7m 4 batang, tiang 9 meter: 5 batang
        for m in re.finditer(r"(?:tiang|pole|tanam)\s*(?:[0-9]+[\s]*(?:meter|m|\"))?[\s:=]+([0-9]+)\s*(?:btg|batang|pcs|titik)\b", line):
            poles += float(m.group(1))

        # 3. Tiang via format angka mendahului: 15 btg tiang, 8 batang tiang 7m
        for m in re.finditer(r"\b([0-9]+)\s*(?:btg|batang|pcs|titik)\s*(?:tiang|pole)\b", line):
            poles += float(m.group(1))

        # 4. Kabel: hanya diekstrak jika ada kata kunci konteks kabel di baris tersebut
        if any(k in line for k in ("kabel", "cable", "adss", "fig-8", "fig8", "drop core", "dropcore", "fo", "fiber", "tarik", "bentang", "span", "ku 24", "ku24", "udara")):
            for m in re.finditer(r"\b([0-9\.,]+)\s*(?:m|meter|mtr)\b", line):
                try:
                    val = float(m.group(1).replace(",", "."))
                    prev = line[max(0, m.start() - 12) : m.start()]
                    if "tiang" not in prev and "pole" not in prev and val > 15:
                        cables += val
                except ValueError:
                    pass

        # 5. FAT (Fiber Access Terminal) / ODP: Titik terminasi drop core pelanggan (8/16/24 port).
        # WAJIB memiliki satuan fisik eksplisit (box, unit, titik, pcs, buah, set).
        for m in re.finditer(r"\b(?:fat|odp)\s*(?:(?:8|16|24|32|48|64|[0-9]+\s*(?:c|port|core))\b)?[\s:=]*([0-9]+)\s*(?:box|unit|titik|pcs|buah|set)\b", line):
            fats += float(m.group(1))
        for m in re.finditer(r"\b([0-9]+)\s*(?:box|unit|titik|pcs|buah|set)\s*(?:fat|odp)\b", line):
            fats += float(m.group(1))

        # 6. FDT (Fiber Distribution Terminal) / ODC: Kabinet distribusi feeder-ke-distribusi (48-288 port).
        # WAJIB memiliki satuan fisik eksplisit (box, unit, titik, pcs, buah, set).
        for m in re.finditer(r"\b(?:fdt|odc)\s*(?:(?:48|72|96|144|288|[0-9]+\s*(?:c|port|core))\b)?[\s:=]*([0-9]+)\s*(?:box|unit|titik|pcs|buah|set)\b", line):
            fdts += float(m.group(1))
        for m in re.finditer(r"\b([0-9]+)\s*(?:box|unit|titik|pcs|buah|set)\s*(?:fdt|odc)\b", line):
            fdts += float(m.group(1))

    return {"cables": cables, "poles": poles, "fats": fats, "fdts": fdts}

def is_to_group(name: str) -> bool:
    """Deteksi apakah nama chat/grup adalah grup TO (Transfer Order) yang harus diabaikan."""
    if not name:
        return False
    low = name.strip().lower()
    return (
        low.startswith(("to ", "to-", "to_", "to/"))
        or " to " in low
        or "grup to" in low
        or "to grup" in low
        or "to material" in low
        or "transfer order" in low
        or "& to" in low
        or "/to" in low
        or "-to" in low
    )

def is_project_or_pengambilan(name: str) -> bool:
    """True bila chat adalah grup proyek FTTH lapangan atau grup pengambilan material resmi."""
    if not name:
        return False
    low = name.strip().lower()
    if is_to_group(low):
        return False
    if low.startswith(("+62", "08")) or low in (
        "chat pribadi",
        "telegram (chat)",
        "test verification",
        "wa: grup test",
    ):
        return False
    return (
        "imt" in low
        or "yofc" in low
        or "recon" in low
        or "pengambilan" in low
        or "ftth" in low
        or "project" in low
        or "proyek" in low
    )
