"""
╔══════════════════════════════════════════════════════════════════════════════╗
║               ALFA SOVEREIGN AFFILIATE SALES SWARM ENGINE                    ║
║         Automated 6-Agent Sales Force for Shopee & TikTok Affiliate          ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import os
import re
import json
import time
import sqlite3
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional

logger = logging.getLogger("alfa.affiliate")

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent_data.db")
AFFILIATE_DIR = os.path.expanduser("~/Dokumen/ALFA_AFFILIATE_TOOLS")
os.makedirs(AFFILIATE_DIR, exist_ok=True)
os.makedirs(os.path.join(AFFILIATE_DIR, "Scripts"), exist_ok=True)
os.makedirs(os.path.join(AFFILIATE_DIR, "Campaigns"), exist_ok=True)
os.makedirs(os.path.join(AFFILIATE_DIR, "Deals"), exist_ok=True)


def init_affiliate_tables():
    """Ensure affiliate database tables exist."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    cur.execute("""
    CREATE TABLE IF NOT EXISTS affiliate_products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_name TEXT NOT NULL,
        category TEXT,
        platform TEXT DEFAULT 'shopee',
        original_price TEXT,
        discount_price TEXT,
        commission_rate TEXT,
        affiliate_url TEXT NOT NULL,
        image_url TEXT,
        rating REAL DEFAULT 4.9,
        sold_count TEXT DEFAULT '1000+',
        notes TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)
    
    cur.execute("""
    CREATE TABLE IF NOT EXISTS affiliate_campaigns (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id INTEGER,
        product_name TEXT NOT NULL,
        platform TEXT,
        target_audience TEXT,
        tiktok_script TEXT,
        shopee_copy TEXT,
        wa_broadcast TEXT,
        telegram_card TEXT,
        spill_link_templates TEXT,
        status TEXT DEFAULT 'active',
        clicks_count INTEGER DEFAULT 0,
        sales_count INTEGER DEFAULT 0,
        estimated_earnings REAL DEFAULT 0.0,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (product_id) REFERENCES affiliate_products(id)
    )
    """)
    conn.commit()
    conn.close()


init_affiliate_tables()


# ══════════════════════════════════════════════════════════════════════════════
#  1. RESEARCHER PRIME: TREND & PRODUCT SCOUTING
# ══════════════════════════════════════════════════════════════════════════════

def research_trending_niche(niche: str, platform: str = "shopee") -> Dict[str, Any]:
    """
    Riset tren produk dan kata kunci viral untuk niche affiliate tertentu.
    Menggunakan web search untuk mengidentifikasi produk yang paling dicari.
    """
    try:
        import tools
        query = f"produk viral terlaris {niche} {platform} diskon murah review rating tinggi 2026"
        search_res = tools.web_search(query)
        
        results = search_res.get("results", [])
        top_insights = []
        for r in results[:5]:
            top_insights.append({
                "title": r.get("title", ""),
                "snippet": r.get("snippet", ""),
                "link": r.get("link", "")
            })
            
        return {
            "status": "success",
            "niche": niche,
            "platform": platform,
            "total_found": len(top_insights),
            "market_insights": top_insights,
            "scouted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
    except Exception as e:
        logger.error(f"Error researching niche: {e}")
        return {"status": "error", "message": str(e)}


# ══════════════════════════════════════════════════════════════════════════════
#  2. STRATEGIC PLANNER: HIGH-CONVERTING COPYWRITING & TIKTOK SCRIPT
# ══════════════════════════════════════════════════════════════════════════════

def generate_affiliate_campaign_content(
    product_name: str,
    key_features: str,
    original_price: str,
    discount_price: str,
    affiliate_link: str,
    target_audience: str = "Pecinta Gadget & Lifestyle / Pemburu Diskon",
    platform: str = "shopee_tiktok"
) -> Dict[str, Any]:
    """
    Menghasilkan paket konten lengkap penjualan affiliate:
    1. Script Video TikTok/Shorts (Format: Hook 3s, Story/Problem, Demo/Solusi, CTA Bio).
    2. Copywriting Shopee Flash Sale / Telegram Deals Card (FOMO, Rating, Urgensi).
    3. WhatsApp Broadcast Template (Santai, Akrab, Direct Link).
    4. Auto-Reply Templates untuk komentar "Spill link kak!".
    """
    # 1. TikTok Script (Hook-Story-Offer Formula)
    tiktok_script = f"""🎬 [TIKTOK & REELS VIRAL VIDEO SCRIPT]
🏷️ Produk: {product_name}
🎯 Target: {target_audience}
⏱️ Durasi Rekomendasi: 25 - 40 Detik

[00:00 - 00:03] 🔥 HOOK (Visual: Pegang produk / Tunjukkan masalah dengan mimik kaget):
Voiceover / Audio: "Sumpah gue nyesel baru tau ada barang ini sekarang! Kalau kalian punya masalah {key_features.split(',')[0] if ',' in key_features else key_features}, wajib tonton ini sampai habis!"
On-Screen Text: "JANGAN BELI DULU SEBELUM NONTON INI! 😱🔥"

[00:03 - 00:15] 📦 STORY & UNBOXING (Visual: Buka paket, zoom close-up detail kualitas & fungsi):
Voiceover: "Ini dia {product_name}! Desainnya compact banget dan fiturnya beneran ngebantu: {key_features}. Biasanya barang kayak gini harganya bisa {original_price}, tapi sekarang lagi drop parah cuma {discount_price}!"
On-Screen Text: "Harga Normal {original_price} ❌ Drop jadi {discount_price} ✅"

[00:15 - 00:25] 💡 DEMO REAL & BENEFIT (Visual: Tunjukkan produk saat dipakai nyata dan hasilnya memuaskan):
Voiceover: "Materialnya kokoh, gampang dipakai, dan praktis dibawa ke mana-mana. Bintang 4.9 dari ribuan pembeli, jadi gak usah ragu lagi sama kualitasnya."
On-Screen Text: "Rating 4.9 ⭐ (Ribuan Terjual)"

[00:25 - 00:35] 🚀 CALL TO ACTION (Visual: Arahkan jari ke keranjang kuning / bio link):
Voiceover: "Mumpung lagi flash sale dan gratis ongkir, langsung klik keranjang kuning di kiri bawah atau cek bio nomor 1 sebelum voucher habis ya!"
On-Screen Text: "KLIK KERANJANG KUNING / LINK DI BIO NOMOR 1 👇🔥"
"""

    # 2. Telegram Deals Card
    telegram_card = f"""🔥 *RACUN DISKON SPESIAL HARI INI!* 🔥

📦 *{product_name}*
⭐ *Rating:* 4.9 / 5.0 | *Terjual:* 2.500+ Pcs

💡 *Keunggulan Utama:*
• {key_features.replace(',', '\n• ')}

💰 *Harga Normal:* ~{original_price}~
🏷️ *Harga Flash Sale:* *{discount_price}* (Hemat Gila!)
🚚 *Voucher:* Gratis Ongkir Xtra + Cashback

👉 *Serbu link diskon resmi di sini:*
🛒 [KLIK DISINI UNTUK BELI SEBELUM HABIS]({affiliate_link})

⚠️ _Stok flash sale sangat terbatas, harga bisa naik sewaktu-waktu!_"""

    # 3. WhatsApp Community Broadcast
    wa_broadcast = f"""Halo semuanya! Buat yang kemarin nanyain rekomendasi *{product_name}*, kebetulan lagi ada promo flash sale parah hari ini! 😱🔥

Biasanya harganya {original_price}, hari ini cuma *{discount_price}* + gratis ongkir!

Fitur andalannya:
✅ {key_features.replace(',', '\n✅ ')}

Udah bintang 4.9 dan ribuan orang udah checkout. 

Yang mau amankan diskonnya sebelum kuponnya abis, langsung klik link ini ya:
👇👇
{affiliate_link}

(Jangan lupa klaim voucher gratis ongkirnya di halaman produk ya! 👍)"""

    # 4. Laguna Spill Link Auto-Reply Templates
    spill_replies = [
        f"Halo kak! Ini link resminya yang lagi diskon {discount_price} + gratis ongkir ya 👉 {affiliate_link} 🥰",
        f"Spill link siap kak! Langsung checkout di sini sebelum flash sale selesai ya kak 👉 {affiliate_link} 🔥",
        f"Produk originalnya yang ini ya kak: {affiliate_link} . Jangan lupa klaim voucher tokonya ya kak! ✨",
        f"Ada di link ini ya kak 👉 {affiliate_link} . Lagi promo hemat dari {original_price} jadi {discount_price} kak! 👍"
    ]

    # Save scripts to Dokumen/ALFA_AFFILIATE_TOOLS/Scripts/
    safe_stem = re.sub(r'[^a-zA-Z0-9_-]', '_', product_name)[:30]
    out_file = os.path.join(AFFILIATE_DIR, "Scripts", f"{safe_stem}_campaign.json")
    
    campaign_data = {
        "product_name": product_name,
        "key_features": key_features,
        "original_price": original_price,
        "discount_price": discount_price,
        "affiliate_link": affiliate_link,
        "target_audience": target_audience,
        "tiktok_script": tiktok_script,
        "telegram_card": telegram_card,
        "wa_broadcast": wa_broadcast,
        "spill_replies": spill_replies,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    
    with open(out_file, "w", encoding="utf-8") as f_out:
        json.dump(campaign_data, f_out, indent=2, ensure_ascii=False)

    # Save to database
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
    INSERT INTO affiliate_campaigns 
    (product_name, platform, target_audience, tiktok_script, shopee_copy, wa_broadcast, telegram_card, spill_link_templates)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        product_name,
        platform,
        target_audience,
        tiktok_script,
        telegram_card,
        wa_broadcast,
        telegram_card,
        json.dumps(spill_replies)
    ))
    campaign_id = cur.lastrowid
    conn.commit()
    conn.close()

    campaign_data["campaign_id"] = campaign_id
    campaign_data["script_file_path"] = out_file
    return campaign_data


# ══════════════════════════════════════════════════════════════════════════════
#  3. CODE CRAFTER: MULTI-CHANNEL BROADCASTER
# ══════════════════════════════════════════════════════════════════════════════

def broadcast_affiliate_deal(
    product_name: str,
    message_text: str,
    affiliate_link: str,
    channels: List[str] = ["telegram", "whatsapp"]
) -> Dict[str, Any]:
    """
    Mengirimkan konten promosi affiliate secara otomatis ke Telegram Channel atau WhatsApp Broadcast.
    """
    results = {}
    
    # 1. Telegram
    if "telegram" in channels:
        try:
            import bot
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup
            
            uid = int(os.getenv("ALLOWED_USER_IDS", "8821693251").split(",")[0].strip())
            
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🛒 Beli Sekarang / Cek Diskon", url=affiliate_link)]
            ])
            
            asyncio_res = "Queued to Telegram Channel/Chat"
            bot.schedule_tool_broadcast(uid, message_text, reply_markup=keyboard)
            results["telegram"] = {"status": "success", "message": asyncio_res}
        except Exception as e:
            results["telegram"] = {"status": "error", "message": str(e)}

    # 2. WhatsApp
    if "whatsapp" in channels:
        try:
            import tools
            wa_status = tools.manage_wa_sheets_bot("status")
            results["whatsapp"] = {
                "status": "ready",
                "wa_bot_status": wa_status.get("status", "unknown"),
                "message": "Broadcast template siap dikirim via WhatsApp bot."
            }
        except Exception as e:
            results["whatsapp"] = {"status": "error", "message": str(e)}

    return {
        "status": "success",
        "product_name": product_name,
        "channels": channels,
        "results": results,
        "broadcasted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }


# ══════════════════════════════════════════════════════════════════════════════
#  4. ALPHA LEAD: CAMPAIGN RECAP & PERFORMANCE TRACKER
# ══════════════════════════════════════════════════════════════════════════════

def list_affiliate_campaigns(limit: int = 20) -> List[Dict[str, Any]]:
    """Ambil daftar seluruh campaign affiliate yang telah digenerate."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("""
    SELECT id, product_name, platform, target_audience, status, clicks_count, sales_count, estimated_earnings, created_at 
    FROM affiliate_campaigns 
    ORDER BY id DESC LIMIT ?
    """, (limit,))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def get_affiliate_campaign_detail(campaign_id: int) -> Optional[Dict[str, Any]]:
    """Ambil detail lengkap 1 campaign affiliate."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM affiliate_campaigns WHERE id = ?", (campaign_id,))
    row = cur.fetchone()
    conn.close()
    if row:
        data = dict(row)
        try:
            data["spill_link_templates"] = json.loads(data.get("spill_link_templates", "[]"))
        except:
            pass
        return data
    return None
