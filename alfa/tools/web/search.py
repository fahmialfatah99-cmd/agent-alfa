"""Web search, page fetching, and security audit tools."""

import datetime
import json
import logging
import os
import re
import subprocess
from typing import Any, Dict, List, Optional

from alfa.tools.registry import register_tool

try:
    from ddgs import DDGS
except ImportError:
    DDGS = None

logger = logging.getLogger("AgentTools.Web.Search")

@register_tool(category="web")
def web_search(query: str, max_results: int = 5) -> Dict[str, Any]:
    """
    Perform a live web search using DuckDuckGo to get up-to-date real-time information, news, or facts.
    Use this tool whenever the user asks about current events, stock prices, weather, documentation, or recent news.
    
    Args:
        query: Search query string.
        max_results: Maximum number of search results to return (default: 5).
    """
    try:
        if DDGS is None:
            return {
                "status": "error",
                "message": "Paket pencarian web (ddgs) belum terpasang. Jalankan: pip install ddgs",
            }
        logger.info(f"Searching web for: {query}")
        results = list(DDGS(verify=False).text(query, max_results=max_results))
        if not results:
            return {"status": "success", "results": [], "message": "Tidak ada hasil pencarian ditemukan."}
        
        formatted_results = []
        for item in results:
            formatted_results.append({
                "title": item.get("title", ""),
                "snippet": item.get("body", ""),
                "link": item.get("href", "")
            })
            
        return {"status": "success", "results": formatted_results}
    except Exception as e:
        logger.error(f"Web search error: {e}")
        return {"status": "error", "message": f"Gagal melakukan pencarian web: {str(e)}"}


@register_tool(category="web")
def fetch_web_page_content(url: str, max_length: int = 5000) -> Dict[str, Any]:
    """
    Fetch and extract clean text and structured content from any website or article URL.
    Uses multi-tier stealth engine (Fast TLS -> Stealthy Scrapling -> MarkItDown) to bypass anti-bot protections.
    
    Args:
        url: Full web URL (e.g. 'https://en.wikipedia.org/wiki/Python').
        max_length: Maximum text length to extract (default: 5000 chars).
    """
    text = ""
    status_code = 200
    engine_used = "httpx"
    
    # Tier 1: Fast HTTPX with Chrome/Linux Headers
    try:
        import httpx
        headers = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
            "Sec-Ch-Ua": '"Chromium";v="130", "Google Chrome";v="130", "Not?A_Brand";v="99"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Linux"',
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Upgrade-Insecure-Requests": "1"
        }
        with httpx.Client(timeout=12.0, follow_redirects=True, verify=False) as client:
            resp = client.get(url, headers=headers)
            status_code = resp.status_code
            if resp.status_code == 200:
                html = resp.text
                # Clean html
                html = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.IGNORECASE)
                html = re.sub(r"<style[\s\S]*?</style>", " ", html, flags=re.IGNORECASE)
                html = re.sub(r"<nav[\s\S]*?</nav>", " ", html, flags=re.IGNORECASE)
                html = re.sub(r"<footer[\s\S]*?</footer>", " ", html, flags=re.IGNORECASE)
                html = re.sub(r"<!--[\s\S]*?-->", " ", html)
                cleaned = re.sub(r"<[^>]+>", " ", html)
                text = re.sub(r"\s+", " ", cleaned).strip()
    except Exception as e:
        logger.debug(f"HTTPX fetch error, falling back to stealth: {e}")

    # Tier 2: Stealth Scrapling Fallback if Tier 1 got blocked (403/429/503/empty)
    if not text or len(text) < 100 or status_code in (403, 429, 503):
        try:
            from scrapling import StealthyFetcher, Fetcher
            engine_used = "scrapling_stealth"
            try:
                page = StealthyFetcher.fetch(url)
            except Exception:
                page = Fetcher.get(url, timeout=15)
            
            status_code = getattr(page, "status", 200)
            p_texts = [p.text.strip() for p in page.css("article, main, p, h1, h2, h3, li, table") if p.text and p.text.strip()]
            if p_texts:
                text = "\n\n".join(p_texts)
            else:
                raw = getattr(page, "text", "") or ""
                text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", raw)).strip()
        except Exception as err:
            logger.debug(f"Scrapling fallback failed: {err}")

    # Tier 3: MarkItDown Markdown Conversion if available
    if not text or len(text) < 80:
        try:
            from markitdown import MarkItDown
            mid = MarkItDown()
            res = mid.convert(url)
            if res and res.text_content:
                text = res.text_content.strip()
                engine_used = "markitdown"
        except Exception:
            pass

    if not text:
        return {
            "status": "error",
            "message": f"Gagal mengekstrak konten teks dari '{url}' (status code: {status_code}). Web mungkin memblokir akses atau memerlukan login."
        }

    if len(text) > max_length:
        text = text[:max_length] + "\n\n...[Konten web dipotong sesuai batas panjang maksimal]"

    return {
        "status": "success",
        "url": url,
        "engine": engine_used,
        "length": len(text),
        "content": text
    }


@register_tool(category="web")
def audit_website_security(target_url: str) -> Dict[str, Any]:
    """
    Conduct a Defensive Cybersecurity Audit on a website or API endpoint (Cyber Sentry):
    Audits SSL/TLS certificate, Security Headers (CSP, HSTS, X-Frame-Options, XSS, etc.),
    CORS policies, server fingerprint leaks, and generates an overall Security Grade (A+ to F).
    
    Args:
        target_url: The URL or domain to audit (e.g. 'https://shopee.co.id', 'https://example.com').
    """
    try:
        from alfa.core import permissions as security_auditor
        return security_auditor.audit_website_security(target_url)
    except Exception as e:
        return {"status": "error", "message": f"Security audit error: {str(e)}"}

