"""ALFA Dashboard Route Modules."""

from alfa.dashboard.routes.auth import auth_router
from alfa.dashboard.routes.chat import chat_router
from alfa.dashboard.routes.swarm import swarm_router
from alfa.dashboard.routes.system import system_router
from alfa.dashboard.routes.tools import tools_router
from alfa.dashboard.routes.webhook import webhook_router

__all__ = [
    "auth_router",
    "chat_router",
    "swarm_router",
    "system_router",
    "tools_router",
    "webhook_router",
]
