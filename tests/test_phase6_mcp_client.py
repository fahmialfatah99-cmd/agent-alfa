"""Phase 6 coverage: MCP client — store atomik, OAuth PKCE, transport sync.

Hermetic: STATE_DIR/STORE_FILE diarahkan ke tmp_path, urlopen/SDK MCP di-mock.
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from alfa.mcp import client as mcp


@pytest.fixture
def store(tmp_path, monkeypatch):
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setattr(mcp, "STATE_DIR", str(state))
    monkeypatch.setattr(mcp, "STORE_FILE", str(state / "mcp_connections.json"))
    return state


class _FakeHTTPResponse:
    def __init__(self, payload: str):
        self._payload = payload

    def read(self):
        return self._payload.encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_load_missing_corrupt_and_non_dict(store, monkeypatch):
    assert mcp._load() == {}
    Path(mcp.STORE_FILE).write_text("{not json", encoding="utf-8")
    assert mcp._load() == {}
    Path(mcp.STORE_FILE).write_text("[1, 2]", encoding="utf-8")
    assert mcp._load() == {}
    Path(mcp.STORE_FILE).write_text('{"a": 1}', encoding="utf-8")
    assert mcp._load() == {"a": 1}


def test_save_is_atomic_and_private(store):
    mcp._save({"x": "y"})
    path = Path(mcp.STORE_FILE)
    assert json.loads(path.read_text(encoding="utf-8")) == {"x": "y"}
    assert (path.stat().st_mode & 0o777) == 0o600


def test_update_read_modify_write(store):
    def mutate(data):
        data["k"] = 1

    assert mcp._update(mutate)["k"] == 1
    assert mcp._load()["k"] == 1


def test_validate_http_url():
    mcp._validate_http_url("https://example.com/mcp")
    mcp._validate_http_url("http://127.0.0.1:1/x")
    with pytest.raises(ValueError):
        mcp._validate_http_url("file:///etc/passwd")
    with pytest.raises(ValueError):
        mcp._validate_http_url("https:///nohost")


def test_http_get_and_empty_body(monkeypatch):
    calls = []

    def fake_urlopen(req, timeout=0):
        calls.append((req.full_url, req.get_method(), req.data, timeout))
        return _FakeHTTPResponse('{"ok": true}' if len(calls) == 1 else "")

    monkeypatch.setattr(mcp.urllib.request, "urlopen", fake_urlopen)
    assert mcp._http("GET", "https://x.test/a", timeout=5) == {"ok": True}
    assert mcp._http("POST", "https://x.test/b", body={"a": 1}) == {}
    assert calls[0][1] == "GET"
    assert calls[1][1] == "POST"
    assert json.loads(calls[1][2].decode()) == {"a": 1}


def test_post_form_encodes_fields(monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout=0):
        captured["data"] = req.data.decode()
        captured["ctype"] = req.headers.get("Content-type")
        return _FakeHTTPResponse('{"access_token": "t"}')

    monkeypatch.setattr(mcp.urllib.request, "urlopen", fake_urlopen)
    out = mcp._post_form("https://x.test/token", {"a": "b c", "d": "e"})
    assert out == {"access_token": "t"}
    assert "a=b+c" in captured["data"]
    assert captured["ctype"].startswith("application/x-www-form-urlencoded")


def test_discover_oauth_falls_back_to_second_url(monkeypatch):
    seen = []

    def fake_http(method, url, *a, **k):
        seen.append(url)
        if len(seen) == 1:
            raise OSError("nope")
        return {"authorization_endpoint": "https://auth"}

    monkeypatch.setattr(mcp, "_http", fake_http)
    out = mcp._discover_oauth("https://mcp.example.com/mcp")
    assert out["authorization_endpoint"] == "https://auth"
    assert len(seen) == 2


def test_discover_oauth_all_fail(monkeypatch):
    def fake_http(*a, **k):
        raise OSError("down")

    monkeypatch.setattr(mcp, "_http", fake_http)
    with pytest.raises(RuntimeError):
        mcp._discover_oauth("https://mcp.example.com/mcp")


def test_basic_auth_header():
    assert mcp._basic_auth_header({}) == {}
    header = mcp._basic_auth_header({"client_id": "id", "client_secret": "sec"})
    import base64

    assert header["Authorization"] == "Basic " + base64.b64encode(b"id:sec").decode()


def test_start_connect_unknown_server(store):
    out = mcp.start_connect("nope", "http://localhost/cb")
    assert out["status"] == "error"
    assert "tak dikenal" in out["message"]


def test_start_connect_success_and_store(store, monkeypatch):
    monkeypatch.setattr(
        mcp,
        "_discover_oauth",
        lambda url: {
            "registration_endpoint": "https://auth.test/register",
            "authorization_endpoint": "https://auth.test/authorize",
            "token_endpoint": "https://auth.test/token",
        },
    )
    monkeypatch.setattr(
        mcp,
        "_http",
        lambda *a, **k: {"client_id": "cid", "client_secret": "csec"},
    )
    out = mcp.start_connect("lottiefiles", "http://localhost:8080/cb")
    assert out["status"] == "success"
    assert "code_challenge=" in out["auth_url"]
    stored = mcp._load()["lottiefiles"]
    assert stored["client_id"] == "cid"
    assert stored["connected"] is False
    assert stored["code_verifier"]


def test_start_connect_missing_endpoints(store, monkeypatch):
    monkeypatch.setattr(mcp, "_discover_oauth", lambda url: {"authorization_endpoint": "x"})
    out = mcp.start_connect("lottiefiles", "http://localhost/cb")
    assert out["status"] == "error"


def test_start_connect_registration_rejected(store, monkeypatch):
    monkeypatch.setattr(
        mcp,
        "_discover_oauth",
        lambda url: {
            "registration_endpoint": "https://auth.test/register",
            "authorization_endpoint": "https://auth.test/authorize",
        },
    )
    monkeypatch.setattr(mcp, "_http", lambda *a, **k: {"error": "denied"})
    out = mcp.start_connect("lottiefiles", "http://localhost/cb")
    assert out["status"] == "error"
    assert "Registrasi" in out["message"]


def test_start_connect_discovery_failure(store, monkeypatch):
    monkeypatch.setattr(mcp, "_discover_oauth", lambda url: (_ for _ in ()).throw(RuntimeError("x")))
    out = mcp.start_connect("lottiefiles", "http://localhost/cb")
    assert out["status"] == "error"
    assert "OAuth" in out["message"]


def test_start_connect_save_failure(store, monkeypatch):
    monkeypatch.setattr(
        mcp,
        "_discover_oauth",
        lambda url: {
            "registration_endpoint": "https://auth.test/register",
            "authorization_endpoint": "https://auth.test/authorize",
        },
    )
    monkeypatch.setattr(mcp, "_http", lambda *a, **k: {"client_id": "cid"})
    monkeypatch.setattr(mcp, "_update", lambda mutate: (_ for _ in ()).throw(OSError("disk")))
    out = mcp.start_connect("lottiefiles", "http://localhost/cb")
    assert out["status"] == "error"
    assert "menyimpan" in out["message"]


def _seed_session(store, state="s1", endpoint="https://auth.test/token"):
    mcp._save(
        {
            "lottiefiles": {
                "url": "https://mcp.lottiefiles.com/mcp",
                "client_id": "cid",
                "client_secret": "sec",
                "redirect_uri": "http://localhost/cb",
                "code_verifier": "ver",
                "state": state,
                "token_endpoint": endpoint,
                "connected": False,
            }
        }
    )


def test_finish_connect_invalid_state(store):
    out = mcp.finish_connect("code", "no-colon")
    assert out["status"] == "error"


def test_finish_connect_missing_session(store):
    out = mcp.finish_connect("code", "lottiefiles:abc")
    assert out["status"] == "error"


def test_finish_connect_missing_expected_state(store):
    mcp._save({"lottiefiles": {"token_endpoint": "https://t"}})
    out = mcp.finish_connect("code", "lottiefiles:abc")
    assert out["status"] == "error"


def test_finish_connect_state_mismatch(store):
    _seed_session(store, state="right")
    out = mcp.finish_connect("code", "lottiefiles:wrong")
    assert out["status"] == "error"


def test_finish_connect_success_urlencoded(store, monkeypatch):
    _seed_session(store, state="right")
    monkeypatch.setattr(
        mcp, "_post_form", lambda *a, **k: {"access_token": "at", "refresh_token": "rt", "expires_in": 60}
    )
    out = mcp.finish_connect("code", "lottiefiles%3Aright")
    assert out["status"] == "success"
    ent = mcp._load()["lottiefiles"]
    assert ent["access_token"] == "at"
    assert ent["connected"] is True
    assert "code_verifier" not in ent
    assert "state" not in ent


def test_finish_connect_token_error(store, monkeypatch):
    _seed_session(store, state="right")

    def boom(*a, **k):
        raise OSError("refused")

    monkeypatch.setattr(mcp, "_post_form", boom)
    out = mcp.finish_connect("code", "lottiefiles:right")
    assert out["status"] == "error"


def test_finish_connect_token_rejected(store, monkeypatch):
    _seed_session(store, state="right")
    monkeypatch.setattr(mcp, "_post_form", lambda *a, **k: {"error": "invalid_grant"})
    out = mcp.finish_connect("code", "lottiefiles:right")
    assert out["status"] == "error"
    assert "ditolak" in out["message"]


def test_finish_connect_save_failure(store, monkeypatch):
    _seed_session(store, state="right")
    monkeypatch.setattr(mcp, "_post_form", lambda *a, **k: {"access_token": "at"})
    monkeypatch.setattr(mcp, "_update", lambda mutate: (_ for _ in ()).throw(OSError("disk")))
    out = mcp.finish_connect("code", "lottiefiles:right")
    assert out["status"] == "error"


def test_fresh_token_missing(store):
    mcp._save({"lottiefiles": {"url": "https://x"}})
    with pytest.raises(RuntimeError):
        mcp._fresh_token("lottiefiles")


def test_fresh_token_valid_no_expiry(store):
    mcp._save({"lottiefiles": {"access_token": "at"}})
    assert mcp._fresh_token("lottiefiles") == "at"


def test_fresh_token_not_expired(store):
    import time

    mcp._save({"lottiefiles": {"access_token": "at", "expires_at": time.time() + 3600}})
    assert mcp._fresh_token("lottiefiles") == "at"


def test_fresh_token_expired_without_refresh(store):
    import time

    mcp._save({"lottiefiles": {"access_token": "at", "expires_at": time.time() - 10}})
    with pytest.raises(RuntimeError):
        mcp._fresh_token("lottiefiles")


def test_fresh_token_expired_without_endpoint(store):
    import time

    mcp._save(
        {"lottiefiles": {"access_token": "at", "refresh_token": "rt", "expires_at": time.time() - 10}}
    )
    with pytest.raises(RuntimeError):
        mcp._fresh_token("lottiefiles")


def test_fresh_token_refresh_success(store, monkeypatch):
    import time

    _seed_session(store)
    ent = mcp._load()["lottiefiles"]
    ent.update({"access_token": "old", "refresh_token": "rt", "expires_at": time.time() - 10})
    mcp._save({"lottiefiles": ent})
    monkeypatch.setattr(
        mcp, "_post_form", lambda *a, **k: {"access_token": "new", "refresh_token": "rt2", "expires_in": 120}
    )
    assert mcp._fresh_token("lottiefiles") == "new"
    assert mcp._load()["lottiefiles"]["refresh_token"] == "rt2"


def test_fresh_token_refresh_failure_marks_disconnected(store, monkeypatch):
    import time

    _seed_session(store)
    ent = mcp._load()["lottiefiles"]
    ent.update({"access_token": "old", "refresh_token": "rt", "expires_at": time.time() - 10})
    mcp._save({"lottiefiles": ent})

    def boom(*a, **k):
        raise OSError("down")

    monkeypatch.setattr(mcp, "_post_form", boom)
    with pytest.raises(RuntimeError):
        mcp._fresh_token("lottiefiles")
    assert mcp._load()["lottiefiles"]["connected"] is False


def test_fresh_token_refresh_empty_response(store, monkeypatch):
    import time

    _seed_session(store)
    ent = mcp._load()["lottiefiles"]
    ent.update({"access_token": "old", "refresh_token": "rt", "expires_at": time.time() - 10})
    mcp._save({"lottiefiles": ent})
    monkeypatch.setattr(mcp, "_post_form", lambda *a, **k: {})
    with pytest.raises(RuntimeError):
        mcp._fresh_token("lottiefiles")


def test_connection_status(store):
    mcp._save(
        {
            "a": {"connected": True, "url": "u1"},
            "b": {"connected": False, "url": "u2"},
        }
    )
    assert mcp.connection_status("a")["connected"] is True
    assert mcp.connection_status("missing")["connected"] is False
    all_status = mcp.connection_status()
    assert {s["server"] for s in all_status["servers"]} == {"a", "b"}


def test_run_sync_plain_success():
    async def coro():
        return {"status": "ok"}

    assert mcp._run_sync(coro, 5) == {"status": "ok"}


def test_run_sync_plain_non_dict():
    async def coro():
        return [1, 2]

    assert mcp._run_sync(coro, 5) == {"status": "success", "result": [1, 2]}


def test_run_sync_propagates_error():
    async def coro():
        raise ValueError("bad")

    with pytest.raises(ValueError):
        mcp._run_sync(coro, 5)


@pytest.mark.asyncio
async def test_run_sync_inside_running_loop():
    async def coro():
        return {"status": "inner"}

    assert mcp._run_sync(coro, 5) == {"status": "inner"}


@pytest.mark.asyncio
async def test_run_sync_timeout_branch(monkeypatch):
    class FakeThread:
        def __init__(self, *a, **k):
            self._alive = True

        def start(self):
            pass

        def join(self, timeout=None):
            pass

        def is_alive(self):
            return self._alive

    monkeypatch.setattr(mcp.threading, "Thread", FakeThread)

    async def coro():
        return {}

    out = mcp._run_sync(coro, 1)
    assert out["status"] == "error"
    assert "Timeout" in out["message"]


def test_call_tool_sync_unknown_server(store):
    out = mcp.call_tool_sync("nope", "tool")
    assert out["status"] == "error"


def test_call_tool_sync_success(store, monkeypatch):
    _seed_session(store)
    mcp._save({**mcp._load(), "lottiefiles": {**mcp._load()["lottiefiles"], "access_token": "at"}})

    async def fake_call(url, token, tool, args, timeout):
        return {"echo": args}

    monkeypatch.setattr(mcp, "_call_remote", fake_call)
    out = mcp.call_tool_sync("lottiefiles", "echo", {"a": 1})
    assert out == {"status": "success", "result": {"echo": {"a": 1}}}


def test_call_tool_sync_fresh_token_error(store):
    _seed_session(store)
    out = mcp.call_tool_sync("lottiefiles", "echo")
    assert out["status"] == "error"


def test_call_tool_sync_remote_error(store, monkeypatch):
    _seed_session(store)
    mcp._save({**mcp._load(), "lottiefiles": {**mcp._load()["lottiefiles"], "access_token": "at"}})

    async def boom(*a, **k):
        raise RuntimeError("remote down")  # noqa: TRY003

    monkeypatch.setattr(mcp, "_call_remote", boom)
    out = mcp.call_tool_sync("lottiefiles", "echo")
    assert out["status"] == "error"
    assert "remote down" in out["message"]


def test_list_tools_sync_unknown_and_success(store, monkeypatch):
    assert mcp.list_tools_sync("nope")["status"] == "error"
    _seed_session(store)
    mcp._save({**mcp._load(), "lottiefiles": {**mcp._load()["lottiefiles"], "access_token": "at"}})

    async def fake_list(url, token, timeout):
        return [{"name": "t"}]

    monkeypatch.setattr(mcp, "_list_remote", fake_list)
    assert mcp.list_tools_sync("lottiefiles") == {
        "status": "success",
        "tools": [{"name": "t"}],
    }


def test_list_tools_sync_fresh_token_error(store):
    _seed_session(store)
    assert mcp.list_tools_sync("lottiefiles")["status"] == "error"


def test_list_tools_sync_remote_error(store, monkeypatch):
    _seed_session(store)
    mcp._save({**mcp._load(), "lottiefiles": {**mcp._load()["lottiefiles"], "access_token": "at"}})

    async def boom(*a, **k):
        raise RuntimeError("remote")

    monkeypatch.setattr(mcp, "_list_remote", boom)
    assert mcp.list_tools_sync("lottiefiles")["status"] == "error"


# ---------------------------------------------------------------------------
# Remote transport (SDK MCP di-fake lewat sys.modules)
# ---------------------------------------------------------------------------


class _FakeSession:
    def __init__(self, read, write):
        self.read = read
        self.write = write

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def initialize(self):
        return None

    async def call_tool(self, tool, args):
        return types.SimpleNamespace(model_dump=lambda mode=None: {"tool": tool, "args": args})

    async def list_tools(self):
        tool = types.SimpleNamespace(name="echo", description="d" * 300, inputSchema={"type": "object"})
        return types.SimpleNamespace(tools=[tool])


class _FakeStreamCM:
    def __init__(self, streams):
        self.streams = streams

    async def __aenter__(self):
        return self.streams

    async def __aexit__(self, *a):
        return False


def _install_fake_mcp(monkeypatch, signature: str = "headers"):
    pkg = types.ModuleType("mcp")
    pkg.__path__ = []
    client_pkg = types.ModuleType("mcp.client")
    client_pkg.__path__ = []
    stream_mod = types.ModuleType("mcp.client.streamable_http")
    session_mod = types.ModuleType("mcp.client.session")

    if signature == "headers":
        def transport(url, headers=None, timeout=None):
            transport.kwargs = {"headers": headers, "timeout": timeout}
            return _FakeStreamCM((object(), object(), None))
    else:
        def transport(url, http_client=None):
            transport.kwargs = {"http_client": http_client}
            return _FakeStreamCM((object(), object()))

    stream_mod.streamablehttp_client = transport
    session_mod.ClientSession = _FakeSession
    monkeypatch.setitem(sys.modules, "mcp", pkg)
    monkeypatch.setitem(sys.modules, "mcp.client", client_pkg)
    monkeypatch.setitem(sys.modules, "mcp.client.streamable_http", stream_mod)
    monkeypatch.setitem(sys.modules, "mcp.client.session", session_mod)
    return transport


@pytest.mark.asyncio
async def test_remote_session_headers_path(monkeypatch):
    transport = _install_fake_mcp(monkeypatch, "headers")
    async with mcp._remote_session("https://x/mcp", "tok", 5) as session:
        assert isinstance(session, _FakeSession)
    assert transport.kwargs["headers"]["Authorization"] == "Bearer tok"


@pytest.mark.asyncio
async def test_remote_session_http_client_path(monkeypatch):
    transport = _install_fake_mcp(monkeypatch, "http_client")
    async with mcp._remote_session("https://x/mcp", "tok", 5) as session:
        assert isinstance(session, _FakeSession)
    assert "http_client" in transport.kwargs


@pytest.mark.asyncio
async def test_call_and_list_remote(monkeypatch):
    _install_fake_mcp(monkeypatch, "headers")
    out = await mcp._call_remote("https://x/mcp", "tok", "echo", {"a": 1}, 5)
    assert out["tool"] == "echo"
    tools = await mcp._list_remote("https://x/mcp", "tok", 5)
    assert tools[0]["name"] == "echo"
    assert len(tools[0]["description"]) == 200


def test_import_streamable_client_fallback(monkeypatch):
    pkg = types.ModuleType("mcp")
    pkg.__path__ = []
    client_pkg = types.ModuleType("mcp.client")
    client_pkg.__path__ = []
    stream_mod = types.ModuleType("mcp.client.streamable_http")
    v2 = MagicMock()
    stream_mod.streamable_http_client = v2
    monkeypatch.setitem(sys.modules, "mcp", pkg)
    monkeypatch.setitem(sys.modules, "mcp.client", client_pkg)
    monkeypatch.setitem(sys.modules, "mcp.client.streamable_http", stream_mod)
    assert mcp._import_streamable_client() is v2
