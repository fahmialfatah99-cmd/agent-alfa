"""Browser automation via the Python Camoufox engine (stealth Firefox).

Mesin: `camoufox.sync_api` (terpasang via `camoufox fetch`). Browser dijalankan
SEBAGAI PROSES PERSISTEN di memori module sehingga state antar tool call
(halaman aktif, daftar elemen `e1..eN`) tetap hidup.

Node CLI `camofox` lama sudah tidak bisa dipakai ("installed Camoufox version
could not be determined"), jadi semua tool di sini diarahkan ke engine Python.
"""

from __future__ import annotations

import atexit
import concurrent.futures
import functools
import json
import logging
import os
import re
import threading
from collections.abc import Callable
from typing import Any, TypeVar

from alfa.tools.registry import register_tool
from alfa.tools.system_tools import SANDBOX_DIR
from alfa.tools.web.search import fetch_web_page_content, web_search
from alfa.tools.web.visual_tester import (
    browser_visual_test_page as browser_visual_test_page,
)

logger = logging.getLogger("AgentTools.Web.Browser")

_INTERACTIVE_SEL = (
    "a[href], button, input, textarea, select, "
    "[role=button], [role=link], [role=tab], [role=menuitem], [onclick]"
)
_MAX_REFS = 60
_LOCK = threading.RLock()
_STATE: dict[str, Any] = {"ctx": None, "page": None, "elements": []}
_AT_EXIT_DONE = False


# ── engine ──────────────────────────────────────────────────────────────────
def _headless() -> bool:
    return (
        os.getenv("ALFA_BROWSER_HEADLESS", "true").strip().lower()
        not in ("0", "false", "off", "no")
    )


_T = TypeVar("_T")
_UI_POOL: concurrent.futures.ThreadPoolExecutor | None = None
_UI_POOL_LOCK = threading.Lock()


def _ui(fn: Callable[..., _T], *args: Any, timeout: float = 240.0, **kwargs: Any) -> _T:
    """Jalankan operasi browser di SATU thread khusus.

    Playwright/Camoufox sync API hanya aman dipakai dari thread yang sama dengan
    thread pembuatnya, dan engine-nya meninggalkan 'running loop' di thread
    pemanggil. Tanpa thread khusus ini, satu tool call merusak event loop milik
    pemanggil (asyncio.run() di test/bot jadi 'cannot be called from a running
    event loop').
    """
    global _UI_POOL
    with _UI_POOL_LOCK:
        if _UI_POOL is None:
            _UI_POOL = concurrent.futures.ThreadPoolExecutor(
                max_workers=1, thread_name_prefix="alfa-browser"
            )
    fut = _UI_POOL.submit(fn, *args, **kwargs)
    return fut.result(timeout=timeout)


def _on_browser_thread(fn: Callable) -> Callable:
    """Decorator: seluruh tubuh tool dijalankan di thread browser tunggal."""

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        return _ui(fn, *args, **kwargs)

    return wrapper


def _shutdown_browser() -> None:
    """Tutup browser + thread worker saat interpreter berhenti."""
    global _UI_POOL
    pool = _UI_POOL
    if pool is None:
        _close_browser()
        return
    try:
        pool.submit(_close_browser).result(timeout=15)
    except Exception:  # noqa: BLE001
        pass
    try:
        pool.shutdown(wait=False, cancel_futures=True)
    except Exception:  # noqa: BLE001
        pass
    _UI_POOL = None


def _close_browser() -> None:
    global _AT_EXIT_DONE
    with _LOCK:
        ctx = _STATE.get("ctx")
        _STATE["ctx"] = None
        _STATE["page"] = None
        _STATE["elements"] = []
    if ctx is not None:
        try:
            ctx.__exit__(None, None, None)
        except Exception:  # noqa: BLE001
            pass
    if not _AT_EXIT_DONE:
        _AT_EXIT_DONE = True


def _ensure_page():
    """Kembalikan page Camoufox aktif, launch bila belum ada. None bila gagal."""
    global _AT_EXIT_DONE
    with _LOCK:
        page = _STATE.get("page")
        if page is not None:
            try:
                if not page.is_closed():
                    return page
            except Exception:  # noqa: BLE001
                pass
            _STATE["page"] = None

        try:
            from camoufox.sync_api import Camoufox

            ctx = Camoufox(headless=_headless(), humanize=False, enable_cache=True)
            browser = ctx.__enter__()
            page = browser.new_page()
            page.set_default_timeout(20000)
            _STATE["ctx"] = ctx
            _STATE["page"] = page
            _STATE["elements"] = []
            if not _AT_EXIT_DONE:
                atexit.register(_shutdown_browser)
                _AT_EXIT_DONE = True
            logger.info("Camoufox engine diluncurkan (headless=%s)", _headless())
            return page
        except Exception as e:  # noqa: BLE001
            logger.error("Gagal meluncurkan Camoufox: %s", e)
            _STATE["ctx"] = None
            _STATE["page"] = None
            return None


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


# ── LLM planner (sinkron, dipanggil dari thread tool) ───────────────────────
_MODEL_CACHE: list[str] = []


def _candidate_models(cfg: dict[str, Any]) -> list[str]:
    """Urutan model: yang terkonfigurasi dulu, lalu cadangan dari .env."""
    out: list[str] = []
    for m in _MODEL_CACHE + [
        cfg.get("model") or "",
        os.getenv("GEMINI_MODEL", "").strip(),
        "gemini-3.5-flash-lite",
    ]:
        if m and m not in out:
            out.append(m)
    return out


def _remember_model(model: str) -> None:
    """Catat model yang terbukti jalan agar langkah berikutnya tidak kena 429 lagi."""
    if model in _MODEL_CACHE:
        _MODEL_CACHE.remove(model)
    _MODEL_CACHE.insert(0, model)


def _llm_complete(prompt: str, system: str, timeout: float = 25.0) -> str:
    from alfa.core import brain

    cfg = brain.get_main_brain() or {}
    provider = (cfg.get("provider") or "").lower()
    key = cfg.get("api_key") or ""
    if not key:
        raise RuntimeError("konfigurasi LLM (api key) tidak tersedia")

    last_err: Exception | None = None

    if "gemini" in provider or provider in ("google", "vertex"):
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=key)
        for model in _candidate_models(cfg):
            try:
                resp = client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=system,
                        temperature=0.1,
                        max_output_tokens=700,
                    ),
                )
                if resp.text:
                    _remember_model(model)
                    return resp.text.strip()
            except Exception as e:  # noqa: BLE001
                last_err = e
                logger.info("planner model %s gagal (%s) -> coba cadangan", model, e)
        raise last_err or RuntimeError("semua model Gemini gagal")

    import httpx

    base = (cfg.get("base_url") or "").rstrip("/")
    if not base:
        raise RuntimeError("provider non-gemini tanpa base_url")
    for model in _candidate_models(cfg):
        try:
            r = httpx.post(
                f"{base}/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.1,
                    "max_tokens": 700,
                },
                timeout=timeout,
            )
            if r.status_code >= 400:
                raise RuntimeError(f"HTTP {r.status_code}: {r.text[:160]}")
            text = (r.json()["choices"][0]["message"]["content"] or "").strip()
            if text:
                _remember_model(model)
                return text
        except Exception as e:  # noqa: BLE001
            last_err = e
            logger.info("planner model %s gagal (%s) -> coba cadangan", model, e)
    raise last_err or RuntimeError("semua model cadangan gagal")


_PLAN_SYSTEM = (
    "Kamu perencana otomasi browser. Balas HANYA JSON valid tanpa teks lain, "
    "tanpa markdown fence."
)


def _parse_json_obj(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    t = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    try:
        obj = json.loads(t)
        return obj if isinstance(obj, dict) else None
    except Exception:  # noqa: BLE001
        pass
    m = re.search(r"\{.*\}", t, re.DOTALL)
    if m:
        try:
            obj = json.loads(m.group(0))
            return obj if isinstance(obj, dict) else None
        except Exception:  # noqa: BLE001
            return None
    return None


_STOPWORDS = {
    "the", "and", "for", "with", "please", "open", "go", "find", "search",
    "look", "page", "website", "site", "web", "into", "from", "that", "this",
    "guna", "yang", "untuk", "dari", "dan", "atau", "buka", "cari", "halaman",
}


def _heuristic_plan(
    task: str, elements: list[dict[str, Any]], cap: int
) -> dict[str, Any]:
    """Rencana cadangan ketika planner LLM tidak bisa dipanggil (kuota/error)."""
    words = [
        w
        for w in re.findall(r"[a-zA-Z0-9_-]{3,}", (task or "").lower())
        if w not in _STOPWORDS
    ]
    best_i, best_score, best_word = -1, 0, ""
    for i, el in enumerate(elements):
        hay = " ".join(
            str(el.get(k) or "") for k in ("text", "href", "name", "type")
        ).lower()
        score = sum(1 for w in words if w in hay)
        if score > best_score:
            best_i, best_score, best_word = i, score, next(
                (w for w in words if w in hay), ""
            )
    if best_i >= 0 and best_score > 0:
        return {
            "action": "click",
            "ref": f"e{best_i + 1}",
            "reason": f"pencocokan kata kunci '{best_word}' (mode heuristik)",
        }
    if cap > 1:
        return {"action": "scroll", "reason": "mode heuristik: telusuri halaman"}
    return {
        "action": "done",
        "reason": "planner LLM tidak tersedia dan tidak ada elemen yang cocok",
    }


def _plan_next_action(
    task: str, url: str, snapshot_text: str, history: list[str], step: int, cap: int
) -> dict[str, Any]:
    prompt = (
        f"TUGAS: {task[:600]}\n"
        f"URL SEKARANG: {url}\n"
        f"LANGKAH: {step + 1} dari {cap}\n"
        f"RIWAYAT: {' | '.join(history[-6:]) or '(belum ada)'}\n\n"
        f"ELEMEN INTERAKTIF YANG TERLIHAT:\n{snapshot_text[:3500]}\n\n"
        "Balas HANYA JSON:\n"
        '{"action":"click|type|scroll|goto|done","ref":"e12",'
        '"text":"isi input bila action=type","url":"https://... bila action=goto",'
        '"reason":"alasan singkat"}\n'
        "Pakai ref persis dari daftar. Pilih done bila tugas sudah tercapai "
        "atau mustahil dilakukan dari halaman ini."
    )
    raw = _llm_complete(prompt, _PLAN_SYSTEM)
    plan = _parse_json_obj(raw)
    if not plan:
        raise RuntimeError(f"planner tidak menghasilkan JSON: {raw[:160]}")
    action = str(plan.get("action") or "").strip().lower()
    if action not in ("click", "type", "scroll", "goto", "done"):
        raise RuntimeError(f"aksi tidak dikenal: {action!r}")
    return plan


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
                page.goto(_normalize_url(start_url), wait_until="domcontentloaded", timeout=45000)
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
                    plan = _plan_next_action(
                        task, page.url, snap_text, history, i, cap
                    )
                except Exception as pe:  # noqa: BLE001
                    note = f"planner LLM gagal -> heuristik: {str(pe)[:140]}"
                    logger.warning("%s", note)
                    plan = _heuristic_plan(task, elements, cap)

                action = plan["action"]
                reason = str(plan.get("reason") or "")[:160]
                entry: dict[str, Any] = {"step": i + 1, "action": action, "reason": reason}
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
                    f"pada {page.url}." if done else
                    f"Otomasi browser '{task}' berhenti setelah {len(steps)} langkah "
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
        "steps": [{"step": i + 1, "action": "fetch", "ref": it.get("link")}
                  for i, it in enumerate(insights)],
        "insights_gathered": insights,
        "final_summary": (
            "Engine browser visual TIDAK aktif, jadi tugas dijalankan lewat riset "
            f"teks (web_search + fetch) menghasilkan {len(insights)} sumber. "
            "Untuk klik/form otomatis, jalankan `camoufox fetch` lalu ulangi."
        ),
    }
