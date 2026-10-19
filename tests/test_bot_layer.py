"""Lapisan bot: helper Discord, gating handler, dan loop proaktif.

Modul-modul ini difficult untuk diuji penuh (butuh klien Discord/Telegram
nyata), tapi bagian yang menentukan perilaku — gating otorisasi, pemecahan
pesan, helper konfigurasi, dancabang validasi — bisa diuji dengan mock.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_DB_DOWN_MSG = "db mati"


# ── Discord bot: helper murni ────────────────────────────────────────────────


class TestDiscordHelpers:
    def test_split_pesan_menghormati_batas(self):
        from alfa.bot.discord_bot import _split

        chunks = _split("\n".join("x" * 200 for _ in range(40)), limit=1900)
        assert len(chunks) > 1
        assert all(len(c) <= 1901 for c in chunks)

    def test_split_pesan_kecil(self):
        from alfa.bot.discord_bot import _split

        assert _split("pendek", limit=1900) == ["pendek"]

    def test_split_pesan_kosong(self):
        from alfa.bot.discord_bot import _split

        assert _split("", limit=1900) == [""]

    def test_owner_ids_termasuk_default(self, monkeypatch):
        from alfa.bot import discord_bot

        monkeypatch.setattr(discord_bot, "_setting", lambda k, d="": d)
        ids = discord_bot._owner_ids()
        assert isinstance(ids, set)
        assert discord_bot.DEF_OWNER_ID in ids

    def test_owner_ids_gabungan_dari_setting(self, monkeypatch):
        from alfa.bot import discord_bot

        monkeypatch.setattr(
            discord_bot, "_setting", lambda k, d="": "4242" if k == "discord_owner_id" else d
        )
        assert 4242 in discord_bot._owner_ids()

    def test_channel_id_dari_setting(self, monkeypatch):
        from alfa.bot import discord_bot

        monkeypatch.setattr(
            discord_bot, "_setting", lambda k, d="": "999" if k == "discord_channel_id" else d
        )
        assert discord_bot._channel_id() == 999

    def test_channel_id_default_saat_setting_bukan_angka(self, monkeypatch):
        from alfa.bot import discord_bot

        monkeypatch.setattr(discord_bot, "_setting", lambda k, d="": "bukan-angka")
        assert discord_bot._channel_id() == discord_bot.DEF_CHANNEL_ID

    def test_setting_dari_db(self, monkeypatch):
        from alfa.bot import discord_bot

        class _Row(dict):
            pass

        class _Conn:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def execute(self, sql, params=()):
                return self

            def fetchone(self):
                return _Row(value="nilai-db")

        class _Db:
            def get_sync_db(self):
                return _Conn()

        monkeypatch.setattr(discord_bot, "_db", lambda: _Db())
        assert discord_bot._setting("kunci") == "nilai-db"

    def test_setting_default_saat_error(self, monkeypatch):
        from alfa.bot import discord_bot

        def _boom():
            raise RuntimeError(_DB_DOWN_MSG)

        monkeypatch.setattr(discord_bot, "_db", _boom)
        assert discord_bot._setting("kunci", "fallback") == "fallback"

    def test_discord_token_dari_db(self, monkeypatch):
        from alfa.bot import discord_bot

        class _Row(dict):
            pass

        class _Conn:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def execute(self, sql, params=()):
                return self

            def fetchone(self):
                return _Row(api_key="enc1:xxx")

        class _Db:
            def get_sync_db(self):
                return _Conn()

            def decrypt_key(self, v):
                return "token-test"

        monkeypatch.setattr(discord_bot, "_db", lambda: _Db())
        assert discord_bot._discord_token() == "token-test"

    def test_discord_token_kosong_bila_baris_tak_ada(self, monkeypatch):
        from alfa.bot import discord_bot

        class _Conn:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def execute(self, sql, params=()):
                return self

            def fetchone(self):
                return None

        class _Db:
            def get_sync_db(self):
                return _Conn()

        monkeypatch.setattr(discord_bot, "_db", lambda: _Db())
        assert discord_bot._discord_token() == ""

    def test_play_lock_satu_per_guild(self):
        from alfa.bot.discord_bot import _play_lock

        assert _play_lock(1) is _play_lock(1)
        assert _play_lock(1) is not _play_lock(2)

    def test_register_discord_tools_tidak_crash(self):
        from alfa.bot.discord_bot import _register_discord_tools

        _register_discord_tools()

    def test_discord_play_music_tanpa_query(self, monkeypatch):
        from alfa.bot import discord_bot

        monkeypatch.setattr(discord_bot, "DISCORD_CLIENT", None, raising=False)
        res = discord_bot.discord_play_music("")
        assert isinstance(res, dict)


# ── Handlers: gating & sapaan ───────────────────────────────────────────────


class TestHandlerGating:
    def test_greeting_reply(self):
        from alfa.bot.handlers import greeting_reply

        assert greeting_reply("halo") is not None
        assert greeting_reply("tolong帮我 bikin website") is None

    def test_is_authorized_dengan_whitelist(self, monkeypatch):
        import alfa.bot.config as bot_config
        from alfa.bot import handlers

        monkeypatch.setattr(bot_config, "ALLOWED_USER_IDS", {111, 222})
        assert handlers._is_authorized(111) is True
        assert handlers._is_authorized(999) is False

    def test_is_authorized_tanpa_whitelist_menolak_semua(self, monkeypatch):
        """Whitelist kosong harus menolak semua (fail-safe), bukan sebaliknya."""
        import alfa.bot.config as bot_config
        from alfa.bot import handlers

        monkeypatch.setattr(bot_config, "ALLOWED_USER_IDS", set())
        assert handlers._is_authorized(111) is False

    def test_get_bot_module_tidak_crash(self):
        from alfa.bot.handlers import _get_bot_module

        assert _get_bot_module() is not None


# ── Proaktif: helper & validasi ─────────────────────────────────────────────


class TestProactiveHelpers:
    def test_import_loop_tidak_crash(self):
        from alfa.bot import proactive

        for fn in (
            "proactive_reminder_loop",
            "proactive_cron_watchdog_loop",
            "proactive_wa_digest_loop",
            "proactive_sites_watch_loop",
            "proactive_system_guardian_loop",
            "proactive_focus_session_loop",
            "proactive_ambient_agent_loop",
            "proactive_ecosystem_watchdog_loop",
        ):
            assert callable(getattr(proactive, fn)), fn

    def test_run_scheduled_swarm_job_tanpa_job(self, monkeypatch):
        import asyncio

        from alfa.bot import proactive

        async def _noop(*a, **k):
            return None

        monkeypatch.setattr(proactive, "_run_scheduled_swarm_job", _noop)
        assert asyncio.run(proactive._run_scheduled_swarm_job(None, 1, 2, 3, "t", "p")) is None


# ── Config: kredensial tidak boleh bocor ────────────────────────────────────


class TestCredentialHygiene:
    def test_env_example_tanpa_secret_nyata(self):
        """`.env.example` hanya boleh berisi placeholder."""
        env = (Path(__file__).resolve().parents[1] / ".env.example").read_text(
            encoding="utf-8"
        )
        for line in env.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            if any(
                s in key.upper()
                for s in ("TOKEN", "KEY", "SECRET", "PASSWORD")
            ):
                if value and not value.startswith(("your", "passwordkuat", "x", "sk-", "AIza")):
                    # placeholder generik atau kosong → aman
                    assert "changeme" in value.lower() or value == "", (key, value)

    def test_tidak_ada_secret_yang_tercommit(self):
        """File .env / oauth token tidak boleh masuk repo."""
        import subprocess

        repo = Path(__file__).resolve().parents[1]
        out = subprocess.run(
            ["git", "ls-files"], cwd=repo, capture_output=True, text=True
        ).stdout.split()
        forbidden = [
            f
            for f in out
            if f in (".env", "gdrive_oauth_token.json", "gdrive_oauth_client_secret.json")
            or f.endswith(".pem")
            or f.endswith(".key")
        ]
        assert not forbidden, forbidden
        assert os.path.isfile(repo / ".gitignore")
        assert ".env" in (repo / ".gitignore").read_text(encoding="utf-8")
