"""System routes package decomposing telemetry, pipelines, workspace, vault, settings, scrapers, whatsapp, gdrive, and keys."""

from fastapi import APIRouter

from alfa.dashboard.routes.system.telemetry import router as telemetry_router
from alfa.dashboard.routes.system.pipelines_memory import router as pipelines_memory_router
from alfa.dashboard.routes.system.workspace_vault import (
    WORKSPACE_ROOTS,
    _WS_MAX_FILE_BYTES,
    _WS_SKIP_DIRS,
    _safe_workspace_path,
    _ws_real_path,
    router as workspace_vault_router,
)
from alfa.dashboard.routes.system.settings_admin import router as settings_admin_router
from alfa.dashboard.routes.system.scrapers import router as scrapers_router
from alfa.dashboard.routes.system.whatsapp import router as whatsapp_router
from alfa.dashboard.routes.system.gdrive import router as gdrive_router
from alfa.dashboard.routes.system.keys_models import router as keys_models_router

system_router = APIRouter(tags=["system"])

# Flatten all sub-routes directly onto system_router for full backward-compatibility with tests & introspectors
_sub_routers = [
    telemetry_router,
    pipelines_memory_router,
    workspace_vault_router,
    settings_admin_router,
    scrapers_router,
    whatsapp_router,
    gdrive_router,
    keys_models_router,
]
for _sub in _sub_routers:
    system_router.routes.extend(_sub.routes)

__all__ = [
    "system_router",
    "telemetry_router",
    "pipelines_memory_router",
    "workspace_vault_router",
    "settings_admin_router",
    "scrapers_router",
    "whatsapp_router",
    "gdrive_router",
    "keys_models_router",
    "WORKSPACE_ROOTS",
    "_WS_SKIP_DIRS",
    "_WS_MAX_FILE_BYTES",
    "_ws_real_path",
    "_safe_workspace_path",
]
