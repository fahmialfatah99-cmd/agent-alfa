"""Jembatan Discord ALFA: chat + swarm + cermin war-room.

- Chat teks (owner saja) -> otak yang sama (run_agent_turn, memori bersama Telegram).
- !swarm <tugas> -> misi multi-agen, hasil dipost ke channel.
- !sites / !budget / !waringkas -> perintah yang sama versi Discord.
- Mirror: baris baru live_meeting_feed.jsonl diteruskan ke channel.
"""

import asyncio
import json
import logging
import os
import sys
from typing import Any

logger = logging.getLogger("DiscordBridge")

FEED_FILE = os.path.expanduser("~/Dokumen/ALFA_SWARM_OUTPUTS/live_meeting_feed.jsonl")
DEF_CHANNEL_ID = 1066901365357551708  # #general
DEF_OWNER_ID = 570747813781176332


def _db():
    from alfa.core import database

    return database


def _setting(key: str, default: str = "") -> str:
    try:
        db = _db()
        with db.get_sync_db() as conn:
            row = conn.execute("SELECT value FROM system_settings WHERE key = ?", (key,)).fetchone()
            if row and row["value"]:
                return str(row["value"])
    except Exception:
        pass
    return default


def _discord_token() -> str:
    db = _db()
    with db.get_sync_db() as conn:
        row = conn.execute("SELECT api_key FROM api_keys WHERE provider='discord'").fetchone()
    if not row:
        return ""
    try:
        return str(db.decrypt_key(row["api_key"]))
    except Exception:
        return ""


def _owner_ids() -> set[int]:
    try:
        from alfa.bot.config import ALLOWED_USER_IDS

        tg = {int(x) for x in ALLOWED_USER_IDS}
    except Exception:
        tg = set()
    raw = _setting("discord_owner_id", str(DEF_OWNER_ID))
    try:
        disc = {int(x) for x in raw.replace(",", " ").split() if x.strip().isdigit()}
    except Exception:
        disc = set()
    return tg | disc | {DEF_OWNER_ID}


def _channel_id() -> int:
    try:
        return int(_setting("discord_channel_id", str(DEF_CHANNEL_ID)))
    except ValueError:
        return DEF_CHANNEL_ID


def _split(text: str, limit: int = 1900) -> list[str]:
    text = text or ""
    if len(text) <= limit:
        return [text]
    chunks, cur = [], ""
    for line in text.split("\n"):
        if len(cur) + len(line) + 1 > limit:
            chunks.append(cur)
            cur = ""
        cur += (line + "\n")
    if cur.strip():
        chunks.append(cur)
    return chunks or [text[:limit]]


async def _run_single(prompt: str, uid: int) -> str:
    from alfa.bot.turn_executor import run_agent_turn

    try:
        try:
            from alfa.tools.media.player import set_host_play_blocked

            set_host_play_blocked(True)  # Discord: musik HANYA via !play, tanpa Brave
        except Exception:
            pass
        try:
            return await run_agent_turn(user_id=uid, user_prompt=prompt, chat_id=uid)
        finally:
            try:
                from alfa.tools.media.player import set_host_play_blocked as _unblock

                _unblock(False)
            except Exception:
                pass
    except Exception as e:
        logger.error(f"[discord] turn gagal: {e}")
        return f"❌ Gagal memproses ({type(e).__name__})."


async def _run_swarm(topic: str) -> tuple[str, str]:
    from alfa.bot.mode_commands import format_swarm_result, run_swarm_task

    try:
        result = await run_swarm_task(topic)
        return format_swarm_result(result)[:2]
    except Exception as e:
        logger.error(f"[discord] swarm gagal: {e}")
        return f"❌ Misi gagal: {e}", ""



_VC_LISTEN: dict[int, bool] = {}
_DC_CLIENT = None
_DC_LOOP = None
_DISCORD_CMD_CTX: dict = {}


def discord_play_music(query: str = "") -> dict:
    """Putar lagu di voice channel Discord (SSEMPURNA untuk request musik di chat).

    Pakai tool ini tiap user minta putar lagu/musik di Discord — JANGAN tolak,
    JANGAN arahkan ke !play. Musik HANYA boleh lewat tool ini (pemutar host diblokir).

    Args:
        query: Judul/penyanyi lagu (mis. 'dj tiktok'). Wajib diisi.
    """
    import asyncio as _a

    query = (query or "").strip()
    if not query:
        return {"status": "error", "message": "Query lagu kosong."}
    if _DC_CLIENT is None or _DC_LOOP is None:
        return {"status": "error", "message": "Klien Discord belum siap."}
    gid = _DISCORD_CMD_CTX.get("guild_id")
    vc_id = _DISCORD_CMD_CTX.get("voice_channel_id")
    if not gid or not vc_id:
        return {"status": "error",
                "message": "User belum masuk voice channel — minta user join VC dulu."}

    async def _do():
        import discord as _dc

        try:
            _dc.opus.load_opus("libopus.so.0")
        except Exception:
            pass
        guild = _DC_CLIENT.get_guild(int(gid))
        if guild is None:
            return {"status": "error", "message": "Guild tak ditemukan."}
        channel = guild.get_channel(int(vc_id))
        if channel is None:
            return {"status": "error", "message": "Voice channel tak ditemukan."}
        vc = guild.voice_client
        if not vc or not vc.is_connected():
            vc = await channel.connect()
        try:
            if vc.is_playing() or vc.is_paused():
                vc.stop()
        except Exception:
            pass
        import yt_dlp as _ydl

        opts = {"format": "bestaudio/best", "quiet": True, "noplaylist": True,
                "default_search": "ytsearch1", "no_warnings": True}
        with _ydl.YoutubeDL(opts) as ydl:
            info = await _a.to_thread(ydl.extract_info, query, False)
            if isinstance(info, dict) and "entries" in info:
                info = info["entries"][0]
            url, title = info["url"], info.get("title", query)
        vc.play(_dc.FFmpegPCMAudio(url, before_options="-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"))
        return {"status": "success", "title": title,
                "message": f"Sedang diputar di voice channel: {title}"}

    fut = _a.run_coroutine_threadsafe(_do(), _DC_LOOP)
    try:
        return fut.result(timeout=120)
    except Exception as e:
        return {"status": "error", "message": f"{type(e).__name__}: {str(e)[:150]}"}


def _register_discord_tools() -> None:
    try:
        from alfa.tools import AVAILABLE_TOOLS

        names = {getattr(f, "__name__", "") for f in AVAILABLE_TOOLS}
        if "discord_play_music" not in names:
            AVAILABLE_TOOLS.append(discord_play_music)
    except Exception as e:
        logger.debug(f"[discord] registrasi tool gagal: {e}")
_PLAY_LOCKS: dict[int, object] = {}


def _play_lock(gid: int):
    import asyncio as _a

    lock = _PLAY_LOCKS.get(gid)
    if lock is None:
        lock = _a.Lock()
        _PLAY_LOCKS[gid] = lock
    return lock
_WHISPER_MODEL = None


def _whisper():
    global _WHISPER_MODEL
    if _WHISPER_MODEL is None:
        from faster_whisper import WhisperModel

        _WHISPER_MODEL = WhisperModel(
            __import__("os").getenv("ALFA_WHISPER_MODEL", "base"),
            device="cpu", compute_type="int8",
        )
    return _WHISPER_MODEL


async def _vc_listen_loop(vc, chan, guild_id: int, owner_uid: int) -> None:
    """Half-duplex Jarvis: rekam 8 detik -> transcribe -> jawab suara. Berhenti bila flag mati."""
    import discord as _dc

    _dc_any: Any = _dc
    while _VC_LISTEN.get(guild_id):
        try:
            sink = _dc_any.sinks.WaveSink()
            vc.start_recording(sink, lambda *a: None)
            await asyncio.sleep(8)
            try:
                vc.stop_recording()
            except Exception:
                pass
            await asyncio.sleep(1)
            heard = []
            for _user_id, audio in (sink.audio_data or {}).items():
                try:
                    import tempfile as _tf

                    opus_frames = getattr(audio, "file", None)
                    if opus_frames is None:
                        continue
                    opus_frames.seek(0)
                    data = opus_frames.read()
                    if len(data) < 8000:
                        continue
                    with _tf.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
                        tf.write(data)
                        wpath = tf.name
                    model = await asyncio.to_thread(_whisper)
                    segs, _ = await asyncio.to_thread(model.transcribe, wpath, language="id")
                    text = " ".join(s.text for s in segs).strip()
                    try:
                        __import__("os").remove(wpath)
                    except OSError:
                        pass
                    if len(text) >= 4:
                        heard.append(text)
                except Exception as e:
                    logger.debug(f"[jarvis] transcribe gagal: {e}")
            if not heard:
                continue
            prompt = heard[-1][:500]
            await chan.send(f"👂 Dengar: _{prompt[:200]}_")
            reply = await _run_single(f"[Obrolan suara Discord] {prompt}", owner_uid)
            reply = (reply or "")[:800]
            if not reply.strip():
                continue
            try:
                from alfa.media import tts_engine as _tts

                ogg = await _tts.text_to_speech_ogg(reply)
                while vc.is_playing():
                    await asyncio.sleep(0.5)
                vc.play(_dc.FFmpegPCMAudio(ogg))
                while vc.is_playing():
                    await asyncio.sleep(0.5)
            except Exception as e:
                await chan.send((reply)[:1900])
                logger.debug(f"[jarvis] TTS gagal: {e}")
        except Exception as e:
            logger.debug(f"[jarvis] loop: {e}")
            await asyncio.sleep(2)




async def _discord_play(msg, query: str) -> None:
    """Putar satu lagu; selalu hentikan audio lama dulu (anti-double)."""
    import discord as _dc

    try:
        try:
            _dc.opus.load_opus("libopus.so.0")
        except Exception:
            pass
        voice_state = getattr(msg.author, "voice", None)
        vc = msg.guild.voice_client
        if not vc or not vc.is_connected():
            if not voice_state or not voice_state.channel:
                return
            vc = await voice_state.channel.connect()
        try:
            if vc.is_playing() or vc.is_paused():
                vc.stop()
        except Exception:
            pass
        await asyncio.sleep(0.3)
        import yt_dlp as _ydl

        opts = {"format": "bestaudio/best", "quiet": True, "noplaylist": True,
                "default_search": "ytsearch1", "no_warnings": True}
        with _ydl.YoutubeDL(opts) as ydl:
            info = await asyncio.to_thread(ydl.extract_info, query, False)
            if isinstance(info, dict) and "entries" in info:
                info = info["entries"][0]
            url = info["url"]
            title = info.get("title", query)
        try:
            if vc.is_playing() or vc.is_paused():
                vc.stop()
        except Exception:
            pass
        vc.play(_dc.FFmpegPCMAudio(url, before_options="-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"))
        await msg.reply(f"▶️ **Memutar:** {title[:150]}")
    except Exception as e:
        await msg.reply(f"❌ Musik gagal: {str(e)[:200]}")


def _tg_owner_uid() -> int:
    try:
        from alfa.bot.config import ALLOWED_USER_IDS

        return int(list(ALLOWED_USER_IDS)[0])
    except Exception:
        return DEF_OWNER_ID


def main() -> None:
    from alfa.core.security_boot_guard import check_runtime_security

    check_runtime_security("discord-bot")

    import discord

    token = _discord_token()
    if not token:
        print("Token Discord tidak ada di vault (provider='discord').", file=sys.stderr)
        sys.exit(1)

    intents = discord.Intents.default()
    intents.message_content = True
    intents.guilds = True
    global _DC_CLIENT, _DC_LOOP
    intents.dm_messages = True
    client = discord.Client(intents=intents)
    _DC_CLIENT = client
    _register_discord_tools()

    from discord import app_commands as _ac

    tree = _ac.CommandTree(client)
    _guild = __import__("discord").Object(id=1066901364636139641)

    async def _owner_only(interaction) -> bool:
        if interaction.user.id not in _owner_ids():
            try:
                await interaction.response.send_message("🔒 Khusus owner.", ephemeral=True)
            except Exception:
                pass
            return False
        return True

    @tree.command(name="tanya", description="Tanya agen ALFA (memori bersama Telegram)", guild=_guild)
    async def _slash_tanya(interaction, pesan: str):
        await interaction.response.defer(thinking=True)
        reply = await _run_single(pesan, _tg_owner_uid())
        for part in _split(reply)[:4]:
            await interaction.followup.send(part)

    @tree.command(name="swarm", description="Misi swarm multi-agen", guild=_guild)
    async def _slash_swarm(interaction, tugas: str):
        if not await _owner_only(interaction):
            return
        await interaction.response.defer(thinking=True)
        await interaction.followup.send(f"⚡ Misi swarm dimulai: _{tugas[:150]}_")
        steps, final = await _run_swarm(tugas)
        for part in _split(steps + "\n\n" + final)[:5]:
            await interaction.followup.send(part)

    @tree.command(name="misi", description="Riwayat & status misi swarm", guild=_guild)
    async def _slash_misi(interaction):
        import glob as _g
        import json as _j
        import os as _o

        from alfa.swarm.checkpoint import CHECKPOINT_DIR

        rows = []
        try:
            files = sorted(_g.glob(_o.path.join(CHECKPOINT_DIR, "*.json")), key=_o.path.getmtime, reverse=True)[:5]
            for fp in files:
                try:
                    st = _j.load(open(fp, encoding="utf-8"))
                    icon = {"completed": "✅", "cancelled": "⏹️", "running": "⚙️"}.get(st.get("status"), "⏸️")
                    rows.append(
                        f"{icon} `{st.get('session_id', '?')[:18]}` {st.get('status')} "
                        f"({st.get('steps_done', 0)}/{st.get('steps_total', '?')}) — {(st.get('topic') or '')[:60]}"
                    )
                except Exception:
                    pass
        except Exception:
            pass
        await interaction.response.send_message(
            ("📋 **Misi Swarm Terakhir:**\n" + "\n".join(rows) if rows else "📋 Belum ada misi tercatat.")[:1900]
        )

    @tree.command(name="gabung", description="Bot join VC + mode Jarvis dengar-jawab", guild=_guild)
    async def _slash_gabung(interaction):
        if interaction.user.id not in _owner_ids():
            try:
                await interaction.response.send_message("🔒 Khusus owner.", ephemeral=True)
            except Exception:
                pass
            return
        try:
            vs = getattr(interaction.user, "voice", None)
            if not vs or not vs.channel:
                await interaction.response.send_message("❌ Masuk dulu ke voice channel.", ephemeral=True)
                return
            await interaction.response.defer(thinking=True)
            vc = interaction.guild.voice_client if interaction.guild else None
            if not vc or not vc.is_connected():
                vc = await vs.channel.connect()
            _VC_LISTEN[interaction.guild.id] = True
            await interaction.followup.send("🤖 **Mode Jarvis ON** — bicara, saya jawab suara. `!leave` berhenti.")
            client.loop.create_task(_vc_listen_loop(vc, interaction.channel, interaction.guild.id, _tg_owner_uid()))
        except Exception as e:
            try:
                await interaction.followup.send(f"❌ Join gagal: {str(e)[:150]}")
            except Exception:
                pass

    @tree.command(name="situs", description="Galeri situs hasil kerja agent", guild=_guild)
    async def _slash_situs(interaction):
        from alfa.tools import serve_site

        rows = serve_site(action="status").get("sites", []) or []
        lines = ["🌐 **Galeri Situs:**"] + [
            f"{'🟢' if (s.get('backend_on') or s.get('frontend_on')) else '⚪'} **{s.get('title', s.get('slug'))}**"
            for s in rows
        ]
        await interaction.response.send_message("\n".join(lines)[:1900])
    tg_uid = _tg_owner_uid()

    @client.event
    async def on_ready():
        global _DC_LOOP
        try:
            synced = await tree.sync(guild=_guild)
            logger.warning(f"[discord] {len(synced)} slash command tersinkron.")
        except Exception as e:
            logger.error(f"[discord] sync slash gagal: {e}")
        try:
            _DC_LOOP = asyncio.get_running_loop()
        except RuntimeError:
            pass
        logger.warning(f"[discord] login sebagai {client.user} — mirror + chat aktif.")
        try:
            await client.change_presence(
                activity=__import__("discord").Activity(
                    type=__import__("discord").ActivityType.watching, name="WA & swarm"
                )
            )
        except Exception:
            pass
        client.loop.create_task(_mirror_loop(client))
        client.loop.create_task(_digest_loop(client))

    @client.event
    async def on_message(msg):
        try:
            if msg.author.bot or (client.user and msg.author.id == client.user.id):
                return
            is_owner = msg.author.id in _owner_ids()
            text = (msg.content or "").strip()
            if not text:
                return
            try:
                _DISCORD_CMD_CTX["guild_id"] = msg.guild.id if msg.guild else 0
                vs = getattr(msg.author, "voice", None)
                _DISCORD_CMD_CTX["voice_channel_id"] = vs.channel.id if vs and vs.channel else 0
            except Exception:
                pass
            low = text.lower()
            owner_only = {"!swarm", "!serve", "!stop", "!ss", "!cam", "!join",
                          "!leave", "!budget", "!waringkas", "!sites"}
            first_word = low.split(None, 1)[0] if low else ""
            if not is_owner and first_word in owner_only:
                await msg.reply("🔒 Perintah khusus owner — yang lain cukup ngobrol / `!play` / `!help`.")
                return
            async with msg.channel.typing():
                if low.startswith("!swarm"):
                    topic = text[6:].strip()
                    if not topic:
                        await msg.reply("Usage: `!swarm <tugas>` atau `!swarm template [nama]`")
                        return
                    if topic.lower() in ("cancel", "stop", "batal"):
                        try:
                            from alfa.swarm.workspace_hygiene import (
                                request_cancel_swarm,
                            )

                            ok = request_cancel_swarm()
                            await msg.reply("⏹️ Permintaan henti dikirim." if ok else "ℹ️ Tidak ada misi berjalan.")
                        except Exception:
                            await msg.reply("ℹ️ Tidak ada misi berjalan.")
                        return
                    if topic.lower().startswith("template"):
                        from alfa.bot.mode_commands import SWARM_TEMPLATES

                        rest = topic[8:].strip()
                        if not rest:
                            rows = [f"• `{n}`" for n in SWARM_TEMPLATES]
                            await msg.reply("📦 **Templat:**\n" + "\n".join(rows) + "\n\n`!swarm template <nama>`")
                            return
                        tpl = SWARM_TEMPLATES.get(rest.lower())
                        if not tpl:
                            await msg.reply("❌ Templat tidak ada.")
                            return
                        topic = tpl
                    await msg.reply(f"⚡ Misi swarm dimulai: _{topic[:150]}_")
                    try:
                        await client.change_presence(
                            activity=__import__("discord").Activity(
                                type=__import__("discord").ActivityType.playing,
                                name="misi swarm berjalan",
                            )
                        )
                    except Exception:
                        pass
                    steps, final = await _run_swarm(topic)
                    try:
                        await client.change_presence(
                            activity=__import__("discord").Activity(
                                type=__import__("discord").ActivityType.watching, name="WA & swarm"
                            )
                        )
                    except Exception:
                        pass
                    for part in _split(steps)[:4]:
                        await msg.channel.send(part)
                    for part in _split(final)[:4]:
                        await msg.channel.send(part)
                elif low.startswith("!sites"):
                    from alfa.tools import serve_site

                    site_res: dict[str, Any] = serve_site(action="status")
                    site_rows: list[dict[str, Any]] = site_res.get("sites") or []
                    lines = ["🌐 **Galeri Situs:**"]
                    for s in site_rows:
                        dot = "🟢" if (s.get("backend_on") or s.get("frontend_on")) else "⚪"
                        lines.append(f"{dot} **{s.get('title', s.get('slug'))}** (`{s.get('slug')}`)")
                    lines.append("\nHidupkan: `!serve <slug>`")
                    await msg.reply("\n".join(lines)[:1900])
                elif low.startswith("!serve"):
                    from alfa.tools import serve_site

                    args = text[6:].strip().split(None, 1)
                    slug = args[0] if args else ""
                    if not slug:
                        res = {"status": "error", "message": "Usage: `!serve <slug>` / `!stop <slug>`"}
                    else:
                        res = serve_site(action="start", slug=slug)
                    await msg.reply(str(json.dumps(res, ensure_ascii=False))[:1900])
                elif low.startswith("!stop"):
                    from alfa.tools import serve_site

                    slug = text[5:].strip()
                    res = serve_site(action="stop", slug=slug) if slug else {"status": "error", "message": "Usage: `!stop <slug>`"}
                    await msg.reply(str(json.dumps(res, ensure_ascii=False))[:1900])
                elif low.startswith("!budget"):
                    from alfa.core.rate_limiter import get_budget_report

                    rep = get_budget_report()
                    if rep.get("status") == "ok":
                        await msg.reply(
                            f"💰 Kuota: **{rep['total_tokens']:,}**/{rep['budget_limit']:,} "
                            f"({rep['pct'] * 100:.0f}%) • sisa {rep['remaining']:,}"
                        )
                    else:
                        await msg.reply("❓ Data kuota belum tersedia.")
                elif low.startswith("!waringkas"):
                    from alfa.bot.wa_digest import build_digest_text

                    fmt = text[9:].strip()
                    await msg.reply((await build_digest_text(fmt))[:1900])
                elif low.startswith("!ss"):
                    await msg.reply("📸 Menangkap layar...")
                    try:
                        from alfa.tools.desktop.capture import (
                            capture_desktop_screenshot,
                        )

                        res = await asyncio.to_thread(capture_desktop_screenshot)
                        fp = (res or {}).get("file_path", "")
                        if res.get("status") == "success" and fp and os.path.isfile(fp):
                            await msg.reply("🖥️ **Layar laptop saat ini:**", file=__import__("discord").File(fp))
                        else:
                            await msg.reply(f"❌ Screenshot gagal: {(res or {}).get('message', '?')}")
                    except Exception as e:
                        await msg.reply(f"❌ Screenshot gagal: {e}")
                elif low.startswith("!cam"):
                    await msg.reply("📷 Mengambil frame webcam...")
                    try:
                        from alfa.tools.desktop.capture import capture_webcam_frame

                        res = await asyncio.to_thread(capture_webcam_frame)
                        fp = (res or {}).get("file_path", "") or (res or {}).get("path", "")
                        if fp and os.path.isfile(fp):
                            await msg.reply("📷 **Webcam saat ini:**", file=__import__("discord").File(fp))
                        else:
                            await msg.reply(f"❌ Webcam gagal: {(res or {}).get('message', '?')}")
                    except Exception as e:
                        await msg.reply(f"❌ Webcam gagal: {e}")
                elif low.startswith("!play"):
                    query = text[5:].strip()
                    if not query:
                        await msg.reply("Usage: `!play <judul/lagu>` (kamu harus di voice channel)")
                        return
                    voice_state = getattr(msg.author, "voice", None)
                    if not voice_state or not voice_state.channel:
                        await msg.reply("❌ Masuk dulu ke voice channel, baru `!play`.")
                        return
                    gid = msg.guild.id if msg.guild else 0
                    lock = _play_lock(gid)
                    if lock.locked():
                        await msg.reply("⏳ Masih memproses lagu sebelumnya — tunggu sebentar.")
                        return
                    async with lock:
                        await msg.reply(f"🎵 Mencari & memutar: _{query[:100]}_")
                        await _discord_play(msg, query)
                    return
                elif low.startswith("!stopvc"):
                    try:
                        vc = msg.guild.voice_client if msg.guild else None
                        if vc and vc.is_connected():
                            await vc.disconnect(force=True)
                            await msg.reply("⏹️ Keluar dari voice channel.")
                        else:
                            await msg.reply("ℹ️ Tidak sedang di voice channel.")
                    except Exception as e:
                        await msg.reply(f"❌ {e}")
                elif low.startswith("!join"):
                    vs = getattr(msg.author, "voice", None)
                    if not vs or not vs.channel:
                        await msg.reply("❌ Masuk dulu ke voice channel.")
                        return
                    try:
                        import discord as _dc2

                        try:
                            _dc2.opus.load_opus("libopus.so.0")
                        except Exception:
                            pass
                        vc = msg.guild.voice_client
                        if not vc or not vc.is_connected():
                            vc = await vs.channel.connect()
                        gid = msg.guild.id
                        if _VC_LISTEN.get(gid):
                            await msg.reply("ℹ️ Mode Jarvis sudah jalan. `!leave` untuk berhenti.")
                            return
                        _VC_LISTEN[gid] = True
                        await msg.reply("🤖 **Mode Jarvis ON** — bicara, saya dengar 8 detik lalu jawab suara. `!leave` berhenti.")
                        client.loop.create_task(_vc_listen_loop(vc, msg.channel, gid, _tg_owner_uid()))
                    except Exception as e:
                        await msg.reply(f"❌ Join gagal: {str(e)[:200]}")
                elif low.startswith("!leave"):
                    gid = msg.guild.id if msg.guild else 0
                    _VC_LISTEN[gid] = False
                    try:
                        vc = msg.guild.voice_client if msg.guild else None
                        if vc and vc.is_connected():
                            try:
                                vc.stop_recording()
                            except Exception:
                                pass
                            await vc.disconnect(force=True)
                    except Exception:
                        pass
                    await msg.reply("👋 Mode Jarvis OFF, keluar VC.")
                elif low.startswith("!help") or low.startswith("!menu"):
                    await msg.reply(
                        "**ALFA Discord bridge:**\n"
                        "• chat biasa → agen (memori bersama Telegram)\n"
                        "• `!swarm <tugas>` → misi multi-agen (template/cancel juga bisa)\n"
                        "• `!sites` / `!serve <slug>` → galeri & hidupkan situs\n"
                        "• `!budget` → kuota • `!waringkas [format]` → digest WA\n"
                        "• `!ss` → screenshot layar • `!cam` → foto webcam\n"
                        "• `!play <lagu>` → putar YouTube di VC • `!stopvc` → keluar VC\n"
                        "• `!join` → mode Jarvis (dengar+jawab suara) • `!leave` → berhenti"
                    )
                else:
                    if msg.guild is None or client.user in msg.mentions:
                        reply = await _run_single(
                            "[Obrolan Discord — JANGAN panggil play_youtube_music/open_url_in_system_browser/"
                            "desktop_launch_app (dilarang putar di host/Brave); untuk musik arahkan user pakai !play. "
                            "GAYA BICARA: santai-gaul kayak teman nongkrong (gue-lo), pendek (maks ~4 baris kecuali "
                            "diminta panjang), tanpa bullet formal, tanpa sapaan robot, tanpa emoji hujan. "
                            "Tetap jujur: dilarang karang fakta.] "
                            + text,
                            tg_uid,
                        )
                        for part in _split(reply)[:4]:
                            await msg.reply(part)
        except Exception as e:
            logger.error(f"[discord] on_message gagal: {e}")

    client.run(token, log_handler=None)


async def _digest_loop(cli) -> None:
    """Digest WA cerdas harian ke Discord (07:00 WIB, sama seperti Telegram)."""
    import datetime as _dt

    from alfa.bot.wa_digest import _set_setting as _dset
    from alfa.bot.wa_digest import _setting as _dget
    from alfa.bot.wa_digest import build_digest_text, digest_enabled, digest_hours

    await cli.wait_until_ready()
    while True:
        try:
            if digest_enabled():
                now = _dt.datetime.now()
                if now.strftime("%H:%M") in digest_hours() and _dget("wa_digest_discord_date", "") != now.strftime("%Y-%m-%d"):
                    try:
                        chan = await cli.fetch_channel(_channel_id())
                        text = await build_digest_text()
                        for part in _split(text)[:4]:
                            await chan.send(part)
                            await asyncio.sleep(1)
                        _dset("wa_digest_discord_date", now.strftime("%Y-%m-%d"))
                        logger.warning("[discord] digest harian terkirim")
                    except Exception as e:
                        logger.debug(f"[discord] digest gagal: {e}")
        except Exception as e:
            logger.error(f"[discord] digest loop error: {e}")
        await asyncio.sleep(60)

async def _mirror_loop(cli):
    await cli.wait_until_ready()
    try:
        chan = await cli.fetch_channel(_channel_id())
    except Exception as e:
        logger.error(f"[discord] channel mirror tak bisa dibuka: {e}")
        return
    pos = os.path.getsize(FEED_FILE) if os.path.isfile(FEED_FILE) else 0
    while True:
        try:
            if _setting("discord_mirror", "1") == "1" and os.path.isfile(FEED_FILE):
                size = os.path.getsize(FEED_FILE)
                if size < pos:
                    pos = 0
                if size > pos:
                    with open(FEED_FILE, errors="ignore") as f:
                        f.seek(pos)
                        chunk = f.read()
                    pos = size
                    lines = [ln for ln in chunk.splitlines() if ln.strip()][-6:]
                    for ln in lines:
                        try:
                            d = json.loads(ln)
                            tag, text = d.get("tag", "?"), d.get("text", "")[:1200]
                        except Exception:
                            tag, text = "LOG", ln[:1200]
                        if tag in ("PLAN", "EXEC", "VERIFY", "DONE", "CANCEL", "TIMEOUT", "QA", "FILE", "HARVEST"):
                            for part in _split(f"**[{tag}]** {text}"):
                                await chan.send(part)
                                await asyncio.sleep(1)
        except Exception as e:
            logger.debug(f"[discord] mirror dilewati: {e}")
        await asyncio.sleep(15)



if __name__ == "__main__":
    main()
