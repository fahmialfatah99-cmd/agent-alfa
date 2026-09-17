"""Web search, scraping, browser automation, and affiliate tools."""

from alfa.tools.web.affiliate import (
    affiliate_broadcast_deal,
    affiliate_generate_viral_content,
    affiliate_hunt_trending_products,
    affiliate_list_campaigns,
    marketplace_search_products,
)
from alfa.tools.web.browser import (
    _ensure_camofox_server,
    _find_camofox_bin,
    _run_camofox_cli,
    browser_capture_screenshot,
    browser_click_element,
    browser_close_tab,
    browser_open_url,
    browser_type_text,
    browser_use_autonomous_task,
    browser_visual_test_page,
)
from alfa.tools.web.scrapers import (
    crawl4ai_web_crawler,
    crawlee_web_scraper,
    firecrawl_scrape_and_crawl,
    scrape_custom_urls_batch,
    scrape_large_scale_batch,
    scrape_real_product_data,
    scrapling_stealth_fetch,
    scrapy_spider_quick_scrape,
    universal_deep_scraper,
)
from alfa.tools.web.search import (
    audit_website_security,
    fetch_web_page_content,
    web_search,
)

__all__ = [
    "web_search",
    "fetch_web_page_content",
    "audit_website_security",
    "_find_camofox_bin",
    "_ensure_camofox_server",
    "_run_camofox_cli",
    "browser_open_url",
    "browser_click_element",
    "browser_type_text",
    "browser_capture_screenshot",
    "browser_close_tab",
    "browser_use_autonomous_task",
    "browser_visual_test_page",
    "scrapling_stealth_fetch",
    "scrapy_spider_quick_scrape",
    "crawlee_web_scraper",
    "crawl4ai_web_crawler",
    "firecrawl_scrape_and_crawl",
    "universal_deep_scraper",
    "scrape_custom_urls_batch",
    "scrape_real_product_data",
    "scrape_large_scale_batch",
    "marketplace_search_products",
    "affiliate_hunt_trending_products",
    "affiliate_generate_viral_content",
    "affiliate_broadcast_deal",
    "affiliate_list_campaigns",
]
