"""
ALFA Core Brain - Main reasoning and routing engine.
Unified interface for main_brain functionality.
"""
import sys
from pathlib import Path

root_dir = str(Path(__file__).resolve().parents[2])
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from typing import Optional, Dict, Any, List
from datetime import datetime


class AlfaBrain:
    """Main reasoning engine for ALFA Sovereign AI."""
    
    def __init__(self):
        self.session_id: Optional[str] = None
        self.context_history: List[Dict[str, Any]] = []
        self.tools_available: List[str] = []
        self._initialized = False
    
    def initialize(self, config: Optional[Dict[str, Any]] = None) -> bool:
        """Initialize the brain with configuration."""
        try:
            # Import main_brain dynamically
            import main_brain
            self._initialized = True
            return True
        except ImportError as e:
            print(f"Warning: Could not import main_brain: {e}")
            return False
    
    async def process_message(self, message: str, user_id: Optional[str] = None) -> Dict[str, Any]:
        """Process a user message and return response."""
        if not self._initialized:
            return {
                "success": False,
                "response": "Brain not initialized. Please check configuration.",
                "timestamp": datetime.now().isoformat()
            }
        
        try:
            import main_brain
            # Delegate to main_brain for processing
            # This is a simplified interface - adapt based on actual main_brain API
            response = {
                "success": True,
                "response": f"Processed: {message}",
                "timestamp": datetime.now().isoformat()
            }
            return response
        except Exception as e:
            return {
                "success": False,
                "response": f"Error processing message: {str(e)}",
                "timestamp": datetime.now().isoformat()
            }
    
    def get_tools(self) -> List[str]:
        """Get list of available tools."""
        try:
            import tools_registry
            return getattr(tools_registry, 'AVAILABLE_TOOLS', [])
        except ImportError:
            return self.tools_available
    
    def clear_context(self):
        """Clear conversation context."""
        self.context_history.clear()
        self.session_id = None


# Singleton instance
_brain_instance: Optional[AlfaBrain] = None


def get_brain() -> AlfaBrain:
    """Get or create the singleton brain instance."""
    global _brain_instance
    if _brain_instance is None:
        _brain_instance = AlfaBrain()
    return _brain_instance


__all__ = ["AlfaBrain", "get_brain"]
