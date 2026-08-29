"""Memory & Knowledge Tools for ALFA Agent."""

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


def save_knowledge_memory(key_topic: str, content: str, category: str = "general") -> Dict[str, Any]:
    """Save knowledge to persistent memory."""
    try:
        import database
        from tools import current_user_id_var
        
        user_id = current_user_id_var.get()
        if not user_id:
            return {"status": "error", "error": "User ID not set"}
        
        with database.get_sync_db() as conn:
            conn.execute(
                "INSERT INTO knowledge_memory (user_id, key_topic, content, category) VALUES (?, ?, ?, ?)",
                (user_id, key_topic, content, category)
            )
            conn.commit()
        
        return {
            "status": "success",
            "message": f"Saved memory: {key_topic}"
        }
    except Exception as e:
        logger.error(f"Save memory error: {e}")
        return {"status": "error", "error": str(e)}


def search_knowledge_memory(query: str) -> Dict[str, Any]:
    """Search knowledge memory by query."""
    try:
        import database
        from tools import current_user_id_var
        
        user_id = current_user_id_var.get()
        if not user_id:
            return {"status": "error", "error": "User ID not set"}
        
        with database.get_sync_db() as conn:
            results = conn.execute(
                "SELECT key_topic, content, category FROM knowledge_memory "
                "WHERE user_id = ? AND (key_topic LIKE ? OR content LIKE ?)",
                (user_id, f"%{query}%", f"%{query}%")
            ).fetchall()
        
        return {
            "status": "success",
            "message": f"Found {len(results)} memories",
            "data": [
                {"topic": r[0], "content": r[1][:200], "category": r[2]}
                for r in results
            ]
        }
    except Exception as e:
        logger.error(f"Search memory error: {e}")
        return {"status": "error", "error": str(e)}


def extract_and_link_knowledge(entity: str, relation: str, target_value: str, 
                                category: str = "general", tags: str = "") -> Dict[str, Any]:
    """Extract and link knowledge entities."""
    try:
        content = f"{entity} {relation} {target_value}"
        return save_knowledge_memory(entity, content, category)
    except Exception as e:
        logger.error(f"Extract knowledge error: {e}")
        return {"status": "error", "error": str(e)}


def export_knowledge_base(format: str = "markdown") -> Dict[str, Any]:
    """Export the knowledge base."""
    try:
        import database
        from tools import current_user_id_var
        
        user_id = current_user_id_var.get()
        if not user_id:
            return {"status": "error", "error": "User ID not set"}
        
        with database.get_sync_db() as conn:
            memories = conn.execute(
                "SELECT key_topic, content, category FROM knowledge_memory WHERE user_id = ?",
                (user_id,)
            ).fetchall()
        
        if format == "markdown":
            output = "# Knowledge Base Export\n\n"
            for topic, content, category in memories:
                output += f"## {topic} [{category}]\n\n{content}\n\n"
        else:
            output = [{"topic": m[0], "content": m[1], "category": m[2]} for m in memories]
        
        return {
            "status": "success",
            "message": f"Exported {len(memories)} memories",
            "data": output
        }
    except Exception as e:
        logger.error(f"Export knowledge error: {e}")
        return {"status": "error", "error": str(e)}
