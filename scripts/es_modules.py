#!/usr/bin/env python3
"""Konversi SPA dashboard dari classic script ke ES module.

Alasannya: dashboard memuat 13 file ``<script>`` klasik yang saling
berketergantungan lewat global implisit. Akibatnya:

* tidak ada graf dependensi yang bisa dianalisis statis;
* 78 guard ``typeof x === 'function'`` menyembunyikan dependensi yang hilang;
* 143 handler inline di HTML bergantung pada fungsi yang HARUS tetap global.

Skrip ini melakukan konversi secara deterministik:

1. Menandai simbol yang perlu ``export`` (dipakai modul lain atau handler
   inline HTML).
2. Menyisipkan ``import`` untuk simbol asing yang dipakai file tersebut.
3. Menambahkan *global bridge* (``window.x = x``) untuk simbol yang dipanggil
   handler inline HTML — perilaku ini dipertahankan 100%.
4. Mengganti ``<script src=...>`` di ``templates/index.html`` dengan satu
   ``<script type="module" src="/static/js/app.js">``.

Jalankan: ``python scripts/es_modules.py`` (idempoten).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "static" / "js"
HTML = ROOT / "templates" / "index.html"

# Simpul modul → label
FILES = {
    "state.js": "modules/state.js",
    "audio.js": "modules/audio.js",
    "hotkeys.js": "modules/hotkeys.js",
    "telemetry.js": "modules/telemetry.js",
    "affiliate.js": "modules/affiliate.js",
    "vault_security.js": "modules/vault_security.js",
    "scraper.js": "modules/scraper.js",
    "gdrive.js": "modules/gdrive.js",
    "pipelines_sites.js": "modules/pipelines_sites.js",
    "app.js": "app.js",
    "terminal.js": "terminal.js",
    "tools.js": "tools.js",
    "chat.js": "chat.js",
}

# Path relatif dari tiap file ke file lain (import specifier)
def _relpath(src: str, dst: str) -> str:
    import os

    src_dir = (JS / FILES[src]).parent
    target = JS / FILES[dst]
    rel = os.path.relpath(target, src_dir).replace("\\", "/")
    return rel if rel.startswith(".") else "./" + rel


# Fungsi bawaan JS yang boleh muncul sebagai "handler" di HTML
JS_BUILTINS = {
    "click", "if", "void", "getElementById", "String", "Number", "Boolean",
    "Array", "Object", "JSON", "Math", "Date", "parseInt", "parseFloat",
    "setTimeout", "clearTimeout", "alert", "confirm", "prompt", "encodeURIComponent",
    "decodeURIComponent", "event", "e",
}


# Simbol yang DIDEKLARASIKAN GANDA di beberapa file. Di dunia classic script
# deklarasi terakhir menimpa yang sebelumnya; di ES module itu error
# "Identifier already declared". Untuk tiap simbol, satu file jadi pemilik
# (owner) yang diekspor, dan deklarasi kembar di file lain dihapus.
DUP_SYMBOLS = {
    "fmtTokens": "state.js",
    "speakTextMessage": "audio.js",
    "playToolAudio": "audio.js",
    "ToolAudioRecorder": "tools.js",
}

# Urutan muat klasik (lama) — dipakai untuk menentukan pemilik bawaan.
LOAD_ORDER = [
    "state.js",
    "audio.js",
    "hotkeys.js",
    "telemetry.js",
    "affiliate.js",
    "vault_security.js",
    "scraper.js",
    "gdrive.js",
    "pipelines_sites.js",
    "app.js",
    "terminal.js",
    "tools.js",
    "chat.js",
]


def normalize_class_expressions() -> None:
    """Pre-pass: `window.X = window.X || class X {` → deklarasi kelas biasa."""
    for name in FILES:
        path = JS / FILES[name]
        text = path.read_text(encoding="utf-8")
        new = re.sub(
            r"window\.([A-Za-z_$][\w$]*)\s*=\s*window\.\1\s*\|\|\s*class\s+\1\s*\{",
            r"class \1 {",
            text,
        )
        if new != text:
            path.write_text(new, encoding="utf-8")


# Fungsi API publik dashboard yang WAJIB tetap global: dipakai handler
# inline, test Playwright, dan integrasi luar (console/CLI).
PUBLIC_API = {
    "fetchVaultSecrets",
    "fetchGdriveStatus",
    "fetchSites",
    "fetchTools",
    "fetchStats",
    "fetchSwarmLive",
    "fetchServiceLogs",
    "runAffiliateGenerator",
    "runUniversalScraper",
    "cvSetView",
    "showToast",
    "safeMarkdown",
    "escHtml",
    "escAttr",
}


def collect_declarations() -> dict[str, dict]:
    """{symbol: {"owners": [...], "kind": ...}} untuk deklarasi top-level."""
    decls: dict[str, dict] = {}
    for name in LOAD_ORDER:
        text = (JS / FILES[name]).read_text(encoding="utf-8")
        for m in re.finditer(r"^(async\s+)?function\s+([A-Za-z_$][\w$]*)", text, re.M):
            d = decls.setdefault(
                m.group(2), {"owners": [], "kind": "function", "async": m.group(1) or ""}
            )
            d["owners"].append(name)
        for m in re.finditer(r"^(const|let|var)\s+([A-Za-z_$][\w$]*)\s*=", text, re.M):
            d = decls.setdefault(
                m.group(2), {"owners": [], "kind": m.group(1), "async": ""}
            )
            d["owners"].append(name)
        for m in re.finditer(r"^class\s+([A-Za-z_$][\w$]*)", text, re.M):
            d = decls.setdefault(
                m.group(1), {"owners": [], "kind": "class", "async": ""}
            )
            d["owners"].append(name)
    return decls


def owner_of(sym: str, decls: dict[str, dict]) -> str | None:
    """File pemilik (satu-satunya) untuk sebuah simbol."""
    if sym in DUP_SYMBOLS:
        return DUP_SYMBOLS[sym]
    info = decls.get(sym)
    if not info or not info["owners"]:
        return None
    return info["owners"][-1]


def remove_declaration(text: str, sym: str, kind: str) -> str:
    """Hapus deklarasi (pungsi/const/class) dari teks."""
    if kind == "function":
        m = re.search(
            r"^\s*(?:async\s+)?function\s+" + re.escape(sym) + r"\s*\(", text, re.M
        )
        if not m:
            return text
        start = m.start()
        i = text.index("{", m.end() - 1)
        depth = 0
        while i < len(text):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    i += 1
                    break
            i += 1
        return text[:start] + text[i:]
    # const/let/var satu baris; class bisa multi-baris → brace matching.
    if kind == "class":
        m = re.search(r"^[ \t]*class\s+" + re.escape(sym) + r"\b", text, re.M)
        if not m:
            return text
        start = m.start()
        i = text.index("{", m.end() - 1)
        depth = 0
        while i < len(text):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    i += 1
                    break
            i += 1
        return text[:start] + text[i:]
    pat = re.compile(
        r"^[ \t]*(?:const|let|var)\s+" + re.escape(sym) + r"\b[^\n]*\n",
        re.M,
    )
    return pat.sub("", text)


def html_handler_symbols() -> set[str]:
    """Fungsi yang dipanggil dari handler inline (HTML + string onclick di JS)."""
    html = HTML.read_text(encoding="utf-8")
    out: set[str] = set()
    for m in re.finditer(
        r'on(?:click|change|input|submit|load|keyup|keydown)\s*=\s*"([^"]*)"', html
    ):
        out.update(re.findall(r"\b([A-Za-z_$][\w$]*)\s*\(", m.group(1)))
    # Handler inline yang DIBANGUN di JS (`onclick="fn(...)"` di dalam template
    # string) juga butuh fungsi global.
    for js in JS.rglob("*.js"):
        text = js.read_text(encoding="utf-8")
        for m in re.finditer(
            r'on(?:click|change|input|submit)\s*=\s*"([^"]*)"', text
        ):
            out.update(re.findall(r"\b([A-Za-z_$][\w$]*)\s*\(", m.group(1)))
    return out - JS_BUILTINS


def used_symbols(text: str) -> set[str]:
    called = set(re.findall(r"\b([A-Za-z_$][\w$]*)\s*\(", text))
    bare = set(re.findall(r"(?<![.\w$])([A-Za-z_$][\w$]*)\b", text))
    return called | bare


def simplify_typeof_guards(text: str) -> str:
    """Hapus guard ``typeof x === 'function'`` untuk simbol yang di-import.

    Di classic script, guard ini menyembunyikan dependensi yang hilang (load
    order). Di ES module, import menjamin kehadirannya — guard hanya noise
    yang menutupi bug dependensi.
    """
    # if (typeof X === 'function') X(...);   ->  X(...);
    text = re.sub(
        r"if\s*\(\s*typeof\s+[A-Za-z_$][\w$]*\s*===\s*'function'\s*\)\s*",
        "",
        text,
    )
    # if (typeof X === 'function' && COND)  ->  if (COND)
    text = re.sub(
        r"if\s*\(\s*typeof\s+[A-Za-z_$][\w$]*\s*===\s*'function'\s*&&\s*",
        "if (",
        text,
    )
    # COND && typeof X === 'function')  ->  COND)
    text = re.sub(
        r"&&\s*typeof\s+[A-Za-z_$][\w$]*\s*===\s*'function'\s*\)",
        ")",
        text,
    )
    return text


# Kasus khusus: blok `if (typeof X === 'function') {...} else {...}` di mana
# cabang `else` hanya mungkin terjadi karena X belum ter-load. Setelah
# konversi ke ES module, X dijamin ada → cabang else dibuang.
SPECIAL_CASES = [
    (
        "app.js",
        """    if (typeof startTelemetryPolling === 'function') {
        startTelemetryPolling(2000);
    } else if (typeof fetchStats === 'function') {
        fetchStats();
        setInterval(fetchStats, 2000);
    }""",
        """    startTelemetryPolling(2000);""",
    ),
    (
        "terminal.js",
        """        if (typeof updateSwarmArena === 'function') {
            updateSwarmArena(data);
        } else if (window.updateSwarmArena) {
            window.updateSwarmArena(data);
        }""",
        """        updateSwarmArena(data);""",
    ),
    (
        "terminal.js",
        "const parsed = typeof parseAnsiToHtml === 'function' ? parseAnsiToHtml(line) : line;",
        "const parsed = parseAnsiToHtml(line);",
    ),
]


def apply_special_cases() -> None:
    for name, old, new in SPECIAL_CASES:
        path = JS / FILES[name]
        text = path.read_text(encoding="utf-8")
        if old in text:
            path.write_text(text.replace(old, new), encoding="utf-8")


def main() -> int:
    # Pre-pass normalisasi class expression sebelum deklarasi dikumpulkan.
    normalize_class_expressions()
    apply_special_cases()
    decls = collect_declarations()
    handlers = html_handler_symbols()

    # 1) Foreign symbols per file
    foreign: dict[str, dict[str, str]] = {}
    for name in FILES:
        text = (JS / FILES[name]).read_text(encoding="utf-8")
        used = used_symbols(text)
        found: dict[str, str] = {}
        for sym in used:
            owner = owner_of(sym, decls)
            if owner and owner != name:
                found[sym] = owner
        foreign[name] = found

    # 1b) Simbol yang dideklarasikan file itu SENDIRI → deklarasi lokal menang,
    #     tidak boleh di-import (duplikat identifier). Kecuali bila deklarasi
    #     itu dihapus (simbol kembar) — lalu WAJIB di-import dari pemiliknya.
    local_decls: dict[str, set[str]] = {name: set() for name in FILES}
    for name in FILES:
        text = (JS / FILES[name]).read_text(encoding="utf-8")
        local_decls[name] = set(
            re.findall(r"^(?:async\s+)?function\s+([A-Za-z_$][\w$]*)", text, re.M)
        ) | set(re.findall(r"^(?:const|let|var|class)\s+([A-Za-z_$][\w$]*)", text, re.M))

    removed: dict[str, set[str]] = {name: set() for name in FILES}
    for name in FILES:
        for sym in foreign[name]:
            if sym in local_decls[name] and sym in DUP_SYMBOLS:
                removed[name].add(sym)
    for sym, owner in DUP_SYMBOLS.items():
        for name in FILES:
            if owner != name and sym in local_decls[name]:
                removed[name].add(sym)

    shadowed: dict[str, set[str]] = {
        name: (local_decls[name] - removed[name]) for name in FILES
    }

    # 2) Simbol yang perlu di-export per file (hanya pemilik yang exporting)
    exports: dict[str, set[str]] = {name: set() for name in FILES}
    for syms in foreign.values():
        for sym, owner in syms.items():
            exports[owner].add(sym)
    for sym in handlers:
        owner = owner_of(sym, decls)
        if owner:
            exports[owner].add(sym)

    # 3) Terapkan perubahan per file
    for name in FILES:
        path = JS / FILES[name]
        text = path.read_text(encoding="utf-8")
        orig = text

        # 0) Class expression sudah dinormalisasi di pre-pass.

        # 0b) Hapus deklarasi kembar (file ini bukan pemilik simbol).
        for sym in sorted(removed[name]):
            if sym in decls:
                text = remove_declaration(text, sym, decls[sym]["kind"])

        # 3a. export pada deklarasi (hanya file pemilik)
        for sym in sorted(exports[name]):
            decl = decls.get(sym)
            if not decl or name not in decl["owners"]:
                continue
            if decl["kind"] == "function":
                pat = re.compile(
                    r"^(?P<indent>\s*)(?P<async>async\s+)?function\s+"
                    + re.escape(sym)
                    + r"\b",
                    re.M,
                )
                text = pat.sub(
                    lambda m, _sym=sym: (
                        f"{m.group('indent')}export {m.group('async') or ''}function {_sym}"
                    ),
                    text,
                    count=1,
                )
            elif decl["kind"] in ("const", "let", "var"):
                pat = re.compile(
                    r"^(?P<indent>\s*)" + decl["kind"] + r"\s+" + re.escape(sym) + r"\s*=",
                    re.M,
                )
                text = pat.sub(
                    lambda m, _sym=sym, _kind=decl["kind"]: (
                        f"{m.group('indent')}export {_kind} {_sym} ="
                    ),
                    text,
                    count=1,
                )
            elif decl["kind"] == "class":
                pat = re.compile(
                    r"^(?P<indent>\s*)class\s+" + re.escape(sym) + r"\b", re.M
                )
                text = pat.sub(
                    lambda m, _sym=sym: f"{m.group('indent')}export class {_sym}",
                    text,
                    count=1,
                )

        # 3b. import untuk simbol asing
        imp_lines = []
        by_owner: dict[str, list[str]] = {}
        for sym, owner in foreign[name].items():
            if sym in shadowed[name]:
                continue
            by_owner.setdefault(owner, []).append(sym)
        for owner in sorted(by_owner):
            syms = sorted(by_owner[owner])
            spec = _relpath(name, owner)
            imp_lines.append(f"import {{ {', '.join(syms)} }} from '{spec}';")

        # 3c. global bridge untuk handler inline HTML + API publik
        bridge = []
        for sym in sorted(handlers | PUBLIC_API):
            if owner_of(sym, decls) == name:
                bridge.append(f"window.{sym} = {sym};")

        if imp_lines or bridge:
            marker = "/* ==== ES MODULE BRIDGE ==== */"
            header = "\n".join(imp_lines)
            if header:
                header += "\n"
            import_block = f"\n{marker}\n{header}" if header else ""
            bridge_block = ""
            if bridge:
                bridge_block = (
                    "\n// ==== ES MODULE BRIDGE (global untuk handler inline HTML) ====\n"
                    + "\n".join(bridge)
                    + "\n"
                )

            # Import di kepala file; bridge global di AKHIR file supaya
            # `const`/`let` tidak berada di TDZ saat assignment.
            lines = text.split("\n")
            insert_at = 0
            for i, line in enumerate(lines):
                if line.startswith(("import ", "from ")) or (
                    insert_at and line.startswith((" ", "\t")) and line.strip()
                ):
                    insert_at = i + 1
                elif line.strip() and insert_at:
                    break
            text = (
                "\n".join(lines[:insert_at])
                + import_block
                + "\n".join(lines[insert_at:])
                + bridge_block
            )

        # 3d. Sederhanakan guard typeof untuk simbol yang kini di-import.
        text = simplify_typeof_guards(text)

        if text != orig:
            path.write_text(text, encoding="utf-8")
            print(f"  updated {FILES[name]}")

    # 4) index.html: satu entry module
    html = HTML.read_text(encoding="utf-8")
    for name, rel in FILES.items():
        if name == "app.js":
            continue
        html = re.sub(
            r'\n\s*<script src="/static/js/' + re.escape(rel) + r'\?v=[^"]*"></script>',
            "",
            html,
        )
    html = re.sub(
        r'\n\s*<script src="/static/js/app\.js\?v=[^"]*"></script>',
        '\n    <script type="module" src="/static/js/app.js?v=es-modules"></script>',
        html,
    )
    HTML.write_text(html, encoding="utf-8")
    print("  updated templates/index.html")
    return 0


if __name__ == "__main__":
    sys.exit(main())
