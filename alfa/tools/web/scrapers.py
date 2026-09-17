"""Multi-engine scraping tools (Scrapling, Scrapy, Crawlee, Crawl4AI, Firecrawl, and Universal Scrapers)."""

import json
import logging
import os
import subprocess
import time
from typing import Any, Dict, List, Optional

from alfa.tools.registry import register_tool
from alfa.tools.system_tools import SANDBOX_DIR

logger = logging.getLogger("AgentTools.Web.Scrapers")


def scrapling_stealth_fetch(
    url: str,
    css_selector: str = "",
    extract_type: str = "text",
    bypass_anti_bot: bool = True,
) -> Dict[str, Any]:
    """
    SCRAPLING STEALTH SUITE: Ultra-fast stealth web scraper engineered to bypass Cloudflare,
    Akamai, and anti-bot systems to extract structured web elements.

    Args:
        url: The web URL to scrape.
        css_selector: Optional CSS selector to extract specific elements (e.g. 'h1', '.product-title', 'table tr').
        extract_type: 'text' (clean text), 'html' (outer HTML), or 'links' (all href URLs).
        bypass_anti_bot: Whether to use stealth fingerprinting (default True).
    """
    try:
        from scrapling import Fetcher, StealthyFetcher

        if bypass_anti_bot:
            try:
                page = StealthyFetcher.fetch(url)
            except Exception:
                page = Fetcher.get(url, timeout=15)
        else:
            page = Fetcher.get(url, timeout=15)

        if css_selector:
            elements = page.css(css_selector)
            if extract_type == "html":
                extracted = [
                    el.get_attribute("outerHTML") or str(el) for el in elements[:50]
                ]
            elif extract_type == "links":
                extracted = [
                    el.get_attribute("href")
                    for el in elements
                    if el.get_attribute("href")
                ]
            else:
                extracted = [
                    el.text.strip() for el in elements if el.text and el.text.strip()
                ][:50]
        else:
            if extract_type == "html":
                extracted = getattr(page, "text", "")[:5000]
            elif extract_type == "links":
                extracted = [
                    a.get_attribute("href")
                    for a in page.css("a")
                    if a.get_attribute("href")
                ][:100]
            else:
                p_texts = [
                    p.text.strip()
                    for p in page.css("p, h1, h2, h3, li, article")
                    if p.text and p.text.strip()
                ]
                extracted = (
                    "\n".join(p_texts)[:4000]
                    if p_texts
                    else getattr(page, "text", "")[:4000]
                )

        return {
            "status": "success",
            "url": url,
            "status_code": getattr(page, "status", 200),
            "match_count": len(extracted) if isinstance(extracted, list) else 1,
            "data": extracted,
        }
    except Exception as e:
        return {"status": "error", "message": f"Scrapling fetch failed: {str(e)}"}


@register_tool(category="web")
def scrapy_spider_quick_scrape(
    url: str, item_selectors_json: str = "{}", max_items: int = 20
) -> Dict[str, Any]:
    """
    SCRAPY FAST ENGINE: High-throughput web crawler and structured item extractor.

    Args:
        url: The entrypoint URL.
        item_selectors_json: JSON string mapping fields to CSS/XPath selectors.
                             Example: '{"title": "h1::text", "prices": ".price::text", "links": "a::attr(href)"}'
        max_items: Maximum items to extract per selector.
    """
    try:
        import json
        import urllib.request

        from parsel import Selector

        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ScrapyCrawler/2.0"
            },
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            html_content = resp.read().decode("utf-8", errors="ignore")
            status_code = resp.status

        sel = Selector(text=html_content)
        selectors = (
            json.loads(item_selectors_json) if item_selectors_json.strip() else {}
        )

        extracted_data = {}
        if selectors:
            for field, query in selectors.items():
                if query.startswith("//"):
                    matches = sel.xpath(query).getall()
                else:
                    matches = sel.css(query).getall()
                extracted_data[field] = [m.strip() for m in matches if m.strip()][
                    :max_items
                ]
        else:
            extracted_data = {
                "title": sel.css("title::text").get("").strip(),
                "headings": [
                    h.strip()
                    for h in sel.css("h1::text, h2::text, h3::text").getall()[:15]
                    if h.strip()
                ],
                "sample_paragraphs": [
                    p.strip() for p in sel.css("p::text").getall()[:10] if p.strip()
                ],
                "links": sel.css("a::attr(href)").getall()[:25],
            }

        return {
            "status": "success",
            "url": url,
            "status_code": status_code,
            "extracted_fields": extracted_data,
        }
    except Exception as e:
        return {"status": "error", "message": f"Scrapy scraper error: {str(e)}"}


@register_tool(category="web")
def crawlee_web_scraper(start_urls: str, max_requests: int = 5) -> Dict[str, Any]:
    """
    CRAWLEE SUITE: Industrial-grade web crawler pipeline with automatic request queueing,
    retry handling, and content aggregation.

    Args:
        start_urls: Single URL or comma-separated URLs to start crawling.
        max_requests: Maximum number of pages to request/crawl (default 5, max 20).
    """
    try:
        import asyncio

        from crawlee.crawlers import BeautifulSoupCrawler, BeautifulSoupCrawlingContext

        urls = [u.strip() for u in start_urls.split(",") if u.strip()]
        max_req = min(20, max(1, max_requests))
        results = []

        crawler = BeautifulSoupCrawler(max_requests_per_crawl=max_req)

        @crawler.router.default_handler
        async def request_handler(context: BeautifulSoupCrawlingContext) -> None:
            title = context.soup.title.string if context.soup.title else ""
            text = " ".join(context.soup.stripped_strings)[:1500]
            results.append(
                {
                    "url": str(context.request.url),
                    "title": title.strip() if title else "",
                    "text_summary": text,
                }
            )
            if len(results) < max_req:
                await context.enqueue_links()

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(crawler.run(urls))
        finally:
            loop.close()

        return {
            "status": "success",
            "start_urls": urls,
            "total_crawled_pages": len(results),
            "pages": results,
        }
    except Exception as e:
        return {"status": "error", "message": f"Crawlee crawl failed: {str(e)}"}


@register_tool(category="web")
def crawl4ai_web_crawler(
    url: str, extract_markdown: bool = True, wait_for_selector: str = ""
) -> Dict[str, Any]:
    """
    CRAWL4AI ENGINE: Asynchronous LLM-first web crawler that converts complex web pages
    into clean Markdown, fit-markdown, internal/external links, and media metadata.

    Args:
        url: The web URL to crawl.
        extract_markdown: Extract clean LLM-ready markdown (default True).
        wait_for_selector: Optional CSS selector to wait for before extracting.
    """
    try:
        import urllib.request

        import markdownify
        from bs4 import BeautifulSoup

        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Crawl4AI/1.0"
            },
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
            status_code = resp.status

        soup = BeautifulSoup(html, "html.parser")
        title = soup.title.string if soup.title else ""

        for tag in soup(["script", "style", "noscript", "svg"]):
            tag.decompose()

        md_content = markdownify.markdownify(str(soup), heading_style="ATX").strip()
        links = [a.get("href") for a in soup.find_all("a", href=True)][:50]
        images = [img.get("src") for img in soup.find_all("img", src=True)][:20]

        return {
            "status": "success",
            "url": url,
            "title": title.strip() if title else "",
            "status_code": status_code,
            "markdown": md_content[:3000] if len(md_content) > 3000 else md_content,
            "content_length": len(md_content),
            "links_count": len(links),
            "links_sample": links[:15],
            "images_count": len(images),
        }
    except Exception as e:
        return {"status": "error", "message": f"Crawl4AI crawler error: {str(e)}"}


def firecrawl_scrape_and_crawl(
    url: str, mode: str = "scrape", extract_markdown: bool = True, api_key: str = ""
) -> Dict[str, Any]:
    """
    FIRECRAWL SUITE: Intelligent web scraper and crawler optimized for LLM RAG pipelines.
    Supports Firecrawl API with automatic local fallback to MarkItDown / Crawl4AI engine.

    Args:
        url: The web URL to scrape or crawl.
        mode: 'scrape' (single page) or 'crawl' (multi-page sublinks).
        extract_markdown: Extract clean markdown for RAG.
        api_key: Optional Firecrawl API key (uses FIRECRAWL_API_KEY env or local engine fallback).
    """
    try:
        key = api_key or os.environ.get("FIRECRAWL_API_KEY", "")
        if key:
            from firecrawl import FirecrawlApp

            app = FirecrawlApp(api_key=key)
            if mode == "crawl":
                res = app.crawl_url(
                    url, params={"limit": 5, "scrapeOptions": {"formats": ["markdown"]}}
                )
            else:
                res = app.scrape_url(url, params={"formats": ["markdown"]})
            return {"status": "success", "engine": "firecrawl_cloud", "data": res}
        else:
            from markitdown import MarkItDown

            md = MarkItDown()
            res = md.convert(url)
            return {
                "status": "success",
                "engine": "sovereign_local_markitdown",
                "url": url,
                "title": getattr(res, "title", url),
                "markdown": (
                    res.text_content[:3000]
                    if len(res.text_content) > 3000
                    else res.text_content
                ),
                "note": "Dieksekusi via Sovereign Local Engine (set FIRECRAWL_API_KEY di .env jika ingin menggunakan cloud Firecrawl).",
            }
    except Exception as e:
        return {"status": "error", "message": f"Firecrawl scrape failed: {str(e)}"}


@register_tool(category="web")
def universal_deep_scraper(
    query: str, category: str = "all_marketplace", limit: int = 50
) -> Dict[str, Any]:
    """
    High-Volume Universal Pro Web Scraper:
    Scrapes large volumes (20 - 200+ results) of rich data across various categories:
    - 'all_marketplace' (Shopee, Tokopedia, TikTok Shop, Lazada, Blibli)
    - 'jobs_career' (JobStreet, LinkedIn, Glints, Karir.com)
    - 'news_media' (Detik, Kompas, CNN, Liputan6, CNBC)
    - 'leads_contacts' (WhatsApp, Phone, Email, Suppliers, Distributors)
    - 'property_realestate' (Rumah123, Rumah.com, Lamudi, OLX)
    - 'google_general' (General Web Deep Search)

    Automatically extracts Titles, Prices, Contacts (Phone/WA/Email), Domains, URLs, and saves to CSV & JSON.

    Args:
        query: What to scrape / search (e.g. 'sepatu sneakers running wanita', 'python developer', 'distributor kopi gayo').
        category: Platform category to scrape (default: 'all_marketplace').
        limit: Total items to harvest (default: 50, supports up to 200).
    """
    try:
        from alfa.scrapers import universal as universal_scraper

        return universal_scraper.scrape_universal_keyword(
            query=query, category=category, limit=limit
        )
    except Exception as e:
        return {"status": "error", "message": f"Universal scraper error: {str(e)}"}


@register_tool(category="web")
def scrape_custom_urls_batch(
    urls: List[str], concurrency: int = 15, use_camoufox: bool = False
) -> Dict[str, Any]:
    """
    Scrape any custom list of URLs with high-speed multi-threaded workers or Camoufox stealth browser.
    Extracts page titles, meta info, prices, images, and descriptions into CSV and JSON.

    Args:
        urls: List of web URLs to scrape.
        concurrency: Concurrent scraping workers (default: 15).
        use_camoufox: If True, uses Camoufox anti-detect stealth browser (for Cloudflare/JS-heavy pages).
    """
    try:
        from alfa.scrapers import universal as universal_scraper

        return universal_scraper.scrape_custom_urls_or_selectors(
            urls=urls, concurrency=concurrency, use_camoufox=use_camoufox
        )
    except Exception as e:
        return {
            "status": "error",
            "message": f"Custom URL batch scraper error: {str(e)}",
        }


@register_tool(category="web")
def scrape_real_product_data(url: str, engine: str = "auto") -> Dict[str, Any]:
    """
    Scrape data produk real dari Shopee, TikTok Shop, Tokopedia, atau website manapun menggunakan Camoufox Anti-Detect Browser atau Fast TLS.
    Bypass proteksi Cloudflare, bot detector, dan dynamic javascript rendering.

    Args:
        url: Link produk atau halaman yang ingin discrape.
        engine: Pilihan engine ('auto', 'camoufox', 'fast_tls').
    """
    try:
        from alfa.scrapers import fast as fast_scraper

        if engine == "camoufox":
            return fast_scraper.scrape_with_camoufox(url)
        elif engine == "fast_tls":
            return fast_scraper.scrape_with_fast_tls(url)
        else:
            domain = url.lower()
            if "shopee" in domain or "tiktok" in domain or "tokopedia" in domain:
                return fast_scraper.scrape_with_camoufox(url)
            else:
                return fast_scraper.scrape_with_fast_tls(url)
    except Exception as e:
        logger.error(f"Error in scrape_real_product_data: {e}")
        return {"status": "error", "message": str(e)}


@register_tool(category="web")
def scrape_large_scale_batch(
    urls: List[str],
    batch_name: str = "batch_products",
    max_concurrency: int = 15,
    use_camoufox: bool = False,
) -> Dict[str, Any]:
    """
    Scraping paralel skala besar untuk puluhan hingga ribuan URL sekaligus dengan kecepatan sangat tinggi.
    Hasil otomatis diekspor ke file JSON dan CSV di ~/Dokumen/ALFA_SCRAPER_DATA/.

    Args:
        urls: Daftar URL yang ingin discrape secara massal.
        batch_name: Nama batch untuk penamaan file ekspor.
        max_concurrency: Jumlah request paralel serentak (default: 15).
        use_camoufox: True untuk menggunakan browser Camoufox Anti-Detect, False untuk Fast TLS engine.
    """
    try:
        from alfa.scrapers import fast as fast_scraper

        return fast_scraper.run_batch_scrape(
            urls=urls,
            batch_name=batch_name,
            max_concurrency=max_concurrency,
            use_camoufox=use_camoufox,
        )
    except Exception as e:
        logger.error(f"Error in scrape_large_scale_batch: {e}")
        return {"status": "error", "message": str(e)}
