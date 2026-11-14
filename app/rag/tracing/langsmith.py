"""
LangSmith tracing for active RAG workflows.

Usage:
    from app.rag.tracing import get_tracing_client, setup_tracing

    setup_tracing()
    with get_tracing_client().trace(name="rag_query") as span:
        span.outputs = {"answer": "Example answer"}
"""

import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.core.config import settings
from app.core.optional_deps import require_dependency
from app.rag.core.logging import get_logger

logger = get_logger("rag.tracing.langsmith")


# Configuration
LANGSMITH_API_KEY = settings.LANGSMITH_API_KEY
LANGSMITH_PROJECT = settings.LANGSMITH_PROJECT
LANGSMITH_ENDPOINT = settings.LANGSMITH_ENDPOINT
LANGSMITH_TRACING_ENABLED = settings.LANGSMITH_TRACING_ENABLED

# Import langsmith if tracing is enabled
LangSmithClient = None  # type: ignore
if LANGSMITH_TRACING_ENABLED:
    langsmith_module = require_dependency("langsmith", feature="langsmith_tracing", pip_name="langsmith")
    LangSmithClient = getattr(langsmith_module, "Client", None)  # type: ignore[assignment]
    if LangSmithClient is None:
        raise RuntimeError("langsmith.Client missing (unsupported langsmith version)")


@dataclass
class SpanContext:
    """Context for a trace span."""

    run_id: str = field(default_factory=lambda: str(uuid4()))
    parent_id: str | None = None
    name: str = ""
    run_type: str = "chain"
    inputs: dict[str, Any] = field(default_factory=dict)
    outputs: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    start_time: float = field(default_factory=time.time)
    end_time: float | None = None
    error: str | None = None

    @property
    def duration_ms(self) -> float | None:
        """Calculate duration in milliseconds."""
        if self.end_time is None:
            return None
        return (self.end_time - self.start_time) * 1000


class TracingClient:
    """
    Client for LangSmith tracing.

    Handles trace collection and submission to LangSmith.
    """

    def __init__(
        self,
        api_key: str | None = None,
        project: str | None = None,
        endpoint: str | None = None,
    ) -> None:
        """
        Initialize the tracing client.

        Args:
            api_key: LangSmith API key
            project: Project name
            endpoint: API endpoint
        """
        self.api_key = api_key or LANGSMITH_API_KEY
        self.project = project or LANGSMITH_PROJECT
        self.endpoint = endpoint or LANGSMITH_ENDPOINT
        self._enabled = bool(self.api_key) and LANGSMITH_TRACING_ENABLED and LangSmithClient is not None
        self._client = None
        self._current_spans: dict[str, SpanContext] = {}

    @property
    def enabled(self) -> bool:
        """Check if tracing is enabled."""
        return self._enabled

    def _get_client(self) -> Any:
        """Get or create LangSmith client."""
        if self._client is not None:
            return self._client

        self._client = LangSmithClient(
            api_key=self.api_key,
            api_url=self.endpoint,
        )
        logger.info("LangSmith client initialized")
        return self._client

    def start_span(
        self,
        name: str,
        run_type: str = "chain",
        inputs: dict[str, Any] | None = None,
        parent_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        tags: list[str] | None = None,
    ) -> SpanContext:
        """
        Start a new trace span.

        Args:
            name: Span name
            run_type: Type of run (chain, llm, retriever, tool)
            inputs: Input data
            parent_id: Parent span ID
            metadata: Additional metadata
            tags: Tags for filtering

        Returns:
            Span context
        """
        span = SpanContext(
            name=name,
            run_type=run_type,
            inputs=inputs or {},
            parent_id=parent_id,
            metadata=metadata or {},
            tags=tags or [],
        )

        self._current_spans[span.run_id] = span

        if self._enabled:
            self._submit_start(span)

        return span

    def end_span(
        self,
        span: SpanContext,
        outputs: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        """
        End a trace span.

        Args:
            span: Span context
            outputs: Output data
            error: Error message if failed
        """
        span.end_time = time.time()
        span.outputs = outputs or {}
        span.error = error

        if self._enabled:
            self._submit_end(span)

        self._current_spans.pop(span.run_id, None)

    def _submit_start(self, span: SpanContext) -> None:
        """Submit span start to LangSmith."""
        try:
            client = self._get_client()
            client.create_run(
                name=span.name,
                run_type=span.run_type,
                inputs=span.inputs,
                id=span.run_id,
                parent_run_id=span.parent_id,
                project_name=self.project,
                tags=span.tags,
                extra={"metadata": span.metadata},
            )
        except Exception as e:
            logger.debug("Failed to submit span start: %s", e)

    def _submit_end(self, span: SpanContext) -> None:
        """Submit span end to LangSmith."""
        try:
            client = self._get_client()
            client.update_run(
                run_id=span.run_id,
                outputs=span.outputs,
                error=span.error,
                end_time=datetime.now(UTC).replace(tzinfo=None),
            )
        except Exception as e:
            logger.debug("Failed to submit span end: %s", e)

    @contextmanager
    def trace(
        self,
        name: str,
        run_type: str = "chain",
        inputs: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        tags: list[str] | None = None,
    ) -> Iterator[SpanContext]:
        """
        Context manager for tracing.

        Args:
            name: Span name
            run_type: Type of run
            inputs: Input data
            metadata: Additional metadata
            tags: Tags for filtering

        Yields:
            Span context
        """
        span = self.start_span(
            name=name,
            run_type=run_type,
            inputs=inputs,
            metadata=metadata,
            tags=tags,
        )

        try:
            yield span
        except Exception as e:
            self.end_span(span, error=str(e))
            raise
        except BaseException:
            # Interruptions release local state without adding telemetry I/O.
            self._current_spans.pop(span.run_id, None)
            raise
        else:
            self.end_span(span, outputs=span.outputs)


# ============================================================================
# Global Client
# ============================================================================


_tracing_client: TracingClient | None = None


def get_tracing_client() -> TracingClient:
    """Get or create the global tracing client."""
    global _tracing_client
    if _tracing_client is None:
        _tracing_client = TracingClient()
    return _tracing_client


def setup_tracing(
    api_key: str | None = None,
    project: str | None = None,
) -> None:
    """
    Setup LangSmith tracing.

    Call this at application startup to configure tracing.

    Args:
        api_key: LangSmith API key
        project: Project name
    """
    global _tracing_client

    # Set environment variables for LangChain auto-tracing
    if api_key:
        os.environ["LANGCHAIN_API_KEY"] = api_key
    elif LANGSMITH_API_KEY:
        os.environ["LANGCHAIN_API_KEY"] = LANGSMITH_API_KEY

    if project:
        os.environ["LANGCHAIN_PROJECT"] = project
    elif LANGSMITH_PROJECT:
        os.environ["LANGCHAIN_PROJECT"] = LANGSMITH_PROJECT

    if LANGSMITH_TRACING_ENABLED:
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        os.environ["LANGCHAIN_ENDPOINT"] = LANGSMITH_ENDPOINT

    _tracing_client = TracingClient(
        api_key=api_key,
        project=project,
    )

    if _tracing_client.enabled:
        logger.info("LangSmith tracing enabled for project: %s", _tracing_client.project)
    else:
        logger.debug("LangSmith tracing not enabled")
