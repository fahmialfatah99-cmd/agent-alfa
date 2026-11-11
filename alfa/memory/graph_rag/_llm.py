"""Ekstraksi triple结 relasi via LLM (Gemini)."""
from __future__ import annotations

import logging
import os
import re
import sqlite3
from typing import Any

from alfa.memory.graph_rag._db import normalize_entity_name

logger = logging.getLogger(__name__)

_GRAG_DB_ERR = (sqlite3.Error, RuntimeError, ValueError, TypeError, KeyError)

def _get_gemini_client(api_key: str | None = None) -> Any:
    """Inisialisasi klien google.genai secara aman (fallback None di CI/offline)."""
    try:
        from google.genai import Client

        key = api_key or os.getenv("GEMINI_API_KEY", "").strip()
        if not key or "CI_DUMMY" in key:
            return None
        return Client(api_key=key)
    except Exception:  # noqa: BLE001
        return None

def extract_triples_with_llm(
    text: str, doc_title: str, client: Any = None
) -> list[tuple[str, str, str, str]]:
    """
    Ekstrak Subject-Predicate-Object (SPO) triples menggunakan LLM (Open-IE).
    Kembalikan list of (source, relation, target, evidence).
    Jika gagal atau offline, fallback ke list kosong agar diproses oleh regex.
    """
    if client is None:
        client = _get_gemini_client()
    if client is None:
        return []

    try:
        prompt = (
            "Anda adalah AI Semantic Knowledge Graph Extractor.\n"
            f"Ekstrak semua relasi entitas fakta (Subject - Predicate - Object) dari teks dokumen '{doc_title}' berikut.\n"
            "Format output HARUS berupa JSON array of objects murni tanpa markdown/penjelasan:\n"
            '[{"source": "Entitas Subjek", "relation": "kata_kerja_relasi", "target": "Entitas Objek", "evidence": "Kutipan kalimat bukti"}]\n\n'
            "Aturan:\n"
            "1. Normalisasi nama subjek dan objek menjadi nama entitas ringkas.\n"
            "2. Gunakan relasi ringkas (misal: 'menggunakan', 'bagian_dari', 'terhubung_ke', 'adalah', 'berjalan_di').\n"
            "3. Hanya ekstrak fakta nyata yang ada pada teks.\n\n"
            f"Teks Dokumen:\n{text[:6000]}"
        )
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        raw_text = (response.text or "").strip()
        import json

        if "```" in raw_text:
            m = re.search(r"```(?:json)?\s*(.*?)\s*```", raw_text, re.DOTALL)
            if m:
                raw_text = m.group(1).strip()
        data = json.loads(raw_text)
        if isinstance(data, list):
            results: list[tuple[str, str, str, str]] = []
            for item in data:
                if isinstance(item, dict):
                    src = normalize_entity_name(str(item.get("source", "")))
                    rel = str(item.get("relation", "")).strip().replace(" ", "_").lower()
                    tgt = normalize_entity_name(str(item.get("target", "")))
                    ev = str(item.get("evidence", "")).strip()
                    if src and tgt and rel and src.lower() != tgt.lower():
                        results.append((src, rel, tgt, ev[:200]))
            if results:
                return results
    except _GRAG_DB_ERR as exc:  # noqa: BLE001
        logger.debug("LLM Graph extraction fallback to regex: %s", exc)
    return []
