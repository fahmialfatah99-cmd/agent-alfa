"""Config pack: paket data domain siap pakai untuk cluster/tenant lain.

Pack membungkus data domain (cluster, constraint simbolik, peta nama mandor)
dalam satu berkas JSON, sehingga ALFA dapat dipakai untuk wilayah atau
tenant lain **tanpa mengubah kode core**.

Pemakaian:
    ALFA_CONFIG_PACK=demo   # di .env / secrets.env

Berkas pack berada di ``alfa/config/packs/*.json``. Pack yang tidak dikenal
tidak menggagalkan runtime — sistem kembali ke pack ``default`` dengan
peringatan.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger("Config.Packs")

PACKS_DIR = Path(__file__).resolve().parent
DEFAULT_PACK = "default"


def available_packs() -> list[str]:
    """Nama pack yang tersedia (tanpa ekstensi)."""
    return sorted(p.stem for p in PACKS_DIR.glob("*.json"))


def active_pack_name() -> str:
    """Nama pack aktif according `ALFA_CONFIG_PACK` (default: ``default``)."""
    return os.getenv("ALFA_CONFIG_PACK", "").strip() or DEFAULT_PACK


def _read_pack(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Config pack %s tidak bisa dibaca: %s", path.name, exc)
        return {}
    if not isinstance(data, dict):
        logger.warning("Config pack %s bukan objek JSON — diabaikan.", path.name)
        return {}
    return data


def load_pack(name: str | None = None) -> dict[str, Any]:
    """Muat isi pack. Pack hilang/rusak → fallback ke pack default."""
    pack_name = (name or active_pack_name()).strip() or DEFAULT_PACK
    path = PACKS_DIR / f"{pack_name}.json"
    if not path.exists():
        if pack_name != DEFAULT_PACK:
            logger.warning(
                "Config pack '%s' tidak ditemukan — memakai pack '%s'.",
                pack_name,
                DEFAULT_PACK,
            )
        path = PACKS_DIR / f"{DEFAULT_PACK}.json"
    return _read_pack(path)


def pack_data() -> dict[str, Any]:
    """Data pack aktif (dict) — dipakai `alfa.config.domain`."""
    return load_pack()
