import os
import subprocess
import sys
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

MODULE_FILES = [
    "state.js",
    "audio.js",
    "hotkeys.js",
    "telemetry.js",
]


def test_module_files_exist():
    """Verify extracted module files physically exist in static/js/modules."""
    from alfa.dashboard.app import STATIC_DIR

    modules_dir = Path(STATIC_DIR) / "js" / "modules"
    assert modules_dir.exists() and modules_dir.is_dir(), "static/js/modules directory does not exist"

    for mod in MODULE_FILES:
        mod_path = modules_dir / mod
        assert mod_path.exists(), f"Module file {mod} does not exist"
        assert mod_path.stat().st_size > 50, f"Module file {mod} is empty or too small"


def test_modules_line_count_limit():
    """Verify each module file adheres to the architecture constraint (< 1,500 lines)."""
    from alfa.dashboard.app import STATIC_DIR

    modules_dir = Path(STATIC_DIR) / "js" / "modules"
    for mod in MODULE_FILES:
        mod_path = modules_dir / mod
        if mod_path.exists():
            lines = mod_path.read_text(encoding="utf-8").splitlines()
            assert len(lines) < 1500, f"Module {mod} exceeds 1500 lines ({len(lines)} lines)"


def test_modules_served_via_fastapi():
    """Verify FastAPI app serves each module with HTTP 200 and javascript content-type."""
    from alfa.dashboard.app import app

    client = TestClient(app)
    for mod in MODULE_FILES:
        route = f"/static/js/modules/{mod}"
        res = client.get(route)
        assert res.status_code == 200, f"Failed serving {route}: status {res.status_code}"
        content_type = res.headers.get("content-type", "")
        assert "javascript" in content_type, f"Expected javascript content-type for {route}, got {content_type}"
        assert len(res.content) > 0


def test_index_html_includes_module_scripts():
    """Verify templates/index.html loads module scripts before app.js."""
    from alfa.dashboard.app import TEMPLATES_DIR

    index_path = Path(TEMPLATES_DIR) / "index.html"
    assert index_path.exists(), "templates/index.html does not exist"
    content = index_path.read_text(encoding="utf-8")

    app_js_pos = content.find("/static/js/app.js")
    assert app_js_pos != -1, "app.js is missing from index.html"

    for mod in MODULE_FILES:
        script_tag = f"/static/js/modules/{mod}"
        mod_pos = content.find(script_tag)
        assert mod_pos != -1, f"Missing script tag for {script_tag} in index.html"
        assert mod_pos < app_js_pos, f"Module {mod} should be loaded before app.js in index.html"


def test_javascript_syntax_validity():
    """Verify JavaScript files have valid syntax using `node -c`."""
    from alfa.dashboard.app import STATIC_DIR

    js_dir = Path(STATIC_DIR) / "js"
    modules_dir = js_dir / "modules"

    files_to_check = [modules_dir / mod for mod in MODULE_FILES] + [js_dir / "app.js"]

    for f in files_to_check:
        assert f.exists(), f"File {f} does not exist for syntax check"
        res = subprocess.run(
            ["node", "-c", str(f)],
            capture_output=True,
            text=True
        )
        assert res.returncode == 0, f"Syntax error in {f.name}:\n{res.stderr}"
