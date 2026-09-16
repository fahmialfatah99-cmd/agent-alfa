import asyncio
import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException

from alfa.core import database
from alfa.dashboard.common import logger, safe_int

router = APIRouter()

def _parse_ai_sections(text: str) -> Dict[str, str]:
    """Pecah output AI bertanda ===NAMA_SEKSI=== menjadi dict."""
    out: Dict[str, str] = {}
    parts = re.split(r"={3,}\s*([A-Za-z_]+)\s*={3,}", text or "")
    for i in range(1, len(parts) - 1, 2):
        out[parts[i].strip().lower()] = parts[i + 1].strip()
    return out


# --- Affiliate Sales Swarm API Endpoints ---

@router.get("/api/affiliate/campaigns")
async def get_affiliate_campaigns(limit: int = 20):
    """Get list of active affiliate campaigns and scripts."""
    import affiliate_engine
    campaigns = affiliate_engine.list_affiliate_campaigns(limit=limit)
    return {
        "status": "success",
        "total": len(campaigns),
        "campaigns": campaigns
    }


@router.get("/api/affiliate/campaigns/{campaign_id}")
async def get_affiliate_campaign_detail(campaign_id: int):
    """Get full details of a specific affiliate campaign."""
    import affiliate_engine
    data = affiliate_engine.get_affiliate_campaign_detail(campaign_id)
    if not data:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return {"status": "success", "campaign": data}


@router.post("/api/affiliate/generate")
async def generate_affiliate_campaign(payload: Dict[str, Any]):
    """Generate viral affiliate campaign: template engine + personalisasi AI oleh agen Content Alchemist."""
    import affiliate_engine
    product_name = payload.get("product_name", "").strip()
    key_features = payload.get("key_features", "").strip()
    original_price = payload.get("original_price", "Rp 100.000").strip()
    discount_price = payload.get("discount_price", "Rp 49.000").strip()
    affiliate_link = payload.get("affiliate_link", "https://shopee.co.id").strip()
    target_audience = payload.get("target_audience", "Pemburu Diskon & Gadget").strip()
    platform = payload.get("platform", "shopee_tiktok").strip()

    if not product_name or not affiliate_link:
        raise HTTPException(status_code=400, detail="product_name and affiliate_link are required")

    res = affiliate_engine.generate_affiliate_campaign_content(
        product_name=product_name,
        key_features=key_features,
        original_price=original_price,
        discount_price=discount_price,
        affiliate_link=affiliate_link,
        target_audience=target_audience,
        platform=platform
    )

    res["ai_enriched"] = False
    try:
        from alfa.swarm import engine as swarm_engine
        alchemist = next(
            (a for a in database.list_custom_agents_sync()
             if a.get("name") == "Content Alchemist" and a.get("is_enabled", 1)),
            None)
        if alchemist:
            prompt = (
                f"Personalisasi konten jualan affiliate berikut agar UNIK dan berbasis data.\n\n"
                f"DATA PRODUK:\n"
                f"- Nama: {product_name}\n- Fitur: {key_features}\n"
                f"- Harga normal: {original_price} -> Flash sale: {discount_price}\n"
                f"- Target: {target_audience} | Platform: {platform}\n"
                f"- Link WAJIB dipertahankan di CTA: {affiliate_link}\n\n"
                f"DRAF TEMPLATE (bahan mentah — boleh rombak struktur & hook):\n"
                f"[SCRIPT DASAR]\n{res['tiktok_script'][:1500]}\n\n"
                f"ATURAN:\n"
                f"1. Hook 3 detik yang spesifik produk (sebut angka/masalah nyata dari fitur).\n"
                f"2. Script 25-40 detik, gaya anak TikTok Indonesia, ada timestamp.\n"
                f"3. Telegram card & WA broadcast dengan urgensi FOMO yang tidak klise.\n\n"
                f"KELUARAN WAJIB PERSIS FORMAT INI (tanpa teks lain):\n"
                f"===TIKTOK_SCRIPT===\n<script lengkap>\n"
                f"===TELEGRAM_CARD===\n<kartu diskon>\n"
                f"===WA_BROADCAST===\n<pesan broadcast>"
            )
            enriched = await asyncio.wait_for(
                swarm_engine.generate_agent_response(
                    agent=alchemist, prompt=prompt,
                    system_instruction=alchemist.get("system_instruction")
                    or "Kamu adalah copywriter viral Indonesia.",
                    timeout_s=110.0),
                timeout=120.0)
            sections = _parse_ai_sections(enriched)
            replaced = 0
            for key_src, key_out in (("tiktok_script", "tiktok_script"),
                                     ("telegram_card", "telegram_card"),
                                     ("wa_broadcast", "wa_broadcast")):
                val = sections.get(key_src)
                if val and len(val) > 80:
                    res[f"{key_out}_template"] = res[key_out]
                    res[key_out] = val
                    replaced += 1
            if replaced:
                res["ai_enriched"] = True
    except Exception as aff_ai_err:
        import traceback as _tb
        logger.warning(
            f"Enrichment affiliate AI gagal — pakai template: "
            f"{type(aff_ai_err).__name__}: {aff_ai_err}\n{_tb.format_exc()[-600:]}")

    return {"status": "success", "result": res}


@router.post("/api/affiliate/broadcast")
async def broadcast_affiliate_campaign(payload: Dict[str, Any]):
    """Broadcast an affiliate deal to Telegram / WhatsApp."""
    import affiliate_engine
    product_name = payload.get("product_name", "")
    message_text = payload.get("message_text", "")
    affiliate_link = payload.get("affiliate_link", "")
    channels = payload.get("channels", ["telegram", "whatsapp"])

    res = affiliate_engine.broadcast_affiliate_deal(
        product_name=product_name,
        message_text=message_text,
        affiliate_link=affiliate_link,
        channels=channels
    )
    return res


@router.post("/api/video/generate")
async def generate_promo_video(payload: Dict[str, Any]):
    """Generate 9:16 vertical promo video from images and script."""
    import video_generator
    image_paths = payload.get("image_paths", [])
    product_name = payload.get("product_name", "Produk Pilihan").strip()
    voiceover_text = payload.get("voiceover_text", "").strip()
    orig_price = payload.get("orig_price", "Rp 149.000").strip()
    disc_price = payload.get("disc_price", "Rp 49.900").strip()
    voice = payload.get("voice", "id-ID-GadisNeural")
    theme = payload.get("theme", "viral_tiktok")
    motion_style = payload.get("motion_style", "zoom_in")
    call_to_action = payload.get("call_to_action", "KLIK KERANJANG KUNING / BIO SEBELUM HABIS")
    visual_prompt = payload.get("visual_prompt", "")
    engine = payload.get("engine", "local_pro")
    api_key = payload.get("api_key", None)
    output_filename = payload.get("output_filename", None)
    badge_text = payload.get("badge_text", "GRATIS ONGKIR")

    if not voiceover_text:
        voiceover_text = f"Promo spesial {product_name}, harga normal {orig_price} sekarang lagi drop cuma {disc_price}! Jangan sampai kehabisan, langsung klik link sekarang!"

    if engine in ("kling", "luma", "runway", "fal_ai", "replicate"):
        return {"status": "error",
                "message": f"Engine '{engine}' belum terimplementasi. Gunakan 'local_pro' atau 'google_veo*'."}
    if (engine in video_generator.VEO_MODEL_MAP
            or engine in getattr(video_generator, "OMNI_MODEL_MAP", {})) \
            and not (api_key or "").strip():
        try:
            with database.get_sync_db() as conn:
                r = conn.execute(
                    "SELECT api_key FROM api_keys WHERE provider = 'gemini' ORDER BY id LIMIT 1")
                row = r.fetchone()
            if row and row["api_key"]:
                api_key = database.decrypt_key(row["api_key"])
        except Exception:
            pass
        if not (api_key or "").strip():
            return {"status": "error",
                    "message": "Google Veo butuh Gemini API Key. Isi manual atau tambahkan kunci 'gemini' di Vault."}

    def _render():
        return video_generator.generate_video_from_images(
            image_paths=image_paths,
            product_name=product_name,
            voiceover_text=voiceover_text,
            orig_price=orig_price,
            disc_price=disc_price,
            voice=voice,
            theme=theme,
            motion_style=motion_style,
            badge_text=badge_text,
            call_to_action=call_to_action,
            visual_prompt=visual_prompt,
            engine=engine,
            api_key=api_key,
            output_filename=output_filename
        )

    res = await asyncio.to_thread(_render)
    return res


