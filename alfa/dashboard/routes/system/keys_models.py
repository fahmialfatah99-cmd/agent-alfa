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

# ==================== API KEYS & MODEL REGISTRY ====================


@router.get("/api/keys")
async def get_api_keys():
    """List all API keys with masked values."""
    keys = database.list_api_keys_sync()
    return {"status": "success", "total": len(keys), "keys": keys}


@router.get("/api/keys/usage")
async def get_api_keys_usage(hours: int = 24):
    """Realtime token-usage summary per API key/provider for the dashboard."""
    hours = safe_int(hours, 24, minimum=1, maximum=720)
    keys = database.list_api_keys_sync()
    key_names = {k["id"]: k["name"] for k in keys}
    summary = database.get_api_usage_summary_sync(hours=hours)
    for row in summary.get("per_key", []):
        row["key_name"] = (
            key_names.get(row.get("key_id")) or row.get("key_label") or "(env)"
        )
    return {"status": "success", **summary}


@router.post("/api/keys")
async def add_api_key_endpoint(payload: Dict[str, Any]):
    """Add a new API key to the vault."""
    name = payload.get("name")
    provider = payload.get("provider", "gemini")
    api_key = payload.get("api_key")
    default_model = payload.get("default_model", "gemini-3.6-flash")
    base_url = payload.get("base_url", "")
    set_active = payload.get("set_active", True)

    if not api_key:
        raise HTTPException(status_code=400, detail="api_key is required")

    res = database.add_api_key_sync(
        name=name or f"{provider.capitalize()} Key",
        provider=provider,
        api_key=api_key,
        default_model=default_model,
        base_url=base_url,
        set_active=set_active,
    )
    return res


@router.post("/api/keys/{key_id}/activate")
async def activate_api_key_endpoint(key_id: int):
    """Set an API key as active."""
    res = database.activate_api_key_sync(key_id)
    return res


@router.delete("/api/keys/{key_id}")
async def delete_api_key_endpoint(key_id: int):
    """Delete an API key."""
    res = database.delete_api_key_sync(key_id)
    return res


@router.post("/api/keys/{key_id}/test")
async def test_api_key_endpoint(key_id: int):
    """Test ping connection for a stored API key."""
    with database.get_sync_db() as conn:
        row = conn.execute("SELECT * FROM api_keys WHERE id = ?", (key_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="API Key tidak ditemukan")
        key_data = dict(row)

    from alfa.swarm import engine as swarm_engine

    dummy_agent = {
        "name": f"Tester-{key_data['provider']}",
        "provider": key_data["provider"],
        "model": key_data["default_model"],
        "api_key_id": key_id,
    }
    start_t = time.time()
    resp = await swarm_engine.generate_agent_response(
        agent=dummy_agent,
        prompt="Katakan 'Koneksi Berhasil' dalam 3 kata.",
        system_instruction="Kamu adalah modul health checker. Jawab dengan sangat singkat.",
    )
    duration_ms = round((time.time() - start_t) * 1000, 1)
    is_error = "[Error:" in resp or "Gagal memanggil" in resp

    return {
        "status": "error" if is_error else "success",
        "key_id": key_id,
        "provider": key_data["provider"],
        "model": key_data["default_model"],
        "duration_ms": duration_ms,
        "response": resp,
    }


PROVIDER_MODELS = {
    "antigravity": [
        {
            "id": "gemini-3.6-flash",
            "name": "Gemini 3.6 Flash (Terbaru - Medium Thinking)",
            "category": "Antigravity OAuth",
            "pricing": "free_oauth",
            "pricing_label": "🟢 GRATIS (Kuota Antigravity)",
        },
        {
            "id": "gemini-3.5-flash",
            "name": "Gemini 3.5 Flash (Cepat - Default Antigravity)",
            "category": "Antigravity OAuth",
            "pricing": "free_oauth",
            "pricing_label": "🟢 GRATIS (Kuota Antigravity)",
        },
        {
            "id": "gemini-3-flash",
            "name": "Gemini 3 Flash",
            "category": "Antigravity OAuth",
            "pricing": "free_oauth",
            "pricing_label": "🟢 GRATIS (Kuota Antigravity)",
        },
        {
            "id": "gemini-3.1-pro",
            "name": "Gemini 3.1 Pro (Penalaran Kompleks)",
            "category": "Antigravity Pro Models",
            "pricing": "free_oauth",
            "pricing_label": "🟢 GRATIS (Kuota Antigravity)",
        },
        {
            "id": "gemini-2.5-pro",
            "name": "Gemini 2.5 Pro",
            "category": "Antigravity Pro Models",
            "pricing": "free_oauth",
            "pricing_label": "🟢 GRATIS",
        },
        {
            "id": "gemini-2.5-flash",
            "name": "Gemini 2.5 Flash",
            "category": "Antigravity OAuth",
            "pricing": "free_oauth",
            "pricing_label": "🟢 GRATIS",
        },
        {
            "id": "claude-sonnet-4.6",
            "name": "Claude Sonnet 4.6 (via Antigravity)",
            "category": "Claude via Antigravity",
            "pricing": "free_oauth",
            "pricing_label": "🟢 GRATIS",
        },
        {
            "id": "claude-opus-4.6",
            "name": "Claude Opus 4.6 Thinking (via Antigravity)",
            "category": "Claude via Antigravity",
            "pricing": "free_oauth",
            "pricing_label": "🟢 GRATIS",
        },
        {
            "id": "gpt-oss-120b",
            "name": "GPT-OSS 120B Medium (OpenAI via Antigravity)",
            "category": "GPT-OSS via Antigravity",
            "pricing": "free_oauth",
            "pricing_label": "🟢 GRATIS (Kuota Antigravity)",
        },
    ],
    "nvidia": [
        {
            "id": "nvidia/llama-3.1-nemotron-70b-instruct",
            "name": "NVIDIA Nemotron 70B Ultra Instruct (Model Unggulan NVIDIA)",
            "category": "NVIDIA Nemotron Ultra",
            "pricing": "free_credits",
            "pricing_label": "🟢 GRATIS (1000 NIM Credits)",
        },
        {
            "id": "nvidia/nemotron-4-340b-instruct",
            "name": "NVIDIA Nemotron-4 340B Instruct (Model Raksasa 340B)",
            "category": "NVIDIA Nemotron Ultra",
            "pricing": "free_credits",
            "pricing_label": "🟢 GRATIS (1000 NIM Credits)",
        },
        {
            "id": "nvidia/llama-3.1-nemotron-51b-instruct",
            "name": "NVIDIA Nemotron 51B Instruct (Efisiensi Tinggi)",
            "category": "NVIDIA Nemotron Ultra",
            "pricing": "free_credits",
            "pricing_label": "🟢 GRATIS (1000 NIM Credits)",
        },
        {
            "id": "nvidia/nemotron-mini-4b-instruct",
            "name": "NVIDIA Nemotron Mini 4B Instruct (Ringan & Cepat)",
            "category": "NVIDIA Nemotron Ultra",
            "pricing": "free_credits",
            "pricing_label": "🟢 GRATIS (1000 NIM Credits)",
        },
        {
            "id": "nvidia/mistral-nemo-minitron-8b-8k-instruct",
            "name": "NVIDIA Minitron 8B 8k Instruct (Kompak & Cerdas)",
            "category": "NVIDIA Nemotron Ultra",
            "pricing": "free_credits",
            "pricing_label": "🟢 GRATIS (1000 NIM Credits)",
        },
        {
            "id": "nvidia/llama-3.2-11b-vision-instruct",
            "name": "NVIDIA Llama 3.2 11B Vision Instruct (Multimodal)",
            "category": "NVIDIA Vision",
            "pricing": "free_credits",
            "pricing_label": "🟢 GRATIS (1000 NIM Credits)",
        },
        {
            "id": "nvidia/llama-3.2-90b-vision-instruct",
            "name": "NVIDIA Llama 3.2 90B Vision Instruct (Vision Pro)",
            "category": "NVIDIA Vision",
            "pricing": "free_credits",
            "pricing_label": "🟢 GRATIS (1000 NIM Credits)",
        },
        {
            "id": "nvidia/llama-3.2-1b-instruct",
            "name": "NVIDIA Llama 3.2 1B Instruct (Ultra Ringan)",
            "category": "NVIDIA Nemotron Ultra",
            "pricing": "free_credits",
            "pricing_label": "🟢 GRATIS (1000 NIM Credits)",
        },
        {
            "id": "nvidia/llama-3.2-3b-instruct",
            "name": "NVIDIA Llama 3.2 3B Instruct (Ringan)",
            "category": "NVIDIA Nemotron Ultra",
            "pricing": "free_credits",
            "pricing_label": "🟢 GRATIS (1000 NIM Credits)",
        },
        {
            "id": "deepseek-ai/deepseek-r1",
            "name": "DeepSeek R1 671B (Penalaran & Logic Terkuat Dunia)",
            "category": "DeepSeek Reasoning",
            "pricing": "free_credits",
            "pricing_label": "🟢 GRATIS (1000 NIM Credits)",
        },
        {
            "id": "deepseek-ai/deepseek-v3",
            "name": "DeepSeek V3 671B (MoE Cerdas & Sangat Cepat)",
            "category": "DeepSeek General",
            "pricing": "free_credits",
            "pricing_label": "🟢 GRATIS (1000 NIM Credits)",
        },
        {
            "id": "deepseek-ai/deepseek-r1-distill-qwen-32b",
            "name": "DeepSeek R1 Distill Qwen 32B (Reasoning Cepat)",
            "category": "DeepSeek Reasoning",
            "pricing": "free_credits",
            "pricing_label": "🟢 GRATIS (1000 NIM Credits)",
        },
        {
            "id": "deepseek-ai/deepseek-r1-distill-qwen-14b",
            "name": "DeepSeek R1 Distill Qwen 14B (Reasoning Ringan)",
            "category": "DeepSeek Reasoning",
            "pricing": "free_credits",
            "pricing_label": "🟢 GRATIS (1000 NIM Credits)",
        },
        {
            "id": "deepseek-ai/deepseek-r1-distill-llama-70b",
            "name": "DeepSeek R1 Distill Llama 70B (Reasoning Kuat)",
            "category": "DeepSeek Reasoning",
            "pricing": "free_credits",
            "pricing_label": "🟢 GRATIS (1000 NIM Credits)",
        },
        {
            "id": "deepseek-ai/deepseek-r1-distill-llama-8b",
            "name": "DeepSeek R1 Distill Llama 8B (Kilat)",
            "category": "DeepSeek Reasoning",
            "pricing": "free_credits",
            "pricing_label": "🟢 GRATIS (1000 NIM Credits)",
        },
        {
            "id": "meta/llama-3.3-70b-instruct",
            "name": "Meta Llama 3.3 70B Instruct (Rekomendasi Utama)",
            "category": "Meta Flagship",
            "pricing": "free_credits",
            "pricing_label": "🟢 GRATIS (1000 NIM Credits)",
        },
        {
            "id": "meta/llama-3.1-405b-instruct",
            "name": "Meta Llama 3.1 405B Instruct (Model Flagship Raksasa)",
            "category": "Meta Flagship",
            "pricing": "free_credits",
            "pricing_label": "🟢 GRATIS (1000 NIM Credits)",
        },
        {
            "id": "meta/llama-3.1-70b-instruct",
            "name": "Meta Llama 3.1 70B Instruct",
            "category": "Meta General",
            "pricing": "free_credits",
            "pricing_label": "🟢 GRATIS (1000 NIM Credits)",
        },
        {
            "id": "meta/llama-3.1-8b-instruct",
            "name": "Meta Llama 3.1 8B Instruct (Super Cepat)",
            "category": "Meta Fast",
            "pricing": "free_credits",
            "pricing_label": "🟢 GRATIS (1000 NIM Credits)",
        },
        {
            "id": "qwen/qwen2.5-coder-32b-instruct",
            "name": "Qwen 2.5 Coder 32B (Spesialis Kode & Programming)",
            "category": "Qwen Coding",
            "pricing": "free_credits",
            "pricing_label": "🟢 GRATIS (1000 NIM Credits)",
        },
        {
            "id": "qwen/qwen2.5-coder-7b-instruct",
            "name": "Qwen 2.5 Coder 7B (Coding Cepat)",
            "category": "Qwen Coding",
            "pricing": "free_credits",
            "pricing_label": "🟢 GRATIS (1000 NIM Credits)",
        },
        {
            "id": "qwen/qwen2.5-72b-instruct",
            "name": "Qwen 2.5 72B Instruct (General Terkuat)",
            "category": "Qwen General",
            "pricing": "free_credits",
            "pricing_label": "🟢 GRATIS (1000 NIM Credits)",
        },
        {
            "id": "qwen/qwen2.5-32b-instruct",
            "name": "Qwen 2.5 32B Instruct",
            "category": "Qwen General",
            "pricing": "free_credits",
            "pricing_label": "🟢 GRATIS (1000 NIM Credits)",
        },
        {
            "id": "qwen/qwen2.5-14b-instruct",
            "name": "Qwen 2.5 14B Instruct",
            "category": "Qwen General",
            "pricing": "free_credits",
            "pricing_label": "🟢 GRATIS (1000 NIM Credits)",
        },
        {
            "id": "qwen/qwen2.5-7b-instruct",
            "name": "Qwen 2.5 7B Instruct",
            "category": "Qwen Fast",
            "pricing": "free_credits",
            "pricing_label": "🟢 GRATIS (1000 NIM Credits)",
        },
        {
            "id": "mistralai/mixtral-8x22b-instruct-v0.1",
            "name": "Mistral Mixtral 8x22B Instruct (MoE Kuat)",
            "category": "Mistral MoE",
            "pricing": "free_credits",
            "pricing_label": "🟢 GRATIS (1000 NIM Credits)",
        },
        {
            "id": "mistralai/mixtral-8x7b-instruct-v0.1",
            "name": "Mistral Mixtral 8x7B Instruct",
            "category": "Mistral MoE",
            "pricing": "free_credits",
            "pricing_label": "🟢 GRATIS (1000 NIM Credits)",
        },
        {
            "id": "mistralai/mistral-large-2-instruct",
            "name": "Mistral Large 2 Instruct (Flagship)",
            "category": "Mistral Flagship",
            "pricing": "free_credits",
            "pricing_label": "🟢 GRATIS (1000 NIM Credits)",
        },
        {
            "id": "mistralai/mistral-nemo-12b-instruct",
            "name": "Mistral NeMo 12B Instruct",
            "category": "Mistral General",
            "pricing": "free_credits",
            "pricing_label": "🟢 GRATIS (1000 NIM Credits)",
        },
        {
            "id": "mistralai/codestral-22b-instruct-v0.1",
            "name": "Mistral Codestral 22B (Coding)",
            "category": "Mistral Coding",
            "pricing": "free_credits",
            "pricing_label": "🟢 GRATIS (1000 NIM Credits)",
        },
        {
            "id": "microsoft/phi-4",
            "name": "Microsoft Phi 4 (14B Penalaran Akurat)",
            "category": "Microsoft Phi",
            "pricing": "free_credits",
            "pricing_label": "🟢 GRATIS (1000 NIM Credits)",
        },
        {
            "id": "microsoft/phi-3.5-moe-instruct",
            "name": "Microsoft Phi 3.5 MoE Instruct",
            "category": "Microsoft Phi",
            "pricing": "free_credits",
            "pricing_label": "🟢 GRATIS (1000 NIM Credits)",
        },
        {
            "id": "microsoft/phi-3.5-mini-instruct",
            "name": "Microsoft Phi 3.5 Mini Instruct",
            "category": "Microsoft Phi",
            "pricing": "free_credits",
            "pricing_label": "🟢 GRATIS (1000 NIM Credits)",
        },
        {
            "id": "google/gemma-2-27b-it",
            "name": "Google Gemma 2 27B IT",
            "category": "Google Gemma",
            "pricing": "free_credits",
            "pricing_label": "🟢 GRATIS (1000 NIM Credits)",
        },
        {
            "id": "google/gemma-2-9b-it",
            "name": "Google Gemma 2 9B IT",
            "category": "Google Gemma",
            "pricing": "free_credits",
            "pricing_label": "🟢 GRATIS (1000 NIM Credits)",
        },
    ],
    "deepseek": [
        {
            "id": "deepseek-chat",
            "name": "DeepSeek-V3 671B MoE (Sangat Cerdas & Cepat)",
            "category": "DeepSeek Official",
            "pricing": "free_tier",
            "pricing_label": "🟢 SANGAT MURAH ($0.14/1M)",
        },
        {
            "id": "deepseek-reasoner",
            "name": "DeepSeek-R1 671B (Penalaran & Logic Terkuat)",
            "category": "DeepSeek Official",
            "pricing": "free_tier",
            "pricing_label": "🟢 SANGAT MURAH ($0.55/1M)",
        },
        {
            "id": "deepseek-coder",
            "name": "DeepSeek Coder 33B (Spesialis Kode)",
            "category": "DeepSeek Official",
            "pricing": "free_tier",
            "pricing_label": "🟢 SANGAT MURAH ($0.14/1M)",
        },
    ],
    "minimax": [
        {
            "id": "MiniMax-Text-01",
            "name": "MiniMax-01 Flagship (Konteks Raksasa 4 Juta Token)",
            "category": "MiniMax AI",
            "pricing": "free_tier",
            "pricing_label": "🟢 FREE TRIAL / Murah",
        },
        {
            "id": "abab6.5s-chat",
            "name": "MiniMax abab6.5s (Ultra-Fast MoE)",
            "category": "MiniMax AI",
            "pricing": "free_tier",
            "pricing_label": "🟢 FREE TRIAL / Murah",
        },
        {
            "id": "abab6.5g-chat",
            "name": "MiniMax abab6.5g (General Knowledge)",
            "category": "MiniMax AI",
            "pricing": "paid",
            "pricing_label": "💎 BERBAYAR",
        },
        {
            "id": "abab6.5t-chat",
            "name": "MiniMax abab6.5t (Long Context)",
            "category": "MiniMax AI",
            "pricing": "paid",
            "pricing_label": "💎 BERBAYAR",
        },
    ],
    "moonshot": [
        {
            "id": "moonshot-v1-8k",
            "name": "Moonshot Kimi v1 8K (Cerdas & Cepat)",
            "category": "Moonshot Kimi",
            "pricing": "free_tier",
            "pricing_label": "🟢 FREE TRIAL (15 RMB Bonus)",
        },
        {
            "id": "moonshot-v1-32k",
            "name": "Moonshot Kimi v1 32K",
            "category": "Moonshot Kimi",
            "pricing": "free_tier",
            "pricing_label": "🟢 FREE TRIAL",
        },
        {
            "id": "moonshot-v1-128k",
            "name": "Moonshot Kimi v1 128K (Konteks Panjang)",
            "category": "Moonshot Kimi",
            "pricing": "paid",
            "pricing_label": "💎 BERBAYAR",
        },
    ],
    "qwen": [
        {
            "id": "qwen-max",
            "name": "Qwen 2.5 Max (Flagship Alibaba Cloud Terkuat)",
            "category": "Alibaba Qwen",
            "pricing": "free_tier",
            "pricing_label": "🟢 FREE TRIAL / Token",
        },
        {
            "id": "qwen-plus",
            "name": "Qwen 2.5 Plus (Keseimbangan Sempurna)",
            "category": "Alibaba Qwen",
            "pricing": "free_tier",
            "pricing_label": "🟢 SANGAT MURAH",
        },
        {
            "id": "qwen-turbo",
            "name": "Qwen 2.5 Turbo (Kilat & Ringan)",
            "category": "Alibaba Qwen",
            "pricing": "free_tier",
            "pricing_label": "🟢 SANGAT MURAH",
        },
        {
            "id": "qwen2.5-coder-32b-instruct",
            "name": "Qwen 2.5 Coder 32B (Spesialis Kode)",
            "category": "Alibaba Qwen",
            "pricing": "free_tier",
            "pricing_label": "🟢 FREE TRIAL",
        },
    ],
    "gemini": [
        {
            "id": "gemini-3.7-flash",
            "name": "Gemini 3.7 Flash (Generasi Termbaru)",
            "category": "Gemini Terbaru",
            "pricing": "free_tier",
            "pricing_label": "🟢 Aktif",
        },
        {
            "id": "gemini-3.6-flash",
            "name": "Gemini 3.6 Flash",
            "category": "Gemini Terbaru",
            "pricing": "free_tier",
            "pricing_label": "🟢 Aktif",
        },
        {
            "id": "gemini-3.5-flash",
            "name": "Gemini 3.5 Flash [DEPRECATED]",
            "category": "Legacy (Jangan Pakai)",
            "pricing": "free_tier",
            "pricing_label": "⚠️ Deprecated",
        },
        {
            "id": "gemini-3.5-flash-lite",
            "name": "Gemini 3.5 Flash Lite [DEPRECATED]",
            "category": "Legacy (Jangan Pakai)",
            "pricing": "free_tier",
            "pricing_label": "⚠️ Deprecated",
        },
        {
            "id": "gemini-3.1-pro-preview",
            "name": "Gemini 3.1 Pro Preview (Penalaran Kompleks)",
            "category": "Gemini 3.1 Pro",
            "pricing": "free_tier",
            "pricing_label": "🟢 Aktif",
        },
        {
            "id": "gemini-3.1-flash-lite",
            "name": "Gemini 3.1 Flash Lite",
            "category": "Gemini 3.1",
            "pricing": "free_tier",
            "pricing_label": "🟢 Aktif",
        },
        {
            "id": "gemini-3-flash-preview",
            "name": "Gemini 3 Flash Preview",
            "category": "Gemini 3.1",
            "pricing": "free_tier",
            "pricing_label": "🟢 Aktif",
        },
        {
            "id": "gemini-omni-flash-preview",
            "name": "Gemini Omni Flash Preview (Multimodal)",
            "category": "Gemini Terbaru",
            "pricing": "free_tier",
            "pricing_label": "🟢 Aktif",
        },
        {
            "id": "gemini-flash-latest",
            "name": "Gemini Flash Latest (Otomatis Versi Termbaru)",
            "category": "Latest Alias",
            "pricing": "free_tier",
            "pricing_label": "🟢 Aktif",
        },
        {
            "id": "gemini-flash-lite-latest",
            "name": "Gemini Flash Lite Latest",
            "category": "Latest Alias",
            "pricing": "free_tier",
            "pricing_label": "🟢 Aktif",
        },
        {
            "id": "gemini-pro-latest",
            "name": "Gemini Pro Latest (Flagship)",
            "category": "Latest Alias",
            "pricing": "free_tier",
            "pricing_label": "🟢 Aktif",
        },
        {
            "id": "gemini-2.5-pro",
            "name": "Gemini 2.5 Pro [DEPRECATED]",
            "category": "Legacy (Jangan Pakai)",
            "pricing": "free_tier",
            "pricing_label": "⚠️ Deprecated",
        },
    ],
}


@router.get("/api/models")
async def get_available_models():
    """Get verified models list per provider with live discovery from NVIDIA & OpenRouter."""
    import httpx

    try:
        async with httpx.AsyncClient(timeout=2.5) as client:
            r = await client.get("https://integrate.api.nvidia.com/v1/models")
            if r.status_code == 200:
                live_data = r.json().get("data", [])
                existing_ids = {m["id"] for m in PROVIDER_MODELS["nvidia"]}
                for item in live_data:
                    mid = item.get("id")
                    if mid and mid not in existing_ids:
                        cat = "NVIDIA Live Models"
                        if "nemotron" in mid:
                            cat = "NVIDIA Nemotron Ultra"
                        elif "llama" in mid:
                            cat = "Meta Llama on NVIDIA"
                        elif "mistral" in mid:
                            cat = "Mistral on NVIDIA"
                        elif "deepseek" in mid:
                            cat = "DeepSeek on NVIDIA"
                        elif "google" in mid or "gemma" in mid:
                            cat = "Google on NVIDIA"

                        PROVIDER_MODELS["nvidia"].append(
                            {
                                "id": mid,
                                "name": f"{mid} (Live NVIDIA NIM)",
                                "category": cat,
                                "pricing": "free_credits",
                                "pricing_label": "🟢 GRATIS (1000 NIM Credits)",
                            }
                        )
    except Exception:
        pass

    try:
        async with httpx.AsyncClient(timeout=2.5) as client:
            r = await client.get("https://openrouter.ai/api/v1/models")
            if r.status_code == 200:
                live_or = r.json().get("data", [])
                existing_or_ids = {m["id"] for m in PROVIDER_MODELS["openrouter"]}
                for item in live_or:
                    mid = item.get("id")
                    mname = item.get("name", mid)
                    if mid and mid not in existing_or_ids:
                        is_free = ":free" in mid
                        PROVIDER_MODELS["openrouter"].append(
                            {
                                "id": mid,
                                "name": f"{mname} ({mid})",
                                "category": (
                                    "OpenRouter Free"
                                    if is_free
                                    else "OpenRouter Live Catalog"
                                ),
                                "pricing": "free" if is_free else "paid",
                                "pricing_label": (
                                    "🟢 100% GRATIS" if is_free else "💎 BERBAYAR"
                                ),
                            }
                        )
    except Exception:
        pass

    try:
        async with httpx.AsyncClient(timeout=1.5) as client:
            r = await client.get("http://127.0.0.1:20128/v1/models")
            if r.status_code == 200:
                live_9r = r.json().get("data", [])
                existing_9r_ids = {m["id"] for m in PROVIDER_MODELS.get("9router", [])}
                for item in live_9r:
                    mid = item.get("id")
                    if mid and mid not in existing_9r_ids:
                        PROVIDER_MODELS["9router"].append(
                            {
                                "id": mid,
                                "name": f"{mid} (via 9Router)",
                                "category": "9Router Live Catalog",
                                "pricing": "free_tier",
                                "pricing_label": "🟢 9ROUTER",
                            }
                        )
    except Exception:
        pass

    return {"status": "success", "providers": PROVIDER_MODELS}


@router.post("/api/keys/validate")
async def validate_raw_api_key(payload: Dict[str, Any]):
    """Test ping connection for unsaved raw credentials before saving."""
    provider = payload.get("provider", "gemini")
    api_key = payload.get("api_key", "").strip()
    model = payload.get("model", "").strip()
    base_url = payload.get("base_url", "").strip()

    if not api_key:
        raise HTTPException(
            status_code=400, detail="API Key wajib diisi untuk divalidasi"
        )

    start_t = time.time()
    if provider in [
        "nvidia",
        "nim",
        "openai",
        "groq",
        "openrouter",
        "9router",
        "ollama",
        "deepseek",
        "minimax",
        "moonshot",
        "kimi",
        "qwen",
        "dashscope",
    ]:
        try:
            import httpx

            url = base_url
            if not url:
                if provider in ["nvidia", "nim"]:
                    url = "https://integrate.api.nvidia.com/v1"
                elif provider == "deepseek":
                    url = "https://api.deepseek.com/v1"
                elif provider == "minimax":
                    url = "https://api.minimax.chat/v1"
                elif provider in ["moonshot", "kimi"]:
                    url = "https://api.moonshot.cn/v1"
                elif provider in ["qwen", "dashscope"]:
                    url = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
                elif provider == "openai":
                    url = "https://api.openai.com/v1"
                elif provider == "groq":
                    url = "https://api.groq.com/openai/v1"
                elif provider == "openrouter":
                    url = "https://openrouter.ai/api/v1"
                elif provider == "9router":
                    url = "http://127.0.0.1:20128/v1"
                elif provider == "ollama":
                    url = "http://localhost:11434/v1"

            target_model = model
            if not target_model:
                if provider in ["nvidia", "nim"]:
                    target_model = "nvidia/llama-3.1-nemotron-70b-instruct"
                elif provider == "deepseek":
                    target_model = "deepseek-chat"
                elif provider == "minimax":
                    target_model = "MiniMax-Text-01"
                elif provider in ["moonshot", "kimi"]:
                    target_model = "moonshot-v1-8k"
                elif provider in ["qwen", "dashscope"]:
                    target_model = "qwen-plus"
                elif provider == "groq":
                    target_model = "llama-3.3-70b-versatile"
                elif provider == "openrouter":
                    target_model = "deepseek/deepseek-r1:free"
                elif provider == "9router":
                    target_model = "all"
                else:
                    target_model = "gpt-4o"

            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }
            if provider == "openrouter":
                headers["HTTP-Referer"] = "https://alfa-agent.local"
                headers["X-Title"] = "ALFA Swarm Validator"

            test_payload = {
                "model": target_model,
                "messages": [{"role": "user", "content": "Tes koneksi. Jawab: OK"}],
                "max_tokens": 10,
                "stream": False,
            }
            async with httpx.AsyncClient(timeout=12.0) as client:
                res = await client.post(
                    f"{url.rstrip('/')}/chat/completions",
                    headers=headers,
                    json=test_payload,
                )
                duration_ms = round((time.time() - start_t) * 1000, 1)
                if res.status_code == 200:
                    return {
                        "status": "success",
                        "duration_ms": duration_ms,
                        "message": f"Koneksi {provider.upper()} ({target_model}) Berhasil ({duration_ms}ms)!",
                    }
                elif res.status_code == 404 and provider in ["nvidia", "nim"]:
                    return {
                        "status": "error",
                        "status_code": 404,
                        "duration_ms": duration_ms,
                        "message": f"Model '{target_model}' memerlukan izin khusus enterprise di NVIDIA NIM. Coba pilih model aktif 'nvidia/llama-3.1-nemotron-70b-instruct' atau 'meta/llama-3.3-70b-instruct' yang 100% aktif untuk akun Free NIM!",
                    }
                elif res.status_code == 401:
                    return {
                        "status": "error",
                        "status_code": 401,
                        "duration_ms": duration_ms,
                        "message": f"API Key {provider.upper()} tidak valid atau tidak memiliki izin akses (HTTP 401 Unauthorized).",
                    }
                else:
                    return {
                        "status": "error",
                        "status_code": res.status_code,
                        "duration_ms": duration_ms,
                        "message": f"HTTP {res.status_code}: {res.text[:200]}",
                    }
        except Exception as e:
            return {"status": "error", "message": f"Error: {str(e)}"}
    else:
        try:
            from google import genai
            from google.genai import types

            target_model = model or "gemini-3.6-flash"
            client = genai.Client(api_key=api_key)
            await client.aio.models.generate_content(
                model=target_model,
                contents="Tes koneksi",
                config=types.GenerateContentConfig(max_output_tokens=10),
            )
            duration_ms = round((time.time() - start_t) * 1000, 1)
            return {
                "status": "success",
                "duration_ms": duration_ms,
                "message": f"Koneksi GEMINI ({target_model}) Berhasil ({duration_ms}ms)!",
            }
        except Exception as e:
            return {"status": "error", "message": f"Error: {str(e)}"}


# ==================== ANTIGRAVITY OAUTH SUITE ====================


@router.post("/api/antigravity/login/start")
async def antigravity_login_start(payload: Dict[str, Any]):
    """Mulai sesi login Google utk akun Antigravity baru."""
    import antigravity_login as agy_oauth

    name = payload.get("name", "").strip().lower()
    if not name:
        raise HTTPException(status_code=400, detail="nama wajib diisi")
    res = agy_oauth.start_login(name)
    return res


@router.get("/api/antigravity/login/status")
async def antigravity_login_status(name: str = ""):
    import antigravity_login as agy_oauth

    return agy_oauth.login_status(name)


@router.get("/api/antigravity/accounts")
async def antigravity_accounts():
    import antigravity_login as agy_oauth

    return {"status": "success", "accounts": agy_oauth.list_accounts()}


@router.post("/api/antigravity/logout")
async def antigravity_logout_endpoint(payload: Dict[str, Any]):
    import antigravity_login as agy_oauth

    return agy_oauth.remove_account(payload.get("name", ""))


# ==================== OBSERVABILITY & CHECKPOINTS ====================


@router.get("/api/traces")
async def get_traces_endpoint(limit: int = 50):
    """Ambil riwayat trace observability terbaru."""
    try:
        import tracing

        traces = tracing.get_recent_traces(n=min(200, max(1, limit)))
        return {"status": "success", "total": len(traces), "traces": traces}
    except Exception as e:
        return {"status": "error", "message": f"Error fetching traces: {e}"}


@router.get("/api/traces/{trace_id}")
async def get_trace_detail_endpoint(trace_id: str):
    """Ambil detail span dari satu trace ID tertentu."""
    try:
        import tracing

        spans = tracing.get_trace_by_id(trace_id)
        return {"status": "success", "trace_id": trace_id, "spans": spans}
    except Exception as e:
        return {"status": "error", "message": f"Error fetching trace detail: {e}"}


@router.get("/api/checkpoints")
async def get_checkpoints_endpoint():
    """Ambil daftar checkpoint swarm yang dapat di-resume."""
    try:
        from alfa.swarm.checkpoint import SwarmCheckpoint

        resumable = SwarmCheckpoint.list_resumable()
        return {"status": "success", "total": len(resumable), "checkpoints": resumable}
    except Exception as e:
        return {"status": "error", "message": f"Error listing checkpoints: {e}"}


@router.post("/api/checkpoints/{session_id}/resume")
async def resume_checkpoint_endpoint(session_id: str):
    """Lanjutkan sesi swarm dari checkpoint."""
    try:
        from alfa.swarm import engine as swarm_engine

        res = await swarm_engine.resume_swarm_session(session_id)
        return res
    except Exception as e:
        return {"status": "error", "message": f"Error resuming session: {e}"}
