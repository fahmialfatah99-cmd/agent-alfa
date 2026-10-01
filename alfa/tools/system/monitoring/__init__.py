"""System monitoring package: telemetry, processes, storage, services, health, guardian."""

from alfa.tools.system.monitoring.guardian import (
    proactive_ambient_agent_config as proactive_ambient_agent_config,
)
from alfa.tools.system.monitoring.guardian import (
    proactive_system_guardian_config as proactive_system_guardian_config,
)
from alfa.tools.system.monitoring.hardware import (
    control_linux_hardware as control_linux_hardware,
)
from alfa.tools.system.monitoring.health import (
    auto_diagnose_and_heal_system as auto_diagnose_and_heal_system,
)
from alfa.tools.system.monitoring.processes import kill_process as kill_process
from alfa.tools.system.monitoring.processes import (
    list_running_processes as list_running_processes,
)
from alfa.tools.system.monitoring.services import (
    manage_crontab_jobs as manage_crontab_jobs,
)
from alfa.tools.system.monitoring.services import (
    manage_system_services as manage_system_services,
)
from alfa.tools.system.monitoring.services import (
    self_restart_service as self_restart_service,
)
from alfa.tools.system.monitoring.stats import get_system_stats as get_system_stats
from alfa.tools.system.monitoring.storage import (
    clean_system_storage as clean_system_storage,
)

__all__ = [
    "get_system_stats",
    "control_linux_hardware",
    "list_running_processes",
    "kill_process",
    "clean_system_storage",
    "manage_system_services",
    "manage_crontab_jobs",
    "auto_diagnose_and_heal_system",
    "self_restart_service",
    "proactive_system_guardian_config",
    "proactive_ambient_agent_config",
]
