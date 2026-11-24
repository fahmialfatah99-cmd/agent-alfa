"""Phase 6 coverage: Discord bridge — helper, slash command, on_message, loop mirror.

Hermetic: modul `discord`, `yt_dlp`, whisper, TTS, dan semua tool eksternal di-fake.
Tidak ada koneksi Discord/YouTube atau proses nyata.
"""

from __future__ import annotations

import asyncio
import io
import json
import sys
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from alfa.bot import discord_bot as db


class _StopLoopError(Exception):
    pass


# ---------------------------------------------------------------------------
# Helper murni
# ---------------------------------------------------------------------------


def test_split_edges():
    assert db._split("") == [""]
    assert db._split("pendek") == ["pendek"]
    assert len(db._split("x" * 4000)) == 3
    parts = db._split("\n".join(["baris"] * 1000))
    assert all(len(p) <= 1900 for p in parts)
    assert all(p.strip() for p in parts)


def test_setting_and_token(monkeypatch):
    monkeypatch.setattr(db, "_db", lambda: (_ for _ in ()).throw(RuntimeError("db")))
    assert db._setting("x", "default") == "default"

    class Row(dict):
        pass

    class Conn:
        def execute(self, *a):
            return self

        def fetchone(self):
            return Row(value="dari-db")

    class DB:
        def get_sync_db(self):
            return _CM(Conn())

    monkeypatch.setattr(db, "_db", lambda: DB())
    assert db._setting("x") == "dari-db"


class _CM:
    def __init__(self, value):
        self.value = value

    def __enter__(self):
        return self.value

    def __exit__(self, *a):
        return False


def test_owner_and_channel(monkeypatch):
    monkeypatch.setattr(db, "_setting", lambda k, d="": "111 222")
    assert {111, 222}.issubset(db._owner_ids())
    assert db._channel_id() == db.DEF_CHANNEL_ID
    monkeypatch.setattr(db, "_setting", lambda k, d="": "not-a-number")
    assert db._channel_id() == db.DEF_CHANNEL_ID


def test_discord_token_paths(monkeypatch):
    class Row(dict):
        pass

    class Conn:
        def execute(self, *a):
            return self

        def fetchone(self):
            return Row(api_key="cipher")

    class DB:
        def get_sync_db(self):
            return _CM(Conn())

        def decrypt_key(self, raw):
            return "plain"

    monkeypatch.setattr(db, "_db", lambda: DB())
    assert db._discord_token() == "plain"

    class Conn2(Conn):
        def fetchone(self):
            return None

    class DB2(DB):
        def get_sync_db(self):
            return _CM(Conn2())

    monkeypatch.setattr(db, "_db", lambda: DB2())
    assert db._discord_token() == ""

    monkeypatch.setattr(db, "_db", lambda: (_ for _ in ()).throw(RuntimeError("db")))
    assert db._discord_token() == ""


def test_context_helpers(monkeypatch):
    db._DISCORD_CMD_CTX.clear()
    db._DISCORD_CTX_LAST.clear()
    db._set_discord_cmd_ctx(1, 10, 20)
    assert db._get_discord_cmd_ctx(1)["guild_id"] == 10
    assert db._get_discord_cmd_ctx(99)["voice_channel_id"] == 20
    from alfa.core import runtime_ctx

    monkeypatch.setattr(runtime_ctx, "get_current_user_id", lambda: 1)
    assert db._get_discord_cmd_ctx()["guild_id"] == 10


def test_run_single_success_and_error(monkeypatch):
    from alfa.bot import turn_executor
    from alfa.tools.media import player

    calls = []
    monkeypatch.setattr(player, "set_host_play_blocked", lambda v: calls.append(v))
    monkeypatch.setattr(
        turn_executor, "run_agent_turn", AsyncMock(return_value="jawaban")
    )
    assert asyncio.run(db._run_single("halo", 1)) == "jawaban"
    assert calls == [True, False]

    monkeypatch.setattr(
        turn_executor, "run_agent_turn", AsyncMock(side_effect=RuntimeError("boom"))
    )
    out = asyncio.run(db._run_single("halo", 1))
    assert "Gagal memproses" in out


def test_run_swarm_success_and_error(monkeypatch):
    from alfa.bot import mode_commands

    monkeypatch.setattr(
        mode_commands, "run_swarm_task", AsyncMock(return_value={"ok": True})
    )
    monkeypatch.setattr(
        mode_commands, "format_swarm_result", lambda result: ("steps", "final")
    )
    assert asyncio.run(db._run_swarm("tugas")) == ("steps", "final")

    monkeypatch.setattr(
        mode_commands, "run_swarm_task", AsyncMock(side_effect=RuntimeError("boom"))
    )
    steps, final = asyncio.run(db._run_swarm("tugas"))
    assert "Misi gagal" in steps
    assert final == ""


def test_play_lock_reused():
    db._PLAY_LOCKS.clear()
    first = db._play_lock(1)
    assert db._play_lock(1) is first
    assert db._play_lock(2) is not first


# ---------------------------------------------------------------------------
# discord_play_music
# ---------------------------------------------------------------------------


class _FakeFuture:
    def __init__(self, value):
        self.value = value

    def result(self, timeout=None):
        return self.value


class _SyncLoop:
    def run_coroutine_threadsafe(self, coro, loop):
        return _FakeFuture(asyncio.run(coro))


class _FakeVoiceChannel:
    def __init__(self):
        self.connected = False
        self.playing = False
        self.paused = False
        self.played = []
        self.stopped = 0
        self.disconnected = False

    def is_connected(self):
        return self.connected

    def is_playing(self):
        return self.playing

    def is_paused(self):
        return self.paused

    async def connect(self):
        self.connected = True
        return self

    def stop(self):
        self.stopped += 1

    def play(self, source):
        self.played.append(source)

    async def disconnect(self, force=False):
        self.disconnected = True
        self.connected = False


class _FakeGuild:
    def __init__(self, voice=None, channel=None):
        self.voice_client = voice
        self.channel = channel

    def get_guild(self, gid):
        return self

    def get_channel(self, cid):
        return self.channel


def _install_media_fakes(monkeypatch, info=None):
    fake = types.ModuleType("discord")
    fake.opus = SimpleNamespace(load_opus=lambda name: None)
    fake.FFmpegPCMAudio = lambda url, **k: ("audio", url)
    monkeypatch.setitem(sys.modules, "discord", fake)
    monkeypatch.setattr(
        db.asyncio,
        "run_coroutine_threadsafe",
        lambda coro, loop: _FakeFuture(asyncio.run(coro)),
    )

    ydl_mod = types.ModuleType("yt_dlp")

    class YDL:
        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def extract_info(self, query, download):
            return info or {"url": "https://audio", "title": "Lagu"}

    ydl_mod.YoutubeDL = YDL
    monkeypatch.setitem(sys.modules, "yt_dlp", ydl_mod)
    return fake


def test_discord_play_music_guards(monkeypatch):
    monkeypatch.setattr(db, "_DC_CLIENT", None)
    monkeypatch.setattr(db, "_DC_LOOP", None)
    assert db.discord_play_music("")["status"] == "error"
    assert db.discord_play_music("lagu")["status"] == "error"

    monkeypatch.setattr(db, "_DC_CLIENT", object())
    monkeypatch.setattr(db, "_DC_LOOP", object())
    db._DISCORD_CMD_CTX.clear()
    db._DISCORD_CTX_LAST.clear()
    out = db.discord_play_music("lagu")
    assert out["status"] == "error"
    assert "voice channel" in out["message"]


def test_discord_play_music_success(monkeypatch):
    _install_media_fakes(monkeypatch)
    vc = _FakeVoiceChannel()
    vc.connected = True
    guild = _FakeGuild(voice=vc, channel=vc)
    monkeypatch.setattr(db, "_DC_CLIENT", guild)
    monkeypatch.setattr(db, "_DC_LOOP", _SyncLoop())
    db._set_discord_cmd_ctx(1, 10, 20)
    out = db.discord_play_music("lagu", user_id=1)
    assert out["status"] == "success"
    assert out["title"] == "Lagu"
    assert vc.played


def test_discord_play_music_missing_guild_or_channel(monkeypatch):
    _install_media_fakes(monkeypatch)
    monkeypatch.setattr(db, "_DC_CLIENT", SimpleNamespace(get_guild=lambda gid: None))
    monkeypatch.setattr(db, "_DC_LOOP", _SyncLoop())
    db._set_discord_cmd_ctx(2, 10, 20)
    assert "Guild" in db.discord_play_music("lagu", user_id=2)["message"]

    guild = _FakeGuild(channel=None)
    monkeypatch.setattr(db, "_DC_CLIENT", guild)
    db._set_discord_cmd_ctx(3, 10, 20)
    assert "channel" in db.discord_play_music("lagu", user_id=3)["message"]


def test_discord_play_music_search_entry(monkeypatch):
    _install_media_fakes(monkeypatch, info={"entries": [{"url": "u", "title": "T"}]})
    vc = _FakeVoiceChannel()
    monkeypatch.setattr(db, "_DC_CLIENT", _FakeGuild(voice=vc, channel=vc))
    monkeypatch.setattr(db, "_DC_LOOP", _SyncLoop())
    db._set_discord_cmd_ctx(4, 10, 20)
    assert db.discord_play_music("lagu", user_id=4)["title"] == "T"


# ---------------------------------------------------------------------------
# Registrasi tool, whisper, voice listen, play
# ---------------------------------------------------------------------------


def test_register_discord_tools(monkeypatch):
    import alfa.tools as tools

    monkeypatch.setattr(tools, "AVAILABLE_TOOLS", [])
    monkeypatch.setattr(tools.registry, "sync_registry_from_available", lambda items: None)
    db._register_discord_tools()
    assert db.discord_play_music in tools.AVAILABLE_TOOLS


def test_whisper_factory(monkeypatch):
    fake = types.ModuleType("faster_whisper")
    fake.WhisperModel = lambda *a, **k: "MODEL"
    monkeypatch.setitem(sys.modules, "faster_whisper", fake)
    monkeypatch.setattr(db, "_WHISPER_MODEL", None)
    assert db._whisper() == "MODEL"
    assert db._whisper() == "MODEL"


class _Audio:
    def __init__(self, data=b"x" * 9000):
        self.file = io.BytesIO(data)


def _voice_listen_env(monkeypatch, audio_data):
    fake = types.ModuleType("discord")

    class Sink:
        def __init__(self):
            self.audio_data = audio_data

    fake.sinks = SimpleNamespace(WaveSink=Sink)
    fake.FFmpegPCMAudio = lambda path: path
    monkeypatch.setitem(sys.modules, "discord", fake)

    vc = SimpleNamespace(
        started=False,
        stopped=False,
        playing=False,
        start_recording=lambda sink, cb: setattr(vc, "started", True),
        stop_recording=lambda: setattr(vc, "stopped", True),
        is_playing=lambda: False,
        play=lambda src: None,
    )
    chan = SimpleNamespace(sent=[], send=AsyncMock(side_effect=lambda text, **k: chan.sent.append(text)))
    return vc, chan


def test_vc_listen_loop_transcribes_and_replies(monkeypatch):
    vc, chan = _voice_listen_env(monkeypatch, {1: _Audio()})
    monkeypatch.setattr(db, "_VC_LISTEN", {10: True})
    monkeypatch.setattr(db, "_whisper", lambda: SimpleNamespace(
        transcribe=lambda path, language=None: ([SimpleNamespace(text="halo dunia")], None)
    ))
    monkeypatch.setattr(db, "_run_single", AsyncMock(return_value="jawaban suara"))
    tts = types.ModuleType("alfa.media.tts_engine")
    tts.text_to_speech_ogg = AsyncMock(return_value="reply.ogg")
    media_pkg = types.ModuleType("alfa.media")
    media_pkg.tts_engine = tts
    monkeypatch.setitem(sys.modules, "alfa.media", media_pkg)
    monkeypatch.setitem(sys.modules, "alfa.media.tts_engine", tts)
    calls = {"n": 0}

    async def fake_sleep(seconds):
        calls["n"] += 1
        if calls["n"] >= 2:
            db._VC_LISTEN[10] = False

    monkeypatch.setattr(db.asyncio, "sleep", fake_sleep)
    asyncio.run(db._vc_listen_loop(vc, chan, 10, 1))
    assert vc.started and vc.stopped
    assert any("Dengar" in s for s in chan.sent)


def test_vc_listen_loop_tts_failure_falls_back_to_text(monkeypatch):
    vc, chan = _voice_listen_env(monkeypatch, {1: _Audio()})
    monkeypatch.setattr(db, "_VC_LISTEN", {10: True})
    monkeypatch.setattr(db, "_whisper", lambda: SimpleNamespace(
        transcribe=lambda path, language=None: ([SimpleNamespace(text="halo dunia")], None)
    ))
    monkeypatch.setattr(db, "_run_single", AsyncMock(return_value="jawaban"))

    async def boom(*a, **k):
        raise RuntimeError("tts down")  # noqa: TRY003

    tts = types.ModuleType("alfa.media.tts_engine")
    tts.text_to_speech_ogg = boom
    media_pkg = types.ModuleType("alfa.media")
    media_pkg.tts_engine = tts
    monkeypatch.setitem(sys.modules, "alfa.media", media_pkg)
    monkeypatch.setitem(sys.modules, "alfa.media.tts_engine", tts)
    calls = {"n": 0}

    async def fake_sleep(seconds):
        calls["n"] += 1
        if calls["n"] >= 2:
            db._VC_LISTEN[10] = False

    monkeypatch.setattr(db.asyncio, "sleep", fake_sleep)
    asyncio.run(db._vc_listen_loop(vc, chan, 10, 1))
    assert any("jawaban" == s for s in chan.sent)


def test_vc_listen_loop_skips_short_audio_and_empty_reply(monkeypatch):
    vc, chan = _voice_listen_env(monkeypatch, {1: _Audio(b"x" * 10)})
    monkeypatch.setattr(db, "_VC_LISTEN", {10: True})

    async def fake_sleep(seconds):
        db._VC_LISTEN[10] = False

    monkeypatch.setattr(db.asyncio, "sleep", fake_sleep)
    asyncio.run(db._vc_listen_loop(vc, chan, 10, 1))
    assert chan.sent == []


def test_discord_play_success(monkeypatch):
    _install_media_fakes(monkeypatch)
    vc = _FakeVoiceChannel()
    voice_state = SimpleNamespace(channel=SimpleNamespace(connect=AsyncMock(return_value=vc)))
    msg = SimpleNamespace(
        author=SimpleNamespace(voice=voice_state),
        guild=SimpleNamespace(voice_client=None),
        reply=AsyncMock(),
    )
    monkeypatch.setattr(db.asyncio, "sleep", AsyncMock())
    asyncio.run(db._discord_play(msg, "lagu"))
    assert vc.played
    assert msg.reply.await_count == 1


def test_discord_play_no_voice(monkeypatch):
    _install_media_fakes(monkeypatch)
    msg = SimpleNamespace(
        author=SimpleNamespace(voice=None),
        guild=SimpleNamespace(voice_client=None),
        reply=AsyncMock(),
    )
    asyncio.run(db._discord_play(msg, "lagu"))
    msg.reply.assert_not_awaited()


def test_discord_play_error(monkeypatch):
    _install_media_fakes(monkeypatch)
    msg = SimpleNamespace(
        author=SimpleNamespace(voice=None),
        guild=SimpleNamespace(voice_client=SimpleNamespace(
            is_connected=lambda: True,
            is_playing=lambda: (_ for _ in ()).throw(RuntimeError("boom")),
            is_paused=lambda: False,
            stop=lambda: None,
        )),
        reply=AsyncMock(),
    )
    monkeypatch.setattr(db.asyncio, "sleep", AsyncMock())
    asyncio.run(db._discord_play(msg, "lagu"))
    assert "Musik gagal" in msg.reply.await_args.args[0]


def test_tg_owner_uid(monkeypatch):
    from alfa.bot import config

    monkeypatch.setattr(config, "ALLOWED_USER_IDS", {77})
    assert db._tg_owner_uid() == 77


# ---------------------------------------------------------------------------
# main() + slash command + on_message
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self):
        self.sent = []
        self.deferred = False

    async def defer(self, thinking=False):
        self.deferred = True

    async def send_message(self, text, ephemeral=False):
        self.sent.append((text, ephemeral))


class _FakeFollowup:
    def __init__(self):
        self.sent = []

    async def send(self, text, **kwargs):
        self.sent.append(text)


class _FakeInteraction:
    def __init__(self, user_id=1, voice=None, guild=None):
        self.user = SimpleNamespace(id=user_id, voice=voice)
        self.guild = guild
        self.response = _FakeResponse()
        self.followup = _FakeFollowup()
        self.channel = SimpleNamespace(send=AsyncMock())


class _FakeTyping:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _FakeMessage:
    def __init__(self, content, author_id=1, guild=None, mentions=None, bot=False):
        self.content = content
        self.author = SimpleNamespace(id=author_id, bot=bot, voice=None)
        self.guild = guild
        self.mentions = mentions or []
        self.replies = []
        self.channel = SimpleNamespace(
            typing=lambda: _FakeTyping(),
            send=AsyncMock(side_effect=lambda text, **k: self.replies.append(text)),
        )

    async def reply(self, text=None, **kwargs):
        self.replies.append(text)
        return SimpleNamespace()


class _FakeLoop:
    def __init__(self):
        self.tasks = []

    def create_task(self, coro):
        self.tasks.append(coro)
        coro.close()
        return SimpleNamespace()


class _FakeClient:
    instances = []

    def __init__(self, intents=None):
        self.intents = intents
        self.user = SimpleNamespace(id=999, bot=False)
        self.loop = _FakeLoop()
        self.events = {}
        self.presences = []
        self.ran = None
        _FakeClient.instances.append(self)

    def event(self, fn):
        self.events[fn.__name__] = fn
        return fn

    async def change_presence(self, activity=None):
        self.presences.append(activity)

    def run(self, token, log_handler=None):
        self.ran = token


class _FakeTree:
    def __init__(self, client):
        self.client = client
        self.commands = {}

    def command(self, name=None, description=None, guild=None):
        def deco(fn):
            self.commands[name] = fn
            return fn

        return deco

    async def sync(self, guild=None):
        return list(self.commands)


def _install_discord_for_main(monkeypatch):
    fake = types.ModuleType("discord")
    fake.__path__ = []

    class Intents:
        @staticmethod
        def default():
            return SimpleNamespace()

    class Object:
        def __init__(self, id):
            self.id = id

    class Activity:
        def __init__(self, type=None, name=None):
            self.type = type
            self.name = name

    class ActivityType:
        watching = "watching"
        playing = "playing"

    class File:
        def __init__(self, path):
            self.path = path

    fake.Intents = Intents
    fake.Client = _FakeClient
    fake.Object = Object
    fake.Activity = Activity
    fake.ActivityType = ActivityType
    fake.File = File
    fake.opus = SimpleNamespace(load_opus=lambda n: None)
    fake.FFmpegPCMAudio = lambda *a, **k: ("audio", a)
    fake.DiscordException = Exception
    app_commands = types.ModuleType("discord.app_commands")
    app_commands.CommandTree = _FakeTree
    fake.app_commands = app_commands
    monkeypatch.setitem(sys.modules, "discord", fake)
    monkeypatch.setitem(sys.modules, "discord.app_commands", app_commands)
    return fake


@pytest.fixture
def bridge(monkeypatch):
    from alfa.core import security_boot_guard

    monkeypatch.setattr(security_boot_guard, "check_runtime_security", lambda name: None)
    monkeypatch.setattr(db, "_discord_token", lambda: "token")
    monkeypatch.setattr(db, "_register_discord_tools", lambda: None)
    _install_discord_for_main(monkeypatch)
    db._VC_LISTEN.clear()
    db._MIRROR_PENDING.clear()
    db._DISCORD_CMD_CTX.clear()
    db._DISCORD_CTX_LAST.clear()
    db.main()
    client = _FakeClient.instances[-1]
    return client, client.tree if hasattr(client, "tree") else None


def test_main_registers_commands_and_on_ready(monkeypatch):
    from alfa.core import security_boot_guard

    monkeypatch.setattr(security_boot_guard, "check_runtime_security", lambda name: None)
    monkeypatch.setattr(db, "_discord_token", lambda: "token")
    monkeypatch.setattr(db, "_register_discord_tools", lambda: None)
    _install_discord_for_main(monkeypatch)
    # Rekam CommandTree milik main.
    created = {}
    original = _FakeTree.__init__

    def capture(self, client):
        original(self, client)
        created["tree"] = self

    monkeypatch.setattr(_FakeTree, "__init__", capture)
    db.main()
    client = _FakeClient.instances[-1]
    tree = created["tree"]
    assert client.ran == "token"
    assert set(tree.commands) == {"tanya", "swarm", "misi", "gabung", "situs"}

    asyncio.run(client.events["on_ready"]())
    assert client.presences
    assert db._DC_LOOP is not None


def test_main_exits_without_token(monkeypatch):
    from alfa.core import security_boot_guard

    monkeypatch.setattr(security_boot_guard, "check_runtime_security", lambda name: None)
    monkeypatch.setattr(db, "_discord_token", lambda: "")
    with pytest.raises(SystemExit):
        db.main()


def _bridge_fixture(monkeypatch):
    from alfa.core import security_boot_guard

    monkeypatch.setattr(security_boot_guard, "check_runtime_security", lambda name: None)
    monkeypatch.setattr(db, "_discord_token", lambda: "token")
    monkeypatch.setattr(db, "_register_discord_tools", lambda: None)
    _install_discord_for_main(monkeypatch)
    created = {}
    original = _FakeTree.__init__

    def capture(self, client):
        original(self, client)
        created["tree"] = self

    monkeypatch.setattr(_FakeTree, "__init__", capture)
    db.main()
    return _FakeClient.instances[-1], created["tree"]


def test_slash_tanya(monkeypatch):
    client, tree = _bridge_fixture(monkeypatch)
    monkeypatch.setattr(db, "_run_single", AsyncMock(return_value="balasan"))
    interaction = _FakeInteraction()
    asyncio.run(tree.commands["tanya"](interaction, "halo"))
    assert interaction.response.deferred
    assert interaction.followup.sent == ["balasan"]


def test_slash_swarm_owner_and_non_owner(monkeypatch):
    client, tree = _bridge_fixture(monkeypatch)
    monkeypatch.setattr(db, "_owner_ids", lambda: {1})
    monkeypatch.setattr(db, "_run_swarm", AsyncMock(return_value=("steps", "final")))
    non_owner = _FakeInteraction(user_id=2)
    asyncio.run(tree.commands["swarm"](non_owner, "tugas"))
    assert non_owner.response.sent[0][1] is True

    owner = _FakeInteraction(user_id=1)
    asyncio.run(tree.commands["swarm"](owner, "tugas"))
    assert owner.response.deferred
    assert any("Misi swarm dimulai" in s for s in owner.followup.sent)


def test_slash_misi_reads_checkpoints(monkeypatch, tmp_path):
    client, tree = _bridge_fixture(monkeypatch)
    from alfa.swarm import checkpoint

    monkeypatch.setattr(checkpoint, "CHECKPOINT_DIR", str(tmp_path))
    (tmp_path / "a.json").write_text(
        json.dumps(
            {
                "session_id": "sesi-1",
                "status": "completed",
                "steps_done": 2,
                "steps_total": 3,
                "topic": "topik",
            }
        ),
        encoding="utf-8",
    )
    interaction = _FakeInteraction()
    asyncio.run(tree.commands["misi"](interaction))
    text = interaction.response.sent[0][0]
    assert "sesi-1" in text and "2/3" in text


def test_slash_misi_empty(monkeypatch, tmp_path):
    client, tree = _bridge_fixture(monkeypatch)
    from alfa.swarm import checkpoint

    monkeypatch.setattr(checkpoint, "CHECKPOINT_DIR", str(tmp_path))
    interaction = _FakeInteraction()
    asyncio.run(tree.commands["misi"](interaction))
    assert "Belum ada misi" in interaction.response.sent[0][0]


def test_slash_gabung_branches(monkeypatch):
    client, tree = _bridge_fixture(monkeypatch)
    monkeypatch.setattr(db, "_owner_ids", lambda: {1})

    non_owner = _FakeInteraction(user_id=2)
    asyncio.run(tree.commands["gabung"](non_owner))
    assert non_owner.response.sent[0][1] is True

    no_voice = _FakeInteraction(user_id=1)
    asyncio.run(tree.commands["gabung"](no_voice))
    assert "Masuk dulu" in no_voice.response.sent[0][0]

    vc = _FakeVoiceChannel()
    voice = SimpleNamespace(channel=SimpleNamespace(connect=AsyncMock(return_value=vc)))
    guild = SimpleNamespace(id=10, voice_client=None)
    ok = _FakeInteraction(user_id=1, voice=voice, guild=guild)
    asyncio.run(tree.commands["gabung"](ok))
    assert db._VC_LISTEN[10] is True
    assert any("Jarvis ON" in s for s in ok.followup.sent)


def test_slash_gabung_error(monkeypatch):
    client, tree = _bridge_fixture(monkeypatch)
    monkeypatch.setattr(db, "_owner_ids", lambda: {1})

    async def boom(*a, **k):
        raise RuntimeError("join gagal")  # noqa: TRY003

    voice = SimpleNamespace(channel=SimpleNamespace(connect=boom))
    guild = SimpleNamespace(id=10, voice_client=None)
    interaction = _FakeInteraction(user_id=1, voice=voice, guild=guild)
    asyncio.run(tree.commands["gabung"](interaction))
    assert any("Join gagal" in s for s in interaction.followup.sent)


def test_slash_situs(monkeypatch):
    client, tree = _bridge_fixture(monkeypatch)
    import alfa.tools as tools

    monkeypatch.setattr(
        tools,
        "serve_site",
        lambda action="status": {"sites": [{"title": "Situs", "backend_on": True}]},
    )
    interaction = _FakeInteraction()
    asyncio.run(tree.commands["situs"](interaction))
    assert "Situs" in interaction.response.sent[0][0]


def _invoke_message(monkeypatch, content, author_id=1, guild=None, mentions=None, bot=False):
    client, tree = _bridge_fixture(monkeypatch)
    msg = _FakeMessage(content, author_id=author_id, guild=guild, mentions=mentions, bot=bot)
    asyncio.run(client.events["on_message"](msg))
    return msg


def test_on_message_ignores_bot_and_empty(monkeypatch):
    msg = _invoke_message(monkeypatch, "halo", bot=True)
    assert msg.replies == []
    msg = _invoke_message(monkeypatch, "   ")
    assert msg.replies == []


def test_on_message_non_owner_owner_command(monkeypatch):
    monkeypatch.setattr(db, "_owner_ids", lambda: {1})
    msg = _invoke_message(monkeypatch, "!swarm tugas", author_id=2)
    assert "Perintah khusus owner" in msg.replies[0]


def test_on_message_swarm_branches(monkeypatch):
    monkeypatch.setattr(db, "_owner_ids", lambda: {1})
    monkeypatch.setattr(db, "_run_swarm", AsyncMock(return_value=("steps", "final")))
    msg = _invoke_message(monkeypatch, "!swarm")
    assert "Usage" in msg.replies[0]

    from alfa.swarm import workspace_hygiene

    monkeypatch.setattr(workspace_hygiene, "request_cancel_swarm", lambda: True)
    msg = _invoke_message(monkeypatch, "!swarm cancel")
    assert "henti dikirim" in msg.replies[0]

    from alfa.bot import mode_commands

    monkeypatch.setattr(mode_commands, "SWARM_TEMPLATES", {"audit": "Audit kode"})
    msg = _invoke_message(monkeypatch, "!swarm template")
    assert "Templat" in msg.replies[0]
    msg = _invoke_message(monkeypatch, "!swarm template missing")
    assert "tidak ada" in msg.replies[0]
    msg = _invoke_message(monkeypatch, "!swarm template audit")
    assert any("Misi swarm dimulai" in r for r in msg.replies)
    assert "steps" in [r for r in msg.replies if r == "steps"] or any("steps" in r for r in msg.replies)


def test_on_message_sites_serve_stop(monkeypatch):
    monkeypatch.setattr(db, "_owner_ids", lambda: {1})
    import alfa.tools as tools

    calls = []

    def fake_site(action="status", slug=""):
        calls.append((action, slug))
        return {"status": "ok", "sites": [{"slug": "a", "backend_on": False}]}

    monkeypatch.setattr(tools, "serve_site", fake_site)
    msg = _invoke_message(monkeypatch, "!sites")
    assert "Galeri Situs" in msg.replies[0]
    msg = _invoke_message(monkeypatch, "!serve")
    assert "Usage" in msg.replies[0]
    msg = _invoke_message(monkeypatch, "!serve a")
    assert "ok" in msg.replies[0]
    msg = _invoke_message(monkeypatch, "!stop")
    assert "Usage" in msg.replies[0]
    msg = _invoke_message(monkeypatch, "!stop a")
    assert "ok" in msg.replies[0]
    assert ("start", "a") in calls and ("stop", "a") in calls


def test_on_message_budget(monkeypatch):
    monkeypatch.setattr(db, "_owner_ids", lambda: {1})
    from alfa.core import rate_limiter

    monkeypatch.setattr(
        rate_limiter,
        "get_budget_report",
        lambda: {"status": "ok", "total_tokens": 10, "budget_limit": 100, "pct": 0.1, "remaining": 90},
    )
    msg = _invoke_message(monkeypatch, "!budget")
    assert "Kuota" in msg.replies[0]
    monkeypatch.setattr(rate_limiter, "get_budget_report", lambda: {"status": "empty"})
    msg = _invoke_message(monkeypatch, "!budget")
    assert "belum tersedia" in msg.replies[0]


def test_on_message_waringkas(monkeypatch):
    monkeypatch.setattr(db, "_owner_ids", lambda: {1})
    from alfa.bot import wa_digest

    monkeypatch.setattr(wa_digest, "build_digest_text", AsyncMock(return_value="digest"))
    msg = _invoke_message(monkeypatch, "!waringkas ringkas")
    assert msg.replies == ["digest"]


def test_on_message_screenshot_and_cam(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "_owner_ids", lambda: {1})
    from alfa.tools.desktop import capture

    shot = tmp_path / "shot.png"
    shot.write_text("x", encoding="utf-8")
    cam = tmp_path / "cam.png"
    cam.write_text("x", encoding="utf-8")
    monkeypatch.setattr(
        capture,
        "capture_desktop_screenshot",
        lambda: {"status": "success", "file_path": str(shot)},
    )
    monkeypatch.setattr(capture, "capture_webcam_frame", lambda: {"path": str(cam)})
    msg = _invoke_message(monkeypatch, "!ss")
    assert any("Layar laptop" in r for r in msg.replies)
    msg = _invoke_message(monkeypatch, "!cam")
    assert any("Webcam" in r for r in msg.replies)

    monkeypatch.setattr(
        capture, "capture_desktop_screenshot", lambda: {"status": "error", "message": "no display"}
    )
    msg = _invoke_message(monkeypatch, "!ss")
    assert any("Screenshot gagal" in r for r in msg.replies)

    monkeypatch.setattr(capture, "capture_webcam_frame", lambda: {"message": "no cam"})
    msg = _invoke_message(monkeypatch, "!cam")
    assert any("Webcam gagal" in r for r in msg.replies)


def test_on_message_play_branches(monkeypatch):
    monkeypatch.setattr(db, "_owner_ids", lambda: {1})
    msg = _invoke_message(monkeypatch, "!play")
    assert "Usage" in msg.replies[0]

    msg = _invoke_message(monkeypatch, "!play lagu")
    assert "voice channel" in msg.replies[0]

    voice = SimpleNamespace(channel=SimpleNamespace(id=5), id=1)

    class _Locked:
        def locked(self):
            return True

    monkeypatch.setitem(db._PLAY_LOCKS, 10, _Locked())
    guild = SimpleNamespace(id=10, voice_client=None)
    client, tree = _bridge_fixture(monkeypatch)
    real_msg = _FakeMessage("!play lagu", author_id=1, guild=guild)
    real_msg.author = SimpleNamespace(id=1, bot=False, voice=voice)
    asyncio.run(client.events["on_message"](real_msg))
    assert any("Masih memproses" in r for r in real_msg.replies)


def test_on_message_play_calls_play(monkeypatch):
    monkeypatch.setattr(db, "_owner_ids", lambda: {1})
    client, tree = _bridge_fixture(monkeypatch)
    voice = SimpleNamespace(channel=SimpleNamespace(id=5), id=1)
    guild = SimpleNamespace(id=11, voice_client=None)
    msg = _FakeMessage("!play lagu", author_id=1, guild=guild)
    msg.author = SimpleNamespace(id=1, bot=False, voice=voice)
    db._PLAY_LOCKS.pop(11, None)
    play = AsyncMock()
    monkeypatch.setattr(db, "_discord_play", play)
    asyncio.run(client.events["on_message"](msg))
    play.assert_awaited_once()


def test_on_message_stopvc_join_leave(monkeypatch):
    monkeypatch.setattr(db, "_owner_ids", lambda: {1})
    vc = _FakeVoiceChannel()
    vc.connected = True
    guild = SimpleNamespace(id=12, voice_client=vc)
    msg = _invoke_message(monkeypatch, "!stopvc", guild=guild)
    assert any("Keluar dari voice" in r for r in msg.replies)

    guild2 = SimpleNamespace(id=13, voice_client=None)
    msg = _invoke_message(monkeypatch, "!stopvc", guild=guild2)
    assert any("Tidak sedang" in r for r in msg.replies)

    msg = _invoke_message(monkeypatch, "!join", guild=guild2)
    assert "Masuk dulu" in msg.replies[0]

    voice = SimpleNamespace(channel=SimpleNamespace(connect=AsyncMock(return_value=_FakeVoiceChannel())))
    real = _FakeMessage("!join", author_id=1, guild=guild2)
    real.author = SimpleNamespace(id=1, bot=False, voice=voice)
    client, tree = _bridge_fixture(monkeypatch)
    asyncio.run(client.events["on_message"](real))
    assert any("Jarvis ON" in r for r in real.replies)
    assert db._VC_LISTEN[13] is True

    real2 = _FakeMessage("!join", author_id=1, guild=guild2)
    real2.author = SimpleNamespace(id=1, bot=False, voice=voice)
    asyncio.run(client.events["on_message"](real2))
    assert any("sudah jalan" in r for r in real2.replies)

    real3 = _FakeMessage("!leave", author_id=1, guild=guild2)
    asyncio.run(client.events["on_message"](real3))
    assert db._VC_LISTEN[13] is False
    assert any("Jarvis OFF" in r for r in real3.replies)


def test_on_message_help_and_chat(monkeypatch):
    monkeypatch.setattr(db, "_owner_ids", lambda: {1})
    msg = _invoke_message(monkeypatch, "!help")
    assert any("ALFA Discord bridge" in r for r in msg.replies)

    monkeypatch.setattr(db, "_run_single", AsyncMock(return_value="jawaban chat"))
    client, tree = _bridge_fixture(monkeypatch)
    chat = _FakeMessage("halo alfa", author_id=1, guild=None)
    asyncio.run(client.events["on_message"](chat))
    assert chat.replies == ["jawaban chat"]


def test_on_message_error_is_logged(monkeypatch):
    monkeypatch.setattr(db, "_owner_ids", lambda: {1})
    client, tree = _bridge_fixture(monkeypatch)

    class BoomMessage(_FakeMessage):
        async def reply(self, *a, **k):
            raise RuntimeError("reply down")  # noqa: TRY003

    msg = BoomMessage("!help", author_id=1)
    asyncio.run(client.events["on_message"](msg))


# ---------------------------------------------------------------------------
# Loop digest & mirror
# ---------------------------------------------------------------------------


def test_digest_loop_sends_daily(monkeypatch):
    from alfa.bot import wa_digest

    now = SimpleNamespace(strftime=lambda fmt: "07:00" if fmt == "%H:%M" else "2026-11-20")
    fake_dt = types.ModuleType("datetime")
    fake_dt.datetime = SimpleNamespace(now=lambda: now)
    monkeypatch.setitem(sys.modules, "datetime", fake_dt)
    monkeypatch.setattr(wa_digest, "digest_enabled", lambda: True)
    monkeypatch.setattr(wa_digest, "digest_hours", lambda: {"07:00"})
    monkeypatch.setattr(wa_digest, "_setting", lambda key, default="": "")
    monkeypatch.setattr(wa_digest, "_set_setting", lambda key, value: None)
    monkeypatch.setattr(wa_digest, "build_digest_text", AsyncMock(return_value="digest"))
    monkeypatch.setattr(db, "_channel_id", lambda: 5)
    sent = []
    chan = SimpleNamespace(send=AsyncMock(side_effect=lambda text: sent.append(text)))
    cli = SimpleNamespace(
        wait_until_ready=AsyncMock(),
        fetch_channel=AsyncMock(return_value=chan),
    )

    async def fake_sleep(seconds):
        if seconds == 60:
            raise _StopLoopError

    monkeypatch.setattr(db.asyncio, "sleep", fake_sleep)
    with pytest.raises(_StopLoopError):
        asyncio.run(db._digest_loop(cli))
    assert sent == ["digest"]


def test_digest_loop_disabled(monkeypatch):
    from alfa.bot import wa_digest

    monkeypatch.setattr(wa_digest, "digest_enabled", lambda: False)
    cli = SimpleNamespace(wait_until_ready=AsyncMock())

    async def fake_sleep(seconds):
        raise _StopLoopError

    monkeypatch.setattr(db.asyncio, "sleep", fake_sleep)
    with pytest.raises(_StopLoopError):
        asyncio.run(db._digest_loop(cli))


def test_mirror_loop_reads_feed(monkeypatch, tmp_path):
    feed = tmp_path / "feed.jsonl"
    feed.write_text(
        json.dumps({"tag": "PLAN", "text": "rencana"}) + "\n"
        + "bukan-json\n"
        + json.dumps({"tag": "OTHER", "text": "abaikan"}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(db, "FEED_FILE", str(feed))
    db._MIRROR_PENDING.clear()
    real_getsize = db.os.path.getsize
    calls = {"n": 0}

    def fake_getsize(path):
        calls["n"] += 1
        return 0 if calls["n"] == 1 else real_getsize(path)

    monkeypatch.setattr(db.os.path, "getsize", fake_getsize)
    monkeypatch.setattr(db, "_setting", lambda key, default="": "1")
    monkeypatch.setattr(db, "_channel_id", lambda: 5)
    sent = []
    chan = SimpleNamespace(send=AsyncMock(side_effect=lambda text: sent.append(text)))
    cli = SimpleNamespace(
        wait_until_ready=AsyncMock(),
        fetch_channel=AsyncMock(return_value=chan),
    )

    async def fake_sleep(seconds):
        if seconds == 15:
            raise _StopLoopError

    monkeypatch.setattr(db.asyncio, "sleep", fake_sleep)
    with pytest.raises(_StopLoopError):
        asyncio.run(db._mirror_loop(cli))
    assert any("PLAN" in s for s in sent)
    assert not any("bukan-json" in s for s in sent)
    assert not any("OTHER" in s for s in sent)


def test_mirror_loop_channel_error(monkeypatch):
    cli = SimpleNamespace(
        wait_until_ready=AsyncMock(),
        fetch_channel=AsyncMock(side_effect=RuntimeError("no channel")),
    )
    asyncio.run(db._mirror_loop(cli))


def test_mirror_loop_disabled(monkeypatch):
    monkeypatch.setattr(db, "_setting", lambda key, default="": "0")
    monkeypatch.setattr(db, "_channel_id", lambda: 5)
    chan = SimpleNamespace(send=AsyncMock())
    cli = SimpleNamespace(
        wait_until_ready=AsyncMock(),
        fetch_channel=AsyncMock(return_value=chan),
    )

    async def fake_sleep(seconds):
        raise _StopLoopError

    monkeypatch.setattr(db.asyncio, "sleep", fake_sleep)
    with pytest.raises(_StopLoopError):
        asyncio.run(db._mirror_loop(cli))
    chan.send.assert_not_awaited()
