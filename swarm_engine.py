"""
Autonomous Multi-Agent Swarm & Meeting Engine for ALFA Ecosystem.
Enables round-table AI meetings, inter-agent dialogue, debate, consensus building,
and multi-provider API key orchestration (Gemini, OpenAI, Groq, OpenRouter, Anthropic, Ollama).
"""

import os
import json
import logging
import asyncio
from datetime import datetime
from typing import List, Dict, Any, Optional

import database
from google import genai
from google.genai import types

logger = logging.getLogger(__name__)


def get_agent_api_client(agent: Dict[str, Any]) -> tuple[str, str, str, Optional[str]]:
    """
    Resolve (provider, api_key, model, base_url) for a specific agent.
    Falls back to active key in database or environment.
    """
    provider = (agent.get("provider") or "gemini").lower()
    model = agent.get("model") or "gemini-2.5-flash"
    api_key = ""
    base_url = ""

    # 1. If agent has specific linked API key in database
    if agent.get("api_key_id"):
        with database.get_sync_db() as conn:
            row = conn.execute("SELECT provider, api_key, default_model, base_url FROM api_keys WHERE id = ?", (agent["api_key_id"],)).fetchone()
            if row:
                provider = row["provider"]
                api_key = row["api_key"]
                base_url = row["base_url"] or ""
                if not agent.get("model"):
                    model = row["default_model"]

    # 2. If no key yet, find active key for this provider
    if not api_key:
        active_key = database.get_active_api_key_sync(provider)
        if active_key:
            api_key = active_key["api_key"]
            base_url = active_key.get("base_url") or ""

    # 3. Environment variable fallback
    if not api_key:
        if provider == "gemini":
            api_key = os.getenv("GEMINI_API_KEY", "")
        elif provider == "openai":
            api_key = os.getenv("OPENAI_API_KEY", "")
        elif provider == "groq":
            api_key = os.getenv("GROQ_API_KEY", "")
        elif provider in ["nvidia", "nim"]:
            api_key = os.getenv("NVIDIA_API_KEY", "")

    return provider, api_key, model, base_url


async def generate_agent_response(agent: Dict[str, Any], prompt: str, system_instruction: str) -> str:
    """Generate response for a specific agent using its configured provider and key."""
    provider, api_key, model, base_url = get_agent_api_client(agent)

    if provider == "gemini":
        candidate_models = [model, "gemini-3.5-flash-lite", "gemini-3.6-flash", "gemini-flash-latest", "gemini-3-flash-preview"]
        # Remove duplicates while preserving order
        unique_models = []
        for m in candidate_models:
            if m and m not in unique_models:
                unique_models.append(m)

        client = genai.Client(api_key=api_key or os.getenv("GEMINI_API_KEY"))
        last_err = None
        for m in unique_models:
            try:
                response = await client.aio.models.generate_content(
                    model=m,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=system_instruction,
                        temperature=0.7,
                    )
                )
                if response and response.text:
                    return response.text.strip()
            except Exception as e:
                last_err = e
                logger.warning(f"Model '{m}' failed for agent '{agent.get('name')}': {e}. Trying next fallback...")

        logger.error(f"All Gemini models failed for agent '{agent.get('name')}': {last_err}")
        return f"[Error: Gagal memanggil Gemini API: {str(last_err)}]"

    elif provider in ["openai", "groq", "openrouter", "9router", "ollama", "nvidia", "nim", "deepseek", "minimax", "moonshot", "kimi", "qwen", "dashscope"]:
        try:
            import httpx
            # Determine endpoint
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
                    url = "http://localhost:20128/v1"
                elif provider == "ollama":
                    url = "http://localhost:11434/v1"

            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }
            if provider == "openrouter":
                headers["HTTP-Referer"] = "https://alfa-agent.local"
                headers["X-Title"] = "ALFA Sovereign Agent"

            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_instruction},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.7
            }

            async with httpx.AsyncClient(timeout=30.0) as http_client:
                res = await http_client.post(f"{url.rstrip('/')}/chat/completions", headers=headers, json=payload)
                if res.status_code == 200:
                    data = res.json()
                    return data["choices"][0]["message"]["content"].strip()
                else:
                    return f"[Error {res.status_code}: {res.text}]"
        except Exception as e:
            logger.error(f"Error in {provider} agent '{agent.get('name')}': {e}")
            return f"[Error: {str(e)}]"

    else:
        # Fallback to Gemini
        return await generate_agent_response({**agent, "provider": "gemini"}, prompt, system_instruction)


async def conduct_multi_agent_meeting(topic: str, participant_names: Optional[List[str]] = None, rounds: int = 2) -> Dict[str, Any]:
    """
    Conduct an autonomous round-table meeting between AI agents.
    Agents discuss, debate, critique, and synthesize a consensus action plan.
    """
    all_agents = database.list_custom_agents_sync()
    if not all_agents:
        database.init_db_sync()
        all_agents = database.list_custom_agents_sync()

    # Filter selected participants or pick first 4
    if participant_names:
        participants = [a for a in all_agents if a["name"] in participant_names and a.get("is_enabled", 1)]
    else:
        participants = [a for a in all_agents if a.get("is_enabled", 1)][:4]

    if not participants:
        participants = all_agents[:3]

    dialogue_transcript = []
    meeting_title = f"Rapat Tim AI: {topic[:60]}"
    
    # Context accumulator
    history_summary = []

    logger.info(f"🏛️ Starting AI Meeting on topic: '{topic}' with {len(participants)} agents for {rounds} rounds.")

    for r in range(1, rounds + 1):
        for agent in participants:
            context_text = "\n".join(history_summary) if history_summary else "(Rapat baru saja dibuka)"
            
            prompt = (
                f"=== TOPIK AGENDA RAPAT ===\n"
                f"{topic}\n\n"
                f"=== JALANNYA DISKUSI SEBELUMNYA (PUTARAN {r}) ===\n"
                f"{context_text}\n\n"
                f"=== PERAN KAMU ===\n"
                f"Nama: {agent['name']}\n"
                f"Role: {agent['role']}\n"
                f"Karakter: {agent['persona']}\n\n"
                f"Instruksi:\n"
                f"1. Berikan tanggapan, gagasan kritis, atau usulan solusi sesuai bidang keahlianmu.\n"
                f"2. Bersikaplah seperti rekan kerja profesional di ruang rapat: tanggapi poin peserta lain (jika ada), beri masukan teknis atau kritisi risiko.\n"
                f"3. Sampaikan secara ringkas, padat, lugas (2-3 paragraf) dalam bahasa Indonesia santai tapi profesional."
            )

            response_text = await generate_agent_response(
                agent=agent,
                prompt=prompt,
                system_instruction=agent.get("system_instruction", "Kamu adalah anggota tim AI otonom profesional.")
            )

            entry = {
                "round": r,
                "agent_name": agent["name"],
                "role": agent["role"],
                "avatar_emoji": agent.get("avatar_emoji", "🤖"),
                "color_theme": agent.get("color_theme", "cyan"),
                "message": response_text,
                "timestamp": datetime.now().strftime("%H:%M:%S")
            }
            dialogue_transcript.append(entry)
            history_summary.append(f"[{agent['name']} - {agent['role']}]:\n{response_text}\n")

    # Final Consensus & Action Plan synthesis by Lead Agent
    lead_agent = participants[0]
    consensus_prompt = (
        f"=== TOPIK RAPAT ===\n{topic}\n\n"
        f"=== TRANSKRIP LENGKAP RAPAT TIM ===\n" + "\n".join(history_summary) + "\n\n"
        f"Sebagai ketua rapat ({lead_agent['name']}), buatlah:\n"
        f"1. KONSENSUS & KEPUTUSAN UTAMA RAPAT (Rangkuman kesepakatan seluruh anggota tim).\n"
        f"2. ACTION PLAN / LANGKAH EKSEKUSI (Daftar tugas konkret terstruktur dengan penanggung jawab agent).\n"
        f"Format dalam Markdown yang rapi dan profesional."
    )
    
    consensus_text = await generate_agent_response(
        agent=lead_agent,
        prompt=consensus_prompt,
        system_instruction="Kamu adalah Project Director yang memimpin perumusan keputusan akhir rapat."
    )

    action_plan_text = ""
    if "ACTION PLAN" in consensus_text.upper():
        parts = consensus_text.split("ACTION PLAN", 1)
        consensus_text_clean = parts[0].strip()
        action_plan_text = "ACTION PLAN" + parts[1]
    else:
        consensus_text_clean = consensus_text

    # Save to SQLite database
    saved = database.create_agent_meeting_sync(
        title=meeting_title,
        topic=topic,
        participants=[a["name"] for a in participants],
        dialogue_transcript=dialogue_transcript,
        consensus=consensus_text_clean,
        action_plan=action_plan_text,
        status="completed"
    )

    return {
        "status": "success",
        "meeting_id": saved.get("id"),
        "title": meeting_title,
        "topic": topic,
        "participants": [a["name"] for a in participants],
        "dialogue_transcript": dialogue_transcript,
        "consensus": consensus_text_clean,
        "action_plan": action_plan_text
    }
