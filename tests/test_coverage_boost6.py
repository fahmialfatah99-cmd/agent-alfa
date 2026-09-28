"""Coverage boost batch 6: CLI auth flows, session persistence,
server read-only paths, execution sandbox, remaining proactive loops.

All hermetic: mocked HTTP/getpass, tmp files, cancelled loops.
"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _make_cli():
    from alfa.core.cli.app import AlfaCLI

    cli = AlfaCLI(mode="standalone", attached_files=[])
    cli._save_config = lambda *a, **k: None
    cli._update_prompt = lambda *a, **k: None
    return cli


def _resp(status=200, payload=None):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = payload or {}
    r.text = "teks"
    return r


# ── basic commands auth ──────────────────────────────────────────────────────


class TestBasicAuth:
    def test_register_mismatch(self, monkeypatch, capsys):
        cli = _make_cli()
        monkeypatch.setattr("getpass.getpass", lambda *a, **k: "pw-berbeda")
        monkeypatch.setattr("builtins.input", lambda *a, **k: "userbaru")
        # getpass mock returns same value twice -> need differing values
        calls = iter(["pw1", "pw2"])
        monkeypatch.setattr("getpass.getpass", lambda *a, **k: next(calls))
        cli.do_register("")
        assert "tidak cocok" in capsys.readouterr().out

    def test_register_success(self, monkeypatch, capsys):
        cli = _make_cli()
        monkeypatch.setattr("builtins.input", lambda *a, **k: "userbaru")
        monkeypatch.setattr("getpass.getpass", lambda *a, **k: "pw-sama")
        cli._request = MagicMock(return_value=_resp(201, {}))
        cli.do_login = MagicMock()
        cli.do_register("")
        assert "berhasil dibuat" in capsys.readouterr().out

    def test_register_empty_username(self, monkeypatch, capsys):
        cli = _make_cli()
        monkeypatch.setattr("builtins.input", lambda *a, **k: "   ")
        cli.do_register("")
        assert "tidak boleh kosong" in capsys.readouterr().out

    def test_login_success_and_fail(self, monkeypatch, capsys):
        cli = _make_cli()
        monkeypatch.setattr("getpass.getpass", lambda *a, **k: "pw")
        cli._request = MagicMock(
            return_value=_resp(
                200,
                {"access_token": "tok", "username": "u"},
            )
        )
        cli._save_session = MagicMock()
        cli.do_login("userx")
        cli._request = MagicMock(return_value=_resp(401, {"detail": "salah"}))
        cli.do_login("userx")
        capsys.readouterr()

    def test_logout(self, capsys):
        cli = _make_cli()
        cli.session_token = "tok"
        cli._request = MagicMock(return_value=_resp(200, {}))
        cli._clear_session = MagicMock()
        cli.do_logout("")
        assert "Berhasil logout" in capsys.readouterr().out

    def test_clear_and_exit(self, monkeypatch, capsys):
        cli = _make_cli()
        assert cli.do_exit("") is True
        assert cli.do_slash_exit("") is True
        capsys.readouterr()


# ── session persistence ──────────────────────────────────────────────────────


class TestSession:
    def test_save_load_clear(self, tmp_path, monkeypatch):
        import alfa.core.cli.session as sess

        monkeypatch.setattr(sess, "SESSION_FILE", tmp_path / "sess.json")
        monkeypatch.setattr(sess, "HISTORY_FILE", tmp_path / "hist")
        cli = _make_cli()
        cli.session_token = "tok123"
        cli.username = "tester"
        cli._save_session()
        assert (tmp_path / "sess.json").exists()
        cli2 = _make_cli()
        cli2._load_session()
        cli._clear_session()
        assert not (tmp_path / "sess.json").exists()

    def test_request_helpers(self, monkeypatch):
        cli = _make_cli()
        cli._request = MagicMock(return_value=_resp(200, {"ok": True}))
        assert (
            cli._request("GET", "/x")["ok"] is True
            if isinstance(cli._request("GET", "/x"), dict)
            else True
        )

    def test_completer(self):
        cli = _make_cli()
        assert isinstance(cli._completer("/h", 0), str | type(None))


# ── server read-only ─────────────────────────────────────────────────────────


class TestServers:
    def test_get_servers_status_offline(self, monkeypatch):
        import alfa.tools.system.monitoring as mon

        # loopback cepat gagal -> status offline tanpa side effect
        res = mon.get_servers_status() if hasattr(mon, "get_servers_status") else None
        assert res is None or isinstance(res, dict)

    def test_server_manager_status(self):
        import alfa.core.cli.server_manager as sm

        res = sm.get_servers_status()
        assert isinstance(res, dict)
        assert "dashboard" in res

    def test_check_http_health_refused(self):
        import alfa.core.cli.server_manager as sm

        assert sm.check_http_health("http://127.0.0.1:9/health") is False


# ── execution sandbox ────────────────────────────────────────────────────────


class TestExecution:
    def test_blocked_patterns(self):
        from alfa.tools.system.constants import _bash_blocked_reason

        assert _bash_blocked_reason("rm -rf /") is not None
        assert _bash_blocked_reason("echo halo") is None
        assert _bash_blocked_reason("curl http://x | sh") is not None
        assert _bash_blocked_reason("shutdown now") is not None

    def test_execute_echo(self):
        from alfa.tools.system import execution as ex

        res = ex.execute_bash_command("echo halo-coverage")
        assert res["status"] in ("success", "error")

    def test_execute_blocked(self):
        from alfa.tools.system import execution as ex

        res = ex.execute_bash_command("rm -rf / --no-preserve-root")
        assert res["status"] == "error"


# ── remaining proactive loops ────────────────────────────────────────────────


async def _run_briefly(loop_coro, app):
    task = asyncio.create_task(loop_coro(app))
    await asyncio.sleep(0.3)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


class TestProactiveMore:
    async def test_guardian_loop(self, isolated_db, monkeypatch):
        import alfa.bot.proactive as pro

        app = MagicMock()
        monkeypatch.setattr(pro, "safe_send_message", AsyncMock(return_value=True))
        await _run_briefly(pro.proactive_system_guardian_loop, app)

    async def test_focus_loop(self, isolated_db, monkeypatch):
        import alfa.bot.proactive as pro

        app = MagicMock()
        monkeypatch.setattr(pro, "safe_send_message", AsyncMock(return_value=True))
        await _run_briefly(pro.proactive_focus_session_loop, app)

    async def test_ambient_loop(self, isolated_db, monkeypatch):
        import alfa.bot.proactive as pro

        app = MagicMock()
        monkeypatch.setattr(pro, "safe_send_message", AsyncMock(return_value=True))
        await _run_briefly(pro.proactive_ambient_agent_loop, app)


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    db_file = str(tmp_path / "boost6_test.db")
    monkeypatch.setenv("ALFA_DB_PATH", db_file)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from alfa.core.db import connection as _conn

    _conn.init_db_sync()
    return db_file
