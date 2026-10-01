"""ALFA Scrapers: Multi-tier stealth web scraping & crawling engines.

Unified entry: `fast` (single/batch marketplace), `universal` (generic),
`large_scale` (CLI batch wrapper around `fast`).
Heavy third-party engines (scrapy/crawlee/crawl4ai/scrapling/firecrawl)
are optional extras: `pip install alfa-ai[scraping-extra]`.
"""

from alfa.scrapers import fast, large_scale, universal

__all__ = ["fast", "universal", "large_scale"]
