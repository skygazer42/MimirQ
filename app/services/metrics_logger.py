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
import json
from app.rag.core.logging import get_logger
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

_METRICS_SCHEMA_VERSION = 1
_HOSTNAME = socket.gethostname()
logger = get_logger(__name__)

_ctx_request_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("metrics.request_id", default=None)
_ctx_tenant_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("metrics.tenant_id", default=None)
_ctx_conversation_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "metrics.conversation_id", default=None
)
_ctx_account_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("metrics.account_id", default=None)
_ctx_extra: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar("metrics.extra", default=None)


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
                logger.debug("Ignoring non-critical service fallback failure: %s", exc)


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

    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            return model_dump()
        except Exception as exc:
            logger.debug("Ignoring non-critical service fallback failure: %s", exc)

    to_dict = getattr(value, "dict", None)
    if callable(to_dict):
        try:
            return to_dict()
        except Exception as exc:
            logger.debug("Ignoring non-critical service fallback failure: %s", exc)

    return str(value)


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


def _safe_kg_path_provenance(raw: Any) -> dict[str, Any] | None:
    """
    Sanitize shortest-path provenance payloads for JSONL metrics.

    We allow identifiers and low-cardinality fields only. Any raw evidence text is
    stripped to avoid persisting PII or document snippets into the metrics log.
    """
    if not isinstance(raw, dict) or not raw:
        return None

    out: dict[str, Any] = {}
    schema = str(raw.get("schema") or "").strip()
    if schema:
        out["schema"] = schema[:80]
    kind = str(raw.get("kind") or "").strip()
    if kind:
        out["kind"] = kind[:50]
    try:
        if raw.get("hops") is not None:
            out["hops"] = int(raw.get("hops") or 0)
    except Exception as exc:
        logger.debug("Ignoring non-critical service fallback failure: %s", exc)

    nodes_raw = raw.get("nodes")
    if isinstance(nodes_raw, list) and nodes_raw:
        nodes: list[dict[str, Any]] = []
        for n in nodes_raw:
            if not isinstance(n, dict):
                continue
            node: dict[str, Any] = {}
            k = str(n.get("kind") or "").strip()
            if k:
                node["kind"] = k[:30]
            for key in ("entity_id", "type", "event_id", "document_id", "chunk_id"):
                v = n.get(key)
                if v is None:
                    continue
                s = str(v).strip()
                if not s:
                    continue
                node[key] = s[:200]
            if node:
                nodes.append(node)
            if len(nodes) >= 10:
                break
        if nodes:
            out["nodes"] = nodes

    edges_raw = raw.get("edges")
    if isinstance(edges_raw, list) and edges_raw:
        edges: list[dict[str, Any]] = []
        for e in edges_raw:
            if not isinstance(e, dict):
                continue
            edge: dict[str, Any] = {}
            k = str(e.get("kind") or "").strip()
            if k:
                edge["kind"] = k[:30]
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
                v = e.get(key)
                if v is None:
                    continue
                s = str(v).strip()
                if not s:
                    continue
                edge[key] = s[:200]
            if edge:
                edges.append(edge)
            if len(edges) >= 10:
                break
        if edges:
            out["edges"] = edges

    return out or None


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

    question = out.pop("question", None)
    if isinstance(question, str) and question.strip():
        q = question.strip()
        out.setdefault("question_hash", _hash_text(q))
        out.setdefault("question_chars", len(q))

    query = out.pop("query_for_retrieval", None)
    if isinstance(query, str) and query.strip():
        q = query.strip()
        out.setdefault("query_hash", _hash_text(q))
        out.setdefault("query_chars", len(q))

    # Citations can include document snippets; keep only numeric + identifiers.
    citations = out.get("citations")
    if isinstance(citations, list):
        safe: list[dict[str, Any]] = []
        for c in citations:
            if not isinstance(c, dict):
                continue
            item: dict[str, Any] = {}
            for k in _CITATION_SAFE_KEYS:
                if k not in c:
                    continue
                if k == "kg_path_provenance":
                    prov = _safe_kg_path_provenance(c.get(k))
                    if prov:
                        item[k] = prov
                    continue
                item[k] = c.get(k)
            safe.append(item)
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
            logger.debug("Ignoring non-critical service fallback failure: %s", exc)
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


@contextlib.contextmanager
def metrics_span(event: str, **fields: Any):
    """
    Context-manager helper to log elapsed time + success/error for a block.
    """

    start = time.perf_counter()
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
