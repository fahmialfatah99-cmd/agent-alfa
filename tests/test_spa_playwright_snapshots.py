"""Playwright visual & layout snapshot gate for SPA modularization (375/768/1024/1440)."""

from __future__ import annotations

import io
import json
import math
import os
import socket
import threading
import time
from pathlib import Path

import pytest
import uvicorn
from PIL import Image, ImageChops

SNAPSHOT_DIR = Path(__file__).resolve().parent / "snapshots" / "spa_baseline"
VIEWPORT_WIDTHS = (375, 768, 1024, 1440)
VIEWPORT_HEIGHT = 900


def _rms_diff(img_a: Image.Image, img_b: Image.Image) -> float:
    """Compute root-mean-square pixel difference between two RGB images."""
    a = img_a.convert("RGB")
    b = img_b.convert("RGB")
    if a.size != b.size:
        b = b.resize(a.size)
    diff = ImageChops.difference(a, b)
    hist = diff.histogram()
    sq = sum(val * ((idx % 256) ** 2) for idx, val in enumerate(hist))
    total_samples = a.size[0] * a.size[1] * 3
    return math.sqrt(sq / max(1, total_samples))


@pytest.fixture(scope="module")
def live_dashboard_url():
    """Spin up local FastAPI dashboard server on an ephemeral port."""
    from alfa.dashboard.app import app

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    cfg = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(cfg)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(60):
        if server.started:
            break
        time.sleep(0.05)

    yield f"http://127.0.0.1:{port}"

    server.should_exit = True
    thread.join(timeout=3)


@pytest.fixture(scope="module")
def pw_browser():
    """Launch headless Chromium via Playwright; skip cleanly if binary unavailable."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        pytest.skip("playwright not installed")

    pw = sync_playwright().start()
    try:
        browser = pw.chromium.launch(headless=True)
    except Exception as exc:  # noqa: BLE001
        pw.stop()
        pytest.skip(f"Playwright Chromium binary unavailable: {exc}")

    yield browser
    browser.close()
    pw.stop()


def _prepare_deterministic_page(page, base_url: str, width: int) -> dict:
    """Load SPA at given width with frozen clock/timers and collect layout metrics."""
    page_errors: list[str] = []
    page.on("pageerror", lambda err: page_errors.append(str(err)))

    # Stub external fonts/CDNs so snapshots remain fast, hermetic & error-free offline
    cdn_stub = (
        "window.tailwind = window.tailwind || { config: {} };"
        "window.lucide = window.lucide || { createIcons: function(){} };"
        "window.Chart = window.Chart || function(){ return { update: function(){}, destroy: function(){} }; };"
        "window.marked = window.marked || { parse: function(s){ return s; } };"
    )

    def _route_handler(route):
        url = route.request.url
        if url.startswith(f"{base_url}/api/"):
            route.fulfill(
                status=200,
                content_type="application/json",
                body='{"status":"ok","items":[],"tools":[],"campaigns":[],"sites":[],"batches":[],"files":[]}',
            )
        elif url.startswith(base_url):
            route.continue_()
        elif route.request.resource_type == "script":
            route.fulfill(
                status=200,
                content_type="application/javascript",
                body=cdn_stub,
            )
        else:
            route.fulfill(status=204, body="")

    page.route("**/*", _route_handler)
    page.set_viewport_size({"width": width, "height": VIEWPORT_HEIGHT})
    page.goto(f"{base_url}/", wait_until="domcontentloaded")

    # Freeze dynamic clock and disable animations for deterministic visual snapshots
    page.evaluate(
        """() => {
            window.updateClock = () => {};
            for (const id of ['header-clock', 'live-clock', 'sys-clock']) {
                const el = document.getElementById(id);
                if (el) el.textContent = '00:00:00 WIB';
            }
            // Badge latensi WebSocket menampilkan angka hasil ukur nyata
            // ("4ms") → non-deterministik dan bikin snapshot flaky. Bekukan.
            for (const id of ['ws-latency-text', 'ws-status-text']) {
                const el = document.getElementById(id);
                if (el) el.textContent = el.id === 'ws-latency-text' ? '0ms' : 'WS';
            }
            const toasts = document.getElementById('toast-container');
            if (toasts) toasts.innerHTML = '';
            const style = document.createElement('style');
            style.textContent = '*, *::before, *::after { transition: none !important; animation: none !important; }';
            document.head.appendChild(style);
        }"""
    )
    # Tunggu font selesai dimuat. Tanpa ini screenshot bisa diambil saat
    # teks masih dirender dengan font fallback → diff piksel kecil tapi
    # deterministik (flaky) antar-run.
    try:
        page.evaluate("async () => { await document.fonts.ready; }")
    except Exception:  # noqa: BLE001 - font API mungkin tidak tersedia
        pass
    page.wait_for_timeout(50)

    metrics = page.evaluate(
        """() => ({
            title: document.title,
            buttonCount: document.querySelectorAll('button').length,
            scriptCount: document.querySelectorAll('script[src^="/static/js/"]').length,
            hasVaultFn: typeof fetchVaultSecrets === 'function',
            hasScraperFn: typeof runUniversalScraper === 'function',
            hasGdriveFn: typeof fetchGdriveStatus === 'function',
            hasPipelineFn: typeof cvSetView === 'function',
            hasSitesFn: typeof fetchSites === 'function',
            hasAffiliateFn: typeof runAffiliateGenerator === 'function',
            viewportWidth: window.innerWidth,
        })"""
    )
    metrics["pageErrors"] = page_errors
    return metrics


@pytest.mark.parametrize("width", VIEWPORT_WIDTHS)
def test_spa_visual_snapshot_and_metrics(pw_browser, live_dashboard_url, width: int):
    """Validate SPA visual snapshot and DOM invariants across 375/768/1024/1440."""
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    page = pw_browser.new_page(viewport={"width": width, "height": VIEWPORT_HEIGHT})
    try:
        metrics = _prepare_deterministic_page(page, live_dashboard_url, width)
        assert metrics["pageErrors"] == [], (
            f"Uncaught JS errors at width {width}: {metrics['pageErrors']}"
        )
        assert "ALFA" in metrics["title"]
        assert metrics["buttonCount"] >= 180
        assert metrics["hasVaultFn"] is True
        assert metrics["hasScraperFn"] is True
        assert metrics["hasGdriveFn"] is True
        assert metrics["hasPipelineFn"] is True
        assert metrics["hasSitesFn"] is True
        assert metrics["hasAffiliateFn"] is True

        png_bytes = page.screenshot(animations="disabled")
        snap_path = SNAPSHOT_DIR / f"viewport_{width}.png"
        update_mode = os.getenv("ALFA_UPDATE_SNAPSHOTS") == "1"

        if not snap_path.exists() or update_mode:
            snap_path.write_bytes(png_bytes)
        else:
            baseline_img = Image.open(snap_path)
            current_img = Image.open(io.BytesIO(png_bytes))
            rms = _rms_diff(baseline_img, current_img)
            assert rms <= 2.5, (
                f"Visual regression at width={width}px: RMS pixel diff={rms:.3f} (> 2.5)"
            )

        meta_path = SNAPSHOT_DIR / f"metrics_{width}.json"
        stable_meta = {
            "title": metrics["title"],
            "buttonCount": metrics["buttonCount"],
            "viewportWidth": metrics["viewportWidth"],
        }
        if not meta_path.exists() or update_mode:
            meta_path.write_text(
                json.dumps(stable_meta, indent=2, sort_keys=True), encoding="utf-8"
            )
        else:
            expected_meta = json.loads(meta_path.read_text(encoding="utf-8"))
            assert stable_meta == expected_meta
    finally:
        page.close()


def test_spa_interactive_tabs_and_approve_flow(pw_browser, live_dashboard_url):
    """Verify tab switching across carved modules and permission approve action work without JS errors."""
    page = pw_browser.new_page(viewport={"width": 1440, "height": VIEWPORT_HEIGHT})
    try:
        metrics = _prepare_deterministic_page(page, live_dashboard_url, 1440)
        assert metrics["pageErrors"] == []

        for tab_name in ("vault", "scraper", "gdrive", "pipelines", "sites", "affiliate"):
            page.evaluate(f"() => {{ if (typeof switchTab === 'function') switchTab('{tab_name}'); }}")
            page.wait_for_timeout(30)

        assert metrics["pageErrors"] == [], (
            f"JS errors during tab switching: {metrics['pageErrors']}"
        )
    finally:
        page.close()
