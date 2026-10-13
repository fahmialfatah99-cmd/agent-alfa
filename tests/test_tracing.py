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


def test_otlp_mati_default(monkeypatch):
    from alfa.core import tracing as t

    monkeypatch.delenv("ALFA_OTEL_EXPORT", raising=False)
    assert t._maybe_export_otlp({"trace_id": "a", "span_id": "b"}) is False


def test_otlp_payload_shape():
    from alfa.core import tracing as t

    entry = {
        "trace_id": "abc123",
        "span_id": "s1",
        "name": "uji",
        "start_time": 100.0,
        "end_time": 101.5,
        "status": "success",
        "tags": {"k": "v"},
    }
    p = t._otlp_payload(entry)
    span = p["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
    assert len(span["traceId"]) == 32 and len(span["spanId"]) == 16
    assert span["name"] == "uji"
    assert span["status"] == {"code": 1}


def test_otlp_gagal_tak_pernah_raise(monkeypatch):
    from alfa.core import tracing as t

    monkeypatch.setenv("ALFA_OTEL_EXPORT", "on")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://127.0.0.1:9")
    assert t._maybe_export_otlp({"trace_id": "a", "span_id": "b"}) is False
