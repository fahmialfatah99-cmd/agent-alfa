"""Phase 6 coverage: CLI chat loop, basic commands, and developer slash commands.

Hermetic: subprocess/HTTP/LLM/DB/session store di-mock. Tidak ada server,
shell, atau layanan produksi yang dijalankan.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock


class FakeConsole:
    def __init__(self):
        self.lines = []

    def print(self, *args, **kwargs):
        self.lines.append(args[0] if args else "")


class FakeResponse:
    def __init__(self, status_code=200, data=None, lines=None, text=""):
        self.status_code = status_code
        self._data = data or {}
        self._lines = lines or []
        self.text = text

    def json(self):
        return self._data

    def iter_lines(self):
        return iter(self._lines)


class FakeDirect:
    provider = "gemini"
    model = "gemini-test"

    def __init__(self, response="jawaban", mentions=None):
        self.response = response
        self.mentions = mentions or []
        self.calls = []

    def scan_file_mentions(self, message):
        return [], self.mentions

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        cb = kwargs.get("stream_callback")
        if cb:
            cb("chunk-1")
            cb("chunk-2")
        return self.response

    def build_prompt_with_context(self, message, attached):
        return f"CTX[{len(attached)}]:{message}"


class FakeRunner:
    def __init__(self):
        self.last_run = {"tools": ["x"]}
        self.auto_approve = False
        self.direct_ai = None
        self.max_turns = 5
        self.max_continuations = 2
        self.calls = []

    def run(self, message, plan_mode=False):
        self.calls.append((message, plan_mode))
        return "hasil-run"

    def format_last_run(self):
        return "RUN-TERAKHIR"


def make_chat(**overrides):
    from alfa.core.cli.chat import CliChatMixin

    class Dummy(CliChatMixin):
        pass

    d = Dummy()
    d.config = {}
    d.console = None
    d.chat_history = []
    d.streaming = False
    d.server_url = "http://localhost:8080"
    d.mode = "standalone"
    d.session_token = None
    d.username = None
    d.direct_ai = None
    d.agent_runner = None
    d.attached_files = []
    d.patch_manager = None
    d.repomap_gen = None
    d.agent_mode = False
    d.agent_execution_mode = "single"
    d.saved = 0
    d.updated = 0
    for key, value in overrides.items():
        setattr(d, key, value)
    return d


def make_basic(**overrides):
    from alfa.core.cli.basic_commands import CliBasicCommandsMixin

    class Dummy(CliBasicCommandsMixin):
        pass

    d = Dummy()
    d.config = {}
    d.console = None
    d.chat_history = []
    d.streaming = False
    d.server_url = "http://localhost:8080"
    d.mode = "standalone"
    d.session_token = None
    d.username = None
    d.direct_ai = None
    d.agent_runner = None
    d.attached_files = []
    d.patch_manager = None
    d.repomap_gen = None
    d.agent_mode = True
    d.agent_execution_mode = "single"
    d.saved = 0
    d.updated = 0
    d.session_saved = 0

    def _request(*args, **kwargs):
        return None

    d._request = _request
    d._save_config = lambda: setattr(d, "saved", d.saved + 1)
    d._update_prompt = lambda: setattr(d, "updated", d.updated + 1)
    d._save_session = lambda: setattr(d, "session_saved", d.session_saved + 1)
    d._clear_session = lambda: setattr(d, "session_token", None)
    d._save_history = lambda: None
    d._run_swarm_execution = lambda msg: None
    for key, value in overrides.items():
        setattr(d, key, value)
    return d


def make_dev(**overrides):
    from alfa.core.cli.slash.developer import SlashDeveloperMixin

    class Dummy(SlashDeveloperMixin):
        pass

    d = Dummy()
    d.config = {}
    d.console = None
    d.agent_mode = True
    d.agent_execution_mode = "single"
    d.patch_manager = None
    d.repomap_gen = None
    d.agent_runner = None
    d.direct_ai = None
    d.saved = 0
    d._save_config = lambda: setattr(d, "saved", d.saved + 1)
    d._set_agent_model_command = lambda arg: setattr(d, "model_arg", arg)
    d.do_slash_mode = lambda arg: setattr(d, "mode_arg", arg)
    for key, value in overrides.items():
        setattr(d, key, value)
    return d


# ---------------------------------------------------------------------------
# chat.py
# ---------------------------------------------------------------------------


def test_contains_tool_call_variants():
    from alfa.core.cli.chat import _contains_tool_call

    assert _contains_tool_call("") is False
    assert _contains_tool_call("```tool_call\n{}") is True
    assert _contains_tool_call("<tool_call>") is True
    assert _contains_tool_call('{"tool": "run_command"}') is True
    assert _contains_tool_call("halo biasa") is False


def test_default_blank_and_shell(monkeypatch):
    import alfa.core.cli.chat as chat

    d = make_chat()
    assert d.default("   ") is None

    seen = {}
    monkeypatch.setattr(chat, "print_status", lambda m, s=None: seen.update(m=m, s=s))
    d.default("!   ")
    assert "kosong" in seen["m"]

    monkeypatch.setattr(
        chat.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(stdout="ok\n", stderr="", returncode=0),
    )
    d.default("!echo ok")

    monkeypatch.setattr(
        chat.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(stdout="out", stderr="err", returncode=2),
    )
    d.default("!false")

    def timeout(*a, **k):
        raise subprocess.TimeoutExpired("x", 1)

    monkeypatch.setattr(chat.subprocess, "run", timeout)
    d.default("!sleep")

    def boom(*a, **k):
        raise OSError("shell rusak")  # noqa: TRY003

    monkeypatch.setattr(chat.subprocess, "run", boom)
    d.default("!x")


def test_default_slash_and_unknown(monkeypatch):
    import alfa.core.cli.chat as chat

    d = make_chat()
    called = {}

    d.do_slash_hello = lambda arg: called.update(arg=arg)
    d.default("/hello dunia")
    assert called["arg"] == "dunia"

    monkeypatch.setattr(chat, "print_status", lambda *a, **k: None)
    d.default("/tidak-ada")
    d.default("/")


def test_maybe_answer_work_status():
    d = make_chat()
    assert d._maybe_answer_work_status("halo") is False
    assert d._maybe_answer_work_status("apa progres?") is False
    runner = FakeRunner()
    d.agent_runner = runner
    assert d._maybe_answer_work_status("apa progres?") is True
    runner.last_run = {"tools": []}
    assert d._maybe_answer_work_status("sampai mana?") is False


def test_default_routing(monkeypatch):
    d = make_chat()
    calls = []
    d._chat_direct_standalone = lambda msg: calls.append(("direct", msg))
    d._chat_via_server = lambda msg: calls.append(("server", msg))

    d.default("halo")
    assert calls[-1] == ("direct", "halo")

    d.mode = "auto"
    d.server_reachable = False
    d.default("halo")
    assert calls[-1][0] == "direct"

    d.mode = "auto"
    d.server_reachable = True
    d.session_token = "tok"
    d.default("halo")
    assert calls[-1][0] == "server"

    d.mode = "server"
    d.default("halo")
    assert calls[-1][0] == "server"


def test_run_agent_turn_rich_plain_and_error(monkeypatch):
    import alfa.core.cli.chat as chat

    d = make_chat(agent_runner=FakeRunner())
    monkeypatch.setattr(chat, "RICH_AVAILABLE", False)
    d._run_agent_turn("pesan")
    assert d.chat_history[-2:] == [
        {"role": "user", "content": "pesan"},
        {"role": "assistant", "content": "hasil-run"},
    ]

    d2 = make_chat(agent_runner=FakeRunner(), console=FakeConsole())
    d2.config = {"markdown": True}
    monkeypatch.setattr(chat, "RICH_AVAILABLE", True)
    monkeypatch.setattr(chat, "Markdown", lambda text: text)
    d2._run_agent_turn("x")
    assert d2.chat_history

    class BoomRunner(FakeRunner):
        def run(self, message, plan_mode=False):
            raise RuntimeError("API Key hilang")  # noqa: TRY003

    d3 = make_chat(agent_runner=BoomRunner())
    d3._run_agent_turn("x")


def test_chat_direct_no_engine(monkeypatch):
    import alfa.core.cli.chat as chat

    seen = {}
    monkeypatch.setattr(chat, "print_status", lambda m, s=None: seen.update(m=m, s=s))
    d = make_chat(direct_ai=None)
    d._chat_direct_standalone("halo")
    assert seen["s"] == "error"


def test_chat_direct_swarm_dispatch(monkeypatch):
    d = make_chat(direct_ai=FakeDirect(), agent_execution_mode="swarm")
    seen = []
    d._run_swarm_execution = lambda msg: seen.append(msg)
    d._chat_direct_standalone("tugas")
    assert seen == ["tugas"]


def test_chat_direct_agent_dispatch(monkeypatch):
    d = make_chat(direct_ai=FakeDirect(), agent_mode=True, agent_runner=FakeRunner())
    seen = []
    d._run_agent_turn = lambda msg: seen.append(msg)
    d._chat_direct_standalone("analisis kode")
    assert seen == ["analisis kode"]


def test_chat_direct_local_intent_keyword(monkeypatch):
    d = make_chat(direct_ai=FakeDirect(), agent_mode=False, agent_runner=FakeRunner())
    seen = []
    d._run_agent_turn = lambda msg: seen.append(msg)
    d._chat_direct_standalone("tolong cek file ini")
    assert seen


def test_chat_direct_stream_and_tool_handover(monkeypatch):
    import alfa.core.cli.chat as chat
    from alfa.core.cli import app as cli_app

    monkeypatch.setattr(chat, "RICH_AVAILABLE", False)
    monkeypatch.setattr(cli_app, "_handle_web_mention", lambda msg: ("", ""))
    d = make_chat(direct_ai=FakeDirect(response="halo"), streaming=True)
    d._chat_direct_standalone("pesan")
    assert d.direct_ai.calls[0]["stream"] is True

    d2 = make_chat(
        direct_ai=FakeDirect(response='{"tool": "x"}'),
        agent_runner=FakeRunner(),
        streaming=False,
    )
    seen = []
    d2._run_agent_turn = lambda msg: seen.append(msg)
    d2._chat_direct_standalone("pesan")
    assert seen == ["pesan"]


def test_chat_direct_web_context_and_files(monkeypatch):
    import alfa.core.cli.chat as chat
    from alfa.core.cli import app as cli_app

    monkeypatch.setattr(chat, "RICH_AVAILABLE", False)
    monkeypatch.setattr(
        cli_app, "_handle_web_mention", lambda msg: ("q", "hasil web")
    )
    d = make_chat(
        direct_ai=FakeDirect(mentions=["f.py"]),
        attached_files=["a.py"],
        agent_mode=False,
    )
    d._chat_direct_standalone("cari @web sesuatu")
    prompt = d.direct_ai.calls[0]["prompt"]
    assert "HASIL PENCARIAN WEB (q)" in prompt
    assert "hasil web" in prompt
    assert d.direct_ai.calls[0]["context_files"] == ["a.py", "f.py"]


def test_chat_direct_plain_response_and_error(monkeypatch):
    import alfa.core.cli.chat as chat

    monkeypatch.setattr(chat, "RICH_AVAILABLE", False)
    d = make_chat(direct_ai=FakeDirect("jawab"), agent_mode=False)
    d._chat_direct_standalone("halo")
    assert d.chat_history[-1]["content"] == "jawab"

    class BoomDirect(FakeDirect):
        def generate(self, **kwargs):
            raise OSError("API Key invalid")  # noqa: TRY003

    d2 = make_chat(direct_ai=BoomDirect(), agent_mode=False)
    d2._chat_direct_standalone("halo")


def test_chat_direct_rich_response(monkeypatch):
    import alfa.core.cli.chat as chat

    monkeypatch.setattr(chat, "RICH_AVAILABLE", True)
    monkeypatch.setattr(chat, "Markdown", lambda text: text)
    d = make_chat(direct_ai=FakeDirect("jawab"), agent_mode=False, console=FakeConsole())
    d.config = {"markdown": True}
    d._chat_direct_standalone("halo")
    assert d.console.lines


def test_chat_via_server_without_token(monkeypatch):
    import alfa.core.cli.chat as chat

    seen = {}
    monkeypatch.setattr(chat, "print_status", lambda m, s=None: seen.update(m=m, s=s))
    d = make_chat(mode="server")
    d._chat_via_server("halo")
    assert "login" in seen["m"].lower()


def test_chat_via_server_nonstream_success_and_fail(monkeypatch):
    import alfa.core.cli.chat as chat

    monkeypatch.setattr(chat, "RICH_AVAILABLE", False)
    d = make_chat(session_token="t", streaming=False)
    d._request = lambda *a, **k: FakeResponse(data={"response": "server-jawab"})
    d._chat_via_server("halo")
    assert d.chat_history[-1]["content"] == "server-jawab"

    d2 = make_chat(session_token="t", streaming=False)
    d2._request = lambda *a, **k: FakeResponse(status_code=500)
    d2._chat_via_server("halo")
    assert d2.chat_history == []

    d3 = make_chat(
        session_token="t", streaming=False, direct_ai=FakeDirect(), attached_files=["a"]
    )
    seen = {}
    d3._request = lambda method, path, payload=None: (
        seen.update(payload=payload) or FakeResponse(data={"message": "m"})
    )
    d3._chat_via_server("halo")
    assert seen["payload"]["message"] == "CTX[1]:halo"


def test_chat_via_server_nonstream_rich(monkeypatch):
    import alfa.core.cli.chat as chat

    monkeypatch.setattr(chat, "RICH_AVAILABLE", True)
    monkeypatch.setattr(chat, "Markdown", lambda text: text)
    d = make_chat(session_token="t", streaming=False, console=FakeConsole())
    d.config = {"markdown": True}
    d._request = lambda *a, **k: FakeResponse(data={"response": "x"})
    d._chat_via_server("halo")
    assert d.console.lines


class FakeLive:
    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def update(self, *a, **k):
        pass


def test_chat_via_server_streaming_rich(monkeypatch):
    import alfa.core.cli.chat as chat

    monkeypatch.setattr(chat, "RICH_AVAILABLE", True)
    monkeypatch.setattr(chat, "Live", FakeLive)
    monkeypatch.setattr(chat, "Spinner", lambda *a, **k: None)
    d = make_chat(session_token="t", streaming=True, console=FakeConsole())
    d._request = lambda *a, **k: FakeResponse(
        lines=[b'{"token": "a"}', b"", b"rusak", b'{"token": "b"}']
    )
    d._chat_via_server("halo")
    assert d.chat_history[-1]["content"] == "ab"

    d2 = make_chat(session_token="t", streaming=True, console=FakeConsole())
    d2._request = lambda *a, **k: FakeResponse(status_code=500)
    d2._chat_via_server("halo")
    assert d2.chat_history == []


def test_chat_via_server_streaming_plain(monkeypatch):
    import alfa.core.cli.chat as chat

    monkeypatch.setattr(chat, "RICH_AVAILABLE", False)
    d = make_chat(session_token="t", streaming=True)
    d._request = lambda *a, **k: FakeResponse(data={"response": "plain"})
    d._chat_via_server("halo")
    assert d.chat_history[-1]["content"] == "plain"

    d2 = make_chat(session_token="t", streaming=True)
    d2._request = lambda *a, **k: FakeResponse(status_code=400)
    d2._chat_via_server("halo")
    assert d2.chat_history == []


def test_run_swarm_no_agents(monkeypatch):
    import alfa.core.cli.chat as chat
    from alfa.core import database

    monkeypatch.setattr(chat, "RICH_AVAILABLE", False)
    monkeypatch.setattr(database, "list_custom_agents_sync", lambda: [])
    d = make_chat()
    d._run_swarm_execution("tugas")
    assert d.chat_history == []


def test_run_swarm_plain_and_success(monkeypatch):
    import alfa.core.cli.chat as chat
    from alfa.core import database
    from alfa.swarm import engine

    agents = [
        {
            "name": "A",
            "role": "R",
            "provider": "gemini",
            "model": "m",
            "is_enabled": 1,
        }
    ]
    monkeypatch.setattr(database, "list_custom_agents_sync", lambda: agents)
    monkeypatch.setattr(chat, "RICH_AVAILABLE", False)

    async def meeting(**kwargs):
        return {"consensus": "sepakat"}

    monkeypatch.setattr(engine, "conduct_multi_agent_meeting", meeting)
    d = make_chat(console=None)
    d._run_swarm_execution("tugas")
    assert d.chat_history[-1]["content"] == "sepakat"

    async def meeting_plan(**kwargs):
        return {"action_plan": "rencana"}

    monkeypatch.setattr(engine, "conduct_multi_agent_meeting", meeting_plan)
    d._run_swarm_execution("tugas")
    assert d.chat_history[-1]["content"] == "rencana"


def test_run_swarm_rich_and_error(monkeypatch):
    import alfa.core.cli.chat as chat
    from alfa.core import database
    from alfa.swarm import engine

    agents = [
        {
            "name": "A",
            "role": "R",
            "provider": "gemini",
            "model": "m",
            "is_enabled": 1,
            "avatar_emoji": "🤖",
        }
    ]
    monkeypatch.setattr(database, "list_custom_agents_sync", lambda: agents)
    monkeypatch.setattr(chat, "RICH_AVAILABLE", True)
    monkeypatch.setattr(chat, "Markdown", lambda text: text)

    async def meeting(**kwargs):
        return {"status": "ok"}

    monkeypatch.setattr(engine, "conduct_multi_agent_meeting", meeting)
    d = make_chat(console=FakeConsole())
    d.config = {"markdown": True}
    d._run_swarm_execution("tugas")
    assert d.chat_history[-1]["content"] == "ok"

    async def boom(**kwargs):
        raise RuntimeError("swarm crash")  # noqa: TRY003

    monkeypatch.setattr(engine, "conduct_multi_agent_meeting", boom)
    d._run_swarm_execution("tugas")


def test_run_swarm_db_error(monkeypatch):
    import alfa.core.cli.chat as chat
    from alfa.core import database

    def boom():
        raise RuntimeError("db")

    monkeypatch.setattr(database, "list_custom_agents_sync", boom)
    monkeypatch.setattr(chat, "RICH_AVAILABLE", False)
    d = make_chat()
    d._run_swarm_execution("tugas")
    assert d.chat_history == []


def test_emptyline():
    assert make_chat().emptyline() is False


# ---------------------------------------------------------------------------
# basic_commands.py
# ---------------------------------------------------------------------------


def test_register_flow(monkeypatch):
    import alfa.core.cli.basic_commands as bc

    seen = {}
    monkeypatch.setattr(bc, "print_status", lambda m, s=None: seen.update(m=m, s=s))
    monkeypatch.setattr(bc.getpass, "getpass", lambda prompt="": "pw")
    monkeypatch.setattr("builtins.input", lambda prompt="": "")
    d = make_basic()
    d.do_register("")
    assert "kosong" in seen["m"].lower()

    passwords = iter(["pw", "beda"])
    monkeypatch.setattr(bc.getpass, "getpass", lambda prompt="": next(passwords))
    d.do_register("budi")
    assert "tidak cocok" in seen["m"].lower()

    monkeypatch.setattr(bc.getpass, "getpass", lambda prompt="": "pw")
    d._request = lambda *a, **k: FakeResponse(status_code=201)
    d.do_login = lambda name: seen.update(login=name)
    d.do_register("budi")
    assert seen["login"] == "budi"

    d._request = lambda *a, **k: FakeResponse(status_code=400, data={"detail": "dupe"})
    d.do_register("budi")
    assert seen["m"] == "dupe"

    class BadJson(FakeResponse):
        def json(self):
            raise ValueError("bukan json")  # noqa: TRY003

    d._request = lambda *a, **k: BadJson(status_code=500, text="mentah")
    d.do_register("budi")
    assert seen["m"] == "mentah"


def test_login_flow(monkeypatch):
    import alfa.core.cli.basic_commands as bc

    seen = {}
    monkeypatch.setattr(bc, "print_status", lambda m, s=None: seen.update(m=m, s=s))
    monkeypatch.setattr(bc.getpass, "getpass", lambda prompt="": "pw")
    monkeypatch.setattr("builtins.input", lambda prompt="": "user")

    d = make_basic()
    captured = {}

    def first_request(method, path, payload=None):
        captured["payload"] = payload
        return None

    d._request = first_request
    d.do_login("")
    assert captured["payload"]["username"] == "user"

    d._request = lambda method, path, payload=None: (
        FakeResponse(
            data={"access_token": "tok", "user": {"is_admin": True}},
        )
        if path == "/api/auth/login"
        else FakeResponse(data={"user": {"is_admin": True}})
    )
    d.do_login("budi")
    assert d.session_token == "tok"
    assert d.is_admin is True
    assert d.updated == 1

    d2 = make_basic()
    d2._request = lambda *a, **k: FakeResponse(status_code=401, data={"detail": "salah"})
    monkeypatch.setattr("builtins.input", lambda prompt="": "")
    d2.do_login("")
    assert "username" in seen["m"].lower()

    d3 = make_basic()
    d3._request = lambda *a, **k: FakeResponse(status_code=401, text="x")
    d3.do_login("budi")

    d4 = make_basic()
    d4._request = lambda *a, **k: None
    d4.do_login("budi")


def test_logout_stats_tools_clear_exit(monkeypatch):
    import alfa.core.cli.basic_commands as bc

    seen = {}
    monkeypatch.setattr(bc, "print_status", lambda m, s=None: seen.update(m=m, s=s))
    d = make_basic(session_token="tok")
    called = []
    d._request = lambda *a, **k: called.append(a) or FakeResponse()
    d.do_logout("")
    assert called and d.session_token is None

    d.do_stats("")
    assert "login" in seen["m"].lower()

    d.session_token = "tok"
    d._request = lambda *a, **k: FakeResponse(data={"cpu": 1})
    d.do_stats("")

    d._request = lambda *a, **k: FakeResponse(status_code=500)
    d.do_stats("")

    d2 = make_basic()
    d2.do_slash_tools = lambda arg: seen.update(slash_tools=arg)
    d2.do_tools("")
    assert seen["slash_tools"] == ""

    d3 = make_basic(session_token="tok")
    d3._request = lambda *a, **k: FakeResponse(
        data={"tools": [{"name": f"t{i}", "description": "d"} for i in range(25)]}
    )
    d3.do_tools("")

    d4 = make_basic(session_token="tok")
    d4._request = lambda *a, **k: FakeResponse(data=["a", "b"])
    d4.do_tools("")

    d5 = make_basic(session_token="tok")
    d5._request = lambda *a, **k: FakeResponse(status_code=500)
    d5.do_tools("")

    monkeypatch.setattr(bc.os, "system", lambda cmd: called.append(cmd))
    monkeypatch.setattr(bc, "print_banner", lambda: called.append("banner"))
    d.do_clear("")
    d.do_slash_clear("")
    assert "banner" in called

    assert d.do_exit("") is True
    assert d.do_q("") is True


def test_slash_help(monkeypatch):
    import alfa.core.cli.basic_commands as bc

    printed = []
    monkeypatch.setattr(
        bc,
        "print",
        lambda *a, **k: printed.append(" ".join(map(str, a))),
        raising=False,
    )
    make_basic().do_slash_help("")
    assert "ALFA CLI" in printed[0]


def test_slash_exit_and_history(monkeypatch):
    import alfa.core.cli.basic_commands as bc
    from alfa.core.cli import session_store

    seen = {}
    monkeypatch.setattr(bc, "print_status", lambda m, s=None: seen.update(m=m, s=s))
    d = make_basic(chat_history=[])
    d.do_slash_exit("")
    assert d.saved == 0

    class Store:
        def save(self, *a, **k):
            seen["saved"] = True

    monkeypatch.setattr(session_store, "SessionStore", Store)
    d2 = make_basic(chat_history=[{"role": "user", "content": "x"}])
    d2.do_slash_exit("")
    assert seen["saved"] is True
    assert d2.do_slash_quit("") is True

    d3 = make_basic(chat_history=[])
    d3.do_slash_history("")
    assert "Belum ada" in seen["m"]

    d4 = make_basic(
        chat_history=[
            {"role": "user", "content": "a"},
            {"role": "assistant", "content": "b"},
            {"role": "user", "content": "c"},
        ]
    )
    d4.do_slash_history("2")


class FakeSessionStore:
    items = []
    saved_data = {}
    delete_ok = True

    def save(self, name, history, plan, extra=None):
        FakeSessionStore.saved_data = {
            "name": name,
            "history": history,
            "plan": plan,
            "extra": extra,
        }
        return name.lower().replace(" ", "-")

    def list(self):
        return FakeSessionStore.items

    def load(self, name):
        if name == "hilang":
            return None
        return {
            "chat_history": [
                {"role": "user", "content": "lama"},
                "bukan-dict",
            ],
            "last_plan": {"task": "t"},
            "extra": {
                "agent_mode": False,
                "agent_execution_mode": "swarm",
                "auto_approve": True,
            },
            "workspace": "/tmp/ws",
        }

    def delete(self, name):
        return FakeSessionStore.delete_ok


def test_slash_session(monkeypatch):
    import alfa.core.cli.basic_commands as bc
    from alfa.core.cli import session_store

    monkeypatch.setattr(session_store, "SessionStore", FakeSessionStore)
    monkeypatch.setattr(bc, "print_status", lambda *a, **k: None)
    d = make_basic(
        chat_history=[{"role": "user", "content": "x"}],
        agent_runner=FakeRunner(),
    )
    d.last_plan = {"task": "t"}
    d.do_slash_session("save Sesi Saya")
    assert FakeSessionStore.saved_data["name"] == "Sesi Saya"
    assert FakeSessionStore.saved_data["extra"]["auto_approve"] is False

    FakeSessionStore.items = []
    d.do_slash_session("list")
    FakeSessionStore.items = [
        {
            "name": "s1",
            "has_plan": True,
            "messages": 2,
            "workspace": "/w",
            "saved_at": "now",
        }
    ]
    d.do_slash_session("list")

    d.do_slash_session("load")
    d.do_slash_session("load hilang")
    d.do_slash_session("load ada")
    assert d.chat_history == [{"role": "user", "content": "lama"}]
    assert d.agent_mode is False
    assert d.agent_execution_mode == "swarm"
    assert d.agent_runner.auto_approve is True

    FakeSessionStore.delete_ok = True
    d.do_slash_session("delete ada")
    FakeSessionStore.delete_ok = False
    d.do_slash_session("delete ada")
    d.do_slash_session("delete")
    d.do_slash_session("ngawur")


def test_slash_compact(monkeypatch):
    import alfa.core.cli.basic_commands as bc

    seen = {}
    monkeypatch.setattr(bc, "print_status", lambda m, s=None: seen.update(m=m, s=s))
    d = make_basic(chat_history=[{"role": "user", "content": "x"}])
    d.do_slash_compact("")
    assert "pendek" in seen["m"]

    d2 = make_basic(
        chat_history=[{"role": "user", "content": str(i)} for i in range(5)],
        direct_ai=None,
    )
    d2.do_slash_compact("")
    assert "belum siap" in seen["m"]

    d3 = make_basic(
        chat_history=[{"role": "user", "content": str(i)} for i in range(5)],
        direct_ai=FakeDirect("ringkasan"),
    )
    d3.do_slash_compact("")
    assert "MEMO RINGKASAN" in d3.chat_history[0]["content"]

    class Boom(FakeDirect):
        def generate(self, **kwargs):
            raise RuntimeError("gagal")

    d4 = make_basic(
        chat_history=[{"role": "user", "content": str(i)} for i in range(5)],
        direct_ai=Boom(),
    )
    d4.do_slash_compact("")
    assert "Gagal" in seen["m"]


def test_slash_config_theme_stream(monkeypatch):
    import alfa.core.cli.basic_commands as bc

    seen = {}
    monkeypatch.setattr(bc, "print_status", lambda m, s=None: seen.update(m=m, s=s))
    d = make_basic(config={"a": 1})
    d.do_slash_config("")
    d.do_slash_config("flag=true")
    assert d.config["flag"] is True
    d.do_slash_config("flag=0")
    assert d.config["flag"] is False
    d.do_slash_config("mode=standalone")
    assert d.config["mode"] == "standalone"
    d.do_slash_config("streaming=on")
    assert d.streaming == "on"
    assert d.saved == 4

    d.do_slash_theme("")
    d.do_slash_theme("default")
    assert d.config["theme"] == "default"

    d.do_slash_stream("")
    d.do_slash_stream("on")
    assert d.streaming is True
    d.do_slash_stream("off")
    assert d.streaming is False


def test_basic_wrappers(monkeypatch):
    d = make_basic()
    calls = []
    d.do_tools = lambda arg: calls.append(("tools", arg))
    d.do_stats = lambda arg: calls.append(("stats", arg))
    d.do_login = lambda arg: calls.append(("login", arg))
    d.do_logout = lambda arg: calls.append(("logout", arg))
    d.do_register = lambda arg: calls.append(("register", arg))
    d.do_slash_tools("")
    d.do_slash_stats("")
    d.do_slash_login("")
    d.do_slash_logout("")
    d.do_slash_register("")
    assert [c[0] for c in calls] == [
        "tools",
        "stats",
        "login",
        "logout",
        "register",
    ]


# ---------------------------------------------------------------------------
# slash/developer.py
# ---------------------------------------------------------------------------


class FakePatch:
    def __init__(self, pid=1, filepath="a.py", summary="edit"):
        self.id = pid
        self.timestamp = "now"
        self.filepath = filepath
        self.summary = summary


class FakePatchManager:
    def __init__(self, patches=None, rollback=(True, "ok")):
        self.patches = patches or []
        self.rollback = rollback
        self.calls = []

    def list_patches(self):
        return self.patches

    def rollback_patch(self, pid):
        self.calls.append(("patch", pid))
        return self.rollback

    def rollback_latest(self):
        self.calls.append(("latest", None))
        return self.rollback


def test_agent_status_and_toggle(monkeypatch):
    import alfa.core.cli.slash.developer as dev

    monkeypatch.setattr(dev, "print_status", lambda *a, **k: None)
    d = make_dev(agent_runner=FakeRunner())
    d.do_slash_agent("")
    d.do_slash_agent("status")
    d.do_slash_agent("on")
    assert d.agent_mode is True
    d.do_slash_agent("off")
    assert d.agent_mode is False
    d.do_slash_agent("ngawur")
    d.do_slash_agent("model agen gemini")
    assert d.model_arg == "agen gemini"
    d.do_slash_agent("single")
    assert d.mode_arg == "single"
    d.do_slash_agent("swarm")
    assert d.mode_arg == "swarm"


def test_undo_list_and_rollback(monkeypatch):
    import alfa.core.cli.slash.developer as dev

    monkeypatch.setattr(dev, "print_status", lambda *a, **k: None)
    monkeypatch.setattr("builtins.input", lambda prompt="": "n")

    d = make_dev(patch_manager=FakePatchManager([]))
    d.do_slash_undo("list")
    d.do_slash_undo("latest")
    d.do_slash_undo("2")

    pm = FakePatchManager([FakePatch(1), FakePatch(2)])
    d2 = make_dev(patch_manager=pm)
    d2.do_slash_undo("list")
    d2.do_slash_undo("1")
    assert ("patch", 1) in pm.calls
    monkeypatch.setattr("builtins.input", lambda prompt="": "")
    d2.do_slash_undo("latest")
    assert ("latest", None) in pm.calls

    pm2 = FakePatchManager([FakePatch(1)], rollback=(False, "gagal"))
    d3 = make_dev(patch_manager=pm2)
    d3.do_slash_undo("1")
    d3.do_slash_undo("latest")

    d4 = make_dev(patch_manager=FakePatchManager([FakePatch(1)]), console=FakeConsole())
    d4.do_slash_undo("list")
    assert d4.console.lines


def test_repomap_and_tools(monkeypatch):
    import alfa.core.cli.constants as constants

    monkeypatch.setattr(constants, "RICH_AVAILABLE", False)
    gen = SimpleNamespace(generate_repomap=lambda: "MAP")
    d = make_dev(repomap_gen=gen)
    d.do_slash_repomap("")

    monkeypatch.setattr(constants, "RICH_AVAILABLE", True)
    d2 = make_dev(repomap_gen=gen, console=FakeConsole())
    d2.do_slash_repomap("")
    d2.do_slash_tools("")
    assert d2.console.lines

    d3 = make_dev(repomap_gen=gen)
    d3.do_slash_tools("")


def test_test_and_git_commands(monkeypatch):
    import alfa.core.cli.slash.developer as dev

    seen = {}
    monkeypatch.setattr(dev, "print_status", lambda m, s=None: seen.update(m=m, s=s))
    d = make_dev()
    d.do_slash_test("src/")
    assert "hanya" in seen["m"]

    executed = []
    d._execute_shell_command = lambda cmd: executed.append(cmd)
    d.do_slash_test("tests/x.py")
    d.do_slash_git("")
    d.do_slash_git("diff")
    d.do_slash_git("log")
    d.do_slash_git("branch")
    d.do_slash_git("commit")
    d.do_slash_git("ngawur")
    assert len(executed) == 5

    d2 = make_dev()
    d2.do_slash_test("tests/x.py")
    d2.do_slash_git("status")


def test_plan_and_approve(monkeypatch, tmp_path):
    import alfa.core.cli.slash.developer as dev

    monkeypatch.setattr(dev, "print_status", lambda *a, **k: None)
    d = make_dev(root=tmp_path)
    d.do_slash_plan("")
    d.do_slash_plan("tugas")
    assert not (tmp_path / ".alfa_backups" / "last_plan.md").exists()

    runner = FakeRunner()
    d2 = make_dev(root=tmp_path, agent_runner=runner, direct_ai=FakeDirect())
    d2.do_slash_plan("bangun fitur")
    assert d2.last_plan["task"] == "bangun fitur"
    assert (tmp_path / ".alfa_backups" / "last_plan.md").exists()

    class BoomRunner(FakeRunner):
        def run(self, message, plan_mode=False):
            raise RuntimeError("plan error")  # noqa: TRY003

    d3 = make_dev(root=tmp_path, agent_runner=BoomRunner())
    d3.do_slash_plan("x")

    monkeypatch.setattr(
        Path, "write_text", MagicMock(side_effect=OSError("disk")), raising=True
    )
    d4 = make_dev(root=tmp_path, agent_runner=FakeRunner())
    d4.do_slash_plan("x")
    monkeypatch.undo()


def test_approve_branches(monkeypatch, tmp_path):
    import alfa.core.cli.slash.developer as dev

    monkeypatch.setattr(dev, "print_status", lambda *a, **k: None)
    d = make_dev(root=tmp_path)
    d.do_slash_approve("")

    plan_file = tmp_path / ".alfa_backups" / "last_plan.md"
    plan_file.parent.mkdir(exist_ok=True)
    plan_file.write_text("rencana dari file", encoding="utf-8")
    d2 = make_dev(root=tmp_path)
    d2.do_slash_approve("catatan")
    assert "rencana dari file" in d2.last_plan["plan"]

    runner = FakeRunner()
    d3 = make_dev(root=tmp_path, agent_runner=runner, direct_ai=FakeDirect())
    d3.last_plan = {"task": "t", "plan": "p"}
    d3.do_slash_approve("extra")
    assert "Catatan tambahan user: extra" in runner.calls[-1][0]

    class BoomRunner(FakeRunner):
        def run(self, message, plan_mode=False):
            raise RuntimeError("gagal")

    d4 = make_dev(root=tmp_path, agent_runner=BoomRunner())
    d4.last_plan = {"task": "t", "plan": "p"}
    d4.do_slash_approve("")


def test_auto_mode(monkeypatch):
    import alfa.core.cli.slash.developer as dev

    monkeypatch.setattr(dev, "print_status", lambda *a, **k: None)
    d = make_dev()
    d.do_slash_auto("on")

    runner = FakeRunner()
    d2 = make_dev(agent_runner=runner)
    d2.do_slash_auto("on")
    assert runner.auto_approve is True
    assert d2.config["auto_approve"] is True
    d2.do_slash_auto("off")
    assert runner.auto_approve is False
    d2.do_slash_auto("")


class FakePermStore:
    def __init__(self):
        self.rules = {}
        self.reset_ok = True

    def as_dict(self):
        return self.rules

    def get(self, tool):
        return self.rules.get(tool, "ask")

    def reset(self, tool):
        self.rules.pop(tool, None)
        return self.reset_ok

    def set(self, tool, action):
        self.rules[tool] = action


def test_permit(monkeypatch):
    import alfa.core.cli.slash.developer as dev

    monkeypatch.setattr(dev, "print_status", lambda *a, **k: None)
    d = make_dev()
    d.do_slash_permit("")

    store = FakePermStore()
    runner = FakeRunner()
    runner.perm_store = store
    d2 = make_dev(agent_runner=runner)
    d2.do_slash_permit("")
    store.rules = {}
    d2.do_slash_permit("")
    d2.do_slash_permit("run_command")
    d2.do_slash_permit("run_command allow")
    assert store.rules["run_command"] == "allow"
    d2.do_slash_permit("run_command reset")
    d2.do_slash_permit("run_command bad")
    store.reset_ok = False
    d2.do_slash_permit("x reset")


class FakeTodoManager:
    def __init__(self):
        self.items = []
        self.done_ok = True

    def add(self, task):
        item = {"id": len(self.items) + 1, "task": task}
        self.items.append(item)
        return item

    def summary(self):
        return "todo-summary"

    def done(self, tid):
        return self.done_ok

    def clear(self, done_only=True):
        return 3


def test_todo(monkeypatch):
    import alfa.core.cli.slash.developer as dev

    monkeypatch.setattr(dev, "print_status", lambda *a, **k: None)
    mgr = FakeTodoManager()
    d = make_dev()
    d._todo_manager = lambda: mgr
    d.do_slash_todo("")
    d.do_slash_todo("list")
    d.do_slash_todo("add")
    d.do_slash_todo("add beli kopi")
    d.do_slash_todo("done 1")
    d.do_slash_todo("done abc")
    mgr.done_ok = False
    d.do_slash_todo("done 9")
    d.do_slash_todo("clear")
    d.do_slash_todo("ngawur")


def test_status(monkeypatch):
    import alfa.core.cli.slash.developer as dev

    monkeypatch.setattr(dev, "print_status", lambda *a, **k: None)
    d = make_dev()
    d.do_slash_status("")
    d2 = make_dev(agent_runner=FakeRunner())
    d2.do_slash_status("")
