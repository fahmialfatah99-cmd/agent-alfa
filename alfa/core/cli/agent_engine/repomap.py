"""Repomap generator: compressed codebase symbol maps."""

from __future__ import annotations

import ast
import os
import re
from pathlib import Path

# ==========================================
# 2. REPOMAP & CODEBASE SYMBOL GENERATOR
# ==========================================


class RepomapGenerator:
    """Generates a compressed, high-density architectural symbol map of the codebase."""

    IGNORE_DIRS = {
        ".git",
        "node_modules",
        "venv",
        ".venv",
        "__pycache__",
        ".alfa_worktrees",
        ".pytest_cache",
        ".ruff_cache",
        ".alfa_backups",
        "dist",
        "build",
        ".next",
        ".dart_tool",
    }

    IGNORE_EXTS = {
        ".pyc",
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".svg",
        ".ico",
        ".woff",
        ".woff2",
        ".ttf",
        ".eot",
        ".zip",
        ".tar",
        ".gz",
        ".db",
        ".sqlite",
        ".sqlite3",
        ".lock",
    }

    def __init__(self, root_dir: Path | None = None):
        self.root = root_dir or Path.cwd()

    def _extract_py_symbols(self, file_path: Path) -> list[str]:
        """Parse Python AST to extract classes and top-level functions."""
        symbols: list[str] = []
        try:
            source = file_path.read_text(encoding="utf-8", errors="ignore")
            tree = ast.parse(source)
            for node in tree.body:
                if isinstance(node, ast.ClassDef):
                    methods = [
                        m.name
                        for m in node.body
                        if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and not m.name.startswith("__")
                    ]
                    meth_str = (
                        f"({', '.join(methods[:4])}{'...' if len(methods) > 4 else ''})"
                        if methods
                        else ""
                    )
                    symbols.append(f"class {node.name}{meth_str}")
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    symbols.append(f"def {node.name}()")
        except Exception:
            pass
        return symbols

    def _extract_regex_symbols(self, file_path: Path) -> list[str]:
        """Rich symbol extraction for TypeScript, JavaScript, Go, Dart, Rust, and generic files."""
        symbols: list[str] = []
        ext = file_path.suffix.lower()
        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")[:40000]

            if ext in (".ts", ".tsx", ".js", ".jsx"):
                interfaces = re.findall(
                    r"(?:export\s+)?interface\s+([A-Za-z0-9_]+)", content
                )
                types = re.findall(r"(?:export\s+)?type\s+([A-Za-z0-9_]+)\s*=", content)
                classes = re.findall(r"(?:export\s+)?class\s+([A-Za-z0-9_]+)", content)
                functions = re.findall(
                    r"(?:export\s+)?(?:async\s+)?function\s+([A-Za-z0-9_]+)\s*\(",
                    content,
                )
                const_fns = re.findall(
                    r"(?:export\s+)?const\s+([A-Za-z0-9_]+)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>",
                    content,
                )
                for i in interfaces[:3]:
                    symbols.append(f"interface {i}")
                for t in types[:3]:
                    symbols.append(f"type {t}")
                for c in classes[:3]:
                    symbols.append(f"class {c}")
                for f in (functions + const_fns)[:5]:
                    symbols.append(f"{f}()")

            elif ext == ".go":
                structs = re.findall(r"type\s+([A-Za-z0-9_]+)\s+struct\b", content)
                interfaces = re.findall(
                    r"type\s+([A-Za-z0-9_]+)\s+interface\b", content
                )
                methods = re.findall(
                    r"func\s+\(\w+\s+\*?([A-Za-z0-9_]+)\)\s+([A-Za-z0-9_]+)\s*\(",
                    content,
                )
                funcs = re.findall(r"func\s+([A-Za-z0-9_]+)\s*\(", content)
                for s in structs[:3]:
                    symbols.append(f"struct {s}")
                for i in interfaces[:3]:
                    symbols.append(f"interface {i}")
                for r, m in methods[:4]:
                    symbols.append(f"({r}).{m}()")
                for f in funcs[:4]:
                    if not any(f == m[1] for m in methods):
                        symbols.append(f"{f}()")

            elif ext == ".rs":
                structs = re.findall(r"(?:pub\s+)?struct\s+([A-Za-z0-9_]+)", content)
                enums = re.findall(r"(?:pub\s+)?enum\s+([A-Za-z0-9_]+)", content)
                traits = re.findall(r"(?:pub\s+)?trait\s+([A-Za-z0-9_]+)", content)
                funcs = re.findall(
                    r"(?:pub\s+)?(?:async\s+)?fn\s+([A-Za-z0-9_]+)\s*\(", content
                )
                for s in structs[:3]:
                    symbols.append(f"struct {s}")
                for e in enums[:2]:
                    symbols.append(f"enum {e}")
                for t in traits[:2]:
                    symbols.append(f"trait {t}")
                for f in funcs[:4]:
                    symbols.append(f"{f}()")

            elif ext == ".dart":
                classes = re.findall(
                    r"(?:abstract\s+)?class\s+([A-Za-z0-9_]+)", content
                )
                mixins = re.findall(r"mixin\s+([A-Za-z0-9_]+)", content)
                enums = re.findall(r"enum\s+([A-Za-z0-9_]+)", content)
                funcs = re.findall(
                    r"(?:void|Future<[^>]+>|Widget|[A-Za-z0-9_]+)\s+([a-zA-Z0-9_]+)\s*\([^)]*\)\s*(?:async\s*)?\{",
                    content,
                )
                for c in classes[:4]:
                    symbols.append(f"class {c}")
                for m in mixins[:2]:
                    symbols.append(f"mixin {m}")
                for e in enums[:2]:
                    symbols.append(f"enum {e}")
                for f in funcs[:4]:
                    if f not in ("build", "initState", "dispose"):
                        symbols.append(f"{f}()")

            else:
                cls_matches = re.findall(r"class\s+([a-zA-Z0-9_]+)", content)
                fn_matches = re.findall(
                    r"(?:function|def|func|fn)\s+([a-zA-Z0-9_]+)\s*\(", content
                )
                for c in cls_matches[:4]:
                    symbols.append(f"class {c}")
                for f in fn_matches[:6]:
                    symbols.append(f"{f}()")

        except Exception:
            pass
        return symbols

    def generate_repomap(self, max_files: int = 60) -> str:
        """Scan workspace and generate compact hierarchical repomap."""
        lines: list[str] = []
        count = 0

        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [
                d
                for d in dirnames
                if d not in self.IGNORE_DIRS and not d.startswith(".")
            ]
            rel_dir = Path(dirpath).relative_to(self.root)
            dir_str = "" if str(rel_dir) == "." else f"{rel_dir}/"

            for fname in sorted(filenames):
                p = Path(dirpath) / fname
                ext = p.suffix.lower()
                if ext in self.IGNORE_EXTS or fname.startswith("."):
                    continue

                rel_file = f"{dir_str}{fname}"
                symbols = []
                if ext == ".py":
                    symbols = self._extract_py_symbols(p)
                elif ext in (".js", ".ts", ".jsx", ".tsx", ".go", ".dart", ".rs"):
                    symbols = self._extract_regex_symbols(p)

                if symbols:
                    sym_repr = ", ".join(symbols[:5])
                    lines.append(f"  • {rel_file}: {sym_repr}")
                else:
                    lines.append(f"  • {rel_file}")

                count += 1
                if count >= max_files:
                    lines.append(f"  ... [dan {count}+ file lainnya]")
                    return "\n".join(lines)

        return "\n".join(lines) if lines else "(Proyek kosong)"
