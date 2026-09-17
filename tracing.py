"""
Lightweight structured tracing for ALFA Agent.
No external dependencies. Outputs JSONL to storage/traces/.
"""
import json
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

TRACE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "storage", "traces")
os.makedirs(TRACE_DIR, exist_ok=True)

_write_lock = threading.Lock()


class TraceSpan:
    """
    Represents a single span (unit of work) in a trace.
    Thread-safe. Auto-closes on context manager exit.
    """
    def __init__(self, name: str, trace_id: Optional[str] = None, parent_span_id: Optional[str] = None, tags: Optional[Dict[str, Any]] = None):
        self.span_id = str(uuid.uuid4())[:8]
        self.trace_id = trace_id or str(uuid.uuid4())[:12]
        self.parent_span_id = parent_span_id
        self.name = name
        self.tags = tags or {}
        self.start_time = time.time()
        self.end_time: Optional[float] = None
        self.status = "running"  # running / success / error / timeout
        self.error: Optional[str] = None
        self._written = False

    def finish(self, status: str = "success", error: Optional[str] = None):
        """Close the span and write to JSONL file."""
        if self._written:
            return
        self.end_time = time.time()
        self.status = status
        self.error = error
        self._write()

    def _write(self):
        if self._written:
            return
        self._written = True
        entry = {
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "name": self.name,
            "start_time": self.start_time,
            "end_time": self.end_time or time.time(),
            "duration_ms": round(((self.end_time or time.time()) - self.start_time) * 1000, 1),
            "status": self.status,
            "error": self.error,
            "tags": self.tags,
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        _append_trace(entry)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            self.finish(status="error", error=f"{exc_type.__name__}: {exc_val}")
        elif self.status == "running":
            self.finish(status="success")
        return False


def _get_trace_file() -> str:
    """Return today's trace file path."""
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return os.path.join(TRACE_DIR, f"trace_{date_str}.jsonl")


def _append_trace(entry: Dict[str, Any]):
    """Thread-safe append to today's JSONL trace file."""
    try:
        with _write_lock:
            with open(_get_trace_file(), "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass  # tracing must never crash the main app


def new_span(name: str, trace_id: Optional[str] = None, parent_span_id: Optional[str] = None, **tags) -> TraceSpan:
    """Create a new TraceSpan. Use as context manager or call .finish() manually."""
    return TraceSpan(name=name, trace_id=trace_id, parent_span_id=parent_span_id, tags=tags)


def get_recent_traces(n: int = 100) -> List[Dict[str, Any]]:
    """
    Return the last n trace spans from today's log.
    Used by /api/traces dashboard endpoint.
    """
    path = _get_trace_file()
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        result = []
        for line in lines[-n:]:
            try:
                result.append(json.loads(line))
            except Exception:
                pass
        return list(reversed(result))  # newest first
    except Exception:
        return []


def get_trace_by_id(trace_id: str) -> List[Dict[str, Any]]:
    """Return all spans for a given trace_id from today's log."""
    spans = get_recent_traces(500)
    return [s for s in spans if s.get("trace_id") == trace_id]
