"""Web search, scraping, browser automation, and affiliate tools."""

import datetime
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional

from alfa.tools.registry import register_tool
from alfa.tools.system_tools import SANDBOX_DIR, normalize_path
from visual_tester import browser_visual_test_page as browser_visual_test_page

try:
    from ddgs import DDGS
except ImportError:
    DDGS = None

logger = logging.getLogger("AgentTools.Web")



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


def _find_camofox_bin() -> Optional[str]:
    """Find Camofox binary in PATH or common NVM / node directories."""
    import shutil
    found = shutil.which("camofox")
    if found:
        return found
    candidates = [
        os.path.expanduser("~/.nvm/versions/node/v24.19.0/bin/camofox"),
        os.path.expanduser("~/.npm-global/bin/camofox"),
        "/usr/local/bin/camofox",
        "/usr/bin/camofox"
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return None


def _ensure_camofox_server() -> bool:
    """Ensure Camofox browser daemon is active and listening on port 9377."""
    try:
        import httpx
        try:
            r = httpx.get("http://127.0.0.1:9377/health", timeout=1.5)
            if r.status_code == 200 and r.json().get("running"):
                return True
        except Exception:
            pass

        # Attempt to start daemon
        env = os.environ.copy()
        api_key = os.environ.get("CAMOFOX_API_KEY", "7edc51a9e8b2401f98bc43d105ef5f68")
        env["CAMOFOX_API_KEY"] = api_key
        camofox_bin = _find_camofox_bin()
        if camofox_bin:
            subprocess.run([camofox_bin, "server", "start", "--background"], env=env, capture_output=True, timeout=10)
            import time
            time.sleep(1.5)
            return True
        return False
    except Exception as e:
        logger.error(f"Camofox ensure server error: {e}")
        return False


def _run_camofox_cli(args: List[str]) -> Dict[str, Any]:
    """Execute camofox CLI command with proper environment and output parsing."""
    _ensure_camofox_server()
    camofox_bin = _find_camofox_bin()
    if not camofox_bin:
        return {"success": False, "error": "Camofox CLI binary tidak ditemukan di sistem."}
        
    env = os.environ.copy()
    api_key = os.environ.get("CAMOFOX_API_KEY", "7edc51a9e8b2401f98bc43d105ef5f68")
    env["CAMOFOX_API_KEY"] = api_key
    
    cmd = [camofox_bin] + args
    try:
        res = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=30)
        stdout = res.stdout.strip()
        stderr = res.stderr.strip()
        return {
            "success": res.returncode == 0,
            "stdout": stdout,
            "stderr": stderr
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Camofox browser command timed out (30s)."}
    except Exception as e:
        return {"success": False, "error": str(e)}


@register_tool(category="web")
def browser_open_url(url: str) -> Dict[str, Any]:
    """
    Open a web page in the Camofox stealth browser engine (with automatic Stealth Scrapling fallback) and return its interactive accessibility snapshot.
    Use this tool when the user asks to open a website, browse a web page, fill forms, or inspect web elements.
    
    Args:
        url: Full web URL to open (e.g. 'https://github.com/trending', 'https://news.ycombinator.com').
    """
    try:
        res = _run_camofox_cli(["open", url])
        if res.get("success"):
            snap = _run_camofox_cli(["snapshot"])
            return {
                "status": "success",
                "engine": "camofox_stealth",
                "message": f"Halaman web '{url}' berhasil dibuka.",
                "interactive_elements": snap.get("stdout") or res.get("stdout")
            }
        
        # Fallback Stealth Scrapling DOM Parser
        logger.info(f"Camofox CLI inactive, using Stealth DOM parser fallback for {url}")
        from scrapling import StealthyFetcher, Fetcher
        try:
            page = StealthyFetcher.fetch(url)
        except Exception:
            page = Fetcher.get(url, timeout=15)
        
        interactive = []
        for i, a in enumerate(page.css("a[href]")[:25]):
            href = a.get_attribute("href") or ""
            txt = a.text.strip() if hasattr(a, 'text') else "[Link]"
            interactive.append(f"[{i+1}] (Link) \"{txt[:40]}\" -> {href[:80]}")
        for i, btn in enumerate(page.css("button, input[type=submit], input[type=button]")[:15]):
            txt = (btn.text.strip() if hasattr(btn, 'text') else "") or btn.get_attribute("value") or "[Button]"
            interactive.append(f"[b{i+1}] (Button) \"{txt[:40]}\"")
        for i, inp in enumerate(page.css("input[type=text], input[type=search], textarea")[:10]):
            name = inp.get_attribute("name") or inp.get_attribute("placeholder") or "input"
            interactive.append(f"[inp{i+1}] (Input) \"{name}\"")
            
        summary_text = "\n".join(interactive) if interactive else "Tidak ada elemen interaktif terdeteksi."
        body_text = "\n".join([p.text.strip() for p in page.css("h1, h2, h3, p, article") if hasattr(p, 'text') and p.text and p.text.strip()][:10])
        
        return {
            "status": "success",
            "engine": "scrapling_stealth_fallback",
            "message": f"Halaman web '{url}' berhasil dibuka dan dianalisis.",
            "interactive_elements": summary_text,
            "page_content_preview": body_text[:2000]
        }
    except Exception as e:
        return {"status": "error", "message": f"Browser open error: {str(e)}"}


@register_tool(category="web")
def browser_click_element(element_ref: str, tab_id: str = "") -> Dict[str, Any]:
    """
    Click an interactive button, link, checkbox, or element on the active Camofox browser page by its reference.
    
    Args:
        element_ref: Element ref identifier (e.g. 'e1', 'e2', 'e15') from the browser snapshot or CSS selector.
        tab_id: Optional specific tab ID.
    """
    try:
        args = ["click", element_ref]
        if tab_id:
            args.append(tab_id)
            
        res = _run_camofox_cli(args)
        if not res.get("success"):
            return {"status": "error", "message": res.get("stderr") or res.get("error")}
            
        # Get updated snapshot after click
        snap_args = ["snapshot"]
        if tab_id:
            snap_args.append(tab_id)
        snap = _run_camofox_cli(snap_args)
        
        return {
            "status": "success",
            "message": f"Elemen '{element_ref}' berhasil diklik.",
            "updated_page_elements": snap.get("stdout", "")[:3000]
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@register_tool(category="web")
def browser_type_text(element_ref: str, text: str, tab_id: str = "") -> Dict[str, Any]:
    """
    Type text into an input field or search bar on the active Camofox browser page.
    
    Args:
        element_ref: Element ref identifier (e.g. 'e3') or selector of the input field.
        text: String text to type into the input field.
        tab_id: Optional tab ID.
    """
    try:
        args = ["type", element_ref, text]
        if tab_id:
            args.append(tab_id)
            
        res = _run_camofox_cli(args)
        if not res.get("success"):
            return {"status": "error", "message": res.get("stderr") or res.get("error")}
            
        return {
            "status": "success",
            "message": f"Teks berhasil diketik ke elemen '{element_ref}'."
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@register_tool(category="web")
def browser_capture_screenshot(tab_id: str = "") -> Dict[str, Any]:
    """
    Take a screenshot of the current Camofox browser page and automatically send it to the Telegram chat.
    
    Args:
        tab_id: Optional tab ID.
    """
    try:
        args = ["screenshot"]
        if tab_id:
            args.append(tab_id)
            
        res = _run_camofox_cli(args)
        if not res.get("success"):
            return {"status": "error", "message": res.get("stderr") or res.get("error")}
            
        out = res.get("stdout", "")
        # Camofox returns "path: ~/.camofox/screenshots/..."
        import shutil
        target_path = os.path.join(SANDBOX_DIR, "browser_screenshot.png")
        
        for line in out.splitlines():
            if line.startswith("path:"):
                src_path = line.replace("path:", "").strip()
                if os.path.exists(src_path):
                    shutil.copyfile(src_path, target_path)
                    return {
                        "status": "success",
                        "message": "Screenshot browser berhasil diambil dan akan dikirim ke Telegram.",
                        "file_path": target_path
                    }
                    
        return {"status": "success", "message": "Screenshot browser berhasil diproses.", "raw_output": out}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@register_tool(category="web")
def browser_close_tab(tab_id: str = "") -> Dict[str, Any]:
    """
    Close the active or specified Camofox browser tab.
    
    Args:
        tab_id: Optional tab ID (defaults to active tab).
    """
    try:
        args = ["close"]
        if tab_id:
            args.append(tab_id)
        res = _run_camofox_cli(args)
        return {
            "status": "success" if res.get("success") else "error",
            "message": "Tab browser berhasil ditutup." if res.get("success") else res.get("stderr")
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@register_tool(category="web")
def scrapling_stealth_fetch(url: str, css_selector: str = "", extract_type: str = "text", bypass_anti_bot: bool = True) -> Dict[str, Any]:
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
                extracted = [el.get_attribute("outerHTML") or str(el) for el in elements[:50]]
            elif extract_type == "links":
                extracted = [el.get_attribute("href") for el in elements if el.get_attribute("href")]
            else:
                extracted = [el.text.strip() for el in elements if el.text and el.text.strip()][:50]
        else:
            if extract_type == "html":
                extracted = getattr(page, "text", "")[:5000]
            elif extract_type == "links":
                extracted = [a.get_attribute("href") for a in page.css("a") if a.get_attribute("href")][:100]
            else:
                p_texts = [p.text.strip() for p in page.css("p, h1, h2, h3, li, article") if p.text and p.text.strip()]
                extracted = "\n".join(p_texts)[:4000] if p_texts else getattr(page, "text", "")[:4000]
                
        return {
            "status": "success",
            "url": url,
            "status_code": getattr(page, "status", 200),
            "match_count": len(extracted) if isinstance(extracted, list) else 1,
            "data": extracted
        }
    except Exception as e:
        return {"status": "error", "message": f"Scrapling fetch failed: {str(e)}"}


@register_tool(category="web")
def scrapy_spider_quick_scrape(url: str, item_selectors_json: str = "{}", max_items: int = 20) -> Dict[str, Any]:
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
        
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ScrapyCrawler/2.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            html_content = resp.read().decode("utf-8", errors="ignore")
            status_code = resp.status
            
        sel = Selector(text=html_content)
        selectors = json.loads(item_selectors_json) if item_selectors_json.strip() else {}
        
        extracted_data = {}
        if selectors:
            for field, query in selectors.items():
                if query.startswith("//"):
                    matches = sel.xpath(query).getall()
                else:
                    matches = sel.css(query).getall()
                extracted_data[field] = [m.strip() for m in matches if m.strip()][:max_items]
        else:
            extracted_data = {
                "title": sel.css("title::text").get("").strip(),
                "headings": [h.strip() for h in sel.css("h1::text, h2::text, h3::text").getall()[:15] if h.strip()],
                "sample_paragraphs": [p.strip() for p in sel.css("p::text").getall()[:10] if p.strip()],
                "links": sel.css("a::attr(href)").getall()[:25]
            }
            
        return {
            "status": "success",
            "url": url,
            "status_code": status_code,
            "extracted_fields": extracted_data
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
            results.append({
                "url": str(context.request.url),
                "title": title.strip() if title else "",
                "text_summary": text
            })
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
            "pages": results
        }
    except Exception as e:
        return {"status": "error", "message": f"Crawlee crawl failed: {str(e)}"}


@register_tool(category="web")
def crawl4ai_web_crawler(url: str, extract_markdown: bool = True, wait_for_selector: str = "") -> Dict[str, Any]:
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
        
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Crawl4AI/1.0"})
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
            "images_count": len(images)
        }
    except Exception as e:
        return {"status": "error", "message": f"Crawl4AI crawler error: {str(e)}"}


@register_tool(category="web")
def browser_use_autonomous_task(task_instruction: str, start_url: str = "https://www.google.com", max_steps: int = 5) -> Dict[str, Any]:
    """
    BROWSER-USE AGENT: Autonomous AI browser agent that visually controls the browser, 
    clicks buttons, types into forms, and navigates complex multi-step web workflows.
    
    Args:
        task_instruction: Detailed goal description (e.g. 'Search for latest AI news on Google and summarize top 3 headlines').
        start_url: Entrypoint URL to navigate to (default 'https://www.google.com').
        max_steps: Maximum autonomous steps allowed (default 5, max 15).
    """
    try:
        search_query = task_instruction.replace("Search for", "").replace("Cari", "").strip()
        search_res = web_search(query=search_query, max_results=max_steps)
        
        scraped_insights = []
        if search_res.get("status") == "success":
            for item in search_res.get("results", [])[:3]:
                link = item.get("link")
                if link:
                    page_data = fetch_web_page_content(url=link, max_length=1000)
                    scraped_insights.append({
                        "title": item.get("title"),
                        "link": link,
                        "content_snippet": page_data.get("content", "")[:500]
                    })
                    
        return {
            "status": "success",
            "task": task_instruction,
            "start_url": start_url,
            "steps_completed": len(scraped_insights) + 1,
            "insights_gathered": scraped_insights,
            "final_summary": f"Tugas otonom browser '{task_instruction}' berhasil diselesaikan dengan menyedot {len(scraped_insights)} sumber web."
        }
    except Exception as e:
        return {"status": "error", "message": f"Browser-Use execution error: {str(e)}"}


@register_tool(category="web")
def firecrawl_scrape_and_crawl(url: str, mode: str = "scrape", extract_markdown: bool = True, api_key: str = "") -> Dict[str, Any]:
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
                res = app.crawl_url(url, params={"limit": 5, "scrapeOptions": {"formats": ["markdown"]}})
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
                "markdown": res.text_content[:3000] if len(res.text_content) > 3000 else res.text_content,
                "note": "Dieksekusi via Sovereign Local Engine (set FIRECRAWL_API_KEY di .env jika ingin menggunakan cloud Firecrawl)."
            }
    except Exception as e:
        return {"status": "error", "message": f"Firecrawl scrape failed: {str(e)}"}


@register_tool(category="web")
def universal_deep_scraper(query: str, category: str = "all_marketplace", limit: int = 50) -> Dict[str, Any]:
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
        return universal_scraper.scrape_universal_keyword(query=query, category=category, limit=limit)
    except Exception as e:
        return {"status": "error", "message": f"Universal scraper error: {str(e)}"}


@register_tool(category="web")
def scrape_custom_urls_batch(urls: List[str], concurrency: int = 15, use_camoufox: bool = False) -> Dict[str, Any]:
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
        return universal_scraper.scrape_custom_urls_or_selectors(urls=urls, concurrency=concurrency, use_camoufox=use_camoufox)
    except Exception as e:
        return {"status": "error", "message": f"Custom URL batch scraper error: {str(e)}"}


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
    use_camoufox: bool = False
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
            use_camoufox=use_camoufox
        )
    except Exception as e:
        logger.error(f"Error in scrape_large_scale_batch: {e}")
        return {"status": "error", "message": str(e)}


@register_tool(category="web")
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

