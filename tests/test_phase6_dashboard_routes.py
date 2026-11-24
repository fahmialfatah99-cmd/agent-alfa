"""Phase 6 coverage: dashboard workspace, agents, pipelines, memory, dan tools.

Hermetic: DB SQLite sementara, HOME/REPO_ROOT ke tmp, tool jaringan & vault
di-mock. Tidak ada file pengguna atau layanan produksi yang disentuh.
"""

from __future__ import annotations

import sqlite3
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    db_file = tmp_path / "routes.db"
    monkeypatch.setenv("ALFA_DB_PATH", str(db_file))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from alfa.core import database
    from alfa.core.db import connection

    connection.init_db_sync()
    with database.get_sync_db() as conn:
        conn.execute("DELETE FROM custom_agents")
        conn.commit()
    return db_file


@pytest.fixture
def client(isolated_db, tmp_path, monkeypatch):
    from alfa.core import config
    from alfa.dashboard import app as pkg_app
    from alfa.dashboard.ratelimit import reset_rate_limits
    from alfa.dashboard.routes import auth as auth_mod
    from alfa.dashboard.routes import tools as tools_routes
    from alfa.dashboard.routes.system import pipelines_memory, settings_admin

    home = tmp_path / "home"
    home.mkdir()
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("DASHBOARD_AUTH_TOKEN", "")
    monkeypatch.setenv("ALFA_INSECURE_LOCAL", "true")
    monkeypatch.setenv("ALLOWED_USER_IDS", "42")
    monkeypatch.setattr(auth_mod, "DASHBOARD_AUTH_TOKEN", "")
    monkeypatch.setattr(config, "SECRETS_PATH", tmp_path / "no-secrets.env")
    monkeypatch.setattr(settings_admin, "REPO_ROOT", str(repo))
    monkeypatch.setattr(pipelines_memory, "REPO_ROOT", str(repo))
    monkeypatch.setattr(tools_routes, "REPO_ROOT", str(repo))
    reset_rate_limits()
    return TestClient(pkg_app)


@pytest.fixture
def ws(tmp_path, monkeypatch):
    from alfa.dashboard.routes.system import workspace_vault

    root = tmp_path / "workspace"
    root.mkdir()
    monkeypatch.setattr(
        workspace_vault,
        "WORKSPACE_ROOTS",
        [{"id": "workspace", "label": "WS", "path": str(root)}],
    )
    return workspace_vault, root


# ---------------------------------------------------------------------------
# Workspace: artifacts, roots, tree, file
# ---------------------------------------------------------------------------


def _hide_sandbox(monkeypatch, module):
    real_exists = module.os.path.exists

    def fake_exists(path):
        if str(path) == "/dev/shm/alfa_sandbox":
            return False
        return real_exists(path)

    monkeypatch.setattr(module.os.path, "exists", fake_exists)


def test_list_artifacts(client, ws, monkeypatch):
    module, _ = ws
    home_dir = Path(__import__("os").environ["HOME"])
    out_dir = home_dir / "output"
    out_dir.mkdir(parents=True)
    (out_dir / "foto.PNG").write_bytes(b"x" * 2048)
    (out_dir / "abaikan.txt").write_text("x", encoding="utf-8")
    alfa_dir = home_dir / ".alfa"
    alfa_dir.mkdir()
    (alfa_dir / "data.json").write_text("{}", encoding="utf-8")
    _hide_sandbox(monkeypatch, module)
    out = client.get("/api/artifacts").json()
    names = {a["name"] for a in out["artifacts"]}
    assert "foto.PNG" in names
    assert "data.json" in names
    assert "abaikan.txt" not in names
    foto = next(a for a in out["artifacts"] if a["name"] == "foto.PNG")
    assert foto["is_image"] is True
    assert foto["extension"] == "PNG"


def test_workspace_roots(client, ws):
    module, root = ws
    (root / "sub").mkdir()
    out = client.get("/api/workspace/roots").json()
    assert out["status"] == "success"
    assert out["roots"][0]["exists"] is True


def test_workspace_tree_and_filters(client, ws, monkeypatch):
    module, root = ws
    (root / "b.txt").write_text("b", encoding="utf-8")
    (root / "a_dir").mkdir()
    (root / ".hidden").mkdir()
    (root / "venv").mkdir()
    out = client.get("/api/workspace/tree", params={"path": str(root)}).json()
    names = [i["name"] for i in out["items"]]
    assert names == ["a_dir", "b.txt"]
    assert out["items"][0]["type"] == "dir"
    assert out["items"][0]["size"] is None

    assert (
        client.get("/api/workspace/tree", params={"path": "/etc"}).status_code
        == 403
    )
    assert (
        client.get(
            "/api/workspace/tree", params={"path": str(root / "missing")}
        ).status_code
        == 404
    )

    def boom(path):
        raise PermissionError

    monkeypatch.setattr(module.os, "scandir", boom)
    assert (
        client.get("/api/workspace/tree", params={"path": str(root)}).status_code
        == 403
    )


class _FakeEntry:
    def __init__(self, name, is_dir_value=False):
        self.name = name
        self._is_dir = is_dir_value

    def is_dir(self):
        return self._is_dir

    def is_file(self):
        return not self._is_dir

    def stat(self):
        raise OSError("stat gagal")  # noqa: TRY003


def test_workspace_tree_stat_error_skipped(client, ws, monkeypatch):
    module, root = ws
    (root / "x.txt").write_text("x", encoding="utf-8")
    monkeypatch.setattr(module.os, "scandir", lambda path: [_FakeEntry("x.txt")])
    out = client.get("/api/workspace/tree", params={"path": str(root)}).json()
    assert out["items"] == []


def test_workspace_read_file_text_binary_truncated(client, ws):
    module, root = ws
    text = root / "a.txt"
    text.write_text("halo dunia", encoding="utf-8")
    out = client.get("/api/workspace/file", params={"path": str(text)}).json()
    assert out["status"] == "success"
    assert out["content"] == "halo dunia"
    assert out["truncated"] is False
    assert "download_url" in out

    binary = root / "b.bin"
    binary.write_bytes(b"\x00\x01")
    out = client.get("/api/workspace/file", params={"path": str(binary)}).json()
    assert out["status"] == "binary"
    assert "Download" in out["message"]

    big = root / "big.txt"
    big.write_text("x" * (module._WS_MAX_FILE_BYTES + 10), encoding="utf-8")
    out = client.get("/api/workspace/file", params={"path": str(big)}).json()
    assert out["truncated"] is True

    assert (
        client.get(
            "/api/workspace/file", params={"path": str(root / "missing")}
        ).status_code
        == 404
    )
    assert (
        client.get("/api/workspace/file", params={"path": "/etc/passwd"}).status_code
        == 403
    )


def test_download_artifact(client, tmp_path):
    home = Path(__import__("os").environ["HOME"])
    out_dir = home / "output"
    out_dir.mkdir(parents=True)
    target = out_dir / "hasil.txt"
    target.write_text("isi", encoding="utf-8")
    res = client.get("/api/artifacts/download", params={"path": str(target)})
    assert res.status_code == 200
    assert res.text == "isi"
    assert (
        client.get(
            "/api/artifacts/download", params={"path": "/etc/hosts"}
        ).status_code
        == 403
    )
    assert (
        client.get(
            "/api/artifacts/download", params={"path": str(out_dir / "nope")}
        ).status_code
        == 404
    )


def test_guardian_config_get_and_update(client, monkeypatch):
    from alfa import tools

    monkeypatch.setattr(
        tools,
        "proactive_system_guardian_config",
        lambda action="status", **kwargs: {
            "guardian": {"enabled": True, "last": action, "kwargs": kwargs}
        },
    )
    monkeypatch.setattr(
        tools,
        "proactive_ambient_agent_config",
        lambda action="status", **kwargs: {
            "proactive_config": {"enabled": False, "last": action}
        },
    )
    out = client.get("/api/guardian/config").json()
    assert out["guardian"]["enabled"] is True
    assert out["proactive"]["enabled"] is False

    out = client.post(
        "/api/guardian/config",
        json={
            "guardian": {"enabled": False, "cpu_threshold": 80},
            "proactive": {"enabled": True, "min_hours_between_pings": 2},
        },
    ).json()
    assert out["status"] == "success"


# ---------------------------------------------------------------------------
# Workspace: vault, audit, trust, passkey
# ---------------------------------------------------------------------------


def test_vault_routes(client, monkeypatch):
    from alfa.security import vault

    monkeypatch.setattr(vault, "list_secrets", lambda category: [{"name": "a"}])
    assert client.get("/api/vault/list").json()["items"] == [{"name": "a"}]

    stored = {}
    monkeypatch.setattr(
        vault,
        "store_secret",
        lambda name, value, category, notes: stored.update(
            name=name, value=value, category=category, notes=notes
        )
        or {"status": "success"},
    )
    assert client.post("/api/vault/store", json={}).json()["status"] == "error"
    out = client.post(
        "/api/vault/store",
        json={"name": " N ", "value": " V ", "category": "api_key", "notes": "x"},
    ).json()
    assert out["status"] == "success"
    assert stored["name"] == "N"

    monkeypatch.setattr(vault, "get_secret", lambda sid: None)
    assert client.post("/api/vault/reveal", json={}).json()["status"] == "error"
    assert client.post("/api/vault/reveal", json={"id": 1}).json()["status"] == "error"
    monkeypatch.setattr(
        vault,
        "get_secret",
        lambda sid: {"name": "n", "category": "c", "value": "v"},
    )
    out = client.post("/api/vault/reveal", json={"name": "n"}).json()
    assert out["value"] == "v"

    monkeypatch.setattr(vault, "delete_secret", lambda sid: sid == 1)
    assert client.delete("/api/vault/1").json()["status"] == "success"
    assert client.delete("/api/vault/2").json()["status"] == "error"


def test_security_audit_and_permission_log(client, monkeypatch):
    from alfa.core import permissions

    assert client.post("/api/security/audit", json={}).json()["status"] == "error"
    monkeypatch.setattr(
        permissions, "audit_website_security", lambda url: {"status": "success", "url": url}
    )
    assert (
        client.post("/api/security/audit", json={"url": "https://x"}).json()["status"]
        == "success"
    )

    from alfa.core.perm import store

    conn = store._connect()
    try:
        conn.execute(
            "INSERT INTO permission_audit (chat_id, tool_name, tier, decision, arguments_json, created_at, response_time_sec) VALUES (1, 't', 'LOW', 'allow', '{\"a\": 1}', 1, 0.5)"
        )
        conn.commit()
    finally:
        conn.close()
    out = client.get("/api/security/permission-audit", params={"chat_id": 1}).json()
    assert out["total"] == 1
    assert out["logs"][0]["arguments_json"] == {"a": 1}
    out = client.get("/api/security/permission-audit").json()
    assert out["total"] == 1


def test_trust_scores(client):
    from alfa.core.perm import store

    conn = store._connect()
    try:
        conn.execute(
            "INSERT INTO user_trust_scores (chat_id, trust_score, total_approvals, safe_approvals, risky_approvals, last_updated) VALUES (1, 0.75, 2, 1, 1, 1)"
        )
        conn.commit()
    finally:
        conn.close()
    out = client.get("/api/security/trust-scores").json()
    assert out["total_users"] == 1
    assert out["scores"][0]["trust_score"] == 0.75


def test_passkey_status_and_toggle(client):
    assert client.get("/api/vault/passkey/status").json()["enabled"] is False
    out = client.post("/api/vault/passkey/toggle", json={"enabled": True}).json()
    assert out["enabled"] is True
    assert client.get("/api/vault/passkey/status").json()["enabled"] is True
    assert (
        client.post("/api/vault/passkey/toggle", json={"enabled": False}).json()[
            "enabled"
        ]
        is False
    )


# ---------------------------------------------------------------------------
# Custom agents
# ---------------------------------------------------------------------------


def _create_agent(client, name="Riset"):
    return client.post(
        "/api/agents",
        json={
            "name": name,
            "role": "Researcher",
            "persona": "P",
            "system_instruction": "S",
            "provider": "gemini",
            "model": "gm",
        },
    ).json()


def test_agents_crud(client):
    assert client.get("/api/agents").json()["total"] == 0
    assert client.post("/api/agents", json={}).status_code == 400
    created = _create_agent(client)
    assert created["status"] == "success"
    agent_id = created["id"]
    assert client.get("/api/agents").json()["total"] == 1

    upd = client.put(
        f"/api/agents/{agent_id}", json={"role": "Analyst", "model": "baru"}
    ).json()
    assert upd["status"] == "success"
    agent = next(
        a for a in client.get("/api/agents").json()["agents"] if a["id"] == agent_id
    )
    assert agent["role"] == "Analyst"
    assert agent["model"] == "baru"
    assert client.put("/api/agents/99999", json={"role": "X"}).json()["status"] == "error"

    assert client.delete(f"/api/agents/{agent_id}").json()["status"] == "success"
    assert client.delete(f"/api/agents/{agent_id}").json()["status"] == "error"


def test_agent_chat(client, monkeypatch):
    from alfa.swarm import engine

    agent_id = _create_agent(client)["id"]
    assert client.post(f"/api/agents/{agent_id}/chat", json={}).status_code == 400
    assert (
        client.post("/api/agents/99999/chat", json={"message": "halo"}).status_code
        == 404
    )
    monkeypatch.setattr(
        engine,
        "generate_agent_response",
        AsyncMock(return_value="jawaban agen"),
    )
    out = client.post(
        f"/api/agents/{agent_id}/chat", json={"message": "halo"}
    ).json()
    assert out["status"] == "success"
    assert out["reply"] == "jawaban agen"


def test_agent_activity(client, monkeypatch):
    from alfa.core import database

    monkeypatch.setattr(
        database,
        "list_agent_activities_sync",
        lambda limit=30: [
            {"agent_id": 1, "action_type": "bash_exec", "description": "d", "tool_name": "t"}
        ],
    )
    monkeypatch.setattr(
        database, "list_subagent_tasks_sync", lambda limit=10: [{"id": "x"}]
    )
    monkeypatch.setattr(
        database,
        "list_custom_agents_sync",
        lambda: [
            {
                "id": 1,
                "name": "A",
                "role": "R",
                "provider": "gemini",
                "model": "m",
                "is_enabled": 1,
            }
        ],
    )
    out = client.get("/api/agent-activity").json()
    assert out["total_activities"] == 1
    assert out["agent_states"][0]["current_state"] == "⚙️ BASH_EXEC"
    assert out["subagent_tasks"] == [{"id": "x"}]


def _patch_swarm(monkeypatch, decision, report="laporan"):
    from alfa.swarm import engine

    responses = [decision, report]
    mock = AsyncMock(side_effect=lambda **kwargs: responses.pop(0))
    monkeypatch.setattr(engine, "generate_agent_response", mock)
    return mock


def test_agent_execute_branches(client, monkeypatch, ws):
    from alfa import tools
    from alfa.core import database

    module, root = ws
    agent_id = _create_agent(client)["id"]
    monkeypatch.setattr(
        "alfa.dashboard.routes.swarm.agents_routes._agent_working_dir",
        lambda: str(root),
    )
    logged = []
    monkeypatch.setattr(
        database,
        "log_agent_activity_sync",
        lambda **kwargs: logged.append(kwargs),
    )
    assert client.post(f"/api/agents/{agent_id}/execute", json={}).status_code == 400
    assert (
        client.post("/api/agents/99999/execute", json={"instruction": "x"}).status_code
        == 404
    )

    # SYSTEM_STATS
    _patch_swarm(monkeypatch, "TOOL: SYSTEM_STATS | none")
    monkeypatch.setattr(tools, "get_system_stats", lambda: {"cpu": 1})
    out = client.post(
        f"/api/agents/{agent_id}/execute", json={"instruction": "cek sistem"}
    ).json()
    assert out["tool_called"] == "get_system_stats"
    assert out["action_type"] == "audit"

    # BASH ditolak policy
    _patch_swarm(monkeypatch, "TOOL: BASH | rm -rf /")
    monkeypatch.setattr(
        "alfa.dashboard.routes.swarm.agents_routes._policy_denial",
        lambda cmd: "[KEAMANAN] ditolak",
    )
    out = client.post(
        f"/api/agents/{agent_id}/execute", json={"instruction": "hapus"}
    ).json()
    assert out["tool_called"] == "execute_bash_command"
    assert "[KEAMANAN]" in out["tool_output"]

    # BASH diizinkan
    monkeypatch.setattr(
        "alfa.dashboard.routes.swarm.agents_routes._policy_denial", lambda cmd: ""
    )
    monkeypatch.setattr(
        tools, "execute_bash_command", lambda cmd, working_dir="": {"stdout": "ok"}
    )
    _patch_swarm(monkeypatch, "TOOL: BASH | echo ok")
    out = client.post(
        f"/api/agents/{agent_id}/execute", json={"instruction": "echo"}
    ).json()
    assert out["tool_output"] == "ok"

    # READ_FILE
    target = root / "f.txt"
    target.write_text("isi", encoding="utf-8")
    _patch_swarm(monkeypatch, f"TOOL: READ_FILE | {target}")
    monkeypatch.setattr(
        tools, "read_local_file", lambda path: {"content": "isi file"}
    )
    out = client.post(
        f"/api/agents/{agent_id}/execute", json={"instruction": "baca"}
    ).json()
    assert out["tool_called"] == "read_local_file"
    assert out["tool_output"] == "isi file"

    # WEB_SEARCH
    _patch_swarm(monkeypatch, "TOOL: WEB_SEARCH | berita")
    monkeypatch.setattr(tools, "web_search", lambda q: {"query": q})
    out = client.post(
        f"/api/agents/{agent_id}/execute", json={"instruction": "cari"}
    ).json()
    assert out["tool_called"] == "web_search"

    # Fallback kata kunci sistem + policy ditolak
    _patch_swarm(monkeypatch, "jawaban langsung")
    monkeypatch.setattr(
        "alfa.dashboard.routes.swarm.agents_routes._policy_denial",
        lambda cmd: "[KEAMANAN] fallback",
    )
    out = client.post(
        f"/api/agents/{agent_id}/execute", json={"instruction": "jalankan git status"}
    ).json()
    assert out["tool_called"] == "execute_bash_command"
    assert "[KEAMANAN] fallback" in out["tool_output"]

    # Direct answer tanpa tool
    _patch_swarm(monkeypatch, "tidak ada tool")
    out = client.post(
        f"/api/agents/{agent_id}/execute", json={"instruction": "jelaskan konsep"}
    ).json()
    assert out["tool_called"] is None
    assert logged


def test_agent_policy_and_working_dir(monkeypatch, ws):
    from alfa.dashboard.routes.swarm import agents_routes as ar
    from alfa.security import command_policy

    module, root = ws
    monkeypatch.setenv("ALFA_TARGET_FOLDER", str(root))
    assert ar._agent_working_dir() == str(root)

    monkeypatch.delenv("ALFA_TARGET_FOLDER", raising=False)
    from alfa.swarm import workspace_hygiene

    monkeypatch.setattr(workspace_hygiene, "_get_target_folder", lambda: str(root))
    assert ar._agent_working_dir() == str(root)

    monkeypatch.setattr(
        workspace_hygiene, "_get_target_folder", MagicMock(side_effect=OSError("x"))
    )
    assert ar._agent_working_dir() == ""

    monkeypatch.setattr(command_policy, "check_agent_command", lambda cmd, working_dir="": "")
    assert ar._policy_denial("ls") == ""
    monkeypatch.setattr(
        command_policy, "check_agent_command", lambda cmd, working_dir="": "bahaya"
    )
    assert "bahaya" in ar._policy_denial("rm")
    monkeypatch.setattr(
        command_policy,
        "check_agent_command",
        MagicMock(side_effect=ValueError("policy")),
    )
    assert "Gagal memverifikasi" in ar._policy_denial("ls")


# ---------------------------------------------------------------------------
# Pipelines
# ---------------------------------------------------------------------------


@pytest.fixture
def pl(monkeypatch):
    from alfa.pipelines import engine

    return engine


def test_pipelines_list_get(client, pl, monkeypatch):
    monkeypatch.setattr(pl, "list_pipelines", lambda: [{"id": "a"}])
    monkeypatch.setattr(pl, "load_pipeline", lambda pid: {"id": pid})
    assert client.get("/api/pipelines").json()["pipelines"] == [{"id": "a"}]
    assert client.get("/api/pipelines/a").json()["pipeline"]["id"] == "a"

    monkeypatch.setattr(
        pl, "load_pipeline", MagicMock(side_effect=FileNotFoundError)
    )
    assert client.get("/api/pipelines/x").status_code == 404


def test_pipeline_run(client, pl, monkeypatch):
    seen = {}

    async def fake_run(pid, overrides):
        seen["pid"] = pid
        seen["overrides"] = overrides
        return {"status": "success"}

    monkeypatch.setattr(pl, "run_pipeline", fake_run)
    out = client.post(
        "/api/pipelines/a/run", json={"vars": {"x": 1}}
    ).json()
    assert out["status"] == "success"
    assert seen == {"pid": "a", "overrides": {"x": 1}}

    monkeypatch.setattr(
        pl, "run_pipeline", AsyncMock(side_effect=FileNotFoundError)
    )
    assert client.post("/api/pipelines/x/run", json={}).status_code == 404

    monkeypatch.setattr(
        pl, "run_pipeline", AsyncMock(side_effect=RuntimeError("boom"))
    )
    res = client.post("/api/pipelines/a/run", json={})
    assert res.status_code == 500
    assert "boom" in res.json()["detail"]


def test_pipeline_run_bad_json(client, pl, monkeypatch):
    monkeypatch.setattr(pl, "run_pipeline", AsyncMock(return_value={}))
    res = client.post(
        "/api/pipelines/a/run",
        content=b"{bukan-json",
        headers={"Content-Type": "application/json"},
    )
    assert res.status_code == 200


def test_pipeline_save(client, pl, monkeypatch):
    monkeypatch.setattr(pl, "save_pipeline", lambda data: "/tmp/a.json")
    res = client.post(
        "/api/pipelines/a", content=b"{bad", headers={"Content-Type": "application/json"}
    )
    assert res.status_code == 400
    assert client.post("/api/pipelines/a", json={}).status_code == 400
    out = client.post("/api/pipelines/a", json={"steps": [{"x": 1}]}).json()
    assert out == {"status": "success", "file": "a.json"}

    monkeypatch.setattr(
        pl, "save_pipeline", MagicMock(side_effect=RuntimeError("disk"))
    )
    res = client.post("/api/pipelines/a", json={"steps": [1]})
    assert res.status_code == 500


def test_pipeline_webhook(client, pl, monkeypatch):
    monkeypatch.setattr(pl, "load_pipeline", lambda pid: {"trigger": {"secret": "s3"}})
    monkeypatch.setattr(
        pl, "run_pipeline", AsyncMock(return_value={"pipeline": "a", "status": "success", "extra": 1})
    )
    assert client.post("/api/pipelines/a/webhook", json={}).status_code == 401
    out = client.post(
        "/api/pipelines/a/webhook?key=s3", json={"x": 1}
    ).json()
    assert out == {"pipeline": "a", "status": "success"}

    monkeypatch.setattr(pl, "load_pipeline", lambda pid: {"trigger": {}})
    res = client.post(
        "/api/pipelines/a/webhook",
        content=b"bukan-json",
        headers={"Content-Type": "application/json"},
    )
    assert res.json()["status"] == "success"

    monkeypatch.setattr(pl, "load_pipeline", MagicMock(side_effect=FileNotFoundError))
    assert client.post("/api/pipelines/x/webhook", json={}).status_code == 404


def test_pipeline_runs_and_enable(client, pl, monkeypatch):
    monkeypatch.setattr(pl, "list_runs", lambda pid, limit: [{"id": 1}])
    assert client.get("/api/pipelines/a/runs").json()["runs"] == [{"id": 1}]

    saved = {}
    monkeypatch.setattr(pl, "load_pipeline", lambda pid: {"trigger": {}})
    monkeypatch.setattr(pl, "save_pipeline", lambda data: saved.update(data) or "/tmp/x")
    out = client.post(
        "/api/pipelines/a/enable", json={"enabled": True, "minutes": 5}
    ).json()
    assert out["trigger"]["enabled"] is True
    assert out["trigger"]["minutes"] == 5

    monkeypatch.setattr(pl, "load_pipeline", MagicMock(side_effect=FileNotFoundError))
    assert client.post("/api/pipelines/x/enable", json={}).status_code == 404
    monkeypatch.setattr(pl, "load_pipeline", lambda pid: {"trigger": {}})
    monkeypatch.setattr(
        pl, "save_pipeline", MagicMock(side_effect=RuntimeError("disk"))
    )
    assert client.post("/api/pipelines/a/enable", json={}).status_code == 500


# ---------------------------------------------------------------------------
# Memory, brain export, vector, graph
# ---------------------------------------------------------------------------


def test_memory_list_and_add(client, monkeypatch):
    from alfa.core import database

    monkeypatch.setattr(
        database, "get_all_memories", AsyncMock(return_value=[{"key_topic": "k"}])
    )
    monkeypatch.setattr(
        database, "get_all_knowledge_graph_sync", lambda uid: [{"entity": "e"}]
    )
    out = client.get("/api/memory").json()
    assert out["total_memories"] == 1
    assert out["total_kg_relations"] == 1

    monkeypatch.setattr(
        database, "save_memory_fact_sync", lambda uid, key, content, cat: {"id": 1}
    )
    assert (
        client.post("/api/memory/add", json={"type": "fact"}).status_code == 400
    )
    out = client.post(
        "/api/memory/add",
        json={"type": "fact", "key_topic": "k", "content": "c"},
    ).json()
    assert out["status"] == "success"

    monkeypatch.setattr(
        database,
        "add_knowledge_relation_sync",
        lambda uid, e, r, t, cat, tags: {"id": 2},
    )
    assert (
        client.post("/api/memory/add", json={"type": "kg"}).status_code == 400
    )
    out = client.post(
        "/api/memory/add",
        json={
            "type": "kg",
            "entity": "a",
            "relation": "r",
            "target_value": "b",
        },
    ).json()
    assert out["status"] == "success"


def test_memory_delete(client, tmp_path, monkeypatch):
    from alfa.dashboard.routes.system import pipelines_memory

    repo = tmp_path / "repo2"
    repo.mkdir()
    monkeypatch.setattr(pipelines_memory, "REPO_ROOT", str(repo))
    db_path = repo / "agent_data.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE knowledge_memory (user_id INTEGER, key_topic TEXT)"
        )
        conn.execute("INSERT INTO knowledge_memory VALUES (42, 'k')")
        conn.commit()

    assert client.post("/api/memory/delete", json={}).status_code == 400
    out = client.post("/api/memory/delete", json={"key_topic": "k"}).json()
    assert out["status"] == "success"
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM knowledge_memory").fetchone()[0] == 0


def test_brain_export(client, monkeypatch):
    from alfa.core import database

    monkeypatch.setattr(
        database,
        "get_all_memories",
        AsyncMock(
            return_value=[{"category": "general", "key_topic": "k", "content": "c"}]
        ),
    )
    monkeypatch.setattr(
        database,
        "get_all_knowledge_graph_sync",
        lambda uid: [
            {"entity": "a", "relation": "r", "target_value": "b", "category": "c"}
        ],
    )
    out = client.get("/api/brain/export").json()
    assert out["status"] == "success"
    assert "k" in out["markdown"]
    assert out["json"]["memories"]


def test_vector_endpoints(client, monkeypatch):
    from alfa.memory import vector

    monkeypatch.setattr(
        vector,
        "semantic_search",
        lambda user_id, query, top_k, category: [{"score": 1}],
    )
    assert (
        client.post("/api/brain/vector/search", json={}).json()["status"] == "error"
    )
    out = client.post(
        "/api/brain/vector/search", json={"query": "x", "top_k": 99, "category": "c"}
    ).json()
    assert out["total_matches"] == 1

    monkeypatch.setattr(
        vector, "ingest_document", lambda **k: {"status": "success", "n": k["title"]}
    )
    assert (
        client.post("/api/brain/vector/ingest", json={}).status_code == 400
    )
    out = client.post(
        "/api/brain/vector/ingest", json={"title": "T", "content": "C"}
    ).json()
    assert out["n"] == "T"

    monkeypatch.setattr(vector, "list_ingested_documents", lambda user_id: [{"t": 1}])
    assert client.get("/api/brain/vector/list").json()["total_documents"] == 1

    monkeypatch.setattr(
        vector, "delete_document", lambda user_id, doc_title: {"status": "success"}
    )
    assert (
        client.post("/api/brain/vector/delete", json={}).status_code == 400
    )
    assert (
        client.post(
            "/api/brain/vector/delete", json={"doc_title": "T"}
        ).json()["status"]
        == "success"
    )


def test_graph_endpoints(client, monkeypatch):
    from alfa.memory import graph_rag

    monkeypatch.setattr(
        graph_rag,
        "graph_rag_get_overview",
        lambda user_id, doc_title, top_n: {"status": "success", "n": top_n},
    )
    assert client.get("/api/brain/graph/overview?top_n=3").json()["n"] == 3

    monkeypatch.setattr(
        graph_rag,
        "graph_rag_get_communities",
        lambda user_id, doc_title: {"status": "success", "doc": doc_title},
    )
    assert client.get("/api/brain/graph/communities?doc_title=x").json()["doc"] == "x"

    monkeypatch.setattr(
        graph_rag,
        "graph_rag_find_connection",
        lambda **k: {"status": "success", "depth": k["max_depth"]},
    )
    assert client.post("/api/brain/graph/path", json={}).status_code == 400
    out = client.post(
        "/api/brain/graph/path",
        json={"entity_a": "a", "entity_b": "b", "max_depth": 9},
    ).json()
    assert out["depth"] == 6

    monkeypatch.setattr(
        graph_rag,
        "consolidate_memory_sleep_cycle",
        lambda user_id, auto_alias, recluster: {
            "status": "success",
            "alias": auto_alias,
        },
    )
    out = client.post(
        "/api/brain/graph/consolidate", json={"auto_alias": False}
    ).json()
    assert out["alias"] is False

    monkeypatch.setattr(
        graph_rag, "export_knowledge_graph", lambda format_type, user_id: {"x": 1}
    )
    assert client.get("/api/brain/graph/export").json()["format"] == "jsonld"
    res = client.get("/api/brain/graph/export?format=graphml")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("application/xml")
    res = client.get("/api/brain/graph/export?format=cypher")
    assert res.headers["content-type"].startswith("text/plain")


def test_graph_elements(client, tmp_path, monkeypatch):
    from alfa.memory import graph_rag, vector

    def fake_export(format_type, user_id):
        return "<graphml/>"

    monkeypatch.setattr(graph_rag, "export_knowledge_graph", fake_export)
    res = client.get("/api/brain/graph/export?format=graphml")
    assert "<graphml/>" in res.text

    db_path = tmp_path / "graph.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE graph_relations (user_id INTEGER, source_entity TEXT, relation TEXT, target_entity TEXT, source_doc TEXT, evidence TEXT)"
        )
        conn.execute(
            "INSERT INTO graph_relations VALUES (42, 'a', 'r', 'b', 'doc', 'e')"
        )
        conn.commit()
    monkeypatch.setattr(vector, "_resolve_db_path", lambda x: str(db_path))
    monkeypatch.setattr(graph_rag, "init_graph_db", lambda path: None)
    out = client.get("/api/brain/graph/elements").json()
    assert out["total_nodes"] == 2
    assert out["total_edges"] == 1
    out = client.get("/api/brain/graph/elements?doc_title=doc").json()
    assert out["edges"][0]["doc"] == "doc"


# ---------------------------------------------------------------------------
# Tools explorer
# ---------------------------------------------------------------------------


def test_categorize_tool_and_extra_group():
    from alfa.dashboard.routes import tools as tr
    from alfa.tools.extras import EXTRA_GROUPS

    cases = {
        "affiliate_scrape": "Affiliate",
        "pdf_merge": "PDF",
        "browser_open": "Browser",
        "desktop_click": "OS & Vision",
        "libreoffice_convert": "LibreOffice",
        "excel_write": "Media & Documents",
        "security_scan": "Security",
        "memory_search": "Memory",
        "guardian_heal": "System",
        "subagent_spawn": "AI & Intelligence",
        "wa_send": "Ecosystem",
        "misc_tool": "Core Utilities",
    }
    for name, expected in cases.items():
        assert expected in tr.categorize_tool(name)

    if EXTRA_GROUPS:
        group, names = next(iter(EXTRA_GROUPS.items()))
        assert tr.extra_group_of(next(iter(names))) == group
    assert tr.extra_group_of("tidak-ada-tool") is None


def test_tools_list(client, monkeypatch):
    from alfa.dashboard.routes import tools as tr

    def contoh_tool(a: int, b: str = "x") -> dict:
        """Deskripsi singkat.

        Detail panjang.
        """
        return {"a": a, "b": b}

    monkeypatch.setattr(tr.tools, "AVAILABLE_TOOLS", [contoh_tool])
    monkeypatch.setattr(tr, "is_extra_tool", lambda name: name == "contoh_tool")
    fake = types.ModuleType("plugins")
    fake.load_all_plugin_tools = lambda: None

    def plugin_fn(x: int = 1):
        """Plugin doc."""
        return x

    fake._RUNTIME_PLUGIN_REGISTRY = {"plugin_fn": plugin_fn}
    monkeypatch.setitem(sys.modules, "plugins", fake)
    out = client.get("/api/tools").json()
    names = {t["name"] for t in out["tools"]}
    assert {"contoh_tool", "plugin_fn"} <= names
    entry = next(t for t in out["tools"] if t["name"] == "contoh_tool")
    assert entry["parameters"][0]["required"] is True
    assert entry["parameters"][1]["required"] is False
    assert entry["is_extra"] is True


def test_tools_list_plugin_errors(client, monkeypatch):
    from alfa.dashboard.routes import tools as tr

    monkeypatch.setattr(tr.tools, "AVAILABLE_TOOLS", [])
    monkeypatch.setitem(sys.modules, "plugins", None)
    out = client.get("/api/tools").json()
    assert out["total_tools"] == 0


def test_tools_execute(client, monkeypatch):
    from alfa.core.perm import gate
    from alfa.dashboard.routes import tools as tr

    def echo(value: str):
        return {"echo": value}

    monkeypatch.setattr(tr.tools, "echo", echo, raising=False)
    monkeypatch.setattr(gate, "check_headless_approval", lambda *a: None)
    assert client.post("/api/tools/execute", json={}).status_code == 400
    assert (
        client.post("/api/tools/execute", json={"tool_name": "nope"}).status_code
        == 404
    )
    out = client.post(
        "/api/tools/execute", json={"tool_name": "echo", "args": {"value": "hi"}}
    ).json()
    assert out["result"] == {"echo": "hi"}

    monkeypatch.setattr(gate, "check_headless_approval", lambda *a: "ditolak")
    assert (
        client.post(
            "/api/tools/execute", json={"tool_name": "echo", "args": {}}
        ).status_code
        == 403
    )

    monkeypatch.setattr(gate, "check_headless_approval", lambda *a: None)
    out = client.post(
        "/api/tools/execute", json={"tool_name": "echo", "args": {"salah": 1}}
    ).json()
    assert out["status"] == "error"


def test_tools_upload(client, tmp_path, monkeypatch):
    from alfa.dashboard.routes import tools as tr

    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    monkeypatch.setattr(tr.tools, "get_pdf_output_dir", lambda name: str(upload_dir))
    out = client.post(
        "/api/tools/upload",
        files=[
            ("files", ("a.txt", b"satu", "text/plain")),
            ("files", ("a.txt", b"dua", "text/plain")),
        ],
    ).json()
    assert out["status"] == "success"
    assert len(out["files"]) == 2
    assert out["files"][0]["filename"] == "a.txt"
    assert out["files"][1]["filename"] != "a.txt"
    assert out["primary_file_path"].endswith("a.txt")


# ---------------------------------------------------------------------------
# Dynamic plugins & superpowers
# ---------------------------------------------------------------------------


def test_plugins_endpoints(client, monkeypatch):
    fake = types.ModuleType("plugins")
    fake.list_all_plugins = lambda: [{"name": "p"}]
    fake.create_and_register_plugin = lambda name, desc, code, test_kwargs=None: {
        "status": "success",
        "name": name,
    }
    fake.delete_plugin = lambda name: {"status": "deleted", "name": name}
    fake.execute_plugin_direct = lambda name, **kwargs: {"name": name, **kwargs}
    monkeypatch.setitem(sys.modules, "plugins", fake)

    assert client.get("/api/plugins/list").json()["total_plugins"] == 1
    assert (
        client.post("/api/plugins/create", json={"tool_name": "x"}).status_code
        == 400
    )
    out = client.post(
        "/api/plugins/create",
        json={"tool_name": "x", "tool_code": "print(1)"},
    ).json()
    assert out["name"] == "x"
    assert client.post("/api/plugins/delete", json={}).status_code == 400
    assert (
        client.post("/api/plugins/delete", json={"tool_name": "x"}).json()["status"]
        == "deleted"
    )
    assert client.post("/api/plugins/execute", json={}).status_code == 400
    out = client.post(
        "/api/plugins/execute", json={"tool_name": "x", "kwargs": {"a": 1}}
    ).json()
    assert out["result"] == {"name": "x", "a": 1}

    fake.execute_plugin_direct = MagicMock(side_effect=RuntimeError("plugin"))
    out = client.post("/api/plugins/execute", json={"tool_name": "x"}).json()
    assert out["status"] == "error"


def test_superpowers_list_and_detail(client, tmp_path, monkeypatch):
    from alfa.dashboard.routes import tools as tr

    repo = Path(tr.REPO_ROOT)
    skills = repo / "skills" / "superpowers"
    skill_a = skills / "brainstorming"
    skill_a.mkdir(parents=True)
    (skill_a / "SKILL.md").write_text(
        "---\ndescription: Skill deskripsi\n---\n", encoding="utf-8"
    )
    (skill_a / "ref.md").write_text("ref", encoding="utf-8")
    skill_b = skills / "custom-skill"
    skill_b.mkdir()
    (skill_b / ".hidden").mkdir()

    out = client.get("/api/skills/superpowers").json()
    ids = {s["id"] for s in out["skills"]}
    assert {"brainstorming", "custom-skill"} <= ids
    entry = next(s for s in out["skills"] if s["id"] == "brainstorming")
    assert entry["description"] == "Skill deskripsi"
    assert entry["file_count"] >= 2

    out = client.get("/api/skills/superpowers/brainstorming").json()
    assert out["status"] == "success"
    assert "ref.md" in out["reference_files"]
    assert client.get("/api/skills/superpowers/nope").status_code == 404


def test_superpowers_fallback_dirs(client, tmp_path, monkeypatch):
    from alfa.dashboard.routes import tools as tr

    missing_repo = tmp_path / "norepo"
    missing_repo.mkdir()
    monkeypatch.setattr(tr, "REPO_ROOT", str(missing_repo))
    monkeypatch.setenv("HOME", str(tmp_path / "nohome"))
    out = client.get("/api/skills/superpowers").json()
    assert out["total_skills"] == 0


def test_ui_ux_endpoints(client, monkeypatch):
    plugin = types.ModuleType("plugins.ui_ux_pro_max")
    seen = {}

    def search(query="", domain="auto", action="search", project_name=""):
        seen.update(
            query=query, domain=domain, action=action, project_name=project_name
        )
        return {"status": "success", "action": action}

    plugin.ui_ux_pro_max_search = search
    pkg = types.ModuleType("plugins")
    pkg.__path__ = []
    pkg.ui_ux_pro_max = plugin
    monkeypatch.setitem(sys.modules, "plugins", pkg)
    monkeypatch.setitem(sys.modules, "plugins.ui_ux_pro_max", plugin)

    assert client.get("/api/skills/ui-ux-pro-max/search").json()["status"] == "error"
    out = client.get("/api/skills/ui-ux-pro-max/search?q=saas&domain=style").json()
    assert out["action"] == "search"
    assert seen["domain"] == "style"

    assert (
        client.post("/api/skills/ui-ux-pro-max/design-system", json={}).status_code
        == 400
    )
    out = client.post(
        "/api/skills/ui-ux-pro-max/design-system",
        json={"query": "saas", "project_name": "ALFA"},
    ).json()
    assert out["action"] == "generate_design_system"
    assert seen["project_name"] == "ALFA"

    out = client.get("/api/skills/ui-ux-pro-max/catalog").json()
    assert out["total_styles"] == 67
    assert out["popular_styles"]
