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

from alfa.core import database
from alfa import tools
from alfa.dashboard.common import REPO_ROOT, get_primary_user_id, logger, safe_int

router = APIRouter()

# ==================== SCRAPER ENDPOINTS ====================

@router.post("/api/scraper/universal")
async def api_universal_scrape(payload: Dict[str, Any]):
    """Execute high-yield universal keyword scraper across specialized platforms."""
    from alfa.scrapers import universal as universal_scraper
    query = payload.get("query", "").strip()
    category = payload.get("category", "all_marketplace")
    limit = safe_int(payload.get("limit", 50), 50, minimum=1, maximum=200)
    if not query:
        return {"status": "error", "message": "Query pencarian wajib diisi."}

    res = universal_scraper.scrape_universal_keyword(query=query, category=category, limit=limit)
    return res


@router.post("/api/scraper/custom-batch")
async def api_custom_batch_scrape(payload: Dict[str, Any]):
    """Execute custom multi-URL batch scraper."""
    from alfa.scrapers import universal as universal_scraper
    urls = payload.get("urls", [])
    concurrency = safe_int(payload.get("concurrency", 15), 15, minimum=1, maximum=50)
    use_camoufox = bool(payload.get("use_camoufox", False))
    if not urls:
        return {"status": "error", "message": "Daftar URL wajib diisi."}

    res = universal_scraper.scrape_custom_urls_or_selectors(urls=urls, concurrency=concurrency, use_camoufox=use_camoufox)
    return res


@router.get("/api/scraper/batches")
async def api_list_scraper_batches(limit: int = 15):
    """List recent master scraper batches."""
    from alfa.scrapers import universal as universal_scraper
    batches = universal_scraper.list_all_scrape_batches(limit=limit)
    return {"status": "success", "batches": batches}


@router.post("/api/scraper/modern-lab")
async def api_modern_scraper_lab(payload: Dict[str, Any]):
    """Unified Next-Gen Scraper Lab combining multiple scraping engines."""
    url = payload.get("url", "").strip()
    engine = payload.get("engine", "auto_hybrid")
    css_selector = payload.get("css_selector", "").strip()
    extract_type = payload.get("extract_type", "markdown")
    max_pages = safe_int(payload.get("max_pages", 3), 3, minimum=1, maximum=50)
    auto_ingest = bool(payload.get("auto_ingest_vector", False))

    if not url:
        return {"status": "error", "message": "URL target wajib diisi."}

    start_t = time.time()
    extracted_text = ""
    markdown_output = ""
    raw_data = None
    engine_used = engine

    try:
        if engine == "crawl4ai":
            res = tools.crawl4ai_web_crawler(url=url)
            markdown_output = res.get("markdown", "")
            extracted_text = markdown_output
            raw_data = res
        elif engine == "scrapling":
            res = tools.scrapling_stealth_fetch(url=url, css_selector=css_selector, extract_type=extract_type)
            raw_data = res
            if isinstance(res.get("data"), list):
                extracted_text = "\n".join(str(x) for x in res["data"])
            else:
                extracted_text = str(res.get("data", ""))
            markdown_output = f"# Scraped from {url}\n\n" + extracted_text
        elif engine == "markitdown":
            res = tools.markitdown_convert_document(source_path_or_url=url)
            markdown_output = res.get("markdown_snippet", "")
            extracted_text = markdown_output
            raw_data = res
        elif engine == "scrapy":
            item_json = json.dumps({"selected": css_selector}) if css_selector else "{}"
            res = tools.scrapy_spider_quick_scrape(url=url, item_selectors_json=item_json)
            raw_data = res
            extracted_text = json.dumps(res.get("extracted_fields", {}), indent=2)
            markdown_output = f"# Scrapy Parsel Result for {url}\n\n```json\n{extracted_text}\n```"
        elif engine == "crawlee":
            res = tools.crawlee_web_scraper(start_urls=url, max_requests=max_pages)
            raw_data = res
            pages = res.get("pages", [])
            extracted_text = "\n\n".join([f"### {p.get('title')}\nURL: {p.get('url')}\n{p.get('text_summary')}" for p in pages])
            markdown_output = f"# Crawlee Multi-Page Result ({len(pages)} pages)\n\n" + extracted_text
        elif engine == "firecrawl":
            res = tools.firecrawl_scrape_and_crawl(url=url)
            raw_data = res
            markdown_output = res.get("markdown", "")
            extracted_text = markdown_output
        else:
            engine_used = "auto_hybrid (Scrapling -> Crawl4AI -> MarkItDown)"
            res = tools.scrapling_stealth_fetch(url=url, css_selector=css_selector, extract_type="text")
            if res.get("status") == "success" and res.get("data"):
                data_val = res.get("data")
                extracted_text = "\n".join(data_val) if isinstance(data_val, list) else str(data_val)
                markdown_output = f"# Extracted Content: {url}\n\n" + extracted_text
                raw_data = res
            else:
                res2 = tools.crawl4ai_web_crawler(url=url)
                if res2.get("status") == "success" and res2.get("markdown"):
                    markdown_output = res2.get("markdown", "")
                    extracted_text = markdown_output
                    raw_data = res2
                else:
                    res3 = tools.markitdown_convert_document(source_path_or_url=url)
                    markdown_output = res3.get("markdown_snippet", "")
                    extracted_text = markdown_output
                    raw_data = res3

        duration_ms = round((time.time() - start_t) * 1000, 1)

        vector_status = None
        if auto_ingest and extracted_text.strip():
            import vector_memory
            uid = get_primary_user_id()
            v_res = vector_memory.ingest_document(
                user_id=uid,
                title=f"Web Scrape: {url[:50]}",
                content_or_path=extracted_text,
                category="Scraped Web Lab"
            )
            vector_status = v_res

        return {
            "status": "success",
            "url": url,
            "engine": engine_used,
            "duration_ms": duration_ms,
            "markdown": markdown_output,
            "extracted_text": extracted_text[:5000],
            "raw_data": raw_data,
            "vector_ingest": vector_status
        }
    except Exception as e:
        return {"status": "error", "message": f"Scraper Lab error: {str(e)}"}


