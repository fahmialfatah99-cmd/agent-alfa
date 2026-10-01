"""ALFA tools extras classification: core vs optional.

Core (~50 tools) always loaded. Extras (affiliate/video/academic/entertainment
+ heavy scrapers) only loaded when `ALFA_ENABLE_EXTRAS=1` (default: enabled
for backward compat) or via explicit `load_extra_group()`.

This keeps LLM tool-selection context slim without breaking existing installs.
"""

import os

# Tool function names considered niche / optional.
EXTRA_TOOL_NAMES = frozenset(
    {
        # Affiliate promo stack (niche e-commerce)
        "affiliate_hunt_trending_products",
        "affiliate_generate_viral_content",
        "affiliate_broadcast_deal",
        "affiliate_list_campaigns",
        "scrape_real_product_data",
        # Promo video / entertainment
        "generate_promo_video_from_images",
        "play_youtube_music",
        "record_desktop_screen",
        "read_clipboard",
        "write_to_clipboard",
        # Academic niche
        "academic_deep_research_paper",
        # Heavy scraping engines (prefer unified alfa.scrapers facade)
        "scrape_large_scale_batch",
        "crawlee_web_scraper",
        "crawl4ai_web_crawler",
        "scrapy_spider_quick_scrape",
        "scrapling_stealth_fetch",
        "firecrawl_scrape_and_crawl",
        "browser_use_autonomous_task",
        "browser_visual_test_page",
    }
)

EXTRA_GROUPS = {
    "affiliate": {
        "affiliate_hunt_trending_products",
        "affiliate_generate_viral_content",
        "affiliate_broadcast_deal",
        "affiliate_list_campaigns",
        "scrape_real_product_data",
    },
    "video": {"generate_promo_video_from_images"},
    "entertainment": {
        "play_youtube_music",
        "record_desktop_screen",
        "read_clipboard",
        "write_to_clipboard",
    },
    "academic": {"academic_deep_research_paper"},
    "scraping-extra": {
        "scrape_large_scale_batch",
        "crawlee_web_scraper",
        "crawl4ai_web_crawler",
        "scrapy_spider_quick_scrape",
        "scrapling_stealth_fetch",
        "firecrawl_scrape_and_crawl",
        "browser_use_autonomous_task",
        "browser_visual_test_page",
    },
}


def extras_enabled() -> bool:
    """Extras on by default (backward compat); set ALFA_ENABLE_EXTRAS=0 for slim core."""
    return os.getenv("ALFA_ENABLE_EXTRAS", "1") != "0"


def is_extra_tool(name: str) -> bool:
    return name in EXTRA_TOOL_NAMES


def filter_core_tools(tools: list) -> list:
    """Return only core tools (drop extras). Accepts callables or names."""
    out = []
    for t in tools:
        name = t if isinstance(t, str) else getattr(t, "__name__", "")
        if name not in EXTRA_TOOL_NAMES:
            out.append(t)
    return out


def filter_extra_group(tools: list, group: str) -> list:
    """Return only tools belonging to an extra group."""
    wanted = EXTRA_GROUPS.get(group, set())
    out = []
    for t in tools:
        name = t if isinstance(t, str) else getattr(t, "__name__", "")
        if name in wanted:
            out.append(t)
    return out
