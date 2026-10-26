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

    def _extract_imports(self, file_path: Path) -> list[str]:
        """Extract imported module/file stems across Python, JS/TS, Go, Rust, and Dart."""
        ext = file_path.suffix.lower()
        imports: list[str] = []
        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")[:30000]
            if ext == ".py":
                for m in re.finditer(r"^\s*(?:from|import)\s+([a-zA-Z0-9_\.]+)", content, re.MULTILINE):
                    parts = m.group(1).split(".")
                    imports.extend(p for p in parts if p)
            elif ext in (".js", ".ts", ".jsx", ".tsx"):
                for m in re.finditer(r"""(?:from|require\()\s*['"]([^'"]+)['"]""", content):
                    stem = Path(m.group(1)).stem
                    if stem and stem not in ("index", "."):
                        imports.append(stem)
            elif ext in (".go", ".rs", ".dart"):
                for m in re.finditer(r"""(?:use|import)\s+['"]?([a-zA-Z0-9_/:.]+)""", content):
                    stem = re.split(r"[/:.]", m.group(1))[-1]
                    if stem:
                        imports.append(stem)
        except Exception:
            pass
        return imports

    def rank_files_by_centrality(self, scan_limit: int = 600) -> list[dict[str, object]]:
        """
        PageRank / Import-Centrality scorer for giant repositories:
        Scans up to `scan_limit` files, builds an inbound import reference graph,
        and ranks files by architectural importance (inbound refs + symbol richness + entrypoint weight).
        """
        candidates: list[dict[str, object]] = []
        stem_to_indices: dict[str, list[int]] = {}

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
                try:
                    if p.stat().st_size > 512_000:
                        continue
                except OSError:
                    continue

                rel_file = f"{dir_str}{fname}"
                symbols = (
                    self._extract_py_symbols(p)
                    if ext == ".py"
                    else self._extract_regex_symbols(p)
                    if ext in (".js", ".ts", ".jsx", ".tsx", ".go", ".dart", ".rs")
                    else []
                )
                imports = self._extract_imports(p)
                idx = len(candidates)
                stem = p.stem.lower()
                stem_to_indices.setdefault(stem, []).append(idx)

                # Entrypoint bonus
                entry_bonus = 3.0 if stem in ("main", "app", "index", "server", "router", "__init__", "cli") else 0.0
                depth_penalty = rel_file.count("/") * 0.15

                candidates.append(
                    {
                        "path": p,
                        "rel_file": rel_file,
                        "stem": stem,
                        "symbols": symbols,
                        "imports": imports,
                        "inbound_refs": 0,
                        "score": len(symbols) * 0.5 + entry_bonus - depth_penalty,
                    }
                )
                if len(candidates) >= scan_limit:
                    break
            if len(candidates) >= scan_limit:
                break

        # Accumulate inbound reference counts (PageRank 1-step centrality)
        for item in candidates:
            for imp in item["imports"]:  # type: ignore[union-attr]
                imp_low = str(imp).lower()
                for target_idx in stem_to_indices.get(imp_low, []):
                    if candidates[target_idx]["rel_file"] != item["rel_file"]:
                        candidates[target_idx]["inbound_refs"] = int(candidates[target_idx]["inbound_refs"]) + 1  # type: ignore[arg-type]
                        candidates[target_idx]["score"] = float(candidates[target_idx]["score"]) + 2.5  # type: ignore[arg-type]

        candidates.sort(key=lambda x: (-float(x["score"]), str(x["rel_file"])))  # type: ignore[arg-type]
        return candidates

    def generate_repomap(self, max_files: int = 60) -> str:
        """Scan workspace and generate compact Centrality-Ranked hierarchical repomap."""
        ranked = self.rank_files_by_centrality(scan_limit=max(600, max_files * 4))
        if not ranked:
            return "(Proyek kosong)"

        selected = ranked[:max_files]
        lines: list[str] = []
        for item in selected:
            rel_file = str(item["rel_file"])
            symbols = list(item["symbols"])  # type: ignore[arg-type]
            inbound = int(item["inbound_refs"])  # type: ignore[arg-type]
            ref_badge = f" [refs:{inbound}]" if inbound > 0 else ""
            if symbols:
                sym_repr = ", ".join(str(s) for s in symbols[:5])
                lines.append(f"  • {rel_file}{ref_badge}: {sym_repr}")
            else:
                lines.append(f"  • {rel_file}{ref_badge}")

        if len(ranked) > max_files:
            lines.append(
                f"  ... [dan {len(ranked) - max_files} file lainnya diurutkan berdasarkan Import Centrality]"
            )
        return "\n".join(lines)
