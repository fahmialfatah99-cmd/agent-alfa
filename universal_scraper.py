"""
╔══════════════════════════════════════════════════════════════════════════════╗
║               ALFA UNIVERSAL HIGH-VOLUME PRO SCRAPER ENGINE                  ║
║   Multi-Engine (Camoufox Stealth + Fast TLS + DDGS Multi-Category Deep Crawl)║
║   Supports: Marketplace, Jobs, News, Leads, Property, Custom URLs/Selectors  ║
║   Copyright (c) 2026 Fahmi Alfatah. All Rights Reserved.                     ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import os
import re
import csv
import json
import time
import uuid
import sqlite3
import logging
import asyncio
import urllib.parse
from datetime import datetime
from typing import Dict, Any, List, Optional
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor
from ddgs import DDGS

logger = logging.getLogger("alfa.universal_scraper")

SCRAPER_DATA_DIR = os.path.expanduser("~/Dokumen/ALFA_SCRAPER_DATA")
MASTER_EXPORT_DIR = os.path.join(SCRAPER_DATA_DIR, "Master_Scrapes")
os.makedirs(MASTER_EXPORT_DIR, exist_ok=True)
os.makedirs(os.path.join(MASTER_EXPORT_DIR, "CSV"), exist_ok=True)
os.makedirs(os.path.join(MASTER_EXPORT_DIR, "JSON"), exist_ok=True)

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent_data.db")


def _init_master_scraper_db():
    """Ensure master_scrapes table exists in SQLite database."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS master_scrapes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        batch_id TEXT UNIQUE NOT NULL,
        name TEXT NOT NULL,
        mode TEXT NOT NULL,
        target TEXT NOT NULL,
        total_items INTEGER DEFAULT 0,
        data_json TEXT,
        csv_file TEXT,
        json_file TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    conn.commit()
    conn.close()


_init_master_scraper_db()


PLATFORM_SEARCH_TEMPLATES = {
    "all_marketplace": [
        "site:shopee.co.id {query}",
        "site:tokopedia.com {query}",
        "site:tiktok.com {query} produk",
        "site:lazada.co.id {query}",
        "site:blibli.com {query}",
        "jual {query} diskon promo shopee tokopedia"
    ],
    "shopee": ["site:shopee.co.id {query} diskon", "site:shopee.co.id {query} promo", "site:shopee.co.id produk {query}"],
    "tokopedia": ["site:tokopedia.com {query} diskon", "site:tokopedia.com {query} promo", "site:tokopedia.com find {query}"],
    "tiktok": ["site:tiktok.com {query} shop", "site:tiktok.com {query} produk viral", "site:tiktok.com {query} affiliate"],
    "jobs_career": [
        "site:jobstreet.co.id lowongan {query}",
        "site:id.linkedin.com/jobs {query}",
        "site:glints.com/id/opportunities/jobs {query}",
        "site:karir.com {query}",
        "site:kalibrr.com {query}"
    ],
    "news_media": [
        "site:detik.com {query}",
        "site:kompas.com {query}",
        "site:cnnindonesia.com {query}",
        "site:liputan6.com {query}",
        "site:tribunnews.com {query}",
        "site:cnbcindonesia.com {query}"
    ],
    "property_realestate": [
        "site:rumah123.com {query}",
        "site:rumah.com {query}",
        "site:lamudi.co.id {query}",
        "site:olx.co.id properti {query}"
    ],
    "leads_contacts": [
        "\"{query}\" \"whatsapp\" OR \"wa.me\" OR \"08\" email",
        "\"{query}\" \"hubungi kami\" \"08\" OR \"email\"",
        "\"{query}\" supplier distributor \"08\" OR \"kontak\""
    ],
    "google_general": [
        "{query}",
        "{query} terbaru",
        "{query} rekomendasi terbaik",
        "{query} review lengkap"
    ]
}


def scrape_universal_keyword(
    query: str,
    category: str = "all_marketplace",
    limit: int = 50,
    extract_contacts: bool = True
) -> Dict[str, Any]:
    """
    Executes high-yield multi-query deep search across specialized platforms.
    Paginates and merges results to yield 20 - 500+ rich records.
    """
    start_time = time.time()
    batch_id = f"batch_{int(time.time())}_{uuid.uuid4().hex[:6]}"
    batch_name = f"Scrape_{category}_{re.sub(r'[^a-zA-Z0-9]', '_', query)[:20]}"

    templates = PLATFORM_SEARCH_TEMPLATES.get(category, PLATFORM_SEARCH_TEMPLATES["google_general"])
    
    # Calculate queries needed to fulfill limit
    queries_to_run = [t.format(query=query) for t in templates]

    all_raw_results = []
    seen_urls = set()

    with DDGS(verify=False) as ddgs:
        for q in queries_to_run:
            try:
                sub_results = list(ddgs.text(q, max_results=max(10, limit // len(queries_to_run) + 5)))
                for r in sub_results:
                    url = r.get("href", "").strip()
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        all_raw_results.append({
                            "title": r.get("title", "No Title"),
                            "snippet": r.get("body", ""),
                            "link": url
                        })
                    if len(all_raw_results) >= limit:
                        break
            except Exception as e:
                logger.warning(f"Error querying '{q}': {e}")
            if len(all_raw_results) >= limit:
                break

    # If direct template yielded few results, fallback to broader general search
    if len(all_raw_results) < min(10, limit):
        try:
            with DDGS(verify=False) as ddgs:
                general_results = list(ddgs.text(query, max_results=limit))
                for r in general_results:
                    url = r.get("href", "").strip()
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        all_raw_results.append({
                            "title": r.get("title", "No Title"),
                            "snippet": r.get("body", ""),
                            "link": url
                        })
        except Exception:
            pass

    # Process and enrich each item
    processed_items = []
    for idx, item in enumerate(all_raw_results[:limit], 1):
        title = item.get("title", "No Title").strip()
        snippet = item.get("snippet", "").strip()
        link = item.get("link", "").strip()

        # Clean title from common site suffixes
        clean_title = re.sub(r'\s*[-|]\s*(Shopee Indonesia|Tokopedia|Lazada|Blibli|Jobstreet|Kompas.com|Detikcom|LinkedIn).*$', '', title, flags=re.IGNORECASE)

        # Smart Price Extractor
        price = "N/A"
        price_match = re.search(r'Rp\s?[\d\.,]+(?:rb|jt|ribu|juta)?', snippet, re.IGNORECASE)
        if price_match:
            price = price_match.group(0)
        elif category in ["all_marketplace", "shopee", "tokopedia", "tiktok"]:
            price = "Cek di Halaman"

        # Smart Phone / WhatsApp Extractor
        phone = "N/A"
        phone_match = re.search(r'(?:08|\+628|628)\d{8,12}', snippet)
        if phone_match:
            phone = phone_match.group(0)

        # Smart Email Extractor
        email = "N/A"
        email_match = re.search(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+', snippet)
        if email_match:
            email = email_match.group(0)

        # Platform / Domain inference
        domain = urllib.parse.urlparse(link).netloc.replace("www.", "")

        processed_items.append({
            "no": idx,
            "title": clean_title or title,
            "snippet": snippet,
            "url": link,
            "domain": domain,
            "price": price,
            "phone_wa": phone,
            "email": email,
            "category": category,
            "scraped_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })

    duration_sec = round(time.time() - start_time, 2)

    # 1. Save to JSON
    json_filename = f"{batch_name}.json"
    json_path = os.path.join(MASTER_EXPORT_DIR, "JSON", json_filename)
    with open(json_path, "w", encoding="utf-8") as f_j:
        json.dump({
            "batch_id": batch_id,
            "query": query,
            "category": category,
            "total_items": len(processed_items),
            "duration_seconds": duration_sec,
            "items": processed_items
        }, f_j, indent=2, ensure_ascii=False)

    # 2. Save to CSV
    csv_filename = f"{batch_name}.csv"
    csv_path = os.path.join(MASTER_EXPORT_DIR, "CSV", csv_filename)
    with open(csv_path, "w", newline="", encoding="utf-8") as f_c:
        writer = csv.writer(f_c)
        writer.writerow(["No", "Title / Name", "Price / Info", "Domain / Source", "Phone / WA", "Email", "URL", "Snippet"])
        for it in processed_items:
            writer.writerow([
                it["no"],
                it["title"],
                it["price"],
                it["domain"],
                it["phone_wa"],
                it["email"],
                it["url"],
                it["snippet"]
            ])

    # 3. Save Batch Summary to SQLite
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
    INSERT INTO master_scrapes (batch_id, name, mode, target, total_items, data_json, csv_file, json_file)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        batch_id,
        batch_name,
        f"keyword_{category}",
        query,
        len(processed_items),
        json.dumps(processed_items[:100]),
        csv_path,
        json_path
    ))
    conn.commit()
    conn.close()

    return {
        "status": "success",
        "batch_id": batch_id,
        "batch_name": batch_name,
        "query": query,
        "category": category,
        "total_scraped": len(processed_items),
        "duration_seconds": duration_sec,
        "items": processed_items,
        "csv_download_url": f"/api/artifacts/download?path={csv_path}",
        "json_download_url": f"/api/artifacts/download?path={json_path}",
        "csv_path": csv_path,
        "json_path": json_path
    }


def scrape_custom_urls_or_selectors(
    urls: List[str],
    concurrency: int = 15,
    use_camoufox: bool = False
) -> Dict[str, Any]:
    """
    Scrapes a custom list of URLs with auto-extraction and concurrency.
    """
    import fast_scraper
    start_time = time.time()
    batch_id = f"custom_{int(time.time())}_{uuid.uuid4().hex[:6]}"
    batch_name = f"Custom_Batch_{len(urls)}_URLs"

    clean_urls = [u.strip() for u in urls if u.strip().startswith("http://") or u.strip().startswith("https://")]
    if not clean_urls:
        return {"status": "error", "message": "Tidak ada URL valid yang diberikan."}

    def _scrape_single(url: str) -> Dict[str, Any]:
        try:
            if use_camoufox:
                return fast_scraper.scrape_with_camoufox(url)
            else:
                return fast_scraper.scrape_with_tls_client(url)
        except Exception as e:
            return {"status": "error", "url": url, "error": str(e)}

    # Multi-threaded execution pool
    with ThreadPoolExecutor(max_workers=min(concurrency, 30)) as pool:
        raw_outputs = list(pool.map(_scrape_single, clean_urls))

    items = []
    for idx, out in enumerate(raw_outputs, 1):
        if out.get("status") == "success":
            data = out.get("data", {})
            items.append({
                "no": idx,
                "url": out.get("url"),
                "title": data.get("title") or out.get("title") or "Halaman Web",
                "price": data.get("price") or "N/A",
                "image_url": data.get("image_url") or "",
                "description": data.get("description") or "",
                "method": out.get("method") or "Fast Scraper"
            })
        else:
            items.append({
                "no": idx,
                "url": out.get("url"),
                "title": "Gagal Mengambil Data",
                "price": "N/A",
                "image_url": "",
                "description": out.get("error", "Unknown error"),
                "method": "Failed"
            })

    duration_sec = round(time.time() - start_time, 2)

    # Save to CSV & JSON
    csv_path = os.path.join(MASTER_EXPORT_DIR, "CSV", f"{batch_name}_{batch_id}.csv")
    json_path = os.path.join(MASTER_EXPORT_DIR, "JSON", f"{batch_name}_{batch_id}.json")

    with open(csv_path, "w", newline="", encoding="utf-8") as f_c:
        writer = csv.writer(f_c)
        writer.writerow(["No", "Title", "Price", "URL", "Image URL", "Description", "Engine"])
        for it in items:
            writer.writerow([it["no"], it["title"], it["price"], it["url"], it["image_url"], it["description"][:120], it["method"]])

    with open(json_path, "w", encoding="utf-8") as f_j:
        json.dump({"batch_id": batch_id, "total_urls": len(clean_urls), "items": items}, f_j, indent=2, ensure_ascii=False)

    return {
        "status": "success",
        "batch_id": batch_id,
        "total_requested": len(clean_urls),
        "total_successful": sum(1 for x in items if x["method"] != "Failed"),
        "duration_seconds": duration_sec,
        "items": items,
        "csv_download_url": f"/api/artifacts/download?path={csv_path}",
        "json_download_url": f"/api/artifacts/download?path={json_path}",
        "csv_path": csv_path
    }


def list_all_scrape_batches(limit: int = 20) -> List[Dict[str, Any]]:
    """List recent master scrape batches."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT id, batch_id, name, mode, target, total_items, csv_file, json_file, created_at FROM master_scrapes ORDER BY created_at DESC LIMIT ?", (limit,))
    rows = cur.fetchall()
    conn.close()

    items = []
    for r in rows:
        items.append({
            "id": r["id"],
            "batch_id": r["batch_id"],
            "name": r["name"],
            "mode": r["mode"],
            "target": r["target"],
            "total_items": r["total_items"],
            "csv_download_url": f"/api/artifacts/download?path={r['csv_file']}",
            "json_download_url": f"/api/artifacts/download?path={r['json_file']}",
            "created_at": r["created_at"]
        })
    return items
