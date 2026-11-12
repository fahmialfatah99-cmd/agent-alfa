"""Mesin multi-agen ALFA (rapat swarm, QA, orkestrasi).

Pecah dari modul monolitik `engine.py` (1.327 baris). **Import path publik
tidak berubah** dan *kontrak patch* tetap utuh: nama yang dipatch test
(`alfa.swarm.engine.<nama>`) tetap milik paket ini, sedangkan sub-modul
membacanya lewat PEP 562 `__getattr__` — sehingga patch/mock tetap memengaruhi
pemanggil internal tanpa mengubah call site.

Sub-modul:
- `_state`       : budget misi, deteksi provider mati, state bersama.
- `modes`        : normalisasi mode swarm.
- `tracing`      : trace rapat (best-effort).
- `parallel`     : eksekusi agen paralel (wave).
- `orchestrator` : loop rapat + QA.
"""

#: Impor asli modul engine (namespace dipertahankan kompatibel).
import asyncio as asyncio
import logging as logging
import os as os
import time as time
import uuid as uuid
from datetime import datetime as datetime
from typing import Any as Any

from alfa import tools as tools
from alfa.core import database as database
from alfa.swarm.deliberation import (
    Proposal as _Proposal,  # noqa: F401 - re-export namespace asli
)
from alfa.swarm.deliberation import (
    Turn as _Turn,  # noqa: F401 - re-export namespace asli
)
from alfa.swarm.deliberation import (
    apply_votes as _apply_votes,  # noqa: F401 - re-export namespace asli
)
from alfa.swarm.deliberation import (
    build_context_digest as _build_context_digest,  # noqa: F401 - re-export namespace asli
)
from alfa.swarm.deliberation import (
    build_proposal_menu as _build_proposal_menu,  # noqa: F401 - re-export namespace asli
)
from alfa.swarm.deliberation import (
    collect_proposals as _collect_proposals,  # noqa: F401 - re-export namespace asli
)
from alfa.swarm.deliberation import (
    parse_turn as _parse_turn,  # noqa: F401 - re-export namespace asli
)
from alfa.swarm.engine._state import (
    _budget_exceeded as _budget_exceeded,  # noqa: F401 - re-export namespace asli
)
from alfa.swarm.engine._state import (
    _provider_dead_streak as _provider_dead_streak,  # noqa: F401 - re-export namespace asli
)
from alfa.swarm.engine._state import (
    _swarm_budget as _swarm_budget,  # noqa: F401 - re-export namespace asli
)
from alfa.swarm.engine.modes import (
    _MODE_ALIASES as _MODE_ALIASES,  # noqa: F401 - re-export namespace asli
)
from alfa.swarm.engine.modes import (
    _SWARM_MODES as _SWARM_MODES,  # noqa: F401 - re-export namespace asli
)
from alfa.swarm.engine.modes import (
    _normalize_swarm_mode as _normalize_swarm_mode,  # noqa: F401 - re-export namespace asli
)
from alfa.swarm.engine.orchestrator import (
    _conduct_multi_agent_meeting_impl as _conduct_multi_agent_meeting_impl,  # noqa: F401 - re-export namespace asli
)
from alfa.swarm.engine.orchestrator import (
    conduct_multi_agent_meeting as conduct_multi_agent_meeting,  # noqa: F401 - re-export namespace asli
)
from alfa.swarm.engine.parallel import (
    _execute_agents_parallel as _execute_agents_parallel,  # noqa: F401 - re-export namespace asli
)
from alfa.swarm.engine.tracing import (
    _record_swarm_trace_safely as _record_swarm_trace_safely,  # noqa: F401 - re-export namespace asli
)
from alfa.swarm.live_logger import (
    _CHECKPOINT_AVAILABLE as _CHECKPOINT_AVAILABLE,  # noqa: F401 - re-export namespace asli
)
from alfa.swarm.live_logger import (
    _append_feed_file as _append_feed_file,  # noqa: F401 - re-export namespace asli
)
from alfa.swarm.live_logger import (
    _build_error_context as _build_error_context,  # noqa: F401 - re-export namespace asli
)
from alfa.swarm.live_logger import (
    _load_last_seq as _load_last_seq,  # noqa: F401 - re-export namespace asli
)
from alfa.swarm.live_logger import (
    _record_step_error as _record_step_error,  # noqa: F401 - re-export namespace asli
)
from alfa.swarm.live_logger import (
    _SwarmCheckpoint as _SwarmCheckpoint,  # noqa: F401 - re-export namespace asli
)
from alfa.swarm.live_logger import (
    detect_task_intent as detect_task_intent,  # noqa: F401 - re-export namespace asli
)
from alfa.swarm.live_logger import (
    log_live as log_live,  # noqa: F401 - re-export namespace asli
)
from alfa.swarm.live_logger import (
    log_tool_live as log_tool_live,  # noqa: F401 - re-export namespace asli
)
from alfa.swarm.live_logger import (
    qa_verdict_passed as qa_verdict_passed,  # noqa: F401 - re-export namespace asli
)
from alfa.swarm.llm_client import (
    KNOWN_OPENAI_PROVIDERS as KNOWN_OPENAI_PROVIDERS,  # noqa: F401 - re-export namespace asli
)
from alfa.swarm.llm_client import (
    _default_gemini_model as _default_gemini_model,  # noqa: F401 - re-export namespace asli
)
from alfa.swarm.llm_client import (
    _generate_with_gemini as _generate_with_gemini,  # noqa: F401 - re-export namespace asli
)
from alfa.swarm.llm_client import (
    _generate_with_openai_compat as _generate_with_openai_compat,  # noqa: F401 - re-export namespace asli
)
from alfa.swarm.llm_client import (
    generate_agent_response as generate_agent_response,  # noqa: F401 - re-export namespace asli
)
from alfa.swarm.llm_client import (
    get_agent_api_client as get_agent_api_client,  # noqa: F401 - re-export namespace asli
)
from alfa.swarm.meeting_steps import (  # noqa: F401 - re-export namespace asli
    _build_task_desc as _build_task_desc,
)
from alfa.swarm.meeting_steps import (
    _execute_agent_step as _execute_agent_step,
)
from alfa.swarm.sessions import resume_swarm_session as resume_swarm_session
from alfa.swarm.step_executor import (
    _decompose_task as _decompose_task,  # noqa: F401 - re-export namespace asli
)
from alfa.swarm.step_executor import (
    _extract_html_doc as _extract_html_doc,  # noqa: F401 - re-export namespace asli
)
from alfa.swarm.step_executor import (
    _forced_json_execution as _forced_json_execution,  # noqa: F401 - re-export namespace asli
)
from alfa.swarm.step_executor import (
    _single_shot_edit_fallback as _single_shot_edit_fallback,  # noqa: F401 - re-export namespace asli
)
from alfa.swarm.step_executor import (
    _verify_step_result as _verify_step_result,  # noqa: F401 - re-export namespace asli
)
from alfa.swarm.step_executor import (
    execute_swarm_task_step as execute_swarm_task_step,  # noqa: F401 - re-export namespace asli
)
from alfa.swarm.step_executor import (
    validate_python_code as validate_python_code,  # noqa: F401 - re-export namespace asli
)
from alfa.swarm.workspace_hygiene import (
    _EXEC_FS_SNAPSHOT as _EXEC_FS_SNAPSHOT,  # noqa: F401 - re-export namespace asli
)
from alfa.swarm.workspace_hygiene import (
    _HARVEST_EXCLUDE as _HARVEST_EXCLUDE,  # noqa: F401 - re-export namespace asli
)
from alfa.swarm.workspace_hygiene import (
    _JUNK_FILE_PATTERNS as _JUNK_FILE_PATTERNS,  # noqa: F401 - re-export namespace asli
)
from alfa.swarm.workspace_hygiene import (
    _SANDBOX_SNAPSHOT as _SANDBOX_SNAPSHOT,  # noqa: F401 - re-export namespace asli
)
from alfa.swarm.workspace_hygiene import (
    _TARGET_FOLDER as _TARGET_FOLDER,  # noqa: F401 - re-export namespace asli
)
from alfa.swarm.workspace_hygiene import (
    CANCEL_FLAG_FILE as CANCEL_FLAG_FILE,  # noqa: F401 - re-export namespace asli
)
from alfa.swarm.workspace_hygiene import (
    LIVE_FEED_FILE as LIVE_FEED_FILE,  # noqa: F401 - re-export namespace asli
)
from alfa.swarm.workspace_hygiene import (
    LIVE_LOG as LIVE_LOG,  # noqa: F401 - re-export namespace asli
)
from alfa.swarm.workspace_hygiene import (
    MAX_QA_ROUNDS as MAX_QA_ROUNDS,  # noqa: F401 - re-export namespace asli
)
from alfa.swarm.workspace_hygiene import (
    MAX_SWARM_AGENTS as MAX_SWARM_AGENTS,  # noqa: F401 - re-export namespace asli
)
from alfa.swarm.workspace_hygiene import (
    MEETING_RUNNING as MEETING_RUNNING,  # noqa: F401 - re-export namespace asli
)
from alfa.swarm.workspace_hygiene import (
    SWARM_OUTPUT_DIR as SWARM_OUTPUT_DIR,  # noqa: F401 - re-export namespace asli
)
from alfa.swarm.workspace_hygiene import (
    _cancel_requested as _cancel_requested,  # noqa: F401 - re-export namespace asli
)
from alfa.swarm.workspace_hygiene import (
    _clear_cancel_flag as _clear_cancel_flag,  # noqa: F401 - re-export namespace asli
)
from alfa.swarm.workspace_hygiene import (
    _fs_changed_since_snapshot as _fs_changed_since_snapshot,  # noqa: F401 - re-export namespace asli
)
from alfa.swarm.workspace_hygiene import (
    _harvest_new_sandbox_projects as _harvest_new_sandbox_projects,  # noqa: F401 - re-export namespace asli
)
from alfa.swarm.workspace_hygiene import (
    _hash_sandbox_projects as _hash_sandbox_projects,  # noqa: F401 - re-export namespace asli
)
from alfa.swarm.workspace_hygiene import (
    _sandbox_project_dirs as _sandbox_project_dirs,  # noqa: F401 - re-export namespace asli
)
from alfa.swarm.workspace_hygiene import (
    request_cancel_swarm as request_cancel_swarm,  # noqa: F401 - re-export namespace asli
)
from alfa.swarm.workspace_hygiene import (
    sanitize_project_directory as sanitize_project_directory,  # noqa: F401 - re-export namespace asli
)

#: State mutable misi (dipakai bersama antar sub-modul & bisa dipatch test).
_BUDGET_EXCEEDED = ""
_PROVIDER_DEAD = ""
_PROVIDER_DEAD_STREAK = 3
_MISSION_START = 0.0
