"""Harness PTB (python-telegram-bot) untuk tes hermetic.

Menyediakan `TestApplication` ringan yang memanggil handler langsung
dengan mock Update/Context — **tanpa inisialisasi PTB penuh**.
Ini jauh lebih cepat dan cocok untuk unit test handler.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Callable, Awaitable, Optional
from unittest.mock import AsyncMock, MagicMock

from telegram import Update, User, Message, Chat, CallbackQuery
from telegram.ext import (
    Application,
    BaseHandler,
    CallbackContext,
    ContextTypes,
    ExtBot,
)


@dataclass
class MockContext:
    """Mock ContextTypes.DEFAULT_TYPE untuk tes."""
    bot: ExtBot
    args: list[str] = field(default_factory=list)
    user_data: dict = field(default_factory=dict)
    chat_data: dict = field(default_factory=dict)
    bot_data: dict = field(default_factory=dict)
    job_queue: Any = None
    application: Any = None
    
    def __post_init__(self):
        # Mock methods
        self.match = None


class TestApplication:
    """Wrapper aplikasi PTB untuk tes — memanggil handler langsung.
    
    Tidak butuh bot token, tidak butuh network, tidak butuh PTB initialize.
    Cukup daftarkan handler, lalu gunakan `feed_update()` dengan mock Update.
    """

    def __init__(
        self,
        handlers: list[BaseHandler] | None = None,
    ):
        self._handlers = handlers or []
        self._bot = MagicMock(spec=ExtBot)
        self._bot.id = 123456789
        self._bot.username = "testbot"
        
        # Mock bot methods
        self._bot.send_message = AsyncMock()
        self._bot.send_photo = AsyncMock()
        self._bot.send_document = AsyncMock()
        self._bot.edit_message_text = AsyncMock()
        self._bot.answer_callback_query = AsyncMock()
    
    @property
    def bot(self) -> MagicMock:
        return self._bot

    @classmethod
    @asynccontextmanager
    async def create(
        cls,
        *,
        handlers: list[BaseHandler] | None = None,
        **app_kwargs: Any,  # ignored, for API compatibility
    ) -> AsyncGenerator["TestApplication", None]:
        """Factory async context manager — no-op startup/shutdown."""
        app = cls(handlers=handlers)
        try:
            yield app
        finally:
            pass  # no cleanup needed

    async def feed_update(self, update: Update) -> None:
        """Proses update melalui semua handler yang cocok."""
        context = MockContext(bot=self._bot)
        
        # PTB handler processing logic (simplified)
        for handler in self._handlers:
            check_result = handler.check_update(update)
            if check_result:
                try:
                    # handle_update signature: (update, application, check_result, context)
                    await handler.handle_update(update, self, check_result, context)
                except Exception as e:
                    # Log tapi lanjutkan handler lain
                    import logging
                    logging.getLogger(__name__).debug(
                        f"Handler {handler} error: {e}"
                    )

    async def feed_and_wait(
        self,
        update: Update,
        *,
        timeout: float = 5.0,
    ) -> None:
        await self.feed_update(update)
        await asyncio.sleep(0.01)

    def get_handlers(self) -> dict[str, list[BaseHandler]]:
        # Group by type seperti PTB
        groups: dict[str, list[BaseHandler]] = {}
        for h in self._handlers:
            group = getattr(h, "group", 0)
            groups.setdefault(str(group), []).append(h)
        return groups

    def add_handler(self, handler: BaseHandler) -> None:
        self._handlers.append(handler)


# --- Helper untuk bikin mock Update ---

def make_mock_update(
    *,
    update_id: int = 1,
    message: Optional[Message] = None,
    callback_query: Optional[CallbackQuery] = None,
    effective_user: Optional[User] = None,
    effective_chat: Optional[Chat] = None,
) -> Update:
    """Buat mock Update dengan field minimal."""
    if effective_user is None:
        effective_user = User(id=123456, first_name="TestUser", is_bot=False)
    if effective_chat is None:
        effective_chat = Chat(id=123456, type=Chat.PRIVATE)
    
    update = MagicMock(spec=Update)
    update.update_id = update_id
    update.message = message
    update.callback_query = callback_query
    update.effective_user = effective_user
    update.effective_chat = effective_chat
    
    # Add effective_message property for CommandHandler
    if message:
        update.effective_message = message
    
    return update


def make_mock_message(
    text: str = "",
    chat: Optional[Chat] = None,
    from_user: Optional[User] = None,
    message_id: int = 1,
    is_command: bool = False,
) -> Message:
    if chat is None:
        chat = Chat(id=123456, type=Chat.PRIVATE)
    if from_user is None:
        from_user = User(id=123456, first_name="TestUser", is_bot=False)
    
    msg = MagicMock(spec=Message)
    msg.message_id = message_id
    msg.text = text
    msg.chat = chat
    msg.from_user = from_user
    msg.reply_text = AsyncMock()
    msg.edit_text = AsyncMock()
    
    # Add get_bot() method for CommandHandler
    bot_user = User(id=999999, first_name="TestBot", username="testbot", is_bot=True)
    msg.get_bot = MagicMock(return_value=bot_user)
    
    # Add entities for bot commands
    if is_command and text and text.startswith('/'):
        from telegram import MessageEntity
        cmd_len = len(text.split()[0])
        msg.entities = [MessageEntity(type=MessageEntity.BOT_COMMAND, offset=0, length=cmd_len)]
    else:
        msg.entities = []
    
    return msg


def make_mock_callback_query(
    data: str = "",
    from_user: Optional[User] = None,
    message: Optional[Message] = None,
    chat: Optional[Chat] = None,
) -> CallbackQuery:
    if from_user is None:
        from_user = User(id=123456, first_name="TestUser", is_bot=False)
    if chat is None:
        chat = Chat(id=123456, type=Chat.PRIVATE)
    if message is None:
        message = make_mock_message(chat=chat, from_user=from_user)
    
    query = MagicMock(spec=CallbackQuery)
    query.id = "callback_query_1"
    query.data = data
    query.from_user = from_user
    query.message = message
    query.chat = chat
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()
    return query


# Backward compatibility alias
build_test_application = TestApplication.create