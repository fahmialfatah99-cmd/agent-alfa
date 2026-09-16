"""Marketplace searching and affiliate marketing campaign tools."""

import json
import logging
import os
from typing import Any, Dict, List, Optional

from alfa.tools.registry import register_tool

logger = logging.getLogger("AgentTools.Web.Affiliate")

def marketplace_search_products(query: str, platform: str = "shopee", max_items: int = 15) -> Dict[str, Any]:
    """
    Cari dan scrape katalog produk real dari marketplace (Shopee, TikTok Shop, Tokopedia) berdasarkan kata kunci pencarian.
    
    Args:
        query: Kata kunci pencarian produk (misal: 'powerbank mini fast charge', 'lampu tidur estetik').
        platform: Marketplace target ('shopee', 'tiktok', 'tokopedia', 'lazada').
        max_items: Jumlah maksimal produk yang diambil (default: 15).
    """
    try:
        from alfa.scrapers import fast as fast_scraper
        return fast_scraper.search_and_scrape_marketplace(
            query=query,
            platform=platform,
            max_items=max_items
        )
    except Exception as e:
        logger.error(f"Error in marketplace_search_products: {e}")
        return {"status": "error", "message": str(e)}


@register_tool(category="web")
def affiliate_hunt_trending_products(niche: str = "gadget unik murah", platform: str = "shopee") -> Dict[str, Any]:
    """
    Riset tren produk dan kata kunci viral untuk niche affiliate Shopee / TikTok Shop (Dikelola oleh Researcher Prime).
    
    Args:
        niche: Kategori atau kata kunci produk (misal: 'gadget unik murah', 'peralatan dapur estetik', 'fashion pria korea').
        platform: Platform target ('shopee', 'tiktok', 'lazada').
    """
    try:
        import affiliate_engine
        return affiliate_engine.research_trending_niche(niche=niche, platform=platform)
    except Exception as e:
        logger.error(f"Error in affiliate_hunt_trending_products: {e}")
        return {"status": "error", "message": str(e)}


@register_tool(category="web")
def affiliate_generate_viral_content(
    product_name: str,
    key_features: str,
    original_price: str,
    discount_price: str,
    affiliate_link: str,
    target_audience: str = "Pecinta Gadget & Lifestyle / Pemburu Diskon",
    platform: str = "shopee_tiktok"
) -> Dict[str, Any]:
    """
    Hasilkan paket copywriting viral lengkap: Script Video TikTok (Hook 3s, Story, CTA), Telegram Deals Card, WhatsApp Broadcast, dan Auto-Reply 'Spill Link' (Dikelola oleh Strategic Planner).
    
    Args:
        product_name: Nama produk (misal: 'Mini Powerbank Kapsul Fast Charging 5000mAh').
        key_features: Keunggulan dan spesifikasi utama produk dipisah koma.
        original_price: Harga sebelum diskon (misal: 'Rp 150.000').
        discount_price: Harga flash sale/diskon (misal: 'Rp 49.000').
        affiliate_link: Link affiliate Shopee / TikTok Shop kamu.
        target_audience: Segmentasi target pembeli.
        platform: Platform target konten.
    """
    try:
        import affiliate_engine
        return affiliate_engine.generate_affiliate_campaign_content(
            product_name=product_name,
            key_features=key_features,
            original_price=original_price,
            discount_price=discount_price,
            affiliate_link=affiliate_link,
            target_audience=target_audience,
            platform=platform
        )
    except Exception as e:
        logger.error(f"Error in affiliate_generate_viral_content: {e}")
        return {"status": "error", "message": str(e)}


@register_tool(category="web")
def affiliate_broadcast_deal(
    product_name: str,
    message_text: str,
    affiliate_link: str,
    channels: List[str] = None
) -> Dict[str, Any]:
    """
    Kirimkan penawaran diskon affiliate secara otomatis ke Telegram Channel atau broadcast WhatsApp (Dikelola oleh Code Crafter).
    
    Args:
        product_name: Nama produk yang dipromosikan.
        message_text: Teks copywriting promosi lengkap.
        affiliate_link: URL link affiliate resmi.
        channels: Daftar channel tujuan (['telegram', 'whatsapp']).
    """
    if channels is None:
        channels = ["telegram", "whatsapp"]
    try:
        import affiliate_engine
        return affiliate_engine.broadcast_affiliate_deal(
            product_name=product_name,
            message_text=message_text,
            affiliate_link=affiliate_link,
            channels=channels
        )
    except Exception as e:
        logger.error(f"Error in affiliate_broadcast_deal: {e}")
        return {"status": "error", "message": str(e)}


@register_tool(category="web")
def affiliate_list_campaigns(limit: int = 15) -> Dict[str, Any]:
    """
    Lihat rekap histori campaign dan script affiliate yang aktif (Dikelola oleh Alpha Lead).
    
    Args:
        limit: Jumlah campaign yang ingin ditampilkan.
    """
    try:
        import affiliate_engine
        campaigns = affiliate_engine.list_affiliate_campaigns(limit=limit)
        return {
            "status": "success",
            "total_campaigns": len(campaigns),
            "campaigns": campaigns
        }
    except Exception as e:
        logger.error(f"Error in affiliate_list_campaigns: {e}")
        return {"status": "error", "message": str(e)}


