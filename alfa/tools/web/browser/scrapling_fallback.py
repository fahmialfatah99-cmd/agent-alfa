"""Stealth-fetch fallback when the browser cannot launch."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("AgentTools.Web.Browser")


# ── scrapling fallback (browser tak bisa diluncurkan) ───────────────────────
def _scrapling_snapshot(url: str) -> dict[str, Any]:
    from scrapling import Fetcher, StealthyFetcher

    try:
        page = StealthyFetcher.fetch(url)
    except Exception:  # noqa: BLE001
        page = Fetcher.get(url, timeout=15)

    interactive: list[str] = []
    for i, a in enumerate(page.css("a[href]")[:25]):
        href = a.get_attribute("href") or ""
        txt = a.text.strip() if hasattr(a, "text") else "[Link]"
        interactive.append(f'e{i + 1} <a> "{txt[:40]}" -> {href[:80]}')
    off = len(interactive)
    for i, btn in enumerate(page.css("button, input[type=submit]")[:15]):
        txt = (
            (btn.text.strip() if hasattr(btn, "text") else "")
            or btn.get_attribute("value")
            or "[Button]"
        )
        interactive.append(f'e{off + i + 1} <button> "{txt[:40]}"')
    body_text = "\n".join(
        [
            p.text.strip()
            for p in page.css("h1, h2, h3, p, article")
            if hasattr(p, "text") and p.text and p.text.strip()
        ][:12]
    )
    return {
        "interactive_elements": "\n".join(interactive)
        or "(tidak ada elemen interaktif)",
        "page_content_preview": body_text[:2500],
    }
