"""Phase 6 coverage: CLI cursor UI, server manager, and app entrypoint.

Hermetic: PromptToolkit, subprocess, HTTP, filesystem, dan server lifecycle
di-mock. Tidak ada proses atau layanan nyata yang dijalankan.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from prompt_toolkit.completion import CompleteEvent
from prompt_toolkit.document import Document


class FakeConsole:
    def __init__(self):
        self.lines = []

    def print(self, *args, **kwargs):
        self.lines.append(args[0] if args else "")


# ---------------------------------------------------------------------------
# cursor_ui.py
# ---------------------------------------------------------------------------


def test_get_git_branch(monkeypatch):
    import alfa.core.cli.cursor_ui as cu

    monkeypatch.setattr(
        cu.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout="main\n"),
    )
    assert cu.get_git_branch() == "main"

    monkeypatch.setattr(
        cu.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=1, stdout=""),
    )
    assert cu.get_git_branch() == ""

    def boom(*a, **k):
        raise OSError("git hilang")  # noqa: TRY003

    monkeypatch.setattr(cu.subprocess, "run", boom)
    assert cu.get_git_branch() == ""


def test_completer_project_files_and_completions(monkeypatch, tmp_path):
    import alfa.core.cli.cursor_ui as cu

    monkeypatch.chdir(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("x", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "skip.js").write_text("x", encoding="utf-8")

    comp = cu.AlfaCursorCompleter(SimpleNamespace())
    files = comp._get_project_files()
    assert "src/app.py" in files
    assert all("node_modules" not in f for f in files)

    at = list(comp.get_completions(Document("lihat @app", 10), CompleteEvent()))
    assert any(getattr(c, "display_text", "") == "@src/app.py" for c in at)

    slash = list(comp.get_completions(Document("/he", 3), CompleteEvent()))
    assert any(c.text == "/help" for c in slash)

    none = list(comp.get_completions(Document("halo", 4), CompleteEvent()))
    assert none == []


def test_extract_modifications():
    from alfa.core.cli.cursor_ui import FilePatcher

    p = FilePatcher(console=FakeConsole())
    text = (
        "```python:src/a.py\nprint(1)\n```\n"
        "### File: `lib/b.py`\n```python\nprint(2)\n```\n"
        "```json\n{}\n```\n"
    )
    mods = p.extract_modifications(text)
    assert ("src/a.py", "print(1)") in mods
    assert ("lib/b.py", "print(2)") in mods
    assert all(not m[0].startswith("json") for m in mods)


def test_file_patcher_apply_existing_and_new(monkeypatch, tmp_path):
    import alfa.core.cli.cursor_ui as cu

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cu, "RICH_AVAILABLE", False)
    target = tmp_path / "a.py"
    target.write_text("lama\n", encoding="utf-8")

    answers = iter(["n", "y", "y", "n"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    patcher = cu.FilePatcher(console=FakeConsole())
    patcher.process_and_prompt("```python:a.py\nbaru\n```\n")
    assert target.read_text(encoding="utf-8") == "lama\n"

    patcher.process_and_prompt("```python:a.py\nbaru\n```\n")
    assert target.read_text(encoding="utf-8") == "baru"
    assert (tmp_path / ".alfa_backups" / "a.py.bak").exists()

    patcher.process_and_prompt("```python:sub/new.py\nisi\n```\n")
    assert (tmp_path / "sub" / "new.py").read_text(encoding="utf-8") == "isi"

    patcher.process_and_prompt("```python:other.py\nisi\n```\n")
    assert not (tmp_path / "other.py").exists()

    patcher.process_and_prompt("tidak ada perubahan")
    patcher.process_and_prompt("```python:a.py\nbaru\n```\n")


def test_file_patcher_identical_and_rich(monkeypatch, tmp_path):
    import alfa.core.cli.cursor_ui as cu

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cu, "RICH_AVAILABLE", True)
    target = tmp_path / "same.py"
    target.write_text("sama", encoding="utf-8")
    monkeypatch.setattr("builtins.input", lambda prompt="": "y")
    patcher = cu.FilePatcher(console=FakeConsole())
    patcher.process_and_prompt("```python:same.py\nsama\n```\n")
    assert not (tmp_path / ".alfa_backups" / "same.py.bak").exists()

    target.write_text("lama\n", encoding="utf-8")
    patcher.process_and_prompt("```python:same.py\nbaru\n```\n")
    assert target.read_text(encoding="utf-8") == "baru"


def test_apply_write_error(monkeypatch, tmp_path):
    import alfa.core.cli.cursor_ui as cu

    monkeypatch.setattr(
        cu.Path, "write_text", MagicMock(side_effect=OSError("disk")), raising=True
    )
    patcher = cu.FilePatcher(console=FakeConsole())
    patcher._apply_write(tmp_path / "x.py", None, "x", "x.py")
    monkeypatch.undo()


def test_render_cursor_banner(monkeypatch):
    import alfa.core.cli.cursor_ui as cu

    monkeypatch.setattr(cu, "RICH_AVAILABLE", True)
    monkeypatch.setattr(cu, "get_git_branch", lambda: "main")
    cli = SimpleNamespace(
        direct_ai=SimpleNamespace(provider="gemini", model="m"),
        console=FakeConsole(),
        mode="standalone",
    )
    cu.render_cursor_banner(cli)
    assert cli.console.lines

    monkeypatch.setattr(cu, "RICH_AVAILABLE", False)
    cli2 = SimpleNamespace(
        direct_ai=SimpleNamespace(provider="gemini", model="m"),
        console=None,
        mode="server",
    )
    cu.render_cursor_banner(cli2)


class FakePromptSession:
    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        FakePromptSession.instances.append(self)

    def prompt(self, *args, **kwargs):
        if kwargs.get("bottom_toolbar"):
            kwargs["bottom_toolbar"]()
        item = self.lines.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


class FakePatcher:
    def __init__(self, *a, **k):
        self.seen = []

    def process_and_prompt(self, text):
        self.seen.append(text)


def _run_loop(monkeypatch, lines, cli=None, rich=True):
    import alfa.core.cli.cursor_ui as cu

    FakePromptSession.instances = []
    FakePromptSession.lines = list(lines)

    def factory(**kwargs):
        inst = FakePromptSession(**kwargs)
        return inst

    monkeypatch.setattr(cu, "PromptSession", factory)
    monkeypatch.setattr(cu, "render_cursor_banner", lambda c: None)
    monkeypatch.setattr(cu, "FilePatcher", FakePatcher)
    monkeypatch.setattr(cu, "get_git_branch", lambda: "main")
    monkeypatch.setattr(cu, "RICH_AVAILABLE", rich)
    monkeypatch.setattr(cu, "HISTORY_FILE", Path("/tmp/opencode/cli-history-test.txt"))
    monkeypatch.setattr(cu.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout="", stderr=""))
    import alfa.core.cli.interactive_menu as menu

    monkeypatch.setattr(menu, "open_interactive_menu", lambda c: None)
    if cli is None:
        cli = SimpleNamespace(
            direct_ai=SimpleNamespace(provider="gemini", model="m"),
            console=FakeConsole() if rich else None,
            mode="standalone",
            attached_files=["a"],
            agent_mode=True,
            chat_history=[],
            default=lambda line: cli.default_lines.append(line),
            default_lines=[],
            do_slash_undo=lambda arg: cli.undo_calls.append(arg),
            undo_calls=[],
            do_slash_file=lambda arg: cli.file_calls.append(arg),
            file_calls=[],
        )
    cu.run_cursor_loop(cli)
    return cli


def test_run_cursor_loop_git_and_context(monkeypatch):

    cli = SimpleNamespace(
        direct_ai=SimpleNamespace(provider="gemini", model="m"),
        console=FakeConsole(),
        mode="standalone",
        attached_files=[],
        agent_mode=False,
        chat_history=[{"role": "assistant", "content": "```python:a.py\nx\n```"}],
        default=lambda line: cli.default_lines.append(line),
        default_lines=[],
        do_slash_undo=lambda arg: cli.undo_calls.append(arg),
        undo_calls=[],
        do_slash_file=lambda arg: cli.file_calls.append(arg),
        file_calls=[],
    )
    import alfa.core.cli.cursor_ui as cursor

    def diff_run(*a, **k):
        return SimpleNamespace(stdout="diff --git", stderr="")

    monkeypatch.setattr(cursor.subprocess, "run", diff_run)
    _run_loop(
        monkeypatch,
        [
            "/diff",
            "/commit pesan",
            "/undo 2",
            "/undo",
            "/add a.py",
            "/add",
            "/drop a.py",
            "/drop",
            "/files",
            "/context",
            "/menu",
            "pesan biasa",
            "/exit",
        ],
        cli=cli,
    )
    assert cli.undo_calls == ["2", ""]
    assert cli.file_calls == ["add a.py", "remove a.py", "list", "list"]
    assert cli.default_lines == ["pesan biasa"]


def test_run_cursor_loop_plain_and_diff_empty(monkeypatch):
    import alfa.core.cli.cursor_ui as cu

    monkeypatch.setattr(
        cu.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(stdout="", stderr="err"),
    )
    cli = _run_loop(monkeypatch, ["/diff", "quit"], rich=False)
    assert cli.default_lines == []


def test_run_cursor_loop_interrupts_and_errors(monkeypatch):

    cli = _run_loop(monkeypatch, [KeyboardInterrupt(), RuntimeError("x"), EOFError()])
    assert cli.default_lines == []

    cli2 = _run_loop(monkeypatch, [EOFError()])
    assert cli2.default_lines == []


# ---------------------------------------------------------------------------
# server_manager.py
# ---------------------------------------------------------------------------


def test_get_repo_root_and_venv(monkeypatch, tmp_path):
    import alfa.core.cli.server_manager as sm

    assert sm.get_repo_root().name
    (tmp_path / "venv" / "bin").mkdir(parents=True)
    (tmp_path / "venv" / "bin" / "python3").write_text("", encoding="utf-8")
    assert sm.get_venv_python(tmp_path).endswith("python3")

    (tmp_path / "venv" / "bin" / "python3").unlink()
    (tmp_path / "venv" / "bin" / "python").write_text("", encoding="utf-8")
    assert sm.get_venv_python(tmp_path).endswith("python")

    (tmp_path / "venv" / "bin" / "python").unlink()
    assert sm.get_venv_python(tmp_path) == sys.executable


def test_port_and_health(monkeypatch):
    import alfa.core.cli.server_manager as sm

    fake_sock = MagicMock()
    fake_sock.__enter__.return_value = fake_sock
    fake_sock.connect_ex.return_value = 0
    monkeypatch.setattr(sm.socket, "socket", lambda *a, **k: fake_sock)
    assert sm.is_port_in_use(8080) is True

    monkeypatch.setattr(
        sm.requests,
        "get",
        lambda *a, **k: SimpleNamespace(status_code=204),
    )
    assert sm.check_http_health("http://x") is True
    monkeypatch.setattr(
        sm.requests,
        "get",
        lambda *a, **k: SimpleNamespace(status_code=500),
    )
    assert sm.check_http_health("http://x") is False

    def boom(*a, **k):
        raise sm.requests.RequestException("down")

    monkeypatch.setattr(sm.requests, "get", boom)
    assert sm.check_http_health("http://x") is False


def test_start_dashboard_server(monkeypatch, tmp_path):
    import alfa.core.cli.server_manager as sm

    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(sm, "check_http_health", lambda url: True)
    ok, msg = sm.start_dashboard_server(tmp_path)
    assert ok is True and "Aktif" in msg

    monkeypatch.setattr(sm, "check_http_health", lambda url: False)
    ok, msg = sm.start_dashboard_server(tmp_path)
    assert ok is False and "tidak ditemukan" in msg

    script = tmp_path / "web_dashboard.py"
    script.write_text("", encoding="utf-8")
    monkeypatch.setattr(sm.subprocess, "Popen", lambda *a, **k: None)
    health = iter([False, True])
    monkeypatch.setattr(sm, "check_http_health", lambda url: next(health))
    ok, msg = sm.start_dashboard_server(tmp_path, wait_timeout=2)
    assert ok is True and "Berhasil" in msg

    monkeypatch.setattr(sm, "check_http_health", lambda url: False)
    ok, msg = sm.start_dashboard_server(tmp_path, wait_timeout=0)
    assert ok is False and "melebihi" in msg

    def popen_boom(*a, **k):
        raise OSError("spawn")

    monkeypatch.setattr(sm.subprocess, "Popen", popen_boom)
    ok, msg = sm.start_dashboard_server(tmp_path)
    assert ok is False and "Gagal" in msg


def test_start_telegram_bot(monkeypatch, tmp_path):
    import alfa.core.cli.server_manager as sm
    import alfa.core.config as config

    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(config, "env_file_paths", lambda: [])
    ok, msg = sm.start_telegram_bot(tmp_path)
    assert ok is False and "Token" in msg

    env = tmp_path / ".env"
    env.write_text("TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here\n", encoding="utf-8")
    ok, msg = sm.start_telegram_bot(tmp_path)
    assert ok is False

    env.write_text("TELEGRAM_BOT_TOKEN=abc\n", encoding="utf-8")
    monkeypatch.setattr(
        sm.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout="123\n"),
    )
    ok, msg = sm.start_telegram_bot(tmp_path)
    assert ok is True and "Aktif" in msg

    monkeypatch.setattr(
        sm.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=1, stdout=""),
    )
    ok, msg = sm.start_telegram_bot(tmp_path)
    assert ok is False and "bot.py" in msg

    (tmp_path / "bot.py").write_text("", encoding="utf-8")
    monkeypatch.setattr(sm.subprocess, "Popen", lambda *a, **k: None)
    ok, msg = sm.start_telegram_bot(tmp_path)
    assert ok is True and "Berhasil" in msg

    def boom(*a, **k):
        raise OSError("spawn")

    monkeypatch.setattr(sm.subprocess, "Popen", boom)
    ok, msg = sm.start_telegram_bot(tmp_path)
    assert ok is False and "Gagal" in msg


def test_check_9router_gateway(monkeypatch):
    import alfa.core.cli.server_manager as sm

    monkeypatch.setattr(sm, "check_http_health", lambda url: True)
    ok, msg = sm.check_9router_gateway()
    assert ok is True and "Aktif" in msg

    check = iter([False, True])
    monkeypatch.setattr(sm, "check_http_health", lambda url: next(check))
    monkeypatch.setattr(sm.shutil, "which", lambda name: "/usr/bin/9router")
    monkeypatch.setattr(sm.subprocess, "Popen", lambda *a, **k: None)
    monkeypatch.setattr(sm.time, "sleep", lambda s: None)
    ok, msg = sm.check_9router_gateway()
    assert ok is True and "Dinyalakan" in msg

    monkeypatch.setattr(sm, "check_http_health", lambda url: False)
    monkeypatch.setattr(sm.shutil, "which", lambda name: None)
    ok, msg = sm.check_9router_gateway()
    assert ok is False and "Offline" in msg

    def boom(*a, **k):
        raise OSError("spawn")

    monkeypatch.setattr(sm.shutil, "which", lambda name: "/bin/9router")
    monkeypatch.setattr(sm.subprocess, "Popen", boom)
    ok, msg = sm.check_9router_gateway()
    assert ok is False


def test_servers_status_and_stop(monkeypatch):
    import alfa.core.cli.server_manager as sm

    monkeypatch.setattr(sm, "check_http_health", lambda url: True)
    monkeypatch.setattr(
        sm.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout="777\n"),
    )
    status = sm.get_servers_status()
    assert status["dashboard"]["ok"] is True
    assert status["bot"]["ok"] is True

    monkeypatch.setattr(sm, "check_http_health", lambda url: False)
    monkeypatch.setattr(
        sm.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=1, stdout=""),
    )
    status = sm.get_servers_status()
    assert status["9router"]["ok"] is False

    def boom(*a, **k):
        raise OSError("pgrep")

    monkeypatch.setattr(sm.subprocess, "run", boom)
    status = sm.get_servers_status()
    assert status["bot"]["ok"] is False

    monkeypatch.setattr(
        sm.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=0),
    )
    assert sm.stop_all_servers() == {"dashboard": True, "bot": True}

    monkeypatch.setattr(sm.subprocess, "run", boom)
    assert sm.stop_all_servers() == {"dashboard": False, "bot": False}


def test_auto_start_all_servers(monkeypatch):
    import alfa.core.cli.server_manager as sm

    monkeypatch.setattr(sm, "get_repo_root", lambda: Path("/repo"))
    monkeypatch.setattr(sm, "start_dashboard_server", lambda root: (True, "dash"))
    monkeypatch.setattr(sm, "start_telegram_bot", lambda root: (False, "bot"))
    monkeypatch.setattr(sm, "check_9router_gateway", lambda: (True, "r9"))
    out = sm.auto_start_all_servers(verbose=True)
    assert out["dashboard"]["ok"] is True
    out = sm.auto_start_all_servers(verbose=False)
    assert out["bot"]["ok"] is False


# ---------------------------------------------------------------------------
# app.py
# ---------------------------------------------------------------------------


def test_alfa_cli_init(monkeypatch, tmp_path):
    import alfa.core.cli.app as app

    class FakeDirectAI:
        def __init__(self, provider=None, model=None):
            self.provider = provider or "gemini"
            self.model = model or "m"

    class FakeComponent:
        def __init__(self, *a, **k):
            self.kwargs = k

    monkeypatch.setattr(app, "DirectAIClient", FakeDirectAI)
    monkeypatch.setattr(app, "PatchHistoryManager", FakeComponent)
    monkeypatch.setattr(app, "RepomapGenerator", FakeComponent)
    monkeypatch.setattr(app, "AutonomousAgentRunner", FakeComponent)
    monkeypatch.setattr(app.AlfaCLI, "_load_config", lambda self: {"mode": "auto"})
    monkeypatch.setattr(app.AlfaCLI, "_setup_readline", lambda self: None)
    monkeypatch.setattr(app.AlfaCLI, "_load_session", lambda self: None)
    monkeypatch.setattr(app.AlfaCLI, "_update_prompt", lambda self: None)
    monkeypatch.setenv("ALFA_AUTO_APPROVE", "1")
    f = tmp_path / "ctx.py"
    f.write_text("x", encoding="utf-8")
    cli = app.AlfaCLI(
        server_url="http://x/",
        mode="standalone",
        attached_files=[str(f), str(tmp_path / "missing")],
        provider="google",
        model="gm",
    )
    assert cli.server_url == "http://x"
    assert cli.attached_files == [str(f)]
    assert cli.direct_ai.provider == "google"
    assert cli.agent_runner.auto_approve is True


def test_run_config_wizard(monkeypatch, tmp_path):
    import alfa.core.cli.app as app
    import alfa.core.config as config

    env_path = tmp_path / ".env"
    env_path.write_text("GEMINI_API_KEY=lama\nLAIN=x\n", encoding="utf-8")
    monkeypatch.setattr(config, "active_env_path", lambda: env_path)

    class FakeDirect:
        provider = "gemini"
        model = "gemini-3.8-flash"

        def get_api_key(self):
            return "old"

    class FakeCLI:
        def __init__(self):
            self.config = {"mode": "auto"}
            self.direct_ai = FakeDirect()
            self.server_url = "http://localhost:8080"
            self.saved = 0

        def _save_config(self):
            self.saved += 1

    monkeypatch.setattr(app, "AlfaCLI", FakeCLI)
    inputs = iter(["2", "1", "2"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))
    monkeypatch.setattr(app.getpass, "getpass", lambda prompt="": "kunci-baru")
    saved = {}
    import alfa.core.database as database

    monkeypatch.setattr(
        database,
        "add_api_key_sync",
        lambda **kwargs: saved.update(kwargs),
    )
    app.run_config_wizard()
    assert "GEMINI_API_KEY=kunci-baru" in env_path.read_text(encoding="utf-8")
    assert saved["provider"] == "gemini"
    assert saved["set_active"] is True


def test_run_config_wizard_skip_and_custom(monkeypatch, tmp_path):
    import alfa.core.cli.app as app
    import alfa.core.config as config

    monkeypatch.setattr(config, "active_env_path", lambda: tmp_path / "none.env")

    class FakeDirect:
        provider = "ollama"
        model = "llama3.2"

        def get_api_key(self):
            return ""

    cli = SimpleNamespace(
        config={"mode": "auto"},
        direct_ai=FakeDirect(),
        server_url="s",
        _save_config=lambda: None,
    )
    monkeypatch.setattr(app, "AlfaCLI", lambda: cli)
    inputs = iter(["", "5", "custom-model", "3"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))
    app.run_config_wizard()
    assert cli.config["model"] == "custom-model"
    assert cli.config["mode"] == "server"


def test_show_config(monkeypatch):
    import alfa.core.cli.app as app

    class FakeDirect:
        provider = "gemini"
        model = "m"

        def get_api_key(self):
            return "k"

    cli = SimpleNamespace(
        config={"mode": "auto", "agent_mode": False, "streaming": True},
        direct_ai=FakeDirect(),
        server_url="s",
        display_api_keys_vault=lambda: None,
    )
    monkeypatch.setattr(app, "AlfaCLI", lambda: cli)
    app.show_config()


def test_handle_web_mention(monkeypatch):
    import alfa.core.cli.app as app

    assert app._handle_web_mention("halo") == ("", "")

    html = (
        '<div class="result__body"><a class="result__title">Judul</a>'
        '<div class="result__snippet">Ringkasan</div></div>'
    )
    monkeypatch.setattr(
        app.requests,
        "get",
        lambda *a, **k: SimpleNamespace(text=html),
    )
    q, ctx = app._handle_web_mention("cari @web python")
    assert q == "python"
    assert "Judul" in ctx and "Ringkasan" in ctx

    monkeypatch.setattr(
        app.requests,
        "get",
        lambda *a, **k: SimpleNamespace(text="<html></html>"),
    )
    q, ctx = app._handle_web_mention("@web kosong")
    assert ctx == "Tidak ada hasil."

    def boom(*a, **k):
        raise ValueError("net")

    monkeypatch.setattr(app.requests, "get", boom)
    q, ctx = app._handle_web_mention("@web gagal")
    assert "gagal" in ctx


def _ask_args(**overrides):
    base = dict(
        server="http://s",
        standalone=True,
        mode="standalone",
        file=[],
        provider="gemini",
        model="m",
        question="q",
        agent=False,
        json=False,
        stream=False,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_handle_ask_agent_and_json(monkeypatch):
    import alfa.core.cli.app as app

    class FakeDirect:
        provider = "gemini"
        model = "m"

        def generate(self, **kwargs):
            return "jawab"

    class FakeCLI:
        def __init__(self, **kwargs):
            self.direct_ai = FakeDirect()
            self.console = FakeConsole()
            self.agent_runner = SimpleNamespace(run=lambda q: "agent-ans")

    monkeypatch.setattr(app, "AlfaCLI", FakeCLI)
    app.handle_ask_command(_ask_args(agent=True, json=True))
    app.handle_ask_command(_ask_args(agent=True))
    app.handle_ask_command(_ask_args(json=True))
    app.handle_ask_command(_ask_args(stream=True))
    app.handle_ask_command(_ask_args(stream=False, json=False))


def test_handle_ask_error_and_plain_render(monkeypatch):
    import alfa.core.cli.app as app

    class BoomDirect:
        provider = "gemini"
        model = "m"

        def generate(self, **kwargs):
            raise RuntimeError("llm")

    class FakeCLI:
        def __init__(self, **kwargs):
            self.direct_ai = BoomDirect()
            self.console = None
            self.agent_runner = SimpleNamespace(run=lambda q: "")

    monkeypatch.setattr(app, "AlfaCLI", FakeCLI)
    with pytest.raises(SystemExit) as exc:
        app.handle_ask_command(_ask_args())
    assert exc.value.code == 1

    class PlainDirect(BoomDirect):
        def generate(self, **kwargs):
            return "jawab"

    class PlainCLI(FakeCLI):
        def __init__(self, **kwargs):
            self.direct_ai = PlainDirect()
            self.console = None
            self.agent_runner = SimpleNamespace(run=lambda q: "")

    monkeypatch.setattr(app, "AlfaCLI", PlainCLI)
    monkeypatch.setattr(app, "RICH_AVAILABLE", False)
    app.handle_ask_command(_ask_args())


def test_handle_run_command(monkeypatch):
    import alfa.core.cli.app as app

    monkeypatch.setattr(
        app.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(stdout="out\n", stderr="err", returncode=0),
    )
    with pytest.raises(SystemExit) as exc:
        app.handle_run_command(SimpleNamespace(command="echo"))
    assert exc.value.code == 0

    def timeout(*a, **k):
        raise app.subprocess.TimeoutExpired("x", 1)

    monkeypatch.setattr(app.subprocess, "run", timeout)
    with pytest.raises(SystemExit) as exc:
        app.handle_run_command(SimpleNamespace(command="sleep"))
    assert exc.value.code == 124

    def boom(*a, **k):
        raise OSError("x")

    monkeypatch.setattr(app.subprocess, "run", boom)
    with pytest.raises(SystemExit) as exc:
        app.handle_run_command(SimpleNamespace(command="x"))
    assert exc.value.code == 1


def _patch_main(monkeypatch, argv, tty=False):
    import alfa.core.cli.app as app
    import alfa.core.cli.cursor_ui as cursor

    monkeypatch.setattr(app.sys, "argv", list(argv))
    monkeypatch.setattr(app.sys, "stdin", SimpleNamespace(isatty=lambda: tty))
    monkeypatch.setattr(app.sys, "stdout", SimpleNamespace(isatty=lambda: tty, write=lambda s: None))
    monkeypatch.setattr(app, "print_banner", lambda: None)
    monkeypatch.setattr(app, "print_status", lambda *a, **k: None)

    class FakeCLI:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.streaming = False
            self.attached_files = kwargs.get("attached_files") or []
            self.cmd_called = 0
            self.server_reachable = None

        def cmdloop(self):
            self.cmd_called += 1

    monkeypatch.setattr(app, "AlfaCLI", FakeCLI)
    calls = {}
    monkeypatch.setattr(
        app,
        "handle_ask_command",
        lambda args: calls.update(ask=args.question),
    )
    monkeypatch.setattr(
        app,
        "handle_run_command",
        lambda args: calls.update(run=args.command),
    )
    monkeypatch.setattr(app, "show_config", lambda: calls.update(show=True))
    monkeypatch.setattr(app, "run_config_wizard", lambda: calls.update(wizard=True))
    monkeypatch.setattr(cursor, "run_cursor_loop", lambda cli: calls.update(loop=cli))
    return app, calls


def test_main_subcommands(monkeypatch):
    app, calls = _patch_main(monkeypatch, ["alfa", "ask", "halo"])
    app.main()
    assert calls["ask"] == "halo"

    app, calls = _patch_main(monkeypatch, ["alfa", "run", "echo hi"])
    app.main()
    assert calls["run"] == "echo hi"

    app, calls = _patch_main(monkeypatch, ["alfa", "config", "--show"])
    app.main()
    assert calls["show"] is True

    app, calls = _patch_main(monkeypatch, ["alfa", "config"])
    app.main()
    assert calls["wizard"] is True


def test_main_chat_paths(monkeypatch, tmp_path):
    app, calls = _patch_main(
        monkeypatch, ["alfa", "chat", "--standalone", "--no-autostart"], tty=True
    )
    monkeypatch.setattr(app.requests, "get", lambda *a, **k: SimpleNamespace(status_code=500))
    app.main()
    assert "loop" in calls

    app, calls = _patch_main(
        monkeypatch, ["alfa", "chat", "--no-autostart"], tty=False
    )
    monkeypatch.setattr(app.requests, "get", lambda *a, **k: SimpleNamespace(status_code=200))
    app.main()
    # cmdloop dipanggil pada instance FakeCLI; cukup pastikan tidak crash
    assert calls == {}

    app, calls = _patch_main(monkeypatch, ["alfa", "--stream"], tty=False)
    monkeypatch.setattr(app.requests, "get", lambda *a, **k: SimpleNamespace(status_code=500))
    app.main()

    app, calls = _patch_main(
        monkeypatch, ["alfa", "chat", "--mode", "server", "--no-autostart"], tty=False
    )

    def offline(*a, **k):
        raise app.requests.RequestException("off")

    monkeypatch.setattr(app.requests, "get", offline)
    app.main()


def test_main_autostart_and_keyboard_interrupt(monkeypatch):
    app, _ = _patch_main(monkeypatch, ["alfa", "chat"], tty=False)
    started = []
    import alfa.core.cli.server_manager as sm

    monkeypatch.setattr(sm, "auto_start_all_servers", lambda verbose=True: started.append(True))
    monkeypatch.setattr(app.requests, "get", lambda *a, **k: SimpleNamespace(status_code=200))
    app.main()
    assert started

    app, _ = _patch_main(monkeypatch, ["alfa", "chat", "--no-autostart"], tty=False)

    class BoomCLI:
        def __init__(self, **kwargs):
            raise KeyboardInterrupt

    monkeypatch.setattr(app, "AlfaCLI", BoomCLI)
    with pytest.raises(SystemExit) as exc:
        app.main()
    assert exc.value.code == 0


def test_main_version(monkeypatch):
    app, _ = _patch_main(monkeypatch, ["alfa", "--version"])
    with pytest.raises(SystemExit) as exc:
        app.main()
    assert exc.value.code == 0
