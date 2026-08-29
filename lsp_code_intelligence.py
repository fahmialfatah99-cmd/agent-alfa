"""
LSP CODE INTELLIGENCE ENGINE — AST Symbol Table & Reference Graph.
Provides Cursor/Antigravity-grade code navigation:
- lsp_find_symbol_definition: Locate exact function/class/method definitions with signatures & docstrings.
- lsp_find_symbol_references: Map all callers, imports, and usages across the entire codebase.
- lsp_analyze_module_hierarchy: Extract class inheritance, methods, and dependency graphs.
"""

import ast
import logging
import os
import re
from typing import Any, Dict, List

logger = logging.getLogger("LSPCodeIntelligence")

def _get_project_root(repo_path: str = "") -> str:
    if repo_path and os.path.isdir(os.path.expanduser(repo_path)):
        return os.path.realpath(os.path.expanduser(repo_path))
    return os.path.dirname(os.path.abspath(__file__))


def _iter_source_files(root_dir: str, extensions: List[str]):
    ignore_dirs = {".git", "venv", "__pycache__", "node_modules", ".pytest_cache", ".alfa_worktrees", "dist", "build"}
    for root, dirs, files in os.walk(root_dir):
        dirs[:] = [d for d in dirs if d not in ignore_dirs and not d.startswith(".")]
        for f in files:
            ext = os.path.splitext(f)[1].lstrip(".").lower()
            if ext in extensions:
                yield os.path.join(root, f)


def lsp_find_symbol_definition(symbol_name: str, repo_path: str = "") -> Dict[str, Any]:
    """
    LSP ENGINE: Locate exact definition(s) of a function, class, method, or variable
    across the codebase with signature, docstring, and line ranges using AST.

    Args:
        symbol_name: Name of the function, class, or method (e.g. 'run_agent_turn', 'VectorMemory', 'gdrive_status').
        repo_path: Optional path to repository root (defaults to current project).
    """
    root = _get_project_root(repo_path)
    symbol_name = symbol_name.strip()
    if not symbol_name:
        return {"status": "error", "message": "symbol_name tidak boleh kosong."}

    matches = []
    py_files = list(_iter_source_files(root, ["py"]))

    for fpath in py_files:
        try:
            with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                source = f.read()
            tree = ast.parse(source, filename=fpath)
            lines = source.splitlines()

            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    if node.name == symbol_name:
                        kind = "class" if isinstance(node, ast.ClassDef) else ("async_function" if isinstance(node, ast.AsyncFunctionDef) else "function")
                        start_l = getattr(node, "lineno", 1)
                        end_l = getattr(node, "end_lineno", start_l)
                        doc = ast.get_docstring(node) or ""

                        sig = ""
                        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            args_list = []
                            for arg in node.args.args:
                                a_str = arg.arg
                                if arg.annotation:
                                    try:
                                        a_str += f": {ast.unparse(arg.annotation)}"
                                    except Exception:
                                        pass
                                args_list.append(a_str)
                            ret_str = ""
                            if node.returns:
                                try:
                                    ret_str = f" -> {ast.unparse(node.returns)}"
                                except Exception:
                                    pass
                            sig = f"({', '.join(args_list)}){ret_str}"

                        rel_path = os.path.relpath(fpath, root)
                        snippet_lines = lines[max(0, start_l - 1):min(len(lines), start_l + 15)]
                        snippet = chr(10).join(snippet_lines)

                        matches.append({
                            "symbol": symbol_name,
                            "kind": kind,
                            "file": rel_path,
                            "abs_path": fpath,
                            "line_start": start_l,
                            "line_end": end_l,
                            "signature": f"{node.name}{sig}" if sig else node.name,
                            "docstring": doc.split(chr(10) + chr(10))[0] if doc else "",
                            "snippet": snippet
                        })
        except Exception as e:
            logger.debug(f"Error parsing {fpath} for symbol {symbol_name}: {e}")

    if not matches:
        other_files = list(_iter_source_files(root, ["js", "ts", "jsx", "tsx", "go", "rs"]))
        pattern = re.compile(rf"(function|class|const|let|var|def|fn|type|struct)\s+{re.escape(symbol_name)}", re.MULTILINE)
        for fpath in other_files:
            try:
                with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
                lines = content.splitlines()
                for i, line in enumerate(lines):
                    if pattern.search(line):
                        snippet_lines = lines[max(0, i):min(len(lines), i + 15)]
                        matches.append({
                            "symbol": symbol_name,
                            "kind": "symbol",
                            "file": os.path.relpath(fpath, root),
                            "abs_path": fpath,
                            "line_start": i + 1,
                            "line_end": min(len(lines), i + 20),
                            "signature": line.strip(),
                            "docstring": "",
                            "snippet": chr(10).join(snippet_lines)
                        })
            except Exception:
                pass

    return {
        "status": "success",
        "symbol": symbol_name,
        "total_definitions": len(matches),
        "definitions": matches,
        "message": f"Ditemukan {len(matches)} definisi untuk simbol '{symbol_name}'." if matches else f"Simbol '{symbol_name}' tidak ditemukan di {root}."
    }


def lsp_find_symbol_references(symbol_name: str, repo_path: str = "", limit: int = 40) -> Dict[str, Any]:
    """
    LSP ENGINE: Map all locations where a function, class, or variable is called,
    imported, or referenced across the entire codebase.

    Args:
        symbol_name: The symbol to search for references (e.g. 'execute_bash_command').
        repo_path: Optional path to repository root.
        limit: Max references to return (default 40).
    """
    root = _get_project_root(repo_path)
    symbol_name = symbol_name.strip()
    if not symbol_name:
        return {"status": "error", "message": "symbol_name tidak boleh kosong."}

    refs = []
    files = list(_iter_source_files(root, ["py", "js", "ts", "jsx", "tsx", "html", "sh"]))
    pattern = re.compile(r"\b" + re.escape(symbol_name) + r"\b")

    for fpath in files:
        if len(refs) >= limit:
            break
        try:
            with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
            rel_path = os.path.relpath(fpath, root)
            for idx, line in enumerate(lines):
                if pattern.search(line):
                    is_definition = bool(re.search(r"\b(def|class|function|const)\s+" + re.escape(symbol_name) + r"\b", line))
                    refs.append({
                        "file": rel_path,
                        "abs_path": fpath,
                        "line_number": idx + 1,
                        "is_definition": is_definition,
                        "line_content": line.strip()
                    })
                    if len(refs) >= limit:
                        break
        except Exception:
            continue

    return {
        "status": "success",
        "symbol": symbol_name,
        "total_references": len(refs),
        "references": refs,
        "message": f"Ditemukan {len(refs)} referensi untuk '{symbol_name}'."
    }


def lsp_analyze_module_hierarchy(target_file: str, repo_path: str = "") -> Dict[str, Any]:
    """
    LSP ENGINE: Parse class hierarchy, methods, imported modules, and exported symbols of a file.

    Args:
        target_file: Path to the python or javascript file.
        repo_path: Optional repository root.
    """
    root = _get_project_root(repo_path)
    abs_path = os.path.realpath(os.path.expanduser(target_file))
    if not os.path.isabs(abs_path) or not os.path.exists(abs_path):
        abs_path = os.path.join(root, target_file)

    if not os.path.exists(abs_path):
        return {"status": "error", "message": f"File '{target_file}' tidak ditemukan."}

    if not abs_path.endswith(".py"):
        return {"status": "error", "message": "Analisis hierarki mendalam saat ini dioptimalkan untuk file Python (.py)."}

    try:
        with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
            source = f.read()
        tree = ast.parse(source, filename=abs_path)

        imports = []
        classes = []
        top_functions = []

        for node in tree.body:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                names = [a.name for a in node.names]
                imports.append(f"{mod} ({', '.join(names)})")
            elif isinstance(node, ast.ClassDef):
                bases = []
                for b in node.bases:
                    try:
                        bases.append(ast.unparse(b))
                    except Exception:
                        pass
                methods = []
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        methods.append({
                            "name": item.name,
                            "line": item.lineno,
                            "is_async": isinstance(item, ast.AsyncFunctionDef)
                        })
                classes.append({
                    "class_name": node.name,
                    "bases": bases,
                    "line_start": node.lineno,
                    "line_end": getattr(node, "end_lineno", node.lineno),
                    "methods_count": len(methods),
                    "methods": methods
                })
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                top_functions.append({
                    "function_name": node.name,
                    "line_start": node.lineno,
                    "line_end": getattr(node, "end_lineno", node.lineno),
                    "is_async": isinstance(node, ast.AsyncFunctionDef)
                })

        return {
            "status": "success",
            "file": os.path.relpath(abs_path, root),
            "total_imports": len(imports),
            "imports": imports,
            "total_classes": len(classes),
            "classes": classes,
            "total_top_functions": len(top_functions),
            "top_functions": top_functions
        }
    except Exception as e:
        return {"status": "error", "message": f"Gagal menganalisis modul {target_file}: {str(e)}"}
