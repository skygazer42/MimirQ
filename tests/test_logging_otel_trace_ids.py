from __future__ import annotations

import logging

import pytest
from opentelemetry import trace
from opentelemetry.context import attach, detach
from opentelemetry.trace import NonRecordingSpan, SpanContext, TraceFlags

from app.core.logging_config import configure_logging


@pytest.mark.asyncio
async def test_log_records_include_trace_id_and_span_id(caplog):
    # Ensure our record factory is installed.
    configure_logging(log_level="INFO", log_format="plain")

    logger = logging.getLogger("tests.otel")
    caplog.set_level(logging.INFO)

    trace_id = 0x1234
    span_id = 0x5678
    ctx = SpanContext(
        trace_id=trace_id,
        span_id=span_id,
        is_remote=False,
        trace_flags=TraceFlags(1),
        trace_state={},
    )
    span = NonRecordingSpan(ctx)
    token = attach(trace.set_span_in_context(span))
    try:
        logger.info("hello")
    finally:
        detach(token)

    assert caplog.records, "Expected at least one captured log record"
    record = caplog.records[-1]
    assert getattr(record, "trace_id", "") == format(trace_id, "032x")
    assert getattr(record, "span_id", "") == format(span_id, "016x")

