"""ALFA Scrapers: Multi-tier stealth web scraping & crawling engines."""
import sys
from pathlib import Path
root_dir = str(Path(__file__).resolve().parents[2])
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

try:
    import universal_scraper
    import fast_scraper
    import large_scale_scraper
except ImportError:
    pass
