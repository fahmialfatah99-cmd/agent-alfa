"""Harness package untuk tes hermetic ALFA OS.

Exports:
- ptb_app: TestApplication, build_test_application
- discord_client: FakeDiscordClient, FakeChannel, FakeMessage, FakeInteraction, fixtures
- fake_llm: DeterministicLLM, RecordingBackend, ReplayBackend, FakeBackend, fixtures
- worker_pool: FakeTaskGroup, SequentialTaskGroup, patch_parallel_task_group
"""

from tests.harness.discord_client import (
    FakeChannel,
    FakeCommandTree,
    FakeDiscordClient,
    FakeGuild,
    FakeInteraction,
    FakeMessage,
    FakeUser,
)
from tests.harness.fake_llm import (
    DeterministicLLM,
    FakeBackend,
    LLMMode,
    LLMRequest,
    LLMResponse,
    RecordingBackend,
    ReplayBackend,
    get_fixture_path,
    llm_mode,
    patch_llm_module,
)
from tests.harness.ptb_app import TestApplication, build_test_application
from tests.harness.worker_pool import (
    FakeTaskGroup,
    SequentialTaskGroup,
    TaskRecord,
    fake_task_group,
    patch_parallel_task_group,
    sequential_task_group,
)

__all__ = [
    # ptb_app
    "TestApplication",
    "build_test_application",
    # discord_client
    "FakeDiscordClient",
    "FakeUser",
    "FakeGuild",
    "FakeChannel",
    "FakeMessage",
    "FakeInteraction",
    "FakeCommandTree",
    # fake_llm
    "DeterministicLLM",
    "LLMRequest",
    "LLMResponse",
    "RecordingBackend",
    "ReplayBackend",
    "FakeBackend",
    "LLMMode",
    "llm_mode",
    "get_fixture_path",
    "patch_llm_module",
    # worker_pool
    "FakeTaskGroup",
    "SequentialTaskGroup",
    "TaskRecord",
    "fake_task_group",
    "sequential_task_group",
    "patch_parallel_task_group",
]
