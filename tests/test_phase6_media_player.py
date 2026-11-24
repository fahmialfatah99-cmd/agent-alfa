"""Phase 6 coverage: player musik YouTube (resolve, cache, pipeline, play_youtube_music).

Hermetic: yt-dlp/ffplay/subprocess di-mock, cache diarahkan ke ``tmp_path``,
tidak ada proses audio atau proses nyata yang dijalankan.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
from types import SimpleNamespace

import pytest


@pytest.fixture
def player(monkeypatch):
    from alfa.tools.media import player as mod

    monkeypatch.setattr(mod, "_HOST_PLAY_BLOCKED", False)
    monkeypatch.setattr(mod, "_AUDIO_PROC", None)
    return mod


def _cp(stdout="", stderr="", rc=0):
    return subprocess.CompletedProcess(
        args=[], returncode=rc, stdout=stdout, stderr=stderr
    )


def _info(**over):
    base = {
        "ok": True,
        "id": "vid123",
        "title": "Lagu Uji",
        "duration": 125,
        "uploader": "Penyanyi Uji",
        "url": "https://www.youtube.com/watch?v=vid123",
        "watch_url": "https://www.youtube.com/watch?v=vid123",
    }
    base.update(over)
    return base


# ---------------------------------------------------------------------------
# Helper kecil: which / client args / run_ytdlp / watch_url
# ---------------------------------------------------------------------------


def test_set_host_play_blocked_toggle(player):
    player.set_host_play_blocked(True)
    assert player._HOST_PLAY_BLOCKED is True
    player.set_host_play_blocked(False)
    assert player._HOST_PLAY_BLOCKED is False
    player.set_host_play_blocked()  # default: aktif
    assert player._HOST_PLAY_BLOCKED is True


def test_which_first_match(player, monkeypatch):
    monkeypatch.setattr(
        player.shutil, "which", lambda n: "/usr/bin/yt-dlp" if n == "yt-dlp" else None
    )
    assert player._which(["yt-dlp", "ffplay"]) == "/usr/bin/yt-dlp"
    assert player._which(["ffplay"]) is None
    assert player._ytdlp() == "/usr/bin/yt-dlp"


def test_client_args_respects_env_default(player, monkeypatch):
    monkeypatch.setattr(player, "_PLAYER_CLIENT", "android")
    assert player._client_args() == [
        "--extractor-args",
        "youtube:player_client=android",
    ]
    monkeypatch.setattr(player, "_PLAYER_CLIENT", "")
    assert player._client_args() == []


def test_watch_url_autoplay_flag(player):
    assert player._watch_url("abc123") == "https://www.youtube.com/watch?v=abc123"
    assert (
        player._watch_url("abc123", autoplay=True)
        == "https://www.youtube.com/watch?v=abc123&autoplay=1"
    )


def test_run_ytdlp_client_then_fallback(player, monkeypatch):
    monkeypatch.setattr(player, "_ytdlp", lambda: "/usr/bin/yt-dlp")
    monkeypatch.setattr(
        player,
        "_client_args",
        lambda: ["--extractor-args", "youtube:player_client=android"],
    )
    calls: list[list] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if "--extractor-args" in cmd:
            return _cp(rc=1, stderr="403 forbidden")
        return _cp(stdout='{"id": "x"}')

    monkeypatch.setattr(player.subprocess, "run", fake_run)
    res = player._run_ytdlp(["-J", "url"], 30)
    assert res.returncode == 0
    assert len(calls) == 2
    assert calls[0][0] == "/usr/bin/yt-dlp"
    assert calls[1] == ["/usr/bin/yt-dlp", "-J", "url"]


def test_run_ytdlp_first_attempt_wins_when_stdout_present(player, monkeypatch):
    monkeypatch.setattr(player, "_ytdlp", lambda: "/usr/bin/yt-dlp")
    monkeypatch.setattr(player, "_client_args", lambda: [])
    calls: list[list] = []
    monkeypatch.setattr(
        player.subprocess,
        "run",
        lambda cmd, **kw: calls.append(cmd) or _cp(stdout="data"),
    )
    res = player._run_ytdlp(["-J"], 10)
    assert res.stdout == "data"
    assert len(calls) == 1
    assert calls[0] == ["/usr/bin/yt-dlp", "-J"]


def test_run_ytdlp_empty_stdout_keeps_last_attempt(player, monkeypatch):
    monkeypatch.setattr(player, "_ytdlp", lambda: None)
    monkeypatch.setattr(player, "_client_args", lambda: [])
    calls: list[list] = []
    monkeypatch.setattr(
        player.subprocess,
        "run",
        lambda cmd, **kw: calls.append(cmd) or _cp(stdout="   "),
    )
    res = player._run_ytdlp(["-J"], 10)
    assert res.stdout.strip() == ""
    # _ytdlp() None -> nama bin dipakai apa adanya.
    assert calls == [["yt-dlp", "-J"]]


def test_run_ytdlp_timeout(player, monkeypatch):
    monkeypatch.setattr(player, "_ytdlp", lambda: "/usr/bin/yt-dlp")
    monkeypatch.setattr(player, "_client_args", lambda: [])

    def boom(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=10)

    monkeypatch.setattr(player.subprocess, "run", boom)
    res = player._run_ytdlp(["-J"], 10)
    assert res.returncode == 124
    assert res.stderr.startswith("timeout:")


def test_run_ytdlp_spawn_error(player, monkeypatch):
    monkeypatch.setattr(player, "_ytdlp", lambda: "/usr/bin/yt-dlp")
    monkeypatch.setattr(player, "_client_args", lambda: [])

    def boom(cmd, **kwargs):
        raise OSError("yt-dlp hilang")  # noqa: TRY003

    monkeypatch.setattr(player.subprocess, "run", boom)
    res = player._run_ytdlp(["-J"], 10)
    assert res.returncode == 1
    assert res.stdout == ""
    assert res.stderr == "yt-dlp hilang"


# ---------------------------------------------------------------------------
# _resolve
# ---------------------------------------------------------------------------


def _patch_ytdlp_ok(monkeypatch, player, payload):
    monkeypatch.setattr(player, "_ytdlp", lambda: "/usr/bin/yt-dlp")
    monkeypatch.setattr(
        player, "_run_ytdlp", lambda args, timeout: _cp(stdout=json.dumps(payload))
    )


def test_resolve_empty_query(player):
    assert player._resolve("   ") == {"ok": False, "error": "Query lagu kosong."}


def test_resolve_without_ytdlp(player, monkeypatch):
    monkeypatch.setattr(player, "_ytdlp", lambda: None)
    out = player._resolve("lagu")
    assert out["ok"] is False
    assert "tidak terpasang" in out["error"]


@pytest.mark.parametrize(
    ("query", "target"),
    [
        ("https://youtu.be/abc123def", "https://www.youtube.com/watch?v=abc123def"),
        (
            "https://youtube.com/watch?v=xyz789abc",
            "https://www.youtube.com/watch?v=xyz789abc",
        ),
        (
            "https://www.youtube.com/shorts/short1234",
            "https://www.youtube.com/watch?v=short1234",
        ),
        ("https://vimeo.com/998877", "https://vimeo.com/998877"),
        ("bohemian rhapsody queen", "ytsearch1:bohemian rhapsody queen"),
    ],
)
def test_resolve_target_selection(player, monkeypatch, query, target):
    seen: dict[str, str] = {}

    def fake_run(args, timeout):
        seen["target"] = args[-1]
        return _cp(stdout=json.dumps({"id": "v1", "title": "T"}))

    monkeypatch.setattr(player, "_ytdlp", lambda: "/usr/bin/yt-dlp")
    monkeypatch.setattr(player, "_run_ytdlp", fake_run)
    out = player._resolve(query)
    assert out["ok"] is True
    assert seen["target"] == target


def test_resolve_run_raises(player, monkeypatch):
    monkeypatch.setattr(player, "_ytdlp", lambda: "/usr/bin/yt-dlp")

    def boom(args, timeout):
        raise RuntimeError("gagal spawn")  # noqa: TRY003

    monkeypatch.setattr(player, "_run_ytdlp", boom)
    out = player._resolve("lagu")
    assert out["ok"] is False
    assert "gagal dijalankan" in out["error"]


def test_resolve_nonzero_output(player, monkeypatch):
    monkeypatch.setattr(player, "_ytdlp", lambda: "/usr/bin/yt-dlp")
    monkeypatch.setattr(
        player, "_run_ytdlp", lambda a, t: _cp(rc=1, stderr="ERROR: tidak ada")
    )
    out = player._resolve("lagu")
    assert out["ok"] is False
    assert "ERROR: tidak ada" in out["error"]

    monkeypatch.setattr(player, "_run_ytdlp", lambda a, t: _cp(rc=1, stderr=""))
    out = player._resolve("lagu")
    assert "tanpa output" in out["error"]


def test_resolve_invalid_json(player, monkeypatch):
    _patch_ytdlp_ok(monkeypatch, player, {})
    monkeypatch.setattr(player, "_run_ytdlp", lambda a, t: _cp(stdout="bukan json"))
    out = player._resolve("lagu")
    assert out["ok"] is False
    assert "bukan JSON valid" in out["error"]


def test_resolve_entries_skips_none(player, monkeypatch):
    _patch_ytdlp_ok(
        monkeypatch,
        player,
        {
            "entries": [
                None,
                {
                    "id": "ketemu1",
                    "title": "  Judul Bersih  ",
                    "duration": 10,
                    "channel": "Kanal",
                },
            ]
        },
    )
    out = player._resolve("lagu")
    assert out["ok"] is True
    assert out["id"] == "ketemu1"
    assert out["title"] == "Judul Bersih"
    assert out["uploader"] == "Kanal"
    assert out["url"] == "https://www.youtube.com/watch?v=ketemu1"


def test_resolve_flat_dict_with_webpage_url(player, monkeypatch):
    _patch_ytdlp_ok(
        monkeypatch,
        player,
        {
            "id": "flat1",
            "title": "",
            "duration": None,
            "uploader": "Solo",
            "webpage_url": "https://www.youtube.com/watch?v=flat1",
        },
    )
    out = player._resolve("lagu")
    assert out["ok"] is True
    assert out["title"] == "Tanpa judul"
    assert out["duration"] is None
    assert out["url"] == "https://www.youtube.com/watch?v=flat1"
    assert out["watch_url"] == "https://www.youtube.com/watch?v=flat1"


@pytest.mark.parametrize("payload", [{}, {"entries": []}, {"entries": [None]}])
def test_resolve_no_entry(player, monkeypatch, payload):
    _patch_ytdlp_ok(monkeypatch, player, payload)
    out = player._resolve("lagu")
    assert out["ok"] is False
    assert "Tidak ada hasil video" in out["error"]


# ---------------------------------------------------------------------------
# Cache & download
# ---------------------------------------------------------------------------


def test_cache_dir_success_and_fallback(player, monkeypatch, tmp_path):
    class _PathProxy:
        def __init__(self, base):
            self._base = str(base)

        def expanduser(self, path):
            return self._base

        def __getattr__(self, name):
            return getattr(os.path, name)

    class CacheOs:
        def __init__(self, base, fail=False):
            self.path = _PathProxy(base)
            self._fail = fail

        def __getattr__(self, name):
            return getattr(os, name)

        def makedirs(self, *args, **kwargs):
            if self._fail:
                raise OSError("read-only")  # noqa: TRY003
            return os.makedirs(*args, **kwargs)

    monkeypatch.setattr(player, "os", CacheOs(tmp_path))
    out = player._cache_dir()
    assert out == str(tmp_path / ".alfa" / "cache" / "music")
    assert os.path.isdir(out)

    monkeypatch.setattr(player, "os", CacheOs(tmp_path, fail=True))
    assert player._cache_dir() == "/tmp"


def test_cached_track_prefers_first_existing_ext(player, monkeypatch, tmp_path):
    monkeypatch.setattr(player, "_cache_dir", lambda: str(tmp_path))
    (tmp_path / "vid1.opus").write_bytes(b"x" * 4096)
    (tmp_path / "vid1.webm").write_bytes(b"y" * 4096)
    assert player._cached_track("vid1") == str(tmp_path / "vid1.opus")

    (tmp_path / "vid2.mp3").write_bytes(b"z" * 10)
    assert player._cached_track("vid2") is None
    assert player._cached_track("vid3") is None


def test_download_track_without_ytdlp(player, monkeypatch):
    monkeypatch.setattr(player, "_ytdlp", lambda: None)
    assert player._download_track("v", "url") == (None, "yt-dlp tidak tersedia.")


def test_download_track_checks_cache_after_run(player, monkeypatch, tmp_path):
    monkeypatch.setattr(player, "_ytdlp", lambda: "/usr/bin/yt-dlp")
    monkeypatch.setattr(player, "_cache_dir", lambda: str(tmp_path))
    calls: list[list] = []
    monkeypatch.setattr(
        player,
        "_run_ytdlp",
        lambda a, t: calls.append(a) or _cp(rc=1, stderr="sudah diunduh"),
    )
    monkeypatch.setattr(
        player, "_cached_track", lambda vid: str(tmp_path / f"{vid}.opus")
    )
    path, err = player._download_track("v1", "https://watch")
    assert path == str(tmp_path / "v1.opus")
    assert err == ""
    assert calls[0][0] == "--no-warnings"
    assert calls[0][-1] == "https://watch"
    assert any("--socket-timeout" in a for a in calls[0])


@pytest.mark.parametrize(
    ("stderr", "expected"),
    [
        ("ERROR: video unavailable", "ERROR: video unavailable"),
        ("", "Unduhan audio gagal."),
        ("e" * 500, "e" * 300),
    ],
)
def test_download_track_failure_messages(player, monkeypatch, tmp_path, stderr, expected):
    monkeypatch.setattr(player, "_ytdlp", lambda: "/usr/bin/yt-dlp")
    monkeypatch.setattr(player, "_cache_dir", lambda: str(tmp_path))
    monkeypatch.setattr(player, "_cached_track", lambda vid: None)
    monkeypatch.setattr(player, "_run_ytdlp", lambda a, t: _cp(rc=1, stderr=stderr))
    path, err = player._download_track("v1", "url")
    assert path is None
    assert err == expected


# ---------------------------------------------------------------------------
# ffplay / kill / stop
# ---------------------------------------------------------------------------


def test_start_ffplay_variants(player, monkeypatch):
    monkeypatch.setattr(player, "_which", lambda names: None)
    assert player._start_ffplay("/tmp/a.opus") is None

    monkeypatch.setattr(player, "_which", lambda names: "/usr/bin/ffplay")
    sentinel = object()
    monkeypatch.setattr(player.subprocess, "Popen", lambda cmd, **kw: sentinel)
    assert player._start_ffplay("/tmp/a.opus") is sentinel

    def boom(cmd, **kwargs):
        raise OSError("display mati")  # noqa: TRY003

    monkeypatch.setattr(player.subprocess, "Popen", boom)
    assert player._start_ffplay("/tmp/a.opus") is None


def test_kill_group_variants(player, monkeypatch):
    assert player._kill_group(None) is False

    killed: list[tuple] = []

    class Alive:
        pid = 777

        def poll(self):
            return None

    monkeypatch.setattr(
        player,
        "os",
        SimpleNamespace(
            killpg=lambda pgid, sig: killed.append((pgid, sig)),
            getpgid=lambda pid: 42,
        ),
    )
    assert player._kill_group(Alive()) is True
    assert killed == [(42, 15)]

    class Dead:
        pid = 1

        def poll(self):
            return 0

    assert player._kill_group(Dead()) is False


def test_kill_group_falls_back_to_terminate(player, monkeypatch):
    class Proc:
        pid = 5

        def poll(self):
            return None

        def terminate(self):
            self.terminated = True

    def failing_killpg(pgid, sig):
        raise OSError("no pg")  # noqa: TRY003

    monkeypatch.setattr(
        player,
        "os",
        SimpleNamespace(killpg=failing_killpg, getpgid=lambda pid: 1),
    )
    proc = Proc()
    assert player._kill_group(proc) is True
    assert getattr(proc, "terminated", False) is True

    class NoTerminate(Proc):
        def terminate(self):
            raise OSError("sudah mati")  # noqa: TRY003

    assert player._kill_group(NoTerminate()) is False


def test_stop_audio_messages(player, monkeypatch):
    monkeypatch.setattr(player, "_kill_group", lambda proc: True)
    monkeypatch.setattr(player, "_AUDIO_PROC", object())
    monkeypatch.setattr(player.subprocess, "run", lambda *a, **kw: _cp())
    out = player._stop_audio()
    assert out["status"] == "success"
    assert "dihentikan" in out["message"]
    assert player._AUDIO_PROC is None

    monkeypatch.setattr(player, "_kill_group", lambda proc: False)
    out = player._stop_audio()
    assert "Tidak ada pemutaran" in out["message"]


def test_stop_audio_pkill_failure_logged(player, monkeypatch):
    monkeypatch.setattr(player, "_kill_group", lambda proc: False)
    monkeypatch.setattr(player, "_AUDIO_PROC", None)

    def boom(cmd, **kwargs):
        raise OSError("pkill hilang")  # noqa: TRY003

    monkeypatch.setattr(player.subprocess, "run", boom)
    out = player._stop_audio()
    assert out["status"] == "success"
    assert "Tidak ada pemutaran" in out["message"]


# ---------------------------------------------------------------------------
# Streaming & file playback
# ---------------------------------------------------------------------------


class PipeProc:
    def __init__(self, rc=None, err=b""):
        self.pid = 555
        self._rc = rc
        self.stderr = io.BytesIO(err)

    def poll(self):
        return self._rc


def test_streaming_missing_tools(player, monkeypatch):
    monkeypatch.setattr(player, "_ytdlp", lambda: None)
    assert player._play_audio_streaming("url")[:2] == (
        False,
        "yt-dlp tidak tersedia.",
    )

    monkeypatch.setattr(player, "_ytdlp", lambda: "/usr/bin/yt-dlp")
    monkeypatch.setattr(player, "_which", lambda names: None)
    assert player._play_audio_streaming("url")[:2] == (
        False,
        "ffplay (ffmpeg) tidak terpasang di sistem.",
    )


def test_streaming_success_pipeline(player, monkeypatch):
    monkeypatch.setattr(player, "_ytdlp", lambda: "/usr/bin/yt-dlp")
    monkeypatch.setattr(player, "_which", lambda n: "/usr/bin/ffplay")
    monkeypatch.setattr(player, "_PLAYER_CLIENT", "android")
    monkeypatch.setattr("time.sleep", lambda s: None)
    pipelines: list[str] = []

    monkeypatch.setattr(
        player.subprocess,
        "Popen",
        lambda cmd, **kw: pipelines.append(cmd) or PipeProc(rc=None),
    )
    ok, detail, pid = player._play_audio_streaming("https://www.youtube.com/watch?v=v1")
    assert ok is True and pid == "555"
    assert '"/usr/bin/yt-dlp"' in pipelines[0]
    assert "--extractor-args" in pipelines[0]
    assert '"/usr/bin/ffplay"' in pipelines[0]
    assert "watch?v=v1" in pipelines[0]
    assert player._AUDIO_PROC is not None


def test_streaming_dies_immediately(player, monkeypatch):
    monkeypatch.setattr(player, "_ytdlp", lambda: "/usr/bin/yt-dlp")
    monkeypatch.setattr(player, "_which", lambda n: "/usr/bin/ffplay")
    monkeypatch.setattr("time.sleep", lambda s: None)
    monkeypatch.setattr(
        player.subprocess,
        "Popen",
        lambda cmd, **kw: PipeProc(rc=1, err=b"error 403 forbidden"),
    )
    ok, detail, pid = player._play_audio_streaming("url")
    assert ok is False
    assert "error 403 forbidden" in detail
    assert player._AUDIO_PROC is None


def test_streaming_dies_without_stderr(player, monkeypatch):
    monkeypatch.setattr(player, "_ytdlp", lambda: "/usr/bin/yt-dlp")
    monkeypatch.setattr(player, "_which", lambda n: "/usr/bin/ffplay")
    monkeypatch.setattr("time.sleep", lambda s: None)
    monkeypatch.setattr(
        player.subprocess,
        "Popen",
        lambda cmd, **kw: PipeProc(rc=0, err=b""),
    )
    ok, detail, pid = player._play_audio_streaming("url")
    assert ok is False
    assert detail == "Pipeline audio berhenti segera."


def test_streaming_stderr_read_failure(player, monkeypatch):
    class BadErr(PipeProc):
        def __init__(self):
            self.pid = 555
            self._rc = 1

        @property
        def stderr(self):
            raise OSError("pipe tertutup")  # noqa: TRY003

    monkeypatch.setattr(player, "_ytdlp", lambda: "/usr/bin/yt-dlp")
    monkeypatch.setattr(player, "_which", lambda n: "/usr/bin/ffplay")
    monkeypatch.setattr("time.sleep", lambda s: None)
    monkeypatch.setattr(player.subprocess, "Popen", lambda cmd, **kw: BadErr())
    ok, detail, pid = player._play_audio_streaming("url")
    assert ok is False
    assert detail == "Pipeline audio berhenti segera."


def test_streaming_spawn_error(player, monkeypatch):
    monkeypatch.setattr(player, "_ytdlp", lambda: "/usr/bin/yt-dlp")
    monkeypatch.setattr(player, "_which", lambda n: "/usr/bin/ffplay")

    def boom(cmd, **kwargs):
        raise RuntimeError("shell mati")  # noqa: TRY003

    monkeypatch.setattr(player.subprocess, "Popen", boom)
    ok, detail, pid = player._play_audio_streaming("url")
    assert ok is False
    assert "Gagal menjalankan pipeline audio" in detail
    assert "shell mati" in detail


def test_play_audio_file_variants(player, monkeypatch):
    monkeypatch.setattr(player, "_kill_group", lambda p: False)
    monkeypatch.setattr("time.sleep", lambda s: None)

    monkeypatch.setattr(player, "_start_ffplay", lambda p: None)
    ok, detail, pid = player._play_audio_file("/tmp/a.opus")
    assert ok is False
    assert "ffplay (ffmpeg) tidak terpasang" in detail

    monkeypatch.setattr(player, "_start_ffplay", lambda p: PipeProc(rc=1))
    ok, detail, pid = player._play_audio_file("/tmp/a.opus")
    assert ok is False
    assert "format/codec tidak didukung" in detail

    monkeypatch.setattr(player, "_start_ffplay", lambda p: PipeProc(rc=None))
    ok, detail, pid = player._play_audio_file("/tmp/musik.opus")
    assert ok is True and pid == "555"
    assert "musik.opus" in detail
    assert player._AUDIO_PROC is not None


# ---------------------------------------------------------------------------
# _start_playback
# ---------------------------------------------------------------------------


def test_start_playback_cache_hit_ok(player, monkeypatch):
    monkeypatch.setattr(player, "_cached_track", lambda vid: "/cache/v.opus")
    monkeypatch.setattr(
        player, "_play_audio_file", lambda p: (True, "dari cache", "1")
    )

    def no_stream(url):
        raise AssertionError("streaming tidak boleh dipanggil")  # noqa: TRY003

    monkeypatch.setattr(player, "_play_audio_streaming", no_stream)
    assert player._start_playback("v", "url") == (True, "dari cache", "1")


def test_start_playback_cache_miss_then_stream(player, monkeypatch):
    monkeypatch.setattr(player, "_cached_track", lambda vid: None)
    monkeypatch.setattr(
        player, "_play_audio_streaming", lambda url: (True, "streaming", "2")
    )
    assert player._start_playback("v", "url") == (True, "streaming", "2")


def test_start_playback_cache_hit_fails_then_stream(player, monkeypatch):
    monkeypatch.setattr(player, "_cached_track", lambda vid: "/cache/v.opus")
    monkeypatch.setattr(player, "_play_audio_file", lambda p: (False, "rusak", ""))
    monkeypatch.setattr(
        player, "_play_audio_streaming", lambda url: (True, "streaming", "3")
    )
    assert player._start_playback("v", "url") == (True, "streaming", "3")


def test_start_playback_download_fallback(player, monkeypatch):
    monkeypatch.setattr(player, "_cached_track", lambda vid: None)
    monkeypatch.setattr(player, "_play_audio_streaming", lambda url: (False, "gagal", ""))
    monkeypatch.setattr(player, "_download_track", lambda vid, url: ("/cache/v.opus", ""))
    monkeypatch.setattr(player, "_play_audio_file", lambda p: (True, "hasil unduh", "9"))
    assert player._start_playback("v", "url") == (True, "hasil unduh", "9")


def test_start_playback_all_fail(player, monkeypatch):
    monkeypatch.setattr(player, "_cached_track", lambda vid: None)
    monkeypatch.setattr(player, "_play_audio_streaming", lambda url: (False, "stream mati", ""))
    monkeypatch.setattr(
        player, "_download_track", lambda vid, url: (None, "unduhan gagal")
    )
    ok, detail, pid = player._start_playback("v", "url")
    assert ok is False
    assert "stream mati | fallback unduh: unduhan gagal" == detail
    assert pid == ""


# ---------------------------------------------------------------------------
# play_youtube_music
# ---------------------------------------------------------------------------


def test_play_host_blocked(player, monkeypatch):
    monkeypatch.setattr(player, "_HOST_PLAY_BLOCKED", True)
    out = player.play_youtube_music("lagu")
    assert out["status"] == "error"
    assert "DINONAKTIFKAN" in out["message"]


def test_play_stop_mode(player, monkeypatch):
    monkeypatch.setattr(
        player, "_stop_audio", lambda: {"status": "success", "message": "dihentikan"}
    )

    def no_resolve(q):
        raise AssertionError("resolve tidak boleh dipanggil")  # noqa: TRY003

    monkeypatch.setattr(player, "_resolve", no_resolve)
    out = player.play_youtube_music(mode="  STOP ")
    assert out == {"status": "success", "message": "dihentikan"}


def test_play_empty_query(player, monkeypatch):
    out = player.play_youtube_music("   ")
    assert out["status"] == "error"
    assert "Query lagu kosong" in out["message"]


def test_play_resolve_failure(player, monkeypatch):
    monkeypatch.setattr(
        player, "_resolve", lambda q: {"ok": False, "error": "tidak ketemu"}
    )
    out = player.play_youtube_music("lagu")
    assert out["status"] == "error"
    assert out["message"] == "tidak ketemu"
    assert out["query"] == "lagu"


def _patch_browser(monkeypatch, result=None, exc=None):
    from alfa.tools.desktop import input_automation as ia_mod

    if exc is not None:
        def fake(url):
            raise exc

    else:
        def fake(url):
            return result

    monkeypatch.setattr(ia_mod, "open_url_in_default_browser", fake)


def test_play_browser_mode_success(player, monkeypatch):
    monkeypatch.setattr(player, "_resolve", lambda q: _info())
    _patch_browser(monkeypatch, result=(True, "xdg-open https://youtube.com"))

    def no_play(vid, url):
        raise AssertionError(  # noqa: TRY003
            "audio tidak boleh diputar di mode browser"
        )

    monkeypatch.setattr(player, "_start_playback", no_play)
    out = player.play_youtube_music("lagu", mode="browser")
    assert out["status"] == "success"
    assert out["mode"] == "browser"
    assert out["browser"]["opened"] is True
    assert "125s" in out["message"]
    assert "Penyanyi Uji" in out["message"]
    assert out["evidence"]["browser_opened"] is True
    assert out["evidence"]["audio_playing"] is False
    assert "halaman YouTube terbuka" in out["message"]


def test_play_browser_mode_failure(player, monkeypatch):
    monkeypatch.setattr(player, "_resolve", lambda q: _info())
    _patch_browser(monkeypatch, result=(False, "Tidak ada opener browser"))
    out = player.play_youtube_music("lagu", mode="browser")
    assert out["status"] == "error"
    assert "GAGAL membuka halaman" in out["message"]


def test_play_browser_mode_exception(player, monkeypatch):
    monkeypatch.setattr(player, "_resolve", lambda q: _info())
    _patch_browser(monkeypatch, exc=OSError("display :0 tidak ada"))
    out = player.play_youtube_music("lagu", mode="browser")
    assert out["status"] == "error"
    assert out["browser"]["opened"] is False
    assert "display :0 tidak ada" in out["browser"]["mechanism"]
    assert "pembuka browser error" in out["message"]


def test_play_auto_success(player, monkeypatch):
    monkeypatch.setattr(player, "_resolve", lambda q: _info())
    monkeypatch.setattr(
        player, "_start_playback", lambda vid, url: (True, "ok", "1234")
    )
    out = player.play_youtube_music("lagu")
    assert out["status"] == "success"
    assert out["mode"] == "auto"
    assert out["audio"] == {"playing": True, "detail": "ok", "pid": "1234"}
    assert "PID 1234" in out["message"]
    assert out["evidence"]["audio_playing"] is True
    assert out["video_id"] == "vid123"
    assert out["duration_seconds"] == 125
    assert out["channel"] == "Penyanyi Uji"


def test_play_audio_mode_failure(player, monkeypatch):
    monkeypatch.setattr(player, "_resolve", lambda q: _info())
    monkeypatch.setattr(
        player, "_start_playback", lambda vid, url: (False, "ffplay hilang", "")
    )
    out = player.play_youtube_music("lagu", mode="audio")
    assert out["status"] == "error"
    assert "GAGAL: ffplay hilang" in out["message"]
    assert out["mode"] == "audio"


def test_play_invalid_mode_normalized_to_auto(player, monkeypatch):
    monkeypatch.setattr(player, "_resolve", lambda q: _info(duration=None, uploader=""))
    monkeypatch.setattr(
        player, "_start_playback", lambda vid, url: (True, "ok", "7")
    )
    out = player.play_youtube_music("lagu", mode="apapun")
    assert out["mode"] == "auto"
    assert out["status"] == "success"
    assert "(s)" not in out["message"]
    assert out["message"].startswith("🎵 Lagu Uji.")
