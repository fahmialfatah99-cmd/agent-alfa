"""Backward-compatibility facade for the split keys/models/antigravity/traces routes.

The 1183-line monolith was decomposed into focused modules; this facade
merges their routers in original order so existing imports
(`from alfa.dashboard.routes.system.keys_models import router, PROVIDER_MODELS`)
keep working unchanged.
"""

from fastapi import APIRouter

from alfa.dashboard.routes.system.antigravity import router as _antigravity_router
from alfa.dashboard.routes.system.keys import router as _keys_router
from alfa.dashboard.routes.system.models_registry import router as _models_router
from alfa.dashboard.routes.system.observability import router as _observability_router
from alfa.dashboard.routes.system.provider_catalog import (
    PROVIDER_MODELS as PROVIDER_MODELS,
)

router = APIRouter()
for _sub in (_keys_router, _models_router, _antigravity_router, _observability_router):
    router.routes.extend(_sub.routes)

__all__ = ["router", "PROVIDER_MODELS"]
