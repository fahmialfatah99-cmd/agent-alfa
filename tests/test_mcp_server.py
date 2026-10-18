"""
Unit tests for ALFA Model Context Protocol (MCP) Server.
Verifies MCP server initialization, tool exposure, schema integrity, and execution.
"""

import json

import pytest

try:
    import mcp.types as types
    from mcp.server import Server as Server

    HAS_MCP = True
except ImportError:
    HAS_MCP = False

from alfa.mcp.server import create_mcp_server


@pytest.mark.skipif(not HAS_MCP, reason="mcp package not installed")
class TestAlfaMCPServer:
    """Test suite for ALFA MCP Server."""

    def test_create_mcp_server(self):
        """Verify MCP server instance creation."""
        server = create_mcp_server("test-alfa-mcp")
        assert server is not None
        assert server.name == "test-alfa-mcp"
        assert types.ListToolsRequest in server.request_handlers
        assert types.CallToolRequest in server.request_handlers

    @pytest.mark.asyncio
    async def test_list_tools_returns_all_registered_tools(self):
        """Verify list_tools exposes all tools with valid JSON input schemas."""
        server = create_mcp_server("test-alfa-mcp")
        handler = server.request_handlers[types.ListToolsRequest]
        res = await handler(None)
        tools = res.root.tools
        assert len(tools) >= 100

        tool_names = {t.name for t in tools}
        assert "deep_research_topic" in tool_names
        assert "generate_secure_password" in tool_names
        assert "get_system_stats" in tool_names

        # Check inputSchema validity
        for t in tools:
            assert isinstance(t.inputSchema, dict)
            assert t.inputSchema.get("type") == "object"
            assert "properties" in t.inputSchema

    @pytest.mark.asyncio
    async def test_call_tool_executes_successfully(self):
        """Verify tool execution via MCP CallToolRequest."""
        server = create_mcp_server("test-alfa-mcp")
        call_handler = server.request_handlers[types.CallToolRequest]
        call_req = types.CallToolRequest(
            method="tools/call",
            params=types.CallToolRequestParams(
                name="generate_secure_password",
                arguments={"length": 12, "count": 1},
            ),
        )
        res = await call_handler(call_req)
        assert len(res.root.content) == 1
        text = res.root.content[0].text
        assert "success" in text

    @pytest.mark.asyncio
    async def test_call_nonexistent_tool_returns_error(self):
        """Verify calling an unknown tool returns an error payload gracefully."""
        server = create_mcp_server("test-alfa-mcp")
        call_handler = server.request_handlers[types.CallToolRequest]
        call_req = types.CallToolRequest(
            method="tools/call",
            params=types.CallToolRequestParams(
                name="nonexistent_tool_xyz_123",
                arguments={},
            ),
        )
        res = await call_handler(call_req)
        text = res.root.content[0].text
        assert "error" in text
        assert "not found" in text

    @pytest.mark.asyncio
    async def test_list_resources_mengekspos_status_dan_katalog(self):
        """Ekspansi: MCP resources — status & katalog tools (alfa://)."""
        server = create_mcp_server("test-alfa-mcp")
        assert types.ListResourcesRequest in server.request_handlers
        assert types.ReadResourceRequest in server.request_handlers

        list_handler = server.request_handlers[types.ListResourcesRequest]
        res = await list_handler(None)
        uris = {str(r.uri) for r in res.root.resources}
        assert "alfa://status" in uris
        assert "alfa://tools/catalog" in uris

    @pytest.mark.asyncio
    async def test_read_resource_status_berisi_jumlah_tools(self):
        server = create_mcp_server("test-alfa-mcp")
        read_handler = server.request_handlers[types.ReadResourceRequest]
        req = types.ReadResourceRequest(
            method="resources/read",
            params=types.ReadResourceRequestParams(uri=types.AnyUrl("alfa://status")),
        )
        res = await read_handler(req)
        text = res.root.contents[0].text
        payload = json.loads(text)
        assert payload["protocol"] == "mcp"
        assert payload["tools"] >= 100

    @pytest.mark.asyncio
    async def test_read_resource_katalog_menyertakan_tool_dasar(self):
        server = create_mcp_server("test-alfa-mcp")
        read_handler = server.request_handlers[types.ReadResourceRequest]
        req = types.ReadResourceRequest(
            method="resources/read",
            params=types.ReadResourceRequestParams(
                uri=types.AnyUrl("alfa://tools/catalog")
            ),
        )
        res = await read_handler(req)
        payload = json.loads(res.root.contents[0].text)
        assert "generate_secure_password" in payload

    @pytest.mark.asyncio
    async def test_read_resource_uri_tidak_dikenal_gagal(self):
        server = create_mcp_server("test-alfa-mcp")
        read_handler = server.request_handlers[types.ReadResourceRequest]
        req = types.ReadResourceRequest(
            method="resources/read",
            params=types.ReadResourceRequestParams(
                uri=types.AnyUrl("alfa://misteri")
            ),
        )
        with pytest.raises(KeyError):
            await read_handler(req)


@pytest.mark.skipif(not HAS_MCP, reason="mcp package not installed")
class TestAlfaMCPStreamableHttp:
    """Transport HTTP streamable: token wajib (fail-closed) + handshake."""

    def test_factory_gagal_tanpa_token(self, monkeypatch):
        from alfa.mcp.http_server import create_streamable_http_app

        monkeypatch.delenv("ALFA_MCP_HTTP_TOKEN", raising=False)
        with pytest.raises(RuntimeError) as err:
            create_streamable_http_app("t", token="")
        assert "fail-closed" in str(err.value) or "MENOLAK" in str(err.value)

    def get_client(self, allowed_hosts_extra=None):
        from fastapi.testclient import TestClient

        from alfa.mcp.http_server import create_streamable_http_app

        hosts = ["testserver", "localhost:*", "127.0.0.1:*"]
        if allowed_hosts_extra:
            hosts.extend(allowed_hosts_extra)
        app = create_streamable_http_app(
            "test-alfa-http",
            token="koin-privat-b3naR",
            allowed_hosts=hosts,
        )
        return TestClient(app)

    _INIT_BODY = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "0"},
        },
    }
    _ACCEPT = "application/json, text/event-stream"

    def test_post_tanpa_token_ditolak_401(self, monkeypatch):
        monkeypatch.setenv("ALFA_MCP_HTTP_TOKEN", "koin-privat-b3naR")
        with self.get_client() as client:
            resp = client.post(
                "/",
                json=self._INIT_BODY,
                headers={"Accept": self._ACCEPT},
            )
        assert resp.status_code == 401
        assert resp.json()["error"] == "unauthorized"

    def test_initialize_handshake_dengan_token(self, monkeypatch):
        monkeypatch.setenv("ALFA_MCP_HTTP_TOKEN", "koin-privat-b3naR")
        with self.get_client() as client:
            resp = client.post(
                "/",
                json=self._INIT_BODY,
                headers={
                    "Accept": self._ACCEPT,
                    "Authorization": "Bearer koin-privat-b3naR",
                },
            )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["result"]["protocolVersion"], "versi protokol dinegosiasikan"
        assert body["result"]["serverInfo"]["name"].startswith("test-alfa")

    def test_token_via_header_x_mcp_token_juga_diterima(self, monkeypatch):
        monkeypatch.setenv("ALFA_MCP_HTTP_TOKEN", "koin-privat-b3naR")
        with self.get_client() as client:
            resp = client.post(
                "/",
                json=self._INIT_BODY,
                headers={"Accept": self._ACCEPT, "X-MCP-Token": "koin-privat-b3naR"},
            )
        assert resp.status_code == 200, resp.text

    def test_host_tak_diizinkan_diblok_rebinding(self, monkeypatch):
        import pytest as _pytest

        _pytest.importorskip("fastapi.testclient")
        monkeypatch.setenv("ALFA_MCP_HTTP_TOKEN", "koin-privat-b3naR")
        from fastapi.testclient import TestClient

        from alfa.mcp.http_server import create_streamable_http_app

        app = create_streamable_http_app(
            "t", token="koin-privat-b3naR", allowed_hosts=["localhost:*"]
        )
        with TestClient(app) as client:
            resp = client.post(
                "/",
                json=self._INIT_BODY,
                headers={
                    "Accept": self._ACCEPT,
                    "Authorization": "Bearer koin-privat-b3naR",
                },
            )
        # Host "testserver" tidak ada di daftar izin → rebinding guard menolak
        # (SDK memakai 421 Misdirected Request utk host tak sah)
        assert resp.status_code in (403, 400, 421), resp.text

    def test_factory_via_env_token(self, monkeypatch):
        monkeypatch.setenv("ALFA_MCP_HTTP_TOKEN", "r4hasia-env")
        from alfa.mcp.http_server import create_streamable_http_app

        app = create_streamable_http_app("env-mcp", allowed_hosts=["testserver"])
        assert app is not None


@pytest.mark.skipif(not HAS_MCP, reason="mcp package not installed")
class TestMcpStatusRoute:
    """Route dashboard /api/mcp/status (admin-gated)."""

    def _client_admin(self):
        import importlib
        import uuid

        from fastapi.testclient import TestClient

        from alfa.dashboard.routes.auth import (
            _create_session_token,
            create_user,
            init_auth_db,
            store_session,
        )

        init_auth_db()
        uname = f"mcpadmin-{uuid.uuid4().hex[:6]}"
        created = create_user(uname, "mcp-status-pwd", 0, True)
        uid = int(created["user_id"])
        token = _create_session_token(uid, uname)
        store_session(uid, token)
        app_mod = importlib.import_module("alfa.dashboard.app")
        return TestClient(app_mod.app), {"Cookie": f"session_token={token}"}

    def test_sesi_member_non_admin_ditolak_403(self):
        """Mode token (conftest off → local mode) anonim = admin lokal;

        gate sesungguhnya teruji lewat sesi member non-admin → 403 (dokumen
        modul require_admin: mode lokal lolos, non-admin 403).
        """
        import importlib
        import uuid

        from fastapi.testclient import TestClient

        from alfa.dashboard.routes.auth import (
            _create_session_token,
            create_user,
            init_auth_db,
            store_session,
        )

        init_auth_db()
        uname = f"mcpmember-{uuid.uuid4().hex[:6]}"
        created = create_user(uname, "member-passk", 0, False)
        uid = int(created["user_id"])
        token = _create_session_token(uid, uname)
        store_session(uid, token)
        app_mod = importlib.import_module("alfa.dashboard.app")
        client = TestClient(app_mod.app)
        resp = client.get("/api/mcp/status", headers={"Cookie": f"session_token={token}"})
        assert resp.status_code == 403, resp.text

    def test_admin_melihat_status_transport(self):
        client, headers = self._client_admin()
        resp = client.get("/api/mcp/status", headers=headers)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["http_transport"]["tersedia"] is True
        assert body["stdio_transport"]["tersedia"] is True
        assert "remote_connectors" in body
