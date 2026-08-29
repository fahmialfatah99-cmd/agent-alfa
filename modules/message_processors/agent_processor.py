"""Core Agent Processing Logic."""

import logging
from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:
    from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)


async def run_agent_turn(
    user_id: int,
    chat_id: int,
    message_text: str,
    context: "ContextTypes.DEFAULT_TYPE",
    photo_file: Optional[Any] = None,
    document_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Execute an agent turn with the main brain.
    
    Args:
        user_id: Telegram user ID
        chat_id: Telegram chat ID  
        message_text: User's message text
        context: Telegram context
        photo_file: Optional photo file object
        document_path: Optional path to downloaded document
        
    Returns:
        Dict with response_text and other metadata
    """
    import main_brain
    import database
    import permission_gate
    from tools import current_user_id_var, get_current_chat_id
    
    # Get main brain configuration
    brain = main_brain.get_main_brain()
    
    # Set context variables for tool isolation
    current_user_id_var.set(user_id)
    get_current_chat_id().set(chat_id)
    
    # Permission gate for dangerous operations
    approval_gate = permission_gate.make_gate(chat_id)
    
    # Build conversation history
    try:
        with database.get_sync_db() as conn:
            history = conn.execute(
                "SELECT role, content FROM messages "
                "WHERE user_id = ? ORDER BY created_at DESC LIMIT 20",
                (user_id,)
            ).fetchall()
            history = list(reversed(history))
    except Exception as e:
        logger.error(f"Error loading history: {e}")
        history = []
    
    # Prepare user message with optional multimodal parts
    user_message = {"role": "user", "content": message_text}
    if photo_file:
        # TODO: Add vision support
        pass
    if document_path:
        # TODO: Add document parsing
        pass
    
    # Call main brain API
    try:
        # This is a simplified call - actual implementation depends on main_brain module
        response_text = f"[Agent response to: {message_text[:50]}...]"
        
        # Save to history
        with database.get_sync_db() as conn:
            conn.execute(
                "INSERT INTO messages (user_id, role, content) VALUES (?, ?, ?)",
                (user_id, "user", message_text)
            )
            conn.execute(
                "INSERT INTO messages (user_id, role, content) VALUES (?, ?, ?)",
                (user_id, "assistant", response_text)
            )
            conn.commit()
            
    except Exception as e:
        logger.error(f"Agent processing error: {e}")
        response_text = f"❌ Error: {str(e)}"
    
    return {"response_text": response_text}
