"""Autonomous multi-agent swarm operations, custom agent workforce, meetings, and affiliate marketing."""

from fastapi import APIRouter

from alfa.dashboard.routes.swarm.affiliate_routes import (
    _parse_ai_sections,
)
from alfa.dashboard.routes.swarm.affiliate_routes import router as affiliate_router
from alfa.dashboard.routes.swarm.agents_routes import router as agents_router
from alfa.dashboard.routes.swarm.live_routes import (
    compute_agent_states,
    compute_consensus_percent,
    detect_active_speaker,
    parse_arena_state,
    parse_swarm_stage,
)
from alfa.dashboard.routes.swarm.live_routes import router as live_router
from alfa.dashboard.routes.swarm.meetings_routes import router as meetings_router

swarm_router = APIRouter(tags=["swarm"])

_sub_routers = [
    affiliate_router,
    agents_router,
    meetings_router,
    live_router,
]
for _sub in _sub_routers:
    swarm_router.routes.extend(_sub.routes)

__all__ = [
    "swarm_router",
    "_parse_ai_sections",
    "affiliate_router",
    "agents_router",
    "meetings_router",
    "live_router",
    "parse_arena_state",
    "parse_swarm_stage",
    "detect_active_speaker",
    "compute_agent_states",
    "compute_consensus_percent",
]
