"""Accessibility snapshot and element-reference helpers."""

from __future__ import annotations

import logging
import re
from typing import Any

from alfa.tools.web.browser.state import _INTERACTIVE_SEL, _MAX_REFS

logger = logging.getLogger("AgentTools.Web.Browser")

def _normalize_url(url: str) -> str:
    u = (url or "").strip()
    if not u:
        return u
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", u):
        u = "https://" + u
    return u


def _snapshot(page) -> tuple[list[dict[str, Any]], str]:
    """Ambil daftar elemen interaktif + teks deskripsi berformat ref."""
    try:
        raw = page.evaluate(
            """(sel) => Array.from(document.querySelectorAll(sel))
                    .slice(0, 80)
                    .map((el, i) => {
                        const r = el.getBoundingClientRect();
                        const st = getComputedStyle(el);
                        const visible = !!(r.width || r.height)
                            && st.visibility !== 'hidden' && st.display !== 'none';
                        const txt = (el.innerText || el.value
                            || el.getAttribute('aria-label')
                            || el.getAttribute('placeholder')
                            || el.getAttribute('title') || '')
                            .trim().replace(/\\s+/g, ' ');
                        return {
                            i, tag: el.tagName.toLowerCase(),
                            text: txt.slice(0, 90),
                            href: (el.getAttribute('href') || '').slice(0, 120),
                            type: el.getAttribute('type') || '',
                            name: (el.getAttribute('name')
                                || el.getAttribute('id') || '').slice(0, 40),
                            visible,
                        };
                    })""",
            _INTERACTIVE_SEL,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("Snapshot DOM gagal: %s", e)
        raw = []

    elements = [el for el in (raw or []) if el.get("visible")][:_MAX_REFS]
    lines: list[str] = []
    for n, el in enumerate(elements, start=1):
        label = el.get("text") or el.get("name") or el.get("href") or ""
        desc = f'e{n} <{el.get("tag", "?")}> "{label[:70]}"'
        if el.get("href"):
            desc += f" -> {el['href']}"
        lines.append(desc)
    return elements, "\n".join(lines) if lines else "(tidak ada elemen interaktif)"


def _page_summary(page) -> str:
    try:
        txt = page.inner_text("body")
    except Exception:  # noqa: BLE001
        try:
            txt = page.evaluate("() => document.body ? document.body.innerText : ''")
        except Exception:  # noqa: BLE001
            txt = ""
    return re.sub(r"\n{3,}", "\n\n", (txt or "")).strip()


def _ref_index(element_ref: str) -> int | None:
    m = re.fullmatch(r"\s*e(\d+)\s*", element_ref or "", re.IGNORECASE)
    if m:
        return int(m.group(1)) - 1
    if (element_ref or "").strip().isdigit():
        return int(element_ref.strip()) - 1
    return None


def _index_ok(idx: int | None, elements: list) -> bool:
    return idx is not None and 0 <= idx < len(elements)


