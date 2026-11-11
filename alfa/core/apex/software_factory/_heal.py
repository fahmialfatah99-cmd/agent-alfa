"""Perbaikan otomatis HTML & picking entrypoint."""
from __future__ import annotations

import html as html_lib
import logging
import os
import re

logger = logging.getLogger(__name__)

_INDEX_READER_HELPER = '''

def _alfa_read_index() -> str:
    """Serve index.html relative to THIS file, never relative to the process CWD."""
    import os as _os

    _here = _os.path.dirname(_os.path.abspath(__file__))
    with open(_os.path.join(_here, "index.html"), encoding="utf-8") as _fh:
        return _fh.read()
'''

def _read_text_file(path: str) -> tuple[str, str | None]:
    """
    Read a text file as UTF-8 without ever raising.

    Returns `(text, decode_error)`. `decode_error` is None on a clean decode; otherwise it
    describes the problem and the text has invalid bytes replaced with U+FFFD so that
    downstream scanning can still continue instead of aborting the whole verification gate.
    """
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError as exc:
        return "", f"unreadable file ({exc.__class__.__name__}: {exc})"
    try:
        return raw.decode("utf-8"), None
    except UnicodeDecodeError as exc:
        return raw.decode("utf-8", errors="replace"), f"invalid UTF-8 at byte offset {exc.start}"

def _script_spans(html_text: str) -> list[tuple[int, int]]:
    """Character ranges covered by `<script>...</script>` blocks (unterminated included)."""
    spans: list[tuple[int, int]] = []
    low = html_text.lower()
    pos = 0
    while True:
        start = low.find("<script", pos)
        if start == -1:
            break
        tag_end = low.find(">", start)
        if tag_end == -1:
            spans.append((start, len(html_text)))
            break
        # A self-closing `<script src="..." />` has no body — it must not swallow the
        # rest of the document, otherwise every later `</body>` / `</html>` looks "inside script".
        if low[start:tag_end + 1].rstrip().endswith("/>"):
            pos = tag_end + 1
            continue
        end = low.find("</script>", tag_end)
        if end == -1:
            spans.append((start, len(html_text)))
            break
        end += len("</script>")
        spans.append((start, end))
        pos = end
    return spans

def _find_safe_close(html_text: str, tag: str) -> int:
    """
    Index of the LAST `</tag>` that is not inside a `<script>` block.

    Prevents the auto-healer from injecting markup into a JS string literal such as
    `var s = "</body>";`.
    """
    spans = _script_spans(html_text)
    best = -1
    for m in re.finditer(rf"</{tag}\s*>", html_text, re.I):
        if any(start <= m.start() < end for start, end in spans):
            continue
        best = m.start()
    return best

def _count_script_tags(html_text: str) -> tuple[int, int]:
    """
    Return `(unbalanced_open, unbalanced_close)` for `<script>` tags.

    Self-closing `<script src="..." />` is legal HTML5 and is NOT counted as an open tag.
    """
    low = html_text.lower()
    paired = re.compile(r"<script\b[^>]*>.*?</script\s*>", re.S)
    rest = paired.sub("", low)
    opens = 0
    for m in re.finditer(r"<script\b[^>]*>", rest):
        if m.group(0).rstrip().endswith("/>"):
            continue
        opens += 1
    closes = len(re.findall(r"</script\s*>", rest))
    return opens, closes

def _pick_entrypoint(root: str) -> str | None:
    """
    Pick the HTML entrypoint used for the live HTTP smoke test.

    Priority: root `index.html` > root `index.htm` > any root HTML > first HTML anywhere.
    Returns an absolute path or None when the project ships no HTML at all.
    """
    root_abs = os.path.abspath(root)
    all_html: list[str] = []
    root_html: list[str] = []
    for walk_root, _dirs, walk_files in os.walk(root):
        for fname in sorted(walk_files):
            if fname.lower().endswith((".html", ".htm")):
                full = os.path.join(walk_root, fname)
                all_html.append(full)
                if os.path.abspath(walk_root) == root_abs:
                    root_html.append(full)
    for candidate in ("index.html", "index.htm"):
        for path in root_html:
            if os.path.basename(path).lower() == candidate:
                return path
    if root_html:
        return sorted(root_html)[0]
    if all_html:
        return sorted(all_html)[0]
    return None

def _auto_heal_html(html_text: str, title: str) -> tuple[str, list[str]]:
    """Automatically repair missing structural HTML tags if a draft frontend is incomplete."""
    healed = html_text.strip()
    repairs: list[str] = []
    safe_title = html_lib.escape(title or "Untitled")

    if "<!doctype html>" not in healed.lower():
        healed = "<!DOCTYPE html>\n" + healed
        repairs.append("Added missing <!DOCTYPE html> declaration.")

    if "<html" not in healed.lower():
        healed = (
            f'<html lang="id">\n<head><meta charset="utf-8"><title>{safe_title}</title></head>\n'
            f"<body>\n{healed}\n</body>\n</html>"
        )
        repairs.append("Wrapped content in standard <html><head><body> structure.")
        return healed, repairs

    head_m = re.search(r"<head\b[^>]*>", healed, re.I)
    title_m = re.search(r"<title\b[^>]*>", healed, re.I)

    if not head_m:
        head_inner = '<meta charset="utf-8">'
        if not title_m:
            head_inner += f"<title>{safe_title}</title>"
        open_html_m = re.search(r"<html\b[^>]*>", healed, re.I)
        if open_html_m:
            pos = open_html_m.end()
            healed = f"{healed[:pos]}\n<head>{head_inner}</head>{healed[pos:]}"
        else:
            healed = f"<head>{head_inner}</head>\n{healed}"
        repairs.append("Injected missing <head> (with <title>) into the document.")
    elif not title_m:
        pos = head_m.end()
        healed = f"{healed[:pos]}<title>{safe_title}</title>{healed[pos:]}"
        repairs.append("Injected <title> tag into <head>.")

    if _find_safe_close(healed, "body") == -1:
        html_close = _find_safe_close(healed, "html")
        if html_close != -1:
            healed = f"{healed[:html_close]}\n</body>\n{healed[html_close:]}"
        else:
            healed += "\n</body>"
        repairs.append("Closed unclosed </body> tag.")

    if _find_safe_close(healed, "html") == -1:
        healed += "\n</html>"
        repairs.append("Closed unclosed </html> tag.")

    return healed, repairs

def _heal_backend_and_anti_mockup(html_text: str, backend_py: str, title: str) -> tuple[str, str, list[str]]:
    """
    Anti-Mockup & Runtime Self-Healing Engine:
    1. Fixes Flask `render_template('index.html')` when `templates/` folder does not exist so root
       `index.html` is served cleanly — resolved relative to the module file, not the process CWD.
    2. Injects a non-blocking Toast notification + real `localStorage` state persistence helper if raw
       `alert()` calls exist. The toast is anchored on a script-safe `</body>` so it can never be
       injected into a JavaScript string literal.
    """
    repairs: list[str] = []
    healed_py = backend_py.strip()
    healed_html = html_text

    if healed_py and "render_template(" in healed_py:
        rewritten = re.sub(
            r"render_template\(\s*['\"]index\.html['\"]\s*\)",
            "_alfa_read_index()",
            healed_py,
        )
        if rewritten != healed_py:
            if "def _alfa_read_index" not in healed_py:
                rewritten = rewritten + _INDEX_READER_HELPER
            healed_py = rewritten
            repairs.append(
                "Replaced Flask render_template('index.html') with a CWD-independent index.html reader."
            )

    if "alert(" in healed_html and "alfa-anti-mockup-runtime" not in healed_html:
        toast_script = """
<script id="alfa-anti-mockup-runtime">
window.alfaToast = function(msg) {
    let box = document.getElementById('alfa-live-toast');
    if (!box) {
        box = document.createElement('div');
        box.id = 'alfa-live-toast';
        box.style.cssText = 'position:fixed;bottom:20px;right:20px;background:#0f172a;color:#38bdf8;border:1px solid #0284c7;padding:12px 18px;border-radius:10px;font-family:system-ui,sans-serif;font-size:13px;z-index:99999;box-shadow:0 10px 25px rgba(0,0,0,0.5);transition:opacity 0.25s;';
        document.body.appendChild(box);
    }
    box.textContent = '⚡ ' + msg;
    box.style.opacity = '1';
    clearTimeout(window._alfaToastTimer);
    window._alfaToastTimer = setTimeout(() => { box.style.opacity = '0'; }, 3500);
};
</script>
"""
        anchor = _find_safe_close(healed_html, "body")
        if anchor == -1:
            anchor = _find_safe_close(healed_html, "html")
        if anchor != -1:
            healed_html = f"{healed_html[:anchor]}{toast_script}\n{healed_html[anchor:]}"
            repairs.append("Injected non-blocking live toast notification runtime.")
        else:
            healed_html = f"{healed_html}{toast_script}"
            repairs.append("Injected non-blocking live toast notification runtime (appended at end).")

    return healed_html, healed_py, repairs
