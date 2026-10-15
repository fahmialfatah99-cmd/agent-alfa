"""Live progress reporter: swarm/rapat activity -> ONE tidy Telegram status message.

Prinsip rapi:
- Tepat SATU pesan status per misi, di-edit di tempat (bukan spam pesan baru).
- Edit dibatasi (min interval), dilewati bila isi sama, aman dari 429/not-modified.
- Ringkas: checklist agen + 1 baris event terakhir + durasi. Detail penuh tetap
  dikirim di akhir oleh command masing-masing (laporan + file).
"""

import asyncio
import json
import logging
import os
import time
from typing import Any

from telegram.error import BadRequest, RetryAfter

logger = logging.getLogger("TelegramAIAgent")

_STATE_ICON = {
    "assigned": "•",
    "running": "⏳",
    "pass": "✅",
    "fail": "❌",
    "file": "📁",
    "done": "🏁",
}

_MAX_TEXT = 900
_DEFAULT_POLL = 10.0
_DEFAULT_MIN_EDIT = 8.0


def _short(text: str, n: int) -> str:
    t = " ".join(str(text or "").split())
    return t if len(t) <= n else t[: n - 1] + "…"


class SwarmProgressReporter:
    """Ekor live feed swarm dan tampilkan ringkasannya ke satu pesan Telegram."""

    def __init__(
        self,
        context: Any,
        chat_id: int,
        topic: str,
        header: str = "⚡ **Swarm**",
        poll_interval: float = _DEFAULT_POLL,
        min_edit_interval: float = _DEFAULT_MIN_EDIT,
    ):
        self.context = context
        self.chat_id = chat_id
        self.topic = _short(topic, 60)
        self.header = header
        self.poll_interval = poll_interval
        self.min_edit_interval = min_edit_interval
        self.message_id: int | None = None
        self.started_at = time.monotonic()
        self._task: asyncio.Task | None = None
        self._stopped = False
        self._last_sent = ""
        self._last_edit = 0.0
        self._backoff_until = 0.0
        self._offset = 0
        self._agents: dict[str, dict[str, str]] = {}
        self._last_event = "menyiapkan misi…"
        self._finished = False

    # -- public API --

    async def start(self) -> None:
        """Kirim pesan status awal & mulai loop ekor feed."""
        self._offset = self._feed_size()
        try:
            msg = await self.context.bot.send_message(
                chat_id=self.chat_id,
                text=f"{self.header}: _{self.topic}_\n🚀 Misi dimulai…",
                parse_mode="Markdown",
            )
            self.message_id = getattr(msg, "message_id", None)
        except Exception as e:
            logger.warning(f"[progress] gagal kirim status awal: {e}")
            return
        self._last_edit = time.monotonic()
        self._task = asyncio.create_task(self._loop())
        # Kirim render pertama setelah poll singkat agar langsung berisi
        await asyncio.sleep(0)

    async def stop(self, final_note: str = "") -> None:
        """Hentikan reporter; kunci pesan status dengan catatan akhir (tanpa hapus)."""
        self._stopped = True
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        if self.message_id and final_note:
            text = self._render() + f"\n{final_note}"
            await self._edit(text, force=True)

    # -- internals --

    def _feed_path(self) -> str:
        try:
            from alfa.swarm.workspace_hygiene import _get_swarm_output_dir

            return os.path.join(_get_swarm_output_dir(), "live_meeting_feed.jsonl")
        except Exception:
            try:
                from alfa.swarm.workspace_hygiene import LIVE_FEED_FILE

                return LIVE_FEED_FILE
            except Exception:
                return ""

    def _feed_size(self) -> int:
        try:
            return os.path.getsize(self._feed_path())
        except OSError:
            return 0

    def _read_new(self) -> list[dict[str, Any]]:
        path = self._feed_path()
        if not path:
            return []
        try:
            size = os.path.getsize(path)
        except OSError:
            return []
        if size < self._offset:
            self._offset = 0  # feed dipangkas engine (300KB cap) -> baca ulang
        if size == self._offset:
            return []
        try:
            out: list[dict[str, Any]] = []
            with open(path, encoding="utf-8") as f:
                f.seek(self._offset)
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        out.append(json.loads(line))
                    except ValueError:
                        pass
                self._offset = f.tell()
            return out
        except OSError as e:
            logger.debug(f"[progress] baca feed gagal: {e}")
            return []

    def _ingest(self, entry: dict[str, Any]) -> None:
        tag = str(entry.get("tag", "")).upper()
        text = str(entry.get("text", ""))
        if tag == "PLAN" and ":" in text:
            # "🗂️ Nama Agen: tugas..." -> tandai assigned
            head = text.split(":", 1)[0]
            name = head.replace("🗂️", "").strip()
            if name:
                self._agents.setdefault(name, {"state": "assigned", "note": ""})
                self._agents[name]["state"] = "assigned"
        elif tag == "EXEC" and ("mulai eksekusi" in text or "mulai" in text):
            name = text.split("mulai eksekusi", 1)[0].replace("⚙️", "").strip(" :")
            if name:
                self._agents.setdefault(name, {"state": "running", "note": ""})
                self._agents[name]["state"] = "running"
            self._last_event = _short(text.replace("⚙️", ""), 110)
        elif tag == "VERIFY":
            name = text.split("(")[0].replace("✅ PASS —", "").replace("❌ FAIL —", "").strip()
            ok = "PASS" in text
            if name:
                self._agents.setdefault(name, {"state": "pass" if ok else "fail", "note": ""})
                self._agents[name]["state"] = "pass" if ok else "fail"
            self._last_event = ("✅ " if ok else "❌ ") + _short(text, 110)
        elif tag == "FILE":
            self._last_event = "📁 " + _short(text, 110)
        elif tag == "QA":
            self._last_event = "🛡️ " + _short(text, 110)
        elif tag in ("DONE", "CANCEL", "TIMEOUT", "SESSION"):
            self._last_event = _short(text, 110)
            if tag in ("DONE", "CANCEL", "TIMEOUT"):
                self._finished = True
        elif tag == "DIALOG":
            self._last_event = "💬 " + _short(text, 110)

    def _render(self) -> str:
        elapsed = int(time.monotonic() - self.started_at)
        mm, ss = divmod(elapsed, 60)
        if self._agents:
            done = sum(1 for a in self._agents.values() if a["state"] in ("pass", "fail", "file"))
            total = len(self._agents)
            counts = f"{done}/{total} langkah"
        else:
            counts = "menyiapkan…"
        lines = [
            f"{self.header}: _{self.topic}_",
            f"🔄 {mm:02d}:{ss:02d} • {counts}",
        ]
        for name, info in list(self._agents.items())[:8]:
            icon = _STATE_ICON.get(info["state"], "•")
            lines.append(f"{icon} {_short(name, 24)}")
        if len(self._agents) > 8:
            lines.append(f"… +{len(self._agents) - 8} agen lain")
        lines.append(f"📌 {_short(self._last_event, 120)}")
        text = "\n".join(lines)
        return text if len(text) <= _MAX_TEXT else text[: _MAX_TEXT - 1] + "…"

    async def _edit(self, text: str, force: bool = False) -> None:
        if not self.message_id or text == self._last_sent:
            return
        now = time.monotonic()
        if not force and (now < self._backoff_until or now - self._last_edit < self.min_edit_interval):
            return
        try:
            await self.context.bot.edit_message_text(
                chat_id=self.chat_id, message_id=self.message_id, text=text, parse_mode="Markdown"
            )
        except RetryAfter as e:
            self._backoff_until = time.monotonic() + float(getattr(e, "retry_after", 5) or 5)
            return
        except BadRequest as e:
            if "message is not modified" not in str(e).lower():
                logger.debug(f"[progress] edit gagal: {e}")
            else:
                self._last_sent = text
            return
        except Exception as e:
            logger.debug(f"[progress] edit gagal: {e}")
            return
        # Fallback tanpa Markdown bila parse gagal diam-diam (BadRequest sudah ditangani)
        self._last_sent = text
        self._last_edit = time.monotonic()

    async def _loop(self) -> None:
        try:
            while not self._stopped and not self._finished:
                for entry in self._read_new():
                    self._ingest(entry)
                await self._edit(self._render())
                await asyncio.sleep(self.poll_interval)
            # Sapu terakhir saat DONE terdeteksi
            for entry in self._read_new():
                self._ingest(entry)
            await self._edit(self._render(), force=True)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.debug(f"[progress] loop berhenti: {e}")


__all__ = ["SwarmProgressReporter"]
