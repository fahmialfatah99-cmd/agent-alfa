"""Public browser tools (open, click, type, screenshot, tasks)."""

from __future__ import annotations

import logging
import os
from typing import Any

from alfa.tools.registry import register_tool
from alfa.tools.system_tools import SANDBOX_DIR
from alfa.tools.web.browser.engine import (
    _close_browser,
    _ensure_page,
    _on_browser_thread,
)
from alfa.tools.web.browser.planner import _heuristic_plan, _plan_next_action
from alfa.tools.web.browser.scrapling_fallback import _scrapling_snapshot
from alfa.tools.web.browser.snapshot import (
    _index_ok,
    _normalize_url,
    _page_summary,
    _ref_index,
    _snapshot,
)
from alfa.tools.web.browser.state import _INTERACTIVE_SEL, _LOCK, _STATE
from alfa.tools.web.search import fetch_web_page_content, web_search
from alfa.tools.web.visual_tester import (
    browser_visual_test_page as browser_visual_test_page,
)

logger = logging.getLogger("AgentTools.Web.Browser")


# ── tools ───────────────────────────────────────────────────────────────────
@register_tool(category="web")
@_on_browser_thread
def browser_open_url(url: str) -> dict[str, Any]:
    """
    Open a web page in the persistent Camoufox stealth browser and return its interactive element snapshot.

    Use this tool when the user asks to open a website, browse a web page, fill forms, or inspect web elements.

    Args:
        url: Full web URL to open (e.g. 'https://github.com/trending', 'https://news.ycombinator.com').
    """
    target = _normalize_url(url)
    if not target:
        return {"status": "error", "message": "URL kosong."}
    try:
        with _LOCK:
            page = _ensure_page()
            if page is not None:
                page.goto(target, wait_until="domcontentloaded", timeout=45000)
                try:
                    page.wait_for_timeout(600)
                except Exception:  # noqa: BLE001
                    pass
                elements, desc = _snapshot(page)
                _STATE["elements"] = elements
                return {
                    "status": "success",
                    "engine": "camoufox_python",
                    "message": f"Halaman '{target}' terbuka (title: {page.title()}).",
                    "url": page.url,
                    "interactive_elements": desc[:6000],
                }
        logger.info("Camofox tak tersedia -> fallback parser DOM untuk %s", target)
        snap = _scrapling_snapshot(target)
        return {
            "status": "success",
            "engine": "scrapling_stealth_fallback",
            "message": f"Halaman '{target}' dianalisis lewat parser DOM (tanpa browser aktif).",
            "url": target,
            "interactive_elements": snap["interactive_elements"],
            "page_content_preview": snap["page_content_preview"],
        }
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "message": f"Browser open error: {str(e)}"}


@register_tool(category="web")
@_on_browser_thread
def browser_click_element(element_ref: str, tab_id: str = "") -> dict[str, Any]:
    """
    Click an interactive button, link, checkbox, or element on the active browser page by its reference (e.g. 'e1', 'e12').

    Args:
        element_ref: Element ref identifier (e.g. 'e1', 'e2', 'e15') from the browser snapshot, or a CSS selector.
        tab_id: Optional specific tab ID (ignored, single persistent tab).
    """
    try:
        with _LOCK:
            page = _ensure_page()
            if page is None:
                return {
                    "status": "error",
                    "message": "Browser tidak aktif. Jalankan browser_open_url dulu.",
                }
            elements = _STATE.get("elements") or []
            idx = _ref_index(element_ref)
            try:
                if _index_ok(idx, elements):
                    page.locator(_INTERACTIVE_SEL).nth(idx).click(timeout=8000)
                else:
                    page.locator(element_ref).first.click(timeout=8000)
            except Exception as ce:  # noqa: BLE001
                return {
                    "status": "error",
                    "message": f"Gagal klik '{element_ref}': {ce}",
                }
            page.wait_for_timeout(900)
            elements, desc = _snapshot(page)
            _STATE["elements"] = elements
            return {
                "status": "success",
                "message": f"Elemen '{element_ref}' diklik.",
                "url": page.url,
                "updated_page_elements": desc[:5000],
            }
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "message": str(e)}


@register_tool(category="web")
@_on_browser_thread
def browser_type_text(element_ref: str, text: str, tab_id: str = "") -> dict[str, Any]:
    """
    Type text into an input field or search bar on the active browser page.

    Args:
        element_ref: Element ref identifier (e.g. 'e3') or CSS selector of the input field.
        text: String text to type into the input field.
        tab_id: Optional specific tab ID (ignored, single persistent tab).
    """
    try:
        with _LOCK:
            page = _ensure_page()
            if page is None:
                return {
                    "status": "error",
                    "message": "Browser tidak aktif. Jalankan browser_open_url dulu.",
                }
            elements = _STATE.get("elements") or []
            idx = _ref_index(element_ref)
            try:
                if _index_ok(idx, elements):
                    loc = page.locator(_INTERACTIVE_SEL).nth(idx)
                else:
                    loc = page.locator(element_ref).first
                loc.fill(str(text), timeout=8000)
            except Exception:  # noqa: BLE001
                try:
                    loc.click(timeout=5000)
                    loc.press_sequentially(str(text), delay=25)
                except Exception as te:  # noqa: BLE001
                    return {
                        "status": "error",
                        "message": f"Gagal mengetik ke '{element_ref}': {te}",
                    }
            page.wait_for_timeout(500)
            return {
                "status": "success",
                "message": f"Teks diketik ke elemen '{element_ref}'.",
                "url": page.url,
            }
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "message": str(e)}


@register_tool(category="web")
@_on_browser_thread
def browser_capture_screenshot(tab_id: str = "") -> dict[str, Any]:
    """
    Take a screenshot of the current browser page (saved into the workspace and ready to send to chat).

    Args:
        tab_id: Optional specific tab ID (ignored, single persistent tab).
    """
    try:
        with _LOCK:
            page = _ensure_page()
            if page is None:
                return {
                    "status": "error",
                    "message": "Browser tidak aktif. Jalankan browser_open_url dulu.",
                }
            os.makedirs(SANDBOX_DIR, exist_ok=True)
            target_path = os.path.join(SANDBOX_DIR, "browser_screenshot.png")
            page.screenshot(path=target_path, full_page=False)
            return {
                "status": "success",
                "message": "Screenshot browser berhasil diambil.",
                "file_path": target_path,
                "url": page.url,
            }
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "message": str(e)}


@register_tool(category="web")
@_on_browser_thread
def browser_close_tab(tab_id: str = "") -> dict[str, Any]:
    """
    Close the active browser tab / shut down the persistent browser session.

    Args:
        tab_id: Optional specific tab ID (ignored, closes the active session).
    """
    try:
        _close_browser()
        return {
            "status": "success",
            "message": "Sesi browser ditutup.",
        }
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "message": str(e)}


@register_tool(category="web")
@_on_browser_thread
def browser_use_autonomous_task(
    task_instruction: str, start_url: str = "https://www.google.com", max_steps: int = 5
) -> dict[str, Any]:
    """
    AUTONOMOUS BROWSER AGENT: opens the real browser, inspects the live page, and plans+executes click/type/scroll/goto steps until the goal is reached.

    Args:
        task_instruction: Detailed goal description (e.g. 'Search for latest AI news on Google and summarize top 3 headlines').
        start_url: Entrypoint URL to navigate to (default 'https://www.google.com').
        max_steps: Maximum autonomous steps allowed (default 5, max 12).
    """
    task = (task_instruction or "").strip()
    if not task:
        return {"status": "error", "message": "task_instruction kosong."}
    cap = max(1, min(int(max_steps or 5), 12))
    history: list[str] = []
    steps: list[dict[str, Any]] = []

    try:
        with _LOCK:
            page = _ensure_page()
            if page is None:
                # Jujur: otomasi visual tidak mungkin tanpa engine.
                # Bantu pengguna dengan riset berbasis teks sebagai gantinya.
                logger.warning("Camofox tak tersedia -> fallback riset teks")
                return _research_fallback(task, start_url)

            try:
                page.goto(
                    _normalize_url(start_url),
                    wait_until="domcontentloaded",
                    timeout=45000,
                )
                page.wait_for_timeout(800)
            except Exception as ge:  # noqa: BLE001
                history.append(f"goto gagal: {ge}")

            done = False
            note = ""
            for i in range(cap):
                if page.is_closed():
                    break
                elements, snap_text = _snapshot(page)
                _STATE["elements"] = elements
                try:
                    plan = _plan_next_action(task, page.url, snap_text, history, i, cap)
                except Exception as pe:  # noqa: BLE001
                    note = f"planner LLM gagal -> heuristik: {str(pe)[:140]}"
                    logger.warning("%s", note)
                    plan = _heuristic_plan(task, elements, cap)

                action = plan["action"]
                reason = str(plan.get("reason") or "")[:160]
                entry: dict[str, Any] = {
                    "step": i + 1,
                    "action": action,
                    "reason": reason,
                }
                try:
                    if action == "done":
                        done = True
                        entry["result"] = "target dianggap tercapai"
                        steps.append(entry)
                        break
                    if action == "click":
                        ref = str(plan.get("ref") or "")
                        entry["ref"] = ref
                        idx = _ref_index(ref)
                        if _index_ok(idx, elements):
                            page.locator(_INTERACTIVE_SEL).nth(idx).click(timeout=8000)
                            entry["result"] = "diklik"
                        else:
                            entry["result"] = f"ref '{ref}' tidak valid"
                    elif action == "type":
                        ref = str(plan.get("ref") or "")
                        val = str(plan.get("text") or "")
                        entry["ref"] = ref
                        entry["text"] = val[:80]
                        idx = _ref_index(ref)
                        loc = (
                            page.locator(_INTERACTIVE_SEL).nth(idx)
                            if _index_ok(idx, elements)
                            else page.locator(ref).first
                        )
                        loc.fill(val, timeout=8000)
                        entry["result"] = "terisi"
                    elif action == "scroll":
                        page.evaluate("() => window.scrollBy(0, 1200)")
                        entry["result"] = "scroll down"
                    elif action == "goto":
                        target = _normalize_url(str(plan.get("url") or ""))
                        entry["url"] = target
                        page.goto(target, wait_until="domcontentloaded", timeout=45000)
                        entry["result"] = "navigasi"
                    page.wait_for_timeout(1000)
                except Exception as ae:  # noqa: BLE001
                    entry["result"] = f"ERROR: {ae}"
                steps.append(entry)
                history.append(f"{action}:{entry.get('result', '')}")

            body_preview = _page_summary(page)[:4000]
            return {
                "status": "success" if done else "partial",
                "engine": "camoufox_python",
                "task": task,
                "start_url": start_url,
                "final_url": page.url,
                "final_title": page.title(),
                "steps_completed": len(steps),
                "max_steps": cap,
                "steps": steps,
                "page_text_preview": body_preview,
                "final_summary": (
                    f"Otomasi browser '{task}' selesai dalam {len(steps)} langkah "
                    f"pada {page.url}."
                    if done
                    else f"Otomasi browser '{task}' berhenti setelah {len(steps)} langkah "
                    f"(target belum pasti tercapai).{(' ' + note) if note else ''}"
                ),
            }
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "message": f"Browser autonomous error: {str(e)}"}


def _research_fallback(task: str, start_url: str) -> dict[str, Any]:
    """Riset berbasis teks ketika engine browser tak tersedia — jujur soal keterbatasannya."""
    try:
        search_res = web_search(query=task, max_results=5)
    except Exception as e:  # noqa: BLE001
        return {
            "status": "error",
            "message": (
                f"Otomasi browser visual tidak tersedia (Camofox gagal diluncurkan) "
                f"dan riset teks juga gagal: {e}"
            ),
        }
    insights = []
    if search_res.get("status") == "success":
        for item in (search_res.get("results") or [])[:4]:
            link = item.get("link")
            if not link:
                continue
            try:
                page_data = fetch_web_page_content(url=link, max_length=1200)
            except Exception:  # noqa: BLE001
                page_data = {}
            insights.append(
                {
                    "title": item.get("title"),
                    "link": link,
                    "content_snippet": (page_data.get("content") or "")[:500],
                }
            )
    return {
        "status": "partial",
        "engine": "text_research_fallback",
        "task": task,
        "start_url": start_url,
        "steps_completed": len(insights),
        "steps": [
            {"step": i + 1, "action": "fetch", "ref": it.get("link")}
            for i, it in enumerate(insights)
        ],
        "insights_gathered": insights,
        "final_summary": (
            "Engine browser visual TIDAK aktif, jadi tugas dijalankan lewat riset "
            f"teks (web_search + fetch) menghasilkan {len(insights)} sumber. "
            "Untuk klik/form otomatis, jalankan `camoufox fetch` lalu ulangi."
        ),
    }
