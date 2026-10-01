"""Main brain engine package (split from the brain.py monolith).

Public names are re-exported here so `from alfa.core import brain` and
`from alfa.core.brain import X` keep working unchanged.
"""

from alfa.core.brain.agentic import run_openai_agentic_turn as run_openai_agentic_turn
from alfa.core.brain.client import get_brain as get_brain
from alfa.core.brain.client import get_main_brain as get_main_brain
from alfa.core.brain.config import _TOOL_KEEP_RECENT as _TOOL_KEEP_RECENT
from alfa.core.brain.config import MAX_ITERATIONS as MAX_ITERATIONS
from alfa.core.brain.config import MAX_TOOL_OUTPUT as MAX_TOOL_OUTPUT
from alfa.core.brain.config import PROJECT_DIR as PROJECT_DIR
from alfa.core.brain.config import REPO_ROOT as REPO_ROOT
from alfa.core.brain.config import TOOL_CONTEXT_BUDGET as TOOL_CONTEXT_BUDGET
from alfa.core.brain.config import TOOL_EXEC_TIMEOUT as TOOL_EXEC_TIMEOUT
from alfa.core.brain.convo import _compact_convo as _compact_convo
from alfa.core.brain.convo import _convo_size as _convo_size
from alfa.core.brain.tool_exec import _clean_json_args as _clean_json_args
from alfa.core.brain.tool_exec import _execute_tool as _execute_tool
from alfa.core.brain.tool_schema import _JSON_TYPES as _JSON_TYPES
from alfa.core.brain.tool_schema import SAFE_TOOL_NAMES as SAFE_TOOL_NAMES
from alfa.core.brain.tool_schema import _find_tool as _find_tool
from alfa.core.brain.tool_schema import _fn_to_openai_tool as _fn_to_openai_tool
from alfa.core.brain.tool_schema import _parse_args_docstring as _parse_args_docstring
from alfa.core.brain.tool_schema import build_openai_tools as build_openai_tools

__all__ = [
    "REPO_ROOT",
    "PROJECT_DIR",
    "MAX_ITERATIONS",
    "MAX_TOOL_OUTPUT",
    "TOOL_EXEC_TIMEOUT",
    "TOOL_CONTEXT_BUDGET",
    "_TOOL_KEEP_RECENT",
    "get_main_brain",
    "get_brain",
    "run_openai_agentic_turn",
    "build_openai_tools",
    "SAFE_TOOL_NAMES",
    "_find_tool",
    "_clean_json_args",
    "_execute_tool",
    "_convo_size",
    "_compact_convo",
    "_parse_args_docstring",
    "_fn_to_openai_tool",
    "_JSON_TYPES",
]
