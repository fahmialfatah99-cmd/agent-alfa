"""LLM planner: model selection and next-action planning."""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

logger = logging.getLogger("AgentTools.Web.Browser")

# ── LLM planner (sinkron, dipanggil dari thread tool) ───────────────────────
_MODEL_CACHE: list[str] = []


def _candidate_models(cfg: dict[str, Any]) -> list[str]:
    """Urutan model: yang terkonfigurasi dulu, lalu cadangan dari .env."""
    out: list[str] = []
    for m in _MODEL_CACHE + [
        cfg.get("model") or "",
        os.getenv("GEMINI_MODEL", "").strip(),
        "gemini-3.5-flash-lite",
    ]:
        if m and m not in out:
            out.append(m)
    return out


def _remember_model(model: str) -> None:
    """Catat model yang terbukti jalan agar langkah berikutnya tidak kena 429 lagi."""
    if model in _MODEL_CACHE:
        _MODEL_CACHE.remove(model)
    _MODEL_CACHE.insert(0, model)


def _llm_complete(prompt: str, system: str, timeout: float = 25.0) -> str:
    from alfa.core import brain

    cfg = brain.get_main_brain() or {}
    provider = (cfg.get("provider") or "").lower()
    key = cfg.get("api_key") or ""
    if not key:
        raise RuntimeError("konfigurasi LLM (api key) tidak tersedia")

    last_err: Exception | None = None

    if "gemini" in provider or provider in ("google", "vertex"):
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=key)
        for model in _candidate_models(cfg):
            try:
                resp = client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=system,
                        temperature=0.1,
                        max_output_tokens=700,
                    ),
                )
                if resp.text:
                    _remember_model(model)
                    return str(resp.text).strip()
            except Exception as e:  # noqa: BLE001
                last_err = e
                logger.info("planner model %s gagal (%s) -> coba cadangan", model, e)
        raise last_err or RuntimeError("semua model Gemini gagal")

    import httpx

    base = (cfg.get("base_url") or "").rstrip("/")
    if not base:
        raise RuntimeError("provider non-gemini tanpa base_url")
    for model in _candidate_models(cfg):
        try:
            r = httpx.post(
                f"{base}/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.1,
                    "max_tokens": 700,
                },
                timeout=timeout,
            )
            if r.status_code >= 400:
                raise RuntimeError(f"HTTP {r.status_code}: {r.text[:160]}")
            text = (r.json()["choices"][0]["message"]["content"] or "").strip()
            if text:
                _remember_model(model)
                return text
        except Exception as e:  # noqa: BLE001
            last_err = e
            logger.info("planner model %s gagal (%s) -> coba cadangan", model, e)
    raise last_err or RuntimeError("semua model cadangan gagal")


_PLAN_SYSTEM = (
    "Kamu perencana otomasi browser. Balas HANYA JSON valid tanpa teks lain, "
    "tanpa markdown fence."
)


def _parse_json_obj(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    t = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    try:
        obj = json.loads(t)
        return obj if isinstance(obj, dict) else None
    except Exception:  # noqa: BLE001
        pass
    m = re.search(r"\{.*\}", t, re.DOTALL)
    if m:
        try:
            obj = json.loads(m.group(0))
            return obj if isinstance(obj, dict) else None
        except Exception:  # noqa: BLE001
            return None
    return None


_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "please",
    "open",
    "go",
    "find",
    "search",
    "look",
    "page",
    "website",
    "site",
    "web",
    "into",
    "from",
    "that",
    "this",
    "guna",
    "yang",
    "untuk",
    "dari",
    "dan",
    "atau",
    "buka",
    "cari",
    "halaman",
}


def _heuristic_plan(
    task: str, elements: list[dict[str, Any]], cap: int
) -> dict[str, Any]:
    """Rencana cadangan ketika planner LLM tidak bisa dipanggil (kuota/error)."""
    words = [
        w
        for w in re.findall(r"[a-zA-Z0-9_-]{3,}", (task or "").lower())
        if w not in _STOPWORDS
    ]
    best_i, best_score, best_word = -1, 0, ""
    for i, el in enumerate(elements):
        hay = " ".join(
            str(el.get(k) or "") for k in ("text", "href", "name", "type")
        ).lower()
        score = sum(1 for w in words if w in hay)
        if score > best_score:
            best_i, best_score, best_word = (
                i,
                score,
                next((w for w in words if w in hay), ""),
            )
    if best_i >= 0 and best_score > 0:
        return {
            "action": "click",
            "ref": f"e{best_i + 1}",
            "reason": f"pencocokan kata kunci '{best_word}' (mode heuristik)",
        }
    if cap > 1:
        return {"action": "scroll", "reason": "mode heuristik: telusuri halaman"}
    return {
        "action": "done",
        "reason": "planner LLM tidak tersedia dan tidak ada elemen yang cocok",
    }


def _plan_next_action(
    task: str, url: str, snapshot_text: str, history: list[str], step: int, cap: int
) -> dict[str, Any]:
    prompt = (
        f"TUGAS: {task[:600]}\n"
        f"URL SEKARANG: {url}\n"
        f"LANGKAH: {step + 1} dari {cap}\n"
        f"RIWAYAT: {' | '.join(history[-6:]) or '(belum ada)'}\n\n"
        f"ELEMEN INTERAKTIF YANG TERLIHAT:\n{snapshot_text[:3500]}\n\n"
        "Balas HANYA JSON:\n"
        '{"action":"click|type|scroll|goto|done","ref":"e12",'
        '"text":"isi input bila action=type","url":"https://... bila action=goto",'
        '"reason":"alasan singkat"}\n'
        "Pakai ref persis dari daftar. Pilih done bila tugas sudah tercapai "
        "atau mustahil dilakukan dari halaman ini."
    )
    raw = _llm_complete(prompt, _PLAN_SYSTEM)
    plan = _parse_json_obj(raw)
    if not plan:
        raise RuntimeError(f"planner tidak menghasilkan JSON: {raw[:160]}")
    action = str(plan.get("action") or "").strip().lower()
    if action not in ("click", "type", "scroll", "goto", "done"):
        raise RuntimeError(f"aksi tidak dikenal: {action!r}")
    return plan
