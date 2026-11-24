"""Fake Worker Pool untuk tes `swarm/engine/parallel.py`.

Menyediakan `FakeTaskGroup` yang meniru `asyncio.TaskGroup`
tapi menjalankan task secara sequential/deterministik —
memudahkan assertion urutan & error handling.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Coroutine
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import pytest


@dataclass
class TaskRecord:
    name: str
    coro_name: str
    args: tuple
    kwargs: dict
    result: Any = None
    exception: BaseException | None = None
    started_at: float = 0.0
    finished_at: float = 0.0


class FakeTaskGroup:
    """TaskGroup palsu — jalankan task sequential, catat semua."""

    def __init__(self, *, fail_fast: bool = True):
        self._tasks: list[TaskRecord] = []
        self._fail_fast = fail_fast
        self._entered = False

    async def __aenter__(self) -> FakeTaskGroup:
        self._entered = True
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> bool:
        self._entered = False
        return False  # jangan suppress exception

    def create_task(
        self,
        coro: Coroutine[Any, Any, Any],
        *,
        name: str | None = None,
    ) -> asyncio.Task:
        if not self._entered:
            raise RuntimeError("Task group not entered")

        task_name = name or getattr(coro, "__name__", "anonymous")
        record = TaskRecord(
            name=task_name,
            coro_name=task_name,
            args=(),
            kwargs={},
        )
        self._tasks.append(record)

        async def _wrapper() -> Any:
            import time
            record.started_at = time.monotonic()
            try:
                result = await coro
            except BaseException as e:
                record.exception = e
                if self._fail_fast:
                    raise
                return None
            else:
                record.result = result
                return result
            finally:
                record.finished_at = time.monotonic()

        return asyncio.create_task(_wrapper(), name=task_name)

    def get_records(self) -> list[TaskRecord]:
        return list(self._tasks)

    def get_results(self) -> list[Any]:
        return [r.result for r in self._tasks if r.exception is None]

    def get_exceptions(self) -> list[BaseException]:
        return [r.exception for r in self._tasks if r.exception is not None]

    def assert_all_succeeded(self) -> None:
        failed = [r for r in self._tasks if r.exception is not None]
        assert not failed, f"{len(failed)} task gagal: {[str(r.exception) for r in failed]}"

    def assert_task_order(self, expected_names: list[str]) -> None:
        actual = [r.name for r in self._tasks]
        assert actual == expected_names, f"Urutan task: expected {expected_names}, got {actual}"


class SequentialTaskGroup(FakeTaskGroup):
    """TaskGroup yang mengeksekusi task **sequential** (bukan concurrent)."""

    def __init__(self, *, fail_fast: bool = True):
        super().__init__(fail_fast=fail_fast)
        self._pending: list[tuple[Coroutine, str]] = []

    def create_task(
        self,
        coro: Coroutine[Any, Any, Any],
        *,
        name: str | None = None,
    ) -> asyncio.Task:
        task_name = name or getattr(coro, "__name__", "anonymous")
        self._pending.append((coro, task_name))
        # Return dummy task — eksekusi real di __aexit__
        async def _dummy() -> None:
            pass
        return asyncio.create_task(_dummy(), name=task_name)

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> bool:
        # Eksekusi sequential semua pending
        for coro, name in self._pending:
            record = TaskRecord(name=name, coro_name=name, args=(), kwargs={})
            self._tasks.append(record)
            import time
            record.started_at = time.monotonic()
            try:
                result = await coro
                record.result = result
            except BaseException as e:
                record.exception = e
                if self._fail_fast:
                    record.finished_at = time.monotonic()
                    self._entered = False
                    return False
            finally:
                record.finished_at = time.monotonic()
        self._entered = False
        return False


# --- Context Manager Helper ---

@asynccontextmanager
async def fake_task_group(fail_fast: bool = True) -> AsyncGenerator[FakeTaskGroup, None]:
    """Context manager singkat untuk FakeTaskGroup."""
    group = FakeTaskGroup(fail_fast=fail_fast)
    async with group:
        yield group


@asynccontextmanager
async def sequential_task_group(fail_fast: bool = True) -> AsyncGenerator[SequentialTaskGroup, None]:
    group = SequentialTaskGroup(fail_fast=fail_fast)
    async with group:
        yield group


# --- Pytest Fixtures ---

@pytest.fixture
def fake_task_group_fixture() -> FakeTaskGroup:
    """FakeTaskGroup fixture — gunakan via `async with`."""
    return FakeTaskGroup()


@pytest.fixture
def sequential_task_group_fixture() -> SequentialTaskGroup:
    return SequentialTaskGroup()


# --- Patch Helper untuk alfa.swarm.engine.parallel ---

def patch_parallel_task_group(
    monkeypatch: pytest.MonkeyPatch,
    group_class: type[FakeTaskGroup] = FakeTaskGroup,
) -> None:
    """Patch `asyncio.TaskGroup` di modul parallel dengan FakeTaskGroup."""
    import alfa.swarm.engine.parallel as parallel_mod

    @asynccontextmanager
    async def _fake_task_group() -> AsyncGenerator[FakeTaskGroup, None]:
        group = group_class()
        async with group:
            yield group

    monkeypatch.setattr(parallel_mod.asyncio, "TaskGroup", _fake_task_group)
    # Juga patch `asyncio.create_task` kalau dipakai langsung
    original_create_task = asyncio.create_task

    def _create_task(coro, *, name=None):
        return original_create_task(coro, name=name)

    monkeypatch.setattr(parallel_mod.asyncio, "create_task", _create_task)
