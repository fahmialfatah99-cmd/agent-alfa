# -*- coding: utf-8 -*-
"""
Database Package for ALFA.
Modular structure:
- connection: Connection pool, session context, sync/async init
- crypto: AES-256-GCM encryption at-rest, key masking
- keys: API key multi-provider vault & main brain models
- agents: Workforce agents and round-table meetings
- memory: Knowledge facts, semantic graph, chat history, settings
- tasks: Scheduled cron, reminders, pomodoro, subagents, token telemetry
"""

from alfa.core.db.agents import (
    add_custom_agent_sync,
    create_agent_meeting_sync,
    delete_custom_agent_sync,
    get_agent_meeting_sync,
    get_custom_agent_sync,
    list_agent_meetings_sync,
    list_custom_agents_sync,
    update_custom_agent_sync,
)
from alfa.core.db.connection import (
    DB_PATH,
    REPO_ROOT,
    ConnectionPool,
    get_connection_pool,
    get_sync_db,
    init_db,
    init_db_sync,
)
from alfa.core.db.crypto import (
    _ENC_PREFIX,
    _get_aesgcm,
    decrypt_key,
    encrypt_key,
    mask_key,
    migrate_encrypt_api_keys,
)
from alfa.core.db.keys import (
    activate_api_key_sync,
    add_api_key_sync,
    delete_api_key_sync,
    get_active_api_key_sync,
    get_api_key_by_id_sync,
    get_main_brain_key_id,
    get_main_brain_model,
    list_active_keys_sync,
    list_api_keys_sync,
    set_main_brain_model,
    update_api_key_model,
)
from alfa.core.db.memory import (
    add_knowledge_relation_sync,
    clear_user_chat_history,
    delete_memory,
    export_full_second_brain_sync,
    get_all_knowledge_graph_sync,
    get_all_memories,
    get_recent_chat_history,
    get_user_settings,
    save_chat_message,
    save_memory_fact,
    save_memory_fact_sync,
    search_knowledge_graph_sync,
    search_memories,
    search_memories_sync,
    toggle_voice_setting,
)
from alfa.core.db.tasks import (
    add_cron_job_sync,
    add_reminder,
    add_reminder_sync,
    delete_cron_job_sync,
    get_api_usage_summary_sync,
    get_due_cron_jobs,
    get_due_focus_sessions,
    get_due_reminders,
    get_subagent_task_sync,
    list_agent_activities_sync,
    list_cron_jobs_sync,
    list_subagent_tasks_sync,
    log_agent_activity_sync,
    mark_focus_session_completed,
    mark_reminder_executed,
    record_api_usage_sync,
    save_subagent_task_sync,
    start_focus_session_sync,
    update_cron_job_after_run,
    update_subagent_task_sync,
)

__all__ = [
    # connection
    "REPO_ROOT",
    "DB_PATH",
    "ConnectionPool",
    "get_connection_pool",
    "get_sync_db",
    "init_db_sync",
    "init_db",
    # crypto
    "_ENC_PREFIX",
    "_get_aesgcm",
    "encrypt_key",
    "decrypt_key",
    "mask_key",
    "migrate_encrypt_api_keys",
    # keys
    "list_api_keys_sync",
    "add_api_key_sync",
    "activate_api_key_sync",
    "set_main_brain_model",
    "get_main_brain_model",
    "get_api_key_by_id_sync",
    "get_main_brain_key_id",
    "delete_api_key_sync",
    "get_active_api_key_sync",
    "list_active_keys_sync",
    "update_api_key_model",
    # agents
    "list_custom_agents_sync",
    "add_custom_agent_sync",
    "update_custom_agent_sync",
    "delete_custom_agent_sync",
    "get_custom_agent_sync",
    "create_agent_meeting_sync",
    "list_agent_meetings_sync",
    "get_agent_meeting_sync",
    # memory
    "save_chat_message",
    "get_recent_chat_history",
    "clear_user_chat_history",
    "save_memory_fact_sync",
    "save_memory_fact",
    "search_memories_sync",
    "get_all_memories",
    "search_memories",
    "delete_memory",
    "add_knowledge_relation_sync",
    "search_knowledge_graph_sync",
    "get_all_knowledge_graph_sync",
    "export_full_second_brain_sync",
    "get_user_settings",
    "toggle_voice_setting",
    # tasks
    "add_cron_job_sync",
    "list_cron_jobs_sync",
    "delete_cron_job_sync",
    "get_due_cron_jobs",
    "update_cron_job_after_run",
    "save_subagent_task_sync",
    "update_subagent_task_sync",
    "get_subagent_task_sync",
    "list_subagent_tasks_sync",
    "log_agent_activity_sync",
    "list_agent_activities_sync",
    "add_reminder_sync",
    "add_reminder",
    "get_due_reminders",
    "mark_reminder_executed",
    "start_focus_session_sync",
    "get_due_focus_sessions",
    "mark_focus_session_completed",
    "record_api_usage_sync",
    "get_api_usage_summary_sync",
]
