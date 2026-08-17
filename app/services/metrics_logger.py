"""
JSONL metrics logger.
Features:
- Non-blocking: write in a background thread (bounded queue; drop on overload)
- Enrichment: add timestamps/host/PID/thread + context fields (request_id/tenant_id/...) when available
- Safety: best-effort PII redaction when `settings.PII_REDACTION_ENABLED` is enabled
"""


import atexit
import contextlib
import contextvars
import hashlib
import importlib
import json
import os
import queue
import socket
import threading
import time
from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from app.core.config import settings
from app.core.pii_redaction import redact_obj
from app.rag.core.logging import get_logger

_METRICS_SCHEMA_VERSION = 1
_HOSTNAME = socket.gethostname()
logger = get_logger(__name__)
_SERVICE_FALLBACK_LOG_MESSAGE = "Ignoring non-critical service fallback failure: %s"

_ctx_request_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("metrics.request_id", default=None)
_ctx_tenant_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("metrics.tenant_id", default=None)
_ctx_conversation_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "metrics.conversation_id", default=None
)
_ctx_account_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("metrics.account_id", default=None)
_ctx_extra: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar("metrics.extra", default=None)
_OTEL_API_UNAVAILABLE = object()
_otel_api_cache: tuple[Any, Any, Any] | object | None = None


def _now_ts_ms() -> int:
    return int(time.time() * 1000)


def _ts_ms_to_iso(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, tz=UTC).isoformat()


def get_metrics_context() -> dict[str, Any]:
    ctx: dict[str, Any] = {}
    request_id = _ctx_request_id.get()
    tenant_id = _ctx_tenant_id.get()
    conversation_id = _ctx_conversation_id.get()
    account_id = _ctx_account_id.get()

    if request_id:
        ctx["request_id"] = request_id
    if tenant_id:
        ctx["tenant_id"] = tenant_id
    if conversation_id:
        ctx["conversation_id"] = conversation_id
    if account_id:
        ctx["account_id"] = account_id

    extra = _ctx_extra.get()
    if isinstance(extra, dict):
        for k, v in extra.items():
            if v is None:
                continue
            ctx.setdefault(str(k), v)

    return ctx


def set_metrics_context(
    *,
    request_id: Any | None = None,
    tenant_id: Any | None = None,
    conversation_id: Any | None = None,
    account_id: Any | None = None,
    **extra: Any,
) -> None:
    """
    Set metrics context fields for the current async/task context.

    Prefer `metrics_context(...)` when you need deterministic reset. For request-scoped
    coroutines/tasks, setting without reset is usually fine.
    """

    if request_id is not None:
        _ctx_request_id.set(str(request_id))
    if tenant_id is not None:
        _ctx_tenant_id.set(str(tenant_id))
    if conversation_id is not None:
        _ctx_conversation_id.set(str(conversation_id))
    if account_id is not None:
        _ctx_account_id.set(str(account_id))
    if extra:
        merged = dict(_ctx_extra.get() or {})
        merged.update(extra)
        _ctx_extra.set(merged)


@contextlib.contextmanager
def metrics_context(
    *,
    request_id: Any | None = None,
    tenant_id: Any | None = None,
    conversation_id: Any | None = None,
    account_id: Any | None = None,
    **extra: Any,
):
    """
    Bind contextual fields to all subsequent `log_metrics` calls in the current async/task context.

    Useful to correlate tool/workflow metrics without plumbing request_id everywhere.
    """

    tokens: list[tuple[contextvars.ContextVar[Any], contextvars.Token[Any]]] = []

    def _set(var: contextvars.ContextVar[Any], value: Any) -> None:
        tokens.append((var, var.set(value)))

    if request_id is not None:
        _set(_ctx_request_id, str(request_id))
    if tenant_id is not None:
        _set(_ctx_tenant_id, str(tenant_id))
    if conversation_id is not None:
        _set(_ctx_conversation_id, str(conversation_id))
    if account_id is not None:
        _set(_ctx_account_id, str(account_id))

    if extra:
        merged = dict(_ctx_extra.get() or {})
        merged.update(extra)
        _set(_ctx_extra, merged)

    try:
        yield
    finally:
        for var, token in reversed(tokens):
            try:
                var.reset(token)
            except Exception as exc:
                logger.debug(_SERVICE_FALLBACK_LOG_MESSAGE, exc)


def _json_default(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (UUID, Path)):
        return str(value)
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8", errors="replace")
        except Exception:
            return repr(value)
    if isinstance(value, (set, tuple)):
        return list(value)
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, Exception):
        return str(value)
    for method_name in ("model_dump", "dict"):
        dumped = _maybe_json_dump_via_method(value, method_name)
        if dumped is not None:
            return dumped
    return str(value)


def _maybe_json_dump_via_method(value: Any, method_name: str) -> Any:
    method = getattr(value, method_name, None)
    if not callable(method):
        return None
    try:
        return method()
    except Exception as exc:
        logger.debug(_SERVICE_FALLBACK_LOG_MESSAGE, exc)
        return None



def _maybe_redact(obj: Any) -> Any:
    # Do not silently bypass redaction when enabled. The core helper is dependency-free
    # and fails closed on unexpected errors.
    return redact_obj(obj)


def _hash_text(text: str) -> str:
    """
    Stable short hash for potentially sensitive strings.

    Used when METRICS_LOG_INCLUDE_TEXT=false to keep correlation/debugging possible
    without storing raw content in JSONL logs.
    """
    raw = (text or "").encode("utf-8", "ignore")
    return hashlib.sha256(raw).hexdigest()[:16]


_CITATION_SAFE_KEYS = {
    "chunk_id",
    "document_id",
    "chunk_index",
    "page_number",
    "start_char",
    "end_char",
    "retrieval_role",
    "neighbor_of",
    "doc_pipeline_key",
    "pipeline_hash",
    "relevance_score",
    "vector_score",
    "bm25_score",
    "keyword_score",
    "kg_path",
    "kg_path_provenance",
    "rerank_score",
    "retrieval_score",
    "reranker_provider",
    "rerank_elapsed_sec",
    "rerank_model_used",
    "retrieval_mode",
    "vector_backend",
    "retrieval_elapsed_sec",
    "hit_type",
    "has_image",
}


def _trimmed_metric_text(value: Any, *, max_len: int) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    return text[:max_len]


def _bounded_metric_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except Exception as exc:
        logger.debug(_SERVICE_FALLBACK_LOG_MESSAGE, exc)
        return None


def _sanitize_kg_path_node(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    node: dict[str, Any] = {}
    kind = _trimmed_metric_text(raw.get("kind"), max_len=30)
    if kind:
        node["kind"] = kind
    for key in ("entity_id", "type", "event_id", "document_id", "chunk_id"):
        value = _trimmed_metric_text(raw.get(key), max_len=200)
        if value:
            node[key] = value
    return node or None


def _sanitize_kg_path_edge(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    edge: dict[str, Any] = {}
    kind = _trimmed_metric_text(raw.get("kind"), max_len=30)
    if kind:
        edge["kind"] = kind
    for key in (
        "entity_id",
        "event_id",
        "document_id",
        "chunk_id",
        "relation_id",
        "predicate",
        "confidence_bucket",
        "evidence_source",
    ):
        value = _trimmed_metric_text(raw.get(key), max_len=200)
        if value:
            edge[key] = value
    return edge or None


def _sanitize_kg_path_items(raw_items: Any, *, sanitizer) -> list[dict[str, Any]] | None:
    if not isinstance(raw_items, list) or not raw_items:
        return None
    items: list[dict[str, Any]] = []
    for raw in raw_items:
        item = sanitizer(raw)
        if item:
            items.append(item)
        if len(items) >= 10:
            break
    return items or None


def _safe_kg_path_provenance(raw: Any) -> dict[str, Any] | None:
    """
    Sanitize shortest-path provenance payloads for JSONL metrics.

    We allow identifiers and low-cardinality fields only. Any raw evidence text is
    stripped to avoid persisting PII or document snippets into the metrics log.
    """
    if not isinstance(raw, dict) or not raw:
        return None

    out: dict[str, Any] = {}
    schema = _trimmed_metric_text(raw.get("schema"), max_len=80)
    if schema:
        out["schema"] = schema
    kind = _trimmed_metric_text(raw.get("kind"), max_len=50)
    if kind:
        out["kind"] = kind
    hops = _bounded_metric_int(raw.get("hops"))
    if hops is not None:
        out["hops"] = hops
    nodes = _sanitize_kg_path_items(raw.get("nodes"), sanitizer=_sanitize_kg_path_node)
    if nodes:
        out["nodes"] = nodes
    edges = _sanitize_kg_path_items(raw.get("edges"), sanitizer=_sanitize_kg_path_edge)
    if edges:
        out["edges"] = edges

    return out or None


def _strip_metrics_text_field(out: dict[str, Any], *, source_key: str, hash_key: str, length_key: str) -> None:
    raw = out.pop(source_key, None)
    if not isinstance(raw, str) or not raw.strip():
        return
    text = raw.strip()
    out.setdefault(hash_key, _hash_text(text))
    out.setdefault(length_key, len(text))


def _safe_metric_citation_item(citation: Any) -> dict[str, Any] | None:
    if not isinstance(citation, dict):
        return None
    item: dict[str, Any] = {}
    for key in _CITATION_SAFE_KEYS:
        if key not in citation:
            continue
        if key == "kg_path_provenance":
            provenance = _safe_kg_path_provenance(citation.get(key))
            if provenance:
                item[key] = provenance
            continue
        item[key] = citation.get(key)
    return item


def _strip_text_fields_for_metrics(record: dict[str, Any]) -> dict[str, Any]:
    """
    When enabled, strip raw text fields from metrics records to reduce PII leakage.

    Important: this is separate from PII_REDACTION. Stripping is a stronger guarantee:
    the content is not persisted at all (instead of being best-effort redacted).
    """
    if bool(getattr(settings, "METRICS_LOG_INCLUDE_TEXT", False)):
        return record

    event = str(record.get("event") or "")
    if event != "rag_trace":
        return record

    out = dict(record)
    _strip_metrics_text_field(out, source_key="question", hash_key="question_hash", length_key="question_chars")
    _strip_metrics_text_field(
        out,
        source_key="query_for_retrieval",
        hash_key="query_hash",
        length_key="query_chars",
    )

    # Citations can include document snippets; keep only numeric + identifiers.
    citations = out.get("citations")
    if isinstance(citations, list):
        safe = [item for item in (_safe_metric_citation_item(citation) for citation in citations) if item is not None]
        out["citations"] = safe

    return out


def _build_record(payload: Mapping[str, Any]) -> dict[str, Any]:
    record = dict(payload or {})
    record.setdefault("_v", _METRICS_SCHEMA_VERSION)
    record.setdefault("event", "metric")
    ts_ms = int(record.get("ts_ms") or _now_ts_ms())
    record["ts_ms"] = ts_ms
    record.setdefault("ts", _ts_ms_to_iso(ts_ms))
    record.setdefault("host", _HOSTNAME)
    record.setdefault("pid", os.getpid())
    record.setdefault("thread_id", threading.get_ident())

    ctx = get_metrics_context()
    for k, v in ctx.items():
        record.setdefault(k, v)

    return record


class _MetricsWriter:
    def __init__(self, *, max_queue_size: int = 2000, flush_interval_sec: float = 0.5) -> None:
        self._queue: queue.Queue[Any] = queue.Queue(maxsize=max_queue_size)
        self._flush_interval_sec = float(flush_interval_sec)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="mimirq-metrics-writer", daemon=True)
        self._dropped = 0
        self._started = False
        self._start_lock = threading.Lock()

    def start(self) -> None:
        with self._start_lock:
            if self._started:
                return
            self._thread.start()
            self._started = True
            atexit.register(self.shutdown)

    def emit(self, record: dict[str, Any]) -> None:
        if not self._started:
            self.start()
        try:
            self._queue.put_nowait(record)
        except queue.Full:
            self._dropped += 1

    def shutdown(self) -> None:
        self._stop.set()
        try:
            self._queue.put_nowait(None)
        except Exception as exc:
            logger.debug(_SERVICE_FALLBACK_LOG_MESSAGE, exc)
        if self._thread.is_alive():
            self._thread.join(timeout=2.0)

    def _write_lines(self, lines: list[str]) -> None:
        if not lines:
            return
        path = Path(getattr(settings, "METRICS_LOG_PATH", "./logs/rag_metrics.jsonl") or "./logs/rag_metrics.jsonl")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                for line in lines:
                    f.write(line)
                    f.write("\n")
        except Exception:
            return

    def _run(self) -> None:
        batch: list[dict[str, Any]] = []
        last_flush = time.time()
        while True:
            if self._stop.is_set() and self._queue.empty():
                break

            try:
                item = self._queue.get(timeout=self._flush_interval_sec)
            except queue.Empty:
                item = None

            if item is None:
                now = time.time()
                if batch and (now - last_flush >= self._flush_interval_sec):
                    self._flush(batch)
                    batch = []
                    last_flush = now
                continue

            batch.append(item)
            if len(batch) >= 100:
                self._flush(batch)
                batch = []
                last_flush = time.time()

        if batch:
            self._flush(batch)

    def _flush(self, batch: list[dict[str, Any]]) -> None:
        try:
            to_write: list[str] = []
            dropped = int(self._dropped or 0)
            if dropped:
                self._dropped = 0
                to_write.append(
                    json.dumps(
                        _build_record({"event": "metrics_dropped", "dropped": dropped}),
                        ensure_ascii=False,
                        default=_json_default,
                    )
                )

            for record in batch:
                record = _strip_text_fields_for_metrics(record)
                record = _maybe_redact(record)
                to_write.append(json.dumps(record, ensure_ascii=False, default=_json_default))
            self._write_lines(to_write)
        except Exception:
            return


_writer: _MetricsWriter | None = None
_writer_lock = threading.Lock()


def _get_writer() -> _MetricsWriter:
    global _writer
    if _writer is None:
        with _writer_lock:
            if _writer is None:
                _writer = _MetricsWriter()
    return _writer


def log_metrics(payload: dict[str, Any]) -> None:
    """
    Append a metrics record to JSONL (best-effort).

    This call is safe to use in hot paths: it only enqueues a record when enabled.
    """

    if not bool(getattr(settings, "ENABLE_METRICS_LOG", False)):
        return

    try:
        record = _build_record(payload)
        _get_writer().emit(record)
    except Exception:
        return


def flush_metrics(timeout_sec: float = 1.0) -> None:
    """
    Best-effort flush for buffered metrics.

    Intended for debugging/tests; production code should not rely on synchronous flush.
    """

    writer = _writer
    if writer is None:
        return

    deadline = time.time() + max(0.0, float(timeout_sec))
    while time.time() < deadline:
        try:
            if writer._queue.empty():
                break
        except Exception:
            break
        time.sleep(0.05)


def shutdown_metrics_logger(timeout_sec: float = 2.0) -> None:
    """Best-effort shutdown for the background writer (mainly for tests)."""

    writer = _writer
    if writer is None:
        return
    try:
        writer.shutdown()
    except Exception:
        return
    if timeout_sec > 0:
        flush_metrics(timeout_sec=timeout_sec)


def _resolve_otel_api() -> tuple[Any, Any, Any] | None:
    global _otel_api_cache
    if _otel_api_cache is _OTEL_API_UNAVAILABLE:
        return None
    if _otel_api_cache is None:
        try:
            otel_trace = importlib.import_module("opentelemetry.trace")
            otel_status = importlib.import_module("opentelemetry.trace.status")
            _otel_api_cache = (
                otel_trace,
                otel_status.Status,
                otel_status.StatusCode,
            )
        except Exception:
            _otel_api_cache = _OTEL_API_UNAVAILABLE
            return None
    return _otel_api_cache if isinstance(_otel_api_cache, tuple) else None


def _otel_provider_configured(provider: Any) -> bool:
    module_name = str(getattr(provider.__class__, "__module__", "") or "")
    if not module_name.startswith("opentelemetry.sdk.trace"):
        return False
    return callable(getattr(provider, "get_tracer", None))


def _get_optional_otel_tracer() -> Any | None:
    api = _resolve_otel_api()
    if api is None:
        return None
    otel_trace, _status_cls, _status_code = api
    try:
        provider = otel_trace.get_tracer_provider()
    except Exception as exc:
        logger.debug(_SERVICE_FALLBACK_LOG_MESSAGE, exc)
        return None
    if not _otel_provider_configured(provider):
        return None
    try:
        return provider.get_tracer("app.services.metrics_logger")
    except Exception as exc:
        logger.debug(_SERVICE_FALLBACK_LOG_MESSAGE, exc)
        return None


def _sanitize_otel_attributes(attributes: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(attributes, Mapping):
        return {}
    out: dict[str, Any] = {}
    for raw_key, raw_value in attributes.items():
        key = str(raw_key or "").strip()
        if not key:
            continue
        if isinstance(raw_value, bool):
            out[key] = raw_value
            continue
        if isinstance(raw_value, int) and not isinstance(raw_value, bool):
            out[key] = raw_value
            continue
        if isinstance(raw_value, float):
            out[key] = raw_value
            continue
        if isinstance(raw_value, str):
            out[key] = raw_value[:120]
            continue
    return out


def _start_optional_otel_span(tracer: Any, span_name: str) -> tuple[Any | None, Any | None]:
    try:
        span_cm = tracer.start_as_current_span(str(span_name or "").strip() or "span")
        return span_cm, span_cm.__enter__()
    except Exception as exc:
        logger.debug(_SERVICE_FALLBACK_LOG_MESSAGE, exc)
        return None, None


def _set_optional_span_status(span: Any, status_cls: Any, status_code: Any, *, error: Exception | None = None) -> None:
    if span is None or not getattr(span, "is_recording", lambda: False)():
        return
    if error is not None:
        with contextlib.suppress(Exception):
            span.record_exception(error)
        with contextlib.suppress(Exception):
            span.set_status(status_cls(status_code.ERROR, str(error)[:200]))
        return
    with contextlib.suppress(Exception):
        span.set_status(status_cls(status_code.OK))


def _close_optional_span(span_cm: Any, error: Exception | None) -> None:
    if span_cm is None:
        return
    with contextlib.suppress(Exception):
        if error is None:
            span_cm.__exit__(None, None, None)
        else:
            span_cm.__exit__(type(error), error, error.__traceback__)


@contextlib.contextmanager
def _optional_otel_span(span_name: str, *, attributes: Mapping[str, Any] | None = None):
    tracer = _get_optional_otel_tracer()
    api = _resolve_otel_api()
    if tracer is None or api is None:
        yield None
        return

    _otel_trace, status_cls, status_code = api
    span_cm, span = _start_optional_otel_span(tracer, span_name)
    caught_exc: Exception | None = None

    if span is not None and getattr(span, "is_recording", lambda: False)():
        for key, value in _sanitize_otel_attributes(attributes).items():
            with contextlib.suppress(Exception):
                span.set_attribute(key, value)

    try:
        yield span
    except Exception as exc:  # noqa: BLE001
        caught_exc = exc
        _set_optional_span_status(span, status_cls, status_code, error=exc)
        raise
    else:
        _set_optional_span_status(span, status_cls, status_code)
    finally:
        _close_optional_span(span_cm, caught_exc)


@contextlib.contextmanager
def metrics_span(
    event: str,
    *,
    otel_span_name: str | None = None,
    otel_attributes: Mapping[str, Any] | None = None,
    **fields: Any,
):
    """
    Context-manager helper to log elapsed time + success/error for a block.
    """

    start = time.perf_counter()
    with _optional_otel_span(otel_span_name or event, attributes=otel_attributes):
        try:
            yield
        except Exception as exc:  # noqa: BLE001
            elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
            log_metrics(
                {
                    "event": event,
                    "success": False,
                    "elapsed_ms": elapsed_ms,
                    "error": str(exc)[:200],
                    **fields,
                }
            )
            raise
        else:
            elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
            log_metrics(
                {
                    "event": event,
                    "success": True,
                    "elapsed_ms": elapsed_ms,
                    **fields,
                }
            )
