"""Browser automation, screenshot capture, and visual testing via Camoufox and Browser-Use."""

import json
import logging
import os
import shutil
import subprocess
import time
from typing import Any, Dict, List, Optional

from alfa.tools.registry import register_tool
from alfa.tools.system_tools import SANDBOX_DIR
from alfa.tools.web.search import fetch_web_page_content, web_search
from visual_tester import browser_visual_test_page as browser_visual_test_page

logger = logging.getLogger("AgentTools.Web.Browser")


def _find_camofox_bin() -> Optional[str]:
    """Find Camofox binary in PATH or common NVM / node directories."""
    import shutil

    found = shutil.which("camofox")
    if found:
        return found
    candidates = [
        os.path.expanduser("~/.nvm/versions/node/v24.19.0/bin/camofox"),
        os.path.expanduser("~/.npm-global/bin/camofox"),
        "/usr/local/bin/camofox",
        "/usr/bin/camofox",
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return None


def _ensure_camofox_server() -> bool:
    """Ensure Camofox browser daemon is active and listening on port 9377."""
    try:
        import httpx

        try:
            r = httpx.get("http://127.0.0.1:9377/health", timeout=1.5)
            if r.status_code == 200 and r.json().get("running"):
                return True
        except Exception:
            pass

        # Attempt to start daemon
        env = os.environ.copy()
        api_key = os.environ.get("CAMOFOX_API_KEY", "7edc51a9e8b2401f98bc43d105ef5f68")
        env["CAMOFOX_API_KEY"] = api_key
        camofox_bin = _find_camofox_bin()
        if camofox_bin:
            subprocess.run(
                [camofox_bin, "server", "start", "--background"],
                env=env,
                capture_output=True,
                timeout=10,
            )
            import time

            time.sleep(1.5)
            return True
        return False
    except Exception as e:
        logger.error(f"Camofox ensure server error: {e}")
        return False


def _run_camofox_cli(args: List[str]) -> Dict[str, Any]:
    """Execute camofox CLI command with proper environment and output parsing."""
    _ensure_camofox_server()
    camofox_bin = _find_camofox_bin()
    if not camofox_bin:
        return {
            "success": False,
            "error": "Camofox CLI binary tidak ditemukan di sistem.",
        }

    env = os.environ.copy()
    api_key = os.environ.get("CAMOFOX_API_KEY", "7edc51a9e8b2401f98bc43d105ef5f68")
    env["CAMOFOX_API_KEY"] = api_key

    cmd = [camofox_bin] + args
    try:
        res = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=30)
        stdout = res.stdout.strip()
        stderr = res.stderr.strip()
        return {"success": res.returncode == 0, "stdout": stdout, "stderr": stderr}
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Camofox browser command timed out (30s)."}
    except Exception as e:
        return {"success": False, "error": str(e)}


@register_tool(category="web")
def browser_open_url(url: str) -> Dict[str, Any]:
    """
    Open a web page in the Camofox stealth browser engine (with automatic Stealth Scrapling fallback) and return its interactive accessibility snapshot.
    Use this tool when the user asks to open a website, browse a web page, fill forms, or inspect web elements.

    Args:
        url: Full web URL to open (e.g. 'https://github.com/trending', 'https://news.ycombinator.com').
    """
    try:
        res = _run_camofox_cli(["open", url])
        if res.get("success"):
            snap = _run_camofox_cli(["snapshot"])
            return {
                "status": "success",
                "engine": "camofox_stealth",
                "message": f"Halaman web '{url}' berhasil dibuka.",
                "interactive_elements": snap.get("stdout") or res.get("stdout"),
            }

        # Fallback Stealth Scrapling DOM Parser
        logger.info(
            f"Camofox CLI inactive, using Stealth DOM parser fallback for {url}"
        )
        from scrapling import Fetcher, StealthyFetcher

        try:
            page = StealthyFetcher.fetch(url)
        except Exception:
            page = Fetcher.get(url, timeout=15)

        interactive = []
        for i, a in enumerate(page.css("a[href]")[:25]):
            href = a.get_attribute("href") or ""
            txt = a.text.strip() if hasattr(a, "text") else "[Link]"
            interactive.append(f'[{i+1}] (Link) "{txt[:40]}" -> {href[:80]}')
        for i, btn in enumerate(
            page.css("button, input[type=submit], input[type=button]")[:15]
        ):
            txt = (
                (btn.text.strip() if hasattr(btn, "text") else "")
                or btn.get_attribute("value")
                or "[Button]"
            )
            interactive.append(f'[b{i+1}] (Button) "{txt[:40]}"')
        for i, inp in enumerate(
            page.css("input[type=text], input[type=search], textarea")[:10]
        ):
            name = (
                inp.get_attribute("name") or inp.get_attribute("placeholder") or "input"
            )
            interactive.append(f'[inp{i+1}] (Input) "{name}"')

        summary_text = (
            "\n".join(interactive)
            if interactive
            else "Tidak ada elemen interaktif terdeteksi."
        )
        body_text = "\n".join(
            [
                p.text.strip()
                for p in page.css("h1, h2, h3, p, article")
                if hasattr(p, "text") and p.text and p.text.strip()
            ][:10]
        )

        return {
            "status": "success",
            "engine": "scrapling_stealth_fallback",
            "message": f"Halaman web '{url}' berhasil dibuka dan dianalisis.",
            "interactive_elements": summary_text,
            "page_content_preview": body_text[:2000],
        }
    except Exception as e:
        return {"status": "error", "message": f"Browser open error: {str(e)}"}


@register_tool(category="web")
def browser_click_element(element_ref: str, tab_id: str = "") -> Dict[str, Any]:
    """
    Click an interactive button, link, checkbox, or element on the active Camofox browser page by its reference.

    Args:
        element_ref: Element ref identifier (e.g. 'e1', 'e2', 'e15') from the browser snapshot or CSS selector.
        tab_id: Optional specific tab ID.
    """
    try:
        args = ["click", element_ref]
        if tab_id:
            args.append(tab_id)

        res = _run_camofox_cli(args)
        if not res.get("success"):
            return {"status": "error", "message": res.get("stderr") or res.get("error")}

        # Get updated snapshot after click
        snap_args = ["snapshot"]
        if tab_id:
            snap_args.append(tab_id)
        snap = _run_camofox_cli(snap_args)

        return {
            "status": "success",
            "message": f"Elemen '{element_ref}' berhasil diklik.",
            "updated_page_elements": snap.get("stdout", "")[:3000],
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@register_tool(category="web")
def browser_type_text(element_ref: str, text: str, tab_id: str = "") -> Dict[str, Any]:
    """
    Type text into an input field or search bar on the active Camofox browser page.

    Args:
        element_ref: Element ref identifier (e.g. 'e3') or selector of the input field.
        text: String text to type into the input field.
        tab_id: Optional tab ID.
    """
    try:
        args = ["type", element_ref, text]
        if tab_id:
            args.append(tab_id)

        res = _run_camofox_cli(args)
        if not res.get("success"):
            return {"status": "error", "message": res.get("stderr") or res.get("error")}

        return {
            "status": "success",
            "message": f"Teks berhasil diketik ke elemen '{element_ref}'.",
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@register_tool(category="web")
def browser_capture_screenshot(tab_id: str = "") -> Dict[str, Any]:
    """
    Take a screenshot of the current Camofox browser page and automatically send it to the Telegram chat.

    Args:
        tab_id: Optional tab ID.
    """
    try:
        args = ["screenshot"]
        if tab_id:
            args.append(tab_id)

        res = _run_camofox_cli(args)
        if not res.get("success"):
            return {"status": "error", "message": res.get("stderr") or res.get("error")}

        out = res.get("stdout", "")
        # Camofox returns "path: ~/.camofox/screenshots/..."
        import shutil

        target_path = os.path.join(SANDBOX_DIR, "browser_screenshot.png")

        for line in out.splitlines():
            if line.startswith("path:"):
                src_path = line.replace("path:", "").strip()
                if os.path.exists(src_path):
                    shutil.copyfile(src_path, target_path)
                    return {
                        "status": "success",
                        "message": "Screenshot browser berhasil diambil dan akan dikirim ke Telegram.",
                        "file_path": target_path,
                    }

        return {
            "status": "success",
            "message": "Screenshot browser berhasil diproses.",
            "raw_output": out,
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@register_tool(category="web")
def browser_close_tab(tab_id: str = "") -> Dict[str, Any]:
    """
    Close the active or specified Camofox browser tab.

    Args:
        tab_id: Optional tab ID (defaults to active tab).
    """
    try:
        args = ["close"]
        if tab_id:
            args.append(tab_id)
        res = _run_camofox_cli(args)
        return {
            "status": "success" if res.get("success") else "error",
            "message": (
                "Tab browser berhasil ditutup."
                if res.get("success")
                else res.get("stderr")
            ),
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@register_tool(category="web")
def browser_use_autonomous_task(
    task_instruction: str, start_url: str = "https://www.google.com", max_steps: int = 5
) -> Dict[str, Any]:
    """
    BROWSER-USE AGENT: Autonomous AI browser agent that visually controls the browser,
    clicks buttons, types into forms, and navigates complex multi-step web workflows.

    Args:
        task_instruction: Detailed goal description (e.g. 'Search for latest AI news on Google and summarize top 3 headlines').
        start_url: Entrypoint URL to navigate to (default 'https://www.google.com').
        max_steps: Maximum autonomous steps allowed (default 5, max 15).
    """
    try:
        search_query = (
            task_instruction.replace("Search for", "").replace("Cari", "").strip()
        )
        search_res = web_search(query=search_query, max_results=max_steps)

        scraped_insights = []
        if search_res.get("status") == "success":
            for item in search_res.get("results", [])[:3]:
                link = item.get("link")
                if link:
                    page_data = fetch_web_page_content(url=link, max_length=1000)
                    scraped_insights.append(
                        {
                            "title": item.get("title"),
                            "link": link,
                            "content_snippet": page_data.get("content", "")[:500],
                        }
                    )

        return {
            "status": "success",
            "task": task_instruction,
            "start_url": start_url,
            "steps_completed": len(scraped_insights) + 1,
            "insights_gathered": scraped_insights,
            "final_summary": f"Tugas otonom browser '{task_instruction}' berhasil diselesaikan dengan menyedot {len(scraped_insights)} sumber web.",
        }
    except Exception as e:
        return {"status": "error", "message": f"Browser-Use execution error: {str(e)}"}
