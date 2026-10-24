"""Uji fitur sesi penguatan: greeting, honesty, slug, breaker, budget, digest, sites.

Hermetik: tanpa network, tanpa DB produksi (isolated_db / mock).
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    db_file = str(tmp_path / "feat_test.db")
    monkeypatch.setenv("ALFA_DB_PATH", db_file)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from alfa.core.db import connection as _conn

    _conn.init_db_sync()
    import alfa.core.db.connection as _c2

    monkeypatch.setattr(_c2, "_DB_PATH", db_file, raising=False)
    return db_file


# --- greeting fast-path -----------------------------------------------------
def test_greeting_matcher():
    from alfa.bot.handlers import greeting_reply

    for g in ["halo", "Halo!", "  HALO  ", "hai", "selamat pagi", "tes", "makasih", "siap"]:
        assert greeting_reply(g) is not None, g
    for t in ["halo tolong screenshot", "oke buatkan laporan", "screenshot layar", "", "halo, apa itu swarm?"]:
        assert greeting_reply(t) is None, t


@pytest.mark.asyncio
async def test_greeting_bypasses_agent(monkeypatch):
    import alfa.bot.handlers as h
    import alfa.bot.telegram_bot as bot

    monkeypatch.setattr(bot, "is_authorized", lambda uid: True)
    u = MagicMock()
    u.effective_user.id = 1
    u.effective_chat.id = 1
    u.message.text = "halo"
    c = MagicMock()
    c.bot.send_message = AsyncMock(return_value=MagicMock(message_id=1))
    turn = AsyncMock(return_value="x")
    with patch.object(h, "_run_agent_turn", turn):
        with patch.object(h.database, "save_chat_message", new=AsyncMock()):
            await h.handle_text_message(u, c)
    assert not turn.called


# --- thought strip ----------------------------------------------------------
def test_strip_thought_blocks():
    from alfa.bot.helpers import strip_thought_blocks

    assert strip_thought_blocks("halo") == "halo"
    dirty = "<thought>\nrahasia dapur\n</thought>\n\nJawaban **asli**."
    assert strip_thought_blocks(dirty) == "Jawaban **asli**."
    code = "```python\nx = '<thought> bukan tag'\n```"
    # tag dalam blok kode tanpa penutup tidak disentuh
    assert "<thought>" in strip_thought_blocks(code)


# --- honesty block ----------------------------------------------------------
def test_honesty_block_wired():
    import alfa.bot.config as c

    assert "SEBAGIAN" in c.HONESTY_BLOCK and "neural" in c.HONESTY_BLOCK.lower()
    import inspect

    import alfa.bot.turn_executor as t

    # Refactor pipeline: blok dikawal di helper tahap-6 (dipanggil setiap giliran)
    src = inspect.getsource(t._build_system_instruction)
    assert "HONESTY_BLOCK" in src


# --- smart slug -------------------------------------------------------------
def test_smart_slug():
    from alfa.swarm.workspace_hygiene import smart_slug

    assert smart_slug("tolong buatin landing page nike promo dong") == "landing-page-nike-promo"
    s = smart_slug("buatkan script monitoring RAM dan jalankan")
    assert "buatkan" not in s and len(s) <= 28
    assert smart_slug("") == "proyek"
    assert smart_slug("!!!") == "proyek"


# --- circuit breaker --------------------------------------------------------
def test_provider_dead_streak():
    from alfa.swarm.engine import _provider_dead_streak as f

    dead = {"status": "error", "tool_output": "SEMUA provider gagal (kuota) — batal", "execution_summary": ""}
    ok = {"status": "success", "tool_output": "ok", "execution_summary": "ok"}
    assert f([]) == "" and f([dead, dead]) == ""
    assert f([dead, dead, dead]) != ""
    assert f([ok, dead, dead, dead]) != ""
    assert f([dead, ok, dead]) == ""


# --- budget monitor (tanpa blokir) ------------------------------------------
def test_budget_report_shape(isolated_db):
    from alfa.core.rate_limiter import get_budget_report

    rep = get_budget_report(1)
    assert rep["status"] == "ok"
    if rep["budget_limit"] > 0:
        assert rep["remaining"] == max(0, rep["budget_limit"] - rep["total_tokens"])
    else:
        # Semantik baru: budget_limit 0 = tanpa batas (unlimited), sentinel -1
        assert rep["remaining"] == -1
    assert "by_key" in rep and "warn" in rep


def test_reset_user_usage_today(isolated_db):
    from alfa.core.db.connection import get_sync_db
    from alfa.core.rate_limiter import get_user_usage_today, reset_user_usage_today

    uid = 424242
    with get_sync_db() as conn:
        conn.execute(
            "INSERT INTO api_token_usage (provider, total_tokens, user_id) VALUES (?, ?, ?)",
            ("gemini", 50000, uid),
        )
        conn.commit()

    usage = get_user_usage_today(uid)
    assert usage["total_tokens"] >= 50000

    deleted = reset_user_usage_today(uid)
    assert deleted >= 1

    usage_after = get_user_usage_today(uid)
    assert usage_after["total_tokens"] == 0
    assert usage_after["total_calls"] == 0


# --- digest helpers ----------------------------------------------------------
def test_digest_parsing_and_empty():
    import asyncio

    import alfa.bot.wa_digest as d

    assert d._parse_ts("14/10/2026, 11.49.13") is not None
    assert d._parse_ts("acak") is None
    assert d.digest_enabled() in (True, False)
    assert isinstance(d.digest_hours(), list)
    with patch("alfa.tools.system.integrations._wa_api", return_value={"status": "error", "message": "x"}):
        assert asyncio.run(d.build_digest_text()) != ""


# --- sites registry ----------------------------------------------------------
def test_sites_detect_and_tools(tmp_path):
    import alfa.tools.system.sites as s

    proj = tmp_path / "demoapp"
    (proj / "static").mkdir(parents=True)
    (proj / "static" / "index.html").write_text("<title>Demo</title>")
    (proj / "app.py").write_text("from fastapi import FastAPI\napp = FastAPI()")
    info = s._detect_stack(str(proj))
    assert info["has_backend"] and info["title"] == "Demo"


def test_honesty_scanner_marks_dummy(tmp_path):
    from alfa.tools.system.management import audit_project_honesty

    proj = tmp_path / "p"
    proj.mkdir()
    (proj / "route.ts").write_text('const ip = "104.21." + Math.floor(Math.random() * 200); // api hasil')
    (proj / "ok.py").write_text("print('halo')")
    r = audit_project_honesty(path=str(proj))
    assert r["status"] == "success"
    assert any(x["pola"] == "random-di-data" for x in r["suspects"])


# --- dashboard: galeri situs & budget ---------------------------------------
def test_dashboard_sites_and_budget(monkeypatch):
    monkeypatch.setenv("DASHBOARD_HOST", "127.0.0.1")
    monkeypatch.setenv("DASHBOARD_AUTH_TOKEN", "")
    from fastapi.testclient import TestClient

    from alfa.dashboard.routes import auth as auth_mod

    auth_mod.DASHBOARD_AUTH_TOKEN = ""
    from alfa.dashboard.app import app

    c = TestClient(app)
    r = c.get("/api/sites")
    assert r.status_code == 200
    assert r.json()["status"] == "success"
    assert isinstance(r.json()["sites"], list)
    r = c.get("/api/budget/today")
    assert r.status_code == 200
    assert "total_tokens" in r.json()
    r = c.post("/api/budget/reset")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    r = c.post("/api/sites/slug-tak-ada/start")
    assert r.status_code in (404, 500)
    r = c.post("/api/sites/x/bakar")
    assert r.status_code == 400


# --- model mati ditolak di semua jalur tulis --------------------------------
def test_dead_models_rejected(isolated_db):
    from alfa.core.db import keys as _keys

    assert _keys.is_dead_model("m1")
    assert _keys.is_dead_model("gemini-3.6-flash")
    assert not _keys.is_dead_model("gemini-3.5-flash-lite")
    assert _keys.update_api_key_model(9999, "m1") is False


# --- pipeline: 4 template + vars override ------------------------------------
def test_pipeline_templates_and_overrides(tmp_path, monkeypatch):
    """Hermetik: sandbox PIPELINE_DIR sendiri; storage/pipelines repo berisi
    data mesin (tidak dikomit), jadi CI fresh tidak boleh bergantung padanya."""
    from alfa.pipelines import engine as pipe

    monkeypatch.setattr(pipe, "PIPELINE_DIR", str(tmp_path))
    templates = [
        {
            "id": "riset_dan_ringkas",
            "name": "Riset lalu Ringkas",
            "description": "Cari topik di web -> rangkum 3 poin -> simpan ke sandbox.",
            "vars": {"topik": "AI Indonesia", "out_dir": "/dev/shm/alfa_sandbox/pipeline_out"},
            "steps": [
                {"id": "cari", "type": "tool", "tool": "web_search",
                 "args": {"query": "berita {{topik}} terbaru"}},
                {"id": "rangkum", "type": "prompt",
                 "text": "Ringkas hasil pencarian ini menjadi 3 poin utama:\n{{cari}}",
                 "depends_on": ["cari"]},
                {"id": "simpan", "type": "tool", "tool": "write_local_file",
                 "args": {"file_path": "{{out_dir}}/ringkasan_{{topik}}.md",
                          "content": "# Ringkasan {{topik}}\n\n{{rangkum}}"},
                 "depends_on": ["rangkum"]},
            ],
        },
        {
            "id": "cek_kesehatan",
            "name": "Cek Kesehatan Server",
            "description": "Ambil telemetri -> ringkas status + 3 tindakan bila ada anomali -> simpan.",
            "vars": {"out_dir": "/dev/shm/alfa_sandbox/pipeline_out"},
            "steps": [
                {"id": "telemetri", "type": "tool", "tool": "get_system_stats", "args": {}},
                {"id": "ringkas", "type": "prompt",
                 "text": "Dari telemetri berikut, jawab SINGKAT: status (SEHAT/WASPADA/KRITIS) "
                         "+ maksimal 3 tindakan konkret bila tidak sehat. Bahasa Indonesia:\n{{telemetri}}",
                 "depends_on": ["telemetri"]},
                {"id": "simpan", "type": "tool", "tool": "write_local_file",
                 "args": {"file_path": "{{out_dir}}/kesehatan_server.md",
                          "content": "# Kesehatan Server\n\n{{ringkas}}"},
                 "depends_on": ["ringkas"]},
            ],
        },
        {
            "id": "audit_situs",
            "name": "Audit Galeri Situs",
            "description": "Daftar situs terkelola -> nilai kesehatan tiap situs -> simpan laporan.",
            "vars": {"out_dir": "/dev/shm/alfa_sandbox/pipeline_out"},
            "steps": [
                {"id": "daftar", "type": "tool", "tool": "list_managed_sites", "args": {}},
                {"id": "nilai", "type": "prompt",
                 "text": "Dari data registry situs berikut, nilai tiap situs "
                         "(jalan/mati/butuh perhatian) dan tulis 3 rekomendasi konkret:\n{{daftar}}",
                 "depends_on": ["daftar"]},
                {"id": "simpan", "type": "tool", "tool": "write_local_file",
                 "args": {"file_path": "{{out_dir}}/audit_situs.md",
                          "content": "# Audit Galeri Situs\n\n{{nilai}}"},
                 "depends_on": ["nilai"]},
            ],
        },
        {
            "id": "arsip_outputs",
            "name": "Arsip Outputs",
            "description": "Arsipkan folder outputs swarm + catat ukuran hasil.",
            "vars": {"src": "/dev/shm/alfa_sandbox/swarm_outputs",
                     "dst": "/dev/shm/alfa_sandbox/swarm_outputs.zip"},
            "steps": [
                {"id": "arsip", "type": "tool", "tool": "execute_bash_command",
                 "args": {"command": "zip -qr {{dst}} {{src}} -x '*/node_modules/*' "
                                     "'*/__pycache__/*' && du -h {{dst}}"}},
                {"id": "catat", "type": "tool", "tool": "write_local_file",
                 "args": {"file_path": "/dev/shm/alfa_sandbox/pipeline_out/arsip_terakhir.md",
                          "content": "# Arsip Outputs\n\n{{arsip}}"},
                 "depends_on": ["arsip"]},
            ],
        },
    ]
    for t in templates:
        pipe.save_pipeline(t)

    ids = {p["id"] for p in pipe.list_pipelines()}
    assert {"riset_dan_ringkas", "audit_situs", "cek_kesehatan", "arsip_outputs"} <= ids
    data = pipe.load_pipeline("cek_kesehatan")
    assert len(data["steps"]) == 3
