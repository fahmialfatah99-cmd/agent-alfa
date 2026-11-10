#!/usr/bin/env python3
"""Gate CI: larang `except Exception: pass` (penelan error senyap).

Handler yang menelan exception tanpa jejak membuat bug sulit dilacak.
Aturan repo: error HARUS dicatat (setidaknya level debug).

Exit code:
  0 — tidak ada handler senyap
  1 — ada handler senyap (dicetak file:line)
"""

from __future__ import annotations

import argparse
import ast
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
TARGETS = ("alfa", "plugins")


def silent_handlers(path: pathlib.Path) -> list[tuple[int, str]]:
    """(baris, nama fungsi) untuk handler yang menelan exception diam-diam."""
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except (OSError, SyntaxError):
        return []

    scopes: dict[int, str] = {}

    def visit(node: ast.AST, scope: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ExceptHandler):
                scopes[id(child)] = scope
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                visit(child, child.name)
            else:
                visit(child, scope)

    visit(tree, "<modul>")

    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        if not isinstance(node.type, ast.Name) or node.type.id not in (
            "Exception",
            "BaseException",
        ):
            continue
        if len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
            found.append((node.lineno, scopes.get(id(node), "<modul>")))
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--list",
        action="store_true",
        help="Tampilkan daftar temuan lalu tetap keluar dengan kode 0",
    )
    args = parser.parse_args(argv)

    total = 0
    for target in TARGETS:
        base = ROOT / target
        if not base.exists():
            continue
        for path in sorted(base.rglob("*.py")):
            if "__pycache__" in str(path):
                continue
            for lineno, scope in silent_handlers(path):
                rel = path.relative_to(ROOT)
                print(f"{rel}:{lineno}: except Exception: pass  (dalam {scope})")
                total += 1

    if total == 0:
        print("OK — tidak ada handler exception senyap.")
        return 0
    print(f"\n{total} handler senyap ditemukan.")
    if args.list:
        return 0
    print("Ganti dengan logging minimal: logger.debug('...: %s', exc)")
    return 1


if __name__ == "__main__":
    sys.exit(main())
