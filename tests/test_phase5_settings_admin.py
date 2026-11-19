"""Phase 5 coverage: settings admin — redaksi rahasia, model per-key, update env.

Hermetic: DB SQLite sementara, HTTP/LLM di-mock, HOME diarahkan ke tmp.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    db_file = tmp_path / "settings_admin.db"
    monkeypatch.setenv("ALFA_DB_PATH", str(db_file))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from alfa.core.db import connection

    connection.init_db_sync()
    return db_file


@pytest.fixture
def sa(isolated_db, monkeypatch):
    import alfa.dashboard.routes.system.settings_admin as module

    module._models_cache.clear()
    monkeypatch.setattr(module, "require_admin", lambda request: {"is_admin": True})
    return module


def _insert_key(db_file: Path, provider: str = "gemini", base_url: str = "") -> int:
    from alfa.core import database

    with database.get_sync_db() as conn:
        cur = conn.execute(
            """
            INSERT INTO api_keys
                (name, provider, api_key, base_url, default_model, is_active)
            VALUES (?, ?, ?, ?, ?, 0)
            """,
            ("uji", provider, "cipher", base_url, "model-uji"),
        )
        conn.commit()
        return int(cur.lastrowid)


class _FakeResponse:
    def __init__(self, payload, status_code=200, text=""):
        self._payload = payload
        self.status_code = status_code
        self.text = text

    def json(self):
        return self._payload


class _FakeAsyncClient:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, url, **kwargs):
        return _FakeResponse(
            {
                "models": [
                    {"name": "models/gemini-x", "supportedGenerationMethods": ["generateContent"]},
                    {"name": "models/gemini-embed", "supportedGenerationMethods": ["embedContent"]},
                ]
            }
        )

    async def post(self, url, **kwargs):
        return _FakeResponse(
            {"choices": [{"message": {"content": "SIAP"}}]}, status_code=200
        )


# ── env helpers ──────────────────────────────────────────────────────────────


def test_env_sources_priority_and_missing(tmp_path, monkeypatch, sa):
    repo = tmp_path / "repo"
    repo.mkdir()
    repo_env = repo / ".env"
    repo_env.write_text("A=1\n", encoding="utf-8")
    secrets = tmp_path / "secrets.env"
    secrets.write_text("B=2\n", encoding="utf-8")

    from alfa.core import config

    monkeypatch.setattr(config, "SECRETS_PATH", secrets)
    monkeypatch.setattr(sa, "REPO_ROOT", str(repo))
    sources = sa._env_sources()
    assert sources == [str(secrets), str(repo_env)]

    monkeypatch.setattr(config, "SECRETS_PATH", tmp_path / "missing.env")
    repo_env.unlink()
    assert sa._env_sources() == []


def test_read_env_values_merges_first_wins_and_skips_oserror(tmp_path, monkeypatch, sa):
    first = tmp_path / "first.env"
    second = tmp_path / "second.env"
    first.write_text("A=first\nB=also\n", encoding="utf-8")
    second.write_text("A=second\nC=third\n", encoding="utf-8")

    calls = {"n": 0}

    def fake_dotenv(path):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("unreadable")
        return {"A": "second", "C": "third"}

    monkeypatch.setattr(sa, "dotenv_values", fake_dotenv)
    monkeypatch.setattr(sa, "_env_sources", lambda: [str(first), str(second)])
    assert sa._read_env_values() == {"A": "second", "C": "third"}


def test_read_env_values_first_source_wins(tmp_path, monkeypatch, sa):
    first = tmp_path / "first.env"
    second = tmp_path / "second.env"
    first.write_text("A=first\n", encoding="utf-8")
    second.write_text("A=second\nB=two\n", encoding="utf-8")
    monkeypatch.setattr(sa, "_env_sources", lambda: [str(first), str(second)])
    assert sa._read_env_values() == {"A": "first", "B": "two"}


# ── GET /api/settings ────────────────────────────────────────────────────────


def test_get_settings_handles_brain_failure(monkeypatch, sa):
    import alfa.core.brain as brain

    monkeypatch.setattr(sa, "_read_env_values", lambda: {"TELEGRAM_BOT_TOKEN": ""})
    monkeypatch.setattr(sa.database, "list_api_keys_sync", lambda: [])

    def boom():
        msg = "brain rusak"
        raise KeyError(msg)

    monkeypatch.setattr(brain, "get_main_brain", boom)
    out = asyncio.run(sa.get_system_settings(None))
    assert out["main_brain"]["provider"] == "?"
    assert out["main_brain"]["key_id"] is None


# ── /api/models-for-key ──────────────────────────────────────────────────────


def test_models_for_key_uses_cache(sa, monkeypatch):
    key_id = _insert_key(sa.database.DB_PATH)
    sa._models_cache[key_id] = (time.time(), "gemini", ["cached-model"])
    monkeypatch.setattr(sa.database, "decrypt_key", lambda value: "rahasia")
    out = asyncio.run(sa.models_for_key(MagicMock(), key_id))
    assert out["models"] == ["cached-model"]
    assert out["provider"] == "gemini"


def test_models_for_key_missing_key_raises_404(sa):
    with pytest.raises(HTTPException) as exc:
        asyncio.run(sa.models_for_key(MagicMock(), 9999))
    assert exc.value.status_code == 404


def test_models_for_key_gemini_filters_and_falls_back(monkeypatch, sa):
    import httpx

    key_id = _insert_key(sa.database.DB_PATH, provider="gemini")
    monkeypatch.setattr(sa.database, "decrypt_key", lambda value: "rahasia")
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    out = asyncio.run(sa.models_for_key(MagicMock(), key_id))
    assert "gemini-x" in out["models"]
    assert "gemini-embed" not in out["models"]


def test_models_for_key_gemini_empty_response_uses_fallback(monkeypatch, sa):
    import httpx

    class EmptyClient(_FakeAsyncClient):
        async def get(self, url, **kwargs):
            return _FakeResponse({"models": []})

    key_id = _insert_key(sa.database.DB_PATH, provider="gemini")
    monkeypatch.setattr(sa.database, "decrypt_key", lambda value: "rahasia")
    monkeypatch.setattr(httpx, "AsyncClient", EmptyClient)
    out = asyncio.run(sa.models_for_key(MagicMock(), key_id))
    assert "gemini-3.6-flash" in out["models"]


def test_models_for_key_openai_compatible(monkeypatch, sa):
    import httpx

    class ModelsClient(_FakeAsyncClient):
        async def get(self, url, **kwargs):
            return _FakeResponse({"data": [{"id": "z-model"}, {"id": "a-model"}]})

    key_id = _insert_key(
        sa.database.DB_PATH, provider="openrouter", base_url="https://example.test/v1"
    )
    sa._models_cache.clear()
    monkeypatch.setattr(sa.database, "decrypt_key", lambda value: "rahasia")
    monkeypatch.setattr(httpx, "AsyncClient", ModelsClient)
    out = asyncio.run(sa.models_for_key(MagicMock(), key_id))
    assert out["models"] == ["a-model", "z-model"]


# ── Antigravity / main brain ─────────────────────────────────────────────────


def test_antigravity_apply_creates_key_and_updates_agents(monkeypatch, sa):
    recorded = {}
    monkeypatch.setattr(sa.database, "list_api_keys_sync", lambda: [])
    monkeypatch.setattr(
        sa.database,
        "add_api_key_sync",
        lambda **kwargs: {"id": 7, "status": "success"},
    )
    monkeypatch.setattr(
        sa.database,
        "list_custom_agents_sync",
        lambda: [
            {"id": 1, "name": "Alpha", "is_enabled": 1},
            {"id": 2, "name": "Nonaktif", "is_enabled": 0},
        ],
    )
    monkeypatch.setattr(
        sa.database,
        "update_custom_agent_sync",
        lambda agent_id, payload: recorded.setdefault(agent_id, payload),
    )

    async def fake_set(key_id, model):
        return {"main_brain": {"provider": "custom", "model": model, "key_id": key_id, "label": "x"}}

    monkeypatch.setattr(sa, "antigravity_set_main_brain_impl", fake_set)
    out = asyncio.run(
        sa.antigravity_apply_model(
            {"model": "m-1", "apply_all_agents": True, "as_main_brain": True},
            MagicMock(),
        )
    )
    assert out["key_id"] == 7
    assert out["agents_updated"] == ["Alpha"]
    assert out["main_brain"]["model"] == "m-1"
    assert "Otak utama dialihkan" in out["message"]
    assert 1 in recorded and 2 not in recorded


def test_antigravity_apply_existing_key_backup_mode(monkeypatch, sa):
    updated = {}
    monkeypatch.setattr(
        sa.database,
        "list_api_keys_sync",
        lambda: [{"id": 3, "base_url": "http://127.0.0.1:8890/v1"}],
    )
    monkeypatch.setattr(
        sa.database,
        "update_api_key_model",
        lambda key_id, model: updated.update(key_id=key_id, model=model),
    )
    monkeypatch.setattr(sa.database, "list_custom_agents_sync", lambda: [])
    out = asyncio.run(
        sa.antigravity_apply_model(
            {"model": "", "apply_all_agents": False, "as_main_brain": False},
            MagicMock(),
        )
    )
    assert out["key_id"] == 3
    assert updated == {"key_id": 3, "model": "gemini-3.6-flash"}
    assert out["main_brain"] is None
    assert "Mode cadangan" in out["message"]


def test_antigravity_set_main_brain_impl_persists(monkeypatch, sa):
    import alfa.core.brain as brain

    monkeypatch.setattr(
        brain,
        "get_main_brain",
        lambda: {"provider": "custom", "model": "m", "key_id": 5, "label": "Custom"},
    )
    out = asyncio.run(sa.antigravity_set_main_brain_impl(5, "m"))
    assert out["main_brain"]["key_id"] == 5

    from alfa.core import database

    with database.get_sync_db() as conn:
        rows = dict(conn.execute("SELECT key, value FROM system_settings").fetchall())
    assert rows["main_brain_key_id"] == "5"
    assert rows["main_brain_model"] == "m"


def test_test_main_brain_combo_validates_key_id(sa):
    with pytest.raises(HTTPException) as exc:
        asyncio.run(sa.test_main_brain_combo({"key_id": "bukan-angka"}, MagicMock()))
    assert exc.value.status_code == 400


def test_test_main_brain_combo_missing_key(sa):
    out = asyncio.run(sa.test_main_brain_combo({"key_id": 12345}, MagicMock()))
    assert out["status"] == "error"
    assert "tidak ditemukan" in out["message"]


def test_test_main_brain_combo_custom_provider(monkeypatch, sa):
    import httpx

    key_id = _insert_key(
        sa.database.DB_PATH, provider="openrouter", base_url="https://example.test/v1"
    )
    monkeypatch.setattr(sa.database, "decrypt_key", lambda value: "rahasia")
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    out = asyncio.run(
        sa.test_main_brain_combo({"key_id": key_id, "model": "m"}, MagicMock())
    )
    assert out["status"] == "success"
    assert out["snippet"] == "SIAP"


def test_set_main_brain_validates_payload(sa):
    for payload in ({}, {"key_id": "x"}):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(sa.set_main_brain_endpoint(payload, MagicMock()))
        assert exc.value.status_code == 400


def test_set_main_brain_syncs_alpha_lead(monkeypatch, sa):
    import alfa.core.brain as brain

    key_id = _insert_key(sa.database.DB_PATH, provider="gemini")
    monkeypatch.setattr(
        sa.database,
        "activate_api_key_sync",
        lambda kid: {"status": "success", "message": "aktif"},
    )
    monkeypatch.setattr(sa.database, "set_main_brain_model", lambda model: None)
    monkeypatch.setattr(
        sa.database,
        "list_custom_agents_sync",
        lambda: [{"id": 1, "name": "Alpha Lead"}],
    )
    synced = {}
    monkeypatch.setattr(
        sa.database,
        "update_custom_agent_sync",
        lambda aid, payload: synced.update(aid=aid, payload=payload),
    )
    monkeypatch.setattr(
        brain,
        "get_main_brain",
        lambda: {"provider": "gemini", "model": "m", "key_id": key_id, "label": "G"},
    )
    out = asyncio.run(sa.set_main_brain_endpoint({"key_id": key_id}, MagicMock()))
    assert out["synced_agents"] == ["Alpha Lead"]
    assert synced["payload"]["api_key_id"] == key_id
    assert "Model: m" in out["message"]


# ── POST /api/settings ───────────────────────────────────────────────────────


def test_update_system_settings_writes_env_prompt_and_db(tmp_path, monkeypatch, sa):
    env_path = tmp_path / "runtime.env"
    env_path.write_text(
        "TELEGRAM_BOT_TOKEN=lama\n"
        "GEMINI_API_KEY=lama-key\n"
        "GEMINI_MODEL=lama-model\n"
        "ALLOWED_USER_IDS=1\n"
        "SYSTEM_INSTRUCTION=\"lama\"\n",
        encoding="utf-8",
    )
    home = tmp_path / "home"
    (home / ".alfa").mkdir(parents=True)
    (home / ".alfa" / "system_prompt.txt").write_text("prompt lama", encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(sa, "active_env_path", lambda: env_path)

    out = asyncio.run(
        sa.update_system_settings(
            {
                "telegram_bot_token": "token-baru",
                "gemini_api_key": "***masked***",
                "gemini_model": "model-baru",
                "allowed_user_ids": "2,3",
                "system_instruction": "baris1\nbaris2",
                "db_settings": {"foo": "bar"},
            },
            MagicMock(),
        )
    )
    assert out["status"] == "success"
    text = env_path.read_text(encoding="utf-8")
    assert "TELEGRAM_BOT_TOKEN=token-baru" in text
    assert "GEMINI_API_KEY=lama-key" in text  # masked tidak menimpa
    assert "GEMINI_MODEL=model-baru" in text
    assert "ALLOWED_USER_IDS=2,3" in text
    assert 'SYSTEM_INSTRUCTION="baris1\\nbaris2"' in text
    assert (home / ".alfa" / "system_prompt.txt").read_text(encoding="utf-8") == "baris1\nbaris2\n"
    assert (home / ".alfa" / "system_prompt.txt.bak").read_text(encoding="utf-8") == "prompt lama"

    from alfa.core import database

    with database.get_sync_db() as conn:
        row = conn.execute(
            "SELECT value FROM system_settings WHERE key='foo'"
        ).fetchone()
    assert row["value"] == "bar"


def test_update_system_settings_appends_missing_keys(tmp_path, monkeypatch, sa):
    env_path = tmp_path / "empty.env"
    env_path.write_text("LOG_LEVEL=INFO\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(sa, "active_env_path", lambda: env_path)
    asyncio.run(
        sa.update_system_settings(
            {
                "telegram_bot_token": "tok",
                "gemini_api_key": "key",
                "gemini_model": "m",
                "allowed_user_ids": "9",
                "system_instruction": "instruksi",
            },
            MagicMock(),
        )
    )
    text = env_path.read_text(encoding="utf-8")
    assert "LOG_LEVEL=INFO" in text
    assert text.index("TELEGRAM_BOT_TOKEN=tok") > text.index("LOG_LEVEL=INFO")
    assert "GEMINI_API_KEY=key" in text
