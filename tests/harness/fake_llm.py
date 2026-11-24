"""Deterministic LLM Harness untuk tes hermetic.

Menyediakan `DeterministicLLM` dengan mode:
- **RECORD**: Panggil LLM nyata, simpan request/response ke JSONL
- **REPLAY**: Baca fixture JSONL, return response deterministik
- **FAKE**: Generator response sederhana tanpa LLM nyata
"""

from __future__ import annotations

import json
import uuid
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest


@dataclass
class LLMRequest:
    prompt: str
    model: str
    temperature: float = 0.7
    max_tokens: int = 4096
    system_prompt: str = ""
    tools: list[dict] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


@dataclass
class LLMResponse:
    text: str
    tool_calls: list[dict] = field(default_factory=list)
    usage: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)


class LLMBackend(ABC):
    """Interface backend LLM."""

    @abstractmethod
    async def complete(self, request: LLMRequest) -> LLMResponse:
        pass


class RecordingBackend(LLMBackend):
    """Backend yang merekam request/response ke file JSONL."""

    def __init__(self, real_backend: LLMBackend, fixture_path: Path):
        self._real = real_backend
        self._fixture_path = fixture_path
        self._fixture_path.parent.mkdir(parents=True, exist_ok=True)
        self._records: list[dict] = []

    async def complete(self, request: LLMRequest) -> LLMResponse:
        response = await self._real.complete(request)
        record = {
            "id": str(uuid.uuid4()),
            "request": {
                "prompt": request.prompt,
                "model": request.model,
                "temperature": request.temperature,
                "max_tokens": request.max_tokens,
                "system_prompt": request.system_prompt,
                "tools": request.tools,
                "metadata": request.metadata,
            },
            "response": {
                "text": response.text,
                "tool_calls": response.tool_calls,
                "usage": response.usage,
                "metadata": response.metadata,
            },
        }
        self._records.append(record)
        # Append ke file (thread-safe untuk single-process)
        with self._fixture_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        return response

    def finalize(self) -> None:
        pass  # sudah ditulis per-record


class ReplayBackend(LLMBackend):
    """Backend yang memutar fixture JSONL secara deterministik."""

    def __init__(self, fixture_path: Path):
        self._fixture_path = fixture_path
        self._records: list[dict] = []
        self._index = 0
        self._load()

    def _load(self) -> None:
        if not self._fixture_path.exists():
            raise FileNotFoundError("Fixture not found")
        with self._fixture_path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    self._records.append(json.loads(line))

    async def complete(self, request: LLMRequest) -> LLMResponse:
        if self._index >= len(self._records):
            raise IndexError("Fixture exhausted")
        record = self._records[self._index]
        self._index += 1

        # Optional: validasi request cocok (prompt prefix)
        expected_prompt = record["request"]["prompt"]
        if not request.prompt.startswith(expected_prompt[:100]):
            # Warning saja, tidak fail — prompt bisa beda sedikit
            pass

        resp_data = record["response"]
        return LLMResponse(
            text=resp_data["text"],
            tool_calls=resp_data.get("tool_calls", []),
            usage=resp_data.get("usage", {}),
            metadata=resp_data.get("metadata", {}),
        )


class FakeBackend(LLMBackend):
    """Backend fake sederhana tanpa LLM nyata — untuk tes unit cepat."""

    def __init__(self, response_template: str = "Fake response for: {prompt}"):
        self._template = response_template
        self._call_count = 0

    async def complete(self, request: LLMRequest) -> LLMResponse:
        self._call_count += 1
        return LLMResponse(
            text=self._template.format(prompt=request.prompt[:100]),
            usage={"prompt_tokens": 10, "completion_tokens": 20},
            metadata={"fake": True, "call_number": self._call_count},
        )


class DeterministicLLM:
    """Facade tinggi untuk LLM deterministik."""

    def __init__(self, backend: LLMBackend):
        self._backend = backend

    async def complete(
        self,
        prompt: str,
        *,
        model: str = "fake-model",
        temperature: float = 0.0,
        max_tokens: int = 4096,
        system_prompt: str = "",
        tools: list[dict] | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        request = LLMRequest(
            prompt=prompt,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            system_prompt=system_prompt,
            tools=tools or [],
            metadata=kwargs,
        )
        return await self._backend.complete(request)

    # Convenience methods
    async def chat(self, messages: list[dict], **kwargs: Any) -> LLMResponse:
        prompt = "\n".join(f"{m['role']}: {m['content']}" for m in messages)
        return await self.complete(prompt, **kwargs)


# --- Fixture Path Management ---

DEFAULT_FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "llm"


def get_fixture_path(name: str) -> Path:
    return DEFAULT_FIXTURE_DIR / f"{name}.jsonl"


# --- Context Manager untuk Mode RECORD/REPLAY ---

class LLMMode:
    RECORD = "record"
    REPLAY = "replay"
    FAKE = "fake"


@contextmanager
def llm_mode(
    mode: str,
    fixture_name: str = "default",
    *,
    fake_template: str = "Fake: {prompt}",
) -> AsyncGenerator[DeterministicLLM, None]:
    """Context manager untuk set mode LLM global (per-test)."""
    fixture_path = get_fixture_path(fixture_name)

    if mode == LLMMode.RECORD:
        # Butuh real backend — diisi oleh test yang punya API key
        from alfa.llm import get_llm_backend  # type: ignore
        real = get_llm_backend()
        backend = RecordingBackend(real, fixture_path)
    elif mode == LLMMode.REPLAY:
        backend = ReplayBackend(fixture_path)
    elif mode == LLMMode.FAKE:
        backend = FakeBackend(fake_template)
    else:
        raise ValueError("Unknown mode")

    llm = DeterministicLLM(backend)
    try:
        yield llm
    finally:
        if isinstance(backend, RecordingBackend):
            backend.finalize()


# --- Pytest Fixtures ---

@pytest.fixture
def fake_llm() -> DeterministicLLM:
    """Fake LLM default untuk tes unit cepat."""
    return DeterministicLLM(FakeBackend())


@pytest.fixture
def recording_llm(tmp_path: Path) -> AsyncGenerator[DeterministicLLM, None]:
    """LLM recording mode — simpan ke tmp_path."""
    fixture = tmp_path / "llm_record.jsonl"
    from alfa.llm import get_llm_backend  # type: ignore
    real = get_llm_backend()
    backend = RecordingBackend(real, fixture)
    llm = DeterministicLLM(backend)
    try:
        yield llm
    finally:
        backend.finalize()


@pytest.fixture
def replay_llm(fixture_name: str = "default") -> DeterministicLLM:
    """LLM replay mode — baca dari fixtures/llm/{name}.jsonl."""
    return DeterministicLLM(ReplayBackend(get_fixture_path(fixture_name)))


# --- Helper untuk patch module alfa.llm ---

def patch_llm_module(monkeypatch: pytest.MonkeyPatch, llm: DeterministicLLM) -> None:
    """Patch `alfa.llm.get_llm_backend` return DeterministicLLM."""
    import alfa.llm as llm_mod

    class _Wrapper:
        async def complete(self, *a, **kw):
            return await llm.complete(*a, **kw)

        async def chat(self, *a, **kw):
            return await llm.chat(*a, **kw)

    monkeypatch.setattr(llm_mod, "get_llm_backend", lambda: _Wrapper())
