"""Web search, page fetching, and security audit tools."""

import logging
import os
import re
from typing import Any

from alfa.tools.registry import register_tool

try:
    from ddgs import DDGS
except ImportError:
    DDGS = None

logger = logging.getLogger("AgentTools.Web.Search")


def _ssl_verify() -> bool:
    """TLS verification for outbound web traffic (set ALFA_VERIFY_SSL=false only behind a MITM proxy)."""
    return os.getenv("ALFA_VERIFY_SSL", "true").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


@register_tool(category="web")
def web_search(query: str, max_results: int = 5) -> dict[str, Any]:
    """
    Perform a live web search using DuckDuckGo to get up-to-date real-time information, news, or facts.
    Falls back to the local Camoufox stealth browser (Bing) when the direct
    search API is blocked. Fully local, no cloud scraping API needed.
    Use this tool whenever the user asks about current events, stock prices, weather, documentation, or recent news.

    Args:
        query: Search query string.
        max_results: Maximum number of search results to return (default: 5).
    """
    if _ddgs_circuit_open():
        return _browser_search_fallback(
            query, max_results, reason="DDGS circuit-breaker aktif."
        )
    try:
        if DDGS is None:
            return _browser_search_fallback(
                query,
                max_results,
                reason="Paket pencarian web (ddgs) belum terpasang.",
            )
        logger.info(f"Searching web for: {query}")
        results = list(DDGS(verify=_ssl_verify()).text(query, max_results=max_results))
        if not results:
            _ddgs_note_failure()
            return _browser_search_fallback(
                query, max_results, reason="DDGS tidak mengembalikan hasil."
            )

        formatted_results = []
        for item in results:
            formatted_results.append(
                {
                    "title": item.get("title", ""),
                    "snippet": item.get("body", ""),
                    "link": item.get("href", ""),
                }
            )

        _ddgs_note_success()
        return {"status": "success", "results": formatted_results}
    except Exception as e:
        logger.error(f"Web search error: {e}")
        _ddgs_note_failure()
        return _browser_search_fallback(query, max_results, reason=str(e))


# ── DDGS circuit breaker ──────────────────────────────────────────────
# Jaringan ini memblokir DuckDuckGo (SSL reset). Setelah 3 gagal beruntun,
# lewati DDGS selama 10 menit dan langsung pakai browser — menghemat
# belasan detik timeout di setiap pencarian dalam satu turn.
_DDGS_BREAKER = {"fails": 0, "skip_until": 0.0}
_DDGS_FAIL_LIMIT = 3
_DDGS_COOLDOWN = 600.0


def _ddgs_circuit_open() -> bool:
    import time as _time

    return _time.time() < _DDGS_BREAKER["skip_until"]


def _ddgs_note_success() -> None:
    _DDGS_BREAKER["fails"] = 0
    _DDGS_BREAKER["skip_until"] = 0.0


def _ddgs_note_failure() -> None:
    import time as _time

    _DDGS_BREAKER["fails"] += 1
    if _DDGS_BREAKER["fails"] >= _DDGS_FAIL_LIMIT:
        _DDGS_BREAKER["skip_until"] = _time.time() + _DDGS_COOLDOWN
        logger.warning(
            "DDGS gagal %dx beruntun — circuit-breaker aktif 10 menit.",
            _DDGS_BREAKER["fails"],
        )


def _browser_search_fallback(
    query: str, max_results: int = 5, reason: str = ""
) -> dict[str, Any]:
    """Fallback pencarian via browser lokal (Camoufox + Bing).

    Dipakai saat API DDGS diblokir/gagal. Murni lokal, tanpa API cloud.
    """
    try:
        import threading
        from urllib.parse import quote_plus

        from alfa.tools.web.browser.engine import _ensure_page, _ui

        def _do() -> list[dict[str, str]]:
            page = _ensure_page()
            if page is None:
                return []
            url = f"https://www.bing.com/search?q={quote_plus(query)}"
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            try:
                page.wait_for_timeout(900)
            except Exception:  # noqa: BLE001
                pass
            try:
                data = page.evaluate(
                    """() => Array.from(document.querySelectorAll('li.b_algo'))
                        .slice(0, 12).map(li => {
                            const a = li.querySelector('h2 a');
                            const p = li.querySelector('.b_caption p, p');
                            let href = a ? (a.href || '') : '';
                            // Bing membungkus link asli di param ?u=a1<base64>.
                            // Buka bungkusnya agar dapat URL asli, bukan redirect.
                            try {
                                const m = href.match(/[?&]u=a1([^&]+)/);
                                if (m) href = atob(m[1]);
                            } catch (e) {}
                            return {
                                title: a ? a.innerText : '',
                                href: href,
                                body: p ? p.innerText : ''
                            };
                        })"""
                )
            except Exception:  # noqa: BLE001
                return []
            return [d for d in (data or []) if d.get("href")]

        if threading.current_thread().name.startswith("alfa-browser"):
            raw = _do()
        else:
            raw = _ui(_do, timeout=90.0)

        formatted = [
            {
                "title": d.get("title", ""),
                "snippet": d.get("body", ""),
                "link": d.get("href", ""),
            }
            for d in raw[:max_results]
        ]
        if not formatted:
            return {
                "status": "error",
                "message": f"Pencarian web gagal (DDGS: {reason or 'unknown'}; browser lokal juga tidak dapat hasil).",
            }
        return {
            "status": "success",
            "results": formatted,
            "engine": "camoufox_bing_fallback",
            "note": f"DDGS gagal ({reason}), memakai browser lokal.",
        }
    except Exception as e:
        logger.error(f"Browser search fallback error: {e}")
        return {
            "status": "error",
            "message": f"Gagal melakukan pencarian web: {reason or e}",
        }


@register_tool(category="web")
def fetch_web_page_content(url: str, max_length: int = 5000) -> dict[str, Any]:
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
            "Upgrade-Insecure-Requests": "1",
        }
        with httpx.Client(
            timeout=12.0, follow_redirects=True, verify=_ssl_verify()
        ) as client:
            resp = client.get(url, headers=headers)
            status_code = resp.status_code
            if resp.status_code == 200:
                html = resp.text
                # Clean html
                html = re.sub(
                    r"<script[\s\S]*?</script>", " ", html, flags=re.IGNORECASE
                )
                html = re.sub(r"<style[\s\S]*?</style>", " ", html, flags=re.IGNORECASE)
                html = re.sub(r"<nav[\s\S]*?</nav>", " ", html, flags=re.IGNORECASE)
                html = re.sub(
                    r"<footer[\s\S]*?</footer>", " ", html, flags=re.IGNORECASE
                )
                html = re.sub(r"<!--[\s\S]*?-->", " ", html)
                cleaned = re.sub(r"<[^>]+>", " ", html)
                text = re.sub(r"\s+", " ", cleaned).strip()
    except Exception as e:
        logger.debug(f"HTTPX fetch error, falling back to stealth: {e}")

    # Tier 2: Stealth Scrapling Fallback if Tier 1 got blocked (403/429/503/empty)
    if not text or len(text) < 100 or status_code in (403, 429, 503):
        try:
            from scrapling import Fetcher, StealthyFetcher

            engine_used = "scrapling_stealth"
            try:
                page = StealthyFetcher.fetch(url)
            except Exception:
                page = Fetcher.get(url, timeout=15)

            status_code = getattr(page, "status", 200)
            p_texts = [
                p.text.strip()
                for p in page.css("article, main, p, h1, h2, h3, li, table")
                if p.text and p.text.strip()
            ]
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
            "message": f"Gagal mengekstrak konten teks dari '{url}' (status code: {status_code}). Web mungkin memblokir akses atau memerlukan login.",
        }

    if len(text) > max_length:
        text = (
            text[:max_length]
            + "\n\n...[Konten web dipotong sesuai batas panjang maksimal]"
        )

    return {
        "status": "success",
        "url": url,
        "engine": engine_used,
        "length": len(text),
        "content": text,
    }


@register_tool(category="web")
def audit_website_security(target_url: str) -> dict[str, Any]:
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
