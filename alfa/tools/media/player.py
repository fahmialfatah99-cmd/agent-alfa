"""Real online playback: resolve a YouTube track and actually play it.

Tool `play_youtube_music` does the two things users literally ask for:
1. opens the real YouTube page in the user's visible desktop browser, and
2. actually streams the audio through the speakers (ffplay), with honest
   reporting of what did / did not work.
"""

import json
import logging
import os
import re
import shutil
import subprocess
import time
from typing import Any

from alfa.tools.registry import register_tool

logger = logging.getLogger("AgentTools.Media.Player")

# Pipeline audio lokal yang sedang berjalan (untuk mode stop / anti-tumpang-tindih)
_AUDIO_PROC: subprocess.Popen | None = None

_YT_URL_RE = re.compile(
    r"(?:youtube\.com/(?:watch\?v=|shorts/|live/)|youtu\.be/)([A-Za-z0-9_-]{6,})"
)


def _which(names: list[str]) -> str | None:
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    return None


def _ytdlp() -> str | None:
    return _which(["yt-dlp"])


# Client pemutar YouTube. Client bawaan (android_vr) dibalas 403 oleh googlevideo,
# sedangkan client 'android' masih menerima unduhan — jadi dicoba lebih dulu,
# baru jatuh ke konfigurasi bawaan yt-dlp bila gagal.
_PLAYER_CLIENT = os.getenv("ALFA_YT_PLAYER_CLIENT", "android").strip()


def _client_args() -> list[str]:
    if not _PLAYER_CLIENT:
        return []
    return ["--extractor-args", f"youtube:player_client={_PLAYER_CLIENT}"]


def _run_ytdlp(args: list[str], timeout: int) -> subprocess.CompletedProcess:
    """Jalankan yt-dlp: coba dulu dengan client pilihan, lalu tanpa (bawaan)."""
    ytdlp = _ytdlp() or "yt-dlp"
    attempts = [[ytdlp, *_client_args(), *args]] if _client_args() else []
    attempts.append([ytdlp, *args])
    last: subprocess.CompletedProcess | None = None
    for cmd in attempts:
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired as te:
            return subprocess.CompletedProcess(cmd, 124, "", f"timeout: {te}")
        except Exception as e:  # noqa: BLE001
            return subprocess.CompletedProcess(args, 1, "", str(e))
        last = res
        if res.returncode == 0 and (res.stdout or "").strip():
            return res
    return last or subprocess.CompletedProcess(args, 1, "", "yt-dlp tidak tersedia")


def _watch_url(video_id: str, autoplay: bool = False) -> str:
    url = f"https://www.youtube.com/watch?v={video_id}"
    return url + "&autoplay=1" if autoplay else url


def _resolve(query: str) -> dict[str, Any]:
    """Cari video YouTube dari query/URL. Return dict berisi id/title/duration/url."""
    q = (query or "").strip()
    if not q:
        return {"ok": False, "error": "Query lagu kosong."}

    ytdlp = _ytdlp()
    if not ytdlp:
        return {
            "ok": False,
            "error": "yt-dlp tidak terpasang di sistem — tidak bisa mencari/memainkan lagu.",
        }

    m = _YT_URL_RE.search(q)
    if m:
        target = f"https://www.youtube.com/watch?v={m.group(1)}"
    elif q.startswith(("http://", "https://")):
        target = q
    else:
        target = f"ytsearch1:{q}"

    try:
        res = _run_ytdlp(
            ["--no-warnings", "--no-playlist", "--socket-timeout", "20", "-J", target],
            60,
        )
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"yt-dlp gagal dijalankan: {e}"}

    if res.returncode != 0 or not (res.stdout or "").strip():
        err = (res.stderr or "").strip()[:400]
        return {
            "ok": False,
            "error": f"yt-dlp tidak menemukan hasil: {err or 'tanpa output'}",
        }

    try:
        data = json.loads(res.stdout)
    except Exception:
        return {"ok": False, "error": "Output yt-dlp bukan JSON valid."}

    entries = data.get("entries") if isinstance(data, dict) else None
    entry = None
    if isinstance(entries, list) and entries:
        entry = next((e for e in entries if e), None)
    elif isinstance(data, dict) and data.get("id"):
        entry = data
    if not entry:
        return {"ok": False, "error": "Tidak ada hasil video untuk query tersebut."}

    vid = entry.get("id") or ""
    duration = entry.get("duration")
    return {
        "ok": True,
        "id": vid,
        "title": (entry.get("title") or "Tanpa judul").strip(),
        "duration": duration,
        "uploader": (entry.get("uploader") or entry.get("channel") or "").strip(),
        "url": entry.get("webpage_url") or _watch_url(vid),
        "watch_url": _watch_url(vid),
    }


def _cache_dir() -> str:
    d = os.path.join(os.path.expanduser("~"), ".alfa", "cache", "music")
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        d = "/tmp"  # nosec B108 - last-resort fallback dir
    return d


def _cached_track(video_id: str) -> str | None:
    base = os.path.join(_cache_dir(), video_id)
    for ext in (".opus", ".webm", ".m4a", ".mp3", ".ogg"):
        cand = base + ext
        if os.path.exists(cand) and os.path.getsize(cand) > 2048:
            return cand
    return None


def _download_track(video_id: str, watch_url: str) -> tuple[str | None, str]:
    """Unduh audio ke cache lokal — yt-dlp yang menangani semua header/UA YouTube."""
    ytdlp = _ytdlp()
    if not ytdlp:
        return None, "yt-dlp tidak tersedia."
    out_tmpl = os.path.join(_cache_dir(), f"{video_id}.%(ext)s")
    res = _run_ytdlp(
        [
            "--no-warnings",
            "-f",
            "bestaudio/best",
            "-o",
            out_tmpl,
            "--socket-timeout",
            "20",
            watch_url,
        ],
        180,
    )
    cached = _cached_track(video_id)
    if cached:
        return cached, ""
    return None, (res.stderr or "").strip()[:300] or "Unduhan audio gagal."


def _start_ffplay(source: str) -> subprocess.Popen | None:
    ffplay = _which(["ffplay"])
    if not ffplay:
        return None
    cmd = [ffplay, "-nodisp", "-autoexit", "-loglevel", "error", source]
    try:
        return subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception:  # noqa: BLE001
        return None


def _kill_group(proc: subprocess.Popen | None) -> bool:
    if proc is None:
        return False
    try:
        if proc.poll() is None:
            os.killpg(os.getpgid(proc.pid), 15)  # SIGTERM ke seluruh pipeline
            return True
    except Exception:  # noqa: BLE001
        try:
            proc.terminate()
            return True
        except Exception:  # noqa: BLE001
            return False
    return False


def _stop_audio() -> dict[str, Any]:
    global _AUDIO_PROC
    stopped = _kill_group(_AUDIO_PROC)
    _AUDIO_PROC = None
    for pat in ("ffplay.*-nodisp", "yt-dlp.*bestaudio"):
        try:
            subprocess.run(["pkill", "-f", pat], capture_output=True, timeout=5)
        except Exception:  # noqa: BLE001
            pass
    return {
        "status": "success",
        "message": (
            "Pemutaran audio lokal dihentikan."
            if stopped
            else "Tidak ada pemutaran audio lokal yang berjalan."
        ),
    }


def _play_audio_streaming(watch_url: str) -> tuple[bool, str, str]:
    """Streaming audio langsung: yt-dlp -> pipe -> ffplay (mulai dalam hitungan detik)."""
    ytdlp = _ytdlp()
    if not ytdlp:
        return False, "yt-dlp tidak tersedia.", ""
    ffplay = _which(["ffplay"])
    if not ffplay:
        return False, "ffplay (ffmpeg) tidak terpasang di sistem.", ""

    global _AUDIO_PROC
    _kill_group(_AUDIO_PROC)
    _AUDIO_PROC = None

    client = " ".join(f'"{a}"' if " " in a else a for a in _client_args())
    pipeline = (
        f'"{ytdlp}" {client} --no-warnings -q -f "bestaudio/best" -o - "{watch_url}"'
        f' | "{ffplay}" -nodisp -autoexit -loglevel error -i -'
    )
    try:
        proc = subprocess.Popen(
            pipeline,  # nosec B602 - watch_url constrained to YouTube IDs/URLs by _YT_URL_RE
            shell=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
    except Exception as e:  # noqa: BLE001
        return False, f"Gagal menjalankan pipeline audio: {e}", ""

    time.sleep(4)
    if proc.poll() is not None:
        err = ""
        try:
            _raw = proc.stderr.read() if proc.stderr else b""
            err = (_raw or b"").decode("utf-8", "replace").strip()
        except Exception:  # noqa: BLE001
            err = ""
        return False, (err[-400:] or "Pipeline audio berhenti segera."), ""

    _AUDIO_PROC = proc
    return True, "Streaming audio berjalan (yt-dlp -> ffplay).", str(proc.pid)


def _play_audio_file(path: str) -> tuple[bool, str, str]:
    global _AUDIO_PROC
    _kill_group(_AUDIO_PROC)
    _AUDIO_PROC = None
    proc = _start_ffplay(path)
    if proc is None:
        return False, "ffplay (ffmpeg) tidak terpasang di sistem.", ""
    time.sleep(1.2)
    if proc.poll() is not None:
        return False, "ffplay berhenti langsung (format/codec tidak didukung).", ""
    _AUDIO_PROC = proc
    return True, f"Memutar file lokal: {os.path.basename(path)}", str(proc.pid)


def _start_playback(video_id: str, watch_url: str) -> tuple[bool, str, str]:
    """Putar audio: cache -> streaming -> unduh-lalu-mutar (semua diverifikasi)."""
    cached = _cached_track(video_id)
    if cached:
        ok, detail, pid = _play_audio_file(cached)
        if ok:
            return True, detail, pid

    ok, detail, pid = _play_audio_streaming(watch_url)
    if ok:
        return True, detail, pid
    logger.info(f"Streaming audio gagal ({detail}) -> fallback unduh file")

    path, err = _download_track(video_id, watch_url)
    if path:
        return _play_audio_file(path)
    return False, f"{detail} | fallback unduh: {err}", ""


@register_tool(category="media")
def play_youtube_music(query: str = "", mode: str = "auto") -> dict[str, Any]:
    """
    Find a song/video on YouTube and PLAY it for real (not just talk about it).

    It really resolves the track with yt-dlp, opens the actual youtube.com watch
    page in the user's visible desktop browser, and streams the audio through the
    speakers. Returns the resolved video id/title/url and playback PID as proof.

    Args:
        query: Song/artist/video title (e.g. 'bohemian rhapsody queen') or a full YouTube URL.
            Required for mode auto/browser/audio; optional for mode 'stop'.
        mode: 'auto' = open the YouTube page AND play audio locally (default),
              'browser' = only open the YouTube page in the visible browser,
              'audio' = only play the audio through the speakers,
              'stop' = stop the local audio playback (query not needed).
    """
    md = (mode or "auto").strip().lower()
    if md == "stop":
        return _stop_audio()
    if md not in {"auto", "browser", "audio"}:
        md = "auto"
    if not (query or "").strip():
        return {
            "status": "error",
            "message": "Query lagu kosong. Sebutkan judul/penyanyi (mode 'stop' cukup tanpa query).",
        }

    info = _resolve(query)
    if not info.get("ok"):
        return {
            "status": "error",
            "message": info.get("error", "Gagal mencari lagu."),
            "query": query,
        }

    video_id = info["id"]
    watch_url = info["watch_url"]
    title = info["title"]
    duration = info.get("duration")
    label = title + (f" ({int(duration)}s)" if duration else "")
    if info.get("uploader"):
        label += f" — {info['uploader']}"

    result: dict[str, Any] = {
        "status": "success",
        "query": query,
        "video_id": video_id,
        "title": title,
        "duration_seconds": duration,
        "channel": info.get("uploader", ""),
        "url": watch_url,
        "mode": md,
    }
    notes: list[str] = []

    opened = False
    if md in {"auto", "browser"}:
        try:
            from alfa.tools.desktop.input_automation import open_url_in_default_browser

            opened, how = open_url_in_default_browser(watch_url)
            result["browser"] = {"opened": opened, "mechanism": how}
            if opened:
                notes.append(f" halaman YouTube terbuka di browser desktop ({how}).")
            else:
                notes.append(f" browser GAGAL membuka halaman: {how}.")
        except Exception as e:  # noqa: BLE001
            result["browser"] = {"opened": False, "mechanism": str(e)}
            notes.append(f" pembuka browser error: {e}.")

    played = False
    if md in {"auto", "audio"}:
        played, detail, pid = _start_playback(video_id, watch_url)
        result["audio"] = {"playing": played, "detail": detail, "pid": pid}
        if played:
            notes.append(f" audio lagu sedang diputar lewat speaker (PID {pid}).")
        else:
            notes.append(f" pemutaran audio GAGAL: {detail}.")
            if md == "auto" and opened:
                try:
                    from alfa.tools.desktop.input_automation import (
                        open_url_in_default_browser,
                    )

                    autoplay_ok, autoplay_how = open_url_in_default_browser(
                        _watch_url(video_id, autoplay=True)
                    )
                    result["browser"] = {
                        "opened": bool(autoplay_ok),
                        "mechanism": f"autoplay fallback: {autoplay_how}",
                    }
                    if autoplay_ok:
                        notes.append(" browser diminta memutar otomatis (autoplay=1).")
                except Exception:  # noqa: BLE001
                    pass

    if md == "browser" and not opened:
        result["status"] = "error"
    elif md == "audio" and not played:
        result["status"] = "error"
    elif md == "auto" and not opened and not played:
        result["status"] = "error"

    result["message"] = f"🎵 {label}." + ("".join(notes) or " Tidak ada aksi yang berhasil.")
    result["evidence"] = {
        "video_id": video_id,
        "url": watch_url,
        "browser_opened": bool(result.get("browser", {}).get("opened")),
        "audio_playing": bool(result.get("audio", {}).get("playing")),
    }
    return result
