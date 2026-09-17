"""Progressive draft streaming and realtime typing engine for Telegram."""

import asyncio
import logging
import time
from typing import Any, Optional

from telegram import constants
from telegram.error import BadRequest, RetryAfter

from alfa.bot.helpers import safe_send_message, send_typing_loop, split_message

logger = logging.getLogger("TelegramAIAgent")


class TelegramStreamer:
    """
    Progressive draft streaming and realtime typing engine for Telegram.

    Maintains native Telegram 'typing...' chat action while thinking/processing.
    Does NOT send dummy placeholder bubbles (e.g. '💭 Sedang berpikir...').
    When text chunks arrive, sends/edits real text progressively with rate-limit dampening.
    Safely swallows non-fatal Telegram errors and handles RetryAfter (429) backoff.
    """

    def __init__(
        self,
        context: Any,
        chat_id: int,
        initial_text: Optional[str] = None,
        min_edit_interval: float = 1.2,
    ):
        self.context = context
        self.chat_id = chat_id
        self.initial_text = initial_text
        self.min_edit_interval = float(min_edit_interval)
        self.message_id: Optional[int] = None
        self.buffer: str = ""
        self.last_edit: float = 0.0
        self.backoff_until: float = 0.0
        self.is_done: bool = False
        self._edit_task: Optional[asyncio.Task] = None
        self._stop_typing: asyncio.Event = asyncio.Event()
        self._typing_task: Optional[asyncio.Task] = None
        self.cursor: str = " ▌"

    async def start(self) -> Optional[int]:
        """Start realtime typing loop and optional initial placeholder message."""
        if self._typing_task is None or self._typing_task.done():
            self._stop_typing.clear()
            self._typing_task = asyncio.create_task(
                send_typing_loop(
                    self.chat_id,
                    self.context,
                    self._stop_typing,
                    constants.ChatAction.TYPING,
                )
            )

        if self.message_id is not None:
            return self.message_id

        if not self.initial_text:
            return None

        try:
            msg = await self.context.bot.send_message(
                chat_id=self.chat_id,
                text=self.initial_text,
            )
            self.message_id = getattr(msg, "message_id", None)
            self.last_edit = time.monotonic()
            return self.message_id
        except Exception as e:
            logger.warning(f"[TelegramStreamer] Gagal mengirim pesan initial: {e}")
            self.message_id = None
            return None

    async def _apply_edit(self, text: str) -> None:
        """Perform message edit with exception suppression and 429 backoff handling."""
        if not self.message_id or self.is_done:
            return
        now = time.monotonic()
        if now < self.backoff_until:
            return
        try:
            await self.context.bot.edit_message_text(
                chat_id=self.chat_id,
                message_id=self.message_id,
                text=text,
            )
            self.last_edit = time.monotonic()
        except RetryAfter as e:
            retry_secs = float(getattr(e, "retry_after", 1.0) or 1.0)
            self.backoff_until = time.monotonic() + retry_secs
            logger.warning(
                f"[TelegramStreamer] Rate limited (RetryAfter): backoff {retry_secs}s"
            )
        except BadRequest as e:
            err_msg = str(e).lower()
            if "message is not modified" in err_msg:
                logger.debug("[TelegramStreamer] Message is not modified, skipping.")
            elif "message to edit not found" in err_msg:
                logger.warning("[TelegramStreamer] Message to edit not found.")
            else:
                logger.warning(f"[TelegramStreamer] BadRequest saat edit: {e}")
        except Exception as e:
            logger.warning(f"[TelegramStreamer] Error tak terduga saat edit: {e}")

    async def push_chunk(self, chunk_text: str) -> None:
        """
        Append text chunk to buffer.
        If message_id is None, sends the first message with actual text once buffer has content,
        and stops the typing action.
        If message_id exists, edits draft with rate-limit dampening.
        """
        if self.is_done:
            return

        self.buffer += chunk_text
        now = time.monotonic()

        if now < self.backoff_until:
            return

        # If no message sent yet, send the first draft message once text is present
        if not self.message_id:
            if (now - self.last_edit) >= self.min_edit_interval and len(
                self.buffer.strip()
            ) >= 1:
                self._stop_typing.set()
                self.last_edit = now
                draft_text = self.buffer + self.cursor
                try:
                    msg = await self.context.bot.send_message(
                        chat_id=self.chat_id,
                        text=draft_text,
                    )
                    self.message_id = getattr(msg, "message_id", None)
                except Exception as e:
                    logger.warning(
                        f"[TelegramStreamer] Gagal mengirim initial streaming message: {e}"
                    )
            return

        if (now - self.last_edit) >= self.min_edit_interval:
            if not self.is_done:
                if self._edit_task and not self._edit_task.done():
                    return
                self.last_edit = now
                draft_text = self.buffer + self.cursor
                self._edit_task = asyncio.create_task(self._apply_edit(draft_text))
                await asyncio.sleep(0)

    async def finalize(self, final_text: Optional[str] = None) -> None:
        """
        Stop typing indicator, deliver the final complete text, and mark streamer as done.
        If message_id is None, sends via safe_send_message directly.
        """
        if self.is_done:
            return
        self.is_done = True
        self._stop_typing.set()
        if self._typing_task and not self._typing_task.done():
            try:
                await self._typing_task
            except Exception:
                pass

        if self._edit_task and not self._edit_task.done():
            try:
                await asyncio.wait_for(asyncio.shield(self._edit_task), timeout=2.0)
            except Exception:
                pass

        target_text = final_text if final_text is not None else self.buffer
        if not target_text or not target_text.strip():
            target_text = "✅ Selesai."

        if not self.message_id:
            await safe_send_message(self.context, self.chat_id, target_text)
            return

        chunks = split_message(target_text)
        first_chunk = chunks[0] if chunks else target_text

        edited = False
        try:
            await self.context.bot.edit_message_text(
                chat_id=self.chat_id,
                message_id=self.message_id,
                text=first_chunk,
                parse_mode=constants.ParseMode.MARKDOWN,
            )
            edited = True
        except Exception:
            try:
                await self.context.bot.edit_message_text(
                    chat_id=self.chat_id,
                    message_id=self.message_id,
                    text=first_chunk,
                )
                edited = True
            except BadRequest as be:
                if "message is not modified" in str(be).lower():
                    edited = True
                else:
                    logger.warning(f"[TelegramStreamer] Finalize edit failed: {be}")
            except Exception as e:
                logger.warning(f"[TelegramStreamer] Finalize edit failed: {e}")

        if not edited:
            await safe_send_message(self.context, self.chat_id, target_text)
            return

        for overflow_chunk in chunks[1:]:
            await safe_send_message(self.context, self.chat_id, overflow_chunk)
