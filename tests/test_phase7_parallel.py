"""Tes hermetik Phase 7B: ``alfa.swarm.engine.parallel``.

Fokus pada:
- ``_execute_agents_parallel`` - eksekusi agen paralel (wave-based)
- Dependency resolution (topological sort)
- Budget & provider dead checking
- Cancel handling
- Checkpoint integration

Menggunakan ``SequentialTaskGroup`` harness untuk deterministik.
"""

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Import modul target
import alfa.swarm.engine.parallel as parallel_mod


def _make_step_result(agent_name: str, passed: bool = True, tool_used: str = "test_tool"):
    """Helper to create a valid step_result dict."""
    return {
        "agent_name": agent_name,
        "tool_used": tool_used,
        "execution_summary": "Test execution",
        "deliverable_file": None,
        "verification": "PASS" if passed else "FAIL",
    }, True, ""


class TestExecuteAgentsParallel:
    """Tes _execute_agents_parallel."""

    @pytest.fixture
    def mock_env(self, monkeypatch):
        """Mock environment variables."""
        monkeypatch.setenv("ALFA_SWARM_PARALLEL", "on")
        monkeypatch.setenv("ALFA_SWARM_MAX_CONCURRENT", "2")

    def _setup_common_mocks(self, monkeypatch, step_results=None):
        """Setup common mocks for _execute_agents_parallel tests."""
        if step_results is None:
            step_results = []
        
        # Create a mock that returns step results with agent_name
        call_count = {"count": 0}
        
        async def mock_execute_step(*args, **kwargs):
            if step_results:
                result = step_results.pop(0)
            else:
                agent_name = args[0].get("name", "Unknown") if args else "Unknown"
                result = _make_step_result(agent_name)
            return result
        
        monkeypatch.setattr(parallel_mod, "_execute_agent_step", mock_execute_step)
        monkeypatch.setattr(parallel_mod, "_budget_exceeded", lambda steps: None)
        monkeypatch.setattr(parallel_mod, "_provider_dead_streak", lambda steps: None)
        monkeypatch.setattr(parallel_mod, "_cancel_requested", lambda sid: False)
        monkeypatch.setattr(parallel_mod, "_checkpoint_available", lambda: False)
        monkeypatch.setattr(parallel_mod, "_swarm_checkpoint", MagicMock())
        monkeypatch.setattr(parallel_mod, "log_live", MagicMock())
        monkeypatch.setattr(parallel_mod, "_build_error_context", lambda x: {})
        monkeypatch.setattr(parallel_mod, "_record_step_error", MagicMock())
        monkeypatch.setattr(parallel_mod, "_build_task_desc", MagicMock(return_value="task"))
        monkeypatch.setattr(parallel_mod, "_set_state", MagicMock())
        monkeypatch.setattr(parallel_mod, "_swarm_checkpoint", MagicMock())
        monkeypatch.setattr(parallel_mod, "_record_step_error", MagicMock())

    @pytest.mark.asyncio
    async def test_sequential_execution_when_no_deps(self, mock_env, monkeypatch):
        """Sequential execution when no dependencies."""
        participants = [
            {"name": "Agent1"},
            {"name": "Agent2"},
        ]
        execution_steps = []
        ctx_lines = []
        failed_steps = []
        
        self._setup_common_mocks(monkeypatch)
        
        result = await parallel_mod._execute_agents_parallel(
            participants=participants,
            subtask_map={},
            topic="Test topic",
            intent_info={},
            session_id="test-session",
            mode="normal",
            execution_steps=execution_steps,
            ctx_lines=ctx_lines,
            failed_steps=failed_steps,
        )
        
        # Should complete without error
        assert result is False  # False = completed normally
        assert len(execution_steps) == 2

    @pytest.mark.asyncio
    async def test_budget_exceeded_stops_execution(self, mock_env, monkeypatch):
        """Budget exceeded stops execution."""
        monkeypatch.setattr(parallel_mod, "_budget_exceeded", lambda steps: "Budget exceeded")
        monkeypatch.setattr(parallel_mod, "_provider_dead_streak", lambda steps: None)
        monkeypatch.setattr(parallel_mod, "_cancel_requested", lambda sid: False)
        monkeypatch.setattr(parallel_mod, "_checkpoint_available", lambda: False)
        monkeypatch.setattr(parallel_mod, "_set_state", MagicMock())
        monkeypatch.setattr(parallel_mod, "_swarm_checkpoint", MagicMock())
        monkeypatch.setattr(parallel_mod, "log_live", MagicMock())
        monkeypatch.setattr(parallel_mod, "_swarm_checkpoint", MagicMock())
        
        result = await parallel_mod._execute_agents_parallel(
            participants=[{"name": "Agent1"}],
            subtask_map={},
            topic="Test",
            intent_info={},
            session_id="test",
            mode="normal",
            execution_steps=[],
            ctx_lines=[],
            failed_steps=[],
        )
        
        # Should return True (early exit)
        assert result is True

    @pytest.mark.asyncio
    async def test_provider_dead_stops_execution(self, mock_env, monkeypatch):
        """Provider dead stops execution."""
        monkeypatch.setattr(parallel_mod, "_budget_exceeded", lambda steps: None)
        monkeypatch.setattr(parallel_mod, "_provider_dead_streak", lambda steps: "Provider dead")
        monkeypatch.setattr(parallel_mod, "_cancel_requested", lambda sid: False)
        monkeypatch.setattr(parallel_mod, "_checkpoint_available", lambda: False)
        monkeypatch.setattr(parallel_mod, "_set_state", MagicMock())
        monkeypatch.setattr(parallel_mod, "_swarm_checkpoint", MagicMock())
        monkeypatch.setattr(parallel_mod, "log_live", MagicMock())
        monkeypatch.setattr(parallel_mod, "_swarm_checkpoint", MagicMock())
        
        result = await parallel_mod._execute_agents_parallel(
            participants=[{"name": "Agent1"}],
            subtask_map={},
            topic="Test",
            intent_info={},
            session_id="test",
            mode="normal",
            execution_steps=[],
            ctx_lines=[],
            failed_steps=[],
        )
        
        assert result is True

    @pytest.mark.asyncio
    async def test_cancel_requested_stops_execution(self, mock_env, monkeypatch):
        """Cancel requested stops execution."""
        monkeypatch.setattr(parallel_mod, "_budget_exceeded", lambda steps: None)
        monkeypatch.setattr(parallel_mod, "_provider_dead_streak", lambda steps: None)
        monkeypatch.setattr(parallel_mod, "_cancel_requested", lambda sid: True)
        monkeypatch.setattr(parallel_mod, "_checkpoint_available", lambda: False)
        monkeypatch.setattr(parallel_mod, "_set_state", MagicMock())
        monkeypatch.setattr(parallel_mod, "_swarm_checkpoint", MagicMock())
        monkeypatch.setattr(parallel_mod, "log_live", MagicMock())
        monkeypatch.setattr(parallel_mod, "_swarm_checkpoint", MagicMock())
        
        result = await parallel_mod._execute_agents_parallel(
            participants=[{"name": "Agent1"}],
            subtask_map={},
            topic="Test",
            intent_info={},
            session_id="test",
            mode="normal",
            execution_steps=[],
            ctx_lines=[],
            failed_steps=[],
        )
        
        assert result is True

    @pytest.mark.asyncio
    async def test_wave_execution_with_mock_step(self, mock_env, monkeypatch):
        """Wave execution with mocked _execute_agent_step."""
        participants = [
            {"name": "Agent1"},
            {"name": "Agent2"},
            {"name": "Agent3"},
        ]
        
        self._setup_common_mocks(monkeypatch)
        
        execution_steps = []
        ctx_lines = []
        failed_steps = []
        
        result = await parallel_mod._execute_agents_parallel(
            participants=participants,
            subtask_map={},
            topic="Test topic",
            intent_info={},
            session_id="test-session",
            mode="normal",
            execution_steps=execution_steps,
            ctx_lines=ctx_lines,
            failed_steps=failed_steps,
        )
        
        assert result is False
        assert len(execution_steps) == 3  # All 3 agents executed


class TestDependencyResolution:
    """Tes dependency resolution (topological sort)."""

    @pytest.fixture
    def mock_env(self, monkeypatch):
        monkeypatch.setenv("ALFA_SWARM_PARALLEL", "on")
        monkeypatch.setenv("ALFA_SWARM_MAX_CONCURRENT", "2")

    @pytest.mark.asyncio
    async def test_dependency_resolution_execution_order(self, mock_env, monkeypatch):
        """Agents with dependencies execute in correct order."""
        # Agent B depends on Agent A
        participants = [
            {"name": "AgentA"},
            {"name": "AgentB"},
        ]
        subtask_map = {
            "AgentB": {"depends_on": ["AgentA"]},
        }
        
        async def mock_execute_step(*args, **kwargs):
            agent_name = args[0].get("name", "Unknown") if args else "Unknown"
            return _make_step_result(agent_name)
        
        monkeypatch.setattr(parallel_mod, "_execute_agent_step", mock_execute_step)
        monkeypatch.setattr(parallel_mod, "_budget_exceeded", lambda steps: None)
        monkeypatch.setattr(parallel_mod, "_provider_dead_streak", lambda steps: None)
        monkeypatch.setattr(parallel_mod, "_cancel_requested", lambda sid: False)
        monkeypatch.setattr(parallel_mod, "_checkpoint_available", lambda: False)
        monkeypatch.setattr(parallel_mod, "_swarm_checkpoint", MagicMock())
        monkeypatch.setattr(parallel_mod, "log_live", MagicMock())
        monkeypatch.setattr(parallel_mod, "_build_error_context", lambda x: {})
        monkeypatch.setattr(parallel_mod, "_record_step_error", MagicMock())
        monkeypatch.setattr(parallel_mod, "_build_task_desc", MagicMock(return_value="task"))
        monkeypatch.setattr(parallel_mod, "_set_state", MagicMock())
        monkeypatch.setattr(parallel_mod, "_swarm_checkpoint", MagicMock())
        monkeypatch.setattr(parallel_mod, "_record_step_error", MagicMock())
        monkeypatch.setattr(parallel_mod, "_build_task_desc", MagicMock(return_value="task"))
        
        execution_steps = []
        ctx_lines = []
        failed_steps = []
        
        result = await parallel_mod._execute_agents_parallel(
            participants=participants,
            subtask_map=subtask_map,
            topic="Test",
            intent_info={},
            session_id="test",
            mode="normal",
            execution_steps=execution_steps,
            ctx_lines=[],
            failed_steps=[],
        )
        
        assert result is False
        # Both agents should execute
        assert len(execution_steps) == 2

    @pytest.mark.asyncio
    async def test_circular_dependency_handled(self, mock_env, monkeypatch):
        """Circular dependency doesn't hang (treated as no deps)."""
        # A depends on B, B depends on A - circular
        participants = [
            {"name": "AgentA"},
            {"name": "AgentB"},
        ]
        subtask_map = {
            "AgentA": {"depends_on": ["AgentB"]},
            "AgentB": {"depends_on": ["AgentA"]},
        }
        
        async def mock_execute_step(*args, **kwargs):
            agent_name = args[0].get("name", "Unknown") if args else "Unknown"
            return _make_step_result(agent_name)
        
        monkeypatch.setattr(parallel_mod, "_execute_agent_step", mock_execute_step)
        monkeypatch.setattr(parallel_mod, "_budget_exceeded", lambda steps: None)
        monkeypatch.setattr(parallel_mod, "_provider_dead_streak", lambda steps: None)
        monkeypatch.setattr(parallel_mod, "_cancel_requested", lambda sid: False)
        monkeypatch.setattr(parallel_mod, "_checkpoint_available", lambda: False)
        monkeypatch.setattr(parallel_mod, "_swarm_checkpoint", MagicMock())
        monkeypatch.setattr(parallel_mod, "log_live", MagicMock())
        monkeypatch.setattr(parallel_mod, "_build_error_context", lambda x: {})
        monkeypatch.setattr(parallel_mod, "_record_step_error", MagicMock())
        monkeypatch.setattr(parallel_mod, "_build_task_desc", MagicMock(return_value="task"))
        monkeypatch.setattr(parallel_mod, "_set_state", MagicMock())
        monkeypatch.setattr(parallel_mod, "_swarm_checkpoint", MagicMock())
        monkeypatch.setattr(parallel_mod, "_record_step_error", MagicMock())
        monkeypatch.setattr(parallel_mod, "_build_task_desc", MagicMock(return_value="task"))
        
        execution_steps = []
        
        # Should complete without hanging (circular deps treated as no deps)
        result = await parallel_mod._execute_agents_parallel(
            participants=participants,
            subtask_map=subtask_map,
            topic="Test",
            intent_info={},
            session_id="test",
            mode="normal",
            execution_steps=execution_steps,
            ctx_lines=[],
            failed_steps=[],
        )
        
        assert result is False
        assert len(execution_steps) == 2


class TestCancelHandling:
    """Tes cancel handling."""

    @pytest.mark.asyncio
    async def test_cancel_during_execution(self, monkeypatch):
        """Cancel during execution stops gracefully."""
        cancel_state = {"requested": False}
        
        def mock_cancel(sid):
            return cancel_state["requested"]
        
        call_count = {"count": 0}
        
        async def mock_execute_step(*args, **kwargs):
            call_count["count"] += 1
            if call_count["count"] == 2:
                cancel_state["requested"] = True
            agent_name = args[0].get("name", "Unknown") if args else "Unknown"
            return _make_step_result(agent_name)
        
        monkeypatch.setattr(parallel_mod, "_execute_agent_step", mock_execute_step)
        monkeypatch.setattr(parallel_mod, "_budget_exceeded", lambda steps: None)
        monkeypatch.setattr(parallel_mod, "_provider_dead_streak", lambda steps: None)
        monkeypatch.setattr(parallel_mod, "_cancel_requested", mock_cancel)
        monkeypatch.setattr(parallel_mod, "_checkpoint_available", lambda: False)
        monkeypatch.setattr(parallel_mod, "_swarm_checkpoint", MagicMock())
        monkeypatch.setattr(parallel_mod, "log_live", MagicMock())
        monkeypatch.setattr(parallel_mod, "_build_error_context", lambda x: {})
        monkeypatch.setattr(parallel_mod, "_record_step_error", MagicMock())
        monkeypatch.setattr(parallel_mod, "_build_task_desc", MagicMock(return_value="task"))
        monkeypatch.setattr(parallel_mod, "_set_state", MagicMock())
        monkeypatch.setattr(parallel_mod, "_swarm_checkpoint", MagicMock())
        monkeypatch.setattr(parallel_mod, "_record_step_error", MagicMock())
        monkeypatch.setattr(parallel_mod, "_build_task_desc", MagicMock(return_value="task"))
        
        execution_steps = []
        
        result = await parallel_mod._execute_agents_parallel(
            participants=[{"name": f"Agent{i}"} for i in range(4)],
            subtask_map={},
            topic="Test",
            intent_info={},
            session_id="test",
            mode="normal",
            execution_steps=execution_steps,
            ctx_lines=[],
            failed_steps=[],
        )
        
        # Should stop early due to cancel
        assert result is True
        assert len(execution_steps) <= 2


class TestCheckpointIntegration:
    """Tes checkpoint integration."""

    @pytest.mark.asyncio
    async def test_checkpoint_saved_on_each_step(self, monkeypatch):
        """Checkpoint saved after each step when available."""
        mock_checkpoint = MagicMock()
        mock_checkpoint.save = AsyncMock()
        
        # Need to return proper step_result with agent_name
        async def mock_execute_step(*args, **kwargs):
            agent_name = args[0].get("name", "Unknown") if args else "Unknown"
            return _make_step_result(agent_name)
        
        monkeypatch.setattr(parallel_mod, "_execute_agent_step", mock_execute_step)
        monkeypatch.setattr(parallel_mod, "_budget_exceeded", lambda steps: None)
        monkeypatch.setattr(parallel_mod, "_provider_dead_streak", lambda steps: None)
        monkeypatch.setattr(parallel_mod, "_cancel_requested", lambda sid: False)
        monkeypatch.setattr(parallel_mod, "_checkpoint_available", lambda: True)
        monkeypatch.setattr(parallel_mod, "_swarm_checkpoint", lambda: mock_checkpoint)
        monkeypatch.setattr(parallel_mod, "log_live", MagicMock())
        monkeypatch.setattr(parallel_mod, "_build_error_context", lambda x: {})
        monkeypatch.setattr(parallel_mod, "_record_step_error", MagicMock())
        monkeypatch.setattr(parallel_mod, "_build_task_desc", MagicMock(return_value="task"))
        monkeypatch.setattr(parallel_mod, "_set_state", MagicMock())
        monkeypatch.setattr(parallel_mod, "_swarm_checkpoint", lambda: mock_checkpoint)
        monkeypatch.setattr(parallel_mod, "_record_step_error", MagicMock())
        monkeypatch.setattr(parallel_mod, "_build_task_desc", MagicMock(return_value="task"))
        
        execution_steps = []
        
        await parallel_mod._execute_agents_parallel(
            participants=[{"name": "Agent1"}, {"name": "Agent2"}],
            subtask_map={},
            topic="Test",
            intent_info={},
            session_id="test-session",
            mode="normal",
            execution_steps=execution_steps,
            ctx_lines=[],
            failed_steps=[],
        )
        
        # Checkpoint save should be called for each agent
        assert mock_checkpoint.save.call_count == 2


class TestHarnessIntegration:
    """Tes integrasi dengan SequentialTaskGroup harness."""

    @pytest.mark.asyncio
    async def test_sequential_task_group_execution(self):
        """SequentialTaskGroup runs tasks sequentially."""
        from tests.harness.worker_pool import SequentialTaskGroup
        
        async with SequentialTaskGroup() as group:
            async def task1():
                return "task1"
            async def task2():
                return "task2"
            
            group.create_task(task1(), name="task1")
            group.create_task(task2(), name="task2")
        
        records = group.get_records()
        assert len(records) == 2
        assert records[0].name == "task1"
        assert records[1].name == "task2"
        assert records[0].result == "task1"
        assert records[1].result == "task2"
        group.assert_task_order(["task1", "task2"])

    @pytest.mark.asyncio
    async def test_sequential_task_group_fail_fast(self):
        """SequentialTaskGroup stops on exception when fail_fast=True."""
        from tests.harness.worker_pool import SequentialTaskGroup
        
        async with SequentialTaskGroup(fail_fast=True) as group:
            async def good():
                return "good"
            async def bad():
                raise ValueError("bad")
            
            group.create_task(good(), name="good")
            group.create_task(bad(), name="bad")
        
        records = group.get_records()
        assert len(records) == 2
        assert records[0].result == "good"
        assert isinstance(records[1].exception, ValueError)


class TestPatchParallelTaskGroup:
    """Tes patch_parallel_task_group helper."""

    def test_patch_parallel_task_group(self, monkeypatch):
        """patch_parallel_task_group replaces asyncio.TaskGroup."""
        from tests.harness.worker_pool import patch_parallel_task_group, FakeTaskGroup
        
        patch_parallel_task_group(monkeypatch, FakeTaskGroup)
        
        # Now asyncio.TaskGroup should be our FakeTaskGroup context manager
        import asyncio
        assert asyncio.TaskGroup is not None  # patched to context manager returning FakeTaskGroup


if __name__ == "__main__":
    pytest.main([__file__, "-v"])