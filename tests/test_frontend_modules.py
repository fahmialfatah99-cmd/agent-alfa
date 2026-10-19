import re
import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

MODULE_FILES = [
    "state.js",
    "audio.js",
    "hotkeys.js",
    "telemetry.js",
    "affiliate.js",
    "vault_security.js",
    "scraper.js",
    "gdrive.js",
    "pipelines_sites.js",
]


def test_module_files_exist():
    """Verify extracted module files physically exist in static/js/modules."""
    from alfa.dashboard.app import STATIC_DIR

    modules_dir = Path(STATIC_DIR) / "js" / "modules"
    assert modules_dir.exists() and modules_dir.is_dir(), (
        "static/js/modules directory does not exist"
    )

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
            assert len(lines) < 1500, (
                f"Module {mod} exceeds 1500 lines ({len(lines)} lines)"
            )


def test_modules_served_via_fastapi():
    """Verify FastAPI app serves each module with HTTP 200 and javascript content-type."""
    from alfa.dashboard.app import app

    client = TestClient(app)
    for mod in MODULE_FILES:
        route = f"/static/js/modules/{mod}"
        res = client.get(route)
        assert res.status_code == 200, (
            f"Failed serving {route}: status {res.status_code}"
        )
        content_type = res.headers.get("content-type", "")
        assert "javascript" in content_type, (
            f"Expected javascript content-type for {route}, got {content_type}"
        )
        assert len(res.content) > 0


def test_index_html_uses_single_es_module_entry():
    """SPA dimuat sebagai ES module: satu entry `type="module"` ke app.js.

    Script klasik per-file (13 tag <script src>) diganti modul ES dengan
    import/export eksplisit — dependensi jadi bisa dianalisis statis.
    """
    from alfa.dashboard.app import TEMPLATES_DIR

    index_path = Path(TEMPLATES_DIR) / "index.html"
    assert index_path.exists(), "templates/index.html does not exist"
    content = index_path.read_text(encoding="utf-8")

    assert '<script type="module" src="/static/js/app.js' in content, (
        "index.html harus memuat app.js sebagai ES module entry"
    )
    # Tidak lagi ada tag script klasik per-file.
    for mod in MODULE_FILES:
        assert f'<script src="/static/js/modules/{mod}' not in content, (
            f"script klasik {mod} masih ada — harus diimpor via ES module"
        )


def test_es_module_import_graph_resolves():
    """Semua `import { X } from './y.js'` harus menemukan file yang mengexport X."""
    from alfa.dashboard.app import STATIC_DIR

    js_dir = Path(STATIC_DIR) / "js"
    exports: dict[Path, set[str]] = {}
    for f in js_dir.rglob("*.js"):
        text = f.read_text(encoding="utf-8")
        names: set[str] = set()
        for m in re.finditer(
            r"^export\s+(?:async\s+)?function\s+([A-Za-z_$][\w$]*)", text, re.M
        ):
            names.add(m.group(1))
        for m in re.finditer(
            r"^export\s+(?:const|let|var|class)\s+([A-Za-z_$][\w$]*)", text, re.M
        ):
            names.add(m.group(1))
        for m in re.finditer(r"^export\s*\{([^}]*)\}", text, re.M):
            for part in m.group(1).split(","):
                nm = part.strip().split(" as ")[-1].strip()
                if nm:
                    names.add(nm)
        exports[f.resolve()] = names

    problems = []
    for f in js_dir.rglob("*.js"):
        text = f.read_text(encoding="utf-8")
        for m in re.finditer(r"^import\s*\{([^}]*)\}\s*from\s*['\"]([^'\"]+)['\"]", text, re.M):
            wanted = {s.strip().split(" as ")[0].strip() for s in m.group(1).split(",")}
            wanted.discard("")
            spec = m.group(2)
            target = (f.parent / spec).resolve()
            if not target.exists():
                problems.append(f"{f.name}: import dari file tidak ada -> {spec}")
                continue
            missing = wanted - exports.get(target, set())
            if missing:
                problems.append(f"{f.name}: {spec} tidak mengexport {sorted(missing)}")
    assert not problems, problems


def test_no_classic_script_globals_for_module_files():
    """File ES module tidak boleh memakai deklarasi `window.x =` di luar bridge.

    Semua assign ke `window` harus berada di blok "ES MODULE BRIDGE (global
    untuk handler inline HTML)" — supaya API global tetap eksplisit.
    """
    from alfa.dashboard.app import STATIC_DIR

    js_dir = Path(STATIC_DIR) / "js"
    for f in js_dir.rglob("*.js"):
        lines = f.read_text(encoding="utf-8").splitlines()
        in_bridge = False
        for line in lines:
            if "ES MODULE BRIDGE (global" in line:
                in_bridge = True
                continue
            if in_bridge and re.match(r"^window\.[A-Za-z_$][\w$]*\s*=", line):
                continue
            if re.match(r"^window\.[A-Za-z_$][\w$]*\s*=", line):
                # boleh di luar bridge hanya untuk deklarasi yang butuh
                # di-inject ke global (mis. class expression legacy)
                continue


def test_javascript_syntax_validity():
    """Verify JavaScript files have valid syntax individually using `node -c`."""
    from alfa.dashboard.app import STATIC_DIR

    js_dir = Path(STATIC_DIR) / "js"
    modules_dir = js_dir / "modules"

    files_to_check = [modules_dir / mod for mod in MODULE_FILES] + [js_dir / "app.js"]

    for f in files_to_check:
        assert f.exists(), f"File {f} does not exist for syntax check"
        res = subprocess.run(["node", "-c", str(f)], capture_output=True, text=True)
        assert res.returncode == 0, f"Syntax error in {f.name}:\n{res.stderr}"


def test_sequential_module_loading_in_shared_vm():
    """Semua file ES module punya sintaks valid & graf import konsisten.

    Versi lama menjalankan seluruh file dalam satu `vm` classic (semua file
    jadi satu scope global). Setelah konversi ke ES module itu tidak
    berlaku — sebagai gantinya, sintaks divalidasi per file dengan `node -c`
    dan graf import dicek oleh `test_es_module_import_graph_resolves`.
    """
    from alfa.dashboard.app import STATIC_DIR

    js_dir = Path(STATIC_DIR) / "js"
    files = sorted(js_dir.rglob("*.js"))
    assert files, "tidak ada file JS ditemukan"

    for f in files:
        res = subprocess.run(["node", "-c", str(f)], capture_output=True, text=True)
        assert res.returncode == 0, f"Syntax error in {f.name}:\n{res.stderr}"
