"""Domain data for telecom field logistics.

Keeping this data out of Apex algorithms makes the engine reusable for other
clusters/tenants without editing verification or dreaming code. Sources, dari
prioritas tertinggi:

1. ``ALFA_CONFIG_PACK`` — pack JSON di ``alfa/config/packs/`` (cluster,
   constraint simbolik, peta nama mandor).
2. ``ALFA_TRACKED_CLUSTERS`` — daftar cluster dipisah koma, mis. ``LAHAT,CURUP``.
3. ``ALFA_DOMAIN_CONSTRAINTS_JSON`` — path JSON atau objek JSON inline dengan
   bentuk sama seperti :data:`SYMBOLIC_LOGISTICS_CONSTRAINTS`.
4. Nilai bawaan (pack ``default``).
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from alfa.config.packs import pack_data

logger = logging.getLogger("Config.Domain")

#: Isi config pack aktif (cluster/constraint/mandor).
_PACK: dict[str, Any] = pack_data()

_FALLBACK_TRACKED_CLUSTERS = ("LAHAT", "CURUP", "BENGKULU", "LUBUKLINGGAU")
_FALLBACK_SUMMARY_CLUSTERS = ("LAHAT", "CURUP", "BENGKULU")
_FALLBACK_CONSTRAINTS: dict[str, dict[str, Any]] = {
    "LAHAT": {
        "cluster": "CLUSTER_LAHAT",
        "mugi_bruto": 68,
        "mugi_retur": 7,
        "mugi_net": 61,
        "aqe_net": 99,
        "total_net": 160,
        "items": {"T72": 63, "T73": 94, "T74": 1, "T94": 2},
    }
}
_FALLBACK_MANDOR_NAMES: dict[str, str] = {
    "75286733418626": "Mandor Mugi",
    "+75286733418626": "Mandor Mugi",
    "8306668109995": "Mandor Aqe Setiawan",
    "+8306668109995": "Mandor Aqe Setiawan",
    "158862351048847": "Mandor Tri",
    "+158862351048847": "Mandor Tri",
    "85383638044": "Mandor Tri",
    "+85383638044": "Mandor Tri",
    "82310084343": "Mandor Eko",
    "+82310084343": "Mandor Eko",
    "122982630432902": "M Diki Darmawan",
    "+122982630432902": "M Diki Darmawan",
    "12615209821818167": "Admin Pengawas",
    "+12615209821818167": "Admin Pengawas",
    "108684466196499": "Mandor Curup",
    "+108684466196499": "Mandor Curup",
}


def _pack_clusters(key: str, fallback: tuple[str, ...]) -> tuple[str, ...]:
    raw = _PACK.get(key)
    if not isinstance(raw, list) or not raw:
        return fallback
    values = tuple(str(item).strip().upper() for item in raw if str(item).strip())
    return values or fallback


_DEFAULT_TRACKED_CLUSTERS = _pack_clusters("clusters", _FALLBACK_TRACKED_CLUSTERS)
_DEFAULT_SUMMARY_CLUSTERS = _pack_clusters("summary_clusters", _FALLBACK_SUMMARY_CLUSTERS)

DEFAULT_CLUSTER = _DEFAULT_TRACKED_CLUSTERS[0] if _DEFAULT_TRACKED_CLUSTERS else "LAHAT"


def _env_clusters() -> tuple[str, ...]:
    raw = os.getenv("ALFA_TRACKED_CLUSTERS", "").strip()
    if not raw:
        return _DEFAULT_TRACKED_CLUSTERS
    values = tuple(part.strip().upper() for part in raw.split(",") if part.strip())
    return values or _DEFAULT_TRACKED_CLUSTERS


TRACKED_CLUSTERS: tuple[str, ...] = _env_clusters()
SUMMARY_CLUSTERS: tuple[str, ...] = tuple(
    c for c in _DEFAULT_SUMMARY_CLUSTERS if c in TRACKED_CLUSTERS
) or TRACKED_CLUSTERS[:3]

_DEFAULT_SYMBOLIC_CONSTRAINTS: dict[str, dict[str, Any]] = {
    str(cluster).upper(): dict(values)
    for cluster, values in (_PACK.get("constraints") or _FALLBACK_CONSTRAINTS).items()
    if isinstance(values, dict)
} or dict(_FALLBACK_CONSTRAINTS)


def _load_constraints_override() -> dict[str, dict[str, Any]]:
    raw = os.getenv("ALFA_DOMAIN_CONSTRAINTS_JSON", "").strip()
    if not raw:
        return _DEFAULT_SYMBOLIC_CONSTRAINTS
    try:
        if raw.startswith("{"):
            parsed = json.loads(raw)
        else:
            with open(os.path.expanduser(raw), encoding="utf-8") as fh:
                parsed = json.load(fh)
        if not isinstance(parsed, dict):
            logger.warning(
                "ALFA_DOMAIN_CONSTRAINTS_JSON must be a JSON object; using built-in defaults"
            )
            return _DEFAULT_SYMBOLIC_CONSTRAINTS
        return {
            str(cluster).upper(): dict(values)
            for cluster, values in parsed.items()
            if isinstance(values, dict)
        }
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        logger.warning(
            "ALFA_DOMAIN_CONSTRAINTS_JSON invalid (%s); using built-in defaults",
            exc,
        )
        return _DEFAULT_SYMBOLIC_CONSTRAINTS


SYMBOLIC_LOGISTICS_CONSTRAINTS: dict[str, dict[str, Any]] = _load_constraints_override()

#: Canonical WhatsApp/LID sender -> human-readable field supervisor names.
#: Keep both raw and ``+``-prefixed variants because stored message senders vary.
#: Diambil dari config pack bila tersedia, jika tidak memakai peta bawaan.
MANDOR_NAME_MAP: dict[str, str] = {
    str(key): str(value)
    for key, value in (_PACK.get("mandor_names") or _FALLBACK_MANDOR_NAMES).items()
} or dict(_FALLBACK_MANDOR_NAMES)


def detect_cluster(text: str, fallback: str = DEFAULT_CLUSTER) -> str:
    """Return the first tracked cluster mentioned in *text* (case-insensitive)."""
    low = (text or "").lower()
    for candidate in TRACKED_CLUSTERS:
        if candidate.lower() in low:
            return candidate
    return (fallback or DEFAULT_CLUSTER).strip().upper()


#: Verified deterministic fast-paths seeded by the Apex dreaming compiler.
FASTPATH_SEEDS: tuple[tuple[str, str, str, str, int], ...] = (
    (
        "CLUSTER_LAHAT_POLE_SUMMARY",
        r"^\s*(?:berapa|cek|info|total|rekap)?\s*(?:jumlah\s+|total\s+)?tiang\s+(?:bersih\s+|net\s+)?(?:cluster\s+)?lahat\s*\??\s*$",
        (
            "📊 *REKAP CEPAT TIANG CLUSTER LAHAT (Verified Symbolic Fast-Path)*\n\n"
            "• *Total Pengambilan Bersih (Net):* `160 Batang`\n"
            "• *Rincian per Mandor:*\n"
            "  1. Mandor Mugi: `61 batang net` (68 diambil bruto − 7 retur)\n"
            "  2. Mandor Aqe Setiawan: `99 batang net`\n"
            "• *Rincian per Tipe Tiang:*\n"
            "  - Tiang 7m 2.5\" (T72): `63 batang`\n"
            "  - Tiang 7m 3\" (T73): `94 batang`\n"
            "  - Tiang 7m 4\" (T74): `1 batang`\n"
            "  - Tiang 9m 4\" (T94): `2 batang`\n\n"
            "⚡ _Dieksekusi instan via Apex Compiled Fast-Path (0 token, terverifikasi Neuro-Symbolic)._"
        ),
        "seed_lahat_160",
        1200,
    ),
    (
        "CLUSTER_CURUP_POLE_SUMMARY",
        r"^\s*(?:berapa|cek|info|total|rekap)?\s*(?:jumlah\s+|total\s+)?tiang\s+(?:bersih\s+|net\s+)?(?:cluster\s+)?curup\s*\??\s*$",
        (
            "📊 *REKAP CEPAT TIANG CLUSTER CURUP (Verified Symbolic Fast-Path)*\n\n"
            "• *Total Pengambilan Bersih (Net):* `27 Batang`\n"
            "• *Rincian Lokasi / Site:*\n"
            "  1. Lubuk Kembang: `17 batang` (T73 7m 3\")\n"
            "  2. Air Lanang: `10 batang` (T73 7m 3\")\n"
            "• *Mandor Pelapor:* `Mandor Curup`\n"
            "• *Aksesoris FTTH Terverifikasi:*\n"
            "  - Stoping: `100 pcs` | Dead End: `80 pcs`\n"
            "  - Full Clamp/Pole Clamp: `60 pcs` | Suspen: `10 pcs`\n"
            "  - Slack Hanger: `49 pcs` | Clamp Buaya: `85 pcs`\n\n"
            "⚡ _Dieksekusi instan via Apex Compiled Fast-Path (0 token, terverifikasi Neuro-Symbolic)._"
        ),
        "seed_curup_27",
        1200,
    ),
)
