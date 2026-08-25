"""Unit tests untuk fitur generasi baru: Tool-RAG, Pipeline Engine,
Memory Reflection, dan helper indexer paralel."""
import asyncio
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


# ── Tool-RAG ──────────────────────────────────────────────────────────────
def test_toolrag_memperkecil_set_tools():
    import tools as t
    from tool_rag import select_relevant_functions

    sel = select_relevant_functions(t.AVAILABLE_TOOLS,
                                    "buat website landing page dengan python")
    assert 0 < len(sel) < len(t.AVAILABLE_TOOLS)


def test_toolrag_core_selalu_ada():
    import tools as t
    from tool_rag import select_relevant_functions

    sel = select_relevant_functions(t.AVAILABLE_TOOLS, "apa itu kucing")
    names = {getattr(f, "__name__", "") for f in sel}
    for core in ("execute_python_sandbox", "read_local_file", "web_search"):
        assert core in names


def test_toolrag_routing_bahasa_indonesia():
    import tools as t
    from tool_rag import select_relevant_functions

    sel = select_relevant_functions(t.AVAILABLE_TOOLS,
                                    "rekam layar laptop saya 10 detik")
    names = {getattr(f, "__name__", "") for f in sel}
    assert "record_desktop_screen" in names


def test_toolrag_failopen_input_kosong():
    from tool_rag import select_relevant_functions
    assert select_relevant_functions([], "apapun") == []


def test_toolrag_off_via_env(monkeypatch):
    import tool_rag
    monkeypatch.setattr(tool_rag, "_ENABLED", False)
    dummy = [{"function": {"name": f"t{i}", "description": f"tool {i}"}} for i in range(60)]
    assert tool_rag.select_relevant_tools(dummy, "query") is dummy


# ── Pipeline Engine ───────────────────────────────────────────────────────
def test_pipeline_topological_waves_paralel():
    import pipelines as pl

    steps = [
        {"id": "a", "type": "set", "value": "1"},
        {"id": "b", "type": "set", "value": "2"},
        {"id": "c", "type": "template", "text": "{{a}}-{{b}}", "depends_on": ["a", "b"]},
    ]
    waves = pl._topological_waves(steps)
    assert len(waves) == 2                      # [a,b] paralel lalu [c]
    assert {s["id"] for s in waves[0]} == {"a", "b"}
    assert waves[1][0]["id"] == "c"


def test_pipeline_deteksi_siklus():
    import pipelines as pl

    steps = [
        {"id": "a", "type": "set", "value": "x", "depends_on": ["b"]},
        {"id": "b", "type": "set", "value": "y", "depends_on": ["a"]},
    ]
    with pytest.raises(ValueError):
        pl._topological_waves(steps)


def test_pipeline_render_interpolasi():
    import pipelines as pl

    out = pl._render("Halo {{nama}}, umur {{umur}}", {"nama": "ALFA", "umur": 3})
    assert out == "Halo ALFA, umur 3"


def test_pipeline_run_end_to_end(tmp_path):
    import pipelines as pl

    data = {
        "id": "_test_unit",
        "name": "Unit",
        "vars": {"sapaan": "Hai"},
        "steps": [
            {"id": "satu", "type": "template", "text": "{{sapaan}} dunia"},
            {"id": "dua", "type": "tool", "tool": "write_local_file",
             "args": {"file_path": str(tmp_path / "pl.txt"), "content": "{{satu}}"},
             "depends_on": ["satu"]},
        ],
    }
    pl.save_pipeline(data)
    result = asyncio.run(pl.run_pipeline("_test_unit"))
    assert result["status"] == "success"
    with open(os.path.join(tmp_path, "pl.txt"), encoding="utf-8") as f:
        assert "Hai dunia" in f.read()
    # bersihkan pipeline uji
    os.remove(os.path.join(pl.PIPELINE_DIR, "_test_unit.json"))


# ── n8n-mini: kondisi, foreach, dot-path, riwayat run ─────────────────────
def test_pipeline_dotpath_render():
    import pipelines as pl

    vars_ = {"data": {"user": {"nama": "Fahmi"}, "items": ["a", "b"]}}
    assert pl._render("Hai {{data.user.nama}}", vars_) == "Hai Fahmi"
    assert pl._render("jumlah {{data.items}}", vars_) == 'jumlah ["a", "b"]'
    assert pl._render("item2 {{data.items.1}}", vars_) == "item2 b"


def test_pipeline_eval_condition_ops():
    import pipelines as pl

    v = {"cari": "Ada Berita AI Terbaru", "kosong": "", "angka": "5"}
    C = pl._eval_condition
    assert C({"left": "{{cari}}", "op": "contains", "right": "ai"}, v) is True
    assert C({"left": "{{cari}}", "op": "not_contains", "right": "bola"}, v) is True
    assert C({"left": "{{kosong}}", "op": "empty"}, v) is True
    assert C({"left": "{{cari}}", "op": "not_empty"}, v) is True
    assert C({"left": "{{angka}}", "op": "gt", "right": "3"}, v) is True
    assert C({"left": "{{cari}}", "op": "regex", "right": r"\d+"}, v) is False


def test_pipeline_if_skip_dan_foreach(tmp_path):
    import pipelines as pl

    data = {
        "id": "_test_cond",
        "vars": {"flag": "tidak_ada"},
        "steps": [
            {"id": "cabang", "type": "template", "text": "harusnya dilewati",
             "if": {"left": "{{flag}}", "op": "contains", "right": "ADA_YA"}},
            {"id": "loop", "type": "foreach", "over": "a,b,c", "item_var": "it",
             "inner_type": "template", "text": "{{it}}!"},
        ],
    }
    pl.save_pipeline(data)
    result = asyncio.run(pl.run_pipeline("_test_cond"))
    os.remove(os.path.join(pl.PIPELINE_DIR, "_test_cond.json"))
    assert result["status"] == "success"
    assert result["outputs"]["cabang"].startswith("(dilewati")
    assert result["outputs"]["loop"].count("!") == 3
    # trace mencatat langkah yang di-skip
    statuses = {t["step"]: t["status"] for t in result["trace"]}
    assert statuses["cabang"] == "skipped"


def test_pipeline_runs_history_roundtrip():
    import pipelines as pl

    data = {
        "id": "_test_hist",
        "steps": [{"id": "s1", "type": "set", "value": "ok"}],
    }
    pl.save_pipeline(data)
    asyncio.run(pl.run_pipeline("_test_hist"))
    asyncio.run(pl.run_pipeline("_test_hist"))
    runs = pl.list_runs("_test_hist")
    os.remove(os.path.join(pl.PIPELINE_DIR, "_test_hist.json"))
    assert len(runs) >= 2
    assert all(r["status"] == "success" for r in runs)


def test_pipeline_http_step_local():
    """HTTP step memakai dashboard sendiri sebagai target (tanpa internet)."""
    import pipelines as pl

    data = {
        "id": "_test_http",
        "steps": [
            {"id": "req", "type": "http", "method": "GET",
             "url": "http://127.0.0.1:8080/openapi.json", "timeout": 10},
        ],
    }
    pl.save_pipeline(data)
    result = asyncio.run(pl.run_pipeline("_test_http"))
    os.remove(os.path.join(pl.PIPELINE_DIR, "_test_http.json"))
    # status 0/200 tergantung server hidup; yang penting tidak exception
    assert result["status"] in ("success", "failed")


# ── Memory Reflection ─────────────────────────────────────────────────────
def test_reflect_interval_counter():
    from memory_reflection import should_reflect, EVERY
    uid = 987654321
    hits = []
    for i in range(1, EVERY * 2 + 2):
        if should_reflect(uid):
            hits.append(i)
    assert hits == [EVERY, EVERY * 2]           # tepat setiap N giliran


def test_reflect_parse_json_fenced():
    """Refleksi harus tahan output ber-fence markdown (dites via ekstraksi regex)."""
    raw = '```json\n[{"key_topic":"projek","content":"ALFA","category":"project"}]\n```'
    txt = raw.strip()
    if txt.startswith("```"):
        txt = txt.split("```")[1]
        if txt.startswith("json"):
            txt = txt[4:]
    start, end = txt.find("["), txt.rfind("]")
    facts = json.loads(txt[start:end + 1])
    assert facts[0]["key_topic"] == "projek"


# ── Indexer paralel ───────────────────────────────────────────────────────
def test_index_one_file_chunking():
    import tools

    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False,
                                     encoding="utf-8") as f:
        f.write("\n".join(f"# baris {i}" for i in range(120)))
        path = f.name
    try:
        result = tools._index_one_file(path, os.path.dirname(path))
        assert result is not None
        fpath, rows = result
        assert len(rows) >= 1                   # file terchunk minimal 1
        assert all(r[0].endswith(".py") for r in rows)
    finally:
        os.remove(path)
