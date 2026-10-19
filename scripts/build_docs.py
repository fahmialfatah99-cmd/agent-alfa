#!/usr/bin/env python3
"""Sinkron salinan dokumen untuk mkdocs (mkdocs tidak mengikuti symlink
lintas-docs dengan andal untuk origin di luar ``docs/``).

Salinan dibuat + path internal README dinormalkan agar link internal valid.
Pemakaian: python scripts/build_docs.py [--check]
"""

from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
COPIES: tuple[tuple[str, str, tuple[tuple[str, str], ...]], ...] = (
    ("README.md", "docs/about.md", ()),
    ("SECURITY.md", "docs/security.md", ()),
    ("CHANGELOG.md", "docs/CHANGELOG.md", ()),
)
REWRITE_DOC_LINKS = (
    ("docs/BENCHMARK.md", "BENCHMARK.md"),
    ("docs/INSTALL.md", "INSTALL.md"),
    ("docs/DEPLOYMENT.md", "DEPLOYMENT.md"),
    ("docs/TESTING.md", "TESTING.md"),
    ("docs/CODE_QUALITY.md", "CODE_QUALITY.md"),
    ("docs/EFFICIENCY.md", "EFFICIENCY.md"),
    ("docs/POSTGRES.md", "POSTGRES.md"),
)
BANNER = (
    "<!-- COPY SINKRON dari /{src} — jangan edit manual; jalankan "
    "scripts/build_docs.py -->"
)


CLI_MENU_URL = "https://github.com/fahmialfatah99-cmd/agent-alfa/tree/main/alfa-cli"


def _rewrite(content: str) -> str:
    for old, new in REWRITE_DOC_LINKS:
        content = content.replace(f"({old})", f"({new})")
    # link subrepo alfa-cli: absolute ke GitHub agar valid di docs build
    content = re.sub(r"\(alfa-cli/(README\.md)\)", f"({CLI_MENU_URL})", content)
    return content


def main() -> int:
    check = "--check" in sys.argv[1:]
    for src, dst, _extra in COPIES:
        content = _rewrite((ROOT / src).read_text(encoding="utf-8"))
        written = (BANNER.format(src=src) + "\n\n" + content)
        target = ROOT / dst
        if check:
            if target.read_text(encoding="utf-8") != written:
                print(f"stale: {dst} — jalankan scripts/build_docs.py")
                return 1
        else:
            target.write_text(written, encoding="utf-8")
            print(f"sync {src} → {dst}")
    print("dokumen sinkron" if check else "beres")
    return 0


if __name__ == "__main__":
    sys.exit(main())
