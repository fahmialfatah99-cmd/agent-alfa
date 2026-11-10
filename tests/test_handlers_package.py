"""Regression tests untuk paket `alfa.bot.handlers`.

Modul monolitik (2.839 baris) dipecah menjadi paket; import path publik dan
perilaku patch/mock pada `alfa.bot.handlers` harus tetap sama.
"""

from __future__ import annotations

import importlib
from unittest.mock import AsyncMock, patch

import alfa.bot.handlers as h


def test_handlers_is_package_with_stable_public_api():
    assert h.__file__.endswith("handlers/__init__.py")

    for sub in (
        "_compat",
        "_state",
        "common",
        "artifacts",
        "documents",
        "forwards",
        "menus",
        "messages",
        "media",
    ):
        assert importlib.import_module(f"alfa.bot.handlers.{sub}") is not None

    public_api = (
        "greeting_reply",
        "_get_bot_module",
        "_is_authorized",
        "_run_agent_turn",
        "handle_text_message",
        "handle_voice_message",
        "handle_photo_message",
        "handle_document_message",
        "handle_callback_query",
        "handle_doc_action_callback",
        "handle_forward_action_callback",
        "check_and_send_media_artifacts",
        "_check_and_send_media_artifacts",
        "get_forward_info",
        "is_artifact_producing_tool",
        "has_artifact_intent",
        "try_handle_fast_wa",
        "ACTIVE_CHAT_TASKS",
    )
    for name in public_api:
        assert hasattr(h, name), f"{name} hilang dari API publik"


def test_state_is_shared_between_modules():
    """State mutable harus benar-benar sama antar sub-modul."""
    from alfa.bot.handlers import _state, documents, messages

    assert documents._RECENT_DOCS is _state._RECENT_DOCS
    assert messages.ACTIVE_CHAT_TASKS is _state.ACTIVE_CHAT_TASKS
    assert h.ACTIVE_CHAT_TASKS is _state.ACTIVE_CHAT_TASKS


async def test_package_level_patch_still_intercepts_internal_calls():
    """Patch pada `alfa.bot.handlers.<nama>` harus memengaruhi pemanggil internal."""
    from alfa.bot.handlers._compat import (
        check_artifacts_turn,
        doc_action_callback,
        forward_action_callback,
        system_stats,
    )

    with patch("alfa.bot.handlers.safe_send_message", new_callable=AsyncMock):
        assert h.safe_send_message is not None

    with patch("alfa.bot.handlers.get_system_stats", return_value={"cpu": "1%"}):
        assert system_stats() == {"cpu": "1%"}

    with patch(
        "alfa.bot.handlers.handle_doc_action_callback",
        new=AsyncMock(return_value="doc"),
    ):
        assert await doc_action_callback() == "doc"

    with patch(
        "alfa.bot.handlers.handle_forward_action_callback",
        new=AsyncMock(return_value="fwd"),
    ):
        assert await forward_action_callback() == "fwd"

    with patch(
        "alfa.bot.handlers._check_and_send_media_artifacts",
        new=AsyncMock(return_value="art"),
    ):
        assert await check_artifacts_turn() == "art"
