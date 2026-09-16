# -*- coding: utf-8 -*-
"""
System Tools Modular Package for ALFA.
Deconstructs monolithic system tooling into single-responsibility modules:
- constants: Paths, limits, regex blockers, hints
- execution: Bash & Python sandboxed execution
- monitoring: System metrics, processes, hardware, guardian, and ambient loop configs
- network: Network scanning, port auditing, SSH, email, and downloads
- management: API keys, custom agents, meetings, subagents, recurring tasks, plugins
- integrations: Productivity, focus, password generation, WhatsApp bot, Android, SQLite
"""

from alfa.tools.system.constants import (
    SANDBOX_DIR,
    _sandbox_base,
    _BASH_BLOCK_PATTERNS,
    _RM_DANGER_TARGETS,
    _DOCKER_AVAILABLE_CACHE,
    _SANDBOX_IMAGE,
    _SOURCE_CODE_EXTS,
    _docker_available,
    _check_docker_available,
    _ensure_sandbox_image,
    normalize_path,
    _bash_blocked_reason,
    _clean_code_snippet,
    generate_self_heal_hint,
    is_internal_sandbox_artifact,
    is_source_code_file,
)

# Alias for convenience if needed
SYSTEM_SANDBOX_DIR = SANDBOX_DIR

from alfa.tools.system.execution import (
    execute_bash_command,
    execute_python_sandbox,
)

from alfa.tools.system.monitoring import (
    get_system_stats,
    control_linux_hardware,
    list_running_processes,
    kill_process,
    clean_system_storage,
    manage_system_services,
    manage_crontab_jobs,
    auto_diagnose_and_heal_system,
    self_restart_service,
    proactive_system_guardian_config,
    proactive_ambient_agent_config,
)

from alfa.tools.system.network import (
    scan_local_network,
    audit_network_security,
    ssh_execute_command,
    send_email,
    download_file_from_url,
)

from alfa.tools.system.management import (
    self_add_new_tool,
    list_dynamic_plugins,
    delete_dynamic_plugin,
    query_token_usage,
    open_web_dashboard,
    manage_api_keys,
    manage_custom_agents,
    conduct_ai_meeting,
    spawn_background_subagent,
    check_subagent_status,
    add_recurring_task,
    list_recurring_tasks,
    cancel_recurring_task,
)

from alfa.tools.system.integrations import (
    schedule_reminder,
    generate_secure_password,
    start_focus_session,
    manage_wa_sheets_bot,
    list_wa_drive_uploads,
    scrcpy_android_control,
    query_database,
)

__all__ = [
    # constants
    "SANDBOX_DIR",
    "_sandbox_base",
    "SYSTEM_SANDBOX_DIR",
    "_BASH_BLOCK_PATTERNS",
    "_RM_DANGER_TARGETS",
    "_DOCKER_AVAILABLE_CACHE",
    "_SANDBOX_IMAGE",
    "_SOURCE_CODE_EXTS",
    "_docker_available",
    "_check_docker_available",
    "_ensure_sandbox_image",
    "normalize_path",
    "_bash_blocked_reason",
    "_clean_code_snippet",
    "generate_self_heal_hint",
    "is_internal_sandbox_artifact",
    "is_source_code_file",
    # execution
    "execute_bash_command",
    "execute_python_sandbox",
    # monitoring
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
    # network
    "scan_local_network",
    "audit_network_security",
    "ssh_execute_command",
    "send_email",
    "download_file_from_url",
    # management
    "self_add_new_tool",
    "list_dynamic_plugins",
    "delete_dynamic_plugin",
    "query_token_usage",
    "open_web_dashboard",
    "manage_api_keys",
    "manage_custom_agents",
    "conduct_ai_meeting",
    "spawn_background_subagent",
    "check_subagent_status",
    "add_recurring_task",
    "list_recurring_tasks",
    "cancel_recurring_task",
    # integrations
    "schedule_reminder",
    "generate_secure_password",
    "start_focus_session",
    "manage_wa_sheets_bot",
    "list_wa_drive_uploads",
    "scrcpy_android_control",
    "query_database",
]
