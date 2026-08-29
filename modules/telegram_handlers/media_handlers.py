"""Media Message Handlers for ALFA Bot (voice, photo, document)."""

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from telegram.ext import ContextTypes
    from telegram import Update

logger = logging.getLogger(__name__)


async def handle_voice_message(update: "Update", context: "ContextTypes.DEFAULT_TYPE"):
    """Handle incoming voice messages - transcribe and process."""
    from bot import (
        is_authorized,
        safe_send_message,
        run_agent_turn,
        send_typing_loop,
    )
    
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    if not is_authorized(user_id):
        return

    # Download voice note
    voice_file = await update.message.voice.get_file()
    voice_path = f"/tmp/voice_{user_id}_{update.message.date.timestamp()}.ogg"
    await voice_file.download_to_drive(voice_path)
    
    logger.info(f"User {user_id}: Received voice message ({voice_path})")
    
    # TODO: Implement STT (Speech-to-Text) processing
    await safe_send_message(
        context,
        chat_id,
        "🎙️ Voice message received. Transcription coming soon..."
    )


async def handle_photo_message(update: "Update", context: "ContextTypes.DEFAULT_TYPE"):
    """Handle incoming photo messages - analyze with vision."""
    from bot import (
        is_authorized,
        safe_send_message,
        run_agent_turn,
        send_typing_loop,
    )
    
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    if not is_authorized(user_id):
        return

    # Get photo (highest resolution)
    photo = update.message.photo[-1]
    photo_file = await photo.get_file()
    
    logger.info(f"User {user_id}: Received photo")
    
    # Process with vision capabilities
    async with send_typing_loop(context, chat_id):
        response_data = await run_agent_turn(
            user_id=user_id,
            chat_id=chat_id,
            message_text="[Photo analysis requested]",
            context=context,
            photo_file=photo_file
        )
    
    if response_data.get("response_text"):
        await safe_send_message(context, chat_id, response_data["response_text"])


async def handle_document_message(update: "Update", context: "ContextTypes.DEFAULT_TYPE"):
    """Handle incoming document messages - parse and analyze."""
    from bot import (
        is_authorized,
        safe_send_message,
        run_agent_turn,
        send_typing_loop,
    )
    
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    if not is_authorized(user_id):
        return

    document = update.message.document
    doc_file = await document.get_file()
    
    logger.info(f"User {user_id}: Received document {document.file_name}")
    
    # Download document
    doc_path = f"/tmp/doc_{user_id}_{document.file_name}"
    await doc_file.download_to_drive(doc_path)
    
    async with send_typing_loop(context, chat_id):
        response_data = await run_agent_turn(
            user_id=user_id,
            chat_id=chat_id,
            message_text=f"[Document: {document.file_name}]",
            context=context,
            document_path=doc_path
        )
    
    if response_data.get("response_text"):
        await safe_send_message(context, chat_id, response_data["response_text"])
