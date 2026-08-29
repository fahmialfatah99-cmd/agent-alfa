#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║             ALFA INDUSTRIAL LARGE-SCALE FAST PRODUCT SCRAPER                 ║
║  High-Speed Async TLS + Camoufox Anti-Detect Browser Multi-Threaded Engine   ║
╚══════════════════════════════════════════════════════════════════════════════╝
Usage examples:
  python3 large_scale_scraper.py --query "powerbank fast charging" --platform shopee --limit 20
  python3 large_scale_scraper.py --urls "https://example.com/item1" "https://example.com/item2"
  python3 large_scale_scraper.py --file list_urls.txt --concurrency 25 --engine fast_tls
"""

import argparse
import sys

import fast_scraper


def main():
    parser = argparse.ArgumentParser(description="ALFA Industrial High-Speed Product Scraper")
    parser.add_argument("--query", "-q", type=str, help="Search query on marketplace (e.g. 'powerbank fast charging')")
    parser.add_argument("--platform", "-p", type=str, default="shopee", choices=["shopee", "tokopedia", "tiktok", "lazada", "general"], help="Target platform")
    parser.add_argument("--urls", "-u", nargs="+", help="List of URLs to scrape directly")
    parser.add_argument("--file", "-f", type=str, help="Text file containing list of URLs (one per line)")
    parser.add_argument("--engine", "-e", type=str, default="auto", choices=["auto", "fast_tls", "camoufox"], help="Scraping engine")
    parser.add_argument("--concurrency", "-c", type=int, default=15, help="Number of concurrent workers (default: 15)")
    parser.add_argument("--limit", "-l", type=int, default=20, help="Max items for query search (default: 20)")
    parser.add_argument("--name", "-n", type=str, default="product_batch", help="Batch export name")

    args = parser.parse_args()

    print("=" * 75)
    print("🚀 ALFA HIGH-SPEED SCRAPER INITIALIZED")
    print(f"Engine: {args.engine.upper()} | Concurrency: {args.concurrency}")
    print("=" * 75)

    if args.query:
        print(f"\n🔍 Searching & Scraping Marketplace: '{args.query}' on {args.platform.upper()} (Max: {args.limit})...")
        res = fast_scraper.search_and_scrape_marketplace(args.query, platform=args.platform, max_items=args.limit)
        print(f"✅ Total Scraped: {res['total_scraped']} products")
        for idx, p in enumerate(res['products'][:5], 1):
            print(f"  [{idx}] {p['title'][:50]}... | {p['price']} | ⭐ {p['rating']}")
        if len(res['products']) > 5:
            print(f"  ... dan {len(res['products']) - 5} produk lainnya.")
        return

    urls = []
    if args.urls:
        urls.extend(args.urls)
    elif args.file:
        try:
            with open(args.file, "r", encoding="utf-8") as f:
                urls = [line.strip() for line in f if line.strip() and not line.startswith("#")]
        except Exception as e:
            print(f"❌ Error reading URL file: {e}")
            sys.exit(1)

    if not urls:
        print("⚠️ Mohon berikan argumen --query 'nama produk' atau --urls <url1> <url2> atau --file <file.txt>")
        parser.print_help()
        sys.exit(1)

    print(f"\n⚡ Scraping {len(urls)} URLs with Concurrency={args.concurrency}...")
    use_camoufox = (args.engine == "camoufox")
    res = fast_scraper.run_batch_scrape(
        urls=urls,
        batch_name=args.name,
        max_concurrency=args.concurrency,
        use_camoufox=use_camoufox
    )

    print("\n" + "=" * 75)
    print("📊 BATCH SCRAPING COMPLETED")
    print(f"Batch ID: {res['batch_id']}")
    print(f"Total Requests: {res['total_requested']} | Sukses: {res['total_successful']} | Gagal: {res['total_failed']}")
    print(f"Waktu Total: {res['duration_seconds']}s | Kecepatan: {res['speed_urls_per_sec']} URLs/detik")
    print(f"📂 Ekspor JSON: {res['json_export_path']}")
    print(f"📂 Ekspor CSV:  {res['csv_export_path']}")
    print(f"🗄️ Database Saved: {res['db_saved_count']} baris di agent_data.db")
    print("=" * 75)


if __name__ == "__main__":
    main()
