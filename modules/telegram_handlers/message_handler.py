"""Text Message Handler for ALFA Bot."""

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from telegram.ext import ContextTypes
    from telegram import Update

logger = logging.getLogger(__name__)


async def handle_text_message(update: "Update", context: "ContextTypes.DEFAULT_TYPE"):
    """Handle incoming text messages and route to agent."""
    from bot import (
        is_authorized, 
        safe_send_message, 
        run_agent_turn,
        check_and_send_media_artifacts,
        send_typing_loop,
    )
    
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    message_text = update.message.text
    
    if not is_authorized(user_id):
        return

    logger.info(f"User {user_id}: {message_text[:100]}...")

    async with send_typing_loop(context, chat_id):
        response_data = await run_agent_turn(
            user_id=user_id,
            chat_id=chat_id,
            message_text=message_text,
            context=context
        )

    # Check for media artifacts (plots, screenshots, etc.)
    await check_and_send_media_artifacts(update, context)

    # Send text response if available
    if response_data.get("response_text"):
        await safe_send_message(
            context, 
            chat_id, 
            response_data["response_text"]
        )
