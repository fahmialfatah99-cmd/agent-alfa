"""Unit test propagasi trace OTel-lite (tanpa I/O berat)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from alfa.core import tracing


def test_child_mewarisi_trace_id():
    with tracing.new_span("root") as root:
        child = tracing.child_span("anak")
        assert child.trace_id == root.trace_id
        assert child.parent_span_id == root.span_id
        assert tracing.current_span() is root


def test_konteks_kembali_setelah_span():
    assert tracing.current_span() is None
    with tracing.new_span("a"):
        assert tracing.current_span() is not None
    assert tracing.current_span() is None


def test_traceparent_format_w3c():
    with tracing.new_span("x") as span:
        tp = span.traceparent()
        parts = tp.split("-")
        assert parts[0] == "00" and parts[3] == "01"
        assert len(parts[1]) == 32 and len(parts[2]) == 16
        assert all(c in "0123456789abcdef" for c in parts[1] + parts[2])
