"""Fake Discord Client untuk tes hermetic.

Menyediakan `FakeDiscordClient` yang meniru `discord.Client` +
`discord.app_commands.CommandTree` tanpa koneksi WebSocket nyata.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable, Optional

import discord
from discord import app_commands
from discord.interactions import Interaction


@dataclass
class FakeUser:
    id: int = 123456789
    name: str = "TestUser"
    display_name: str = "Test User"
    bot: bool = False


@dataclass
class FakeGuild:
    id: int = 987654321
    name: str = "Test Guild"


@dataclass
class FakeChannel:
    id: int = 111222333
    name: str = "test-channel"
    guild: Optional[FakeGuild] = field(default_factory=FakeGuild)
    _messages: list[FakeMessage] = field(default_factory=list, repr=False)

    async def send(self, content: str = "", **kwargs: Any) -> "FakeMessage":
        msg = FakeMessage(content=content, channel=self, **kwargs)
        self._messages.append(msg)
        return msg

    def get_messages(self) -> list["FakeMessage"]:
        return list(self._messages)

    def clear_messages(self) -> None:
        self._messages.clear()


@dataclass
class FakeMessage:
    channel: FakeChannel
    id: int = field(default_factory=lambda: 0)
    content: str = ""
    author: FakeUser = field(default_factory=FakeUser)
    guild: Optional[FakeGuild] = None
    _reactions: list[str] = field(default_factory=list, repr=False)

    def __post_init__(self):
        if self.id == 0:
            FakeMessage._next_id += 1
            self.id = FakeMessage._next_id

    async def reply(self, content: str = "", **kwargs: Any) -> "FakeMessage":
        return await self.channel.send(content, **kwargs)

    async def add_reaction(self, emoji: str) -> None:
        self._reactions.append(emoji)

    def edit(self, **kwargs: Any) -> None:
        for k, v in kwargs.items():
            setattr(self, k, v)


FakeMessage._next_id = 0


@dataclass
class FakeInteraction:
    id: int = 999
    user: FakeUser = field(default_factory=FakeUser)
    guild: Optional[FakeGuild] = field(default_factory=FakeGuild)
    channel: Optional[FakeChannel] = field(default_factory=FakeChannel)
    data: dict = field(default_factory=dict)
    _response_sent: bool = False
    _response_content: str = ""

    async def response_send_message(
        self,
        content: str = "",
        ephemeral: bool = False,
        **kwargs: Any,
    ) -> None:
        self._response_sent = True
        self._response_content = content

    async def followup_send(
        self,
        content: str = "",
        ephemeral: bool = False,
        **kwargs: Any,
    ) -> None:
        self._response_content += "\n" + content


class FakeCommandTree(app_commands.CommandTree):
    """CommandTree yang bisa di-trigger manual tanpa HTTP."""

    def __init__(self, client: "FakeDiscordClient"):
        super().__init__(client)
        self._client = client

    async def call_command(
        self,
        command_name: str,
        user: Optional[FakeUser] = None,
        channel: Optional[FakeChannel] = None,
        guild: Optional[FakeGuild] = None,
        **options: Any,
    ) -> FakeInteraction:
        """Panggil slash command secara langsung."""
        cmd = self.get_command(command_name)
        if not cmd:
            raise ValueError(f"Command '{command_name}' tidak ditemukan")

        interaction = FakeInteraction(user=user, channel=channel, guild=guild)
        interaction.data = {"name": command_name, "options": []}

        # Build options untuk subcommand/group
        for name, value in options.items():
            interaction.data["options"].append({"name": name, "value": value})

        await self._call(interaction)
        return interaction


class FakeDiscordClient(discord.Client):
    """Client Discord palsu — tidak pernah connect ke gateway."""

    def __init__(
        self,
        *,
        loop: Optional[asyncio.AbstractEventLoop] = None,
        **kwargs: Any,
    ):
        # discord.py 2.0+ requires intents
        intents = kwargs.pop("intents", discord.Intents.default())
        super().__init__(loop=loop, intents=intents, **kwargs)
        self.tree = FakeCommandTree(self)
        self._channels: dict[int, FakeChannel] = {}
        self._guilds: dict[int, FakeGuild] = {}
        self._users: dict[int, FakeUser] = {}
        self._ready_event = asyncio.Event()
        self._closed = False

    # --- Lifecycle ---

    async def login(self, token: str) -> None:
        self._ready_event.set()

    async def connect(self, *, reconnect: bool = True) -> None:
        pass  # no-op

    async def close(self) -> None:
        self._closed = True

    def is_ready(self) -> bool:
        return self._ready_event.is_set()

    def is_closed(self) -> bool:
        return self._closed

    # --- Factory entities ---

    def create_user(self, **kwargs: Any) -> FakeUser:
        user = FakeUser(**kwargs)
        self._users[user.id] = user
        return user

    def create_guild(self, **kwargs: Any) -> FakeGuild:
        guild = FakeGuild(**kwargs)
        self._guilds[guild.id] = guild
        return guild

    def create_channel(self, guild: Optional[FakeGuild] = None, **kwargs: Any) -> FakeChannel:
        channel = FakeChannel(guild=guild, **kwargs)
        self._channels[channel.id] = channel
        return channel

    def get_channel(self, channel_id: int) -> Optional[FakeChannel]:
        return self._channels.get(channel_id)

    def get_guild(self, guild_id: int) -> Optional[FakeGuild]:
        return self._guilds.get(guild_id)

    def get_user(self, user_id: int) -> Optional[FakeUser]:
        return self._users.get(user_id)

    # --- Helpers untuk tes ---

    def get_all_messages(self) -> list[FakeMessage]:
        all_msgs = []
        for ch in self._channels.values():
            all_msgs.extend(ch.get_messages())
        return all_msgs

    def clear_all_messages(self) -> None:
        for ch in self._channels.values():
            ch.clear_messages()


# --- Fixture pytest ---

import pytest


@pytest.fixture
def discord_client() -> FakeDiscordClient:
    """FakeDiscordClient siap pakai — auto-cleanup."""
    client = FakeDiscordClient()
    yield client
    # cleanup otomatis via garbage collection


@pytest.fixture
def discord_channel(discord_client: FakeDiscordClient) -> FakeChannel:
    return discord_client.create_channel()


@pytest.fixture
def discord_guild(discord_client: FakeDiscordClient) -> FakeGuild:
    return discord_client.create_guild()


@pytest.fixture
def discord_user(discord_client: FakeDiscordClient) -> FakeUser:
    return discord_client.create_user()