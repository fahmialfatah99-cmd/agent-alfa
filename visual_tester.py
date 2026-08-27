"""
AUTOMATED VISUAL TESTING & CONSOLE AUDIT ENGINE.
Uses Camoufox / Playwright headless browser to:
- browser_visual_test_page: Load webpage, capture console errors, network failures, responsive screenshots, and detect layout overflow bugs.
"""

import os
import time
import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("VisualTester")

SWARM_OUTPUT_DIR = os.path.expanduser("~/Dokumen/ALFA_SWARM_OUTPUTS")
os.makedirs(SWARM_OUTPUT_DIR, exist_ok=True)


def browser_visual_test_page(
    url: str,
    viewports: str = "desktop,mobile",
    wait_seconds: int = 2,
    output_prefix: str = "visual_test"
) -> Dict[str, Any]:
    """
    AUTOMATED VISUAL TESTER: Perform headless browser visual inspection and console log audit on a web page.
    Captures screenshots for Desktop & Mobile, audits JavaScript console errors, and detects horizontal layout overflow.

    Args:
        url: URL of the web application (e.g. 'http://localhost:8080', 'http://localhost:3000', or any website).
        viewports: Comma-separated viewports: 'desktop' (1920x1080), 'tablet' (768x1024), 'mobile' (390x844).
        wait_seconds: Seconds to wait after page load before taking screenshot (default 2).
        output_prefix: Filename prefix for generated screenshot images.
    """
    try:
        from camoufox.sync_api import Camoufox
    except ImportError:
        return {"status": "error", "message": "Camoufox / Playwright browser engine tidak terinstall."}

    viewport_map = {
        "desktop": {"width": 1920, "height": 1080},
        "tablet": {"width": 768, "height": 1024},
        "mobile": {"width": 390, "height": 844}
    }

    requested_views = [v.strip().lower() for v in viewports.split(",") if v.strip().lower() in viewport_map]
    if not requested_views:
        requested_views = ["desktop", "mobile"]

    console_errors: List[str] = []
    console_logs: List[str] = []
    failed_requests: List[Dict[str, Any]] = []
    screenshots_taken: List[Dict[str, str]] = []
    overflow_issues: List[str] = []

    timestamp = int(time.time())

    try:
        with Camoufox(headless=True) as browser:
            for view_name in requested_views:
                v_cfg = viewport_map[view_name]
                context = browser.new_context(
                    viewport={"width": v_cfg["width"], "height": v_cfg["height"]}
                )
                page = context.new_page()

                # Listen to console
                def _handle_console(msg):
                    if msg.type == "error":
                        console_errors.append(f"[{view_name}] [CONSOLE ERROR] {msg.text}")
                    elif msg.type in ("warn", "warning"):
                        console_logs.append(f"[{view_name}] [WARN] {msg.text}")

                page.on("console", _handle_console)
                page.on("pageerror", lambda err: console_errors.append(f"[{view_name}] [PAGE EXCEPTION] {str(err)}"))

                # Listen to failed network requests
                def _handle_response(resp):
                    if resp.status >= 400:
                        failed_requests.append({
                            "view": view_name,
                            "url": resp.url[:120],
                            "status": resp.status,
                            "status_text": resp.status_text
                        })

                page.on("response", _handle_response)

                try:
                    page.goto(url, timeout=20000, wait_until="load")
                except Exception as e:
                    page.goto(url, timeout=20000)

                time.sleep(wait_seconds)

                # Check horizontal overflow bug
                has_overflow = page.evaluate("() => document.documentElement.scrollWidth > window.innerWidth")
                if has_overflow:
                    overflow_issues.append(f"{view_name.upper()} (scrollWidth > innerWidth: elemen meluap secara horizontal)")

                # Take screenshot
                img_filename = f"{output_prefix}_{view_name}_{timestamp}.png"
                img_path = os.path.join(SWARM_OUTPUT_DIR, img_filename)
                page.screenshot(path=img_path, full_page=True)

                screenshots_taken.append({
                    "view": view_name,
                    "resolution": f"{v_cfg['width']}x{v_cfg['height']}",
                    "filename": img_filename,
                    "path": img_path
                })
                context.close()

        has_issues = bool(console_errors or failed_requests or overflow_issues)
        return {
            "status": "success",
            "url": url,
            "page_title": screenshots_taken[0].get("view", ""),
            "has_visual_issues": has_issues,
            "console_errors_count": len(console_errors),
            "console_errors": console_errors[:10],
            "failed_network_requests_count": len(failed_requests),
            "failed_network_requests": failed_requests[:10],
            "layout_overflow_issues": overflow_issues,
            "screenshots": screenshots_taken,
            "message": (
                f"Pengujian visual selesai! {len(screenshots_taken)} screenshot tersimpan di ~/Dokumen/ALFA_SWARM_OUTPUTS. "
                f"Ditemukan {len(console_errors)} error console dan {len(overflow_issues)} isu overflow layout."
            )
        }
    except Exception as e:
        logger.error(f"Visual test error: {e}")
        return {"status": "error", "message": f"Visual test gagal: {str(e)}"}
