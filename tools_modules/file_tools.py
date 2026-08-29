"""File & Workspace Tools for ALFA Agent."""

import logging
import os
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)


def read_local_file(file_path: str, max_lines: int = 300, start_line: int = 1) -> Dict[str, Any]:
    """Read content from a local file."""
    try:
        path = Path(file_path).expanduser().resolve()
        
        if not path.exists():
            return {"status": "error", "error": "File not found"}
        
        with open(path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        total_lines = len(lines)
        start_idx = max(0, start_line - 1)
        end_idx = min(total_lines, start_idx + max_lines)
        
        content = ''.join(lines[start_idx:end_idx])
        
        return {
            "status": "success",
            "message": f"Read {end_idx - start_idx} lines from {file_path}",
            "data": {
                "content": content,
                "lines_returned": end_idx - start_idx,
                "total_lines": total_lines
            }
        }
    except Exception as e:
        logger.error(f"Read file error: {e}")
        return {"status": "error", "error": str(e)}


def write_local_file(file_path: str, content: str) -> Dict[str, Any]:
    """Write content to a local file."""
    try:
        path = Path(file_path).expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
        
        return {
            "status": "success",
            "message": f"Written {len(content)} characters to {file_path}"
        }
    except Exception as e:
        logger.error(f"Write file error: {e}")
        return {"status": "error", "error": str(e)}


def edit_file_precise(file_path: str, old_text: str, new_text: str) -> Dict[str, Any]:
    """Precisely edit a file by replacing old_text with new_text."""
    try:
        path = Path(file_path).expanduser().resolve()
        
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        if old_text not in content:
            return {"status": "error", "error": "Old text not found in file"}
        
        new_content = content.replace(old_text, new_text, 1)
        
        with open(path, 'w', encoding='utf-8') as f:
            f.write(new_content)
        
        return {
            "status": "success",
            "message": "File edited successfully"
        }
    except Exception as e:
        logger.error(f"Edit file error: {e}")
        return {"status": "error", "error": str(e)}


def search_workspace_files(pattern: str, base_dir: str = "~", max_results: int = 30) -> Dict[str, Any]:
    """Search for files matching a pattern in the workspace."""
    try:
        base_path = Path(base_dir).expanduser().resolve()
        results = []
        
        for path in base_path.rglob(pattern.replace("*", "")):
            if path.is_file():
                rel_path = str(path.relative_to(base_path))
                results.append(rel_path)
                
                if len(results) >= max_results:
                    break
        
        return {
            "status": "success",
            "message": f"Found {len(results)} files",
            "data": results
        }
    except Exception as e:
        logger.error(f"Search files error: {e}")
        return {"status": "error", "error": str(e)}


def grep_workspace(query: str, base_dir: str = "~", file_pattern: str = "") -> Dict[str, Any]:
    """Search for text content in workspace files."""
    try:
        base_path = Path(base_dir).expanduser().resolve()
        results = []
        
        for path in base_path.rglob(file_pattern or "*"):
            if not path.is_file():
                continue
            
            try:
                with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                    for line_num, line in enumerate(f, 1):
                        if query.lower() in line.lower():
                            rel_path = str(path.relative_to(base_path))
                            results.append({
                                "file": rel_path,
                                "line": line_num,
                                "content": line.strip()
                            })
                            if len(results) >= 50:
                                break
            except (PermissionError, UnicodeDecodeError):
                continue
                
            if len(results) >= 50:
                break
        
        return {
            "status": "success",
            "message": f"Found {len(results)} matches",
            "data": results[:20]  # Return first 20 results
        }
    except Exception as e:
        logger.error(f"Grep error: {e}")
        return {"status": "error", "error": str(e)}
