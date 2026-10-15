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

    src = inspect.getsource(t.run_agent_turn)
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
    assert rep["remaining"] == rep["budget_limit"] - rep["total_tokens"]
    assert "by_key" in rep and "warn" in rep


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
